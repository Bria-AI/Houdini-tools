"""Thin HDA PythonModule wrapper for Bria Viewport Restyle."""

from __future__ import annotations

from bria_core.version import __version__
from bria_core.status import get_status
from bria_houdini.nodes.viewport_restyle import (
    apply_result_callback,
    apply_texture_callback,
    capture_edit_viewport_callback,
    create_camera_callback,
    on_category_changed,
    on_preset_changed,
    refresh_image_list_callback,
    restyle_viewport_callback,
    ALL_PRESETS,
    CATEGORY_ORDER,
    PRESET_CATEGORIES,
)


def integration_version() -> str:
    return __version__


def integration_status() -> dict:
    return get_status(dcc="houdini", check_network=False)


__all__ = [
    "create_camera_callback",
    "restyle_viewport_callback",
    "capture_edit_viewport_callback",
    "apply_texture_callback",
    "apply_result_callback",
    "refresh_image_list_callback",
    "on_category_changed",
    "on_preset_changed",
    "ALL_PRESETS",
    "CATEGORY_ORDER",
    "PRESET_CATEGORIES",
    "integration_version",
    "integration_status",
]
