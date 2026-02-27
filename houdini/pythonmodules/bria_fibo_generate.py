"""Thin HDA PythonModule wrapper for Bria FIBO Generate."""

from __future__ import annotations

from bria_core.version import __version__
from bria_core.status import get_status
from houdini.nodes.fibo_generate import fibo_generate_bria, on_fibo_generate


def integration_version() -> str:
    return __version__


def integration_status() -> dict:
    return get_status(dcc="houdini", check_network=False)


__all__ = ["fibo_generate_bria", "on_fibo_generate", "integration_version", "integration_status"]
