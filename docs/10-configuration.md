# 10 · Configuration & Secrets

All configuration flows through `config/settings.py`
(pydantic-settings): environment variables first, then an optional
`.env` file at the repo root (git-ignored). `.env.example` documents the
complete, current surface — there are no hidden config sources and no
credentials in code.

## Application

| Variable | Default | Meaning |
|---|---|---|
| `APP_NAME` / `APP_VERSION` | FreelanceDZ Engine / 4.0.0 | reported by `/health` |
| `API_HOST` / `API_PORT` | 127.0.0.1 / 8080 | engine bind (compose: 0.0.0.0) |
| `LOG_LEVEL` | INFO | DEBUG / INFO / WARNING / ERROR / CRITICAL |
| `LOG_FORMAT` | console | `json` for structured logs |
| `LOG_DIR` / `DATABASE_PATH` / `EXPORT_DIR` / `ATTACHMENTS_DIR` | `./data/...` | storage locations |

## Discovery

| Variable | Default | Meaning |
|---|---|---|
| `ENABLE_DDG_SCRAPER` / `ENABLE_OVERPASS_SCRAPER` | true | per-source switches |
| `SEARXNG_URL` | *(empty)* | optional metasearch base URL |
| `DISCOVERY_MAX_VARIANTS` | 2 | dialect variants per campaign (v4 Task 11) |
| `MAX_SEARCH_PAGES` | 3 | SERP pagination depth |
| `DEFAULT_QUERY_LIMIT` | 30 | default campaign size |
| `SCRAPER_TIMEOUT_SECONDS` | 20 | per-request timeout |
| `MAX_CONCURRENT_REQUESTS` | 2×CPU | global scraper semaphore |
| `RATE_LIMIT_DELAY_SECONDS` | 1.5 | politeness baseline |

## Crawler

| Variable | Default | Meaning |
|---|---|---|
| `CRAWLER_WORKERS` | 4×CPU (2–16) | worker pool size |
| `MAX_CRAWL_DEPTH` | 3 | frontier depth |
| `JITTER_BASE_DELAY` | 1.0 | anti-block jitter base (also the per-domain backoff base) |
| `ACQ_MIN/MAX_CONCURRENCY` | 4 / 8×CPU | AIMD bounds |
| `ACQ_DOMAIN_RATE` / `ACQ_DOMAIN_BURST` | 2 / 4 | per-domain token bucket |
| `BLOOM_CAPACITY` | 2,000,000 | legacy name; now the URL dedup capacity hint |

## Entity resolution

`ENTITY_AUTO_RESOLVE` (true), `ENTITY_RESOLUTION_BATCH` (20k), and the
v3.1 evidence thresholds (`ENTITY_MERGE_*`, `ENTITY_RELATED_*`,
`ENTITY_DISTINCT_TOTAL`) — see `config/settings.py` for the precise
semantics of each.

## UI

| Variable | Default | Meaning |
|---|---|---|
| `ENGINE_URL` | http://localhost:8080 | engine API base URL (compose: http://engine:8080) |

## Secrets

There are **none** — no API keys, no tokens. The LLM stack (and its
keys) was removed in v3 for the deterministic analyzer. Proxy URLs in
`PROXY_LIST` may embed credentials; keep them in `.env`, which is
git-ignored (`tests/test_repo_hygiene.py` asserts `.env` and `data/`
are never tracked).

## Validation

`LOG_LEVEL` is validated; numeric fields carry bounds (ge/le) so a
malformed value fails fast at startup instead of misbehaving at runtime.
`get_settings()` is an `lru_cache` singleton — tests reset it via
`get_settings.cache_clear()`.
