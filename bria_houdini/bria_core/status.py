"""Status helper for Bria integrations (pure Python)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from urllib import error as url_error
from urllib import request as url_request

from .config import DEFAULT_CONFIG_PATH, load_config, resolve_api_endpoint, resolve_api_key, resolve_config_path
from .errors import BriaConfigError


def get_status(
    dcc: str = "houdini",
    config_path: Optional[Path] = None,
    check_network: bool = False,
    session: Optional[object] = None,
    probe_url: Optional[str] = None,
    timeout_s: int = 5,
) -> Dict[str, Any]:
    """Return a status dict for the integration.

    Returns:
        ok: bool
        reason: str | None
        message: str
        resolved_endpoint: str
        using_env_override: bool
    """

    cfg_path = resolve_config_path(config_path)
    config_exists = cfg_path.exists()

    cfg = load_config(cfg_path)
    resolved_endpoint = resolve_api_endpoint(cfg)
    using_env_override = bool(os.getenv("BRIA_API_ENDPOINT"))

    api_key: Optional[str] = None
    reason: Optional[str] = None
    message = ""

    try:
        api_key = resolve_api_key(dcc, cfg)
    except BriaConfigError as exc:
        if not config_exists and not using_env_override:
            reason = "missing_config"
            message = f"Config file not found and no env overrides set ({cfg_path})."
        else:
            reason = "missing_key"
            message = str(exc)

    if reason is None and check_network:
        url = probe_url or resolved_endpoint.rstrip("/")
        try:
            req = url_request.Request(url, method="GET")
            with url_request.urlopen(req, timeout=timeout_s) as resp:
                status = resp.getcode()
                message = f"Endpoint reachable (HTTP {status})."
        except url_error.HTTPError as exc:
            # HTTPError still means the endpoint was reached and returned an HTTP response.
            message = f"Endpoint reachable (HTTP {exc.code})."
        except Exception as exc:
            reason = "network_error"
            message = f"Network error: {exc}"

    ok = reason is None
    if ok and not message:
        message = "OK"

    return {
        "ok": ok,
        "reason": reason,
        "message": message,
        "resolved_endpoint": resolved_endpoint,
        "using_env_override": using_env_override,
    }
