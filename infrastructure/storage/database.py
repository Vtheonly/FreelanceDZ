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

# Tables whose v2.0.0 (schema-v1-era) shapes collide with the v2 baseline:
# the baseline's CREATE TABLE IF NOT EXISTS is skipped for them, and the
# follow-up index/trigger statements then reference columns that do not
# exist ("no such column: lead_id"). Mapping: table -> (v2 marker column,
# v1 marker column). Renaming preserves the rows for migration 8 to fold
# into the fresh v2 tables.
_LEGACY_SHAPE_TABLES: dict[str, tuple[str, str]] = {
    "lead_attachments": ("lead_id", "raw_record_id"),          # v2.0.0 migration 7
    "discovery_campaigns": ("target_limit", "limit_num"),     # v2.0.0 migration 5
}


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
            # v4 Task 15: journal_mode=WAL is a database-level persistent
            # setting — re-declaring it per connection acquires an exclusive
            # lock to verify WAL status on every operation. It is set once
            # in initialise(); here we only tune per-connection behaviour.
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA busy_timeout = 5000;")
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
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA busy_timeout = 5000;")
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
            # WAL is switched on exactly once per database lifetime (v4
            # Task 15); the mode persists in the file itself.
            conn.execute("PRAGMA journal_mode = WAL;")
            self._reconcile_legacy_tables(conn)
            # Explicit BEGIN/COMMIT makes the baseline all-or-nothing:
            # executescript otherwise autocommits statement by statement,
            # so a mid-script failure leaves a half-applied schema behind
            # (exactly the v3.0.0 startup crash on v2.0.0 databases).
            conn.executescript(
                "BEGIN;\n" + SCHEMA_FILE.read_text(encoding="utf-8") + "\nCOMMIT;"
            )
            self._run_migrations(conn)
            logger.info("Database ready at %s", self._db_path)

    @staticmethod
    def _reconcile_legacy_tables(conn: sqlite3.Connection) -> None:
        """Rename legacy-shaped tables that would collide with the v2 baseline.

        A v2.0.0 database carries ``lead_attachments`` keyed by
        ``raw_record_id`` (migration 7) and ``discovery_campaigns`` with
        ``limit_num`` / ``*_qty`` columns (migration 5). The v2 baseline
        cannot CREATE its versions (IF NOT EXISTS skips them) and its index
        on ``lead_attachments (lead_id)`` then fails. Renaming the legacy
        table to ``legacy_<name>`` lets the baseline create the fresh shape;
        migration 8 folds the legacy rows back in and drops the shell.
        Idempotent: each table is renamed at most once, and a table that
        already has the v2 shape (or does not exist) is left alone.
        """
        for table, (v2_col, v1_col) in _LEGACY_SHAPE_TABLES.items():
            cols = {
                r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if not cols or v2_col in cols:
                continue
            legacy = f"legacy_{table}"
            logger.warning(
                "Legacy-shaped %s table detected (has %s, v2 expects %s) — "
                "renaming to %s for migration into schema v2",
                table, v1_col, v2_col, legacy,
            )
            conn.execute(f"ALTER TABLE {table} RENAME TO {legacy}")

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
def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (name,)
    ).fetchone() is not None


def _fold_legacy_tables(conn: sqlite3.Connection, raw_records_present: bool) -> None:
    """Fold rows from tables renamed by ``_reconcile_legacy_tables`` into
    their v2 counterparts, then drop the legacy shells.

    Must run while ``raw_records`` still exists (attachment rows map through
    raw_record_id -> fingerprint -> new lead id) and before the v1 tables
    are dropped (their ON DELETE CASCADE would destroy the legacy rows).
    When raw_records is already gone the attachment rows are unmappable and
    are simply dropped; campaigns fold independently of raw_records.
    """
    if _table_exists(conn, "legacy_lead_attachments"):
        if raw_records_present:
            # file_path is not carried over: v2 attachments are metadata
            # rows (file_size_bytes unknown for legacy rows -> 0).
            conn.execute(
                """
                INSERT INTO lead_attachments (lead_id, filename, mime_type, file_size_bytes, created_at)
                SELECT l.id, a.filename, a.mime_type, 0, a.created_at
                FROM legacy_lead_attachments a
                JOIN raw_records r ON r.id = a.raw_record_id
                JOIN leads l ON l.fingerprint = r.fingerprint
                """
            )
        conn.execute("DROP TABLE legacy_lead_attachments")

    if _table_exists(conn, "legacy_discovery_campaigns"):
        conn.execute(
            """
            INSERT INTO discovery_campaigns
                (query, wilaya, target_limit, status, discovered_count, saved_count,
                 duplicate_count, created_at, updated_at)
            SELECT query, wilaya, limit_num, status,
                   COALESCE(discovered_qty, 0), COALESCE(saved_qty, 0), 0,
                   created_at, updated_at
            FROM legacy_discovery_campaigns
            """
        )
        conn.execute("DROP TABLE legacy_discovery_campaigns")


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
        # Fresh install — nothing to consolidate, but fold/drop any legacy
        # shells left behind by earlier (failed) initialisations.
        _fold_legacy_tables(conn, raw_records_present=False)
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

    # Fold tables renamed by the legacy reconciliation pre-pass. This must
    # happen before the drops below: legacy lead_attachments rows reference
    # raw_records and would be CASCADE-deleted with it, and the fold maps
    # them through raw_records -> fingerprint -> leads.id.
    _fold_legacy_tables(conn, raw_records_present=True)

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


# ---------------------------------------------------------------------------
# Migration 9 — entity resolution v3.1: decision log, review queue,
# entity relations, and canonical-record columns on entity_clusters.
#
# The three new tables are created by the v2 baseline for fresh installs
# (and re-created here idempotently for databases initialised before this
# schema revision). The entity_clusters columns must be ALTERed on
# pre-3.1 databases because the baseline's CREATE TABLE IF NOT EXISTS
# skips an existing (old-shaped) table.
# ---------------------------------------------------------------------------
def _ensure_column(conn: sqlite3.Connection, table: str, column: str,
                   ddl_type: str, default: str) -> None:
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type} NOT NULL DEFAULT {default}"
        )


@DatabaseManager.register_migration(9, "entity resolution v3.1: decisions, review, relations")
def _migrate_resolution_v31(conn: sqlite3.Connection) -> None:
    for stmt in (
        """
        CREATE TABLE IF NOT EXISTS resolution_decisions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_a       INTEGER NOT NULL,
            lead_b       INTEGER NOT NULL,
            decision     TEXT NOT NULL,
            relationship TEXT,
            score        REAL NOT NULL DEFAULT 0.0,
            signals      TEXT NOT NULL DEFAULT '{}',
            explanation  TEXT NOT NULL DEFAULT '',
            mode         TEXT NOT NULL DEFAULT 'batch',
            decided_by   TEXT NOT NULL DEFAULT 'engine',
            created_at   TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_res_decisions_lead_a ON resolution_decisions (lead_a)",
        "CREATE INDEX IF NOT EXISTS idx_res_decisions_lead_b ON resolution_decisions (lead_b)",
        "CREATE INDEX IF NOT EXISTS idx_res_decisions_created ON resolution_decisions (created_at)",
        """
        CREATE TABLE IF NOT EXISTS review_queue (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_a      INTEGER NOT NULL,
            lead_b      INTEGER NOT NULL,
            score       REAL NOT NULL DEFAULT 0.0,
            evidence    TEXT NOT NULL DEFAULT '{}',
            explanation TEXT NOT NULL DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'pending',
            created_at  TEXT NOT NULL,
            resolved_at TEXT,
            UNIQUE (lead_a, lead_b, status)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue (status)",
        """
        CREATE TABLE IF NOT EXISTS entity_relations (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            cluster_a    INTEGER NOT NULL REFERENCES entity_clusters (id) ON DELETE CASCADE,
            cluster_b    INTEGER NOT NULL REFERENCES entity_clusters (id) ON DELETE CASCADE,
            relationship TEXT NOT NULL,
            confidence   REAL NOT NULL DEFAULT 0.0,
            explanation  TEXT NOT NULL DEFAULT '',
            created_at   TEXT NOT NULL,
            UNIQUE (cluster_a, cluster_b, relationship)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_entity_relations_a ON entity_relations (cluster_a)",
        "CREATE INDEX IF NOT EXISTS idx_entity_relations_b ON entity_relations (cluster_b)",
    ):
        conn.execute(stmt)

    _ensure_column(conn, "entity_clusters", "aliases", "TEXT", "'[]'")
    _ensure_column(conn, "entity_clusters", "canonical_fields", "TEXT", "'{}'")
    _ensure_column(conn, "entity_clusters", "evidence_summary", "TEXT", "'{}'")

    logger.info("entity resolution v3.1 tables ready")


# ---------------------------------------------------------------------------
# Migration 10 — checkpoints: geographic POIs for field operations
# (refactorv5 Step 4). Created idempotently for fresh installs and
# pre-existing databases alike.
# ---------------------------------------------------------------------------
@DatabaseManager.register_migration(10, "add checkpoints table for POI geospatial tracking")
def _migrate_checkpoints(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS checkpoints (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            category    TEXT NOT NULL DEFAULT 'prospect',
            wilaya      TEXT NOT NULL DEFAULT '',
            latitude    REAL NOT NULL,
            longitude   REAL NOT NULL,
            notes       TEXT,
            status      TEXT NOT NULL DEFAULT 'active',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_wilaya ON checkpoints (wilaya)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_category ON checkpoints (category)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_status ON checkpoints (status)")
    logger.info("checkpoints table and indices verified")
