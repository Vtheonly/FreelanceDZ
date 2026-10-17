# 01 · Project Overview

FreelanceDZ is a deterministic B2B sales-intelligence engine for the
Algerian market. It discovers businesses across the 58 wilayas, audits
their digital presence, scores them as sales opportunities for web-design
and local-SEO services, resolves the same real-world business behind
multiple listings into one entity, and manages geographic checkpoints for
field operations — all behind a documented HTTP API with a modern
Streamlit workspace on top.

## Feature inventory

| Capability | Where | Notes |
|---|---|---|
| Discovery campaigns | `services/discovery_service.py` | DDG HTML scraping + OpenStreetMap Overpass + optional SearXNG; streaming pipeline with sub-second time-to-first-result |
| Deterministic audit | `engine/analyzer.py` | Digital-presence scoring, gap analysis, recommended services with DZD budgets, FR/AR outreach openers — no LLM, fully deterministic |
| Priority scoring | `engine/scorer.py`, `engine/fastops.py` | Explainable 0–100 score; absence of web presence is scored as *opportunity*, not penalty |
| Entity resolution | `engine/resolution/` | Evidence-based clustering with decision log, human review queue, reversible merges/splits |
| Geographic intelligence | `engine/geo.py`, `engine/geodata/` | Real 58-wilaya boundaries (ODbL/OSM), point-in-polygon lookup, centroids, live catalogue joins |
| Checkpoints (POIs) | `infrastructure/storage/checkpoint_repo.py`, `/api/v2/checkpoints` | Full CRUD with geometry-validated wilaya assignment |
| CRM | `/api/v2/leads/*` | Status, contacts, tags, notes, attachments, bulk operations, manual creation |
| Crawler | `services/crawler_service.py` | Autonomous concurrent crawler with persistent frontier, per-domain backoff, bounded (32 KiB) reads |
| Streamlit workspace | `ui/` | Dynamic-grid dashboard, interactive Algeria map, checkpoints manager, discovery, lead inspection, diagnostics |
| Exports | `/api/v2/export/*` | CSV/JSON |

## The three runtimes

1. **Engine** (`python cli.py serve`) — FastAPI service on :8080. Owns the
   SQLite database and ALL business logic. Fully usable and testable
   without any UI.
2. **Workspace** (`python cli.py ui`) — Streamlit service on :8501. A pure
   HTTP client of the engine: no database access, no engine imports.
3. **CLI** (`python cli.py --help`) — discover / analyze / resolve / stats
   / export / bench against the same engine modules.

Docker Compose runs both services in dedicated containers
(`docker-compose.yml`).

## Where to go next

- Architecture and service boundaries → [02-architecture.md](02-architecture.md)
- API contracts → [04-api-reference.md](04-api-reference.md)
- Local setup in five commands → [08-local-development.md](08-local-development.md)
- Why decisions were made → [adr/](adr/)
- What changed in this refactor and why → [14-refactoring-history.md](14-refactoring-history.md)
