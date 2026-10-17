"""SQLite storage engine — WAL mode, versioned idempotent migrations.

v3 keeps the v2 migration-registry pattern (decorator-registered, ordered,
recorded in schema_migrations) with schema_v2.sql as the baseline and a
single v1->v2 consolidation migration for existing databases.

Connection policy: per-operation connections (SQLite in WAL mode scales
better with short-lived connections than a shared handle under contention
from asyncio.to_thread workers; connection setup is ~10us). Every repo
method offloads blocking work via asyncio.to_thread.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Optional

from config.settings import get_settings

logger = logging.getLogger("storage.database")

SCHEMA_FILE = Path(__file__).resolve().parent / "schema_v2.sql"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DatabaseManager:
    """Thread-safe, migration-aware SQLite manager (WAL, per-op connections)."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        settings = get_settings()
        self._db_path = Path(db_path) if db_path else settings.resolved_db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.initialise()

    @property
    def db_path(self) -> Path:
        return self._db_path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(
            str(self._db_path),
            timeout=30.0,
            isolation_level="",          # explicit transaction control
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    @contextmanager
    def immediate_connection(self) -> Iterator[sqlite3.Connection]:
        """Write-priority connection: BEGIN IMMEDIATE avoids the
        SELECT-then-UPDATE race between concurrent claimants."""
        conn = sqlite3.connect(
            str(self._db_path),
            timeout=30.0,
            isolation_level=None,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("BEGIN IMMEDIATE;")
            yield conn
            conn.execute("COMMIT;")
        except Exception:
            try:
                conn.execute("ROLLBACK;")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    def initialise(self) -> None:
        with self._lock, self.connection() as conn:
            conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
            self._run_migrations(conn)
            logger.info("Database ready at %s", self._db_path)

    def integrity_check(self, quick: bool = True) -> bool:
        stmt = "PRAGMA quick_check;" if quick else "PRAGMA integrity_check;"
        with self.connection() as conn:
            row = conn.execute(stmt).fetchone()
            return bool(row and row[0] == "ok")

    # ------------------------------------------------------------------
    # Migration registry
    # ------------------------------------------------------------------
    _MIGRATIONS: dict[int, tuple[str, Callable[[sqlite3.Connection], None]]] = {}

    def _run_migrations(self, conn: sqlite3.Connection) -> None:
        applied = {
            int(r["version"])
            for r in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for version in sorted(self._MIGRATIONS):
            if version in applied:
                continue
            description, migrate = self._MIGRATIONS[version]
            logger.info("Applying migration %d: %s", version, description)
            migrate(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version, description, applied_at) VALUES (?, ?, ?)",
                (version, description, _now_iso()),
            )

    @classmethod
    def register_migration(cls, version: int, description: str):
        def decorator(fn: Callable[[sqlite3.Connection], None]) -> Callable[[sqlite3.Connection], None]:
            cls._MIGRATIONS[version] = (description, fn)
            return fn
        return decorator


# ---------------------------------------------------------------------------
# Migration 8 — consolidate v1 (raw_records + analyses + lead_scores +
# resolved_entities) into the unified v2 `leads` schema.
# No-op on fresh installs (detected via raw_records absence).
# ---------------------------------------------------------------------------
def _ensure_entity_links_v2(conn: sqlite3.Connection) -> None:
    """Guarantee the v2 entity_links shape (cluster_id/lead_id) and indexes.
    On v1 databases the old entity_links (entity_id/raw_record_id) still
    exists at this point; it is dropped by the consolidation below and this
    helper runs again afterwards."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(entity_links)").fetchall()}
    if cols and "cluster_id" not in cols:
        conn.execute("DROP TABLE entity_links")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entity_links (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            cluster_id     INTEGER NOT NULL REFERENCES entity_clusters (id) ON DELETE CASCADE,
            lead_id        INTEGER NOT NULL REFERENCES leads (id) ON DELETE CASCADE,
            match_score    REAL NOT NULL DEFAULT 1.0,
            match_reasons  TEXT NOT NULL DEFAULT '[]',
            linked_at      TEXT NOT NULL,
            UNIQUE (cluster_id, lead_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_links_cluster ON entity_links (cluster_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_links_lead ON entity_links (lead_id)")


@DatabaseManager.register_migration(8, "unify v1 tables into leads (schema v2)")
def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Consolidate v1 (raw_records + analyses + lead_scores + resolved_entities)
    into the unified v2 `leads` schema. No-op (besides index ensure) on fresh
    installs, detected via raw_records absence."""
    _ensure_entity_links_v2(conn)

    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='raw_records'"
    ).fetchone()
    if not exists:
        return

    has_is_contact = "is_contact" in {
        r["name"] for r in conn.execute("PRAGMA table_info(lead_scores)").fetchall()
    }

    conn.execute(
        """
        INSERT OR IGNORE INTO leads (
            fingerprint, name, industry, wilaya, address, website, phone, email,
            social_links, rating, review_count, latitude, longitude, source, source_url,
            phone_details, freshness, digital_score, gaps, recommended_services,
            analysis_model, priority_score, score_breakdown, status, tags, is_contact,
            notes, discovered_at, updated_at
        )
        SELECT
            r.fingerprint, r.name, r.industry, r.wilaya, r.address, r.website, r.phone, r.email,
            COALESCE(r.social_media_handles, '[]'), r.rating, r.review_count,
            r.latitude, r.longitude, r.source, r.source_url,
            COALESCE(r.phone_metadata, '[]'),
            json_object(
                'discovered_at', r.discovered_at,
                'last_updated', r.last_updated,
                'relative_age_hint', r.relative_age_hint,
                'calculated_age_class', r.calculated_age_class
            ),
            a.digital_presence_score,
            COALESCE(a.pain_points, '[]'),
            COALESCE(a.recommended_solutions, '[]'),
            a.analysis_model,
            COALESCE(s.priority_score, 0.0),
            COALESCE(s.score_breakdown, '{}'),
            COALESCE(s.status, 'discovered'),
            COALESCE(s.tags, '[]'),
            CASE WHEN s.is_contact = 1 THEN 1 ELSE 0 END,
            NULL,
            r.discovered_at,
            r.created_at
        FROM raw_records r
        LEFT JOIN analyses a ON a.raw_record_id = r.id
        LEFT JOIN lead_scores s ON s.raw_record_id = r.id
        """
        if has_is_contact
        else """
        INSERT OR IGNORE INTO leads (
            fingerprint, name, industry, wilaya, address, website, phone, email,
            social_links, rating, review_count, latitude, longitude, source, source_url,
            phone_details, freshness, digital_score, gaps, recommended_services,
            analysis_model, priority_score, score_breakdown, status, tags, is_contact,
            notes, discovered_at, updated_at
        )
        SELECT
            r.fingerprint, r.name, r.industry, r.wilaya, r.address, r.website, r.phone, r.email,
            COALESCE(r.social_media_handles, '[]'), r.rating, r.review_count,
            r.latitude, r.longitude, r.source, r.source_url,
            COALESCE(r.phone_metadata, '[]'),
            json_object(
                'discovered_at', r.discovered_at,
                'last_updated', r.last_updated,
                'relative_age_hint', r.relative_age_hint,
                'calculated_age_class', r.calculated_age_class
            ),
            a.digital_presence_score,
            COALESCE(a.pain_points, '[]'),
            COALESCE(a.recommended_solutions, '[]'),
            a.analysis_model,
            COALESCE(s.priority_score, 0.0),
            COALESCE(s.score_breakdown, '{}'),
            COALESCE(s.status, 'discovered'),
            COALESCE(s.tags, '[]'),
            0,
            NULL,
            r.discovered_at,
            r.created_at
        FROM raw_records r
        LEFT JOIN analyses a ON a.raw_record_id = r.id
        LEFT JOIN lead_scores s ON s.raw_record_id = r.id
        """
    )

    # Capture v1 lineage into memory BEFORE any table drops.
    id_to_fp = {
        r["id"]: r["fingerprint"]
        for r in conn.execute("SELECT id, fingerprint FROM raw_records").fetchall()
    }
    try:
        legacy_entities = conn.execute(
            "SELECT name, industry, wilaya, confidence, strategy, raw_record_ids, last_resolved_at"
            " FROM resolved_entities"
        ).fetchall()
    except sqlite3.OperationalError:
        legacy_entities = []

    # Drop v1 artifacts. Order matters under PRAGMA foreign_keys=ON:
    # children first (analyses, lead_scores), then parents
    # (resolved_entities, raw_records). entity_links (v1 shape) was already
    # dropped by _ensure_entity_links_v2; recreate it in v2 shape.
    conn.execute("DROP TABLE IF EXISTS analyses")
    conn.execute("DROP TABLE IF EXISTS lead_scores")
    conn.execute("DROP TABLE IF EXISTS resolved_entities")
    conn.execute("DROP TABLE IF EXISTS raw_records")
    conn.execute("DROP TABLE IF EXISTS raw_records_fts")
    _ensure_entity_links_v2(conn)

    # Map v1 resolved_entities -> v2 entity_clusters (+ links + cluster_id).
    for ent in legacy_entities:
        try:
            raw_ids = json.loads(ent["raw_record_ids"] or "[]")
        except (json.JSONDecodeError, TypeError):
            raw_ids = []
        fps = [id_to_fp[rid] for rid in raw_ids if rid in id_to_fp]
        if not fps:
            continue
        fp_ph = ",".join("?" for _ in fps)
        members = conn.execute(
            f"SELECT id FROM leads WHERE fingerprint IN ({fp_ph})", fps
        ).fetchall()
        if not members:
            continue

        cur = conn.execute(
            """INSERT INTO entity_clusters
               (canonical_lead_id, name, industry, wilaya, confidence, member_count, strategy, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                members[0]["id"], ent["name"], ent["industry"], ent["wilaya"],
                ent["confidence"], len(members), ent["strategy"],
                ent["last_resolved_at"], _now_iso(),
            ),
        )
        cluster_id = cur.lastrowid
        for m in members:
            conn.execute(
                "INSERT OR IGNORE INTO entity_links (cluster_id, lead_id, match_score, match_reasons, linked_at)"
                " VALUES (?, ?, ?, '[]', ?)",
                (cluster_id, m["id"], ent["confidence"], _now_iso()),
            )
            conn.execute("UPDATE leads SET cluster_id = ? WHERE id = ?", (cluster_id, m["id"]))

    logger.info("v1 -> v2 consolidation complete")
