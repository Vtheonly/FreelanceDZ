"""Repository for entity_clusters + entity_links (resolution lineage)."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from infrastructure.storage.database import DatabaseManager

logger = logging.getLogger("storage.cluster_repo")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ClusterRepository:
    """Non-destructive entity-cluster persistence.

    Unlike the v2 wipe-and-rebuild resolver (which DELETEd all resolved
    entities every run, churning IDs), v3 upserts clusters keyed by their
    member lead-ids and only rewrites clusters whose membership changed.
    """

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def replace_all(self, clusters: list[dict[str, Any]]) -> int:
        """Persist the full cluster set: {canonical_lead_id, name, industry,
        wilaya, confidence, strategy, members: [lead_ids], reasons}.

        Reuses an existing cluster when its member set is unchanged.
        Returns the number of distinct clusters stored.
        """
        def _execute() -> int:
            now = _now_iso()
            with self._db.immediate_connection() as conn:
                existing: dict[frozenset[int], int] = {}
                for row in conn.execute(
                    "SELECT cluster_id, lead_id FROM entity_links"
                ).fetchall():
                    existing.setdefault(row["cluster_id"], set()).add(row["lead_id"])
                existing = {frozenset(v): k for k, v in existing.items()}

                used_cluster_ids: set[int] = set()
                for cluster in clusters:
                    members = [int(m) for m in cluster["members"]]
                    if not members:
                        continue
                    member_key = frozenset(members)
                    if member_key in existing:
                        cluster_id = existing[member_key]
                    else:
                        cur = conn.execute(
                            """INSERT INTO entity_clusters
                               (canonical_lead_id, name, industry, wilaya, confidence,
                                member_count, strategy, created_at, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                cluster["canonical_lead_id"], cluster["name"],
                                cluster.get("industry"), cluster.get("wilaya"),
                                cluster.get("confidence", 1.0), len(members),
                                cluster.get("strategy", "graph_merge"), now, now,
                            ),
                        )
                        cluster_id = int(cur.lastrowid or 0)
                    used_cluster_ids.add(cluster_id)

                    reasons = json.dumps(cluster.get("reasons", []), ensure_ascii=False)
                    for lead_id in members:
                        conn.execute(
                            """INSERT INTO entity_links
                               (cluster_id, lead_id, match_score, match_reasons, linked_at)
                               VALUES (?, ?, ?, ?, ?)
                               ON CONFLICT(cluster_id, lead_id) DO UPDATE SET
                                   match_score = excluded.match_score,
                                   match_reasons = excluded.match_reasons""",
                            (cluster_id, lead_id, cluster.get("confidence", 1.0), reasons, now),
                        )
                    conn.execute(
                        "UPDATE leads SET cluster_id = ? WHERE id IN "
                        f"({','.join('?' for _ in members)})",
                        (cluster_id, *members),
                    )

                # Drop clusters no longer present (stale membership).
                stale = [cid for cid in existing.values() if cid not in used_cluster_ids]
                if stale:
                    ph = ",".join("?" for _ in stale)
                    conn.execute(f"DELETE FROM entity_clusters WHERE id IN ({ph})", stale)
                    # leads.cluster_id clears via ON DELETE SET NULL.

                return len(used_cluster_ids)
        return await asyncio.to_thread(_execute)

    async def list_clusters(
        self,
        wilaya: Optional[str] = None,
        industry: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses = ["c.confidence >= ?"]
        params: list[Any] = [min_confidence]
        if wilaya:
            clauses.append("LOWER(c.wilaya) = LOWER(?)")
            params.append(wilaya.strip())
        if industry:
            clauses.append("LOWER(c.industry) LIKE LOWER(?)")
            params.append(f"%{industry.strip()}%")
        where = " AND ".join(clauses)

        def _execute() -> list[dict[str, Any]]:
            with self._db.connection() as conn:
                rows = conn.execute(
                    f"""
                    SELECT c.*, l.name AS canonical_name, l.phone AS canonical_phone,
                           l.website AS canonical_website, l.priority_score AS canonical_score,
                           l.digital_score AS canonical_digital
                    FROM entity_clusters c
                    LEFT JOIN leads l ON l.id = c.canonical_lead_id
                    WHERE {where}
                    ORDER BY c.member_count DESC, c.confidence DESC
                    LIMIT ? OFFSET ?
                    """,
                    (*params, limit, offset),
                ).fetchall()
                return [dict(r) for r in rows]
        return await asyncio.to_thread(_execute)

    async def get_cluster(self, cluster_id: int) -> Optional[dict[str, Any]]:
        def _execute() -> Optional[dict[str, Any]]:
            with self._db.connection() as conn:
                row = conn.execute(
                    """
                    SELECT c.*, l.name AS canonical_name, l.phone AS canonical_phone,
                           l.website AS canonical_website, l.priority_score AS canonical_score
                    FROM entity_clusters c
                    LEFT JOIN leads l ON l.id = c.canonical_lead_id
                    WHERE c.id = ?
                    """,
                    (cluster_id,),
                ).fetchone()
                return dict(row) if row else None
        return await asyncio.to_thread(_execute)

    async def get_lineage(self, cluster_id: int) -> list[dict[str, Any]]:
        def _execute() -> list[dict[str, Any]]:
            with self._db.connection() as conn:
                rows = conn.execute(
                    """
                    SELECT l.id, l.name, l.source, l.source_url, l.discovered_at,
                           el.match_score, el.match_reasons
                    FROM entity_links el
                    JOIN leads l ON l.id = el.lead_id
                    WHERE el.cluster_id = ?
                    ORDER BY el.match_score DESC
                    """,
                    (cluster_id,),
                ).fetchall()
                return [dict(r) for r in rows]
        return await asyncio.to_thread(_execute)

    async def count(self) -> int:
        def _execute() -> int:
            with self._db.connection() as conn:
                return conn.execute("SELECT COUNT(*) FROM entity_clusters").fetchone()[0]
        return await asyncio.to_thread(_execute)
