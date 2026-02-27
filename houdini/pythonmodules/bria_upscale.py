"""Thin HDA PythonModule wrapper for Bria Upscale."""

from __future__ import annotations

from bria_core.version import __version__
from bria_core.status import get_status
from houdini.nodes.upscale import upscale_bria, on_upscale


def integration_version() -> str:
    return __version__


def integration_status() -> dict:
    return get_status(dcc="houdini", check_network=False)


__all__ = ["upscale_bria", "on_upscale", "integration_version", "integration_status"]
