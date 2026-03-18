"""Shared dashboard helpers for DCC integrations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from .config import resolve_config_path
from .errors import BriaConfigError

DASHBOARD_LOGIN_URL = "https://platform.bria.ai/login"
DASHBOARD_API_KEYS_URL = "https://platform.bria.ai/console/account/api-keys"

_TOKEN_FIELDS_BY_DCC = {
    "houdini": (
        ("Production", "houdini_api_key"),
        ("Staging (stored only)", "houdini_api_key_staging"),
        ("ComfyUI (stored only)", "houdini_api_key_comfyui"),
        ("MCP (stored only)", "houdini_api_key_mcp"),
    ),
    "nuke": (("Production", "nuke_api_key"),),
    "toonboom": (("Production", "toonboom_api_key"),),
}

_PRIMARY_TOKEN_KEY_BY_DCC = {
    "houdini": "houdini_api_key",
    "nuke": "nuke_api_key",
    "toonboom": "toonboom_api_key",
}


def token_fields_for_dcc(dcc: str) -> Tuple[Tuple[str, str], ...]:
    dcc_key = (dcc or "").strip().lower()
    if dcc_key not in _TOKEN_FIELDS_BY_DCC:
        raise BriaConfigError(f"Unknown DCC key: {dcc}")
    return _TOKEN_FIELDS_BY_DCC[dcc_key]


def primary_token_key_for_dcc(dcc: str) -> str:
    dcc_key = (dcc or "").strip().lower()
    if dcc_key not in _PRIMARY_TOKEN_KEY_BY_DCC:
        raise BriaConfigError(f"Unknown DCC key: {dcc}")
    return _PRIMARY_TOKEN_KEY_BY_DCC[dcc_key]


def read_dashboard_config(path: Optional[Path] = None) -> Dict[str, Any]:
    cfg_path = resolve_config_path(path)
    if not cfg_path.exists():
        return {}
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise BriaConfigError(f"Invalid config file: {cfg_path} ({exc})") from exc


def write_dashboard_config(data: Mapping[str, Any], path: Optional[Path] = None) -> Path:
    cfg_path = resolve_config_path(path)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(dict(data), indent=2), encoding="utf-8")
    return cfg_path


def save_dashboard_tokens(tokens: Mapping[str, str], path: Optional[Path] = None) -> int:
    data = read_dashboard_config(path)
    updated = 0
    for key, value in tokens.items():
        token = str(value or "").strip()
        if not token:
            continue
        data[key] = token
        updated += 1
    if updated > 0:
        write_dashboard_config(data, path)
    return updated


def clear_dashboard_tokens(keys: Iterable[str], path: Optional[Path] = None) -> int:
    data = read_dashboard_config(path)
    removed = 0
    for key in keys:
        if key in data:
            data.pop(key, None)
            removed += 1
    if removed > 0:
        write_dashboard_config(data, path)
    return removed


def has_any_dashboard_token(data: Mapping[str, Any], fields: Sequence[Tuple[str, str]]) -> bool:
    return any(bool(str(data.get(key) or "").strip()) for _label, key in fields)
