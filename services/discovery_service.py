"""Discovery service — orchestrates the aggregator and persists raw records.

This is the entry point for every "find me N businesses" request. It:

1. Builds the aggregator with the configured scrapers.
2. Runs the exhaustive discovery loop.
3. Persists every discovered ``BusinessRaw`` into ``raw_records``.
4. Returns a summary (count saved, count skipped as duplicates).

The service is async throughout and uses ``BackgroundTasks``-friendly
semantics — long-running crawls can be kicked off without blocking the
API response.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from core.interfaces import IDiscoveryAggregator, IRawRecordRepository
from domain.models import BusinessRaw


_logger = logging.getLogger("services.discovery")


@dataclass(slots=True)
class DiscoveryResult:
    """Outcome of a discovery run — surfaced to the API as JSON."""
    query: str
    wilaya: Optional[str]
    requested_limit: int
    discovered_count: int
    saved_count: int
    duplicate_count: int

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "wilaya": self.wilaya,
            "requested_limit": self.requested_limit,
            "discovered_count": self.discovered_count,
            "saved_count": self.saved_count,
            "duplicate_count": self.duplicate_count,
        }


class DiscoveryService:
    """Orchestrates discovery and persistence."""

    def __init__(
        self,
        aggregator: IDiscoveryAggregator,
        raw_repo: IRawRecordRepository,
    ) -> None:
        self._aggregator = aggregator
        self._repo = raw_repo

    async def discover(
        self,
        query: str,
        wilaya: Optional[str] = None,
        limit: int = 30,
    ) -> DiscoveryResult:
        """Run an exhaustive discovery campaign and persist the results."""
        _logger.info("Discovery start: query=%r wilaya=%r limit=%d", query, wilaya, limit)
        businesses = await self._aggregator.discover_exhaustive(
            query=query, wilaya=wilaya, limit=limit
        )
        saved = 0
        duplicates = 0
        for biz in businesses:
            row_id = await self._repo.save(biz)
            if row_id is not None:
                saved += 1
                _logger.info("Saved lead id=%d: %s", row_id, biz.name)
            else:
                duplicates += 1
                _logger.debug("Skipped duplicate: %s", biz.name)
        result = DiscoveryResult(
            query=query,
            wilaya=wilaya,
            requested_limit=limit,
            discovered_count=len(businesses),
            saved_count=saved,
            duplicate_count=duplicates,
        )
        _logger.info(
            "Discovery complete: %d discovered, %d new, %d duplicates",
            result.discovered_count, result.saved_count, result.duplicate_count,
        )
        return result

    async def discover_many(
        self,
        queries: list[str],
        wilaya: Optional[str] = None,
        limit_per_query: int = 20,
    ) -> list[DiscoveryResult]:
        """Run discovery for multiple queries in sequence."""
        results: list[DiscoveryResult] = []
        for q in queries:
            res = await self.discover(query=q, wilaya=wilaya, limit=limit_per_query)
            results.append(res)
        return results
