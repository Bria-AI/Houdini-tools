"""Small DCC adapter contract for node parameter and logging helpers.

This keeps shared logic portable across Houdini, Nuke, and other DCCs.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class DccNodeUtils(Protocol):
    def opt_parm_str(self, node: Any, name: str) -> str | None: ...

    def opt_parm_menu_str(self, node: Any, name: str) -> str | None: ...

    def opt_parm_bool(self, node: Any, name: str) -> bool | None: ...

    def opt_parm_int(self, node: Any, name: str) -> int | None: ...

    def opt_parm_float(self, node: Any, name: str) -> float | None: ...

    def as_dcc_path(self, path: str) -> str: ...


def debug_logger(prefix: str, sink: Callable[[str], None] | None = None) -> Callable[[str], None]:
    out = sink or print

    def _log(msg: str) -> None:
        out(f"[{prefix}] {msg}")

    return _log
