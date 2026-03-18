"""Optional cache utilities (placeholder for future expansion)."""

from __future__ import annotations

from typing import Any, Dict


class MemoryCache:
    """Simple in-memory cache with string keys."""

    def __init__(self) -> None:
        self._data: Dict[str, Any] = {}

    def get(self, key: str) -> Any:
        return self._data.get(key)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
