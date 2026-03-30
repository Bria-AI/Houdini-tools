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
    ensure_api_aspect_ratio as _ensure_api_aspect_ratio,
    extract_image_url as _extract_image_url,
    resolve_temp_dir,
    resolve_proxies,
    validate_bria_image_file as _validate_bria_image_file,
)

from bria_core.errors import BriaConfigError, BriaRequestError
from houdini.adapter import expand_from_files
from houdini.cop_export import cop_to_png, export_via_internal_rop
from houdini.node_utils import (
    _safe_exc_str,
    apply_result_to_ui,
    debug_logger,
    opt_parm_bool as _opt_parm_bool,
    opt_parm_int as _opt_parm_int,
    opt_parm_menu_str as _opt_parm_menu_str,
    opt_parm_str as _opt_parm_str,
    resolve_output_dir,
    resolve_result_save_path,
    save_api_metadata,
)
if not hasattr(hou.session, "bria_expand_session"):
    hou.session.bria_expand_session = None


_debug_log = debug_logger("Bria Expand")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

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
        allowed_list = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9"]
        if 0 <= idx < len(allowed_list):
            return allowed_list[idx]
    if "/" in txt:
        parts = txt.split("/", 1)
        txt = f"{parts[0]}:{parts[1]}"
    allowed = {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9"}
    if txt not in allowed:
        raise RuntimeError(
            "aspect_ratio must be one of: 1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9."
        )
    return txt


def _read_input_dimensions(image_path: Optional[str]) -> Optional[tuple]:
    """Read width and height from a PNG file's IHDR chunk."""
    if not image_path or not os.path.exists(image_path):
        return None
    ext = os.path.splitext(image_path)[1].lower()
    try:
        if ext == ".png":
            with open(image_path, "rb") as f:
                sig = f.read(8)
                if sig != b"\x89PNG\r\n\x1a\n":
                    return None
                length = int.from_bytes(f.read(4), "big")
                ctype = f.read(4)
                if ctype != b"IHDR" or length < 8:
                    return None
                ihdr = f.read(length)
                w = int.from_bytes(ihdr[0:4], "big")
                h = int.from_bytes(ihdr[4:8], "big")
                return (w, h)
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def expand_bria(cop_node: hou.Node) -> None:
    t_start_click = time.perf_counter()

    try:
        inputs = cop_node.inputs()
        input_op = inputs[0] if len(inputs) > 0 else None

        temp_dir = resolve_temp_dir(hou)

        run_id = str(int(time.time() * 1000))
        img_path = os.path.join(temp_dir, f"bria_expand_input_{run_id}.png")
        out_path = resolve_output_dir(temp_dir, run_id, "expand")

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
        img_path = _ensure_api_aspect_ratio(img_path)

        t_disk_end = time.perf_counter()
        _debug_log(f"Disk Write Overhead: {(t_disk_end - t_disk_start):.4f} sec")

        # --- Read parameters ---
        prompt = _opt_parm_str(cop_node, "prompt")
        negative_prompt = _opt_parm_str(cop_node, "negative_prompt")
        enable_negative = _opt_parm_bool(cop_node, "enable_negative_prompt")
        if enable_negative is False:
            negative_prompt = None

        expansion_mode = _opt_parm_menu_str(cop_node, "expansion_mode") or "aspect_ratio"
        preserve_alpha = _opt_parm_bool(cop_node, "preserve_alpha")
        seed = _opt_parm_int(cop_node, "seed")
        fast = _opt_parm_bool(cop_node, "fast")
        content_mod_input = _opt_parm_bool(cop_node, "content_moderation_input")
        content_mod_output = _opt_parm_bool(cop_node, "content_moderation_output")
        content_mod_prompt = _opt_parm_bool(cop_node, "content_moderation_prompt")

        # --- Determine sizing based on expansion mode ---
        aspect_ratio = None
        original_image_size = None
        original_image_location = None
        canvas_size = None

        if expansion_mode == "aspect_ratio":
            aspect_ratio = _normalize_aspect_ratio(
                _opt_parm_menu_str(cop_node, "aspect_ratio")
            )
            if not aspect_ratio:
                raise RuntimeError("Select an aspect ratio.")
            _debug_log(f"Aspect ratio mode: {aspect_ratio}")

        elif expansion_mode == "directional":
            # Per-side pixel expansion (Nuke-style)
            expand_left = _opt_parm_int(cop_node, "expand_left") or 0
            expand_right = _opt_parm_int(cop_node, "expand_right") or 0
            expand_top = _opt_parm_int(cop_node, "expand_top") or 0
            expand_bottom = _opt_parm_int(cop_node, "expand_bottom") or 0

            if expand_left + expand_right + expand_top + expand_bottom <= 0:
                raise RuntimeError(
                    "Set at least one expand direction (left/right/top/bottom) to a value > 0."
                )

            dims = _read_input_dimensions(img_path)
            if not dims:
                raise RuntimeError(
                    "Could not read input image dimensions. "
                    "Ensure input is a valid PNG."
                )
            img_w, img_h = dims

            canvas_size = [img_w + expand_left + expand_right,
                           img_h + expand_top + expand_bottom]
            original_image_size = {"width": img_w, "height": img_h}
            original_image_location = {"x": expand_left, "y": expand_top}

            _debug_log(
                f"Directional mode: {img_w}x{img_h} + "
                f"L={expand_left} R={expand_right} T={expand_top} B={expand_bottom} "
                f"-> canvas {canvas_size[0]}x{canvas_size[1]}"
            )

        elif expansion_mode == "canvas_size":
            canvas_width = _opt_parm_int(cop_node, "canvas_width")
            canvas_height = _opt_parm_int(cop_node, "canvas_height")
            anchor = _opt_parm_menu_str(cop_node, "anchor") or "top-left"

            if not canvas_width or not canvas_height or canvas_width <= 0 or canvas_height <= 0:
                raise RuntimeError("Canvas width and height must be > 0.")

            dims = _read_input_dimensions(img_path)
            if not dims:
                raise RuntimeError(
                    "Could not read input image dimensions for canvas mode. "
                    "Ensure input is a valid PNG."
                )
            img_w, img_h = dims

            original_image_size, original_image_location = compute_image_size_location(
                width=img_w,
                height=img_h,
                anchor=anchor if anchor in ("top-left", "center") else "top-left",
                canvas_width=canvas_width,
                canvas_height=canvas_height,
            )
            canvas_size = [canvas_width, canvas_height]

            _debug_log(
                f"Canvas mode: {img_w}x{img_h} -> "
                f"{canvas_width}x{canvas_height} (anchor={anchor})"
            )
        else:
            raise RuntimeError(f"Unknown expansion_mode: {expansion_mode}")

        # --- Connection params ---
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
            msg = "Bria Expand: api_token parm is deprecated. Prefer config/env-based auth."
            _debug_log(msg)
            try:
                hou.ui.setStatusMessage(msg, severity=hou.severityType.Warning)
            except Exception:
                pass
        api_endpoint = _opt_parm_str(cop_node, "api_base_url")

        # --- Call API ---
        data = expand_from_files(
            image_path=img_path,
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            original_image_size=original_image_size,
            original_image_location=original_image_location,
            canvas_size=canvas_size,
            seed=seed,
            negative_prompt=negative_prompt,
            preserve_alpha=preserve_alpha,
            fast=fast,
            content_moderation_input=content_mod_input,
            content_moderation_output=content_mod_output,
            content_moderation_prompt=content_mod_prompt,
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

        save_api_metadata(save_path, data, "expand", {
            "api_time": round(api_time, 4),
            "download_time": round(dl_time, 4),
            "total_time": round(total_time, 4),
        }, request_params={
            "expansion_mode": expansion_mode,
            "prompt": prompt or None,
            "seed": seed,
            "preserve_alpha": preserve_alpha,
        })

        hdefereval.executeDeferred(
            lambda node=cop_node, path=save_path, total=total_time: apply_result_to_ui(
                node,
                path,
                f"Bria Expand Complete ({total:.2f}s) \u2192 {path}",
            )
        )

    except (BriaConfigError, BriaRequestError) as e:
        error_msg = f"Bria Expand Error: {_safe_exc_str(e)}"
        _debug_log(error_msg)
        hdefereval.executeDeferred(
            lambda msg=error_msg: hou.ui.setStatusMessage(msg, severity=hou.severityType.Error)
        )
    except Exception as e:
        error_msg = f"Bria Expand Exception: {_safe_exc_str(e)}"
        _debug_log(error_msg)
        hdefereval.executeDeferred(
            lambda msg=error_msg: hou.ui.setStatusMessage(msg, severity=hou.severityType.Error)
        )


def on_expand(kwargs: dict) -> None:
    node = kwargs.get("node")
    if node is None:
        raise ValueError("Missing kwargs['node']")
    expand_bria(node)
