"""Read-side repository that joins raw_records + analyses + lead_scores.

This is the repository the API layer talks to when listing leads for the
dashboard. It does not own a table — it composes a read model from three
underlying tables via a JOIN.
"""

from __future__ import annotations

import asyncio
import json
import logging
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
        limit: int = 100,
        offset: int = 0,
    ) -> list[Lead]:
        # COALESCE handles newly discovered leads that do not have scores yet
        # Second clause strictly filters out blocked leads (status = 'rejected')
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
        where = " WHERE " + " AND ".join(clauses)
        sql = (
            self._base_query()
            + where
            + " ORDER BY COALESCE(s.priority_score, 0.0) DESC, r.created_at DESC LIMIT ? OFFSET ?"
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

    async def search(self, term: str, limit: int = 50) -> list[Lead]:
        """Use the FTS5 mirror for fast full-text search, excluding blocked leads."""
        sql = """
            SELECT r.*
            FROM raw_records_fts f
            JOIN raw_records r ON r.id = f.rowid
            LEFT JOIN lead_scores s ON s.raw_record_id = r.id
            WHERE raw_records_fts MATCH ?
              AND COALESCE(s.status, 'discovered') != 'rejected'
            ORDER BY rank
            LIMIT ?
        """
        fts_query = _build_fts_query(term)

        def _execute():
            with self._db.connection() as conn:
                return conn.execute(sql, (fts_query, limit)).fetchall()
        rows = await asyncio.to_thread(_execute)
        return [self._row_to_lead(r, fetch_relations=False) for r in rows]

    async def stats(self) -> dict[str, Any]:
        def _execute():
            with self._db.connection() as conn:
                total = conn.execute("SELECT COUNT(*) FROM raw_records r LEFT JOIN lead_scores s ON s.raw_record_id = r.id WHERE COALESCE(s.status, 'discovered') != 'rejected'").fetchone()[0]
                analyzed = conn.execute("SELECT COUNT(*) FROM analyses a LEFT JOIN lead_scores s ON s.raw_record_id = a.raw_record_id WHERE COALESCE(s.status, 'discovered') != 'rejected'").fetchone()[0]
                scored = conn.execute(
                    "SELECT COUNT(*) FROM lead_scores WHERE priority_score > 0 AND status != 'rejected'"
                ).fetchone()[0]
                avg_score = conn.execute(
                    "SELECT AVG(priority_score) FROM lead_scores WHERE status != 'rejected'"
                ).fetchone()[0] or 0.0
                top_wilayas = [
                    {"wilaya": r[0], "count": r[1]}
                    for r in conn.execute(
                        "SELECT wilaya, COUNT(*) c FROM raw_records r LEFT JOIN lead_scores s ON s.raw_record_id = r.id WHERE COALESCE(s.status, 'discovered') != 'rejected' GROUP BY wilaya ORDER BY c DESC LIMIT 10"
                    ).fetchall()
                ]
                top_industries = [
                    {"industry": r[0], "count": r[1]}
                    for r in conn.execute(
                        "SELECT industry, COUNT(*) c FROM raw_records r LEFT JOIN lead_scores s ON s.raw_record_id = r.id WHERE COALESCE(s.status, 'discovered') != 'rejected' GROUP BY industry ORDER BY c DESC LIMIT 10"
                    ).fetchall()
                ]
                sources = [
                    {"source": r[0], "count": r[1]}
                    for r in conn.execute(
                        "SELECT source, COUNT(*) c FROM raw_records r LEFT JOIN lead_scores s ON s.raw_record_id = r.id WHERE COALESCE(s.status, 'discovered') != 'rejected' GROUP BY source ORDER BY c DESC"
                    ).fetchall()
                ]
                age_breakdown = [
                    {"age_class": r[0], "count": r[1]}
                    for r in conn.execute(
                        "SELECT calculated_age_class, COUNT(*) c FROM raw_records r LEFT JOIN lead_scores s ON s.raw_record_id = r.id WHERE COALESCE(s.status, 'discovered') != 'rejected' GROUP BY calculated_age_class ORDER BY c DESC"
                    ).fetchall()
                ]
                return {
                    "total_leads": total,
                    "analyzed_leads": analyzed,
                    "scored_leads": scored,
                    "unanalyzed_leads": total - analyzed,
                    "average_score": round(avg_score, 2),
                    "top_wilayas": top_wilayas,
                    "top_industries": top_industries,
                    "sources": sources,
                    "age_breakdown": age_breakdown,
                }
        return await asyncio.to_thread(_execute)

    # ------------------------------------------------------------------
    #  Internals
    # ------------------------------------------------------------------

    def _base_query(self) -> str:
        return """
            SELECT
                r.id, r.fingerprint, r.name, r.industry, r.wilaya, r.address,
                r.website, r.phone, r.email, r.social_media_handles, r.rating,
                r.review_count, r.latitude, r.longitude, r.source, r.source_url,
                r.phone_metadata, r.discovered_at, r.last_updated,
                r.relative_age_hint, r.calculated_age_class, r.created_at,
                a.pain_points, a.recommended_solutions, a.digital_presence_score,
                a.pitch_angles, a.estimated_monthly_revenue_usd, a.analysis_model,
                a.from_cache, a.analyzed_at,
                s.priority_score, s.score_breakdown, s.status, s.tags, s.computed_at
            FROM raw_records r
            LEFT JOIN analyses  a ON a.raw_record_id = r.id
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

        return Lead(
            id=row["id"],
            business=business,
            analysis=analysis,
            priority_score=float(row["priority_score"] or 0.0),
            score_breakdown=breakdown,
            status=status,
            tags=tags,
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


def _build_fts_query(term: str) -> str:
    """Convert a free-text search term into an FTS5 query string.

    Splits on whitespace and ORs the tokens so a search for "pharmacie
    oran" matches any record containing either word.
    """
    if not term:
        return '""'
    # Escape double quotes and wrap each token in quotes.
    tokens = [f'"{t.replace("\"", "\"\"")}"' for t in term.split() if t]
    return " OR ".join(tokens) if tokens else '""'