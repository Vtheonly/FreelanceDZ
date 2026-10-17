"""Repository for geographic checkpoints / points of interest (POIs).

Follows the storage-layer conventions of ``lead_repo``: every blocking
SQLite call is offloaded via ``asyncio.to_thread``, writes go through
``immediate_connection`` (BEGIN IMMEDIATE — no upgrade deadlock under
concurrency), and reads use the plain pooled connection helper.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from domain.models import Checkpoint, utcnow
from infrastructure.storage.database import DatabaseManager


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_ALLOWED_UPDATE_FIELDS = frozenset({
    "name", "category", "wilaya", "latitude", "longitude", "notes", "status",
})


class CheckpointRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    async def create(self, cp: Checkpoint) -> int:
        now = _now_iso()

        def _execute() -> int:
            with self._db.immediate_connection() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO checkpoints
                        (name, category, wilaya, latitude, longitude, notes, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (cp.name, cp.category, cp.wilaya, cp.latitude, cp.longitude,
                     cp.notes, cp.status, now, now),
                )
                return int(cur.lastrowid or 0)

        return await asyncio.to_thread(_execute)

    async def update(self, cp_id: int, **fields: Any) -> bool:
        """Update a subset of fields; returns False when nothing changed."""
        clean = {k: v for k, v in fields.items() if v is not None and k in _ALLOWED_UPDATE_FIELDS}
        if not clean:
            return False
        clean["updated_at"] = _now_iso()
        set_clause = ", ".join(f"{k} = ?" for k in clean)
        params = list(clean.values()) + [cp_id]

        def _execute() -> bool:
            with self._db.immediate_connection() as conn:
                cur = conn.execute(f"UPDATE checkpoints SET {set_clause} WHERE id = ?", params)
                return cur.rowcount > 0

        return await asyncio.to_thread(_execute)

    async def delete(self, cp_id: int) -> bool:
        def _execute() -> bool:
            with self._db.immediate_connection() as conn:
                cur = conn.execute("DELETE FROM checkpoints WHERE id = ?", (cp_id,))
                return cur.rowcount > 0

        return await asyncio.to_thread(_execute)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    async def get(self, cp_id: int) -> Optional[Checkpoint]:
        def _execute() -> Optional[Checkpoint]:
            with self._db.connection() as conn:
                row = conn.execute("SELECT * FROM checkpoints WHERE id = ?", (cp_id,)).fetchone()
                return self._row_to_cp(row) if row else None

        return await asyncio.to_thread(_execute)

    async def list_checkpoints(
        self,
        wilaya: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 1000,
    ) -> list[Checkpoint]:
        clauses: list[str] = []
        params: list[Any] = []
        if wilaya:
            clauses.append("LOWER(wilaya) = LOWER(?)")
            params.append(wilaya.strip())
        if category:
            clauses.append("category = ?")
            params.append(category)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM checkpoints {where} ORDER BY id DESC LIMIT ?"
        params.append(limit)

        def _execute() -> list[Checkpoint]:
            with self._db.connection() as conn:
                rows = conn.execute(sql, params).fetchall()
                return [self._row_to_cp(r) for r in rows]

        return await asyncio.to_thread(_execute)

    async def count(self) -> int:
        def _execute() -> int:
            with self._db.connection() as conn:
                return conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]

        return await asyncio.to_thread(_execute)

    async def count_by_wilaya(self) -> dict[str, int]:
        """Aggregated counts (lowercase wilaya -> n) for the map catalogue."""

        def _execute() -> dict[str, int]:
            with self._db.connection() as conn:
                rows = conn.execute(
                    "SELECT LOWER(wilaya) AS w, COUNT(*) AS n FROM checkpoints "
                    "WHERE wilaya != '' GROUP BY w"
                ).fetchall()
                return {r["w"]: r["n"] for r in rows}

        return await asyncio.to_thread(_execute)

    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_cp(row: Any) -> Checkpoint:
        def _dt(v: Optional[str]) -> datetime:
            if not v:
                return utcnow()
            try:
                parsed = datetime.fromisoformat(v)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                return utcnow()

        return Checkpoint(
            id=row["id"],
            name=row["name"],
            category=row["category"],
            wilaya=row["wilaya"] or "",
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            notes=row["notes"],
            status=row["status"],
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
        )
