"""Scraper foundations: shared fetch behaviour and the scraper protocol.

v3 folds v2's BaseAsyncScraper + AsyncRateLimiter + DomainRateLimiter into
one small module. Politeness uses the engine's per-domain token bucket
(shared across scrapers now, fixing v2's per-scraper isolated limits).
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Optional, Protocol, runtime_checkable

import httpx

from config.settings import get_settings
from engine.acquisition.rate_limiter import DomainTokenBucketLimiter
from utils.anti_block_engine import CrawlerAntiBlockEngine
from utils.spam_filter import SourcingSpamFilter

logger = logging.getLogger("scrapers.base")


@runtime_checkable
class Scraper(Protocol):
    """Every scraper streams Leads for a query."""
    source_name: str

    def stream_discover(
        self, query: str, wilaya: Optional[str], limit: int
    ) -> AsyncIterator["Lead"]: ...  # noqa: F821


class BaseAsyncScraper:
    """Shared fetch: spam filter, headers, global semaphore, domain bucket."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        spam_filter: Optional[SourcingSpamFilter] = None,
        domain_limiter: Optional[DomainTokenBucketLimiter] = None,
    ) -> None:
        self.client = client
        self._spam_filter = spam_filter or SourcingSpamFilter()
        self._anti_block = CrawlerAntiBlockEngine()
        settings = get_settings()
        self._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_REQUESTS)
        self._domain_limiter = domain_limiter or DomainTokenBucketLimiter(
            rate=settings.ACQ_DOMAIN_RATE, burst=settings.ACQ_DOMAIN_BURST
        )
        self._jitter_base = settings.JITTER_BASE_DELAY

    async def _fetch(
        self,
        url: str,
        *,
        params: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
        mobile: bool = False,
    ) -> Optional[httpx.Response]:
        """Fetch with politeness; None on any failure (skip and continue)."""
        if self._spam_filter.is_spam(url, ""):
            logger.debug("Spam-filtered URL skipped: %s", url)
            return None

        from urllib.parse import urlparse
        host = (urlparse(url).netloc or "").lower() or None
        headers = self._anti_block.generate_headers(host=host, mobile=mobile)

        try:
            async with self._semaphore:
                await self._domain_limiter.acquire(url)
                await self._anti_block.introduce_jitter(
                    base_delay=self._jitter_base * 0.5
                )
                response = await self.client.get(
                    url, params=params, headers=headers,
                    timeout=timeout or get_settings().SCRAPER_TIMEOUT_SECONDS,
                )
                if response.status_code != 200:
                    logger.debug("Non-200 (%d) from %s", response.status_code, url)
                    return None
                return response
        except httpx.HTTPError as exc:
            logger.debug("Network error fetching %s: %s", url, exc)
            return None
        except Exception as exc:
            logger.debug("Unexpected error fetching %s: %s", url, exc)
            return None
