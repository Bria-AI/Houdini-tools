"""Thin HDA PythonModule wrapper for Bria FIBO Edit Presets."""

from __future__ import annotations

from bria_core.version import __version__
from bria_core.status import get_status
from houdini.nodes.fibo_edit_presets import (
    fibo_edit_presets_bria,
    on_fibo_edit_presets,
    on_category_changed,
    on_preset_changed,
    on_object_target_changed,
    on_comp_element_changed,
    CATEGORY_ORDER,
    PRESET_CATEGORIES,
    ALL_PRESETS,
)
from houdini.vgl_parms import (
    on_parse_vgl,
    sync_vgl_to_json,
    on_refresh_upstream,
    clear_vgl_parms,
)
from houdini.result_history import (
    build_history_menu,
    on_load_result,
    on_open_result_folder,
)


def integration_version() -> str:
    return __version__


def integration_status() -> dict:
    return get_status(dcc="houdini", check_network=False)


__all__ = [
    "fibo_edit_presets_bria",
    "on_fibo_edit_presets",
    "on_category_changed",
    "on_preset_changed",
    "on_object_target_changed",
    "on_comp_element_changed",
    "on_parse_vgl",
    "sync_vgl_to_json",
    "on_refresh_upstream",
    "clear_vgl_parms",
    "build_history_menu",
    "on_load_result",
    "on_open_result_folder",
    "CATEGORY_ORDER",
    "PRESET_CATEGORIES",
    "ALL_PRESETS",
    "integration_version",
    "integration_status",
]
