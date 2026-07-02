"""Tests for the entity resolver."""

from __future__ import annotations

from datetime import datetime, timezone

from domain.enums import DataSource, FreshnessAge
from domain.models import RawRecord
from domain.value_objects import FreshnessMetadata
from infrastructure.entity_resolution.graph_resolver import GraphEntityResolver
from infrastructure.entity_resolution.similarity import (
    jaccard_similarity,
    levenshtein_ratio,
)


def _make_raw(name: str, website: str | None = None, phone: str | None = None, id_: int = 1) -> RawRecord:
    return RawRecord(
        id=id_,
        fingerprint=f"{name.lower()}|{website or ''}|{phone or ''}",
        name=name,
        industry="Test",
        wilaya="Algiers",
        website=website,
        phone=phone,
        email=None,
        social_media_handles=[],
        rating=0.0,
        review_count=0,
        latitude=None,
        longitude=None,
        source=DataSource.MOCK,
        source_url=website,
        phone_metadata=[],
        freshness=FreshnessMetadata(),
        discovered_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )


def test_levenshtein_identical():
    assert levenshtein_ratio("pharmacie", "pharmacie") == 1.0


def test_levenshtein_different():
    assert levenshtein_ratio("pharmacie", "restaurant") < 0.5


def test_jaccard_full_overlap():
    assert jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0


def test_jaccard_no_overlap():
    assert jaccard_similarity({"a"}, {"b"}) == 0.0


def test_resolver_merges_duplicates():
    r1 = _make_raw("Pharmacie Centrale", website="https://centrale.dz", phone="+213555111222", id_=1)
    r2 = _make_raw("Pharmacie Centrale", website="https://centrale.dz", phone="+213555111222", id_=2)
    resolver = GraphEntityResolver()
    import asyncio
    entities = asyncio.run(resolver.resolve([r1, r2]))
    assert len(entities) == 1
    assert entities[0].raw_record_ids == [1, 2]


def test_resolver_keeps_distinct():
    r1 = _make_raw("Pharmacie Centrale", website="https://centrale.dz", id_=1)
    r2 = _make_raw("Restaurant Le Port", website="https://leport.dz", id_=2)
    resolver = GraphEntityResolver()
    import asyncio
    entities = asyncio.run(resolver.resolve([r1, r2]))
    assert len(entities) == 2


def test_resolver_single_record():
    r1 = _make_raw("Solo Business", website="https://solo.dz", id_=1)
    resolver = GraphEntityResolver()
    import asyncio
    entities = asyncio.run(resolver.resolve([r1]))
    assert len(entities) == 1
    assert entities[0].confidence == 1.0
