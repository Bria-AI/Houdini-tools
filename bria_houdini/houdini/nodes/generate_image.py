"""Houdini Bria Generate Image node logic (thin DCC adapter layer).

Takes a structured prompt JSON (from Generate Structured Prompt node)
or a plain text prompt and generates an image via Bria FIBO.
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

import hou
import hdefereval
from bria_core.utils import (
    download_url,
    extract_image_url as _extract_image_url,
    resolve_proxies,
    resolve_temp_dir,
)

from bria_core.errors import BriaConfigError, BriaRequestError
from houdini.adapter import fibo_generate_from_payload
from houdini.vgl_parms import assemble_from_parms
from houdini.node_utils import (
    apply_result_to_ui,
    clamp_steps_num,
    debug_logger,
    opt_parm_bool as _opt_parm_bool,
    opt_parm_float as _opt_parm_float,
    opt_parm_int as _opt_parm_int,
    opt_parm_menu_str as _opt_parm_menu_str,
    opt_parm_str as _opt_parm_str,
    resolve_output_dir,
    resolve_result_save_path,
    save_api_metadata,
)
if not hasattr(hou.session, "bria_generate_image_session"):
    hou.session.bria_generate_image_session = None


_debug_log = debug_logger("Bria Generate Image")

_ALLOWED_ASPECT_RATIOS = {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9"}


def _normalize_aspect_ratio(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    txt = value.strip().lower().replace(" ", "")
    if not txt:
        return None
    if txt.isdigit():
        idx = int(txt)
        allowed_list = sorted(_ALLOWED_ASPECT_RATIOS)
        if 0 <= idx < len(allowed_list):
            return allowed_list[idx]
    if "/" in txt:
        parts = txt.split("/", 1)
        txt = f"{parts[0]}:{parts[1]}"
    if txt not in _ALLOWED_ASPECT_RATIOS:
        raise RuntimeError(
            f"aspect_ratio must be one of: {', '.join(sorted(_ALLOWED_ASPECT_RATIOS))}."
        )
    return txt


def _parse_structured_prompt(raw: Optional[str]) -> Optional[str]:
    """Validate structured prompt is valid JSON and return as string.

    The Bria API expects structured_prompt as a JSON *string*, not a parsed object.
    """
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        json.loads(raw)  # validate only
        return raw
    except Exception as exc:
        raise RuntimeError(f"structured_prompt must be valid JSON: {exc}")


def generate_image_bria(cop_node: hou.Node) -> None:
    t_start_click = time.perf_counter()

    try:
        temp_dir = resolve_temp_dir(hou)

        run_id = str(int(time.time() * 1000))
        out_path = resolve_output_dir(temp_dir, run_id, "generate_image")

        # Priority: VGL structured parms → raw structured_prompt → text prompt
        structured_prompt = assemble_from_parms(cop_node)
        if not structured_prompt:
            structured_prompt_raw = _opt_parm_str(cop_node, "structured_prompt")
            structured_prompt = _parse_structured_prompt(structured_prompt_raw)

        prompt = _opt_parm_str(cop_node, "prompt")
        negative_prompt = _opt_parm_str(cop_node, "negative_prompt")

        # Respect mode toggles — clear whichever mode the user disabled
        use_basic = _opt_parm_bool(cop_node, "use_basic_prompt")
        use_struct = _opt_parm_bool(cop_node, "use_structured_prompt")
        if use_basic is False:
            prompt = ""
        if use_struct is False:
            structured_prompt = ""

        if not structured_prompt and not prompt:
            hou.ui.displayMessage(
                "Provide a structured prompt (from Generate Structured Prompt node) "
                "or a text prompt.",
                severity=hou.severityType.Error,
                title="Bria FIBO Generate",
            )
            return

        aspect_ratio = _normalize_aspect_ratio(_opt_parm_menu_str(cop_node, "aspect_ratio"))

        seed = _opt_parm_int(cop_node, "seed")
        guidance_scale = _opt_parm_int(cop_node, "guidance_scale")
        steps_num = clamp_steps_num(_opt_parm_int(cop_node, "steps_num"))
        sync = _opt_parm_bool(cop_node, "sync")

        pipeline = _opt_parm_menu_str(cop_node, "pipeline") or "standard"
        use_structured = bool(structured_prompt)

        payload: dict = {}
        if structured_prompt:
            # Structured prompt takes priority — don't send text prompt
            # so the API uses the structured prompt for generation.
            payload["structured_prompt"] = structured_prompt
            _debug_log(f"Structured prompt payload (first 200 chars): {structured_prompt[:200]}")
        elif prompt:
            payload["prompt"] = prompt
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        if seed is not None and seed > 0:
            payload["seed"] = seed
        if guidance_scale is not None and guidance_scale > 0:
            payload["guidance_scale"] = min(guidance_scale, 5)
        if steps_num is not None:
            payload["steps_num"] = steps_num
        if sync is not None:
            payload["sync"] = bool(sync)

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
            msg = "Bria Generate Image: api_token parm is deprecated. Prefer config/env-based auth."
            _debug_log(msg)
            try:
                hou.ui.setStatusMessage(msg, severity=hou.severityType.Warning)
            except Exception:
                pass
        api_endpoint = _opt_parm_str(cop_node, "api_base_url")

        source = "structured_prompt" if use_structured else "text_prompt"
        _debug_log(f"Generating image from {source} (pipeline={pipeline})")

        data = fibo_generate_from_payload(
            payload=payload,
            pipeline=pipeline,
            use_structured_prompt=use_structured,
            api_key=api_key,
            api_endpoint=api_endpoint,
            use_bearer=use_bearer_auth,
            proxies=proxies,
            session=hou.session.bria_generate_image_session,
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
        api_time = t_dl_start - t_start_click
        dl_time = t_dl_end - t_dl_start

        _debug_log(f"API Generate Time: {api_time:.4f} sec")
        _debug_log(f"Image Download:    {dl_time:.4f} sec")
        _debug_log(f"Total Turnaround:  {total_time:.4f} sec")
        _debug_log(
            f"Saved result: {save_path} ({os.path.getsize(save_path)} bytes) | content-type={content_type or 'unknown'}"
        )

        save_api_metadata(save_path, data, "generate_image", {
            "api_time": round(api_time, 4),
            "download_time": round(dl_time, 4),
            "total_time": round(total_time, 4),
            "source": source,
        }, request_params={
            "prompt": prompt or None,
            "structured_prompt": structured_prompt or None,
            "negative_prompt": negative_prompt or None,
            "seed": seed,
            "steps_num": steps_num,
        })

        hdefereval.executeDeferred(
            lambda node=cop_node, path=save_path, total=total_time: apply_result_to_ui(
                node,
                path,
                f"Bria Generate Image Complete ({total:.2f}s) \u2192 {path}",
            )
        )

    except (BriaConfigError, BriaRequestError) as e:
        error_msg = f"Bria Generate Image Error: {e}"
        _debug_log(error_msg)
        hdefereval.executeDeferred(
            lambda msg=error_msg: hou.ui.setStatusMessage(msg, severity=hou.severityType.Error)
        )
    except Exception as e:
        error_msg = f"Bria Generate Image Exception: {e}"
        _debug_log(error_msg)
        hdefereval.executeDeferred(
            lambda msg=error_msg: hou.ui.setStatusMessage(msg, severity=hou.severityType.Error)
        )


def on_generate_image(kwargs: dict) -> None:
    node = kwargs.get("node")
    if node is None:
        raise ValueError("Missing kwargs['node']")
    generate_image_bria(node)
