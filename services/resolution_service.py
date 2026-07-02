"""Resolution service — runs the entity resolver and persists golden records.

Pulls every raw record from storage, runs the graph-based resolver,
clears the previous ``resolved_entities`` table, and writes the new
golden records. Returns summary statistics for the API/UI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from core.interfaces import IEntityResolver, IRawRecordRepository, IResolvedEntityRepository


_logger = logging.getLogger("services.resolution")


@dataclass(slots=True)
class ResolutionResult:
    """Outcome of a resolution run — surfaced to the API as JSON."""
    input_count: int
    output_count: int
    compression_ratio: float
    duration_seconds: float

    def to_dict(self) -> dict:
        return {
            "input_count": self.input_count,
            "output_count": self.output_count,
            "compression_ratio": round(self.compression_ratio, 3),
            "duration_seconds": round(self.duration_seconds, 3),
        }


class ResolutionService:
    """Orchestrate entity resolution and persist the golden records."""

    def __init__(
        self,
        raw_repo: IRawRecordRepository,
        resolved_repo: IResolvedEntityRepository,
        resolver: IEntityResolver,
    ) -> None:
        self._raw_repo = raw_repo
        self._resolved_repo = resolved_repo
        self._resolver = resolver

    async def resolve_all(self, batch_size: int = 5000) -> ResolutionResult:
        """Resolve every raw record into golden entities.

        ``batch_size`` controls how many records are pulled from the DB
        at once. The resolver runs entirely in memory on the batch, so
        very large datasets should be processed in multiple calls.
        """
        import time
        start = time.monotonic()

        records = await self._raw_repo.list_all(limit=batch_size)
        _logger.info("Loaded %d raw records for resolution", len(records))
        if not records:
            return ResolutionResult(0, 0, 0.0, 0.0)

        entities = await self._resolver.resolve(records)
        _logger.info("Resolver produced %d golden entities", len(entities))

        # Clear the previous golden records and write the new ones.
        await self._resolved_repo.delete_all()
        for entity in entities:
            await self._resolved_repo.upsert(entity)

        duration = time.monotonic() - start
        ratio = len(records) / max(len(entities), 1)
        result = ResolutionResult(
            input_count=len(records),
            output_count=len(entities),
            compression_ratio=ratio,
            duration_seconds=duration,
        )
        _logger.info(
            "Resolution complete: %d → %d (ratio %.2fx) in %.2fs",
            result.input_count, result.output_count, result.compression_ratio,
            result.duration_seconds,
        )
        return result
