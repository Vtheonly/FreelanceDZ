"""Scraper aggregator — runs multiple enabled scrapers and deduplicates results.

Implements the same `IScraper` interface as individual scrapers, so it can be
used transparently wherever a single scraper is expected.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from core.interfaces import IScraper
from config.settings import settings
from domain.models import BusinessRaw, DataSource
from infrastructure.scrapers.base import BaseScraper
from infrastructure.scrapers.duckduckgo import DuckDuckGoScraper
from infrastructure.scrapers.mock import MockScraper
from infrastructure.scrapers.overpass import OverpassScraper


class ScraperAggregator(BaseScraper):
    """Runs all enabled scrapers in sequence and de-duplicates by fingerprint."""

    source_name = "aggregator"

    def __init__(self, scrapers: Optional[List[IScraper]] = None) -> None:
        super().__init__()
        if scrapers is None:
            scrapers = self._default_scrapers()
        self._scrapers = scrapers
        self._logger.info(
            "ScraperAggregator initialised with: %s",
            [s.source_name for s in self._scrapers],
        )

    @staticmethod
    def _default_scrapers() -> List[IScraper]:
        """Build the default scraper list based on settings flags."""
        scrapers: List[IScraper] = []
        if settings.ENABLE_OVERPASS_SCRAPER:
            scrapers.append(OverpassScraper())
        if settings.ENABLE_DDG_SCRAPER:
            scrapers.append(DuckDuckGoScraper())
        if settings.ENABLE_MOCK_SCRAPER:
            scrapers.append(MockScraper())
        if not scrapers:
            # Always keep mock as a safety net.
            scrapers.append(MockScraper())
        return scrapers

    def discover_businesses(
        self,
        query: str,
        wilaya: Optional[str] = None,
        limit: int = 10,
    ) -> List[BusinessRaw]:
        self._logger.info("Aggregator starting discovery: query=%r wilaya=%r limit=%d", query, wilaya, limit)

        # Per-source quota — we slightly over-fetch to allow for dedup losses.
        per_source_limit = max(limit, 5)
        all_results: List[BusinessRaw] = []

        for scraper in self._scrapers:
            try:
                self._logger.debug("Running scraper: %s", scraper.source_name)
                results = scraper.discover_businesses(query, wilaya, per_source_limit)
                all_results.extend(results)
            except Exception as e:
                # A single scraper failure must NOT bring down the whole aggregator.
                self._logger.error("Scraper %s raised: %s", scraper.source_name, e)

        deduped = self._deduplicate(all_results)
        # Bias towards non-mock sources when trimming to `limit`.
        sorted_results = sorted(
            deduped,
            key=lambda b: 0 if b.source != DataSource.MOCK else 1,
        )
        final = sorted_results[:limit]
        self._logger.info(
            "Aggregator finished: %d raw → %d deduped → %d returned",
            len(all_results), len(deduped), len(final),
        )
        return final

    @staticmethod
    def _deduplicate(businesses: List[BusinessRaw]) -> List[BusinessRaw]:
        """Keep the first occurrence of each fingerprint, preferring richer records."""
        seen: dict[str, BusinessRaw] = {}
        for b in businesses:
            fp = b.fingerprint()
            if fp not in seen:
                seen[fp] = b
                continue
            # Replace if the new record is "richer" (more filled fields).
            existing_score = ScraperAggregator._richness(seen[fp])
            new_score = ScraperAggregator._richness(b)
            if new_score > existing_score:
                seen[fp] = b
        return list(seen.values())

    @staticmethod
    def _richness(b: BusinessRaw) -> int:
        """Score how complete a record is — used to pick the best of duplicates."""
        score = 0
        if b.website: score += 3
        if b.phone: score += 2
        if b.email: score += 2
        score += min(len(b.social_media_handles), 3)
        score += min(b.review_count // 50, 3)
        if b.address: score += 1
        if b.latitude is not None and b.longitude is not None: score += 1
        # Prefer real sources over mock.
        if b.source != DataSource.MOCK:
            score += 5
        return score
