"""Repository for the ``raw_records`` table.

Implements ``IRawRecordRepository``. Every method is async to keep the
contract uniform with future async backends (Postgres, etc.), even though
SQLite itself is synchronous — the calls are offloaded to a thread pool
by ``asyncio.to_thread`` where blocking would matter.

The repository is intentionally thin: it does JSON serialisation and
row-to-model mapping, but no business logic. Business decisions (what to
save, when to deduplicate) live in the services layer.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from core.interfaces import IRawRecordRepository
from domain.enums import DataSource, FreshnessAge
from domain.models import BusinessRaw, RawRecord
from domain.value_objects import FreshnessMetadata, PhoneDetails
from infrastructure.storage.database import DatabaseManager


_logger = logging.getLogger("storage.raw_record_repo")


class RawRecordRepository(IRawRecordRepository):
    """CRUD for ``raw_records``."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def save(self, business: BusinessRaw) -> Optional[int]:
        """Insert or upsert a raw record. Returns the row id.

        On fingerprint conflict, the freshness columns are refreshed (the
        source may have updated the listing) but the identity columns
        (name, phone, website) are left untouched to preserve lineage.
        """
        fp = business.fingerprint()
        phone_meta_json = json.dumps(
            [p.model_dump(mode="json") for p in business.phone_metadata],
            ensure_ascii=False,
        )
        social_json = json.dumps(business.social_media_handles, ensure_ascii=False)
        now = _now_iso()
        discovered_at = business.freshness.discovered_at.isoformat()
        last_updated = (
            business.freshness.last_updated.isoformat()
            if business.freshness.last_updated
            else None
        )
        age_class = business.freshness.calculated_age_class.value

        def _execute():
            with self._db.connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO raw_records (
                        fingerprint, name, industry, wilaya, address, website,
                        phone, email, social_media_handles, rating, review_count,
                        latitude, longitude, source, source_url, phone_metadata,
                        raw_html_hash, discovered_at, last_updated, relative_age_hint,
                        calculated_age_class, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(fingerprint) DO UPDATE SET
                        last_updated         = excluded.last_updated,
                        relative_age_hint    = excluded.relative_age_hint,
                        calculated_age_class = excluded.calculated_age_class,
                        rating               = excluded.rating,
                        review_count         = excluded.review_count,
                        phone_metadata       = excluded.phone_metadata
                    """,
                    (
                        fp, business.name, business.industry, business.wilaya,
                        business.address, business.website, business.phone, business.email,
                        social_json, business.rating, business.review_count,
                        business.latitude, business.longitude,
                        business.source.value, business.source_url, phone_meta_json,
                        business.raw_html_hash, discovered_at, last_updated,
                        business.freshness.relative_age_hint, age_class, now,
                    ),
                )
                # On INSERT, lastrowid is the new row id. On UPDATE (conflict),
                # lastrowid is 0/unchanged, so we fall back to looking up by fingerprint.
                row_id = cursor.lastrowid
                if not row_id:
                    row = conn.execute(
                        "SELECT id FROM raw_records WHERE fingerprint = ?", (fp,)
                    ).fetchone()
                    row_id = row["id"] if row else None
                return row_id

        try:
            row_id = await asyncio.to_thread(_execute)
            _logger.debug("Saved raw record id=%d (%s)", row_id, business.name)
            return row_id
        except Exception as exc:
            _logger.error("Failed to save raw record %r: %s", business.name, exc)
            return None

    async def get_by_id(self, record_id: int) -> Optional[RawRecord]:
        def _execute():
            with self._db.connection() as conn:
                return conn.execute(
                    "SELECT * FROM raw_records WHERE id = ?",
                    (record_id,),
                ).fetchone()
        row = await asyncio.to_thread(_execute)
        return self._row_to_record(row) if row else None

    async def list_all(self, limit: int = 1000, offset: int = 0) -> list[RawRecord]:
        def _execute():
            with self._db.connection() as conn:
                return conn.execute(
                    "SELECT * FROM raw_records ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
        rows = await asyncio.to_thread(_execute)
        return [self._row_to_record(r) for r in rows]

    async def list_unresolved(self, limit: int = 1000) -> list[RawRecord]:
        """Return raw records that have not yet been linked to a resolved entity.

        For simplicity we treat every raw record as unresolved — the
        resolver overwrites ``resolved_entities`` on each run. A more
        sophisticated implementation would track a ``resolved_at`` column
        on ``raw_records`` and only return those with ``NULL``.
        """
        return await self.list_all(limit=limit)

    async def count(self) -> int:
        def _execute():
            with self._db.connection() as conn:
                return conn.execute("SELECT COUNT(*) FROM raw_records").fetchone()[0]
        return await asyncio.to_thread(_execute)

    # ------------------------------------------------------------------
    #  Mapping
    # ------------------------------------------------------------------

    def _row_to_record(self, row) -> RawRecord:
        social = json.loads(row["social_media_handles"] or "[]")
        phone_meta = [
            PhoneDetails(**p)
            for p in json.loads(row["phone_metadata"] or "[]")
        ]
        freshness = FreshnessMetadata(
            discovered_at=_parse_dt(row["discovered_at"]),
            last_updated=_parse_dt(row["last_updated"]) if row["last_updated"] else None,
            relative_age_hint=row["relative_age_hint"],
            calculated_age_class=FreshnessAge(row["calculated_age_class"]),
        )
        return RawRecord(
            id=row["id"],
            fingerprint=row["fingerprint"],
            name=row["name"],
            industry=row["industry"],
            wilaya=row["wilaya"],
            address=row["address"],
            website=row["website"],
            phone=row["phone"],
            email=row["email"],
            social_media_handles=social,
            rating=float(row["rating"] or 0.0),
            review_count=int(row["review_count"] or 0),
            latitude=row["latitude"],
            longitude=row["longitude"],
            source=DataSource(row["source"]),
            source_url=row["source_url"],
            phone_metadata=phone_meta,
            freshness=freshness,
            discovered_at=_parse_dt(row["discovered_at"]),
            created_at=_parse_dt(row["created_at"]),
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
