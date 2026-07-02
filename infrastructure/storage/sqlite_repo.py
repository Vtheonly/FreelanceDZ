"""SQLite repository — implements `core.interfaces.ILeadRepository`.

A single file-based SQLite database is plenty for the project's scale
(thousands of leads, low-RAM Docker). For larger deployments one could
swap in a Postgres adapter implementing the same interface.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from config.settings import settings, PROJECT_ROOT
from core.interfaces import ILeadRepository
from domain.exceptions import StorageError
from domain.models import (
    BusinessRaw,
    DataSource,
    Lead,
    LeadAnalysis,
    LeadStatus,
    ProposedService,
)


_SCHEMA_PATH = PROJECT_ROOT / "infrastructure" / "storage" / "schema.sql"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteLeadRepository(ILeadRepository):
    """File-based SQLite repository."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = str(db_path or settings.resolved_db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger("storage.sqlite")
        self.init_schema()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        try:
            yield conn
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            self._logger.error("SQLite error: %s", e)
            raise StorageError(str(e)) from e
        finally:
            conn.close()

    # Update init_schema to safely auto-migrate older database files
    def init_schema(self) -> None:
        schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        with self._conn() as c:
            c.executescript(schema_sql)
        # Migration: dynamically add 'tags' column to businesses table if not exists
        try:
            with self._conn() as c:
                c.execute("ALTER TABLE businesses ADD COLUMN tags TEXT;")
        except Exception:
            pass # Column already exists
        self._logger.debug("Schema initialised at %s", self._db_path)

    # Update save_business to write initial blank tag JSON:
    def save_business(self, business: BusinessRaw) -> Optional[int]:
        """Insert a business, skip on duplicate fingerprint. Return id (or None)."""
        fp = business.fingerprint()
        with self._conn() as c:
            # Check existing.
            row = c.execute("SELECT id FROM businesses WHERE fingerprint = ?", (fp,)).fetchone()
            if row is not None:
                self._logger.debug("Duplicate business skipped: %s (id=%d)", business.name, row["id"])
                return None

            social_json = json.dumps(business.social_media_handles, ensure_ascii=False)
            now = _now_iso()
            cur = c.execute(
                """INSERT INTO businesses
                   (fingerprint, name, industry, wilaya, address, website, phone, email,
                    social_media_handles, rating, review_count, latitude, longitude,
                    source, source_url, tags, discovered_at, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    fp, business.name, business.industry, business.wilaya, business.address,
                    business.website, business.phone, business.email, social_json,
                    business.rating, business.review_count, business.latitude, business.longitude,
                    business.source.value, business.source_url, "[]",
                    business.discovered_at.isoformat() if business.discovered_at else now,
                    now, now,
                ),
            )
            business_id = cur.lastrowid

            # Create an empty score row so the lead appears in lists immediately.
            c.execute(
                """INSERT OR IGNORE INTO lead_scores (business_id, priority_score, status, computed_at)
                   VALUES (?, 0.0, ?, ?)""",
                (business_id, LeadStatus.DISCOVERED.value, now),
            )
        self._logger.debug("Saved business id=%d (%s)", business_id, business.name)
        return business_id

    # Update _base_query to include b.tags:
    def _base_query(self) -> str:
        return """
            SELECT
                b.id, b.name, b.industry, b.wilaya, b.address, b.website, b.phone, b.email,
                b.social_media_handles, b.rating, b.review_count, b.latitude, b.longitude,
                b.source, b.source_url, b.tags, b.discovered_at, b.created_at, b.updated_at,
                a.pain_points, a.recommended_solutions, a.digital_presence_score,
                a.pitch_angles, a.estimated_monthly_revenue_usd, a.analysis_model,
                a.from_cache, a.analyzed_at,
                s.priority_score, s.status, s.computed_at
            FROM businesses b
            LEFT JOIN analyses  a ON a.business_id = b.id
            LEFT JOIN lead_scores s ON s.business_id = b.id
        """

    # Update _row_to_lead mapping:
    def _row_to_lead(self, row: sqlite3.Row) -> Lead:
        row_dict = dict(row)
        b_id = row_dict["id"]
        # Decode business.
        social = json.loads(row_dict["social_media_handles"] or "[]")
        business = BusinessRaw(
            name=row_dict["name"],
            industry=row_dict["industry"],
            wilaya=row_dict["wilaya"],
            address=row_dict["address"],
            website=row_dict["website"],
            phone=row_dict["phone"],
            email=row_dict["email"],
            social_media_handles=social,
            rating=float(row_dict["rating"] or 0.0),
            review_count=int(row_dict["review_count"] or 0),
            latitude=row_dict["latitude"],
            longitude=row_dict["longitude"],
            source=DataSource(row_dict["source"]),
            source_url=row_dict["source_url"],
            discovered_at=datetime.fromisoformat(row_dict["discovered_at"]) if row_dict["discovered_at"] else None,
        )

        analysis: Optional[LeadAnalysis] = None
        if row_dict.get("analyzed_at"):
            solutions_data = json.loads(row_dict["recommended_solutions"] or "[]")
            solutions = [ProposedService(**s) for s in solutions_data]
            analysis = LeadAnalysis(
                pain_points=json.loads(row_dict["pain_points"] or "[]"),
                recommended_solutions=solutions,
                digital_presence_score=int(row_dict["digital_presence_score"] or 50),
                pitch_angles=json.loads(row_dict["pitch_angles"] or "[]"),
                estimated_monthly_revenue_usd=row_dict["estimated_monthly_revenue_usd"],
                analysis_model=row_dict["analysis_model"],
                from_cache=bool(row_dict["from_cache"]),
                analyzed_at=datetime.fromisoformat(row_dict["analyzed_at"]),
            )

        status_str = row_dict.get("status") or LeadStatus.DISCOVERED.value
        try:
            status = LeadStatus(status_str)
        except ValueError:
            status = LeadStatus.DISCOVERED

        tags_json = row_dict.get("tags") or "[]"
        tags = json.loads(tags_json)

        return Lead(
            id=b_id,
            business=business,
            analysis=analysis,
            priority_score=float(row_dict.get("priority_score") or 0.0),
            status=status,
            tags=tags,
            created_at=datetime.fromisoformat(row_dict["created_at"]) if row_dict.get("created_at") else None,
            updated_at=datetime.fromisoformat(row_dict["updated_at"]) if row_dict.get("updated_at") else None,
        )

    # Add the concrete implementation for tag writes:
    def set_tags(self, business_id: int, tags: List[str]) -> None:
        tags_json = json.dumps(tags, ensure_ascii=False)
        with self._conn() as c:
            c.execute("UPDATE businesses SET tags = ?, updated_at = ? WHERE id = ?", (tags_json, _now_iso(), business_id))


    def attach_analysis(self, business_id: int, analysis: LeadAnalysis) -> None:
        solutions_json = json.dumps(
            [s.model_dump(mode="json") for s in analysis.recommended_solutions],
            ensure_ascii=False,
        )
        pain_json = json.dumps(analysis.pain_points, ensure_ascii=False)
        pitch_json = json.dumps(analysis.pitch_angles, ensure_ascii=False)

        with self._conn() as c:
            # Upsert analysis.
            c.execute(
                """INSERT INTO analyses
                   (business_id, pain_points, recommended_solutions, digital_presence_score,
                    pitch_angles, estimated_monthly_revenue_usd, analysis_model, from_cache, analyzed_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(business_id) DO UPDATE SET
                     pain_points=excluded.pain_points,
                     recommended_solutions=excluded.recommended_solutions,
                     digital_presence_score=excluded.digital_presence_score,
                     pitch_angles=excluded.pitch_angles,
                     estimated_monthly_revenue_usd=excluded.estimated_monthly_revenue_usd,
                     analysis_model=excluded.analysis_model,
                     from_cache=excluded.from_cache,
                     analyzed_at=excluded.analyzed_at""",
                (
                    business_id, pain_json, solutions_json, analysis.digital_presence_score,
                    pitch_json, analysis.estimated_monthly_revenue_usd,
                    analysis.analysis_model, int(analysis.from_cache),
                    analysis.analyzed_at.isoformat() if analysis.analyzed_at else _now_iso(),
                ),
            )
            # Update lead_scores status.
            c.execute(
                """INSERT INTO lead_scores (business_id, priority_score, status, computed_at)
                   VALUES (?, 0.0, ?, ?)
                   ON CONFLICT(business_id) DO UPDATE SET status=excluded.status""",
                (business_id, LeadStatus.ANALYZED.value, _now_iso()),
            )
            # Bump businesses.updated_at.
            c.execute("UPDATE businesses SET updated_at = ? WHERE id = ?", (_now_iso(), business_id))
        self._logger.debug("Attached analysis to business id=%d", business_id)

    def update_score(self, business_id: int, score: float, breakdown: Optional[Dict[str, float]] = None) -> None:
        breakdown_json = json.dumps(breakdown or {}, ensure_ascii=False)
        with self._conn() as c:
            # If status is currently 'analyzed', promote to 'scored'.
            c.execute(
                """INSERT INTO lead_scores (business_id, priority_score, score_breakdown, status, computed_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(business_id) DO UPDATE SET
                     priority_score=excluded.priority_score,
                     score_breakdown=excluded.score_breakdown,
                     status=CASE
                       WHEN lead_scores.status = 'contacted' OR lead_scores.status = 'rejected'
                       THEN lead_scores.status
                       ELSE 'scored'
                     END,
                     computed_at=excluded.computed_at""",
                (business_id, score, breakdown_json, LeadStatus.SCORED.value, _now_iso()),
            )
        self._logger.debug("Updated score for business id=%d → %.2f", business_id, score)

    def set_status(self, business_id: int, status: LeadStatus) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO lead_scores (business_id, priority_score, status, computed_at)
                   VALUES (?, 0.0, ?, ?)
                   ON CONFLICT(business_id) DO UPDATE SET status=excluded.status""",
                (business_id, status.value, _now_iso()),
            )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------


    def list_unanalyzed(self, limit: int = 100) -> List[Lead]:
        sql = self._base_query() + " WHERE a.business_id IS NULL ORDER BY b.created_at ASC LIMIT ?"
        with self._conn() as c:
            rows = c.execute(sql, (limit,)).fetchall()
        return [self._row_to_lead(r) for r in rows]

    def list_leads(
        self,
        wilaya: Optional[str] = None,
        industry: Optional[str] = None,
        min_score: float = 0.0,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Lead]:
        clauses = ["s.priority_score >= ?"]
        params: List[Any] = [min_score]
        if wilaya:
            clauses.append("LOWER(b.wilaya) = LOWER(?)")
            params.append(wilaya)
        if industry:
            clauses.append("LOWER(b.industry) LIKE LOWER(?)")
            params.append(f"%{industry}%")
        where = " WHERE " + " AND ".join(clauses)
        sql = self._base_query() + where + " ORDER BY s.priority_score DESC, b.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [self._row_to_lead(r) for r in rows]

    def get_lead(self, lead_id: int) -> Optional[Lead]:
        sql = self._base_query() + " WHERE b.id = ?"
        with self._conn() as c:
            row = c.execute(sql, (lead_id,)).fetchone()
        return self._row_to_lead(row) if row else None

    def count_leads(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM businesses").fetchone()[0]

    def count_analyzed(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]

    def search(self, term: str, limit: int = 50) -> List[Lead]:
        like = f"%{term}%"
        sql = (
            self._base_query()
            + " WHERE b.name LIKE ? OR b.industry LIKE ? OR b.wilaya LIKE ? OR b.phone LIKE ? "
              "ORDER BY s.priority_score DESC LIMIT ?"
        )
        with self._conn() as c:
            rows = c.execute(sql, (like, like, like, like, limit)).fetchall()
        return [self._row_to_lead(r) for r in rows]

    def stats(self) -> Dict[str, Any]:
        with self._conn() as c:
            total = c.execute("SELECT COUNT(*) FROM businesses").fetchone()[0]
            analyzed = c.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
            scored = c.execute("SELECT COUNT(*) FROM lead_scores WHERE priority_score > 0").fetchone()[0]
            avg_score = c.execute("SELECT AVG(priority_score) FROM lead_scores").fetchone()[0] or 0.0

            # Top wilayas.
            top_wilayas = [
                {"wilaya": r[0], "count": r[1]}
                for r in c.execute(
                    "SELECT wilaya, COUNT(*) c FROM businesses GROUP BY wilaya ORDER BY c DESC LIMIT 10"
                ).fetchall()
            ]

            # Top industries.
            top_industries = [
                {"industry": r[0], "count": r[1]}
                for r in c.execute(
                    "SELECT industry, COUNT(*) c FROM businesses GROUP BY industry ORDER BY c DESC LIMIT 10"
                ).fetchall()
            ]

            # Source breakdown.
            sources = [
                {"source": r[0], "count": r[1]}
                for r in c.execute(
                    "SELECT source, COUNT(*) c FROM businesses GROUP BY source ORDER BY c DESC"
                ).fetchall()
            ]

            # Total estimated pipeline value.
            pipeline_value = 0.0
            for row in c.execute("SELECT recommended_solutions FROM analyses").fetchall():
                try:
                    sols = json.loads(row["recommended_solutions"] or "[]")
                    pipeline_value += sum(float(s.get("estimated_value_usd", 0)) for s in sols)
                except (json.JSONDecodeError, TypeError):
                    continue

            return {
                "total_leads": total,
                "analyzed_leads": analyzed,
                "scored_leads": scored,
                "unanalyzed_leads": total - analyzed,
                "average_score": round(avg_score, 2),
                "top_wilayas": top_wilayas,
                "top_industries": top_industries,
                "sources": sources,
                "estimated_pipeline_usd": round(pipeline_value, 2),
            }
