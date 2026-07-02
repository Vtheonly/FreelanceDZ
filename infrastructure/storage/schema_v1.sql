-- ============================================================
--  FreelanceDZ Refactored — Initial Schema (v1)
--  Single, authoritative schema file. No duplicate CREATE TABLE blocks.
--  Every CREATE uses IF NOT EXISTS so the file is idempotent.
-- ============================================================

-- ============================================================
--  schema_migrations : tracks applied migrations
-- ============================================================
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at  TEXT NOT NULL
);

-- ============================================================
--  raw_records : one row per scrape (immutable)
--
--  This table is the *source of truth*. Records are never updated
--  in-place except for the freshness columns (which are derived from
--  re-scrapes and are safe to overwrite).
-- ============================================================
CREATE TABLE IF NOT EXISTS raw_records (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint           TEXT NOT NULL UNIQUE,
    name                  TEXT NOT NULL,
    industry              TEXT NOT NULL,
    wilaya                TEXT NOT NULL,
    address               TEXT,
    website               TEXT,
    phone                 TEXT,
    email                 TEXT,
    social_media_handles  TEXT,             -- JSON array
    rating                REAL NOT NULL DEFAULT 0.0,
    review_count          INTEGER NOT NULL DEFAULT 0,
    latitude              REAL,
    longitude             REAL,
    source                TEXT NOT NULL,    -- overpass|duckduckgo|searxng|social|manual|mock|infinite
    source_url            TEXT,
    phone_metadata        TEXT,             -- JSON array of PhoneDetails
    raw_html_hash         TEXT,             -- SHA-256 of scraped HTML (skip reprocessing)
    discovered_at         TEXT NOT NULL,    -- ISO8601 UTC
    last_updated          TEXT,             -- ISO8601 UTC (source-claimed)
    relative_age_hint     TEXT,             -- raw hint, e.g. "Updated 2 days ago"
    calculated_age_class  TEXT NOT NULL DEFAULT 'older',  -- hour|day|week|month|older
    created_at            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_records_wilaya    ON raw_records (wilaya);
CREATE INDEX IF NOT EXISTS idx_raw_records_industry  ON raw_records (industry);
CREATE INDEX IF NOT EXISTS idx_raw_records_source    ON raw_records (source);
CREATE INDEX IF NOT EXISTS idx_raw_records_website   ON raw_records (website);

-- ============================================================
--  resolved_entities : golden records produced by the entity resolver
--
--  One row per *real-world* entity. The ``raw_record_ids`` column is a
--  JSON array of ``raw_records.id`` values that were merged to produce
--  this entity — it preserves lineage for audit. The ``entity_links``
--  table (below) provides the same lineage as a proper relational join
--  table for SQL-grade queries.
-- ============================================================
CREATE TABLE IF NOT EXISTS resolved_entities (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type           TEXT NOT NULL DEFAULT 'business',
    name                  TEXT NOT NULL,
    industry              TEXT,
    wilaya                TEXT,
    address               TEXT,
    website               TEXT,
    phone                 TEXT,
    email                 TEXT,
    social_media_handles  TEXT,             -- JSON array
    phones                TEXT,             -- JSON array of E.164 strings
    rating                REAL NOT NULL DEFAULT 0.0,
    review_count          INTEGER NOT NULL DEFAULT 0,
    latitude              REAL,
    longitude             REAL,
    confidence            REAL NOT NULL DEFAULT 1.0,
    strategy              TEXT NOT NULL DEFAULT 'single',  -- single|graph_merge|manual_merge
    raw_record_ids        TEXT NOT NULL DEFAULT '[]',      -- JSON array of ints (denormalised for fast reads)
    last_resolved_at      TEXT NOT NULL
);

-- ============================================================
--  entity_links : proper join table for golden-record ↔ raw-record lineage
--
--  Each row links one resolved entity to one raw record that contributed
--  to it. This is the relational counterpart of the denormalised
--  ``raw_record_ids`` JSON array on ``resolved_entities`` — it lets us
--  run efficient SQL queries like "show me every raw record that
--  contributed to entity #42" without parsing JSON in Python.
-- ============================================================
CREATE TABLE IF NOT EXISTS entity_links (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id       INTEGER NOT NULL REFERENCES resolved_entities (id) ON DELETE CASCADE,
    raw_record_id   INTEGER NOT NULL REFERENCES raw_records (id) ON DELETE CASCADE,
    match_score     REAL NOT NULL DEFAULT 1.0,  -- similarity score that triggered the merge
    match_reasons   TEXT,                        -- JSON array of human-readable match reasons
    linked_at       TEXT NOT NULL,
    UNIQUE (entity_id, raw_record_id)
);

CREATE INDEX IF NOT EXISTS idx_entity_links_entity     ON entity_links (entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_links_raw_record ON entity_links (raw_record_id);

-- ============================================================
--  analyses : LLM analysis attached to a raw record (1-to-1)
-- ============================================================
CREATE TABLE IF NOT EXISTS analyses (
    raw_record_id                 INTEGER PRIMARY KEY REFERENCES raw_records (id) ON DELETE CASCADE,
    pain_points                   TEXT,             -- JSON array
    recommended_solutions         TEXT,             -- JSON array of objects
    digital_presence_score        INTEGER NOT NULL DEFAULT 50,
    pitch_angles                  TEXT,             -- JSON array
    estimated_monthly_revenue_usd REAL,
    analysis_model                TEXT,
    from_cache                    INTEGER NOT NULL DEFAULT 0,
    analyzed_at                   TEXT NOT NULL
);

-- ============================================================
--  lead_scores : cached priority scores (1-to-1 with raw_records)
-- ============================================================
CREATE TABLE IF NOT EXISTS lead_scores (
    raw_record_id    INTEGER PRIMARY KEY REFERENCES raw_records (id) ON DELETE CASCADE,
    priority_score   REAL NOT NULL DEFAULT 0.0,
    score_breakdown  TEXT,             -- JSON object {factor: points}
    status           TEXT NOT NULL DEFAULT 'discovered',
    tags             TEXT NOT NULL DEFAULT '[]',  -- JSON array of strings
    computed_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lead_scores_score   ON lead_scores (priority_score DESC);
CREATE INDEX IF NOT EXISTS idx_lead_scores_status  ON lead_scores (status);

-- ============================================================
--  crawl_queue : persistent priority queue for the infinite crawler
-- ============================================================
CREATE TABLE IF NOT EXISTS crawl_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT UNIQUE NOT NULL,
    domain          TEXT NOT NULL,
    priority        INTEGER NOT NULL DEFAULT 1,
    depth           INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending|processing|completed|failed
    last_attempted  TEXT,
    fail_count      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_crawl_queue_domain_status ON crawl_queue (domain, status);
CREATE INDEX IF NOT EXISTS idx_crawl_queue_priority       ON crawl_queue (priority DESC, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_crawl_queue_status         ON crawl_queue (status);

-- ============================================================
--  domain_politeness : per-domain last-visited timestamps
-- ============================================================
CREATE TABLE IF NOT EXISTS domain_politeness (
    domain          TEXT PRIMARY KEY,
    last_visited_at TEXT NOT NULL
);
