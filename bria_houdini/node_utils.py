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


def resolve_output_dir(temp_dir: str, run_id: str, node_name: str) -> str:
    """Resolve the output directory for a Bria node result.

    Priority:
    1. Global project path (if use_bria_project_path is enabled and valid)
    2. Temp directory fallback
    """
    from bria_houdini.bria_core.config import load_config

    cfg = load_config()
    if cfg.use_bria_project_path:
        output_dir = (cfg.houdini_output_dir or "").strip()
        if not output_dir:
            output_dir = os.environ.get("BRIA_PROJECT_PATH", "").strip()
        if output_dir and os.path.isdir(output_dir):
            return os.path.join(output_dir, f"bria_{node_name}_result_{run_id}.png")
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

    # 2. Set result_path parm
    result_parm = cop_node.parm("result_path") if cop_node is not None else None
    if result_parm is not None:
        result_parm.set(save_path)

    # 3. Unlock HDA contents so we can modify internal nodes
    try:
        cop_node.allowEditingOfContents()
    except Exception as exc:
        _ui_log(f"allowEditingOfContents failed: {_safe_exc_str(exc)}")

    # 4. Configure and load File node
    loader = cop_node.node("loader_result") if cop_node is not None else None
    if loader is not None:
        # Copernicus File node requires AOV config to load images
        if loader.parm("aovs") is not None:
            loader.parm("aovs").set(1)
        if loader.parm("aov1") is not None:
            loader.parm("aov1").set("C")
        # Try different filename parameter names (varies by Houdini version/context)
        for pname in ("file", "filename1", "filename"):
            fp = loader.parm(pname)
            if fp is not None:
                fp.set(save_path)
                _ui_log(f"loader {pname} set to {save_path}")
                break

        # pressButton("reload") can hang on macOS (see cop_export.py).
        # Setting a new file path above already triggers the node to reload.
        if sys.platform != "darwin":
            if loader.parm("reload") is not None:
                loader.parm("reload").pressButton()

        try:
            loader.cook(force=True)
            _ui_log("loader cook OK")
        except Exception as exc:
            _ui_log(f"loader cook failed: {_safe_exc_str(exc)}")

    # 5. Wire switch and toggle to result
    switch = cop_node.node("switch_result") if cop_node is not None else None
    cop_outputs = cop_node.node("outputs") if cop_node is not None else None

    if switch is not None:
        # Ensure loader_result is wired into the switch
        try:
            if loader is not None:
                switch.setInput(1, loader)
        except Exception as exc:
            _ui_log(f"switch setInput failed: {_safe_exc_str(exc)}")
        # Ensure switch is wired to Copernicus outputs
        if cop_outputs is not None:
            try:
                cop_outputs.setInput(0, None)
                cop_outputs.setInput(0, switch)
            except Exception as exc:
                _ui_log(f"outputs setInput failed: {_safe_exc_str(exc)}")
        if switch.parm("input") is not None:
            try:
                switch.parm("input").set(1)  # input 0=pass-through, 1=result
            except Exception as exc:
                _ui_log(f"switch toggle failed: {_safe_exc_str(exc)}")
    elif loader is not None and cop_outputs is not None:
        # No switch node — wire loader directly to Copernicus outputs
        try:
            cop_outputs.setInput(0, None)
            cop_outputs.setInput(0, loader)
        except Exception as exc:
            _ui_log(f"direct wire failed: {_safe_exc_str(exc)}")

    # 6. Force cook outputs to propagate the new image through the COP pipeline
    if cop_outputs is not None:
        try:
            cop_outputs.cook(force=True)
            _ui_log("outputs cook OK")
        except Exception as exc:
            _ui_log(f"outputs cook failed: {_safe_exc_str(exc)}")
        # Ensure display flag is set so viewer picks up the result
        try:
            cop_outputs.setDisplayFlag(True)
        except Exception:
            pass

    # 7. Force viewport to notice the updated COP data
    try:
        hou.ui.triggerUpdate()
    except Exception:
        pass

    # 8. Status message
    if status_message:
        hou.ui.setStatusMessage(status_message)

    # 9. Open result in MPlay if the toggle is enabled.
    # MPlay reads files from disk (no COP pixel pipeline), so it bypasses
    # Houdini Non-Commercial watermarks and resolution limits.
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
