"""Thin HDA PythonModule wrapper for Bria Expand (outpainting)."""

from __future__ import annotations

from bria_core.version import __version__
from bria_core.status import get_status
from houdini.nodes.expand import expand_bria, on_expand


def integration_version() -> str:
    return __version__


def integration_status() -> dict:
    return get_status(dcc="houdini", check_network=False)


__all__ = ["expand_bria", "on_expand", "integration_version", "integration_status"]
