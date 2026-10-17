"""Schema v2 + migration tests: fresh install, v1 upgrade path, FTS safety."""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from domain.enums import DataSource
from domain.models import Lead
from infrastructure.storage.cluster_repo import ClusterRepository
from infrastructure.storage.crawl_queue_repo import CrawlQueueRepository
from infrastructure.storage.database import DatabaseManager
from infrastructure.storage.lead_repo import LeadRepository, fts_sanitize


@pytest.fixture()
def fresh_db(tmp_path):
    return DatabaseManager(tmp_path / "fresh.db")


@pytest.fixture()
def repo(fresh_db):
    return LeadRepository(fresh_db)


def _make_lead(**overrides) -> Lead:
    defaults = dict(
        name="Pharmacie Centrale",
        industry="pharmacie",
        wilaya="Alger",
        website="https://pharmacie-centrale.dz",
        phone="+213550123456",
        source=DataSource.MANUAL,
    )
    defaults.update(overrides)
    return Lead(**defaults)


# ---------------------------------------------------------------------------
# Fresh install
# ---------------------------------------------------------------------------

def test_fresh_schema_tables(fresh_db):
    with fresh_db.connection() as conn:
        tables = {
            r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "leads" in tables
    assert "entity_clusters" in tables
    assert "entity_links" in tables
    assert "crawl_queue" in tables
    assert "domain_politeness" in tables
    assert "discovery_campaigns" in tables
    assert "lead_attachments" in tables
    # v1 tables must NOT exist on a fresh install
    assert "raw_records" not in tables
    assert "analyses" not in tables
    assert "lead_scores" not in tables
    assert "resolved_entities" not in tables


def test_fresh_migration_recorded(fresh_db):
    with fresh_db.connection() as conn:
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    assert {r["version"] for r in rows} == {8}


def test_double_init_idempotent(tmp_path):
    db = DatabaseManager(tmp_path / "idem.db")
    DatabaseManager(tmp_path / "idem.db")  # second init
    with db.connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# Lead repository behaviour
# ---------------------------------------------------------------------------

def test_upsert_create_then_merge(repo):
    lead = _make_lead(email="contact@pharmacie.dz")
    result = asyncio.run(repo.upsert(lead))
    assert result[1] is True

    # Re-discovery with less info (email missing) — same fingerprint because
    # identity is name|wilaya|phone|website; the merge must keep the richer row.
    lead.email = None
    lead_id, created = asyncio.run(repo.upsert(lead))
    assert created is False and lead_id == result[0]

    stored = asyncio.run(repo.get(lead_id))
    assert stored.email == "contact@pharmacie.dz"  # COALESCE kept the richer value


def test_upsert_new_fingerprint_new_row(repo):
    asyncio.run(repo.upsert(_make_lead()))
    _, created = asyncio.run(repo.upsert(_make_lead(name="Menuiserie El Nour", wilaya="Oran")))
    assert created is True
    assert asyncio.run(repo.count()) == 2


def test_fts_search_and_injection_safety(repo):
    asyncio.run(repo.upsert(_make_lead()))
    asyncio.run(repo.upsert(_make_lead(
        name="Menuiserie El Nour", industry="menuiserie aluminium", wilaya="Oran"
    )))

    hits = asyncio.run(repo.search("pharmacie"))
    assert len(hits) == 1 and hits[0].name == "Pharmacie Centrale"

    # v2 bug: raw FTS syntax raised OperationalError -> HTTP 500.
    for evil in ['"*NEAR(x)', 'a OR b AND (c', '"unclosed', 'col:*']:
        asyncio.run(repo.search(evil))  # must not raise


def test_fts_sanitize_quotes_tokens():
    assert fts_sanitize('caf"e NEAR(a') == '"caf" "e" "NEAR" "a"'
    assert fts_sanitize("") == ""


def test_list_unanalyzed_vs_analyzed(repo):
    asyncio.run(repo.upsert(_make_lead()))
    asyncio.run(repo.upsert(_make_lead(name="Clinique Es Salem", wilaya="Blida")))

    pending = asyncio.run(repo.list_unanalyzed())
    assert len(pending) == 2  # digital_score NULL

    lead = pending[0]
    lead.digital_score = 55
    asyncio.run(repo.upsert(lead))
    assert len(asyncio.run(repo.list_unanalyzed())) == 1


def test_list_unscored_after_scoring(repo):
    from engine.scorer import LeadScorer
    scorer = LeadScorer()
    lead_a = _make_lead()
    lead_b = _make_lead(name="Boulangerie Bab Zouar", wilaya="Alger")
    for l in (lead_a, lead_b):
        scorer.score(l)
        asyncio.run(repo.upsert(l))

    assert asyncio.run(repo.list_unscored()) == []


def test_stats_age_breakdown_populated(repo):
    from domain.value_objects import FreshnessMetadata
    from domain.enums import FreshnessAge
    lead = _make_lead()
    lead.freshness = FreshnessMetadata(calculated_age_class=FreshnessAge.DAILY)
    asyncio.run(repo.upsert(lead))

    stats = asyncio.run(repo.stats())
    assert stats["age_breakdown"].get("day") == 1  # v2 always returned []


def test_status_transitions_preserved(repo):
    lead = _make_lead()
    lead_id, _ = asyncio.run(repo.upsert(lead))

    asyncio.run(repo.set_status(lead_id, __import__("domain.enums", fromlist=["LeadStatus"]).LeadStatus.CONTACTED))
    stored = asyncio.run(repo.get(lead_id))
    assert stored.status.value == "contacted"

    # A re-scrape upsert must not clobber the CRM status back to discovered.
    stored.priority_score = 42.0
    asyncio.run(repo.upsert(stored))
    again = asyncio.run(repo.get(lead_id))
    assert again.status.value == "contacted"


# ---------------------------------------------------------------------------
# Clusters
# ---------------------------------------------------------------------------

def test_cluster_persistence_and_lineage(repo, fresh_db):
    a = _make_lead()
    b = _make_lead(name="Pharmacie Central", website=None)
    id_a, _ = asyncio.run(repo.upsert(a))
    id_b, _ = asyncio.run(repo.upsert(b))

    clusters = ClusterRepository(fresh_db)
    asyncio.run(clusters.replace_all([
        {
            "canonical_lead_id": id_a,
            "name": "Pharmacie Centrale",
            "industry": "pharmacie",
            "wilaya": "Alger",
            "confidence": 0.93,
            "strategy": "graph_merge",
            "members": [id_a, id_b],
            "reasons": ["name_similarity"],
        }
    ]))

    listed = asyncio.run(clusters.list_clusters())
    assert len(listed) == 1
    assert listed[0]["member_count"] == 2

    lineage = asyncio.run(clusters.get_lineage(listed[0]["id"]))
    assert {row["id"] for row in lineage} == {id_a, id_b}

    for lead_id in (id_a, id_b):
        stored = asyncio.run(repo.get(lead_id))
        assert stored.cluster_id == listed[0]["id"]

    # Re-running resolution with identical membership reuses the cluster.
    asyncio.run(clusters.replace_all([
        {
            "canonical_lead_id": id_a, "name": "Pharmacie Centrale",
            "industry": "pharmacie", "wilaya": "Alger", "confidence": 0.93,
            "strategy": "graph_merge", "members": [id_a, id_b], "reasons": [],
        }
    ]))
    assert asyncio.run(clusters.count()) == 1


# ---------------------------------------------------------------------------
# v1 -> v2 migration
# ---------------------------------------------------------------------------

def _build_v1_db(path):
    """Recreate the exact v1 table set with representative data."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, description TEXT NOT NULL, applied_at TEXT NOT NULL);
        INSERT INTO schema_migrations VALUES (1,'baseline','2024-01-01');

        CREATE TABLE raw_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL, industry TEXT NOT NULL, wilaya TEXT NOT NULL,
            address TEXT, website TEXT, phone TEXT, email TEXT, social_media_handles TEXT,
            rating REAL NOT NULL DEFAULT 0.0, review_count INTEGER NOT NULL DEFAULT 0,
            latitude REAL, longitude REAL, source TEXT NOT NULL, source_url TEXT,
            phone_metadata TEXT, raw_html_hash TEXT, discovered_at TEXT NOT NULL,
            last_updated TEXT, relative_age_hint TEXT, calculated_age_class TEXT NOT NULL DEFAULT 'older',
            created_at TEXT NOT NULL
        );
        CREATE TABLE resolved_entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT NOT NULL DEFAULT 'business',
            name TEXT NOT NULL, industry TEXT, wilaya TEXT, address TEXT, website TEXT,
            phone TEXT, email TEXT, social_media_handles TEXT, phones TEXT,
            rating REAL NOT NULL DEFAULT 0.0, review_count INTEGER NOT NULL DEFAULT 0,
            latitude REAL, longitude REAL, confidence REAL NOT NULL DEFAULT 1.0,
            strategy TEXT NOT NULL DEFAULT 'single', raw_record_ids TEXT NOT NULL DEFAULT '[]',
            last_resolved_at TEXT NOT NULL
        );
        CREATE TABLE entity_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id INTEGER NOT NULL REFERENCES resolved_entities (id) ON DELETE CASCADE,
            raw_record_id INTEGER NOT NULL REFERENCES raw_records (id) ON DELETE CASCADE,
            match_score REAL NOT NULL DEFAULT 1.0, match_reasons TEXT, linked_at TEXT NOT NULL,
            UNIQUE (entity_id, raw_record_id)
        );
        CREATE TABLE analyses (
            raw_record_id INTEGER PRIMARY KEY REFERENCES raw_records (id) ON DELETE CASCADE,
            pain_points TEXT, recommended_solutions TEXT,
            digital_presence_score INTEGER NOT NULL DEFAULT 50,
            pitch_angles TEXT, estimated_monthly_revenue_usd REAL,
            analysis_model TEXT, from_cache INTEGER NOT NULL DEFAULT 0, analyzed_at TEXT NOT NULL
        );
        CREATE TABLE lead_scores (
            raw_record_id INTEGER PRIMARY KEY REFERENCES raw_records (id) ON DELETE CASCADE,
            priority_score REAL NOT NULL DEFAULT 0.0, score_breakdown TEXT,
            status TEXT NOT NULL DEFAULT 'discovered', tags TEXT NOT NULL DEFAULT '[]',
            is_contact INTEGER NOT NULL DEFAULT 0, computed_at TEXT NOT NULL
        );
        CREATE TABLE crawl_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE NOT NULL, domain TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 1, depth INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending', last_attempted TEXT,
            fail_count INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
        );
        CREATE TABLE domain_politeness (domain TEXT PRIMARY KEY, last_visited_at TEXT NOT NULL);
        """
    )
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
        "INSERT INTO analyses (raw_record_id, pain_points, digital_presence_score, analysis_model, analyzed_at)"
        " VALUES (1, '[\"no website\"]', 35, 'heuristic-fallback', '2024-05-01T12:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO lead_scores (raw_record_id, priority_score, score_breakdown, status, tags, is_contact, computed_at)"
        " VALUES (1, 72.5, '{\"phone\": 15}', 'contacted', '[\"vip\"]', 1, '2024-05-01T12:30:00+00:00')"
    )
    conn.execute(
        "INSERT INTO resolved_entities (name, industry, wilaya, confidence, strategy, raw_record_ids, last_resolved_at)"
        " VALUES ('Pharmacie Centrale', 'pharmacie', 'Alger', 0.95, 'graph_merge', '[1]', '2024-05-03T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO entity_links (entity_id, raw_record_id, match_score, match_reasons, linked_at)"
        " VALUES (1, 1, 0.95, '[]', '2024-05-03T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()


def test_v1_to_v2_migration(tmp_path):
    db_file = tmp_path / "legacy.db"
    _build_v1_db(db_file)

    db = DatabaseManager(db_file)  # triggers schema_v2 + migration 8

    with db.connection() as conn:
        tables = {
            r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "raw_records" not in tables
        assert "resolved_entities" not in tables
        assert "leads" in tables

        rows = conn.execute("SELECT * FROM leads ORDER BY id").fetchall()
        assert len(rows) == 2

        migrated = rows[0]
        assert migrated["name"] == "Pharmacie Centrale"
        assert migrated["digital_score"] == 35            # from analyses
        assert migrated["priority_score"] == 72.5          # from lead_scores
        assert migrated["status"] == "contacted"           # CRM state preserved
        assert migrated["is_contact"] == 1
        assert json.loads(migrated["tags"]) == ["vip"]
        freshness = json.loads(migrated["freshness"])
        assert freshness["calculated_age_class"] == "day"
        assert migrated["cluster_id"] is not None          # resolved -> cluster

        second = rows[1]
        assert second["digital_score"] is None             # never analyzed
        assert second["priority_score"] == 0.0

        cluster = conn.execute(
            "SELECT * FROM entity_clusters WHERE id = ?", (migrated["cluster_id"],)
        ).fetchone()
        assert cluster["name"] == "Pharmacie Centrale"
        assert cluster["strategy"] == "graph_merge"

        links = conn.execute(
            "SELECT lead_id FROM entity_links WHERE cluster_id = ?", (migrated["cluster_id"],)
        ).fetchall()
        assert [l["lead_id"] for l in links] == [migrated["id"]]

        versions = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
        assert 8 in versions

    # Migration is idempotent (re-init does not fail or duplicate).
    DatabaseManager(db_file)


# ---------------------------------------------------------------------------
# Crawl queue atomicity
# ---------------------------------------------------------------------------

def test_crawl_queue_claim_and_retry(fresh_db):
    q = CrawlQueueRepository(fresh_db)
    asyncio.run(q.add_url("https://a.dz/1", priority=1))
    asyncio.run(q.add_url("https://b.dz/2", priority=10))

    claimed = asyncio.run(q.get_next_url())
    assert claimed is not None and claimed[1] == "https://b.dz/2"  # priority order

    asyncio.run(q.update_status(claimed[0], success=False))
    with fresh_db.connection() as conn:
        row = conn.execute("SELECT * FROM crawl_queue WHERE id = ?", (claimed[0],)).fetchone()
    assert row["fail_count"] == 1 and row["status"] == "pending"

    asyncio.run(q.reset_stale_processing(older_than_seconds=0))
    assert asyncio.run(q.count_by_status("pending")) == 2
