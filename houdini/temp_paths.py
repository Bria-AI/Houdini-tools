"""Deprecated Houdini temp path shim.

Use `bria_core.utils.resolve_temp_dir` directly.
"""

from __future__ import annotations

from typing import Any

from bria_core.utils import resolve_temp_dir as _resolve_temp_dir


def resolve_temp_dir(hou_module: Any = None, fallback: str = ".") -> str:
    """Compatibility wrapper forwarding to `bria_core.utils.resolve_temp_dir`."""
    return _resolve_temp_dir(dcc_module=hou_module, fallback=fallback)
