# 12 · Performance

## Method

Measured on the development sandbox (Python 3.12.15, Linux). "Before" is
commit `481cc9b` (pre-refactor) in a git worktree; because the C++ native
library was never shipped or built, production always ran the pure-Python
fallback paths — which is what the "before" numbers measure. "After" is
the refactored branch. Storage numbers use fresh temp databases and
realistic workloads (2,000 seeded leads). Threshold-protected regression
tests live in `tests/test_performance.py`.

## Results

| Operation | Before (481cc9b) | After | Δ |
|---|---|---|---|
| HTML structural extraction (11 KB page) | 989/s (BS4 fallback) | **9,117/s** (regex scan) | **9.2× faster** |
| Batch scoring (50k leads) | 1,121,248/s | 978,256/s | −13% (adds the Task-10 opportunity arithmetic; both ≫ workload) |
| Batch scoring, 100k flags (issue #16) | 943,656/s (scalar oracle) | **3,457,148/s** (512-entry LUT) | **3.66×** like-for-like (identical gated semantics), exact parity with the oracle |
| Upsert, sequential ×500 | 1,005/s | 877/s | −13% (ON CONFLICT + BEGIN IMMEDIATE — the price of race-freedom) |
| Upsert, 50 concurrent same-lead | 1 id, 0 exceptions* | 1 id, 0 exceptions | *see honesty note |
| Point-in-wilaya lookup | — | **39,627/s** (59% hit-rate on uniform bbox points) | new capability |
| Wilaya catalogue join (58 + counts) | — | 13,334/s | new capability |

### Read paths (after, 2k-lead database)

| Query | Rate |
|---|---|
| `list_leads()` page of 50 | 431/s |
| `list_leads(wilaya=…)` | 390/s |
| `list_leads(q=… FTS)` | 294/s |
| `list_leads(q + wilaya + min_score)` composed | 500/s |
| `stats()` | 310/s |
| `count_by_wilaya()` (catalogue aggregation) | 758/s |

### API round-trips (TestClient, in-process)

| Endpoint | Latency |
|---|---|
| `GET /health` | 0.76 ms |
| `GET /api/v2/stats` | 4.09 ms |
| `GET /api/v2/geo/wilayas` | 4.26 ms |
| `GET /api/v2/leads?limit=50` | 5.79 ms |
| `GET /api/v2/leads?q&wilaya` (composed) | 6.50 ms |
| `GET /api/v2/geo/boundaries` | 26.96 ms — the one heavyweight: immutable, so the UI caches it (1 h TTL) and refetches only on dataset change |

### Honesty notes

- **Upsert apparent safety before**: the old code also produced "1 id, 0
  exceptions" in-process — not because it was race-free, but because the
  per-connection `PRAGMA journal_mode=WAL` re-declaration (the exact
  anti-pattern Task 15 removed) serialised writers behind an exclusive
  lock. The SELECT-then-INSERT window was real; multi-process
  deployments could hit `UNIQUE constraint failed`. The new upsert is
  race-free *by construction* (single `ON CONFLICT` statement inside
  `BEGIN IMMEDIATE`) and the −13% sequential throughput is the documented
  cost of that guarantee.
- **Scoring −13%**: the new arithmetic adds two opportunity checks per
  lead (the v4 Task 10 requirement). At ~1M leads/s, irrelevant in
  practice.
- **Scoring LUT (issue #16)**: the 9 channel flags span exactly 512
  words, so every flag-derived component is precomputed at import into
  `_SCORE_LUT` and the batch loop is one list index per lead. Measured
  on the dev sandbox (Python 3.12.15, Linux, best-of-5, official
  harness `python cli.py bench`, 100k random flag words): LUT path
  3,457,148/s vs 943,656/s for the branch-by-branch scalar oracle with
  identical gated semantics — **3.66×**. (The pre-#16 ungated loop
  measured ~990k/s; its semantics differed — no contactability gate.)
  A numpy vectorization of the same arithmetic measured **26.8M rec/s**
  but was **rejected**: it would add numpy to the engine's dependency
  footprint for a workload (discovery campaigns + rescoring, tens to
  hundreds of leads at a time) that 3.4M rec/s already exceeds by three
  orders of magnitude. Right-sizing over raw speed.

## Streamlit rerun economy

- Reads are TTL-cached client-side (stats/leads 10 s, campaigns 5 s,
  catalogue 30 s, boundaries 1 h) — a widget rerun costs zero engine
  round-trips until a TTL lapses or a mutation invalidates the cache.
- The boundaries payload (~113 KB) crosses the wire once per session.
- Discovery runs engine-side in the background (`background=true`) and
  the queue polls `/discover/campaigns` — no rerun ever blocks on
  network scraping.

## Rejected / deferred optimizations (deliberate)

- **DNS pre-caching (v4 §5.1)**: httpx connection pooling + HTTP/2
  keep-alive already amortises DNS across the crawl; an aiodns/aiohttp
  swap would churn the HTTP stack for a marginal win. Rejected.
- **Full-map incremental rendering**: streamlit-folium re-renders the
  Leaflet component per state change; at 58 polygons + bounded marker
  counts this is imperceptible. Deferred until a measured need exists.
- **Redis-style server cache**: SQLite reads are already ~400/s per
  query class and the catalogue aggregates in SQL. Rejected as
  unnecessary infrastructure.

## Reproducing

```bash
python benchmarks/bench_engine.py     # CPU hot paths
python benchmarks/bench_storage.py    # storage + API + geo
python -m pytest tests/test_performance.py -q
```
