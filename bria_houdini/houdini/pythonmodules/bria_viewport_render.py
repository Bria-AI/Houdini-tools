"""Thin HDA PythonModule wrapper for Bria Viewport Render."""

from __future__ import annotations

from bria_core.version import __version__
from bria_core.status import get_status
from houdini.nodes.viewport_render import (
    apply_result_callback,
    apply_texture_callback,
    capture_render_viewport_callback,
    create_camera_callback,
    enhance_result_callback,
    generate_vgl_callback,
    on_category_changed,
    on_parse_vgl,
    sync_vgl_to_json,
    on_preset_changed,
    refresh_image_list_callback,
    render_viewport_callback,
    upscale_result_callback,
    validate_existing_camera_callback,
    ALL_PRESETS,
    CATEGORY_ORDER,
    PRESET_CATEGORIES,
    SUPPORTED_RESOLUTIONS,
)


def integration_version() -> str:
    return __version__


def integration_status() -> dict:
    return get_status(dcc="houdini", check_network=False)


__all__ = [
    "create_camera_callback",
    "render_viewport_callback",
    "capture_render_viewport_callback",
    "apply_texture_callback",
    "apply_result_callback",
    "enhance_result_callback",
    "refresh_image_list_callback",
    "generate_vgl_callback",
    "on_category_changed",
    "on_parse_vgl",
    "sync_vgl_to_json",
    "on_preset_changed",
    "upscale_result_callback",
    "validate_existing_camera_callback",
    "ALL_PRESETS",
    "CATEGORY_ORDER",
    "PRESET_CATEGORIES",
    "SUPPORTED_RESOLUTIONS",
    "integration_version",
    "integration_status",
]
