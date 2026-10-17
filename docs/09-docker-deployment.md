# 09 · Docker Deployment

## The stack

```bash
docker compose up                 # engine :8080 + streamlit ui :8501
docker compose --profile searxng up   # + optional local metasearch :8888
```

| Service | Image | Role | Healthcheck |
|---|---|---|---|
| `engine` | `docker/engine.Dockerfile` | the whole engine: API, discovery, resolution, geo; owns the SQLite volume | `GET /health` |
| `ui` | `docker/ui.Dockerfile` | Streamlit workspace; slim UI-only dependency set; no engine code in the image | `GET /_stcore/health` |
| `searxng` (profile) | `searxng/searxng` | optional metasearch aggregator | built-in |

The `ui` service starts only after the engine reports healthy
(`depends_on: condition: service_healthy`). Restarts are
`unless-stopped`; both services have resource limits; the engine is
capped at 2 GB / 2 CPUs, the UI at 512 MB.

## Service isolation contract

- The engine container contains **no Streamlit** and no `ui/` code — it
  builds from `requirements.txt` and the engine packages only. It is
  independently runnable and testable.
- The UI container contains **no engine code** — it builds from
  `requirements-ui.txt` and `ui/` only. All data flows through
  `ENGINE_URL=http://engine:8080` over the documented API.
- Inter-service communication is plain HTTP with the engine's own
  timeouts; the UI's error states cover engine unavailability.

## Persistence

`fdz_data` (named volume) is mounted at the engine's `/app/data` — the
SQLite database, exports, attachments, and logs survive container
recreation. The UI stores nothing persistent.

## Configuration & secrets

All configuration is environment-driven (compose reads `.env` — never
committed; `.env.example` documents the complete surface). Notable keys:

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_PATH` | `/app/data/leads.db` | volume-backed in compose |
| `API_PORT` / `API_HOST` | 8080 / 0.0.0.0 | engine bind |
| `SEARXNG_URL` | *(empty)* | set to `http://searxng:8080` **and** run with `--profile searxng` |
| `PROXY_LIST` | *(empty)* | comma-separated proxy URLs for the crawler |
| `LOG_LEVEL` | INFO | DEBUG for verbose scraping logs |
| `ENGINE_URL` | `http://localhost:8080` | UI-side; compose sets `http://engine:8080` |

No credentials are hardcoded anywhere; the engine needs no API keys (the
deterministic analyzer replaced the old LLM stack in v3).

## Operations

```bash
docker compose ps                     # health status
docker compose logs -f engine         # follow engine logs
docker compose exec engine python cli.py stats
docker compose restart ui             # pick up UI code changes
docker compose down                   # stop (data survives in fdz_data)
docker compose down -v                # stop AND erase data
```

Upgrades: `git pull && docker compose build && docker compose up -d`.
Migrations apply automatically at engine startup (idempotent ledger —
see [05-database-schema.md](05-database-schema.md)).

## Notes

- The development sandbox used to prepare this refactor had no Docker
  daemon: the compose file and both Dockerfiles are structurally
  validated (YAML parse + dependency-split assertions) but were not
  runtime-tested here — verify with `docker compose config && docker
  compose build` on your machine.
- Single-user/personal scale by design; scale the crawler with
  `CRAWLER_WORKERS` and the HTTP pool with `HTTP_MAX_CONNECTIONS`
  rather than replicas (SQLite is single-writer by nature).
