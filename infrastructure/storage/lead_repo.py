"""Unified lead repository — the single data-access layer for `leads`.

Replaces v2's RawRecordRepository + LeadRepository + the campaign raw SQL
(that leaked through the service layer). All methods offload blocking
SQLite work via asyncio.to_thread. FTS search input is sanitized into a
quoted phrase so user input can never raise FTS5 syntax errors.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Optional

from domain.enums import DataSource, LeadStatus
from domain.models import Lead, utcnow
from domain.value_objects import FreshnessMetadata, PhoneDetails
from infrastructure.storage.database import DatabaseManager

logger = logging.getLogger("storage.lead_repo")

_SORT_COLUMNS = {
    "priority_score": "priority_score",
    "name": "name",
    "industry": "industry",
    "wilaya": "wilaya",
    "status": "status",
    "updated_at": "updated_at",
    "discovered_at": "discovered_at",
}

_FTS_TOKEN_RE = re.compile(r'[\wÀ-ÿ\u0600-\u06FF]+')


def fts_sanitize(term: str) -> str:
    """Quote every token so raw FTS5 syntax in user input cannot raise."""
    tokens = _FTS_TOKEN_RE.findall(term)
    if not tokens:
        return ""
    return " ".join(f'"{t}"' for t in tokens)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LeadRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db
        self._vocab_cache: tuple[float, list[str]] = (0.0, [])
        self._vocab_ttl = 30.0

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    async def upsert(self, lead: Lead) -> tuple[int, bool]:
        """Insert or merge by fingerprint. Returns (lead_id, created).

        v4 Task 6 — race-free by construction:
          * the write itself is a single native ``INSERT ... ON CONFLICT
            DO UPDATE`` statement (atomic in SQLite, no SELECT/INSERT
            window for concurrent writers to collide in), and
          * it runs inside ``immediate_connection`` (BEGIN IMMEDIATE),
            which serialises writers up front so the existence probe
            used for the created/merged flag is snapshot-consistent.

        The merge policy mirrors the historical UPDATE exactly: richer
        values win, scores take the max, and CRM state (name, industry,
        wilaya, status, tags, is_contact, notes) is never clobbered by a
        re-scrape.
        """
        fp = lead.fingerprint()
        now = _now_iso()
        if not lead.discovered_at.tzinfo:
            lead.discovered_at = lead.discovered_at.replace(tzinfo=timezone.utc)
        discovered = lead.discovered_at.isoformat()

        social_json = json.dumps(lead.social_links, ensure_ascii=False)
        phones_json = json.dumps(
            [p.model_dump(mode="json") for p in lead.phone_details], ensure_ascii=False
        )
        gaps_json = json.dumps(lead.gaps, ensure_ascii=False)
        services_json = json.dumps(lead.recommended_services, ensure_ascii=False)
        breakdown_json = json.dumps(lead.score_breakdown, ensure_ascii=False)
        tags_json = json.dumps(lead.tags, ensure_ascii=False)

        def _execute() -> tuple[int, bool]:
            with self._db.immediate_connection() as conn:
                existed = conn.execute(
                    "SELECT 1 FROM leads WHERE fingerprint = ?", (fp,)
                ).fetchone() is not None

                cur = conn.execute(
                    """
                    INSERT INTO leads (
                        fingerprint, name, industry, wilaya, address, website, phone, email,
                        social_links, rating, review_count, latitude, longitude, source, source_url,
                        phone_details, freshness, digital_score, digital_tier, gaps,
                        recommended_services, cta_fr, cta_ar, analysis_model, priority_score,
                        score_breakdown, status, tags, is_contact, notes, discovered_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(fingerprint) DO UPDATE SET
                        address = COALESCE(excluded.address, leads.address),
                        website = COALESCE(excluded.website, leads.website),
                        phone = COALESCE(excluded.phone, leads.phone),
                        email = COALESCE(excluded.email, leads.email),
                        social_links = CASE WHEN excluded.social_links != '[]' THEN excluded.social_links ELSE leads.social_links END,
                        phone_details = CASE WHEN excluded.phone_details != '[]' THEN excluded.phone_details ELSE leads.phone_details END,
                        freshness = excluded.freshness,
                        digital_score = COALESCE(excluded.digital_score, leads.digital_score),
                        digital_tier = COALESCE(excluded.digital_tier, leads.digital_tier),
                        gaps = CASE WHEN excluded.gaps != '[]' THEN excluded.gaps ELSE leads.gaps END,
                        recommended_services = CASE WHEN excluded.recommended_services != '[]' THEN excluded.recommended_services ELSE leads.recommended_services END,
                        cta_fr = CASE WHEN excluded.cta_fr != '' THEN excluded.cta_fr ELSE leads.cta_fr END,
                        cta_ar = CASE WHEN excluded.cta_ar != '' THEN excluded.cta_ar ELSE leads.cta_ar END,
                        analysis_model = COALESCE(excluded.analysis_model, leads.analysis_model),
                        priority_score = MAX(excluded.priority_score, leads.priority_score),
                        score_breakdown = CASE WHEN excluded.score_breakdown != '{}' THEN excluded.score_breakdown ELSE leads.score_breakdown END,
                        rating = MAX(excluded.rating, leads.rating),
                        review_count = MAX(excluded.review_count, leads.review_count),
                        latitude = COALESCE(excluded.latitude, leads.latitude),
                        longitude = COALESCE(excluded.longitude, leads.longitude),
                        updated_at = excluded.updated_at
                    RETURNING id
                    """,
                    (
                        fp, lead.name, lead.industry, lead.wilaya, lead.address, lead.website,
                        lead.phone, lead.email, social_json,
                        lead.rating, lead.review_count, lead.latitude, lead.longitude,
                        lead.source.value, lead.source_url,
                        phones_json, lead.freshness.model_dump_json(),
                        lead.digital_score, lead.digital_tier, gaps_json, services_json,
                        lead.cta_fr, lead.cta_ar, lead.analysis_model,
                        lead.priority_score, breakdown_json,
                        lead.status.value, tags_json, int(lead.is_contact), lead.notes,
                        discovered, now,
                    ),
                )
                row = cur.fetchone()
                return (int(row["id"]) if row else 0), not existed

        return await asyncio.to_thread(_execute)

    async def upsert_many(self, leads: list[Lead]) -> tuple[int, int]:
        """Batched upsert. Returns (created, merged)."""
        created = merged = 0
        for lead in leads:
            _, was_created = await self.upsert(lead)
            if was_created:
                created += 1
            else:
                merged += 1
        return created, merged

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    async def get(self, lead_id: int) -> Optional[Lead]:
        def _execute() -> Optional[Lead]:
            with self._db.connection() as conn:
                row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
                return self._row_to_lead(row) if row else None
        return await asyncio.to_thread(_execute)

    async def get_by_fingerprint(self, fingerprint: str) -> Optional[Lead]:
        def _execute() -> Optional[Lead]:
            with self._db.connection() as conn:
                row = conn.execute(
                    "SELECT * FROM leads WHERE fingerprint = ?", (fingerprint,)
                ).fetchone()
                return self._row_to_lead(row) if row else None
        return await asyncio.to_thread(_execute)

    async def list_leads(
        self,
        q: Optional[str] = None,
        wilaya: Optional[str] = None,
        industry: Optional[str] = None,
        status: Optional[str] = None,
        is_contact: Optional[bool] = None,
        tag: Optional[str] = None,
        age_class: Optional[str] = None,
        min_score: float = 0.0,
        sort_by: str = "priority_score",
        sort_order: str = "desc",
        limit: int = 50,
        offset: int = 0,
        exclude_rejected: bool = True,
    ) -> list[Lead]:
        """Unified listing: full-text search (``q``) AND every structured
        filter compose in a single query (v4 Task 5 — the old UI had to
        switch to /leads/search and silently drop all other filters)."""
        clauses: list[str] = []
        params: list[Any] = []

        if q and q.strip():
            phrase = fts_sanitize(q.strip())
            if phrase:
                clauses.append("leads.id IN (SELECT rowid FROM leads_fts WHERE leads_fts MATCH ?)")
                params.append(phrase)

        if min_score > 0:
            clauses.append("priority_score >= ?")
            params.append(min_score)
        if wilaya:
            clauses.append("LOWER(wilaya) = LOWER(?)")
            params.append(wilaya.strip())
        if industry:
            clauses.append("LOWER(industry) LIKE LOWER(?)")
            params.append(f"%{industry.strip()}%")
        if status:
            clauses.append("status = ?")
            params.append(status)
        elif exclude_rejected:
            clauses.append("status != 'rejected'")
        if is_contact is not None:
            clauses.append("is_contact = ?")
            params.append(1 if is_contact else 0)
        if age_class:
            clauses.append("json_extract(freshness, '$.calculated_age_class') = ?")
            params.append(age_class)
        if tag:
            clauses.append("EXISTS (SELECT 1 FROM json_each(leads.tags) WHERE LOWER(value) = LOWER(?))")
            params.append(tag.strip())

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        col = _SORT_COLUMNS.get(sort_by, "priority_score")
        direction = "ASC" if sort_order.lower() == "asc" else "DESC"
        sql = f"SELECT * FROM leads {where} ORDER BY {col} {direction} LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        def _execute() -> list[Lead]:
            with self._db.connection() as conn:
                rows = conn.execute(sql, params).fetchall()
                return [self._row_to_lead(r) for r in rows]
        return await asyncio.to_thread(_execute)

    async def search(self, term: str, limit: int = 20) -> list[Lead]:
        """FTS5 search; input sanitized into a quoted phrase (no syntax errors)."""
        phrase = fts_sanitize(term)
        if not phrase:
            return []
        sql = (
            "SELECT l.* FROM leads l JOIN leads_fts f ON f.rowid = l.id "
            "WHERE leads_fts MATCH ? ORDER BY rank LIMIT ?"
        )

        def _execute() -> list[Lead]:
            with self._db.connection() as conn:
                rows = conn.execute(sql, (phrase, limit)).fetchall()
                return [self._row_to_lead(r) for r in rows]
        return await asyncio.to_thread(_execute)

    async def list_unanalyzed(self, limit: int = 200) -> list[Lead]:
        """Leads that still lack a deterministic audit (fixes the v2 bug where
        list_unresolved == list_all re-analyzed everything every run)."""
        sql = (
            "SELECT * FROM leads WHERE digital_score IS NULL "
            "ORDER BY discovered_at DESC LIMIT ?"
        )

        def _execute() -> list[Lead]:
            with self._db.connection() as conn:
                rows = conn.execute(sql, (limit,)).fetchall()
                return [self._row_to_lead(r) for r in rows]
        return await asyncio.to_thread(_execute)

    async def list_unscored(self, limit: int = 500) -> list[Lead]:
        """Leads with a computed score of zero (fixes the v2 bug where
        score_all re-scored only the top-N by existing score)."""
        sql = (
            "SELECT * FROM leads WHERE priority_score = 0.0 AND status != 'rejected' "
            "ORDER BY discovered_at DESC LIMIT ?"
        )

        def _execute() -> list[Lead]:
            with self._db.connection() as conn:
                rows = conn.execute(sql, (limit,)).fetchall()
                return [self._row_to_lead(r) for r in rows]
        return await asyncio.to_thread(_execute)

    async def all_for_resolution(self, limit: int = 20_000) -> list[Lead]:
        sql = "SELECT * FROM leads ORDER BY id LIMIT ?"

        def _execute() -> list[Lead]:
            with self._db.connection() as conn:
                rows = conn.execute(sql, (limit,)).fetchall()
                return [self._row_to_lead(r) for r in rows]
        return await asyncio.to_thread(_execute)

    async def get_many(self, lead_ids: list[int]) -> list[Lead]:
        """Fetch leads by id (order follows input; missing ids skipped)."""
        if not lead_ids:
            return []
        ph = ",".join("?" for _ in lead_ids)

        def _execute() -> list[Lead]:
            with self._db.connection() as conn:
                rows = conn.execute(
                    f"SELECT * FROM leads WHERE id IN ({ph})", lead_ids
                ).fetchall()
                by_id = {r["id"]: r for r in rows}
                return [self._row_to_lead(by_id[i]) for i in lead_ids if i in by_id]
        return await asyncio.to_thread(_execute)

    async def set_cluster(self, lead_id: int, cluster_id: Optional[int]) -> None:
        def _execute() -> None:
            with self._db.connection() as conn:
                conn.execute(
                    "UPDATE leads SET cluster_id = ?, updated_at = ? WHERE id = ?",
                    (cluster_id, _now_iso(), lead_id),
                )
        await asyncio.to_thread(_execute)

    # ------------------------------------------------------------------
    # CRM mutations (status-preserving policies unified)
    # ------------------------------------------------------------------
    _PRESERVED = ("contacted", "rejected", "verified")

    async def update_fields(
        self, lead_id: int, *, name: str, industry: str, wilaya: str,
        phone: Optional[str], email: Optional[str], website: Optional[str],
        address: Optional[str], tags: list[str], notes: Optional[str],
    ) -> None:
        def _execute() -> None:
            with self._db.connection() as conn:
                conn.execute(
                    """
                    UPDATE leads SET name = ?, industry = ?, wilaya = ?, phone = ?, email = ?,
                        website = ?, address = ?, tags = ?, notes = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (name, industry, wilaya, phone, email, website, address,
                     json.dumps(tags, ensure_ascii=False), notes, _now_iso(), lead_id),
                )
        await asyncio.to_thread(_execute)

    async def set_status(self, lead_id: int, status: LeadStatus) -> None:
        def _execute() -> None:
            with self._db.connection() as conn:
                conn.execute(
                    "UPDATE leads SET status = ?, updated_at = ? WHERE id = ?",
                    (status.value, _now_iso(), lead_id),
                )
        await asyncio.to_thread(_execute)

    async def set_bulk_status(self, lead_ids: list[int], status: LeadStatus) -> int:
        def _execute() -> int:
            with self._db.connection() as conn:
                placeholders = ",".join("?" for _ in lead_ids)
                cur = conn.execute(
                    f"UPDATE leads SET status = ?, updated_at = ? WHERE id IN ({placeholders})",
                    (status.value, _now_iso(), *lead_ids),
                )
                return cur.rowcount
        return await asyncio.to_thread(_execute)

    async def set_contact(self, lead_id: int, is_contact: bool) -> None:
        def _execute() -> None:
            with self._db.connection() as conn:
                conn.execute(
                    "UPDATE leads SET is_contact = ?, "
                    "status = CASE WHEN ? = 1 AND status IN ('discovered','analyzed','scored') "
                    "              THEN 'contacted' ELSE status END, "
                    "updated_at = ? WHERE id = ?",
                    (int(is_contact), int(is_contact), _now_iso(), lead_id),
                )
        await asyncio.to_thread(_execute)

    async def set_bulk_contact(self, lead_ids: list[int], is_contact: bool) -> int:
        def _execute() -> int:
            with self._db.connection() as conn:
                placeholders = ",".join("?" for _ in lead_ids)
                cur = conn.execute(
                    f"UPDATE leads SET is_contact = ?, updated_at = ? WHERE id IN ({placeholders})",
                    (int(is_contact), _now_iso(), *lead_ids),
                )
                return cur.rowcount
        return await asyncio.to_thread(_execute)

    async def set_tags(self, lead_id: int, tags: list[str]) -> None:
        def _execute() -> None:
            with self._db.connection() as conn:
                conn.execute(
                    "UPDATE leads SET tags = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(tags, ensure_ascii=False), _now_iso(), lead_id),
                )
        await asyncio.to_thread(_execute)

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------
    async def stats(self) -> dict[str, Any]:
        def _execute() -> dict[str, Any]:
            with self._db.connection() as conn:
                total = conn.execute(
                    "SELECT COUNT(*) FROM leads WHERE status != 'rejected'"
                ).fetchone()[0]
                analyzed = conn.execute(
                    "SELECT COUNT(*) FROM leads WHERE digital_score IS NOT NULL AND status != 'rejected'"
                ).fetchone()[0]
                contacts = conn.execute(
                    "SELECT COUNT(*) FROM leads WHERE is_contact = 1 AND status != 'rejected'"
                ).fetchone()[0]
                avg = conn.execute(
                    "SELECT AVG(priority_score) FROM leads WHERE status != 'rejected'"
                ).fetchone()[0] or 0.0
                clusters = conn.execute("SELECT COUNT(*) FROM entity_clusters").fetchone()[0]
                age_rows = conn.execute(
                    "SELECT json_extract(freshness, '$.calculated_age_class') AS cls, COUNT(*) AS n "
                    "FROM leads GROUP BY cls"
                ).fetchall()
                return {
                    "total_leads": total,
                    "analyzed_leads": analyzed,
                    "active_contacts": contacts,
                    "average_score": round(avg, 1),
                    "total_resolved_entities": clusters,
                    "age_breakdown": {r["cls"] or "older": r["n"] for r in age_rows},
                }
        return await asyncio.to_thread(_execute)

    async def all_tags(self) -> list[str]:
        def _execute() -> list[str]:
            with self._db.connection() as conn:
                rows = conn.execute(
                    "SELECT tags FROM leads WHERE tags IS NOT NULL AND tags != '[]'"
                ).fetchall()
                found: set[str] = set()
                for r in rows:
                    try:
                        for t in json.loads(r["tags"]):
                            if t and str(t).strip():
                                found.add(str(t).strip())
                    except (json.JSONDecodeError, TypeError):
                        continue
                return sorted(found)
        return await asyncio.to_thread(_execute)

    async def search_vocabulary(self) -> list[str]:
        """Autocomplete vocabulary (names + wilayas + industries), cached briefly."""
        now = time.monotonic()
        if now - self._vocab_cache[0] < self._vocab_ttl:
            return self._vocab_cache[1]

        def _execute() -> list[str]:
            with self._db.connection() as conn:
                names = conn.execute("SELECT name FROM leads LIMIT 4000").fetchall()
                vocab: set[str] = set()
                for r in names:
                    for token in _FTS_TOKEN_RE.findall(r["name"] or ""):
                        if len(token) >= 3:
                            vocab.add(token)
                return sorted(vocab)[:500]

        words = await asyncio.to_thread(_execute)
        self._vocab_cache = (now, words)
        return words

    async def count(self) -> int:
        def _execute() -> int:
            with self._db.connection() as conn:
                return conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        return await asyncio.to_thread(_execute)

    async def count_by_wilaya(self) -> dict[str, int]:
        """Aggregated lead counts per wilaya (lowercase name -> n).

        Used by the geographic catalogue — a GROUP BY instead of loading
        rows, per the performance contract (aggregate before transport)."""

        def _execute() -> dict[str, int]:
            with self._db.connection() as conn:
                rows = conn.execute(
                    "SELECT LOWER(wilaya) AS w, COUNT(*) AS n FROM leads "
                    "WHERE wilaya != '' AND wilaya IS NOT NULL GROUP BY w"
                ).fetchall()
                return {r["w"]: r["n"] for r in rows}

        return await asyncio.to_thread(_execute)

    async def count_geolocated(self) -> int:
        """Leads with GPS coordinates (map overlay sizing)."""

        def _execute() -> int:
            with self._db.connection() as conn:
                return conn.execute(
                    "SELECT COUNT(*) FROM leads WHERE latitude IS NOT NULL AND longitude IS NOT NULL"
                ).fetchone()[0]

        return await asyncio.to_thread(_execute)

    # ------------------------------------------------------------------
    # Campaigns
    # ------------------------------------------------------------------
    async def create_campaign(self, query: str, wilaya: Optional[str], limit: int) -> int:
        def _execute() -> int:
            with self._db.connection() as conn:
                cur = conn.execute(
                    "INSERT INTO discovery_campaigns (query, wilaya, target_limit, status, created_at, updated_at)"
                    " VALUES (?, ?, ?, 'processing', ?, ?)",
                    (query, wilaya, limit, _now_iso(), _now_iso()),
                )
                return int(cur.lastrowid or 0)
        return await asyncio.to_thread(_execute)

    async def finish_campaign(
        self, campaign_id: int, status: str, discovered: int, saved: int, duplicates: int
    ) -> None:
        def _execute() -> None:
            with self._db.connection() as conn:
                conn.execute(
                    "UPDATE discovery_campaigns SET status = ?, discovered_count = ?, saved_count = ?,"
                    " duplicate_count = ?, updated_at = ? WHERE id = ?",
                    (status, discovered, saved, duplicates, _now_iso(), campaign_id),
                )
        await asyncio.to_thread(_execute)

    async def list_campaigns(self, limit: int = 10) -> list[dict[str, Any]]:
        def _execute() -> list[dict[str, Any]]:
            with self._db.connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM discovery_campaigns ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                return [dict(r) for r in rows]
        return await asyncio.to_thread(_execute)

    # ------------------------------------------------------------------
    # Attachments
    # ------------------------------------------------------------------
    async def add_attachment(
        self, lead_id: int, filename: str, mime_type: str, size: int
    ) -> int:
        def _execute() -> int:
            with self._db.connection() as conn:
                cur = conn.execute(
                    "INSERT INTO lead_attachments (lead_id, filename, mime_type, file_size_bytes, created_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (lead_id, filename, mime_type, size, _now_iso()),
                )
                return int(cur.lastrowid or 0)
        return await asyncio.to_thread(_execute)

    async def list_attachments(self, lead_id: int) -> list[dict[str, Any]]:
        def _execute() -> list[dict[str, Any]]:
            with self._db.connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM lead_attachments WHERE lead_id = ? ORDER BY id",
                    (lead_id,),
                ).fetchall()
                return [dict(r) for r in rows]
        return await asyncio.to_thread(_execute)

    async def get_attachment(self, attachment_id: int) -> Optional[dict[str, Any]]:
        def _execute() -> Optional[dict[str, Any]]:
            with self._db.connection() as conn:
                row = conn.execute(
                    "SELECT * FROM lead_attachments WHERE id = ?", (attachment_id,)
                ).fetchone()
                return dict(row) if row else None
        return await asyncio.to_thread(_execute)

    async def delete_attachment(self, attachment_id: int) -> None:
        def _execute() -> None:
            with self._db.connection() as conn:
                conn.execute("DELETE FROM lead_attachments WHERE id = ?", (attachment_id,))
        await asyncio.to_thread(_execute)

    # ------------------------------------------------------------------
    # Row mapping
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_lead(row: sqlite3.Row) -> Lead:
        try:
            phones = [PhoneDetails(**p) for p in json.loads(row["phone_details"] or "[]")]
        except Exception:
            phones = []
        try:
            socials = json.loads(row["social_links"] or "[]")
        except (json.JSONDecodeError, TypeError):
            socials = []
        try:
            factors = json.loads(row["score_breakdown"] or "{}")
        except (json.JSONDecodeError, TypeError):
            factors = {}
        try:
            gaps = json.loads(row["gaps"] or "[]")
        except (json.JSONDecodeError, TypeError):
            gaps = []
        try:
            services = json.loads(row["recommended_services"] or "[]")
        except (json.JSONDecodeError, TypeError):
            services = []
        try:
            tags = json.loads(row["tags"] or "[]")
        except (json.JSONDecodeError, TypeError):
            tags = []
        try:
            freshness = FreshnessMetadata(**json.loads(row["freshness"] or "{}"))
        except Exception:
            freshness = FreshnessMetadata()

        def _dt(value: Optional[str]) -> datetime:
            if not value:
                return utcnow()
            try:
                parsed = datetime.fromisoformat(value)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                return utcnow()

        return Lead(
            id=row["id"],
            name=row["name"],
            industry=row["industry"] or "",
            wilaya=row["wilaya"] or "",
            address=row["address"],
            website=row["website"],
            phone=row["phone"],
            email=row["email"],
            social_links=socials,
            rating=float(row["rating"] or 0.0),
            review_count=int(row["review_count"] or 0),
            latitude=row["latitude"],
            longitude=row["longitude"],
            source=DataSource(row["source"]) if row["source"] else DataSource.DUCKDUCKGO,
            source_url=row["source_url"],
            phone_details=phones,
            freshness=freshness,
            digital_score=row["digital_score"],
            digital_tier=row["digital_tier"],
            gaps=gaps,
            recommended_services=services,
            cta_fr=row["cta_fr"] or "",
            cta_ar=row["cta_ar"] or "",
            analysis_model=row["analysis_model"],
            priority_score=float(row["priority_score"] or 0.0),
            score_breakdown=factors,
            cluster_id=row["cluster_id"],
            status=LeadStatus(row["status"]) if row["status"] else LeadStatus.DISCOVERED,
            tags=tags,
            is_contact=bool(row["is_contact"]),
            notes=row["notes"],
            discovered_at=_dt(row["discovered_at"]),
            updated_at=_dt(row["updated_at"]),
        )
