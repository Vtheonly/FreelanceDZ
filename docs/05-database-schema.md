# 05 · Database Schema & Migrations

Single SQLite database (WAL mode), managed by
`infrastructure/storage/database.py` with a decorator-registered,
ordered, recorded migration system (`schema_migrations` table). Baseline:
`infrastructure/storage/schema_v2.sql`.

## Migration ledger

| Version | Description |
|---|---|
| 8 | unify v1 tables (`raw_records` + `analyses` + `lead_scores` + `resolved_entities`) into the unified `leads` schema; folds legacy-shaped tables |
| 9 | entity resolution v3.1: `resolution_decisions`, `review_queue`, `entity_relations` + canonical columns on `entity_clusters` |
| 10 | **checkpoints**: geographic POI table + wilaya/category/status indices (refactorv5 Step 4) |

Migrations are idempotent (`CREATE TABLE IF NOT EXISTS` / column-existence
guards) and applied inside one transaction at startup; a second
`DatabaseManager()` initialisation on the same file is a no-op.

## Core tables

- **`leads`** — the single source of truth per business record:
  identity (`fingerprint` UNIQUE, name, industry, wilaya, address,
  website, phone, email, social_links, rating, GPS), discovery
  (source, source_url, phone_details JSON, freshness JSON), audit
  (digital_score, digital_tier, gaps, recommended_services, cta_fr/ar,
  analysis_model), scoring (priority_score, score_breakdown JSON), CRM
  (status, tags JSON, is_contact, notes, cluster_id), timestamps.
  Plus `leads_fts` (FTS5) for full-text search.
- **`checkpoints`** — name, category, wilaya, latitude, longitude, notes,
  status, timestamps (indices on wilaya/category/status).
- **`entity_clusters` / `entity_links`** — canonical entities and their
  member leads (non-destructive: source rows are never rewritten).
- **`resolution_decisions`** — every SAME/RELATED/DISTINCT/UNRESOLVED
  verdict with signals and explanations (explainability).
- **`review_queue`** — ambiguous pairs awaiting a human call.
- **`entity_relations`** — RELATED entities (branches, franchises).
- **`discovery_campaigns`** — per-campaign query/wilaya/limit/status and
  discovered/saved/duplicate counts.
- **`crawl_queue`** — persistent crawler frontier with atomic claims.
- **`lead_attachments`** — attachment metadata (files on disk under
  `ATTACHMENTS_DIR`, stored under safe unique names).

## Concurrency model

- WAL mode is declared **once** at initialisation (v4 Task 15 —
  re-declaring it per connection took an exclusive lock on every
  operation).
- Per-operation short-lived connections; `busy_timeout = 5000`;
  writes go through `immediate_connection()` (`BEGIN IMMEDIATE`) which
  serialises claimants up front.
- Upserts are single native `INSERT ... ON CONFLICT(fingerprint) DO
  UPDATE ... RETURNING id` statements (v4 Task 6): race-free even across
  processes, with the merge policy (richer value wins, scores take the
  max, CRM state never clobbered) encoded in the `DO UPDATE` clause.
- Blocking SQLite work is offloaded via `asyncio.to_thread`; the FastAPI
  event loop is never blocked by storage.

## Backups

The database is one file plus `-wal`/`-shm` siblings. Use
`sqlite3 leads.db ".backup '/backup/leads.db'"` (or stop the engine and
copy all three). In Docker, `/app/data` is the `fdz_data` named volume.
