"""Thin HDA PythonModule wrapper for Bria Generate Structured Prompt."""

from __future__ import annotations

from bria_core.version import __version__
from bria_core.status import get_status
from houdini.nodes.generate_structured_prompt import (
    generate_structured_prompt_bria,
    on_generate_structured_prompt,
    on_send_downstream,
)


def integration_version() -> str:
    return __version__


def integration_status() -> dict:
    return get_status(dcc="houdini", check_network=False)


__all__ = [
    "generate_structured_prompt_bria",
    "on_generate_structured_prompt",
    "on_send_downstream",
    "integration_version",
    "integration_status",
]
