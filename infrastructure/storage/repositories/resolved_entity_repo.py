"""Repository for the ``resolved_entities`` table (golden records)."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from core.interfaces import IResolvedEntityRepository
from domain.enums import EntityType, ResolutionStrategy
from domain.models import ResolvedEntity
from infrastructure.storage.database import DatabaseManager


_logger = logging.getLogger("storage.resolved_entity_repo")


class ResolvedEntityRepository(IResolvedEntityRepository):
    """CRUD for ``resolved_entities``."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def upsert(self, entity: ResolvedEntity) -> Optional[int]:
        """Insert (or update by id) and return the row id.

        Also populates the ``entity_links`` join table so callers can run
        SQL-grade lineage queries without parsing the ``raw_record_ids``
        JSON array.
        """
        social_json = json.dumps(entity.social_media_handles, ensure_ascii=False)
        phones_json = json.dumps(entity.phones, ensure_ascii=False)
        raw_ids_json = json.dumps(entity.raw_record_ids, ensure_ascii=False)
        now = _now_iso()
        # The ``phone`` column stores the primary phone (first in the list)
        # for backward compatibility with the leads view; ``phones`` stores
        # the full JSON array.
        primary_phone = entity.phones[0] if entity.phones else None

        def _execute():
            with self._db.connection() as conn:
                if entity.id is not None:
                    conn.execute(
                        """
                        UPDATE resolved_entities SET
                            entity_type=?, name=?, industry=?, wilaya=?, address=?,
                            website=?, phone=?, email=?, social_media_handles=?,
                            phones=?, rating=?, review_count=?, latitude=?, longitude=?,
                            confidence=?, strategy=?, raw_record_ids=?, last_resolved_at=?
                        WHERE id=?
                        """,
                        (
                            entity.entity_type.value, entity.name, entity.industry,
                            entity.wilaya, entity.address, entity.website, primary_phone,
                            entity.email, social_json, phones_json, entity.rating,
                            entity.review_count, entity.latitude, entity.longitude,
                            entity.confidence, entity.strategy.value, raw_ids_json, now,
                            entity.id,
                        ),
                    )
                    row_id = entity.id
                else:
                    cursor = conn.execute(
                        """
                        INSERT INTO resolved_entities (
                            entity_type, name, industry, wilaya, address, website, phone,
                            email, social_media_handles, phones, rating, review_count,
                            latitude, longitude, confidence, strategy, raw_record_ids,
                            last_resolved_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            entity.entity_type.value, entity.name, entity.industry,
                            entity.wilaya, entity.address, entity.website, primary_phone,
                            entity.email, social_json, phones_json, entity.rating,
                            entity.review_count, entity.latitude, entity.longitude,
                            entity.confidence, entity.strategy.value, raw_ids_json, now,
                        ),
                    )
                    row_id = cursor.lastrowid
                    if not row_id:
                        row = conn.execute(
                            "SELECT id FROM resolved_entities WHERE name = ? ORDER BY id DESC LIMIT 1",
                            (entity.name,),
                        ).fetchone()
                        row_id = row["id"] if row else None

                # Populate the entity_links join table for relational lineage.
                if row_id is not None and entity.raw_record_ids:
                    # Clear old links for this entity (idempotent re-resolution).
                    conn.execute("DELETE FROM entity_links WHERE entity_id = ?", (row_id,))
                    for raw_id in entity.raw_record_ids:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO entity_links
                                (entity_id, raw_record_id, match_score, match_reasons, linked_at)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (row_id, raw_id, float(entity.confidence), "[]", now),
                        )
                return row_id

        try:
            return await asyncio.to_thread(_execute)
        except Exception as exc:
            _logger.error("Failed to upsert resolved entity %r: %s", entity.name, exc)
            return None

    async def get_by_id(self, entity_id: int) -> Optional[ResolvedEntity]:
        def _execute():
            with self._db.connection() as conn:
                return conn.execute(
                    "SELECT * FROM resolved_entities WHERE id = ?",
                    (entity_id,),
                ).fetchone()
        row = await asyncio.to_thread(_execute)
        return self._row_to_entity(row) if row else None

    async def list_all(
        self,
        wilaya: Optional[str] = None,
        industry: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ResolvedEntity]:
        clauses = ["confidence >= ?"]
        params: list = [min_confidence]
        if wilaya:
            clauses.append("LOWER(wilaya) = LOWER(?)")
            params.append(wilaya)
        if industry:
            clauses.append("LOWER(industry) LIKE LOWER(?)")
            params.append(f"%{industry}%")
        where = " WHERE " + " AND ".join(clauses)
        sql = (
            "SELECT * FROM resolved_entities"
            + where
            + " ORDER BY confidence DESC, last_resolved_at DESC LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])

        def _execute():
            with self._db.connection() as conn:
                return conn.execute(sql, params).fetchall()
        rows = await asyncio.to_thread(_execute)
        return [self._row_to_entity(r) for r in rows]

    async def count(self) -> int:
        def _execute():
            with self._db.connection() as conn:
                return conn.execute("SELECT COUNT(*) FROM resolved_entities").fetchone()[0]
        return await asyncio.to_thread(_execute)

    async def delete_all(self) -> int:
        def _execute():
            with self._db.connection() as conn:
                # entity_links cascades on DELETE, but clear it explicitly
                # to be safe across SQLite versions.
                conn.execute("DELETE FROM entity_links")
                result = conn.execute("DELETE FROM resolved_entities")
                return result.rowcount
        deleted = await asyncio.to_thread(_execute)
        _logger.info("Cleared %d resolved entities", deleted)
        return deleted

    async def get_lineage(self, entity_id: int) -> list[dict]:
        """Return every raw record that contributed to ``entity_id``.

        Uses the ``entity_links`` join table for an efficient SQL query.
        Each row contains the raw record's id, name, source, source_url,
        and the match score that triggered the merge.
        """
        def _execute():
            with self._db.connection() as conn:
                rows = conn.execute(
                    """
                    SELECT r.id, r.name, r.source, r.source_url, r.website,
                           r.phone, r.email, el.match_score, el.linked_at
                    FROM entity_links el
                    JOIN raw_records r ON r.id = el.raw_record_id
                    WHERE el.entity_id = ?
                    ORDER BY el.linked_at DESC
                    """,
                    (entity_id,),
                ).fetchall()
                return [dict(row) for row in rows]
        return await asyncio.to_thread(_execute)

    # ------------------------------------------------------------------
    #  Mapping
    # ------------------------------------------------------------------

    def _row_to_entity(self, row) -> ResolvedEntity:
        return ResolvedEntity(
            id=row["id"],
            entity_type=EntityType(row["entity_type"]),
            name=row["name"],
            industry=row["industry"],
            wilaya=row["wilaya"],
            address=row["address"],
            website=row["website"],
            phone=row["phone"],
            email=row["email"],
            social_media_handles=json.loads(row["social_media_handles"] or "[]"),
            phones=json.loads(row["phones"] or "[]"),
            rating=float(row["rating"] or 0.0),
            review_count=int(row["review_count"] or 0),
            latitude=row["latitude"],
            longitude=row["longitude"],
            confidence=float(row["confidence"] or 1.0),
            strategy=ResolutionStrategy(row["strategy"]),
            raw_record_ids=json.loads(row["raw_record_ids"] or "[]"),
            last_resolved_at=_parse_dt(row["last_resolved_at"]),
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
