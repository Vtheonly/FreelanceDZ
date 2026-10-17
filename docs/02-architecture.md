# 02 · Architecture & Service Boundaries

## Topology

```
┌──────────────────────┐   HTTP (JSON, documented)   ┌──────────────────────┐
│  Streamlit UI :8501  │ ──────────────────────────► │   Engine API :8080   │
│  ui/                 │      /api/v2/*, /health     │  api/                │
│  pure API client     │                             │  ┌────────────────┐  │
└──────────────────────┘                             │  │ services/      │  │
                                                     │  │  discovery     │  │
┌──────────────────────┐                             │  │  resolution    │  │
│  CLI                 │ ──────────────────────────► │  │  crawler       │  │
│  cli.py              │   same engine modules        │  │  export        │  │
└──────────────────────┘                             │  ├────────────────┤  │
                                                     │  │ engine/        │  │
                                                     │  │  analyzer      │  │
                                                     │  │  scorer        │  │
                                                     │  │  fastops       │  │
                                                     │  │  geo + geodata │  │
                                                     │  │  resolution/   │  │
                                                     │  ├────────────────┤  │
                                                     │  │ infrastructure │  │
                                                     │  │  storage (SQL) │  │
                                                     │  │  scrapers      │  │
                                                     │  │  http, resil.  │  │
                                                     │  └────────────────┘  │
                                                     │        SQLite         │
                                                     │      /app/data/       │
                                                     └──────────────────────┘
```

The engine is a **modular monolith** with clean internal boundaries — a
deliberate choice (see [adr/ADR-006-modular-monolith.md](adr/ADR-006-modular-monolith.md)).
Only two containers are deployed because only two components have genuinely
different lifecycles (API vs. presentation); splitting the engine itself
into microservices would add network hops and operational cost with zero
isolation benefit at this scale.

## Layer contract

| Layer | Modules | May import | Never imports |
|---|---|---|---|
| Domain | `domain/` | (stdlib, pydantic) | everything else |
| Engine kernels | `engine/` | domain, config | infrastructure, services, api, ui |
| Infrastructure | `infrastructure/` | domain, engine kernels, utils | services, api, ui |
| Services | `services/` | domain, engine, infrastructure, utils | api, ui |
| API | `api/` | services, infrastructure, domain, engine.geo, config | ui |
| UI | `ui/` | **httpx + streamlit only** | api, services, infrastructure, engine kernels, domain |

The UI purity rule is enforced by an automated test
(`tests/test_repo_hygiene.py::test_ui_never_imports_engine_internals`):
the workspace must remain a client, not a second backend.

## Key invariants

1. **Business logic exists once.** Scoring, auditing, filtering, wilaya
   geometry, campaign accounting — all live in the engine. The UI calls
   the same endpoints any other client would.
2. **The engine never depends on Streamlit.** `tests/` run the whole
   engine without Streamlit installed.
3. **All state transitions are persisted by the engine**; the UI keeps
   only presentation state (session) and TTL-bounded read caches.
4. **Explicit contracts.** Every UI-visible operation maps to a documented
   endpoint ([04-api-reference.md](04-api-reference.md)); errors carry
   `detail` messages that the UI surfaces verbatim.

## Process model

- Engine: one uvicorn process; SQLite in WAL mode with per-operation
  connections; blocking SQL offloaded via `asyncio.to_thread`.
- Discovery: concurrent (variant × scraper) streams fan-in through one
  queue; per-scraper failure isolation (OSM down never blocks web search).
- Crawler: bounded worker pool, AIMD adaptive concurrency, per-domain
  token bucket + per-domain exponential backoff.
- UI: one Streamlit process; reads cached with TTLs; mutations invalidate
  exactly the affected caches.
