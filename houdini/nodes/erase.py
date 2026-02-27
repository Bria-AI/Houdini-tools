"""Houdini Bria Erase node logic (thin DCC adapter layer)."""

from __future__ import annotations

import os
import time
from typing import Dict, Optional

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
from houdini.adapter import erase_from_files
from houdini.cop_export import cop_to_png, export_via_internal_rop
from houdini.node_utils import (
    apply_result_to_ui,
    debug_logger,
    opt_parm_bool as _opt_parm_bool,
    opt_parm_str as _opt_parm_str,
    resolve_result_save_path,
)
if not hasattr(hou.session, "bria_erase_session"):
    hou.session.bria_erase_session = None


_debug_log = debug_logger("Bria Erase")


def erase_bria(cop_node: hou.Node) -> None:
    t_start_click = time.perf_counter()

    try:
        inputs = cop_node.inputs()
        input_op = inputs[0] if len(inputs) > 0 else None
        mask_op = inputs[1] if len(inputs) > 1 else None

        temp_dir = resolve_temp_dir(hou)

        run_id = str(int(time.time() * 1000))
        img_path = os.path.join(temp_dir, f"bria_erase_input_{run_id}.png")
        mask_path = os.path.join(temp_dir, f"bria_erase_mask_{run_id}.png")
        out_path = os.path.join(temp_dir, f"bria_erase_result_{run_id}.png")

        t_disk_start = time.perf_counter()
        if input_op is None or mask_op is None:
            hou.ui.setStatusMessage(
                "Connect image to input 1 and mask to input 2",
                severity=hou.severityType.Error,
            )
            return
        img_path = (
            export_via_internal_rop(cop_node, "rop_save_input", img_path)
            or cop_to_png(input_op, img_path)
        )
        mask_path = (
            export_via_internal_rop(cop_node, "rop_save_mask", mask_path)
            or cop_to_png(mask_op, mask_path)
        )

        _validate_bria_image_file(img_path, "Input image")
        _validate_bria_image_file(mask_path, "Mask")

        t_disk_end = time.perf_counter()
        _debug_log(f"Disk Write Overhead: {(t_disk_end - t_disk_start):.4f} sec")

        use_bearer_auth = bool(_opt_parm_bool(cop_node, "use_bearer_auth"))
        allow_multipart = bool(_opt_parm_bool(cop_node, "allow_multipart_fallback"))

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
            msg = "Bria Erase: api_token parm is deprecated. Prefer config/env-based auth (BRIA_API_KEY_HOUDINI or ~/.bria/bria.json)."
            _debug_log(msg)
            try:
                hou.ui.setStatusMessage(msg, severity=hou.severityType.Warning)
            except Exception:
                pass
        api_endpoint = _opt_parm_str(cop_node, "api_base_url")

        data = erase_from_files(
            image_path=img_path,
            mask_path=mask_path,
            preserve_alpha=bool(cop_node.evalParm("preserve_alpha")),
            api_key=api_key,
            api_endpoint=api_endpoint,
            use_bearer=use_bearer_auth,
            allow_multipart_fallback=allow_multipart,
            proxies=proxies,
            session=hou.session.bria_erase_session,
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

        _debug_log(f"API Erase Time:   {api_time:.4f} sec")
        _debug_log(f"Image Download:   {dl_time:.4f} sec")
        _debug_log(f"Total Turnaround: {total_time:.4f} sec")
        _debug_log(f"Saved result: {save_path} ({os.path.getsize(save_path)} bytes) | content-type={content_type or 'unknown'}")

        hdefereval.executeDeferred(
            lambda node=cop_node, path=save_path, total=total_time: apply_result_to_ui(
                node,
                path,
                f"Bria Erase Complete ({total:.2f}s) → {path}",
            )
        )

    except (BriaConfigError, BriaRequestError) as e:
        error_msg = f"Bria Erase Error: {e}"
        _debug_log(error_msg)
        hdefereval.executeDeferred(
            lambda msg=error_msg: hou.ui.setStatusMessage(msg, severity=hou.severityType.Error)
        )
    except Exception as e:
        error_msg = f"Bria Erase Exception: {e}"
        _debug_log(error_msg)
        hdefereval.executeDeferred(
            lambda msg=error_msg: hou.ui.setStatusMessage(msg, severity=hou.severityType.Error)
        )


def on_erase(kwargs: dict) -> None:
    node = kwargs.get("node")
    if node is None:
        raise ValueError("Missing kwargs['node']")
    erase_bria(node)
