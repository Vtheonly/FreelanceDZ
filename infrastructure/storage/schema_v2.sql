-- ============================================================
--  FreelanceDZ v3 — Schema v2 (unified leads)
--
--  One canonical `leads` table replaces the v1 quartet
--  (raw_records + analyses + lead_scores + resolved_entities).
--  Entity resolution is non-destructive metadata: `cluster_id`
--  on leads plus entity_clusters / entity_links.
--  Every CREATE uses IF NOT EXISTS so the file is idempotent.
-- ============================================================

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at  TEXT NOT NULL
);

-- ============================================================
--  entity_clusters : golden-record metadata for resolved groups
-- ============================================================
CREATE TABLE IF NOT EXISTS entity_clusters (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_lead_id INTEGER,             -- best member (set after resolution)
    name              TEXT NOT NULL,
    industry          TEXT,
    wilaya            TEXT,
    confidence        REAL NOT NULL DEFAULT 1.0,
    member_count      INTEGER NOT NULL DEFAULT 1,
    strategy          TEXT NOT NULL DEFAULT 'single',  -- single|graph_merge|manual_merge
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entity_clusters_wilaya ON entity_clusters (wilaya);

-- ============================================================
--  leads : the single source of truth
-- ============================================================
CREATE TABLE IF NOT EXISTS leads (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint          TEXT NOT NULL UNIQUE,
    name                 TEXT NOT NULL,
    industry             TEXT NOT NULL DEFAULT '',
    wilaya               TEXT NOT NULL DEFAULT '',
    address              TEXT,
    website              TEXT,
    phone                TEXT,
    email                TEXT,
    social_links         TEXT NOT NULL DEFAULT '[]',   -- JSON array
    rating               REAL NOT NULL DEFAULT 0.0,
    review_count         INTEGER NOT NULL DEFAULT 0,
    latitude             REAL,
    longitude            REAL,
    source               TEXT NOT NULL DEFAULT 'duckduckgo',
    source_url           TEXT,
    phone_details        TEXT NOT NULL DEFAULT '[]',   -- JSON array of PhoneDetails
    freshness            TEXT NOT NULL DEFAULT '{}',   -- FreshnessMetadata JSON
    digital_score        INTEGER,                      -- deterministic audit 0-100
    digital_tier         TEXT,
    gaps                 TEXT NOT NULL DEFAULT '[]',   -- JSON array
    recommended_services TEXT NOT NULL DEFAULT '[]',   -- JSON array of objects
    cta_fr               TEXT NOT NULL DEFAULT '',
    cta_ar               TEXT NOT NULL DEFAULT '',
    analysis_model       TEXT,
    priority_score       REAL NOT NULL DEFAULT 0.0,
    score_breakdown      TEXT NOT NULL DEFAULT '{}',   -- JSON object
    cluster_id           INTEGER REFERENCES entity_clusters (id) ON DELETE SET NULL,
    status               TEXT NOT NULL DEFAULT 'discovered',
    tags                 TEXT NOT NULL DEFAULT '[]',   -- JSON array
    is_contact           INTEGER NOT NULL DEFAULT 0,
    notes                TEXT,
    discovered_at        TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_leads_wilaya    ON leads (wilaya);
CREATE INDEX IF NOT EXISTS idx_leads_industry  ON leads (industry);
CREATE INDEX IF NOT EXISTS idx_leads_status    ON leads (status);
CREATE INDEX IF NOT EXISTS idx_leads_priority  ON leads (priority_score DESC);
CREATE INDEX IF NOT EXISTS idx_leads_cluster   ON leads (cluster_id);
CREATE INDEX IF NOT EXISTS idx_leads_contact   ON leads (is_contact);
CREATE INDEX IF NOT EXISTS idx_leads_source    ON leads (source);

-- ============================================================
--  entity_links : cluster <-> lead lineage
--  (indexes are ensured by migration 8, not here: v1 databases carry
--   an incompatible same-named table that must be dropped first)
-- ============================================================
CREATE TABLE IF NOT EXISTS entity_links (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_id     INTEGER NOT NULL REFERENCES entity_clusters (id) ON DELETE CASCADE,
    lead_id        INTEGER NOT NULL REFERENCES leads (id) ON DELETE CASCADE,
    match_score    REAL NOT NULL DEFAULT 1.0,
    match_reasons  TEXT NOT NULL DEFAULT '[]',   -- JSON array of strings
    linked_at      TEXT NOT NULL,
    UNIQUE (cluster_id, lead_id)
);

-- ============================================================
--  crawl_queue : persistent priority frontier for the crawler
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

-- ============================================================
--  discovery_campaigns : sourcing run bookkeeping
-- ============================================================
CREATE TABLE IF NOT EXISTS discovery_campaigns (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    query            TEXT NOT NULL,
    wilaya           TEXT,
    target_limit     INTEGER NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',  -- pending|processing|completed|failed
    discovered_count INTEGER NOT NULL DEFAULT 0,
    saved_count      INTEGER NOT NULL DEFAULT 0,
    duplicate_count  INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

-- ============================================================
--  lead_attachments : files attached to a lead
-- ============================================================
CREATE TABLE IF NOT EXISTS lead_attachments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id         INTEGER NOT NULL REFERENCES leads (id) ON DELETE CASCADE,
    filename        TEXT NOT NULL,
    mime_type       TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lead_attachments_lead ON lead_attachments (lead_id);

-- ============================================================
--  leads_fts : full-text mirror (unicode61, diacritics folded)
-- ============================================================
CREATE VIRTUAL TABLE IF NOT EXISTS leads_fts USING fts5(
    name, industry, wilaya, address, email, notes,
    content='leads',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS trg_leads_fts_ai AFTER INSERT ON leads BEGIN
    INSERT INTO leads_fts (rowid, name, industry, wilaya, address, email, notes)
    VALUES (new.id, new.name, new.industry, new.wilaya, new.address, new.email, new.notes);
END;

CREATE TRIGGER IF NOT EXISTS trg_leads_fts_ad AFTER DELETE ON leads BEGIN
    INSERT INTO leads_fts (leads_fts, rowid, name, industry, wilaya, address, email, notes)
    VALUES ('delete', old.id, old.name, old.industry, old.wilaya, old.address, old.email, old.notes);
END;

CREATE TRIGGER IF NOT EXISTS trg_leads_fts_au AFTER UPDATE ON leads BEGIN
    INSERT INTO leads_fts (leads_fts, rowid, name, industry, wilaya, address, email, notes)
    VALUES ('delete', old.id, old.name, old.industry, old.wilaya, old.address, old.email, old.notes);
    INSERT INTO leads_fts (rowid, name, industry, wilaya, address, email, notes)
    VALUES (new.id, new.name, new.industry, new.wilaya, new.address, new.email, new.notes);
END;
