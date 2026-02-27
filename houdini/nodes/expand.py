"""Houdini Bria Expand (outpainting) node logic (thin DCC adapter layer)."""

from __future__ import annotations

import os
import re
import time
from typing import Optional

import hou
import hdefereval
from bria_core.utils import (
    compute_image_size_location,
    download_url,
    extract_image_url as _extract_image_url,
    resolve_temp_dir,
    resolve_proxies,
    validate_bria_image_file as _validate_bria_image_file,
)

from bria_core.errors import BriaConfigError, BriaRequestError
from houdini.adapter import expand_from_files
from houdini.cop_export import cop_to_png, export_via_internal_rop
from houdini.node_utils import (
    apply_result_to_ui,
    debug_logger,
    opt_parm_bool as _opt_parm_bool,
    opt_parm_menu_str as _opt_parm_menu_str,
    opt_parm_str as _opt_parm_str,
    resolve_result_save_path,
)
if not hasattr(hou.session, "bria_expand_session"):
    hou.session.bria_expand_session = None


_debug_log = debug_logger("Bria Expand")


def _parse_size(value: Optional[str]) -> Optional[dict]:
    if not value:
        return None
    txt = value.strip().lower().replace("x", ",")
    parts = [p.strip() for p in re.split(r"[,\s]+", txt) if p.strip()]
    if len(parts) != 2:
        raise RuntimeError("original_image_size must be 'W,H' or 'W x H'.")
    try:
        w = int(parts[0])
        h = int(parts[1])
    except Exception:
        raise RuntimeError("original_image_size must contain integers.")
    return {"width": w, "height": h}


def _parse_location(value: Optional[str]) -> Optional[dict]:
    if not value:
        return None
    txt = value.strip().lower().replace("x", ",")
    parts = [p.strip() for p in re.split(r"[,\s]+", txt) if p.strip()]
    if len(parts) != 2:
        raise RuntimeError("original_image_location must be 'X,Y'.")
    try:
        x = int(parts[0])
        y = int(parts[1])
    except Exception:
        raise RuntimeError("original_image_location must contain integers.")
    return {"x": x, "y": y}


def _normalize_aspect_ratio(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    txt = value.strip().lower().replace(" ", "")
    if not txt:
        return None
    if txt.isdigit():
        idx = int(txt)
        allowed_list = ["1:1", "4:3", "16:9", "3:2", "2:3", "9:16", "3:4", "4:5", "5:4"]
        if 0 <= idx < len(allowed_list):
            return allowed_list[idx]
    if "/" in txt:
        parts = txt.split("/", 1)
        txt = f"{parts[0]}:{parts[1]}"
    allowed = {"1:1", "4:3", "16:9", "3:2", "2:3", "9:16", "3:4", "4:5", "5:4"}
    if txt not in allowed:
        raise RuntimeError(
            "aspect_ratio must be one of: 1:1, 4:3, 16:9, 3:2, 2:3, 9:16, 3:4, 4:5, 5:4."
        )
    return txt


def _compute_input_size_location_from_file(image_path: Optional[str]) -> tuple[Optional[dict], Optional[dict]]:
    if not image_path or not os.path.exists(image_path):
        return None, None

    ext = os.path.splitext(image_path)[1].lower()
    try:
        if ext == ".png":
            with open(image_path, "rb") as f:
                sig = f.read(8)
                if sig != b"\x89PNG\r\n\x1a\n":
                    return None, None
                length = int.from_bytes(f.read(4), "big")
                ctype = f.read(4)
                if ctype != b"IHDR" or length < 8:
                    return None, None
                ihdr = f.read(length)
                w = int.from_bytes(ihdr[0:4], "big")
                h = int.from_bytes(ihdr[4:8], "big")
        else:
            return None, None
        return compute_image_size_location(w, h, anchor="top-left")
    except Exception:
        return None, None


def expand_bria(cop_node: hou.Node) -> None:
    t_start_click = time.perf_counter()

    try:
        inputs = cop_node.inputs()
        input_op = inputs[0] if len(inputs) > 0 else None

        temp_dir = resolve_temp_dir(hou)

        run_id = str(int(time.time() * 1000))
        img_path = os.path.join(temp_dir, f"bria_expand_input_{run_id}.png")
        out_path = os.path.join(temp_dir, f"bria_expand_result_{run_id}.png")

        t_disk_start = time.perf_counter()
        if input_op is None:
            hou.ui.setStatusMessage(
                "Connect image to input 1",
                severity=hou.severityType.Error,
            )
            return
        img_path = (
            export_via_internal_rop(cop_node, "rop_save_input", img_path)
            or cop_to_png(input_op, img_path)
        )

        _validate_bria_image_file(img_path, "Input image")

        t_disk_end = time.perf_counter()
        _debug_log(f"Disk Write Overhead: {(t_disk_end - t_disk_start):.4f} sec")

        prompt = _opt_parm_str(cop_node, "prompt")
        aspect_ratio = _normalize_aspect_ratio(_opt_parm_menu_str(cop_node, "aspect_ratio"))
        size_str = _opt_parm_str(cop_node, "original_image_size")
        loc_str = _opt_parm_str(cop_node, "original_image_location")

        original_image_size = _parse_size(size_str)
        original_image_location = _parse_location(loc_str)

        if not aspect_ratio:
            if not (original_image_size and original_image_location):
                auto_size, auto_loc = _compute_input_size_location_from_file(img_path)
                original_image_size = original_image_size or auto_size
                original_image_location = original_image_location or auto_loc

            if not (original_image_size and original_image_location):
                raise RuntimeError(
                    "Provide aspect_ratio or both original_image_size and original_image_location."
                )
        else:
            original_image_size = None
            original_image_location = None

        use_bearer_auth = bool(_opt_parm_bool(cop_node, "use_bearer_auth"))

        use_env_proxy = _opt_parm_bool(cop_node, "use_env_proxy")

        http_proxy = _opt_parm_str(cop_node, "http_proxy")
        https_proxy = _opt_parm_str(cop_node, "https_proxy")
        proxies = resolve_proxies(
            http_proxy=http_proxy,
            https_proxy=https_proxy,
            use_env_proxy=use_env_proxy,
        )

        api_key = _opt_parm_str(cop_node, "api_token")
        if api_key:
            msg = "Bria Expand: api_token parm is deprecated. Prefer config/env-based auth (BRIA_API_KEY_HOUDINI or ~/.bria/bria.json)."
            _debug_log(msg)
            try:
                hou.ui.setStatusMessage(msg, severity=hou.severityType.Warning)
            except Exception:
                pass
        api_endpoint = _opt_parm_str(cop_node, "api_base_url")

        data = expand_from_files(
            image_path=img_path,
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            original_image_size=original_image_size,
            original_image_location=original_image_location,
            api_key=api_key,
            api_endpoint=api_endpoint,
            use_bearer=use_bearer_auth,
            proxies=proxies,
            session=hou.session.bria_expand_session,
        )

        dl_url = _extract_image_url(data)
        if not dl_url:
            raise BriaRequestError(f"Unexpected API response (no image_url): {data}")

        t_dl_start = time.perf_counter()
        img_bytes, content_type = download_url(dl_url, timeout_s=300, proxies=proxies)
        t_dl_end = time.perf_counter()

        save_path = resolve_result_save_path(out_path, content_type)

        with open(save_path, "wb") as f:
            f.write(img_bytes)

        if not os.path.exists(save_path) or os.path.getsize(save_path) <= 0:
            raise RuntimeError(f"Bria download produced an empty file: {save_path}")

        t_final = time.perf_counter()
        total_time = t_final - t_start_click
        api_time = t_dl_start - t_disk_end
        dl_time = t_dl_end - t_dl_start

        _debug_log(f"API Expand Time:   {api_time:.4f} sec")
        _debug_log(f"Image Download:    {dl_time:.4f} sec")
        _debug_log(f"Total Turnaround:  {total_time:.4f} sec")
        _debug_log(
            f"Saved result: {save_path} ({os.path.getsize(save_path)} bytes) | content-type={content_type or 'unknown'}"
        )

        hdefereval.executeDeferred(
            lambda node=cop_node, path=save_path, total=total_time: apply_result_to_ui(
                node,
                path,
                f"Bria Expand Complete ({total:.2f}s) → {path}",
            )
        )

    except (BriaConfigError, BriaRequestError) as e:
        error_msg = f"Bria Expand Error: {e}"
        _debug_log(error_msg)
        hdefereval.executeDeferred(
            lambda msg=error_msg: hou.ui.setStatusMessage(msg, severity=hou.severityType.Error)
        )
    except Exception as e:
        error_msg = f"Bria Expand Exception: {e}"
        _debug_log(error_msg)
        hdefereval.executeDeferred(
            lambda msg=error_msg: hou.ui.setStatusMessage(msg, severity=hou.severityType.Error)
        )


def on_expand(kwargs: dict) -> None:
    node = kwargs.get("node")
    if node is None:
        raise ValueError("Missing kwargs['node']")
    expand_bria(node)
