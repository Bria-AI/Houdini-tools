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


def _ensure_ssl_cert_file(logger) -> None:
    """Ensure embedded Python can validate HTTPS certificates.

    - On macOS: auto-detect a CA bundle when SSL_CERT_FILE is missing/invalid.
    - On non-macOS: clear macOS placeholder values if they were injected by package env.
    """
    current = (os.getenv("SSL_CERT_FILE") or "").strip()

    mac_candidates = (
        "/etc/ssl/cert.pem",
        "/private/etc/ssl/cert.pem",
        "/opt/homebrew/etc/ca-certificates/cert.pem",
    )

    if sys.platform == "darwin":
        if current and os.path.exists(current):
            return

        for candidate in mac_candidates:
            if os.path.exists(candidate):
                os.environ["SSL_CERT_FILE"] = candidate
                os.environ.setdefault("REQUESTS_CA_BUNDLE", candidate)
                os.environ.setdefault("BRIA_CA_BUNDLE", candidate)
                logger.info("Bria bootstrap set SSL_CERT_FILE=%s", candidate)
                return

        logger.warning("Bria bootstrap could not find a macOS CA bundle for SSL_CERT_FILE")
        return

    # Non-macOS safety: if package env injected a macOS placeholder path, unset it.
    if current in mac_candidates and not os.path.exists(current):
        os.environ.pop("SSL_CERT_FILE", None)
        if (os.getenv("REQUESTS_CA_BUNDLE") or "").strip() == current:
            os.environ.pop("REQUESTS_CA_BUNDLE", None)
        if (os.getenv("BRIA_CA_BUNDLE") or "").strip() == current:
            os.environ.pop("BRIA_CA_BUNDLE", None)
        logger.info("Bria bootstrap cleared macOS SSL_CERT_FILE placeholder on non-macOS")


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
            print(
                f"[Bria] Bootstrap OK | endpoint={status['resolved_endpoint']} | env_override={status['using_env_override']}"
            )
        else:
            logger.warning("Bria Houdini bootstrap: %s (%s)", status["message"], status["reason"])
            print(f"[Bria] Bootstrap WARNING | {status['message']} ({status['reason']})")
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
