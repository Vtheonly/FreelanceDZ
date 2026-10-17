"""Repository for entity resolution persistence.

Owns five tables:

- ``entity_clusters``    — canonical entities (golden records, aliases,
                           per-field provenance, evidence summary)
- ``entity_links``       — cluster <-> lead membership lineage
- ``entity_relations``   — RELATED links (branches, franchises, shared
                           owner) between distinct entities
- ``resolution_decisions`` — the explainability / reversibility log
- ``review_queue``       — ambiguous pairs awaiting a human decision

Stable-identity upserts: when a cluster's membership grows, the existing
cluster row is updated in place (v3.0 allocated a new row and deleted
the old one on every membership change, churning cluster ids). A cluster
row is only deleted when its leads actually moved elsewhere, and only
within the scope of leads the current run considered — never as a
side effect of the batch cap.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from infrastructure.storage.database import DatabaseManager

logger = logging.getLogger("storage.cluster_repo")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pair(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


class ClusterRepository:
    """Non-destructive entity-cluster persistence."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    # ==================================================================
    # Cluster persistence (batch + incremental share one code path)
    # ==================================================================

    async def persist(
        self,
        records: Sequence[dict[str, Any]],
        scope_lead_ids: Optional[set[int]] = None,
    ) -> dict[str, int]:
        """Upsert cluster records with stable ids.

        ``records``: CanonicalBuilder outputs (members, canonical_lead_id,
        name, industry, wilaya, confidence, strategy, aliases,
        canonical_fields, evidence, reasons).

        Reuse rules, in order:
        1. an existing cluster with the same member set -> row update;
        2. an existing cluster whose members are a subset of the new
           members -> row update *in place* (stable id, so API consumers
           and relations keep pointing at the same entity);
        3. otherwise -> insert.

        Pruning: existing clusters that were not reused and whose members
        intersect ``scope_lead_ids`` (the leads this run actually
        considered) are deleted — their leads moved into other groups or
        became plain singletons. Clusters outside the run's scope are
        untouched (fixes v3.0's latent prune of clusters beyond the
        resolution batch cap).
        """
        def _execute() -> dict[str, int]:
            now = _now_iso()
            with self._db.immediate_connection() as conn:
                existing_members: dict[int, set[int]] = {}
                for row in conn.execute(
                    "SELECT cluster_id, lead_id FROM entity_links"
                ).fetchall():
                    existing_members.setdefault(row["cluster_id"], set()).add(
                        row["lead_id"]
                    )

                by_members = {frozenset(v): k for k, v in existing_members.items()}
                reused: set[int] = set()
                inserted = updated = 0

                for record in records:
                    members = [int(m) for m in record["members"] if m is not None]
                    if not members:
                        continue
                    member_set = set(members)
                    cluster_id = by_members.get(frozenset(members))
                    if cluster_id is None:
                        # Superset reuse: the cluster grew, keep its id.
                        for existing_key, cid in by_members.items():
                            if existing_key and existing_key <= member_set:
                                cluster_id = cid
                                break

                    if cluster_id is not None:
                        conn.execute(
                            """UPDATE entity_clusters SET
                                   canonical_lead_id = ?, name = ?, industry = ?,
                                   wilaya = ?, confidence = ?, member_count = ?,
                                   strategy = ?, aliases = ?, canonical_fields = ?,
                                   evidence_summary = ?, updated_at = ?
                               WHERE id = ?""",
                            (
                                record["canonical_lead_id"], record["name"],
                                record.get("industry"), record.get("wilaya"),
                                record.get("confidence", 1.0), len(members),
                                record.get("strategy", "graph_merge"),
                                json.dumps(record.get("aliases", []),
                                           ensure_ascii=False),
                                json.dumps(record.get("canonical_fields", {}),
                                           ensure_ascii=False),
                                json.dumps(record.get("evidence", {}),
                                           ensure_ascii=False),
                                now, cluster_id,
                            ),
                        )
                        updated += 1
                    else:
                        cur = conn.execute(
                            """INSERT INTO entity_clusters
                               (canonical_lead_id, name, industry, wilaya, confidence,
                                member_count, strategy, aliases, canonical_fields,
                                evidence_summary, created_at, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                record["canonical_lead_id"], record["name"],
                                record.get("industry"), record.get("wilaya"),
                                record.get("confidence", 1.0), len(members),
                                record.get("strategy", "graph_merge"),
                                json.dumps(record.get("aliases", []),
                                           ensure_ascii=False),
                                json.dumps(record.get("canonical_fields", {}),
                                           ensure_ascii=False),
                                json.dumps(record.get("evidence", {}),
                                           ensure_ascii=False),
                                now, now,
                            ),
                        )
                        cluster_id = int(cur.lastrowid or 0)
                        inserted += 1
                        by_members[frozenset(members)] = cluster_id

                    reused.add(cluster_id)

                    reasons = json.dumps(record.get("reasons", []),
                                         ensure_ascii=False)
                    for lead_id in members:
                        conn.execute(
                            """INSERT INTO entity_links
                               (cluster_id, lead_id, match_score, match_reasons, linked_at)
                               VALUES (?, ?, ?, ?, ?)
                               ON CONFLICT(cluster_id, lead_id) DO UPDATE SET
                                   match_score = excluded.match_score,
                                   match_reasons = excluded.match_reasons""",
                            (cluster_id, lead_id,
                             record.get("confidence", 1.0), reasons, now),
                        )
                    conn.execute(
                        "UPDATE leads SET cluster_id = ? WHERE id IN "
                        f"({','.join('?' for _ in members)})",
                        (cluster_id, *members),
                    )

                # Prune superseded clusters, scoped to the leads we saw.
                deleted = 0
                for cid, members_of_cluster in existing_members.items():
                    if cid in reused:
                        continue
                    if scope_lead_ids is not None and not (
                        members_of_cluster & scope_lead_ids
                    ):
                        continue  # outside this run's scope
                    conn.execute(
                        "DELETE FROM entity_clusters WHERE id = ?", (cid,)
                    )
                    deleted += 1  # leads.cluster_id clears via ON DELETE SET NULL

                return {
                    "stored": len(reused),
                    "inserted": inserted,
                    "updated": updated,
                    "pruned": deleted,
                }
        return await asyncio.to_thread(_execute)

    async def replace_all(self, clusters: list[dict[str, Any]]) -> int:
        """v3.0 compatibility entry point: persist with global scope."""
        scope: set[int] = set()
        for c in clusters:
            scope.update(int(m) for m in c["members"] if m is not None)
        result = await self.persist(clusters, scope_lead_ids=scope)
        return result["stored"]

    # ==================================================================
    # Reads
    # ==================================================================

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
                return [_cluster_row(r) for r in rows]
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
                return _cluster_row(row) if row else None
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
                out = []
                for r in rows:
                    item = dict(r)
                    item["match_reasons"] = _loads(item.get("match_reasons"), [])
                    out.append(item)
                return out
        return await asyncio.to_thread(_execute)

    async def member_lead_ids(self, cluster_id: int) -> list[int]:
        def _execute() -> list[int]:
            with self._db.connection() as conn:
                rows = conn.execute(
                    "SELECT lead_id FROM entity_links WHERE cluster_id = ?"
                    " ORDER BY lead_id",
                    (cluster_id,),
                ).fetchall()
                return [r["lead_id"] for r in rows]
        return await asyncio.to_thread(_execute)

    async def cluster_id_by_lead(self) -> dict[int, int]:
        """lead_id -> cluster_id for every clustered lead (one query)."""

        def _execute() -> dict[int, int]:
            with self._db.connection() as conn:
                rows = conn.execute(
                    "SELECT id, cluster_id FROM leads WHERE cluster_id IS NOT NULL"
                ).fetchall()
                return {r["id"]: r["cluster_id"] for r in rows}
        return await asyncio.to_thread(_execute)

    async def count(self) -> int:
        def _execute() -> int:
            with self._db.connection() as conn:
                return conn.execute("SELECT COUNT(*) FROM entity_clusters").fetchone()[0]
        return await asyncio.to_thread(_execute)

    # ==================================================================
    # Decision log (explainability + reversibility)
    # ==================================================================

    async def record_decisions(self, decisions: Sequence[dict[str, Any]],
                               mode: str = "batch") -> int:
        """Persist decision rows: {lead_a, lead_b, decision, relationship,
        score, signals (dict), explanation, decided_by?}."""
        if not decisions:
            return 0

        def _execute() -> int:
            from config.settings import get_settings
            keep = get_settings().ENTITY_DECISION_LOG_LIMIT
            now = _now_iso()
            with self._db.immediate_connection() as conn:
                conn.executemany(
                    """INSERT INTO resolution_decisions
                       (lead_a, lead_b, decision, relationship, score, signals,
                        explanation, mode, decided_by, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            d["lead_a"], d["lead_b"], d["decision"],
                            d.get("relationship"), d.get("score", 0.0),
                            json.dumps(d.get("signals") or {}, ensure_ascii=False),
                            d.get("explanation", ""), mode,
                            d.get("decided_by", "engine"), now,
                        )
                        for d in decisions
                    ],
                )
                # FIFO trim: keep only the newest N rows.
                conn.execute(
                    "DELETE FROM resolution_decisions WHERE id NOT IN ("
                    " SELECT id FROM resolution_decisions"
                    " ORDER BY id DESC LIMIT ?)",
                    (keep,),
                )
                return len(decisions)
        return await asyncio.to_thread(_execute)

    async def manual_overrides(self) -> list[dict[str, Any]]:
        """Latest manual decision per lead pair (splits, merges, review
        resolutions). The engine loads these as pinned constraints so a
        human decision survives every later automated run."""

        def _execute() -> list[dict[str, Any]]:
            with self._db.connection() as conn:
                rows = conn.execute(
                    """
                    SELECT d.* FROM resolution_decisions d
                    JOIN (
                        SELECT lead_a, lead_b, MAX(id) AS max_id
                        FROM resolution_decisions
                        WHERE decided_by = 'manual'
                        GROUP BY lead_a, lead_b
                    ) latest ON d.id = latest.max_id
                    """
                ).fetchall()
                return [
                    {
                        "lead_a": r["lead_a"], "lead_b": r["lead_b"],
                        "decision": r["decision"],
                    }
                    for r in rows
                ]
        return await asyncio.to_thread(_execute)

    async def get_evidence(self, cluster_id: int, limit: int = 100) -> list[dict[str, Any]]:
        """Decision log entries involving this cluster's members."""

        def _execute() -> list[dict[str, Any]]:
            with self._db.connection() as conn:
                rows = conn.execute(
                    """
                    SELECT d.* FROM resolution_decisions d
                    JOIN entity_links el ON el.cluster_id = ?
                        AND (el.lead_id = d.lead_a OR el.lead_id = d.lead_b)
                    GROUP BY d.id
                    ORDER BY d.id DESC LIMIT ?
                    """,
                    (cluster_id, limit),
                ).fetchall()
                out = []
                for r in rows:
                    item = dict(r)
                    item["signals"] = _loads(item.get("signals"), {})
                    out.append(item)
                return out
        return await asyncio.to_thread(_execute)

    # ==================================================================
    # Review queue
    # ==================================================================

    async def enqueue_review(self, items: Sequence[dict[str, Any]]) -> int:
        """Queue ambiguous pairs: {lead_a, lead_b, score, evidence, explanation}."""
        if not items:
            return 0

        def _execute() -> int:
            now = _now_iso()
            with self._db.immediate_connection() as conn:
                # Drop stale pending duplicates first (INSERT OR IGNORE
                # alone would keep the old evidence).
                for item in items:
                    a, b = _pair(int(item["lead_a"]), int(item["lead_b"]))
                    conn.execute(
                        "DELETE FROM review_queue WHERE lead_a = ? AND lead_b = ?"
                        " AND status = 'pending'",
                        (a, b),
                    )
                    conn.execute(
                        """INSERT INTO review_queue
                           (lead_a, lead_b, score, evidence, explanation,
                            status, created_at)
                           VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                        (a, b, item.get("score", 0.0),
                         json.dumps(item.get("evidence") or {},
                                    ensure_ascii=False),
                         item.get("explanation", ""), now),
                    )
                return len(items)
        return await asyncio.to_thread(_execute)

    async def list_review(self, status: str = "pending",
                          limit: int = 50) -> list[dict[str, Any]]:
        def _execute() -> list[dict[str, Any]]:
            with self._db.connection() as conn:
                rows = conn.execute(
                    """
                    SELECT q.*, la.name AS name_a, lb.name AS name_b,
                           la.wilaya AS wilaya_a, lb.wilaya AS wilaya_b,
                           la.source AS source_a, lb.source AS source_b
                    FROM review_queue q
                    LEFT JOIN leads la ON la.id = q.lead_a
                    LEFT JOIN leads lb ON lb.id = q.lead_b
                    WHERE q.status = ?
                    ORDER BY q.score DESC, q.id DESC
                    LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
                out = []
                for r in rows:
                    item = dict(r)
                    item["evidence"] = _loads(item.get("evidence"), {})
                    out.append(item)
                return out
        return await asyncio.to_thread(_execute)

    async def get_review_item(self, item_id: int) -> Optional[dict[str, Any]]:
        def _execute() -> Optional[dict[str, Any]]:
            with self._db.connection() as conn:
                row = conn.execute(
                    "SELECT * FROM review_queue WHERE id = ?", (item_id,)
                ).fetchone()
                if not row:
                    return None
                item = dict(row)
                item["evidence"] = _loads(item.get("evidence"), {})
                return item
        return await asyncio.to_thread(_execute)

    async def resolve_review(self, item_id: int, resolution: str) -> bool:
        """resolution: merged | kept_separate | dismissed."""
        if resolution not in ("merged", "kept_separate", "dismissed"):
            raise ValueError(f"invalid review resolution: {resolution}")

        def _execute() -> bool:
            with self._db.immediate_connection() as conn:
                cur = conn.execute(
                    "UPDATE review_queue SET status = ?, resolved_at = ?"
                    " WHERE id = ? AND status = 'pending'",
                    (resolution, _now_iso(), item_id),
                )
                return cur.rowcount > 0
        return await asyncio.to_thread(_execute)

    async def count_pending_review(self) -> int:
        def _execute() -> int:
            with self._db.connection() as conn:
                return conn.execute(
                    "SELECT COUNT(*) FROM review_queue WHERE status = 'pending'"
                ).fetchone()[0]
        return await asyncio.to_thread(_execute)

    # ==================================================================
    # Entity relations (RELATED: branches, franchises, shared owner)
    # ==================================================================

    async def upsert_relations(self, relations: Sequence[dict[str, Any]]) -> int:
        """{cluster_a, cluster_b, relationship, confidence, explanation}."""
        if not relations:
            return 0

        def _execute() -> int:
            now = _now_iso()
            with self._db.immediate_connection() as conn:
                for rel in relations:
                    a, b = _pair(int(rel["cluster_a"]), int(rel["cluster_b"]))
                    if a == b:
                        continue
                    conn.execute(
                        """INSERT INTO entity_relations
                           (cluster_a, cluster_b, relationship, confidence,
                            explanation, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)
                           ON CONFLICT(cluster_a, cluster_b, relationship) DO UPDATE SET
                               confidence = excluded.confidence,
                               explanation = excluded.explanation""",
                        (a, b, rel["relationship"], rel.get("confidence", 0.0),
                         rel.get("explanation", ""), now),
                    )
                return len(relations)
        return await asyncio.to_thread(_execute)

    async def list_relations(self, cluster_id: int) -> list[dict[str, Any]]:
        def _execute() -> list[dict[str, Any]]:
            with self._db.connection() as conn:
                rows = conn.execute(
                    """
                    SELECT r.id, r.relationship, r.confidence, r.explanation,
                           r.created_at,
                           CASE WHEN r.cluster_a = ?
                                THEN r.cluster_b ELSE r.cluster_a END AS other_cluster_id,
                           CASE WHEN r.cluster_a = ?
                                THEN cb.name ELSE ca.name END AS other_cluster_name,
                           CASE WHEN r.cluster_a = ?
                                THEN cb.wilaya ELSE ca.wilaya END AS other_cluster_wilaya
                    FROM entity_relations r
                    JOIN entity_clusters ca ON ca.id = r.cluster_a
                    JOIN entity_clusters cb ON cb.id = r.cluster_b
                    WHERE r.cluster_a = ? OR r.cluster_b = ?
                    ORDER BY r.confidence DESC
                    """,
                    (cluster_id, cluster_id, cluster_id, cluster_id, cluster_id),
                ).fetchall()
                return [dict(r) for r in rows]
        return await asyncio.to_thread(_execute)

    async def remap_relations(self, old_cluster_id: int, new_cluster_id: int) -> None:
        """Point relations at a different cluster (used by manual merge)."""

        def _execute() -> None:
            with self._db.immediate_connection() as conn:
                _remap_relations(conn, old_cluster_id, new_cluster_id)
        await asyncio.to_thread(_execute)

    # ==================================================================
    # Manual split / merge (reversibility)
    # ==================================================================

    async def split_cluster(
        self,
        cluster_id: int,
        groups: list[list[int]],
        records: list[dict[str, Any]],
    ) -> list[int]:
        """Reassign memberships: ``groups`` partitions the current member
        lead ids; ``records[i]`` is the CanonicalBuilder output for
        ``groups[i]``. The first group keeps the original cluster id;
        the others get new rows. Relations stay attached to the surviving
        cluster. Returns the resulting cluster ids in group order."""
        def _execute() -> list[int]:
            now = _now_iso()
            with self._db.immediate_connection() as conn:
                result_ids: list[int] = []
                for i, (group, record) in enumerate(zip(groups, records)):
                    if i == 0:
                        cid = cluster_id
                        conn.execute(
                            """UPDATE entity_clusters SET
                                   canonical_lead_id = ?, name = ?, industry = ?,
                                   wilaya = ?, confidence = ?, member_count = ?,
                                   strategy = 'manual_merge', aliases = ?,
                                   canonical_fields = ?, evidence_summary = ?,
                                   updated_at = ?
                               WHERE id = ?""",
                            (record["canonical_lead_id"], record["name"],
                             record.get("industry"), record.get("wilaya"),
                             record.get("confidence", 1.0), len(group),
                             json.dumps(record.get("aliases", []), ensure_ascii=False),
                             json.dumps(record.get("canonical_fields", {}),
                                        ensure_ascii=False),
                             json.dumps(record.get("evidence", {}),
                                        ensure_ascii=False),
                             now, cid),
                        )
                    else:
                        cur = conn.execute(
                            """INSERT INTO entity_clusters
                               (canonical_lead_id, name, industry, wilaya, confidence,
                                member_count, strategy, aliases, canonical_fields,
                                evidence_summary, created_at, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?, 'manual_merge', ?, ?, ?, ?, ?)""",
                            (record["canonical_lead_id"], record["name"],
                             record.get("industry"), record.get("wilaya"),
                             record.get("confidence", 1.0), len(group),
                             json.dumps(record.get("aliases", []), ensure_ascii=False),
                             json.dumps(record.get("canonical_fields", {}),
                                        ensure_ascii=False),
                             json.dumps(record.get("evidence", {}),
                                        ensure_ascii=False),
                             now, now),
                        )
                        cid = int(cur.lastrowid or 0)
                    result_ids.append(cid)

                    ph = ",".join("?" for _ in group)
                    conn.execute(
                        f"DELETE FROM entity_links WHERE cluster_id = ?"
                        f" AND lead_id NOT IN ({ph})",
                        (cluster_id if i == 0 else cid, *group),
                    )
                    for lead_id in group:
                        conn.execute(
                            """INSERT INTO entity_links
                               (cluster_id, lead_id, match_score, match_reasons, linked_at)
                               VALUES (?, ?, 1.0, ?, ?)
                               ON CONFLICT(cluster_id, lead_id) DO UPDATE SET
                                   match_reasons = excluded.match_reasons""",
                            (cid, lead_id,
                             json.dumps(record.get("reasons", []), ensure_ascii=False),
                             now),
                        )
                    conn.execute(
                        f"UPDATE leads SET cluster_id = ? WHERE id IN ({ph})",
                        (cid, *group),
                    )
                return result_ids
        return await asyncio.to_thread(_execute)

    async def merge_clusters(
        self,
        surviving_cluster_id: int,
        absorbed_cluster_ids: Sequence[int],
        record: dict[str, Any],
    ) -> None:
        """Fold absorbed clusters into the surviving one and repoint their
        relations. Source leads are untouched; only memberships move."""
        def _execute() -> None:
            now = _now_iso()
            with self._db.immediate_connection() as conn:
                members: set[int] = set()
                for cid in (*absorbed_cluster_ids, surviving_cluster_id):
                    for row in conn.execute(
                        "SELECT lead_id FROM entity_links WHERE cluster_id = ?",
                        (cid,),
                    ).fetchall():
                        members.add(row["lead_id"])

                # Remap relations BEFORE deleting the absorbed rows —
                # entity_relations cascades on cluster deletion.
                for cid in absorbed_cluster_ids:
                    _remap_relations(conn, cid, surviving_cluster_id)

                conn.execute(
                    """UPDATE entity_clusters SET
                           canonical_lead_id = ?, name = ?, industry = ?, wilaya = ?,
                           confidence = ?, member_count = ?, strategy = 'manual_merge',
                           aliases = ?, canonical_fields = ?, evidence_summary = ?,
                           updated_at = ?
                       WHERE id = ?""",
                    (record["canonical_lead_id"], record["name"],
                     record.get("industry"), record.get("wilaya"),
                     record.get("confidence", 1.0), len(members),
                     json.dumps(record.get("aliases", []), ensure_ascii=False),
                     json.dumps(record.get("canonical_fields", {}),
                                ensure_ascii=False),
                     json.dumps(record.get("evidence", {}), ensure_ascii=False),
                     now, surviving_cluster_id),
                )
                for cid in absorbed_cluster_ids:
                    conn.execute("DELETE FROM entity_clusters WHERE id = ?", (cid,))
                if members:
                    ph = ",".join("?" for _ in members)
                    conn.execute(
                        f"UPDATE leads SET cluster_id = ? WHERE id IN ({ph})",
                        (surviving_cluster_id, *members),
                    )
                reasons = json.dumps(record.get("reasons", []), ensure_ascii=False)
                for lead_id in members:
                    conn.execute(
                        """INSERT INTO entity_links
                           (cluster_id, lead_id, match_score, match_reasons, linked_at)
                           VALUES (?, ?, 1.0, ?, ?)
                           ON CONFLICT(cluster_id, lead_id) DO UPDATE SET
                               match_reasons = excluded.match_reasons""",
                        (surviving_cluster_id, lead_id, reasons, now),
                    )
        await asyncio.to_thread(_execute)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _remap_relations(conn: Any, old_cluster_id: int, new_cluster_id: int) -> None:
    """Transactional core: copy relations to the new cluster id, drop
    self-relations, remove the old ones."""
    conn.execute(
        """INSERT OR IGNORE INTO entity_relations
           (cluster_a, cluster_b, relationship, confidence,
            explanation, created_at)
           SELECT CASE WHEN cluster_a = ? THEN ? ELSE cluster_a END,
                  CASE WHEN cluster_b = ? THEN ? ELSE cluster_b END,
                  relationship, confidence, explanation, created_at
           FROM entity_relations
           WHERE cluster_a = ? OR cluster_b = ?""",
        (old_cluster_id, new_cluster_id, old_cluster_id, new_cluster_id,
         old_cluster_id, old_cluster_id),
    )
    # Drop self-relations created by absorbing both endpoints.
    conn.execute("DELETE FROM entity_relations WHERE cluster_a = cluster_b")
    conn.execute(
        "DELETE FROM entity_relations WHERE cluster_a = ? OR cluster_b = ?",
        (old_cluster_id, old_cluster_id),
    )


def _loads(raw: Any, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def _cluster_row(row: Any) -> dict[str, Any]:
    """Decode the JSON columns of an entity_clusters row."""
    item = dict(row)
    item["aliases"] = _loads(item.get("aliases"), [])
    item["canonical_fields"] = _loads(item.get("canonical_fields"), {})
    item["evidence_summary"] = _loads(item.get("evidence_summary"), {})
    return item
