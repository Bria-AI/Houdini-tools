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


def _debug_log(msg: str) -> None:
    print(f"[Bria COP Export] {msg}")


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

    Default behavior:
    - macOS: disabled (can deadlock in some Houdini/Qt states)
    - other platforms: enabled

    Override with BRIA_ALLOW_PRESSBUTTON_FALLBACK=1/true/yes/on.
    """
    raw = os.getenv("BRIA_ALLOW_PRESSBUTTON_FALLBACK")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return sys.platform != "darwin"


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

    try:
        os.makedirs(os.path.dirname(rop_path), exist_ok=True)
    except Exception:
        pass

    rendered = False
    render = getattr(rop, "render", None)
    if callable(render):
        try:
            render()
            rendered = True
            _debug_log(f"internal ROP render() succeeded | rop={rop_name}")
        except Exception as exc:
            try:
                exc_msg = repr(exc)
            except Exception:
                exc_msg = type(exc).__name__
            _debug_log(f"internal ROP render() failed: {exc_msg} | rop={rop_name}")
            rendered = False

    if not rendered:
        if _allow_pressbutton_fallback():
            rendered = _press_first_existing_button(rop, ("execute", "render", "executebutton"))
        else:
            _debug_log(f"pressButton fallback skipped on macOS | rop={rop_name}")

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

    # Export from the provided COP node via deterministic alternatives only:
    # 1) temporary ROP export from this exact node, or
    # 2) this exact node's own file-path source.
    # No upstream traversal is allowed.
    if _export_cop_pixels_to_png(cop_node, dst_path):
        return dst_path

    if _export_via_temp_rop(cop_node, dst_path):
        return dst_path

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

    raise RuntimeError(
        f"Could not export COP pixels from node: {cop_node.path()} and no usable file path was found on that node. "
        "Only direct COP export, exact-node temporary ROP export, or that exact node's file source is allowed."
    )
