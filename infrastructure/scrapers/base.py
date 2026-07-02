"""Abstract base class for every async scraper.

Provides shared infrastructure:
  * HTTP client injection (the managed singleton from ``HttpClientFactory``).
  * Spam-filter wiring so subclasses don't re-implement it.
  * Jitter injection between requests (politeness).
  * Concurrency cap via ``AsyncRateLimiter``.
  * Structured logging with the scraper's source name.

Subclasses only implement ``discover()`` — everything else is handled
here.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

import httpx

from core.interfaces import IScraper
from domain.models import BusinessRaw
from infrastructure.http.rate_limiter import AsyncRateLimiter, DomainRateLimiter
from utils.anti_block_engine import CrawlerAntiBlockEngine
from utils.spam_filter import SourcingSpamFilter


class BaseAsyncScraper(IScraper, ABC):
    """Common scaffolding for async scrapers.

    Parameters
    ----------
    client:
        The shared ``httpx.AsyncClient``. Injected so tests can pass a
        mock client.
    spam_filter:
        Optional custom spam filter. Defaults to the standard
        ``SourcingSpamFilter``.
    rate_limiter:
        Optional global concurrency cap. Defaults to ``AsyncRateLimiter``.
    domain_limiter:
        Optional per-domain politeness limiter. Defaults to
        ``DomainRateLimiter`` configured from settings.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        spam_filter: Optional[SourcingSpamFilter] = None,
        rate_limiter: Optional[AsyncRateLimiter] = None,
        domain_limiter: Optional[DomainRateLimiter] = None,
    ) -> None:
        self.client = client
        self._spam_filter = spam_filter or SourcingSpamFilter()
        self._rate_limiter = rate_limiter or AsyncRateLimiter()
        self._domain_limiter = domain_limiter or DomainRateLimiter()
        self._anti_block = CrawlerAntiBlockEngine()
        self._logger = logging.getLogger(f"scrapers.{self.source_name}")

    # ------------------------------------------------------------------
    #  IScraper contract
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Short, stable identifier (e.g. 'duckduckgo', 'overpass')."""

    @abstractmethod
    async def discover(
        self,
        query: str,
        wilaya: Optional[str] = None,
        limit: int = 10,
    ) -> list[BusinessRaw]:
        ...

    # ------------------------------------------------------------------
    #  Shared helpers (used by subclasses)
    # ------------------------------------------------------------------

    async def _fetch(
        self,
        url: str,
        *,
        params: Optional[dict[str, str]] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
        mobile: bool = False,
    ) -> Optional[httpx.Response]:
        """Fetch a URL with rate-limiting, jitter, and spam filtering.

        Returns ``None`` on any failure (network error, spam-detected
        target, non-200 status). Subclasses should treat ``None`` as
        "skip this URL" and continue with the next candidate.
        """
        if self._spam_filter.is_spam(url, ""):
            self._logger.debug("Spam-filtered URL skipped: %s", url)
            return None

        host = _host_of(url)
        final_headers = headers or self._anti_block.generate_headers(host=host, mobile=mobile)

        try:
            async with self._rate_limiter.acquire():
                async with self._domain_limiter.politeness(url):
                    await self._anti_block.introduce_jitter(base_delay=0.5)
                    response = await self.client.get(
                        url,
                        params=params,
                        headers=final_headers,
                        timeout=timeout or 15.0,
                    )
                    if response.status_code != 200:
                        self._logger.debug(
                            "Non-200 (%d) from %s", response.status_code, url,
                        )
                        return None
                    return response
        except httpx.HTTPError as exc:
            self._logger.debug("Network error fetching %s: %s", url, exc)
            return None
        except Exception as exc:
            self._logger.debug("Unexpected error fetching %s: %s", url, exc)
            return None


def _host_of(url: str) -> str:
    """Extract the Host header value from a URL (without scheme/path)."""
    from urllib.parse import urlparse
    return urlparse(url).netloc
