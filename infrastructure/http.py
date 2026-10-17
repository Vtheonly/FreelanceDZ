"""Single HTTP client bootstrap (replaces the v2 lifecycle/client_factory duo).

v2 built the SAME pooled client twice — ApplicationLifecycle created one that
no CLI command ever used, while every command used HttpClientFactory's
singleton (never closed in CLI). v3 has exactly one factory.

Proxy support: httpx 0.28 rejects per-request `proxy=` kwargs on a shared
client (the v2 crawler crashed on TypeError here). We instead maintain one
dedicated AsyncClient per proxy plus one direct client, and rotate among
them via the ProxyOrchestrator.
"""

from __future__ import annotations

import logging
import random
from typing import Optional

import httpx

from config.settings import AppSettings, get_settings

logger = logging.getLogger("infrastructure.http")


class HttpClientFactory:
    _shared: Optional[httpx.AsyncClient] = None
    _proxy_clients: dict[str, httpx.AsyncClient] = {}
    _lock_cls = True  # marker: class-level singleton (single event loop by design)

    # ------------------------------------------------------------------
    @classmethod
    def _build(cls, settings: AppSettings, proxy: Optional[str] = None) -> httpx.AsyncClient:
        timeout = httpx.Timeout(
            connect=settings.HTTP_CONNECT_TIMEOUT,
            read=settings.SCRAPER_TIMEOUT_SECONDS,
            write=settings.HTTP_CONNECT_TIMEOUT,
            pool=settings.HTTP_POOL_TIMEOUT,
        )
        limits = httpx.Limits(
            max_connections=settings.HTTP_MAX_CONNECTIONS,
            max_keepalive_connections=settings.HTTP_KEEPALIVE_CONNECTIONS,
            keepalive_expiry=settings.HTTP_KEEPALIVE_EXPIRY,
        )
        return httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            http2=settings.HTTP_ENABLE_HTTP2,
            follow_redirects=True,
            proxy=proxy,
        )

    # ------------------------------------------------------------------
    @classmethod
    def get_client(cls, settings: Optional[AppSettings] = None) -> httpx.AsyncClient:
        """The shared direct-connection client (pooled, HTTP/2)."""
        if cls._shared is None or cls._shared.is_closed:
            s = settings or get_settings()
            cls._shared = cls._build(s)
            logger.info("Shared HTTP client ready (h2=%s, pool=%d)", s.HTTP_ENABLE_HTTP2, s.HTTP_MAX_CONNECTIONS)
        return cls._shared

    @classmethod
    def get_proxy_client(cls, proxy_url: str, settings: Optional[AppSettings] = None) -> httpx.AsyncClient:
        """One dedicated pooled client per proxy (created lazily)."""
        client = cls._proxy_clients.get(proxy_url)
        if client is None or client.is_closed:
            s = settings or get_settings()
            client = cls._build(s, proxy=proxy_url)
            cls._proxy_clients[proxy_url] = client
            logger.info("Proxy HTTP client ready for %s", proxy_url)
        return client

    @classmethod
    def pick_client(cls, orchestrator) -> httpx.AsyncClient:
        """Direct client, or the healthiest proxy's client when configured."""
        proxy = orchestrator.get_proxy() if orchestrator is not None else None
        if proxy:
            return cls.get_proxy_client(proxy)
        return cls.get_client()

    @classmethod
    async def close_all(cls) -> None:
        for client in [cls._shared, *cls._proxy_clients.values()]:
            if client is not None and not client.is_closed:
                await client.aclose()
        cls._shared = None
        cls._proxy_clients.clear()

    @classmethod
    def reset(cls) -> None:
        """Test hook: drop cached clients without closing (event loop gone)."""
        cls._shared = None
        cls._proxy_clients.clear()


def random_tiebreak(seq: list) -> list:
    """Shuffle a copy so repeated 'pick the first' choices spread load."""
    copy = list(seq)
    random.shuffle(copy)
    return copy
