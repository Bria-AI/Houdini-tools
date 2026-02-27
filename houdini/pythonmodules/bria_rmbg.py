"""Thin HDA PythonModule wrapper for Bria RMBG (Remove Background)."""

from __future__ import annotations

from bria_core.version import __version__
from bria_core.status import get_status
from houdini.nodes.rmbg import remove_background_bria, on_rmbg


def integration_version() -> str:
    return __version__


def integration_status() -> dict:
    return get_status(dcc="houdini", check_network=False)


__all__ = ["remove_background_bria", "on_rmbg", "integration_version", "integration_status"]
