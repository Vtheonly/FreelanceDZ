"""Exhaustive scraper aggregator.

The aggregator is the heart of the discovery system. It guarantees
that a request for N leads produces N leads whenever the underlying
sources actually have that many results — it never stops early just
because one source ran out.

Strategy
--------
1. Expand the query into FR / MSA / Darja variants (offline matrix +
   optional LLM).
2. For each variant, dispatch every enabled scraper concurrently.
3. Collect results into a single pool, deduplicating by fingerprint.
4. If the pool is below the requested limit, cycle back and try the
   next query variant.
5. Stop when the limit is reached OR every variant × every scraper has
   been exhausted.
6. Return the trimmed pool (never more than ``limit``).

The aggregator is *fault-tolerant*: a scraper that raises or returns
an empty list is logged and skipped — it never aborts the whole run.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from core.interfaces import IDiscoveryAggregator, ILLMClient, IScraper
from domain.models import BusinessRaw
from utils.query_expander import AlgerianQueryExpander


_logger = logging.getLogger("scrapers.aggregator")


class ScraperAggregator(IDiscoveryAggregator):
    """Coordinate multiple scrapers to exhaustively reach a target limit."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        scrapers: Optional[list[IScraper]] = None,
        llm: Optional[ILLMClient] = None,
        query_expander: Optional[AlgerianQueryExpander] = None,
    ) -> None:
        self._client = client
        self._scrapers = scrapers or []
        self._expander = query_expander or AlgerianQueryExpander(llm=llm)
        _logger.debug(
            "Aggregator initialised with %d scrapers: %s",
            len(self._scrapers),
            [s.source_name for s in self._scrapers],
        )

    def add_scraper(self, scraper: IScraper) -> None:
        """Register an additional scraper at runtime."""
        self._scrapers.append(scraper)
        _logger.debug("Added scraper %s (total=%d)", scraper.source_name, len(self._scrapers))

    async def discover_exhaustive(
        self,
        query: str,
        wilaya: Optional[str] = None,
        limit: int = 30,
    ) -> list[BusinessRaw]:
        """Run every scraper across every query variant until ``limit`` is met."""
        if not query or not self._scrapers:
            return []

        # 1. Expand the query into localised variants.
        variants = await self._expander.expand(query)
        if not variants:
            variants = [query]
        _logger.info(
            "Aggregator starting: query=%r variants=%d scrapers=%d limit=%d",
            query, len(variants), len(self._scrapers), limit,
        )

        pool: list[BusinessRaw] = []
        seen: set[str] = set()

        # 2. Iterate over variants; stop early once we have enough.
        for variant in variants:
            if len(pool) >= limit:
                break

            # 3. Dispatch every scraper concurrently for this variant.
            tasks = [
                self._safe_discover(scraper, variant, wilaya, limit)
                for scraper in self._scrapers
            ]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in batch_results:
                if isinstance(result, Exception):
                    _logger.warning("Scraper raised: %s", result)
                    continue
                if not result:
                    continue
                for biz in result:
                    fp = biz.fingerprint()
                    if fp in seen:
                        continue
                    seen.add(fp)
                    pool.append(biz)
                    if len(pool) >= limit:
                        break
                if len(pool) >= limit:
                    break

        _logger.info(
            "Aggregator finished: %d unique businesses (target was %d)",
            len(pool), limit,
        )
        return pool[:limit]

    # ------------------------------------------------------------------

    async def _safe_discover(
        self,
        scraper: IScraper,
        query: str,
        wilaya: Optional[str],
        limit: int,
    ) -> list[BusinessRaw]:
        """Call ``scraper.discover`` and never raise.

        Over-fetch by 2x to compensate for spam records that the
        aggregator will deduplicate out.
        """
        try:
            # Ask for 2x the limit so post-dedup we still have enough.
            over_fetch = max(limit * 2, limit + 5)
            return await scraper.discover(query=query, wilaya=wilaya, limit=over_fetch)
        except Exception as exc:
            _logger.warning(
                "Scraper %s raised during discover (%s); continuing.",
                getattr(scraper, "source_name", "?"),
                exc,
            )
            return []
