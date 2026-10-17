"""Regression tests: upgrading a REAL v2.0.0 database to schema v2.

v3.0.0 shipped a migration path tested only against a synthetic v1 database
that lacked the tables v2.0.0 added through its Python migrations 5-7
(``discovery_campaigns`` with limit_num/*_qty columns and ``lead_attachments``
keyed by raw_record_id). On a real v2.0.0 database the v2 baseline failed with
``sqlite3.OperationalError: no such column: lead_id`` at startup, leaving a
half-applied schema behind (executescript autocommits statement by statement).

These tests rebuild a faithful v2.0.0 database — the actual ``schema_v1.sql``
plus the exact SQL of v2.0.0 migrations 5-7 and the raw_records FTS mirror —
and verify the reconciliation pre-pass + migration 8 fold.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from infrastructure.storage.database import SCHEMA_FILE, DatabaseManager
from infrastructure.storage.lead_repo import LeadRepository

SCHEMA_V1_FILE = Path(__file__).resolve().parent.parent / "infrastructure" / "storage" / "schema_v1.sql"

# Exact table shapes created by v2.0.0's Python migrations (see
# 60cc875:infrastructure/storage/database.py, migrations 4/5/6/7).
_V200_MIGRATIONS = """
CREATE VIRTUAL TABLE IF NOT EXISTS raw_records_fts USING fts5(
    name, industry, wilaya, address, email,
    content='raw_records', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS trg_raw_records_fts_ai AFTER INSERT ON raw_records BEGIN
    INSERT INTO raw_records_fts (rowid, name, industry, wilaya, address, email)
    VALUES (new.id, new.name, new.industry, new.wilaya, new.address, new.email);
END;
CREATE TRIGGER IF NOT EXISTS trg_raw_records_fts_ad AFTER DELETE ON raw_records BEGIN
    INSERT INTO raw_records_fts (raw_records_fts, rowid, name, industry, wilaya, address, email)
    VALUES ('delete', old.id, old.name, old.industry, old.wilaya, old.address, old.email);
END;

CREATE TABLE IF NOT EXISTS discovery_campaigns (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    query          TEXT NOT NULL,
    wilaya         TEXT,
    limit_num      INTEGER NOT NULL,
    status         TEXT NOT NULL,
    discovered_qty INTEGER DEFAULT 0,
    saved_qty      INTEGER DEFAULT 0,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

ALTER TABLE lead_scores ADD COLUMN is_contact INTEGER DEFAULT 0;

CREATE TABLE IF NOT EXISTS lead_attachments (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_record_id  INTEGER NOT NULL REFERENCES raw_records (id) ON DELETE CASCADE,
    filename       TEXT NOT NULL,
    mime_type      TEXT NOT NULL,
    file_path      TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lead_attachments_record ON lead_attachments (raw_record_id);

INSERT INTO schema_migrations (version, description, applied_at) VALUES
    (2, 'raw_records source_url index', '2024-01-02'),
    (3, 'age indexes', '2024-01-03'),
    (4, 'raw_records FTS mirror', '2024-01-04'),
    (5, 'discovery_campaigns table', '2024-01-05'),
    (6, 'is_contact column', '2024-01-06'),
    (7, 'lead_attachments table', '2024-01-07');
"""


def _build_v200_db(path: Path) -> None:
    """Recreate a faithful v2.0.0 database: its shipped schema_v1.sql baseline
    plus the exact SQL of its Python migrations 5-7, with representative data."""
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA_V1_FILE.read_text(encoding="utf-8"))
    conn.executescript(_V200_MIGRATIONS)
    conn.execute(
        "INSERT INTO raw_records (fingerprint, name, industry, wilaya, website, phone, source,"
        " discovered_at, calculated_age_class, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("fp1|alger||", "Pharmacie Centrale", "pharmacie", "Alger",
         "https://pharmacie.dz", "+213550123456", "duckduckgo",
         "2024-05-01T10:00:00+00:00", "day", "2024-05-01T10:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO raw_records (fingerprint, name, industry, wilaya, source,"
        " discovered_at, created_at) VALUES (?,?,?,?,?,?,?)",
        ("fp2|oran||", "Menuiserie El Nour", "menuiserie aluminium", "Oran",
         "overpass", "2024-05-02T11:00:00+00:00", "2024-05-02T11:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO analyses (raw_record_id, pain_points, digital_presence_score,"
        " analysis_model, analyzed_at) VALUES (1, '[\"no website\"]', 35, 'heuristic',"
        " '2024-05-01T12:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO lead_scores (raw_record_id, priority_score, score_breakdown, status,"
        " tags, is_contact, computed_at) VALUES (?,?,?,?,?,?,?)",
        (1, 72.5, '{"phone": 15}', "contacted", '["vip"]', 1, "2024-05-01T12:30:00+00:00"),
    )
    conn.execute(
        "INSERT INTO resolved_entities (name, industry, wilaya, confidence, strategy,"
        " raw_record_ids, last_resolved_at) VALUES ('Pharmacie Centrale', 'pharmacie',"
        " 'Alger', 0.95, 'graph_merge', '[1]', '2024-05-03T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO entity_links (entity_id, raw_record_id, match_score, match_reasons,"
        " linked_at) VALUES (1, 1, 0.95, '[]', '2024-05-03T00:00:00+00:00')"
    )
    # One attachment that maps to raw_records.id = 1, one orphan (id = 999)
    # that must be dropped rather than folded.
    conn.executemany(
        "INSERT INTO lead_attachments (raw_record_id, filename, mime_type, file_path,"
        " created_at) VALUES (?,?,?,?,?)",
        [
            (1, "logo.png", "image/png", "/data/attachments/logo.png", "2024-05-04T00:00:00+00:00"),
            (999, "orphan.jpg", "image/jpeg", "/data/attachments/orphan.jpg", "2024-05-04T00:00:00+00:00"),
        ],
    )
    conn.execute(
        "INSERT INTO discovery_campaigns (query, wilaya, limit_num, status, discovered_qty,"
        " saved_qty, created_at, updated_at) VALUES ('pharmacie alger', 'Alger', 30,"
        " 'completed', 12, 9, '2024-05-01T09:00:00+00:00', '2024-05-01T09:05:00+00:00')"
    )
    conn.commit()
    conn.close()


def _assert_upgraded(db: DatabaseManager) -> dict:
    """Full post-upgrade invariant check. Returns the migrated lead row."""
    with db.connection() as conn:
        tables = {
            r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        # v1 artifacts and legacy shells are gone
        for gone in ("raw_records", "analyses", "lead_scores", "resolved_entities",
                     "raw_records_fts", "legacy_lead_attachments",
                     "legacy_discovery_campaigns"):
            assert gone not in tables, gone
        for present in ("leads", "entity_clusters", "entity_links",
                        "lead_attachments", "discovery_campaigns"):
            assert present in tables, present

        rows = conn.execute("SELECT * FROM leads ORDER BY id").fetchall()
        assert len(rows) == 2
        migrated = rows[0]
        assert migrated["name"] == "Pharmacie Centrale"
        assert migrated["digital_score"] == 35
        assert migrated["priority_score"] == 72.5
        assert migrated["status"] == "contacted"
        assert migrated["is_contact"] == 1
        assert json.loads(migrated["tags"]) == ["vip"]
        assert json.loads(migrated["freshness"])["calculated_age_class"] == "day"
        assert migrated["cluster_id"] is not None

        # Attachment folded onto the migrated lead; orphan dropped.
        atts = conn.execute("SELECT * FROM lead_attachments").fetchall()
        assert len(atts) == 1
        assert atts[0]["lead_id"] == migrated["id"]
        assert atts[0]["filename"] == "logo.png"
        assert atts[0]["mime_type"] == "image/png"
        assert atts[0]["file_size_bytes"] == 0

        # Campaign folded with renamed columns.
        camps = conn.execute("SELECT * FROM discovery_campaigns").fetchall()
        assert len(camps) == 1
        assert camps[0]["target_limit"] == 30
        assert camps[0]["discovered_count"] == 12
        assert camps[0]["saved_count"] == 9
        assert camps[0]["duplicate_count"] == 0
        assert camps[0]["status"] == "completed"

        versions = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
        assert 8 in versions and 7 in versions  # lineage preserved

    # FTS mirror populated by the migration-time triggers, end to end.
    hits = asyncio.run(LeadRepository(db).search("pharmacie"))
    assert len(hits) == 1 and hits[0].name == "Pharmacie Centrale"
    return {"lead_id": migrated["id"], "cluster_id": migrated["cluster_id"]}


def test_v200_startup_crash_reproduced(tmp_path):
    """The v3.0.0 bug: the v2 baseline alone cannot run on a v2.0.0 DB."""
    db_file = tmp_path / "legacy.db"
    _build_v200_db(db_file)
    conn = sqlite3.connect(db_file)
    with pytest.raises(sqlite3.OperationalError, match="no such column: lead_id"):
        conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    conn.close()


def test_upgrade_from_real_v200_db(tmp_path):
    """DatabaseManager upgrades a pristine v2.0.0 database end to end."""
    db_file = tmp_path / "legacy.db"
    _build_v200_db(db_file)
    db = DatabaseManager(db_file)
    _assert_upgraded(db)


def test_upgrade_from_partial_v200_db(tmp_path):
    """The reporter's exact state: a failed v3.0.0 startup already applied
    part of the v2 baseline (executescript autocommits statement by
    statement). The fixed initialise() must complete the upgrade anyway."""
    db_file = tmp_path / "legacy.db"
    _build_v200_db(db_file)

    # Simulate the two crashed `python main.py` runs: partial application,
    # leaving fresh leads/entity_clusters next to legacy-shaped tables.
    conn = sqlite3.connect(db_file)
    with pytest.raises(sqlite3.OperationalError):
        conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    with pytest.raises(sqlite3.OperationalError):
        conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    conn.close()

    db = DatabaseManager(db_file)
    _assert_upgraded(db)


def test_upgrade_idempotent(tmp_path):
    """Re-initialising an upgraded database neither fails nor duplicates."""
    db_file = tmp_path / "legacy.db"
    _build_v200_db(db_file)
    db = DatabaseManager(db_file)
    before = _assert_upgraded(db)

    DatabaseManager(db_file)  # re-init
    after = _assert_upgraded(db)
    assert after["lead_id"] == before["lead_id"]
    assert after["cluster_id"] == before["cluster_id"]
