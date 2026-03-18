"""Thin HDA PythonModule wrapper for Bria Generate Image."""

from __future__ import annotations

from bria_core.version import __version__
from bria_core.status import get_status
from houdini.nodes.generate_image import generate_image_bria, on_generate_image
from houdini.vgl_parms import (
    on_parse_vgl,
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
    "generate_image_bria",
    "on_generate_image",
    "on_parse_vgl",
    "on_refresh_upstream",
    "clear_vgl_parms",
    "build_history_menu",
    "on_load_result",
    "on_open_result_folder",
    "integration_version",
    "integration_status",
]
