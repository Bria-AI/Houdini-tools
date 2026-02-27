"""Thin HDA PythonModule wrapper for Bria GenFill."""

from __future__ import annotations

from bria_core.version import __version__
from bria_core.status import get_status
from houdini.nodes.genfill import generate_bria, on_generate

def integration_version() -> str:
	return __version__


def integration_status() -> dict:
	return get_status(dcc="houdini", check_network=False)


__all__ = ["generate_bria", "on_generate", "integration_version", "integration_status"]
