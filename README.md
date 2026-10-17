# FreelanceDZ

Deterministic B2B sales-intelligence engine for the Algerian market —
discovery, digital-presence auditing, opportunity scoring, entity
resolution, and geographic intelligence over the 58 wilayas — with a
modern Streamlit workspace as its UI.

```
┌────────────────────┐    HTTP /api/v2/*    ┌────────────────────┐
│  Streamlit UI      │ ───────────────────► │  Engine (FastAPI)  │
│  :8501  pure client│                      │  :8080  + SQLite   │
└────────────────────┘                      └────────────────────┘
```

## Quick start (local)

```bash
python -m venv .venv && source .venv/bin/activate
python scripts/setup_env.py   # resilient install + verification (timeout retries,
                              # conflict detection, import checks — see docs/08)

python cli.py serve      # engine  → http://localhost:8080 (docs at /docs)
python cli.py ui         # workspace → http://localhost:8501
```

(Plain pip works too: `pip install -r requirements.txt -r requirements-ui.txt
-r requirements-dev.txt` in one command — retry the same command on a
download timeout; nothing needs deleting.)

## Quick start (Docker)

```bash
docker compose up           # engine + streamlit ui (health-gated)
```

## What it does

- **Discovery** — DDG + OpenStreetMap + optional SearXNG campaigns;
  streaming pipeline, sub-second first result; area-code geo-inference
  recovers wilayas for online-only businesses.
- **Audit & scoring** — deterministic (no LLM): digital-presence score,
  gaps, recommended services with DZD budgets, FR/AR outreach openers,
  and an explainable 0–100 priority where *absence* of a website is a
  sales opportunity, not a penalty.
- **Entity resolution** — evidence-based clustering with a decision log,
  human review queue, and reversible merges/splits.
- **Geographic intelligence** — real 58-wilaya boundaries (ODbL/OSM),
  point-in-polygon lookup, and checkpoint (POI) management with
  geometry-validated wilaya assignment.
- **Workspace** — dynamic-grid Streamlit dashboard: interactive Algeria
  map (click a wilaya to filter everything), leads matrix with composed
  filters and bulk ops, lead inspector with attachments, campaign
  launcher, crawler control, live diagnostics.

## Documentation

Everything lives in [`docs/`](docs/):

[Overview](docs/01-overview.md) ·
[Architecture](docs/02-architecture.md) ·
[Engine design](docs/03-engine-design.md) ·
[API reference](docs/04-api-reference.md) ·
[Database](docs/05-database-schema.md) ·
[Geographic data](docs/06-geographic-data.md) ·
[Streamlit UI](docs/07-streamlit-ui.md) ·
[Local dev](docs/08-local-development.md) ·
[Docker](docs/09-docker-deployment.md) ·
[Configuration](docs/10-configuration.md) ·
[Testing](docs/11-testing-quality.md) ·
[Performance](docs/12-performance.md) ·
[Troubleshooting](docs/13-troubleshooting.md) ·
[Refactoring history](docs/14-refactoring-history.md) ·
[Known limitations](docs/15-known-limitations.md) ·
[ADRs](docs/adr/)

## Verification

```bash
python -m pytest tests/ -q      # 260+ tests: unit, integration, API, geo, UI, performance, hygiene
ruff check .                    # lint gate (enforced green)
python cli.py bench             # engine benchmarks
python -m pip check             # dependency consistency (issue #3 guard)
```

Boundary geometry © OpenStreetMap contributors (ODbL) — see
[`engine/geodata/ATTRIBUTION.md`](engine/geodata/ATTRIBUTION.md).
