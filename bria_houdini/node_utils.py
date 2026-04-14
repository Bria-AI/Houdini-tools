"""Shared Houdini node helper utilities for Bria node modules."""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
from typing import Any

from bria_houdini.bria_core.dcc import DccNodeUtils, debug_logger

_meta_log = logging.getLogger(__name__)

try:
    hou = importlib.import_module("hou")
except Exception:  # pragma: no cover - non-Houdini environments
    hou = None  # type: ignore[assignment]


class HoudiniNodeUtils(DccNodeUtils):
    def opt_parm_str(self, node: Any, name: str) -> str | None:
        parm = node.parm(name) if node is not None else None
        if parm is None:
            return None
        try:
            val = parm.eval()
        except Exception:
            return None
        if val is None:
            return None
        val = str(val).strip()
        return val or None

    def opt_parm_menu_str(self, node: Any, name: str) -> str | None:
        parm = node.parm(name) if node is not None else None
        if parm is None:
            return None
        try:
            val = parm.evalAsString()
        except Exception:
            return self.opt_parm_str(node, name)
        if val is None:
            return None
        val = str(val).strip()
        return val or None

    def opt_parm_bool(self, node: Any, name: str) -> bool | None:
        parm = node.parm(name) if node is not None else None
        if parm is None:
            return None
        try:
            return bool(parm.eval())
        except Exception:
            return None

    def opt_parm_int(self, node: Any, name: str) -> int | None:
        parm = node.parm(name) if node is not None else None
        if parm is None:
            return None
        try:
            val = parm.eval()
        except Exception:
            return None
        if val is None:
            return None
        try:
            return int(val)
        except Exception:
            return None

    def opt_parm_float(self, node: Any, name: str) -> float | None:
        parm = node.parm(name) if node is not None else None
        if parm is None:
            return None
        try:
            val = parm.eval()
        except Exception:
            return None
        if val is None:
            return None
        try:
            return float(val)
        except Exception:
            return None

    def as_dcc_path(self, path: str) -> str:
        return str(path).replace("\\", "/")

_UTILS = HoudiniNodeUtils()


def opt_parm_str(node, name: str) -> str | None:
    return _UTILS.opt_parm_str(node, name)


def opt_parm_menu_str(node, name: str) -> str | None:
    return _UTILS.opt_parm_menu_str(node, name)


def opt_parm_bool(node, name: str) -> bool | None:
    return _UTILS.opt_parm_bool(node, name)


def opt_parm_int(node, name: str) -> int | None:
    return _UTILS.opt_parm_int(node, name)


def opt_parm_float(node, name: str) -> float | None:
    return _UTILS.opt_parm_float(node, name)


def as_hscript_path(path: str) -> str:
    return _UTILS.as_dcc_path(path)


def clamp_steps_num(value: int | None, minimum: int = 25, maximum: int = 50) -> int | None:
    """Clamp steps_num to API-safe range. None/0/negative means use API default."""
    if value is None or value <= 0:
        return None
    if value < minimum:
        _meta_log.info("steps_num=%s is below minimum; clamping to %s.", value, minimum)
        return minimum
    if value > maximum:
        _meta_log.info("steps_num=%s exceeds maximum; clamping to %s.", value, maximum)
        return maximum
    return value


def extension_from_content_type(content_type: str | None) -> str | None:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
    }.get((content_type or "").strip().lower())


def _desktop_output_dir() -> str | None:
    """Return ~/Desktop/bria_houdini_tool_output, creating it if needed."""
    desktop = os.environ.get("XDG_DESKTOP_DIR", "").strip()
    if not desktop or not os.path.isdir(desktop):
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(desktop):
        return None
    output_dir = os.path.join(desktop, "bria_houdini_tool_output")
    try:
        os.makedirs(output_dir, exist_ok=True)
        return output_dir
    except Exception:
        return None


def resolve_output_dir(temp_dir: str, run_id: str, node_name: str) -> str:
    """Resolve the output directory for a Bria node result.

    Priority:
    1. Global project path (if use_bria_project_path is enabled and valid)
    2. ~/Desktop/bria_houdini_tool_output/
    3. Temp directory fallback
    """
    from bria_houdini.bria_core.config import load_config

    cfg = load_config()
    if cfg.use_bria_project_path:
        output_dir = (cfg.houdini_output_dir or "").strip()
        if not output_dir:
            output_dir = os.environ.get("BRIA_PROJECT_PATH", "").strip()
        if output_dir and os.path.isdir(output_dir):
            return os.path.join(output_dir, f"bria_{node_name}_result_{run_id}.png")

    desktop_dir = _desktop_output_dir()
    if desktop_dir:
        return os.path.join(desktop_dir, f"bria_{node_name}_result_{run_id}.png")

    return os.path.join(temp_dir, f"bria_{node_name}_result_{run_id}.png")


def resolve_result_save_path(out_path: str, content_type: str | None) -> str:
    ext = extension_from_content_type(content_type)
    if not ext:
        return out_path
    base, _ext = os.path.splitext(out_path)
    return base + ext


def save_api_metadata(
    save_path: str,
    api_response: dict,
    node_name: str,
    timing: dict | None = None,
    request_params: dict | None = None,
) -> str | None:
    """Save API response JSON alongside the result image.

    Creates a .json file next to the image with the same base name.
    Returns the JSON path on success, None on failure.
    """
    try:
        base, _ = os.path.splitext(save_path)
        json_path = base + ".json"
        meta = {
            "node": node_name,
            "image_path": save_path,
            "api_response": api_response,
        }
        if timing:
            meta["timing"] = timing
        if request_params:
            meta["request"] = request_params
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, default=str)
        _meta_log.debug("Saved API metadata: %s", json_path)
        return json_path
    except Exception:
        _meta_log.debug("Failed to save API metadata for %s", save_path, exc_info=True)
        return None


def _safe_exc_str(exc: Exception) -> str:
    """Format exception without str()/repr() which can hang on hou exceptions."""
    try:
        return f"{type(exc).__name__}: {exc.args}"
    except Exception:
        return type(exc).__name__


def apply_result_to_ui(cop_node, save_path: str, status_message: str) -> None:
    if hou is None:
        return

    _ui_log = debug_logger("Bria UI")
    _ui_log(f"apply_result_to_ui: {save_path}")

    # 1. Clear texture/GL caches
    try:
        hou.hscript("texcache -c")
        hou.hscript("glcache -c")
    except Exception:
        pass

    # 2. Set result_path parm — this drives everything via channel references.
    #    Internal nodes use expressions that read from result_path:
    #      loader_result.filename  -> chs("../result_path")
    #      switch_result.input     -> strlen(chs("../result_path")) > 0
    #    No allowEditingOfContents() needed — result_path is an HDA interface parm.
    result_parm = cop_node.parm("result_path") if cop_node is not None else None
    if result_parm is not None:
        result_parm.set(save_path)

    # 3. Force cook outputs to propagate the new image through the COP pipeline
    cop_outputs = cop_node.node("outputs") if cop_node is not None else None
    if cop_outputs is not None:
        try:
            cop_outputs.cook(force=True)
            _ui_log("outputs cook OK")
        except Exception as exc:
            _ui_log(f"outputs cook failed: {_safe_exc_str(exc)}")
        try:
            cop_outputs.setDisplayFlag(True)
        except Exception:
            pass

    # 4. Force viewport to notice the updated COP data
    try:
        hou.ui.triggerUpdate()
    except Exception:
        pass

    # 5. Status message
    if status_message:
        hou.ui.setStatusMessage(status_message)

    # 6. Open result in MPlay if the toggle is enabled.
    try:
        mplay_parm = cop_node.parm("open_in_mplay") if cop_node is not None else None
        if mplay_parm and mplay_parm.eval():
            from bria_houdini.nodes.viewport_render import display_in_mplay
            display_in_mplay(save_path)
    except Exception:
        pass

    _ui_log("apply_result_to_ui complete")


def store_vgl_from_response(node, data: dict) -> None:
    """Extract structured_prompt from an API response and populate VGL fields.

    The Bria generate endpoints return structured_prompt for free alongside
    image_url.  This helper stores it on the node's ``structured_prompt``
    parm and fills the organised VGL editor fields so the user can switch
    to structured-prompt mode and refine without an extra API call.

    Safe to call even if the response contains no structured_prompt — it
    simply returns without touching anything.
    """
    import json

    if not isinstance(data, dict):
        return

    result = data.get("result", {})
    sp = result.get("structured_prompt") if isinstance(result, dict) else None
    if sp is None:
        sp = data.get("structured_prompt")
    if not sp:
        return

    if isinstance(sp, dict):
        json_str = json.dumps(sp, indent=2)
    elif isinstance(sp, str):
        try:
            json_str = json.dumps(json.loads(sp), indent=2)
        except Exception:
            json_str = sp
    else:
        return

    sp_parm = node.parm("structured_prompt")
    if sp_parm:
        sp_parm.set(json_str)

    try:
        from bria_houdini.vgl_parms import populate_parms_from_json
        populate_parms_from_json(node, json_str)
    except Exception:
        pass
