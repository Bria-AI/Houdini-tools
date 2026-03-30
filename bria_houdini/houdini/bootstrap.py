"""Houdini bootstrap stub.

Runs on package load to validate config and log status.
This module should not modify the scene or create nodes.
"""

from __future__ import annotations

try:
    import hou  # type: ignore
except Exception:  # pragma: no cover - only available inside Houdini
    hou = None

import os
import sys

from bria_core import load_config, resolve_api_endpoint, resolve_api_key, get_status
from bria_core.logging import configure_logging, get_logger
from bria_core.errors import BriaConfigError


_CA_BUNDLE_CANDIDATES = (
    "/etc/ssl/cert.pem",                          # macOS, some Linux
    "/etc/ssl/certs/ca-certificates.crt",          # Debian/Ubuntu
    "/etc/pki/tls/certs/ca-bundle.crt",            # RHEL/CentOS/Fedora
    "/etc/ssl/ca-bundle.pem",                      # openSUSE
    "/private/etc/ssl/cert.pem",                   # macOS alternate
    "/opt/homebrew/etc/ca-certificates/cert.pem",  # Homebrew macOS
)


def _ensure_ssl_cert_file(logger) -> None:
    """Ensure embedded Python can validate HTTPS certificates.

    On macOS/Linux: auto-detect a CA bundle when SSL_CERT_FILE is missing/invalid.
    On Windows: clear any invalid SSL_CERT_FILE and let Python use the native cert store.
    """
    current = (os.getenv("SSL_CERT_FILE") or "").strip()

    if current and os.path.exists(current):
        return

    if current and not os.path.exists(current):
        os.environ.pop("SSL_CERT_FILE", None)
        logger.info("Bria bootstrap cleared invalid SSL_CERT_FILE=%s", current)

    if sys.platform == "win32":
        return

    for candidate in _CA_BUNDLE_CANDIDATES:
        if os.path.exists(candidate):
            os.environ["SSL_CERT_FILE"] = candidate
            os.environ.setdefault("REQUESTS_CA_BUNDLE", candidate)
            os.environ.setdefault("BRIA_CA_BUNDLE", candidate)
            logger.info("Bria bootstrap set SSL_CERT_FILE=%s", candidate)
            return

    logger.warning("Bria bootstrap could not find a CA bundle for SSL_CERT_FILE")


def init() -> None:
    configure_logging()
    logger = get_logger("houdini.bootstrap")

    try:
        _ensure_ssl_cert_file(logger)

        do_ping = os.getenv("BRIA_BOOTSTRAP_PING", "").strip().lower() in ("1", "true", "yes")
        status = get_status(dcc="houdini", check_network=do_ping, timeout_s=3)
        if status["ok"]:
            logger.info(
                "Bria Houdini bootstrap OK | endpoint=%s | env_override=%s",
                status["resolved_endpoint"],
                status["using_env_override"],
            )
        else:
            logger.warning("Bria Houdini bootstrap: %s (%s)", status["message"], status["reason"])
            if hou is not None and getattr(hou, "isUIAvailable", lambda: False)():
                try:
                    hou.ui.setStatusMessage(status["message"], severity=hou.severityType.Warning)
                except Exception:
                    pass
    except BriaConfigError as exc:
        logger.warning("Bria Houdini bootstrap config error: %s", exc)
        if hou is not None and getattr(hou, "isUIAvailable", lambda: False)():
            try:
                hou.ui.setStatusMessage(str(exc), severity=hou.severityType.Warning)
            except Exception:
                pass
    except Exception as exc:
        logger.exception("Bria Houdini bootstrap failed (non-fatal): %s", exc)
