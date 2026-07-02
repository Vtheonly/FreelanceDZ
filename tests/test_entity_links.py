"""Tests for the entity_links join table (Task 11)."""

from __future__ import annotations

import asyncio

from domain.enums import DataSource, EntityType, ResolutionStrategy
from domain.models import BusinessRaw, ResolvedEntity
from infrastructure.storage.database import DatabaseManager
from infrastructure.storage.repositories.raw_record_repo import RawRecordRepository
from infrastructure.storage.repositories.resolved_entity_repo import ResolvedEntityRepository


def _make_business(name: str, source: DataSource = DataSource.DUCKDUCKGO) -> BusinessRaw:
    return BusinessRaw(
        name=name,
        industry="Pharmacy",
        wilaya="Oran",
        website=f"https://{name.lower().replace(' ', '')}.dz",
        phone="+213555111222",
        source=source,
    )


def test_lineage_join_table_is_populated(tmp_db):
    async def _run():
        db = DatabaseManager(db_path=tmp_db)
        raw_repo = RawRecordRepository(db)
        resolved_repo = ResolvedEntityRepository(db)

        # Insert 3 raw records so the FK constraint on entity_links passes.
        ids = []
        for name in ("Pharmacie A", "Pharmacie B", "Pharmacie C"):
            rid = await raw_repo.save(_make_business(name))
            assert rid is not None
            ids.append(rid)

        entity = ResolvedEntity(
            entity_type=EntityType.BUSINESS,
            name="Pharmacie Centrale",
            industry="Pharmacy",
            wilaya="Oran",
            website="https://centrale.dz",
            phones=["+213555111222"],
            confidence=0.9,
            strategy=ResolutionStrategy.GRAPH_MERGE,
            raw_record_ids=ids,
        )
        entity_id = await resolved_repo.upsert(entity)
        assert entity_id is not None

        # The entity_links table should have 3 rows for this entity.
        lineage = await resolved_repo.get_lineage(entity_id)
        assert len(lineage) == 3
        lineage_names = {row["name"] for row in lineage}
        assert lineage_names == {"Pharmacie A", "Pharmacie B", "Pharmacie C"}

    asyncio.run(_run())


def test_lineage_cleared_on_delete_all(tmp_db):
    async def _run():
        db = DatabaseManager(db_path=tmp_db)
        raw_repo = RawRecordRepository(db)
        resolved_repo = ResolvedEntityRepository(db)

        rid = await raw_repo.save(_make_business("Solo Pharmacy"))
        assert rid is not None

        entity = ResolvedEntity(
            name="Solo Pharmacy Golden",
            raw_record_ids=[rid],
        )
        await resolved_repo.upsert(entity)
        deleted = await resolved_repo.delete_all()
        assert deleted >= 1
        with db.connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM entity_links").fetchone()[0]
        assert count == 0

    asyncio.run(_run())


def test_lineage_replaced_on_re_upsert(tmp_db):
    """Re-resolving an entity should replace old links, not duplicate them."""
    async def _run():
        db = DatabaseManager(db_path=tmp_db)
        raw_repo = RawRecordRepository(db)
        resolved_repo = ResolvedEntityRepository(db)

        rid = await raw_repo.save(_make_business("Pharmacie X"))
        entity = ResolvedEntity(name="Pharmacie X Golden", raw_record_ids=[rid])
        entity_id = await resolved_repo.upsert(entity)

        # Upsert again with the same id — should replace, not add a duplicate.
        entity.id = entity_id
        await resolved_repo.upsert(entity)

        lineage = await resolved_repo.get_lineage(entity_id)
        assert len(lineage) == 1  # not 2

    asyncio.run(_run())
