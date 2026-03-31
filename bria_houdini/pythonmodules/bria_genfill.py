"""Thin HDA PythonModule wrapper for Bria GenFill."""

from __future__ import annotations

from bria_core.version import __version__
from bria_core.status import get_status
from bria_houdini.nodes.genfill import genfill_bria, on_genfill
from bria_houdini.result_history import (
    build_history_menu,
    on_load_result,
    on_open_result_folder,
)


def integration_version() -> str:
    return __version__


def integration_status() -> dict:
    return get_status(dcc="houdini", check_network=False)


__all__ = [
    "genfill_bria",
    "on_genfill",
    "build_history_menu",
    "on_load_result",
    "on_open_result_folder",
    "integration_version",
    "integration_status",
]
