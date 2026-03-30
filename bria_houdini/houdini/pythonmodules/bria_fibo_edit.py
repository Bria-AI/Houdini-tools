"""Thin HDA PythonModule wrapper for Bria FIBO Edit."""

from __future__ import annotations

from bria_core.version import __version__
from bria_core.status import get_status
from houdini.nodes.fibo_edit import fibo_edit_bria, on_fibo_edit
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
    "fibo_edit_bria",
    "on_fibo_edit",
    "on_parse_vgl",
    "sync_vgl_to_json",
    "on_refresh_upstream",
    "clear_vgl_parms",
    "build_history_menu",
    "on_load_result",
    "on_open_result_folder",
    "integration_version",
    "integration_status",
]
