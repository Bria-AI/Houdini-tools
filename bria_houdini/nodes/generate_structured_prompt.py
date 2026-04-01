"""Houdini Bria Generate Structured Prompt node logic.

Calls the Bria VLM bridge (POST /v2/structured_prompt/generate) to convert
a text prompt, reference image, or both into a structured prompt JSON.
The result is stored on the node so downstream Generate Image nodes can read it.
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

import hou
import hdefereval

from bria_houdini.bria_core.errors import BriaConfigError, BriaRequestError
from bria_houdini.bria_core.utils import resolve_proxies, resolve_temp_dir
from bria_houdini.adapter import generate_structured_prompt
from bria_houdini.cop_export import export_via_internal_rop, cop_to_png, _safe_exc_str
from bria_houdini.node_utils import (
    clamp_steps_num,
    debug_logger,
    opt_parm_bool as _opt_parm_bool,
    opt_parm_int as _opt_parm_int,
    opt_parm_str as _opt_parm_str,
    resolve_output_dir,
    save_api_metadata,
)
if not hasattr(hou.session, "bria_gen_structured_prompt_session"):
    hou.session.bria_gen_structured_prompt_session = None


_debug_log = debug_logger("Bria Generate Structured Prompt")


def generate_structured_prompt_bria(cop_node: hou.Node) -> None:
    t_start = time.perf_counter()

    try:
        prompt = (_opt_parm_str(cop_node, "prompt") or "").strip()

        # Check for connected image input
        inputs = cop_node.inputs()
        input_op = inputs[0] if len(inputs) > 0 else None
        image_path = None

        if input_op is not None:
            temp_dir = resolve_temp_dir(hou)
            run_id = str(int(time.time() * 1000))
            img_export_path = os.path.join(
                temp_dir, f"bria_struct_prompt_input_{run_id}.png"
            )
            try:
                image_path = (
                    export_via_internal_rop(cop_node, "rop_save_input", img_export_path)
                    or cop_to_png(input_op, img_export_path)
                )
            except Exception as exc:
                _debug_log(f"Image export failed: {_safe_exc_str(exc)}")
                image_path = None
                if not prompt:
                    hou.ui.displayMessage(
                        "Connected input has no image data to export.\n\n"
                        "If using a Bria generation node, run it first to "
                        "produce an image, then try again.",
                        severity=hou.severityType.Error,
                        title="Bria Generate Structured Prompt",
                    )
                    return

        if not prompt and not image_path:
            hou.ui.displayMessage(
                "Enter a text prompt or connect an image input (or both).",
                severity=hou.severityType.Error,
                title="Bria Generate Structured Prompt",
            )
            return

        seed = _opt_parm_int(cop_node, "seed")
        if seed is not None and seed <= 0:
            seed = None

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
        api_endpoint = _opt_parm_str(cop_node, "api_base_url")

        mode = "image+text" if (prompt and image_path) else ("image" if image_path else "text")
        _debug_log(f"Generating structured prompt ({mode}): prompt={prompt[:80] if prompt else 'none'}")

        data = generate_structured_prompt(
            prompt=prompt or None,
            image_path=image_path,
            seed=seed,
            api_key=api_key,
            api_endpoint=api_endpoint,
            use_bearer=use_bearer_auth,
            proxies=proxies,
            session=hou.session.bria_gen_structured_prompt_session,
        )

        t_api_end = time.perf_counter()
        api_time = t_api_end - t_start

        # Extract structured prompt from response (nested under "result")
        result = data.get("result", {})
        if isinstance(result, dict):
            structured_prompt = result.get("structured_prompt")
        else:
            structured_prompt = data.get("structured_prompt")
        if structured_prompt is None:
            raise BriaRequestError(
                f"Unexpected API response (no structured_prompt): {data}"
            )

        # Serialize to formatted JSON string
        if isinstance(structured_prompt, dict):
            result_json = json.dumps(structured_prompt, indent=2)
        elif isinstance(structured_prompt, str):
            # API may return a JSON string — parse and re-format for readability
            try:
                result_json = json.dumps(json.loads(structured_prompt), indent=2)
            except Exception:
                result_json = structured_prompt
        else:
            result_json = json.dumps(structured_prompt, indent=2, default=str)

        # Passthrough: copy input image path to result_path so downstream
        # nodes can find the image via _find_image_path_on_node().
        if image_path:
            rp = cop_node.parm("result_path")
            if rp is not None:
                rp.set(image_path)

        # Store result on the node for downstream consumption
        result_parm = cop_node.parm("result_json")
        if result_parm is not None:
            hdefereval.executeDeferred(
                lambda parm=result_parm, val=result_json: parm.set(val)
            )

        # Push updated structured prompt to connected downstream nodes
        def _push_to_downstream(node=cop_node, val=result_json):
            for output_node in node.outputs():
                sp = output_node.parm("structured_prompt")
                if sp is not None:
                    sp.set(val)
                    # Also parse into VGL categories
                    try:
                        phm = output_node.hdaModule()
                        if hasattr(phm, "on_parse_vgl"):
                            phm.on_parse_vgl({"node": output_node})
                    except Exception:
                        pass
        hdefereval.executeDeferred(_push_to_downstream)

        # Save to file
        temp_dir = resolve_temp_dir(hou)
        run_id = str(int(time.time() * 1000))
        json_path = os.path.join(
            temp_dir, f"bria_structured_prompt_{run_id}.json"
        )
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                {"mode": mode, "prompt": prompt, "image_path": image_path,
                 "structured_prompt": structured_prompt, "api_response": data},
                f,
                indent=2,
                default=str,
            )

        _debug_log(f"API Time: {api_time:.4f} sec")
        _debug_log(f"Saved structured prompt: {json_path}")

        # Populate description label
        short_desc = ""
        if isinstance(structured_prompt, dict):
            short_desc = structured_prompt.get("short_description", "")
        if short_desc:
            hdefereval.executeDeferred(
                lambda n=cop_node, d=short_desc: _update_description_label(n, d)
            )

        # Show summary in status bar
        if short_desc:
            status_msg = f"Structured prompt generated ({api_time:.2f}s): {short_desc[:80]}"
        else:
            status_msg = f"Structured prompt generated ({api_time:.2f}s) \u2192 {json_path}"

        hdefereval.executeDeferred(
            lambda msg=status_msg: hou.ui.setStatusMessage(msg)
        )

    except (BriaConfigError, BriaRequestError) as e:
        error_msg = f"Bria Structured Prompt Error: {e}"
        _debug_log(error_msg)
        hdefereval.executeDeferred(
            lambda msg=error_msg: hou.ui.setStatusMessage(msg, severity=hou.severityType.Error)
        )
    except Exception as e:
        error_msg = f"Bria Structured Prompt Exception: {_safe_exc_str(e)}"
        _debug_log(error_msg)
        hdefereval.executeDeferred(
            lambda msg=error_msg: hou.ui.setStatusMessage(msg, severity=hou.severityType.Error)
        )


def _update_description_label(node: hou.Node, description: str) -> None:
    """Update the vgl_description label parm with the short description."""
    try:
        ptg = node.parmTemplateGroup()
        old = ptg.find("vgl_description")
        if old is not None:
            replacement = hou.LabelParmTemplate(
                "vgl_description", "Description:",
                column_labels=[description[:120]],
            )
            ptg.replace("vgl_description", replacement)
            node.setParmTemplateGroup(ptg)
    except Exception as exc:
        _debug_log(f"Could not update description label: {_safe_exc_str(exc)}")


def on_send_downstream(kwargs: dict) -> None:
    """Push current result_json to all connected downstream nodes."""
    node = kwargs.get("node")
    if node is None:
        return
    result_json = (node.parm("result_json").eval() or "").strip()
    if not result_json:
        hou.ui.setStatusMessage(
            "No structured prompt to send.",
            severity=hou.severityType.Warning,
        )
        return

    pushed = 0
    for output_node in node.outputs():
        sp = output_node.parm("structured_prompt")
        if sp is not None:
            sp.set(result_json)
            pushed += 1
            # Also trigger category parse if available
            try:
                phm = output_node.hdaModule()
                if hasattr(phm, "on_parse_vgl"):
                    phm.on_parse_vgl({"node": output_node})
            except Exception:
                pass

    hou.ui.setStatusMessage(
        f"Sent structured prompt to {pushed} downstream node(s)."
    )


def on_generate_structured_prompt(kwargs: dict) -> None:
    node = kwargs.get("node")
    if node is None:
        raise ValueError("Missing kwargs['node']")
    generate_structured_prompt_bria(node)
