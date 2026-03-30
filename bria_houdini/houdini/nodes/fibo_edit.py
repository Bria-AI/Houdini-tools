"""Houdini Bria FIBO Edit node logic (thin DCC adapter layer).

This node calls the general Bria Edit endpoint and returns an edited image.
"""

from __future__ import annotations

import os
import time
from typing import Optional

import hou
import hdefereval

from bria_core.errors import BriaConfigError, BriaRequestError
from bria_core.utils import (
    download_url,
    ensure_api_aspect_ratio as _ensure_api_aspect_ratio,
    extract_image_url as _extract_image_url,
    resolve_proxies,
    resolve_temp_dir,
    validate_bria_image_file as _validate_bria_image_file,
)
from houdini.adapter import fibo_edit_from_files
from houdini.cop_export import cop_to_png, export_via_internal_rop
from houdini.vgl_parms import assemble_from_parms
from houdini.node_utils import (
    _safe_exc_str,
    apply_result_to_ui,
    as_hscript_path as _as_hscript_path,
    clamp_steps_num,
    debug_logger,
    opt_parm_bool as _opt_parm_bool,
    opt_parm_int as _opt_parm_int,
    opt_parm_str as _opt_parm_str,
    resolve_output_dir,
    resolve_result_save_path,
    save_api_metadata,
    store_vgl_from_response,
)
if not hasattr(hou.session, "bria_fibo_edit_session"):
    hou.session.bria_fibo_edit_session = None


_debug_log = debug_logger("Bria FIBO Edit")


def _image_path_override(cop_node: hou.Node) -> str | None:
    """Return an explicit image path if the HDA provides one."""

    path = _opt_parm_str(cop_node, "image_path")
    if not path:
        return None
    path = str(path).strip()
    if not path:
        return None
    # Expand variables if user typed $HIP, etc.
    try:
        path = hou.expandString(path)
    except Exception:
        pass
    return path


def _source_preference(cop_node: hou.Node) -> str | None:
    """Best-effort read of a user preference parm.

    Returns:
      - "image_path" to force the `image_path` source
      - "input" to force upstream input/export source
      - None if no recognizable preference parm exists
    """

    if cop_node is None:
        return None

    # Common bool toggles
    for name in (
        "use_image_path",
        "use_imagepath",
        "use_file",
        "prefer_image_path",
        "prefer_file",
        "use_input_image_path",
    ):
        val = _opt_parm_bool(cop_node, name)
        if val is None:
            continue
        return "image_path" if val else "input"

    # Common menu/int toggles
    for name in ("source", "source_mode", "input_source", "source_choice"):
        parm = cop_node.parm(name)
        if parm is None:
            continue
        try:
            v = parm.eval()
        except Exception:
            continue

        # Heuristics:
        # - if it's a string token, look for keywords
        # - if it's an int, assume 0=input, 1=image_path
        if isinstance(v, str):
            s = v.strip().lower()
            if any(k in s for k in ("image_path", "filepath", "file", "path")):
                return "image_path"
            if any(k in s for k in ("input", "upstream", "cop", "wired")):
                return "input"
        else:
            try:
                iv = int(v)
            except Exception:
                continue
            if iv == 1:
                return "image_path"
            if iv == 0:
                return "input"

    return None


def set_image_path(cop_node: hou.Node, image_path: str) -> None:
    """Set `image_path` parm and refresh obvious internal file nodes if present."""

    if cop_node is None:
        return

    parm = cop_node.parm("image_path")
    if parm is not None:
        try:
            parm.set(_as_hscript_path(image_path))
        except Exception:
            pass

    # If the HDA contains a File COP reading this image, try to update it too.
    try:
        # Prefer the explicit internal node name you set up in the HDA.
        explicit = None
        try:
            explicit = cop_node.node("input_image_path")
        except Exception:
            explicit = None
        if explicit is not None and explicit.parm("filename") is not None:
            try:
                explicit.parm("filename").set(_as_hscript_path(image_path))
            except Exception:
                pass
            if explicit.parm("reload") is not None:
                try:
                    explicit.parm("reload").pressButton()
                except Exception:
                    pass
            return

        nodes = []
        try:
            nodes = list(cop_node.allSubChildren())
        except Exception:
            nodes = list(cop_node.children())

        for child in nodes:
            if child is None or child.parm("filename") is None:
                continue
            name_l = child.name().lower()
            if not any(k in name_l for k in ("file", "read", "source", "input", "img")):
                continue

            try:
                child.parm("filename").set(_as_hscript_path(image_path))
            except Exception:
                pass

            if child.parm("reload") is not None:
                try:
                    child.parm("reload").pressButton()
                except Exception:
                    pass
            break
    except Exception:
        pass


def fibo_edit_bria(cop_node: hou.Node) -> None:
    t_start_click = time.perf_counter()

    try:
        # UI naming: keep consistent with other Bria COP nodes.
        # Bria API field names are still `instruction` / `structured_instruction`.
        prompt = (_opt_parm_str(cop_node, "prompt") or "").strip()

        # Priority: VGL structured parms → raw structured_prompt
        structured_prompt = assemble_from_parms(cop_node)
        if not structured_prompt:
            structured_prompt = (_opt_parm_str(cop_node, "structured_prompt") or "").strip()

        # Back-compat for early HDA drafts.
        if not prompt:
            instruction = (_opt_parm_str(cop_node, "instruction") or "").strip()
            if instruction:
                prompt = instruction
        if not structured_prompt:
            structured_instruction = (_opt_parm_str(cop_node, "structured_instruction") or "").strip()
            if structured_instruction:
                structured_prompt = structured_instruction

        # Mode toggles — respect which prompt mode the user selected.
        use_basic = _opt_parm_bool(cop_node, "use_basic_prompt")
        use_struct = _opt_parm_bool(cop_node, "use_structured_prompt")
        enable_negative = _opt_parm_bool(cop_node, "enable_negative_prompt")

        negative_prompt = (_opt_parm_str(cop_node, "negative_prompt") or "").strip()

        if enable_negative is False:
            negative_prompt = ""
        if use_basic is False:
            prompt = ""
        if use_struct is False:
            structured_prompt = ""

        if not prompt and not structured_prompt:
            hou.ui.displayMessage(
                "Provide either Prompt or Structured Prompt (JSON).",
                severity=hou.severityType.Error,
                title="Bria FIBO Edit",
            )
            return

        inputs = cop_node.inputs()
        input_op = inputs[0] if len(inputs) > 0 else None

        temp_dir = resolve_temp_dir(hou)

        run_id = str(int(time.time() * 1000))
        img_path = os.path.join(temp_dir, f"bria_fibo_edit_input_{run_id}.png")
        out_path = resolve_output_dir(temp_dir, run_id, "fibo_edit")

        t_disk_start = time.perf_counter()
        pref = _source_preference(cop_node)
        override_path = _image_path_override(cop_node)

        # Decide source: explicit preference wins, otherwise fall back to "use image_path if set".
        use_image_path = False
        if pref == "image_path":
            use_image_path = True
        elif pref == "input":
            use_image_path = False
        else:
            use_image_path = bool(override_path)

        if use_image_path:
            if not override_path:
                hou.ui.displayMessage(
                    "image_path is selected but empty",
                    severity=hou.severityType.Error,
                    title="Bria FIBO Edit",
                )
                return
            if not os.path.exists(override_path):
                hou.ui.displayMessage(
                    f"image_path does not exist: {override_path}",
                    severity=hou.severityType.Error,
                    title="Bria FIBO Edit",
                )
                return
            img_path = override_path
        else:
            if input_op is None:
                hou.ui.setStatusMessage(
                    "Connect an image to input 1 (or switch to image_path)",
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

        guidance_scale = _opt_parm_int(cop_node, "guidance_scale")
        if guidance_scale is not None and guidance_scale > 0:
            guidance_scale = min(guidance_scale, 5)
        else:
            guidance_scale = None
        seed = _opt_parm_int(cop_node, "seed")
        if seed is not None and seed <= 0:
            seed = None
        steps_num = clamp_steps_num(_opt_parm_int(cop_node, "steps_num"))

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
            msg = "Bria FIBO Edit: api_token parm is deprecated. Prefer config/env-based auth (BRIA_API_KEY_HOUDINI or ~/.bria/bria.json)."
            _debug_log(msg)
            try:
                hou.ui.setStatusMessage(msg, severity=hou.severityType.Warning)
            except Exception:
                pass
        api_endpoint = _opt_parm_str(cop_node, "api_base_url")

        data = fibo_edit_from_files(
            image_path=img_path,
            prompt=prompt or None,
            structured_prompt=structured_prompt or None,
            guidance_scale=guidance_scale,
            negative_prompt=negative_prompt or None,
            seed=seed,
            steps_num=steps_num,
            api_key=api_key,
            api_endpoint=api_endpoint,
            use_bearer=use_bearer_auth,
            proxies=proxies,
            session=hou.session.bria_fibo_edit_session,
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

        _debug_log(f"API Edit Time:    {api_time:.4f} sec")
        _debug_log(f"Image Download:   {dl_time:.4f} sec")
        _debug_log(f"Total Turnaround: {total_time:.4f} sec")
        _debug_log(
            f"Saved result: {save_path} ({os.path.getsize(save_path)} bytes) | content-type={content_type or 'unknown'}"
        )

        save_api_metadata(save_path, data, "fibo_edit", {
            "api_time": round(api_time, 4),
            "download_time": round(dl_time, 4),
            "total_time": round(total_time, 4),
        }, request_params={
            "prompt": prompt or None,
            "structured_prompt": structured_prompt or None,
            "negative_prompt": negative_prompt or None,
            "seed": seed,
            "steps_num": steps_num,
            "guidance_scale": guidance_scale,
        })

        # Store structured_prompt from API response if present (defensive)
        hdefereval.executeDeferred(
            lambda node=cop_node, d=data: store_vgl_from_response(node, d)
        )

        hdefereval.executeDeferred(
            lambda node=cop_node, path=save_path, total=total_time: apply_result_to_ui(
                node,
                path,
                f"Bria FIBO Edit Complete ({total:.2f}s) → {path}",
            )
        )

    except (BriaConfigError, BriaRequestError) as e:
        error_msg = f"Bria FIBO Edit Error: {_safe_exc_str(e)}"
        _debug_log(error_msg)
        hdefereval.executeDeferred(
            lambda msg=error_msg: hou.ui.setStatusMessage(msg, severity=hou.severityType.Error)
        )
    except Exception as e:
        error_msg = f"Bria FIBO Edit Exception: {_safe_exc_str(e)}"
        _debug_log(error_msg)
        hdefereval.executeDeferred(
            lambda msg=error_msg: hou.ui.setStatusMessage(msg, severity=hou.severityType.Error)
        )


def on_fibo_edit(kwargs: dict) -> None:
    node = kwargs.get("node")
    if node is None:
        raise ValueError("Missing kwargs['node']")
    fibo_edit_bria(node)
