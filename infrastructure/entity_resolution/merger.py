"""Golden-record merger — combines duplicate records into one rich entity.

Strategy:
1. Pick the most *complete* record as the base (most non-null fields).
2. Fill any missing field on the base with values from the duplicates.
3. Union list-valued fields (phones, socials) across all duplicates.
4. Compute a confidence score: the fraction of base fields that had
   corroboration from at least one duplicate.
"""

from __future__ import annotations

import logging
from typing import Any

from domain.enums import EntityType, ResolutionStrategy
from domain.models import RawRecord, ResolvedEntity


_logger = logging.getLogger("entity_resolution.merger")


class GoldenRecordMerger:
    """Merge a list of duplicate ``RawRecord`` into one ``ResolvedEntity``."""

    def merge(self, records: list[RawRecord]) -> ResolvedEntity:
        if not records:
            raise ValueError("Cannot merge an empty record list.")
        if len(records) == 1:
            return self._single_entity(records[0])

        # Sort by completeness (desc) — most complete first.
        sorted_records = sorted(records, key=self._completeness, reverse=True)
        base = sorted_records[0]

        phones: set[str] = set()
        socials: set[str] = set()
        raw_ids: list[int] = []
        corroborated_fields: int = 0

        for rec in records:
            if rec.id is not None:
                raw_ids.append(rec.id)
            if rec.phone:
                phones.add(rec.phone)
            for p in rec.phone_metadata:
                phones.add(p.e164)
            socials.update(rec.social_media_handles or [])

        # Build the merged entity.
        entity = ResolvedEntity(
            entity_type=EntityType.BUSINESS,
            name=base.name,
            industry=base.industry,
            wilaya=base.wilaya,
            address=self._pick_best([r.address for r in records if r.address]),
            website=self._pick_best([r.website for r in records if r.website]),
            phone=base.phone,
            email=self._pick_best([r.email for r in records if r.email]),
            social_media_handles=sorted(socials),
            phones=sorted(phones),
            rating=max((r.rating for r in records), default=0.0),
            review_count=max((r.review_count for r in records), default=0),
            latitude=base.latitude,
            longitude=base.longitude,
            confidence=self._confidence(records, corroborated_fields),
            strategy=ResolutionStrategy.GRAPH_MERGE,
            raw_record_ids=raw_ids,
        )
        _logger.debug(
            "Merged %d records → entity %r (phones=%d, socials=%d, confidence=%.2f)",
            len(records), entity.name, len(entity.phones), len(entity.social_media_handles),
            entity.confidence,
        )
        return entity

    # ------------------------------------------------------------------

    def _single_entity(self, rec: RawRecord) -> ResolvedEntity:
        return ResolvedEntity(
            entity_type=EntityType.BUSINESS,
            name=rec.name,
            industry=rec.industry,
            wilaya=rec.wilaya,
            address=rec.address,
            website=rec.website,
            phone=rec.phone,
            email=rec.email,
            social_media_handles=list(rec.social_media_handles or []),
            phones=[rec.phone] if rec.phone else [],
            rating=rec.rating,
            review_count=rec.review_count,
            latitude=rec.latitude,
            longitude=rec.longitude,
            confidence=1.0,
            strategy=ResolutionStrategy.SINGLE,
            raw_record_ids=[rec.id] if rec.id is not None else [],
        )

    @staticmethod
    def _completeness(rec: RawRecord) -> int:
        """Count non-empty fields — used to pick the base record."""
        score = 0
        for value in (rec.name, rec.address, rec.website, rec.phone, rec.email,
                      rec.industry, rec.wilaya):
            if value:
                score += 1
        score += len(rec.social_media_handles or [])
        score += len(rec.phone_metadata or [])
        return score

    @staticmethod
    def _pick_best(values: list[str]) -> str | None:
        """Return the longest non-empty value (heuristic for 'most specific')."""
        if not values:
            return None
        return max(values, key=len)

    @staticmethod
    def _confidence(records: list[RawRecord], corroborated: int) -> float:
        """Confidence in the merge — more records = higher confidence."""
        if len(records) <= 1:
            return 1.0
        # Diminishing returns: 2 records → 0.9, 3 → 0.95, 5+ → ~0.99.
        return min(0.99, 0.7 + 0.1 * len(records))
