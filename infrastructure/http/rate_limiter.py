"""Async rate limiters.

Two complementary limiters are provided:

* ``AsyncRateLimiter`` — a global semaphore that caps the total number
  of concurrent HTTP requests across the whole engine. Protects against
  socket exhaustion and aggressive-rate-limit bans.

* ``DomainRateLimiter`` — a per-domain lock that serialises requests to
  the same host and enforces a minimum delay between them. Implements
  the politeness policy required by ethical crawlers.

Both limiters are async-context-manager compatible and re-entrant within
the same coroutine (a coroutine that already holds the lock will not
deadlock itself — though re-entrancy is discouraged in practice).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from config.settings import get_settings
from utils.url_utils import domain_of


_logger = logging.getLogger("infrastructure.http.rate_limiter")


class AsyncRateLimiter:
    """Global concurrency cap implemented as a reusable semaphore.

    The semaphore is created lazily on first use so it picks up the
    latest ``MAX_CONCURRENT_REQUESTS`` setting.
    """

    _semaphore: Optional[asyncio.Semaphore] = None
    _max_concurrency: int = 0

    @classmethod
    def _ensure_semaphore(cls) -> asyncio.Semaphore:
        if cls._semaphore is None:
            settings = get_settings()
            cls._max_concurrency = settings.MAX_CONCURRENT_REQUESTS
            cls._semaphore = asyncio.Semaphore(cls._max_concurrency)
            _logger.debug("Rate limiter initialised (max=%d)", cls._max_concurrency)
        return cls._semaphore

    @classmethod
    @asynccontextmanager
    async def acquire(cls) -> AsyncIterator[None]:
        """Acquire a slot, yield, then release."""
        sem = cls._ensure_semaphore()
        await sem.acquire()
        try:
            yield
        finally:
            sem.release()

    @classmethod
    def reset(cls) -> None:
        """Drop the cached semaphore. The next call re-creates it."""
        cls._semaphore = None
        cls._max_concurrency = 0


class DomainRateLimiter:
    """Per-domain politeness enforcer.

    Tracks the last-request timestamp for each domain and sleeps the
    minimum required delay before yielding. A separate ``asyncio.Lock``
    per domain serialises concurrent requests to the same host so the
    delay is measured between actual network sends, not between
    acquisitions.

    Usage
    -----
    .. code-block:: python

        limiter = DomainRateLimiter(delay_seconds=2.0)
        async with limiter.politeness("https://example.com/page"):
            response = await client.get(...)
    """

    def __init__(self, delay_seconds: Optional[float] = None) -> None:
        if delay_seconds is None:
            delay_seconds = get_settings().RATE_LIMIT_DELAY_SECONDS
        self._delay = max(0.0, delay_seconds)
        self._last_seen: dict[str, float] = defaultdict(lambda: 0.0)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    @asynccontextmanager
    async def politeness(self, url: str) -> AsyncIterator[None]:
        """Sleep if needed to respect the per-domain delay, then yield."""
        domain = domain_of(url)
        if not domain or self._delay <= 0:
            yield
            return

        lock = self._locks[domain]
        async with lock:
            elapsed = time.monotonic() - self._last_seen[domain]
            if elapsed < self._delay:
                wait = self._delay - elapsed
                _logger.debug("Politeness: sleeping %.2fs for domain %s", wait, domain)
                await asyncio.sleep(wait)
            self._last_seen[domain] = time.monotonic()
            yield

    def reset(self) -> None:
        """Clear all tracked timestamps (used by tests)."""
        self._last_seen.clear()
        self._locks.clear()
