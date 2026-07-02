"""Base class for scraper plugins.

A plugin is a scraper that targets a *specific* platform (Facebook,
Instagram, TikTok) and accepts a profile URL rather than a free-text
query. Plugins share the same HTTP pool and anti-blocking infrastructure
as the core scrapers, but they can override the User-Agent strategy and
add platform-specific parsing.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from typing import Optional

import httpx

from core.interfaces import IScraperPlugin
from domain.models import BusinessRaw
from infrastructure.http.rate_limiter import AsyncRateLimiter, DomainRateLimiter
from infrastructure.scrapers.base import BaseAsyncScraper
from utils.anti_block_engine import CrawlerAntiBlockEngine
from utils.spam_filter import SourcingSpamFilter


class BaseScraperPlugin(BaseAsyncScraper, IScraperPlugin):
    """Common scaffolding for platform-specific scraper plugins."""

    #: The platform's main domain (e.g. ``facebook.com``).
    platform_domain: str = ""

    def __init__(
        self,
        client: httpx.AsyncClient,
        spam_filter: Optional[SourcingSpamFilter] = None,
        rate_limiter: Optional[AsyncRateLimiter] = None,
        domain_limiter: Optional[DomainRateLimiter] = None,
    ) -> None:
        super().__init__(
            client=client,
            spam_filter=spam_filter,
            rate_limiter=rate_limiter,
            domain_limiter=domain_limiter,
        )
        # Plugins use the mobile UA pool because social platforms expose
        # more public metadata to mobile clients.
        self._mobile = True

    async def discover(
        self,
        query: str,
        wilaya: Optional[str] = None,
        limit: int = 10,
    ) -> list[BusinessRaw]:
        """Plugins don't support query-based discovery — use ``scrape_target``."""
        return []

    @abstractmethod
    async def scrape_target(self, url: str) -> Optional[BusinessRaw]:
        """Scrape a single profile/page URL on this platform."""
