"""Application lifecycle helpers.

Centralises the bootstrapping steps that every entry point (CLI, API,
infinite crawler) needs to perform:

1. Load and validate configuration.
2. Configure structured logging.
3. Ensure data directories exist.
4. Initialise the database schema (idempotent).
5. Provide a shared ``httpx.AsyncClient`` singleton.
6. Tear everything down cleanly on shutdown.

Used as an async context manager so resources are guaranteed to be
released even when an exception is raised mid-run.

Example
-------
.. code-block:: python

    async with ApplicationLifecycle.create() as lifecycle:
        crawler = AutonomousInfiniteCrawler(lifecycle)
        await crawler.run()
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Optional

import httpx

from config.settings import AppSettings, get_settings
from core.logging_setup import configure_logging


_logger = logging.getLogger("core.lifecycle")


@dataclass(slots=True)
class ApplicationLifecycle:
    """Bundle of resources owned by a single application run.

    Every field is a *managed* resource that must be closed on shutdown.
    Holding them in a single dataclass makes the teardown code trivial
    and lets tests substitute individual components.
    """

    settings: AppSettings
    http_client: httpx.AsyncClient
    logger: logging.Logger

    async def aclose(self) -> None:
        """Release every managed resource. Safe to call multiple times."""
        if not self.http_client.is_closed:
            await self.http_client.aclose()
        self.logger.debug("ApplicationLifecycle closed.")

    @classmethod
    @asynccontextmanager
    async def create(
        cls,
        settings: Optional[AppSettings] = None,
        log_format: str = "console",
    ) -> AsyncIterator["ApplicationLifecycle"]:
        """Bootstrap the engine and yield a ready-to-use lifecycle.

        Parameters
        ----------
        settings:
            Optional pre-built settings. When ``None``, the cached
            singleton from ``config.settings.get_settings()`` is used.
        log_format:
            ``"console"`` (default) or ``"json"``.
        """
        settings = settings or get_settings()
        settings.ensure_directories()

        logger = configure_logging(
            level=settings.LOG_LEVEL,
            log_dir=Path(settings.LOG_DIR),
            log_format=log_format,
        )
        logger.info(
            "Bootstrapping %s v%s (log_level=%s, db=%s)",
            settings.APP_NAME,
            settings.APP_VERSION,
            settings.LOG_LEVEL,
            settings.DATABASE_PATH,
        )

        limits = httpx.Limits(
            max_keepalive_connections=settings.HTTP_KEEPALIVE_CONNECTIONS,
            max_connections=settings.HTTP_MAX_CONNECTIONS,
            keepalive_expiry=settings.HTTP_KEEPALIVE_EXPIRY,
        )
        timeout = httpx.Timeout(
            connect=settings.HTTP_CONNECT_TIMEOUT,
            read=settings.SCRAPER_TIMEOUT_SECONDS,
            write=10.0,
            pool=settings.HTTP_POOL_TIMEOUT,
        )

        http_client = httpx.AsyncClient(
            limits=limits,
            timeout=timeout,
            http2=settings.HTTP_ENABLE_HTTP2,
            follow_redirects=True,
        )
        logger.debug(
            "HTTP client initialised (max_connections=%d, http2=%s)",
            settings.HTTP_MAX_CONNECTIONS,
            settings.HTTP_ENABLE_HTTP2,
        )

        lifecycle = cls(settings=settings, http_client=http_client, logger=logger)
        try:
            yield lifecycle
        finally:
            await lifecycle.aclose()
            logger.info("ApplicationLifecycle shutdown complete.")
