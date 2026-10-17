# 13 · Troubleshooting & Diagnostics

## `RuntimeDependencyError` on import or `cli.py serve`

The environment holds a provably incompatible framework trio — almost
always because `requirements-ui.txt` was installed *after* the engine
set into the same venv, letting pip upgrade Starlette past the installed
fastapi's supported range (issue #3). The error message lists the exact
versions and requirements. Fix:

```bash
pip install -r requirements.txt -r requirements-ui.txt -r requirements-dev.txt
python -m pip check
```

or recreate the venv, or use separate venvs / `docker compose up`.
Regression checks: `tests/test_dependency_hygiene.py`.

## The workspace shows "engine is unreachable"

1. Is the engine running? `curl http://localhost:8080/health`
2. Wrong URL? The UI reads `ENGINE_URL` (default
   `http://localhost:8080`; in compose `http://engine:8080`).
3. Engine crashed? `docker compose logs engine` or the console running
   `python cli.py serve`.
4. Port clash? Change `API_PORT` and `ENGINE_URL` consistently.

## "No leads match the current filters"

A fresh database is empty — launch a discovery campaign (Discovery →
Launch campaign) or add a lead manually (＋ Add a lead manually).

## Discovery returns 0 results

- The DDG HTML endpoint may be rate-limiting: check engine logs for
  `Non-200` / block signatures. Options: wait, lower
  `MAX_SEARCH_PAGES`, reduce `RATE_LIMIT_DELAY_SECONDS`, or stand up the
  SearXNG profile (`SEARXNG_URL` + `docker compose --profile searxng up`).
- Overpass being down does **not** abort a campaign (asymmetric oracle);
  you still get web results, just without map enrichment.
- Some queries have no OSM tag mapping (see
  `infrastructure/scrapers/overpass.py`) — that only skips the OSM source.

## "database is locked" errors

The engine sets `busy_timeout = 5000` and serialises writers with
`BEGIN IMMEDIATE`. If you still see locks, something outside the engine
is writing the same file (e.g. a second engine instance or a manual
`sqlite3` session holding a write transaction) — find and stop it.

## Checkpoint rejected with 422

The engine validated your coordinates against the real wilaya geometry
and they disagree with the named wilaya. Either omit `wilaya` (the engine
derives it), or correct the name/coordinates. Coastal clicks just outside
simplified boundaries automatically get the nearest wilaya.

## Map shows grey background

Tiles are unreachable (offline / blocked) but the wilaya polygons and
markers still render — the geographic functionality does not depend on
the tile service. If nothing renders at all, check the browser console:
`streamlit-folium` must be installed (`requirements-ui.txt`).

## UI feels slow

- Check Engine diagnostics panel → probe latency (should be single-digit
  ms; hundreds of ms means the engine is starved — check CPU limits).
- Very large tables: use the filters (server-side, SQL) rather than
  scrolling; pagination is 25 rows by design.

## Migrations failed at startup

`schema_migrations` records applied versions; failures are loud. A
half-applied baseline (pre-v3 crash) is reconciled automatically by the
legacy-table pre-pass. If a manual experiment corrupted the DB, restore
from backup (`sqlite3 leads.db ".backup ..."`).

## Where to look

| Concern | Place |
|---|---|
| Engine health, version, DB status | `GET /health`, Diagnostics panel |
| Crawler activity | `GET /api/v2/crawler/status` |
| Campaign outcomes | `GET /api/v2/discover/campaigns` |
| Resolution backlog | `GET /api/v2/entities/stats` |
| Structured logs | `LOG_DIR` (`data/logs`), `LOG_FORMAT=json` for ingestion |
