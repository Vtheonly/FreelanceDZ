"""Read-side repository that joins raw_records + analyses + lead_scores.

This is the repository the API layer talks to when listing leads for the
dashboard. It does not own a table — it composes a read model from three
underlying tables via a JOIN.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from core.interfaces import ILeadRepository
from domain.enums import DataSource, FreshnessAge, LeadStatus
from domain.models import BusinessRaw, Lead, LeadAnalysis, ProposedService
from domain.value_objects import FreshnessMetadata, PhoneDetails
from infrastructure.storage.database import DatabaseManager


_logger = logging.getLogger("storage.lead_repo")


class LeadRepository(ILeadRepository):
    """Read-side lead view composed from raw_records + analyses + lead_scores."""

    _vocab_cache: Optional[list[str]] = None
    _vocab_cache_time: Optional[float] = None

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    # ------------------------------------------------------------------
    #  Writes (delegated to the underlying tables)
    # ------------------------------------------------------------------

    async def attach_analysis(self, business_id: int, analysis: LeadAnalysis) -> None:
        solutions_json = json.dumps(
            [s.model_dump(mode="json") for s in analysis.recommended_solutions],
            ensure_ascii=False,
        )
        pain_json = json.dumps(analysis.pain_points, ensure_ascii=False)
        pitch_json = json.dumps(analysis.pitch_angles, ensure_ascii=False)
        analyzed_at = analysis.analyzed_at.isoformat() if analysis.analyzed_at else _now_iso()

        def _execute():
            with self._db.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO analyses (
                        raw_record_id, pain_points, recommended_solutions,
                        digital_presence_score, pitch_angles,
                        estimated_monthly_revenue_usd, analysis_model, from_cache, analyzed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(raw_record_id) DO UPDATE SET
                        pain_points                   = excluded.pain_points,
                        recommended_solutions         = excluded.recommended_solutions,
                        digital_presence_score        = excluded.digital_presence_score,
                        pitch_angles                  = excluded.pitch_angles,
                        estimated_monthly_revenue_usd = excluded.estimated_monthly_revenue_usd,
                        analysis_model                = excluded.analysis_model,
                        from_cache                    = excluded.from_cache,
                        analyzed_at                   = excluded.analyzed_at
                    """,
                    (
                        business_id, pain_json, solutions_json,
                        analysis.digital_presence_score, pitch_json,
                        analysis.estimated_monthly_revenue_usd, analysis.analysis_model,
                        int(analysis.from_cache), analyzed_at,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO lead_scores (raw_record_id, priority_score, status, computed_at)
                    VALUES (?, 0.0, ?, ?)
                    ON CONFLICT(raw_record_id) DO UPDATE SET status = excluded.status
                    """,
                    (business_id, LeadStatus.ANALYZED.value, _now_iso()),
                )
        await asyncio.to_thread(_execute)
        _logger.debug("Attached analysis to raw_record_id=%d", business_id)

    async def update_score(
        self,
        business_id: int,
        score: float,
        breakdown: Optional[dict[str, float]] = None,
    ) -> None:
        breakdown_json = json.dumps(breakdown or {}, ensure_ascii=False)

        def _execute():
            with self._db.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO lead_scores (raw_record_id, priority_score, score_breakdown, status, computed_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(raw_record_id) DO UPDATE SET
                        priority_score  = excluded.priority_score,
                        score_breakdown = excluded.score_breakdown,
                        status = CASE
                            WHEN lead_scores.status IN ('contacted', 'rejected') THEN lead_scores.status
                            ELSE 'scored'
                        END,
                        computed_at = excluded.computed_at
                    """,
                    (business_id, score, breakdown_json, LeadStatus.SCORED.value, _now_iso()),
                )
        await asyncio.to_thread(_execute)

    async def set_status(self, business_id: int, status: LeadStatus) -> None:
        def _execute():
            with self._db.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO lead_scores (raw_record_id, priority_score, status, computed_at)
                    VALUES (?, 0.0, ?, ?)
                    ON CONFLICT(raw_record_id) DO UPDATE SET status = excluded.status
                    """,
                    (business_id, status.value, _now_iso()),
                )
        await asyncio.to_thread(_execute)

    async def set_tags(self, business_id: int, tags: list[str]) -> None:
        tags_json = json.dumps(tags, ensure_ascii=False)
        def _execute():
            with self._db.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO lead_scores (raw_record_id, priority_score, status, tags, computed_at)
                    VALUES (?, 0.0, 'discovered', ?, ?)
                    ON CONFLICT(raw_record_id) DO UPDATE SET tags = excluded.tags
                    """,
                    (business_id, tags_json, _now_iso()),
                )
        await asyncio.to_thread(_execute)

    async def set_contact_status(self, business_id: int, is_contact: bool) -> None:
        def _execute():
            with self._db.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO lead_scores (raw_record_id, priority_score, status, is_contact, computed_at)
                    VALUES (?, 0.0, 'discovered', ?, ?)
                    ON CONFLICT(raw_record_id) DO UPDATE SET is_contact = excluded.is_contact, computed_at = excluded.computed_at
                    """,
                    (business_id, int(is_contact), _now_iso()),
                )
        await asyncio.to_thread(_execute)

    async def update_lead_details(
        self,
        business_id: int,
        name: str,
        tags: list[str],
        address: Optional[str] = None,
        website: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
    ) -> None:
        tags_json = json.dumps(tags, ensure_ascii=False)
        def _execute():
            with self._db.connection() as conn:
                # Update attributes in raw_records
                conn.execute(
                    """
                    UPDATE raw_records
                    SET name = ?, address = ?, website = ?, phone = ?, email = ?
                    WHERE id = ?
                    """,
                    (name, address, website, phone, email, business_id),
                )
                # Update lead_scores
                conn.execute(
                    """
                    INSERT INTO lead_scores (raw_record_id, priority_score, status, tags, computed_at)
                    VALUES (?, 0.0, 'discovered', ?, ?)
                    ON CONFLICT(raw_record_id) DO UPDATE SET tags = excluded.tags, computed_at = excluded.computed_at
                    """,
                    (business_id, tags_json, _now_iso()),
                )
        await asyncio.to_thread(_execute)

    async def bulk_set_contact_status(self, business_ids: list[int], is_contact: bool) -> None:
        if not business_ids:
            return
        def _execute():
            now = _now_iso()
            with self._db.connection() as conn:
                for b_id in business_ids:
                    conn.execute(
                        """
                        INSERT INTO lead_scores (raw_record_id, priority_score, status, is_contact, computed_at)
                        VALUES (?, 0.0, 'discovered', ?, ?)
                        ON CONFLICT(raw_record_id) DO UPDATE SET is_contact = excluded.is_contact, computed_at = excluded.computed_at
                        """,
                        (b_id, int(is_contact), now),
                    )
        await asyncio.to_thread(_execute)
        _logger.info("Successfully completed bulk contacts toggle for %d records", len(business_ids))

    async def bulk_set_status(self, business_ids: list[int], status: LeadStatus) -> None:
        if not business_ids:
            return
        def _execute():
            now = _now_iso()
            with self._db.connection() as conn:
                for b_id in business_ids:
                    conn.execute(
                        """
                        INSERT INTO lead_scores (raw_record_id, priority_score, status, computed_at)
                        VALUES (?, 0.0, ?, ?)
                        ON CONFLICT(raw_record_id) DO UPDATE SET status = excluded.status, computed_at = excluded.computed_at
                        """,
                        (b_id, status.value, now),
                    )
        await asyncio.to_thread(_execute)
        _logger.info("Successfully completed bulk status update for %d records", len(business_ids))

    async def get_all_tags(self) -> list[str]:
        def _execute():
            with self._db.connection() as conn:
                rows = conn.execute("SELECT tags FROM lead_scores WHERE tags IS NOT NULL AND tags != '[]'").fetchall()
                all_tags = set()
                for r in rows:
                    try:
                        for t in json.loads(r["tags"]):
                            if t and t.strip():
                                all_tags.add(t.strip())
                    except Exception:
                        pass
                return sorted(list(all_tags))
        return await asyncio.to_thread(_execute)

    async def create_manual_lead(self, business: BusinessRaw, tags: list[str]) -> int:
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
        tags_json = json.dumps(tags, ensure_ascii=False)

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
                        address              = COALESCE(address, excluded.address),
                        website              = COALESCE(website, excluded.website),
                        phone                = COALESCE(phone, excluded.phone),
                        email                = COALESCE(email, excluded.email)
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
                row_id = cursor.lastrowid
                if not row_id:
                    row = conn.execute(
                        "SELECT id FROM raw_records WHERE fingerprint = ?", (fp,)
                    ).fetchone()
                    row_id = row["id"] if row else None

                if row_id is not None:
                    conn.execute(
                        """
                        INSERT INTO lead_scores (raw_record_id, priority_score, status, tags, computed_at)
                        VALUES (?, 0.0, ?, ?, ?)
                        ON CONFLICT(raw_record_id) DO UPDATE SET tags = excluded.tags
                        """,
                        (row_id, LeadStatus.VERIFIED.value, tags_json, now),
                    )
                return row_id
        return await asyncio.to_thread(_execute)

    async def add_attachment(self, raw_record_id: int, filename: str, mime_type: str, file_path: str) -> int:
        now = _now_iso()
        def _execute():
            with self._db.connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO lead_attachments (raw_record_id, filename, mime_type, file_path, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (raw_record_id, filename, mime_type, file_path, now),
                )
                return cursor.lastrowid
        return await asyncio.to_thread(_execute)

    async def get_attachments(self, raw_record_id: int) -> list[dict]:
        def _execute():
            with self._db.connection() as conn:
                rows = conn.execute(
                    "SELECT id, filename, mime_type, created_at FROM lead_attachments WHERE raw_record_id = ? ORDER BY created_at DESC",
                    (raw_record_id,),
                ).fetchall()
                return [dict(r) for r in rows]
        return await asyncio.to_thread(_execute)

    async def delete_attachment(self, attachment_id: int) -> bool:
        def _get_and_delete():
            with self._db.connection() as conn:
                row = conn.execute(
                    "SELECT file_path FROM lead_attachments WHERE id = ?",
                    (attachment_id,)
                ).fetchone()
                if not row:
                    return False
                file_path = row["file_path"]
                conn.execute("DELETE FROM lead_attachments WHERE id = ?", (attachment_id,))
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                except Exception as exc:
                    _logger.warning("Could not delete physical attachment file: %s", exc)
                return True
        return await asyncio.to_thread(_get_and_delete)

    # ------------------------------------------------------------------
    #  Reads
    # ------------------------------------------------------------------

    async def get_lead(self, lead_id: int) -> Optional[Lead]:
        sql = self._base_query() + " WHERE r.id = ?"
        def _execute():
            with self._db.connection() as conn:
                return conn.execute(sql, (lead_id,)).fetchone()
        row = await asyncio.to_thread(_execute)
        return self._row_to_lead(row) if row else None

    async def list_leads(
        self,
        wilaya: Optional[str] = None,
        industry: Optional[str] = None,
        age_class: Optional[FreshnessAge] = None,
        min_score: float = 0.0,
        is_contact: Optional[bool] = None,
        tag: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_order: str = "desc",
        limit: int = 100,
        offset: int = 0,
    ) -> list[Lead]:
        clauses = [
            "COALESCE(s.priority_score, 0.0) >= ?",
            "COALESCE(s.status, 'discovered') != 'rejected'"
        ]
        params: list[Any] = [min_score]
        if wilaya:
            clauses.append("LOWER(r.wilaya) = LOWER(?)")
            params.append(wilaya)
        if industry:
            clauses.append("LOWER(r.industry) LIKE LOWER(?)")
            params.append(f"%{industry}%")
        if age_class:
            clauses.append("r.calculated_age_class = ?")
            params.append(age_class.value)
        if is_contact is not None:
            clauses.append("COALESCE(s.is_contact, 0) = ?")
            params.append(1 if is_contact else 0)
        if tag:
            clauses.append("EXISTS (SELECT 1 FROM json_each(CASE WHEN json_valid(COALESCE(s.tags, '[]')) THEN s.tags ELSE '[]' END) WHERE LOWER(value) = LOWER(?))")
            params.append(tag)

        # Build dynamic column sorting safely
        sort_col = "COALESCE(s.priority_score, 0.0)"
        if sort_by == "name":
            sort_col = "r.name"
        elif sort_by == "industry":
            sort_col = "r.industry"
        elif sort_by == "wilaya":
            sort_col = "r.wilaya"
        elif sort_by == "phone":
            sort_col = "r.phone"
        elif sort_by == "source":
            sort_col = "r.source"
        elif sort_by == "freshness":
            sort_col = "r.calculated_age_class"
        elif sort_by == "status":
            sort_col = "COALESCE(s.status, 'discovered')"
        elif sort_by == "tags":
            sort_col = "s.tags"

        direction = "DESC" if sort_order.lower() == "desc" else "ASC"

        where = " WHERE " + " AND ".join(clauses)
        sql = (
            self._base_query()
            + where
            + f" ORDER BY {sort_col} {direction}, r.created_at DESC LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])

        def _execute():
            with self._db.connection() as conn:
                return conn.execute(sql, params).fetchall()
        rows = await asyncio.to_thread(_execute)
        return [self._row_to_lead(r) for r in rows]

    async def count_leads(self) -> int:
        def _execute():
            with self._db.connection() as conn:
                return conn.execute("SELECT COUNT(*) FROM raw_records r LEFT JOIN lead_scores s ON s.raw_record_id = r.id WHERE COALESCE(s.status, 'discovered') != 'rejected'").fetchone()[0]
        return await asyncio.to_thread(_execute)

    async def count_analyzed(self) -> int:
        def _execute():
            with self._db.connection() as conn:
                return conn.execute("SELECT COUNT(*) FROM analyses a JOIN lead_scores s ON s.raw_record_id = a.raw_record_id WHERE COALESCE(s.status, 'discovered') != 'rejected'").fetchone()[0]
        return await asyncio.to_thread(_execute)

    async def search(self, term: str, is_contact: Optional[bool] = None, limit: int = 50) -> list[Lead]:
        sql = """
            SELECT r.*, s.status, s.tags, s.priority_score, s.score_breakdown, COALESCE(s.is_contact, 0) AS is_contact
            FROM raw_records_fts f
            JOIN raw_records r ON r.id = f.rowid
            LEFT JOIN lead_scores s ON s.raw_record_id = r.id
            WHERE raw_records_fts MATCH ?
              AND COALESCE(s.status, 'discovered') != 'rejected'
        """
        params = [term]
        if is_contact is not None:
            sql += " AND COALESCE(s.is_contact, 0) = ?"
            params.append(1 if is_contact else 0)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        def _execute():
            with self._db.connection() as conn:
                return conn.execute(sql, params).fetchall()
        rows = await asyncio.to_thread(_execute)
        return [self._row_to_lead(r, fetch_relations=False) for r in rows]

    async def stats(self) -> dict[str, Any]:
        def _execute():
            with self._db.connection() as conn:
                total_active = conn.execute("SELECT COUNT(*) FROM raw_records r LEFT JOIN lead_scores s ON s.raw_record_id = r.id WHERE COALESCE(s.status, '') != 'rejected'").fetchone()[0]
                analyzed = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
                avg_score = conn.execute("SELECT AVG(priority_score) FROM lead_scores WHERE status != 'rejected'").fetchone()[0] or 0.0
                return {
                    "total_leads": total_active,
                    "analyzed_leads": analyzed,
                    "average_score": avg_score,
                    "age_breakdown": []
                }
        return await asyncio.to_thread(_execute)

    async def get_search_vocabulary(self) -> list[str]:
        import time
        now = time.monotonic()
        if self._vocab_cache is not None and self._vocab_cache_time is not None:
            if now - self._vocab_cache_time < 30.0:  # Cache vocabulary list for 30 seconds
                return self._vocab_cache

        def _execute():
            import re
            with self._db.connection() as conn:
                rows = conn.execute(
                    "SELECT name, industry, wilaya, address, website, email, phone FROM raw_records"
                ).fetchall()
                words = set()
                for row in rows:
                    for field in row:
                        if field:
                            tokens = re.findall(r"\b[\w\-']+\b", str(field), re.UNICODE)
                            for t in tokens:
                                if len(t) >= 2:
                                    words.add(t)
                return sorted(list(words))

        vocab = await asyncio.to_thread(_execute)
        self._vocab_cache = vocab
        self._vocab_cache_time = now
        return vocab

    # ------------------------------------------------------------------
    #  Serialisation helper mapping
    # ------------------------------------------------------------------

    def _base_query(self) -> str:
        return """
            SELECT r.id, r.fingerprint, r.name, r.industry, r.wilaya, r.address, r.website,
                   r.phone, r.email, r.social_media_handles, r.rating, r.review_count,
                   r.latitude, r.longitude, r.source, r.source_url, r.phone_metadata,
                   r.discovered_at, r.last_updated, r.relative_age_hint, r.calculated_age_class,
                   r.created_at,
                   a.pain_points, a.recommended_solutions, a.digital_presence_score,
                   a.pitch_angles, a.estimated_monthly_revenue_usd, a.analysis_model,
                   a.from_cache, a.analyzed_at,
                   s.priority_score, s.score_breakdown, s.status, s.tags, s.computed_at,
                   COALESCE(s.is_contact, 0) AS is_contact
            FROM raw_records r
            LEFT JOIN analyses a ON a.raw_record_id = r.id
            LEFT JOIN lead_scores s ON s.raw_record_id = r.id
        """

    def _row_to_lead(self, row, fetch_relations: bool = True) -> Lead:
        social = json.loads(row["social_media_handles"] or "[]")
        phone_meta = [
            PhoneDetails(**p) for p in json.loads(row["phone_metadata"] or "[]")
        ]
        freshness = FreshnessMetadata(
            discovered_at=_parse_dt(row["discovered_at"]),
            last_updated=_parse_dt(row["last_updated"]) if row["last_updated"] else None,
            relative_age_hint=row["relative_age_hint"],
            calculated_age_class=FreshnessAge(row["calculated_age_class"]),
        )
        business = BusinessRaw(
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
        )

        analysis: Optional[LeadAnalysis] = None
        if fetch_relations and row["analyzed_at"]:
            solutions = [
                ProposedService(**s)
                for s in json.loads(row["recommended_solutions"] or "[]")
            ]
            analysis = LeadAnalysis(
                pain_points=json.loads(row["pain_points"] or "[]"),
                recommended_solutions=solutions,
                digital_presence_score=int(row["digital_presence_score"] or 50),
                pitch_angles=json.loads(row["pitch_angles"] or "[]"),
                estimated_monthly_revenue_usd=row["estimated_monthly_revenue_usd"],
                analysis_model=row["analysis_model"],
                from_cache=bool(row["from_cache"]),
                analyzed_at=_parse_dt(row["analyzed_at"]),
            )

        status_str = row["status"] or LeadStatus.DISCOVERED.value
        try:
            status = LeadStatus(status_str)
        except ValueError:
            status = LeadStatus.DISCOVERED

        tags = json.loads(row["tags"] or "[]") if "tags" in row.keys() and row["tags"] else []
        breakdown = (
            json.loads(row["score_breakdown"] or "{}")
            if "score_breakdown" in row.keys() and row["score_breakdown"]
            else None
        )

        is_contact_val = bool(row["is_contact"]) if "is_contact" in row.keys() else False

        return Lead(
            id=row["id"],
            business=business,
            analysis=analysis,
            priority_score=float(row["priority_score"] or 0.0),
            score_breakdown=breakdown,
            status=status,
            tags=tags,
            is_contact=is_contact_val,
            created_at=_parse_dt(row["created_at"]) or datetime.now(timezone.utc),
            updated_at=_parse_dt(row["computed_at"]) or datetime.now(timezone.utc),
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