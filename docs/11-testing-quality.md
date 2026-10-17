# 11 · Testing & Quality

## Suite layout (`python -m pytest tests/ -q`)

| File | Scope |
|---|---|
| `test_v4_refactor.py` | the acceptance record: one test class per documented refactorv4/v5 task (empty-wilaya 422, tags alias, unified listing + FTS injection, 50-way concurrent atomic upsert, URL scheme allow-list, junk-domain gate, WAL-once, ≥60 opportunity score, variant cap + concurrent dispatch proof, Overpass bbox fallback, per-domain backoff isolation, checkpoint CRUD + geometry validation + moving re-derivation, campaign contract) |
| `test_geographic.py` | dataset integrity (58 codes, closed rings, bbox, catalogue name equality), point-in-polygon on known cities, centroid self-containment, catalogue joins, telephony inference |
| `test_ui.py` | REAL frontend→backend integration: `ui/app.py` under AppTest against an in-process uvicorn engine with a seeded DB; plus the unreachable-engine error state |
| `test_api.py` | route ordering, search/autocomplete, stats, CRM transitions, resolution flow, exports, crawler |
| `test_fastops.py` | kernel semantics: Levenshtein cases, trigram ordering, score invariants + opportunity arithmetic, NameMatcher isolation, UrlDedup bounding, HTML extraction fields/caps |
| `test_storage_v2.py` / `test_legacy_upgrade.py` | schema, migrations, merge policy, legacy-database upgrades |
| `test_engine.py` / `test_resolution.py` | analyzer, scorer flags, resolver determinism, human-in-the-loop operations |
| `test_performance.py` | repeatable regression thresholds (extraction ≥2k/s, 50k scoring <1 s, upsert atomicity, composed listing latency, geo lookup, API budgets) |
| `test_repo_hygiene.py` | architecture guards: every module compiles & imports resolve; no stale references to removed subsystems; **ui/ purity** (no engine imports); no package import cycles; no unreachable modules; intentional repo root; no tracked data/secrets; geodata committed + attributed; ruff F/E9 clean |

## Philosophy

- **No mock-first integration.** The UI suite drives the actual app
  against an actual server; storage tests use real SQLite files; API
  tests use the real app factory. Mocks appear only where the boundary is
  genuinely external (scraper HTTP is exercised through the engine's own
  failure isolation).
- **Coverage follows meaning, not file count.** Configuration files and
  generated assets are validated structurally (hygiene suite, compose
  assertions, dataset integrity) rather than by contrived unit tests.
- **Tests document decisions.** The Task-numbered classes in
  `test_v4_refactor.py` are the durable evidence ledger for the refactor;
  `docs/14-refactoring-history.md` cross-references them.

## Static analysis & formatting

```bash
ruff check .                          # F (pyflakes) + E9 (syntax) — enforced green in CI-style runs
ruff check --fix --select F401 .      # auto-remove unused imports
```

Line length 110, target py3.10 (`pyproject.toml [tool.ruff]`).

## Adding a migration or endpoint

1. Migration: register with `@DatabaseManager.register_migration(N, ...)`,
   keep it idempotent, update `test_storage_v2.py`'s expected version set.
2. Endpoint: extend `docs/04-api-reference.md` in the same commit; API
   behaviours get a test in `test_api.py` or `test_v4_refactor.py`.
3. New UI panel: keep it a pure API client — the hygiene suite fails the
   build if `ui/` imports engine internals.
