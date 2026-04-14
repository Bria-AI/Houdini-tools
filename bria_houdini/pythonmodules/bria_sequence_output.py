"""Thin HDA PythonModule wrapper for Bria Sequence Output."""

from __future__ import annotations

from bria_houdini.bria_core.version import __version__
from bria_houdini.bria_core.status import get_status
from bria_houdini.nodes.sequence_output import (
    on_refresh_chain,
    on_render,
    render_sequence,
)


def integration_version() -> str:
    return __version__


def integration_status() -> dict:
    return get_status(dcc="houdini", check_network=False)


__all__ = [
    "on_render",
    "on_refresh_chain",
    "render_sequence",
    "integration_version",
    "integration_status",
]
