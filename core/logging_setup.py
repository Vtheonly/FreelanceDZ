"""Centralised logging configuration.

Provides a single entry point (`configure_logging`) so every CLI command and
the FastAPI server use the same format, handlers, and verbosity.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional


# Log line format optimised for both human reading and grep-ability.
_LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)-25s : %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(
    level: str = "INFO",
    log_dir: Optional[Path] = None,
    file_name: str = "dz_sales_intel.log",
) -> None:
    """Configure root logger once.

    Args:
        level: DEBUG | INFO | WARNING | ERROR (case-insensitive).
        log_dir: If provided, also writes to a rotating file in this directory.
        file_name: Log file name inside `log_dir`.
    """
    root = logging.getLogger()
    # Reset any pre-existing handlers (e.g. from pytest or imports).
    for h in list(root.handlers):
        root.removeHandler(h)

    log_level = getattr(logging, level.upper(), logging.INFO)
    root.setLevel(log_level)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # Console handler — always present.
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(log_level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # Optional rotating file handler (10 MB × 5 files).
    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / file_name,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # Quiet down noisy third-party loggers.
    for noisy in ("urllib3", "httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Convenience wrapper."""
    return logging.getLogger(name)
