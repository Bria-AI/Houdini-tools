"""Shared Houdini node helper utilities for Bria node modules."""

from __future__ import annotations

import importlib
import os
from typing import Any

from bria_core.dcc import DccNodeUtils, debug_logger

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


def extension_from_content_type(content_type: str | None) -> str | None:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
    }.get((content_type or "").strip().lower())


def resolve_result_save_path(out_path: str, content_type: str | None) -> str:
    ext = extension_from_content_type(content_type)
    if not ext:
        return out_path
    base, _ext = os.path.splitext(out_path)
    return base + ext


def apply_result_to_ui(cop_node, save_path: str, status_message: str) -> None:
    if hou is None:
        return

    try:
        hou.hscript("texcache -c")
        hou.hscript("glcache -c")
    except Exception:
        pass

    result_parm = cop_node.parm("result_path") if cop_node is not None else None
    if result_parm is not None:
        result_parm.set(save_path)

    loader = cop_node.node("loader_result") if cop_node is not None else None
    if loader is not None:
        if loader.parm("filename") is not None:
            loader.parm("filename").set(save_path)
        if loader.parm("reload") is not None:
            loader.parm("reload").pressButton()
        try:
            loader.cook(force=True)
        except Exception:
            pass

    switch = cop_node.node("switch_result") if cop_node is not None else None
    if switch is not None and switch.parm("input") is not None:
        try:
            switch.parm("input").set(1)  # input 0=Before, 1=After
        except Exception:
            pass

    if status_message:
        hou.ui.setStatusMessage(status_message)
