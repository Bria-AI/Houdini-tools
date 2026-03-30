"""Centralized logging for bria_core."""

from __future__ import annotations

import logging
import os
from typing import Optional

_DEFAULT_LEVEL = os.getenv("BRIA_LOG_LEVEL", "WARNING").upper()


def configure_logging(level: Optional[str] = None) -> None:
    """Configure root logger for bria_core usage."""
    lvl = (level or _DEFAULT_LEVEL).upper()
    logging.basicConfig(
        level=getattr(logging, lvl, logging.INFO),
        format="[%(asctime)s][%(levelname)s][%(name)s] %(message)s",
    )


def get_logger(name: str = "bria") -> logging.Logger:
    """Get a logger instance for bria_core."""
    return logging.getLogger(name)
