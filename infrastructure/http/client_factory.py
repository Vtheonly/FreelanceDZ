"""Managed ``httpx.AsyncClient`` factory.

Creating a new ``httpx.AsyncClient`` per request leaks sockets and
exhausts file descriptors under load. This module provides a single,
long-lived client configured from ``AppSettings`` and shared across the
whole engine.

The factory is intentionally minimal — it does not implement the
``IHttpClient`` protocol because ``httpx.AsyncClient`` already satisfies
it structurally. Tests can substitute a custom client by passing it to
the service constructors directly.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from config.settings import AppSettings, get_settings


_logger = logging.getLogger("infrastructure.http")


class HttpClientFactory:
    """Create and cache a singleton ``httpx.AsyncClient``.

    The first call to ``get_client()`` creates the client; subsequent
    calls return the same instance. ``close()`` releases it.

    The factory is safe to use from multiple coroutines — there is no
    mutation after the client is created.
    """

    _client: Optional[httpx.AsyncClient] = None
    _settings: Optional[AppSettings] = None

    @classmethod
    def get_client(cls, settings: Optional[AppSettings] = None) -> httpx.AsyncClient:
        """Return the shared client, creating it on first call."""
        if cls._client is not None and not cls._client.is_closed:
            return cls._client

        settings = settings or get_settings()
        cls._settings = settings

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
        cls._client = httpx.AsyncClient(
            limits=limits,
            timeout=timeout,
            http2=settings.HTTP_ENABLE_HTTP2,
            follow_redirects=True,
        )
        _logger.info(
            "HTTP client created (max_connections=%d, http2=%s, read_timeout=%ds)",
            settings.HTTP_MAX_CONNECTIONS,
            settings.HTTP_ENABLE_HTTP2,
            settings.SCRAPER_TIMEOUT_SECONDS,
        )
        return cls._client

    @classmethod
    async def close(cls) -> None:
        """Close the shared client if it exists. Safe to call multiple times."""
        if cls._client is None:
            return
        if not cls._client.is_closed:
            await cls._client.aclose()
        cls._client = None
        _logger.debug("HTTP client closed.")

    @classmethod
    def reset(cls) -> None:
        """Force the next ``get_client()`` call to create a fresh client.

        Useful in tests that need to swap the underlying client between
        test cases without restarting the process.
        """
        cls._client = None
        cls._settings = None
