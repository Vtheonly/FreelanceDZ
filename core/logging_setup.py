"""Structured logging configuration.

Design goals
------------
* **One logger per module** — callers do ``logging.getLogger(__name__)``
  and the configuration handles the rest.
* **Rotating files** — ``data/logs/deephuntr.log`` is rotated at 10 MB with
  5 backups, so long-running crawls never fill the disk.
* **Console mirror** — every log line is also echoed to stderr in a
  human-readable format for development.
* **JSON option** — set ``LOG_FORMAT=json`` to emit structured JSON lines
  suitable for ingestion by Loki / Elasticsearch / Datadog.
* **Idempotent** — calling ``configure_logging`` twice is a no-op after
  the first call, so importing modules that configure logging at import
  time cannot reconfigure the root logger.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from core.constants import APP_NAME, APP_VERSION


# Sentinel attribute used to mark a logger as "already configured by us".
_CONFIGURED_FLAG = "_deephuntr_configured"


class JsonFormatter(logging.Formatter):
    """Emit log records as single-line JSON.

    Used when ``LOG_FORMAT=json`` is requested. Every record carries the
    timestamp, level, logger name, message, and any extra fields the caller
    attached via ``logger.info("...", extra={...})``.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "app": APP_NAME,
            "version": APP_VERSION,
        }
        # Attach structured extras without overwriting reserved keys.
        reserved = set(payload.keys()) | {
            "name", "msg", "args", "levelname", "levelno", "pathname",
            "filename", "module", "exc_info", "exc_text", "stack_info",
            "lineno", "funcName", "created", "msecs", "relativeCreated",
            "thread", "threadName", "processName", "process", "getMessage",
        }
        for key, value in record.__dict__.items():
            if key not in reserved and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    """Colour-friendly console formatter with a stable column layout."""

    BASE_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)-24s : %(message)s"
    DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        # Truncate the logger name to keep the column width predictable.
        if len(record.name) > 24:
            record.name = "…" + record.name[-23:]
        return super().format(record)


def configure_logging(
    level: str = "INFO",
    log_dir: Optional[Path] = None,
    log_format: str = "console",
    filename: str = "deephuntr.log",
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """Configure the root logger exactly once.

    Parameters
    ----------
    level:
        Logging level (``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``).
    log_dir:
        Directory for rotating log files. Created if missing. When ``None``,
        only console logging is enabled.
    log_format:
        ``"console"`` (default, human-readable) or ``"json"`` (structured).
    filename:
        Name of the log file inside ``log_dir``.
    max_bytes:
        Size at which the log file is rotated.
    backup_count:
        Number of rotated backup files to keep.

    Returns
    -------
    logging.Logger
        The configured root logger.
    """
    root = logging.getLogger()
    if getattr(root, _CONFIGURED_FLAG, False):
        # Already configured — only adjust the level if the caller asked
        # for a more verbose setting than the current one.
        new_level = _level_value(level)
        if new_level < root.level:
            root.setLevel(new_level)
        return root

    root.setLevel(_level_value(level))
    root.handlers.clear()

    formatter: logging.Formatter
    if log_format.lower() == "json":
        formatter = JsonFormatter()
    else:
        formatter = ConsoleFormatter(ConsoleFormatter.BASE_FORMAT, datefmt=ConsoleFormatter.DATE_FORMAT)

    # --- Console handler (stderr) ---
    console_handler = logging.StreamHandler(stream=sys.stderr)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(root.level)
    root.addHandler(console_handler)

    # --- Rotating file handler ---
    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            filename=str(log_dir / filename),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(root.level)
        root.addHandler(file_handler)

    # --- Third-party noise reduction ---
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    setattr(root, _CONFIGURED_FLAG, True)
    return root


def get_logger(name: str) -> logging.Logger:
    """Thin convenience wrapper — equivalent to ``logging.getLogger(name)``.

    Exists so call sites read ``get_logger(__name__)`` and signal intent
    ("I want the project logger, not a random one").
    """
    return logging.getLogger(name)


def _level_value(level: str) -> int:
    return getattr(logging, level.upper(), logging.INFO)
