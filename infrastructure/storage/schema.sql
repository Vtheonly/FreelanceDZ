-- DZ Sales Intelligence — SQLite schema
-- Idempotent: every CREATE uses IF NOT EXISTS.
-- ============================================================
-- businesses : one row per discovered business (raw data)
-- ============================================================
CREATE TABLE
    IF NOT EXISTS businesses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fingerprint TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        industry TEXT NOT NULL,
        wilaya TEXT NOT NULL,
        address TEXT,
        website TEXT,
        phone TEXT,
        email TEXT,
        social_media_handles TEXT, -- JSON array
        rating REAL NOT NULL DEFAULT 0.0,
        review_count INTEGER NOT NULL DEFAULT 0,
        latitude REAL,
        longitude REAL,
        source TEXT NOT NULL, -- overpass | duckduckgo | mock | manual
        source_url TEXT,
        discovered_at TEXT NOT NULL, -- ISO8601 UTC
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

CREATE INDEX IF NOT EXISTS idx_businesses_wilaya ON businesses (wilaya);

CREATE INDEX IF NOT EXISTS idx_businesses_industry ON businesses (industry);

CREATE INDEX IF NOT EXISTS idx_businesses_name ON businesses (name);

CREATE INDEX IF NOT EXISTS idx_businesses_source ON businesses (source);

-- ============================================================
-- analyses : LLM analysis attached to a business (1-to-1)
-- ============================================================
CREATE TABLE
    IF NOT EXISTS analyses (
        business_id INTEGER PRIMARY KEY REFERENCES businesses (id) ON DELETE CASCADE,
        pain_points TEXT, -- JSON array
        recommended_solutions TEXT, -- JSON array of objects
        digital_presence_score INTEGER NOT NULL DEFAULT 50,
        pitch_angles TEXT, -- JSON array
        estimated_monthly_revenue_usd REAL,
        analysis_model TEXT,
        from_cache INTEGER NOT NULL DEFAULT 0,
        analyzed_at TEXT NOT NULL
    );

-- ============================================================
-- lead_scores : cached priority scores (1-to-1 with businesses)
-- ============================================================
CREATE TABLE
    IF NOT EXISTS lead_scores (
        business_id INTEGER PRIMARY KEY REFERENCES businesses (id) ON DELETE CASCADE,
        priority_score REAL NOT NULL DEFAULT 0.0,
        score_breakdown TEXT, -- JSON object {factor: points}
        status TEXT NOT NULL DEFAULT 'discovered',
        computed_at TEXT NOT NULL
    );

CREATE INDEX IF NOT EXISTS idx_lead_scores_score ON lead_scores (priority_score DESC);

CREATE INDEX IF NOT EXISTS idx_lead_scores_status ON lead_scores (status);

CREATE TABLE
    IF NOT EXISTS businesses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fingerprint TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        industry TEXT NOT NULL,
        wilaya TEXT NOT NULL,
        address TEXT,
        website TEXT,
        phone TEXT,
        email TEXT,
        social_media_handles TEXT, -- JSON array
        rating REAL NOT NULL DEFAULT 0.0,
        review_count INTEGER NOT NULL DEFAULT 0,
        latitude REAL,
        longitude REAL,
        source TEXT NOT NULL, -- overpass | duckduckgo | mock | manual
        source_url TEXT,
        tags TEXT, -- JSON array of custom strings
        discovered_at TEXT NOT NULL, -- ISO8601 UTC
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );