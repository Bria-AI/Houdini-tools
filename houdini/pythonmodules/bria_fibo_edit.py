"""Thin HDA PythonModule wrapper for Bria FIBO Edit."""

from __future__ import annotations

from bria_core.version import __version__
from bria_core.status import get_status
from houdini.nodes.fibo_edit import fibo_edit_bria, on_fibo_edit


def integration_version() -> str:
    return __version__


def integration_status() -> dict:
    return get_status(dcc="houdini", check_network=False)


__all__ = [
    "fibo_edit_bria",
    "on_fibo_edit",
    "integration_version",
    "integration_status",
]
