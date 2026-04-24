"""Configuration resolution (env + config file)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .errors import BriaConfigError

DEFAULT_ENDPOINT = "https://engine.prod.bria-api.com/v2"
DEFAULT_CONFIG_PATH = Path("~/.bria/bria.json").expanduser()

_ENV_API_ENDPOINT = "BRIA_API_ENDPOINT"
_ENV_RMBG_ENDPOINT = "BRIA_RMBG_ENDPOINT"
_ENV_CONFIG_PATH = "BRIA_CONFIG_PATH"
_ENV_KEYS = {
    "houdini": "BRIA_API_KEY_HOUDINI",
    "nuke": "BRIA_API_KEY_NUKE",
    "toonboom": "BRIA_API_KEY_TOONBOOM",
}


@dataclass(frozen=True)
class BriaConfig:
    api_endpoint: str
    rmbg_endpoint: Optional[str] = None
    houdini_api_key: Optional[str] = None
    nuke_api_key: Optional[str] = None
    toonboom_api_key: Optional[str] = None
    houdini_output_dir: Optional[str] = None
    use_bria_project_path: Optional[bool] = None
    default_timeout: Optional[int] = None
    cache_enabled: Optional[bool] = None
    use_temp_dir: Optional[bool] = None


def _read_config_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise BriaConfigError(f"Invalid config file: {path} ({exc})") from exc


def resolve_config_path(path: Optional[Path] = None) -> Path:
    """Resolve config path with precedence: explicit arg > env > default."""
    if path is not None:
        return path
    env_path = os.getenv(_ENV_CONFIG_PATH)
    if env_path:
        return Path(env_path).expanduser()
    return DEFAULT_CONFIG_PATH


def load_config(path: Optional[Path] = None) -> BriaConfig:
    """Load config with defaults; env overrides are resolved separately."""
    cfg_path = resolve_config_path(path)
    data = _read_config_file(cfg_path)

    return BriaConfig(
        api_endpoint=data.get("api_endpoint") or DEFAULT_ENDPOINT,
        rmbg_endpoint=data.get("rmbg_endpoint"),
        houdini_api_key=data.get("houdini_api_key"),
        nuke_api_key=data.get("nuke_api_key"),
        toonboom_api_key=data.get("toonboom_api_key"),
        houdini_output_dir=data.get("houdini_output_dir"),
        use_bria_project_path=data.get("use_bria_project_path"),
        default_timeout=data.get("default_timeout"),
        cache_enabled=data.get("cache_enabled"),
        use_temp_dir=data.get("use_temp_dir"),
    )


def resolve_api_endpoint(config: Optional[BriaConfig] = None) -> str:
    """Resolve endpoint with precedence: env > config > default."""
    env_val = os.getenv(_ENV_API_ENDPOINT)
    if env_val:
        return env_val.strip()
    cfg = config or load_config()
    return (cfg.api_endpoint or DEFAULT_ENDPOINT).strip()


def resolve_rmbg_endpoint(config: Optional[BriaConfig] = None) -> str:
    """Resolve RMBG endpoint with precedence: env > config > api_endpoint."""
    env_val = os.getenv(_ENV_RMBG_ENDPOINT)
    if env_val:
        return env_val.strip()
    cfg = config or load_config()
    if cfg.rmbg_endpoint:
        return cfg.rmbg_endpoint.strip()
    return resolve_api_endpoint(cfg)


def resolve_api_key(dcc: str, config: Optional[BriaConfig] = None) -> str:
    """Resolve API key with precedence: config > env > error."""
    dcc_key = dcc.strip().lower()
    if dcc_key not in _ENV_KEYS:
        raise BriaConfigError(f"Unknown DCC key: {dcc}")

    cfg = config or load_config()
    key = getattr(cfg, f"{dcc_key}_api_key", None)
    if key:
        return str(key).strip()

    # Convenience fallback: Nuke can reuse Houdini key when dedicated key is absent.
    if dcc_key == "nuke" and cfg.houdini_api_key:
        return str(cfg.houdini_api_key).strip()

    env_name = _ENV_KEYS[dcc_key]
    env_val = os.getenv(env_name)
    if env_val:
        return env_val.strip()

    if dcc_key == "nuke":
        env_val_hou = os.getenv(_ENV_KEYS["houdini"])
        if env_val_hou:
            return env_val_hou.strip()

    raise BriaConfigError(
        f"Missing API key for {dcc_key}. Add {dcc_key}_api_key to {DEFAULT_CONFIG_PATH} or set {env_name}"
    )
