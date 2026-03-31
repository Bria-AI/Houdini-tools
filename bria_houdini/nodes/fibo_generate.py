"""Houdini Bria FIBO Generate node logic (thin DCC adapter layer)."""

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
from bria_houdini.adapter import fibo_generate_from_payload
from bria_houdini.node_utils import (
    _safe_exc_str,
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
    store_vgl_from_response,
)
if not hasattr(hou.session, "bria_fibo_generate_session"):
    hou.session.bria_fibo_generate_session = None


_debug_log = debug_logger("Bria FIBO")


def _parse_structured_prompt(raw: Optional[str]) -> Optional[str]:
    """Validate structured prompt is valid JSON and return as string.

    The Bria API expects structured_prompt as a JSON *string*, not a parsed object.
    """
    if not raw:
        return None
    raw = raw.strip() if isinstance(raw, str) else raw
    if not raw:
        return None
    try:
        json.loads(raw)  # validate only
        return raw
    except Exception as exc:
        raise RuntimeError(f"structured_prompt must be valid JSON: {exc}")


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


def fibo_generate_bria(cop_node: hou.Node) -> None:
    t_start_click = time.perf_counter()

    try:
        temp_dir = resolve_temp_dir(hou)

        run_id = str(int(time.time() * 1000))
        out_path = resolve_output_dir(temp_dir, run_id, "fibo_generate")

        prompt = _opt_parm_str(cop_node, "prompt")
        negative_prompt = _opt_parm_str(cop_node, "negative_prompt")
        structured_prompt_raw = _opt_parm_str(cop_node, "structured_prompt")
        structured_prompt = _parse_structured_prompt(structured_prompt_raw)

        aspect_ratio = _normalize_aspect_ratio(_opt_parm_menu_str(cop_node, "aspect_ratio"))
        tailored_model_id = _opt_parm_str(cop_node, "tailored_model_id")

        seed = _opt_parm_int(cop_node, "seed")
        guidance_scale = _opt_parm_int(cop_node, "guidance_scale")
        steps_num = clamp_steps_num(_opt_parm_int(cop_node, "steps_num"))
        tailored_model_influence = _opt_parm_float(cop_node, "tailored_model_influence")
        sync = _opt_parm_bool(cop_node, "sync")

        pipeline = _opt_parm_menu_str(cop_node, "pipeline") or "standard"
        use_structured = bool(structured_prompt)

        payload: dict = {}
        if prompt:
            payload["prompt"] = prompt
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if structured_prompt:
            payload["structured_prompt"] = structured_prompt
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        if seed is not None and seed > 0:
            payload["seed"] = seed
        if guidance_scale is not None and guidance_scale > 0:
            payload["guidance_scale"] = min(guidance_scale, 5)
        if steps_num is not None:
            payload["steps_num"] = steps_num
        if tailored_model_influence is not None:
            payload["tailored_model_influence"] = tailored_model_influence
        if sync is not None:
            payload["sync"] = bool(sync)

        if pipeline.strip().lower() == "tailored":
            if not tailored_model_id:
                raise RuntimeError("tailored_model_id is required for tailored FIBO generation.")
            payload["tailored_model_id"] = tailored_model_id

        if not payload.get("prompt") and not payload.get("structured_prompt"):
            raise RuntimeError("Provide at least prompt or structured_prompt.")

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
            msg = "Bria FIBO: api_token parm is deprecated. Prefer config/env-based auth (BRIA_API_KEY_HOUDINI or ~/.bria/bria.json)."
            _debug_log(msg)
            try:
                hou.ui.setStatusMessage(msg, severity=hou.severityType.Warning)
            except Exception:
                pass
        api_endpoint = _opt_parm_str(cop_node, "api_base_url")

        data = fibo_generate_from_payload(
            payload=payload,
            pipeline=pipeline,
            use_structured_prompt=use_structured,
            api_key=api_key,
            api_endpoint=api_endpoint,
            use_bearer=use_bearer_auth,
            proxies=proxies,
            session=hou.session.bria_fibo_generate_session,
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

        _debug_log(f"API FIBO Time:    {api_time:.4f} sec")
        _debug_log(f"Image Download:   {dl_time:.4f} sec")
        _debug_log(f"Total Turnaround: {total_time:.4f} sec")
        _debug_log(
            f"Saved result: {save_path} ({os.path.getsize(save_path)} bytes) | content-type={content_type or 'unknown'}"
        )

        save_api_metadata(save_path, data, "fibo_generate", {
            "api_time": round(api_time, 4),
            "download_time": round(dl_time, 4),
            "total_time": round(total_time, 4),
        }, request_params={
            "prompt": prompt or None,
            "structured_prompt": structured_prompt_raw or None,
            "negative_prompt": negative_prompt or None,
            "seed": seed,
            "steps_num": steps_num,
        })

        # Store structured_prompt from API response (free with every generation)
        hdefereval.executeDeferred(
            lambda node=cop_node, d=data: store_vgl_from_response(node, d)
        )

        hdefereval.executeDeferred(
            lambda node=cop_node, path=save_path, total=total_time: apply_result_to_ui(
                node,
                path,
                f"Bria FIBO Complete ({total:.2f}s) → {path}",
            )
        )

    except (BriaConfigError, BriaRequestError) as e:
        error_msg = f"Bria FIBO Error: {_safe_exc_str(e)}"
        _debug_log(error_msg)
        hdefereval.executeDeferred(
            lambda msg=error_msg: hou.ui.setStatusMessage(msg, severity=hou.severityType.Error)
        )
    except Exception as e:
        error_msg = f"Bria FIBO Exception: {_safe_exc_str(e)}"
        _debug_log(error_msg)
        hdefereval.executeDeferred(
            lambda msg=error_msg: hou.ui.setStatusMessage(msg, severity=hou.severityType.Error)
        )


def on_fibo_generate(kwargs: dict) -> None:
    node = kwargs.get("node")
    if node is None:
        raise ValueError("Missing kwargs['node']")
    fibo_generate_bria(node)
