"""Auth helpers (DCC-agnostic)."""

from __future__ import annotations

from typing import Dict

from .errors import BriaAuthError


def build_headers(api_key: str, use_bearer: bool = False) -> Dict[str, str]:
    """Build request headers for Bria API."""
    if not api_key or not str(api_key).strip():
        raise BriaAuthError("API key is empty")

    token = str(api_key).strip()
    headers = {"Content-Type": "application/json"}

    if token.lower().startswith("bearer "):
        headers["Authorization"] = token
        return headers

    if use_bearer:
        headers["Authorization"] = f"Bearer {token}"
        return headers

    headers["api_token"] = token
    return headers
