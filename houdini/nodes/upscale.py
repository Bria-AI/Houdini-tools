"""Houdini Bria Upscale node logic (thin DCC adapter layer)."""

from __future__ import annotations

import os
import time
from typing import Optional

import hou
import hdefereval
from bria_core.utils import (
    download_url,
    extract_image_url as _extract_image_url,
    resolve_temp_dir,
    resolve_proxies,
    validate_bria_image_file as _validate_bria_image_file,
)

from bria_core.errors import BriaConfigError, BriaRequestError
from houdini.adapter import upscale_from_files
from houdini.cop_export import cop_to_png, export_via_internal_rop
from houdini.node_utils import (
    apply_result_to_ui,
    debug_logger,
    opt_parm_bool as _opt_parm_bool,
    opt_parm_int as _opt_parm_int,
    opt_parm_str as _opt_parm_str,
    resolve_result_save_path,
)
if not hasattr(hou.session, "bria_upscale_session"):
    hou.session.bria_upscale_session = None


_debug_log = debug_logger("Bria Upscale")


def _build_payload_preview(
    mode: str,
    desired_increase: Optional[int],
    resolution: Optional[str],
    preserve_alpha: Optional[bool],
    content_moderation: Optional[bool],
    use_cache: Optional[bool],
    output_color_space: Optional[str],
) -> dict:
    payload: dict = {
        "image": "<base64 omitted>",
        "sync": True,
    }
    if preserve_alpha is not None:
        payload["preserve_alpha"] = bool(preserve_alpha)
    if content_moderation is not None:
        payload["content_moderation"] = bool(content_moderation)
    if use_cache is not None:
        payload["use_cache"] = bool(use_cache)
    if output_color_space:
        payload["output_color_space"] = str(output_color_space)

    if mode == "increase_resolution":
        if desired_increase is not None:
            payload["desired_increase"] = int(desired_increase)
    else:
        if resolution:
            payload["resolution"] = str(resolution)

    return payload


def _normalize_mode(mode: str | None) -> str:
    mode_l = (mode or "").strip().lower()
    if mode_l in ("increase", "increase_resolution", "upscale", "upscale_only"):
        return "increase_resolution"
    if mode_l in ("enhance", "enhance_image", "enhance_upscale"):
        return "enhance"
    return "increase_resolution"


def upscale_bria(cop_node: hou.Node) -> None:
    t_start_click = time.perf_counter()

    try:
        inputs = cop_node.inputs()
        input_op = inputs[0] if len(inputs) > 0 else None

        temp_dir = resolve_temp_dir(hou)

        run_id = str(int(time.time() * 1000))
        img_path = os.path.join(temp_dir, f"bria_upscale_input_{run_id}.png")
        out_path = os.path.join(temp_dir, f"bria_upscale_result_{run_id}.png")

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

        mode = _normalize_mode(_opt_parm_str(cop_node, "mode"))

        desired_increase: Optional[int] = None
        resolution: Optional[str] = None

        if mode == "increase_resolution":
            desired_increase = _opt_parm_int(cop_node, "desired_increase")
            if desired_increase is None:
                raw = _opt_parm_str(cop_node, "desired_increase")
                if raw:
                    raw_l = raw.strip().lower().replace("x", "")
                    try:
                        desired_increase = int(raw_l)
                    except Exception:
                        raise RuntimeError("desired_increase must be an integer (2 or 4).")
            if desired_increase in (0, 1):
                desired_increase = 2 if desired_increase == 0 else 4
            if desired_increase is None:
                desired_increase = 2
            if desired_increase not in (2, 4):
                raise RuntimeError("desired_increase must be 2 or 4.")
        else:
            resolution = _opt_parm_str(cop_node, "resolution") or ""
            if resolution not in ("1MP", "2MP", "4MP"):
                raise RuntimeError("resolution must be one of: 1MP, 2MP, 4MP.")

        preserve_alpha = _opt_parm_bool(cop_node, "preserve_alpha")
        content_moderation = _opt_parm_bool(cop_node, "content_moderation")
        use_cache = _opt_parm_bool(cop_node, "use_cache")
        output_color_space = _opt_parm_str(cop_node, "output_color_space")

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
            msg = "Bria Upscale: api_token parm is deprecated. Prefer config/env-based auth (BRIA_API_KEY_HOUDINI or ~/.bria/bria.json)."
            _debug_log(msg)
            try:
                hou.ui.setStatusMessage(msg, severity=hou.severityType.Warning)
            except Exception:
                pass
        api_endpoint = _opt_parm_str(cop_node, "api_base_url")

        payload_preview = _build_payload_preview(
            mode=mode,
            desired_increase=desired_increase,
            resolution=resolution,
            preserve_alpha=preserve_alpha,
            content_moderation=content_moderation,
            use_cache=use_cache,
            output_color_space=output_color_space,
        )
        _debug_log(f"Payload preview: {payload_preview}")

        data = upscale_from_files(
            image_path=img_path,
            mode=mode,
            desired_increase=desired_increase,
            resolution=resolution,
            preserve_alpha=preserve_alpha,
            content_moderation=content_moderation,
            use_cache=use_cache,
            output_color_space=output_color_space,
            api_key=api_key,
            api_endpoint=api_endpoint,
            use_bearer=use_bearer_auth,
            proxies=proxies,
            session=hou.session.bria_upscale_session,
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

        _debug_log(f"API Upscale Time: {api_time:.4f} sec")
        _debug_log(f"Image Download:   {dl_time:.4f} sec")
        _debug_log(f"Total Turnaround: {total_time:.4f} sec")
        _debug_log(
            f"Saved result: {save_path} ({os.path.getsize(save_path)} bytes) | content-type={content_type or 'unknown'}"
        )

        hdefereval.executeDeferred(
            lambda node=cop_node, path=save_path, total=total_time: apply_result_to_ui(
                node,
                path,
                f"Bria Upscale Complete ({total:.2f}s) → {path}",
            )
        )

    except (BriaConfigError, BriaRequestError) as e:
        error_msg = f"Bria Upscale Error: {e}"
        _debug_log(error_msg)
        hdefereval.executeDeferred(
            lambda msg=error_msg: hou.ui.setStatusMessage(msg, severity=hou.severityType.Error)
        )
    except Exception as e:
        error_msg = f"Bria Upscale Exception: {e}"
        _debug_log(error_msg)
        hdefereval.executeDeferred(
            lambda msg=error_msg: hou.ui.setStatusMessage(msg, severity=hou.severityType.Error)
        )


def on_upscale(kwargs: dict) -> None:
    node = kwargs.get("node")
    if node is None:
        raise ValueError("Missing kwargs['node']")
    upscale_bria(node)
