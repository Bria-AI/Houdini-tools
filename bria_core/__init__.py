"""Bria shared core (DCC-agnostic)."""

from .version import __version__
from .client import BriaClient
from .config import (
    BriaConfig,
    load_config,
    resolve_api_endpoint,
    resolve_api_key,
    resolve_config_path,
    resolve_rmbg_endpoint,
)
from .errors import BriaError, BriaAuthError, BriaConfigError, BriaRequestError
from .status import get_status
from .dcc import DccNodeUtils, debug_logger
from .dashboard import (
    DASHBOARD_LOGIN_URL,
    DASHBOARD_API_KEYS_URL,
    token_fields_for_dcc,
    read_dashboard_config,
    write_dashboard_config,
    save_dashboard_tokens,
    clear_dashboard_tokens,
    has_any_dashboard_token,
)

__all__ = [
    "__version__",
    "BriaClient",
    "BriaConfig",
    "load_config",
    "resolve_api_endpoint",
    "resolve_rmbg_endpoint",
    "resolve_api_key",
    "resolve_config_path",
    "BriaError",
    "BriaAuthError",
    "BriaConfigError",
    "BriaRequestError",
    "get_status",
    "DccNodeUtils",
    "debug_logger",
    "DASHBOARD_LOGIN_URL",
    "DASHBOARD_API_KEYS_URL",
    "token_fields_for_dcc",
    "read_dashboard_config",
    "write_dashboard_config",
    "save_dashboard_tokens",
    "clear_dashboard_tokens",
    "has_any_dashboard_token",
]
