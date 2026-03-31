"""Copernicus-friendly COP export helpers.

These helpers export deterministic data from the intended node path.
They prefer direct COP export, then deterministic exact-node options.
Upstream traversal is disabled to guarantee exported data matches the
intended HDA input.
"""

from __future__ import annotations

import os
import shutil
import importlib
import sys
import time
from typing import Any

try:
    hou = importlib.import_module("hou")
except Exception:  # pragma: no cover - non-Houdini environments
    hou = None  # type: ignore[assignment]

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".exr"}


import logging as _logging
_cop_export_logger = _logging.getLogger("bria.cop_export")


def _debug_log(msg: str) -> None:
    _cop_export_logger.info("[Bria COP Export] %s", msg)


def _safe_exc_str(exc: BaseException) -> str:
    """Format exception without str()/repr() which can hang on hou exceptions."""
    try:
        name = type(exc).__name__
    except Exception:
        name = "Exception"
    try:
        args = exc.args
        if args:
            return f"{name}: {args[0]}" if len(args) == 1 else f"{name}{args}"
    except Exception:
        pass
    return name


def _is_png_file(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(8) == _PNG_SIGNATURE
    except Exception:
        return False


def _existing_image_path(raw_path: str) -> str | None:
    if not raw_path:
        return None

    value = str(raw_path).strip()
    if not value:
        return None

    candidates = [value]
    if hou is not None and hasattr(hou, "expandString"):
        try:
            expanded = hou.expandString(value)
            if expanded and expanded not in candidates:
                candidates.append(expanded)
        except Exception:
            pass

    for path in candidates:
        ext = os.path.splitext(path)[1].lower()
        if ext in _IMAGE_EXTS and os.path.exists(path):
            return path

    return None


def _find_image_path_on_node(node: Any) -> str | None:
    if node is None:
        return None

    for name in ("result_path", "filename", "file", "filepath", "image", "image_path"):
        parm = node.parm(name)
        if parm is None:
            continue
        try:
            found = _existing_image_path(parm.evalAsString())
        except Exception:
            found = None
        if found:
            return found

    for parm in node.parms():
        try:
            template = parm.parmTemplate()
            if template is None:
                continue
            if template.type() != hou.parmTemplateType.String:
                continue
            found = _existing_image_path(parm.evalAsString())
        except Exception:
            found = None
        if found:
            return found

    # Fallback: check internal loader_result File node (post-restart persistence)
    try:
        loader = node.node("loader_result")
        if loader is not None:
            for pname in ("file", "filename1", "filename"):
                p = loader.parm(pname)
                if p is not None:
                    found = _existing_image_path(p.evalAsString())
                    if found:
                        return found
    except Exception:
        pass

    return None


def _export_cop_pixels_to_png(cop_node: Any, dst_path: str) -> bool:
    if cop_node is None:
        return False

    try:
        cook = getattr(cop_node, "cook", None)
        if callable(cook):
            cook(force=True)
    except Exception:
        pass

    for method_name in ("saveImageToFile", "saveImagesToFile", "saveImage"):
        method = getattr(cop_node, method_name, None)
        if method is None:
            continue
        try:
            method(dst_path)
        except Exception:
            continue

        if os.path.exists(dst_path) and _is_png_file(dst_path):
            try:
                node_path = cop_node.path()
            except Exception:
                node_path = "<unknown>"
            _debug_log(f"mode=direct-cop | node={node_path} | method={method_name} | dst={dst_path}")
            return True

    return False


def _set_first_existing_parm(node: Any, parm_names: tuple[str, ...], value: str) -> bool:
    for name in parm_names:
        parm = node.parm(name)
        if parm is None:
            continue
        try:
            parm.set(value)
            return True
        except Exception:
            continue
    return False


def _press_first_existing_button(node: Any, parm_names: tuple[str, ...]) -> bool:
    for name in parm_names:
        parm = node.parm(name)
        if parm is None:
            continue
        try:
            parm.pressButton()
            return True
        except Exception:
            continue
    return False


def _allow_pressbutton_fallback() -> bool:
    """Whether to allow button-based render fallback.

    pressButton uses Houdini's UI event loop rather than blocking render(),
    making it safer on macOS where render() can deadlock.

    Override with BRIA_ALLOW_PRESSBUTTON_FALLBACK=0/false/no/off to disable.
    """
    raw = os.getenv("BRIA_ALLOW_PRESSBUTTON_FALLBACK")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return True


def _export_via_temp_rop(cop_node: Any, dst_path: str) -> bool:
    """Export exact COP node output via a temporary ROP Image Output node."""
    if hou is None or cop_node is None:
        return False

    parent = None
    try:
        parent = cop_node.parent()
    except Exception:
        parent = None
    if parent is None:
        return False

    rop = None
    rop_type_names = ("rop_comp", "rop_image", "ropcop2", "rop_cop2")

    try:
        for rop_type_name in rop_type_names:
            try:
                rop = parent.createNode(rop_type_name, f"__bria_tmp_export_{int(time.time() * 1000)}")
                break
            except Exception:
                rop = None
        if rop is None:
            return False

        try:
            rop.setInput(0, cop_node)
        except Exception:
            pass

        _set_first_existing_parm(
            rop,
            ("copoutput", "picture", "filename", "file", "output"),
            dst_path,
        )

        # On macOS, temp ROP render() can deadlock — skip entirely
        if sys.platform == "darwin":
            _debug_log("temp ROP export skipped on macOS (can deadlock)")
            return False

        render = getattr(rop, "render", None)
        rendered = False
        if callable(render):
            try:
                render()
                rendered = True
            except Exception:
                rendered = False

        if not rendered:
            if _allow_pressbutton_fallback():
                _press_first_existing_button(
                    rop,
                    ("execute", "render", "executebutton", "reload"),
                )
            else:
                _debug_log("pressButton fallback skipped (BRIA_ALLOW_PRESSBUTTON_FALLBACK not enabled)")

        if os.path.exists(dst_path) and _is_png_file(dst_path):
            try:
                node_path = cop_node.path()
            except Exception:
                node_path = "<unknown>"
            _debug_log(f"mode=temp-rop-exact-node | node={node_path} | rop={rop.path()} | dst={dst_path}")
            return True

        return False
    finally:
        if rop is not None:
            try:
                rop.destroy()
            except Exception:
                pass


def export_via_internal_rop(owner_node: Any, rop_name: str, dst_path: str | None = None) -> str | None:
    """Execute an internal HDA ROP and return the produced file path.

    This is deterministic and does not traverse upstream networks.
    """
    if owner_node is None or not rop_name:
        _debug_log(f"internal ROP: owner_node or rop_name missing")
        return None

    try:
        rop = owner_node.node(rop_name)
    except Exception as exc:
        _debug_log(f"internal ROP: node lookup failed: {exc}")
        rop = None
    if rop is None:
        _debug_log(f"internal ROP: '{rop_name}' not found inside {owner_node.path()}")
        return None

    _debug_log(f"internal ROP: found '{rop_name}' at {rop.path()} (type={rop.type().name()})")

    path_parm = None
    for parm_name in ("copoutput", "picture", "filename", "file", "output"):
        parm = rop.parm(parm_name)
        if parm is not None:
            path_parm = parm
            break

    if path_parm is None:
        _debug_log(f"internal ROP: no output path parm found on {rop.path()}")
        return None

    try:
        rop_path = path_parm.evalAsString()
    except Exception:
        return None

    rop_path = _existing_image_path(rop_path) or rop_path
    if dst_path:
        try:
            path_parm.set(dst_path)
            rop_path = dst_path
        except Exception:
            pass

    if not rop_path:
        return None

    # Tier 0: check if the upstream input already has a result file on disk.
    # This bypasses Copernicus entirely, avoiding Apprentice/NC resolution limits
    # (1920x1080 cap on Copernicus) and potential render deadlocks.
    #
    # Determine which HDA input this ROP corresponds to by checking
    # which output of the internal 'inputs' node it's wired to.
    # rop_save_input → inputs output 0 → HDA input 1 (source image)
    # rop_save_mask  → inputs output 1 → HDA input 2 (mask)
    input_idx = 0
    try:
        inputs_node = owner_node.node("inputs")
        if inputs_node is not None:
            conns = rop.inputConnections()
            if conns:
                conn = conns[0]
                if conn.inputNode() == inputs_node:
                    input_idx = conn.outputIndex()
    except Exception:
        pass

    inputs = owner_node.inputs()
    if inputs and len(inputs) > input_idx:
        upstream = inputs[input_idx]
        if upstream is not None:
            src = _find_image_path_on_node(upstream)
            if src and os.path.isfile(src):
                target = dst_path if dst_path else rop_path
                src_abs = os.path.abspath(src)
                dst_abs = os.path.abspath(target)
                if src_abs != dst_abs:
                    os.makedirs(os.path.dirname(dst_abs), exist_ok=True)
                    shutil.copyfile(src_abs, dst_abs)
                _debug_log(f"mode=internal-rop-passthrough | src={src_abs} | dst={dst_abs}")
                return dst_abs

    try:
        os.makedirs(os.path.dirname(rop_path), exist_ok=True)
    except Exception:
        pass

    rendered = False
    # On macOS, render() can deadlock — skip it, but still try pressButton below
    if sys.platform != "darwin":
        render = getattr(rop, "render", None)
        if callable(render):
            try:
                render()
                rendered = True
                _debug_log(f"internal ROP render() succeeded | rop={rop_name}")
            except Exception as exc:
                exc_msg = _safe_exc_str(exc)
                _debug_log(f"internal ROP render() failed: {exc_msg} | rop={rop_name}")
                rendered = False

    if not rendered:
        # pressButton uses Houdini's UI event loop — safer than render() on macOS
        if _allow_pressbutton_fallback():
            rendered = _press_first_existing_button(rop, ("execute", "render", "executebutton"))
        else:
            _debug_log(f"pressButton fallback disabled via env var | rop={rop_name}")

    if not rendered:
        _debug_log(f"internal ROP export failed (not rendered) | rop={rop_name} | dst={rop_path}")
        return None

    if not os.path.exists(rop_path):
        return None

    try:
        node_path = owner_node.path()
    except Exception:
        node_path = "<unknown>"
    _debug_log(f"mode=internal-hda-rop | owner={node_path} | rop={rop.path()} | out={rop_path}")
    return os.path.abspath(rop_path)


def cop_to_png(cop_node: Any, dst_path: str) -> str:
    """Export COP input to a deterministic disk file for upload.

    Preferred path is direct COP pixel export to PNG at ``dst_path``.
    If unavailable, deterministic exact-node alternatives are used.
    """

    if cop_node is None:
        raise RuntimeError("Missing COP input node")
    if not dst_path:
        raise RuntimeError("Destination export path is empty")

    os.makedirs(os.path.dirname(dst_path), exist_ok=True)

    # Tier 0: If the node has a file on disk (e.g. result_path from a
    # previous Bria API call), use it directly.  This bypasses the COP
    # pixel pipeline entirely, which prevents Houdini Non-Commercial
    # from applying watermarks or throwing resolution-limit errors on
    # high-res results (e.g. 4x upscale → downstream edit).
    src_path = _find_image_path_on_node(cop_node)
    if src_path:
        src_abs = os.path.abspath(src_path)
        dst_abs = os.path.abspath(dst_path)
        src_ext = os.path.splitext(src_abs)[1].lower()

        if src_ext == ".png":
            if src_abs != dst_abs:
                shutil.copyfile(src_abs, dst_abs)
            _debug_log(f"mode=node-source-path-copy | node={cop_node.path()} | src={src_abs} | dst={dst_abs}")
            return dst_path

        _debug_log(f"mode=node-source-path-direct | node={cop_node.path()} | src={src_abs}")
        return src_abs

    # Tier 1: Direct COP pixel export (may fail under NC license limits)
    if _export_cop_pixels_to_png(cop_node, dst_path):
        return dst_path

    # Tier 2: Temporary ROP export from this exact node
    if _export_via_temp_rop(cop_node, dst_path):
        return dst_path

    raise RuntimeError(
        f"Could not export COP pixels from node: {cop_node.path()} and no usable file path was found on that node. "
        "Only direct COP export, exact-node temporary ROP export, or that exact node's file source is allowed."
    )
