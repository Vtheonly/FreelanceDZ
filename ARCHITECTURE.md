# FreelanceDZ v3 — Architecture Decision Record

This document records how the definitive v3 implementation incorporates the
engineering knowledge of all previous iterations, what was retained or
replaced and why, and what the measured results are. It reflects the code
that actually exists; every claim below is backed by the test suite
(`tests/`), the benchmark suite (`benchmarks/`), or a file reference.

---

## 1. Iteration history (reconstructed)

| Iteration | Contribution | Fate in v3 |
|---|---|---|
| Iter 0 (notes) | Engine equation `s ← F(s, C)`, six-layer model, work elimination, hot/cold state split | Structural philosophy throughout |
| Iter 1 (v2.1) | LLM removal ("cannot afford"), deterministic auditor, **unified `leads` schema + FTS5**, one Lead model | Restored core; the unified schema is the centerpiece of storage v2 |
| Iter 2 (v3.0) | `engine/` package, 58-wilaya DB, carrier detection, dialect matrix, DZD service catalog, FR/AR CTAs | Restored in `engine/analyzer.py` + `config/` |
| Iter 3 | **C++20 native core**: Myers Levenshtein, AVX2 trigram Jaccard, SoA scoring, DSU, ISA detection, ctypes bridge + fallbacks | Restored as `engine_native/` + `engine/native.py`, improved |
| Iter 4 | **Streaming acquisition**: blocked Bloom, SIMD HTML scan, token bucket, AIMD, prioritized frontier, TTFR | Restored in `engine/acquisition/` + streaming services, bugs fixed |
| v2.0.0 repo | Two-layer SERP+schema extraction, freshness detector (EN/FR/AR), trigram blocking + graph resolver, persistent frontier, migration registry, 56 network-free tests | Retained (utils, extractor, frontier, migrations, tests) |
| v2.0.0 regressions | LLM stack reintroduced; 4-way data model split; single-flight crawler; proxy TypeError crash-loop; route-order 422s; FTS injection 500s; dead settings/interfaces/deps | All eliminated (see §4) |

## 2. The definitive architecture

**Hybrid execution model.** The workload is network-bound (search + page
fetches with politeness delays), so the orchestration layer is Python
asyncio — the right tool for I/O concurrency. The CPU-bound hot paths
(HTML scanning, entity-resolution matching, batch scoring, URL dedup) live
in ONE C++20 shared library with runtime ISA detection (SSE4.2 / AVX2 /
AVX-512 / scalar) and **pure-Python fallbacks for every symbol**, parity-
tested (`tests/test_native_parity.py`). The engine runs correctly without
the native library; it just runs slower on those paths.

**Single source of truth.** One `leads` table (schema v2) replaces the v2
quartet (raw_records + analyses + lead_scores + resolved_entities). Entity
resolution became non-destructive metadata: `cluster_id` on leads plus
`entity_clusters` / `entity_links`. Migration 8 consolidates v1 databases
(and is a no-op on fresh installs).

**Legacy reconciliation (v3.0.1).** v3.0.0 crashed at startup on real v2.0.0
databases (`no such column: lead_id`): v2.0.0's Python migrations 5-7 had
created `lead_attachments` (keyed by `raw_record_id`) and
`discovery_campaigns` (`limit_num` / `*_qty` columns) in shapes the v2
baseline cannot CREATE over — and `executescript` had already autocommitted
the statements before the failing one, leaving a half-applied schema. Fix:
`initialise()` now (1) renames legacy-shaped tables to `legacy_<name>` before
applying the baseline, (2) applies the baseline inside an explicit
BEGIN/COMMIT so a failure leaves nothing behind, and (3) migration 8 folds
legacy attachment and campaign rows into the v2 tables (mapping
`raw_record_id` through fingerprints to new lead ids) before the v1 drops
would CASCADE-delete them. `tests/test_legacy_upgrade.py` rebuilds a faithful
v2.0.0 database (actual `schema_v1.sql` + the exact SQL of v2.0.0 migrations
5-7) and covers the pristine, the half-migrated, and the re-init paths.

**Streaming pipeline.** Discovery yields leads the moment each SERP page is
parsed; audit + scoring + persistence happen per-lead while later pages are
still in flight. The crawler runs N concurrent workers (hardware-derived,
bounded) over the persistent SQLite frontier with atomic
(`BEGIN IMMEDIATE`) claims, per-domain token-bucket politeness, AIMD
congestion control, and per-proxy pooled clients.

**Deterministic intelligence.** The LLM stack is gone entirely (rationale in
§5). The analyzer computes digital score, gaps, catalog-matched DZD pitches,
and FR/AR CTAs deterministically in microseconds.

## 3. Native core decisions (what justified C++/SIMD and what didn't)

| Component | Kept? | Rationale (measured) |
|---|---|---|
| Zero-copy SIMD HTML scan | **Yes** | ~106x vs BS4+lxml on an 11 KB page (44k vs 418 pages/s). This is the crawler's per-page cost. |
| Blocked Bloom URL dedup | **Yes** | 47x less memory than a Python set at 1M URLs. Speed is comparable (per-op ctypes overhead); the win is scale. |
| SoA batch scoring | **Yes** | ~3x vs Python loop. Cheap to maintain, aligned with the flags-based hot state. |
| Names-match session (prefilter + Myers) | **Yes** | ~1.55x end-to-end on full resolution with identical cluster output. |
| Raw per-pair Levenshtein | **No — rapidfuzz wins** | rapidfuzz's isolated-call binding (3.2M/s) beats the native session (0.45M/s) because index marshalling dominates. The fallback therefore uses rapidfuzz; the native path only pays off batched with the prefilter cascade. |
| Full C++ engine / kernel bypass / core pinning | **No** | The workload is network-bound; these add complexity without measurable benefit at this scale. |

## 4. Defects eliminated (all verified in the v2.0.0 audit)

1. `/leads/search` shadowed by `/leads/{lead_id}` → 422 on every dashboard
   search. **Fixed** (static routes registered first; regression-tested).
2. FTS5 `MATCH` injection → unhandled `OperationalError` → HTTP 500.
   **Fixed** (`fts_sanitize` quotes every token; tested with hostile inputs).
3. `score_all` re-scored only the top-N leads *by existing score* —
   zero-score leads beyond N were never scored. **Fixed**
   (`list_unscored`).
4. `list_unresolved` == `list_all` — every run re-analyzed the newest N
   records. **Fixed** (`list_unanalyzed` filters `digital_score IS NULL`).
5. `attach_analysis` clobbered CRM status (`contacted`/`rejected`).
   **Fixed** (unified status-preserving upsert; tested).
6. Per-request `proxy=` kwarg on a shared httpx 0.28 client → TypeError
   crash-loop whenever proxies were configured. **Fixed** (per-proxy pooled
   clients via `HttpClientFactory.get_proxy_client`).
7. `duplicate_count` never reflected duplicates (repo returned the existing
   row id on conflict). **Fixed** (upsert returns `(id, created)`).
8. Crawler housekeeping modulo bug (`0 % 50 == 0` fired every iteration).
   **Fixed** (`if self._pages and ...`).
9. Health endpoint ran a full `PRAGMA integrity_check` synchronously on the
   event loop. **Fixed** (metadata-only by default; opt-in check offloaded).
10. Dashboard autocomplete called a nonexistent endpoint. **Fixed**
    (`/api/v2/search/autocomplete` wired to `search_vocabulary`).
11. `stats()` hardcoded `age_breakdown: []` ("Fresh 24h" always 0).
    **Fixed** (real GROUP BY over the freshness JSON).
12. Crawler `bootstrap(wilaya)` ignored the wilaya. **Fixed** (seed builder
    uses it).
13. Bloom FPR 9.4% vs 1% target (correlated bit-position hash). **Fixed**
    (seeded second hash; measured 0.57%).
14. Stale test `test_blocks_social_platforms` contradicted the deliberate
    allow-listing of social platforms (deep-crawl enrichment targets).
    **Fixed** (test now asserts the actual design).
15. SQLite frontier claim race (SELECT-then-UPDATE in a deferred
    transaction). **Fixed** (`BEGIN IMMEDIATE` claim path).

## 5. Removals (and why the system is better without them)

| Removed | Why |
|---|---|
| **LLM stack** (`infrastructure/llm/`, 9 modules) | The user removed it in iteration 1 for cost/reliability; iterations 2-4 never needed it; v2.0.0 reintroduced it behind three redundant fallback layers whose practical runtime path (no API key) was the keyword heuristic anyway. The deterministic analyzer provides the same capability offline, deterministically, in microseconds. Dead config (`LLM_MAX_RETRIES`, `LLM_FALLBACK_KEYS`) and dead deps (`openai`, `tiktoken`) went with it. |
| **4-way data model** | Iteration 1 proved the unified model; v2.0.0's split forced a 3-way LEFT JOIN on every read and duplicated INSERT SQL across repos. |
| `core/lifecycle.py` + duplicate client factory | Two copies of the same pooled-client bootstrap; the lifecycle's client was never used by any CLI command and the factory's client was never closed in CLI. One factory now serves both paths. |
| `core/interfaces.py` (17 ABCs) | 6 were decorative (never implemented/inherited), including `IProxyOrchestrator.evaluate_response` (no implementation anywhere). Replaced by a runtime-checkable `Scraper` protocol where polymorphism is real (DDG/Overpass). |
| Social scraper + FB/IG/TikTok plugin classes | Never wired (`ENABLE_SOCIAL_SCRAPER` unread); three near-identical httpx-only stubs. Social URL handling folded into the DDG deep-crawl enrichment. |
| `utils/retry.py`, `tenacity`, `python-dateutil` deps | `retry`'s only consumer was the LLM client; the other two packages were never imported. |
| `config/proxies.py` | Parallel proxy-config path; the orchestrator already parses `settings.proxy_list_parsed`. |
| Dead exceptions (4 of 9), dead settings (7), dead constants (5+) | Never raised/read anywhere. |

## 6. Data integrity guarantees

- Upserts merge by fingerprint and keep the richer value per field
  (`COALESCE`/`MAX` semantics) — a re-scrape with less data never erases.
- CRM status survives re-analysis and re-scoring (tested).
- Entity resolution never mutates or deletes lead rows; clusters reuse
  existing IDs when membership is unchanged, and stale clusters are pruned
  via `ON DELETE SET NULL` (v3.1: pruning is scoped to the leads the run
  actually considered, so clusters beyond the resolution batch cap are
  no longer destroyed).
- v3.1 guarantees: every merge/link/separation is logged with its full
  evidence (`resolution_decisions`); manual decisions (splits, merges,
  review resolutions) are loaded as pinned overrides that no later
  automated run can contradict; splitting restores the exact source
  records because they were never modified in the first place.
- Migration 8 is idempotent and re-runnable; the test suite builds a full
  synthetic v1 database and verifies field-level migration correctness.
  Migration 9 (v3.1) adds the decision log, review queue and relations
  tables with guarded column adds — idempotent on fresh and v3.0.1
  databases alike.

## 7. Configuration policy (hardcoding audit)

- **Hardware-derived defaults**: crawler workers
  `max(2, min(16, cpus*4))`, max concurrency `max(8, min(64, cpus*8))`,
  connection pool `max(20, min(200, cpus*16))` — bounded, env-overridable.
- **Operational parameters** (timeouts, rates, limits, thresholds): settings
  with sane defaults, every field consumed somewhere (verified).
- **Domain rules** (scoring weights, entity composite weights): named
  constants in the owning module — they are invariants of the domain model,
  not runtime knobs.
- **Genuine invariants** (e.g., 64-byte cache-line blocking, 256-bit
  bitsets): documented constants in the native code.

## 8. Remaining limitations

- DuckDuckGo HTML scraping is inherently fragile (markup changes, rate
  limits); the anti-block engine mitigates but cannot eliminate this.
- Social-platform enrichment is best-effort (login walls); no headless
  browser is bundled by choice (Playwright remains optional).
- The native library must be rebuilt per platform (`bash
  engine_native/build.sh`); pure-Python fallbacks keep the engine correct
  without it.
- Entity resolution is no longer batch-only: v3.1 runs incrementally after
  every discovery campaign (new records scored against their candidates
  only, existing clusters pre-seeded). A full cross-record re-resolution
  pass over the whole corpus remains a manual operation
  (`POST /api/v2/entities/resolve`).
- Cross-script (Arabic ↔ French) name matching relies on non-name signals;
  transliteration is future work.
- One event loop by design (personal use); multi-process serving was
  deliberately not built.

## 9. Verification

- `python -m pytest tests/ -q` → **131 passed** (utils, storage v2,
  migration, native/fallback parity, engine, resolver, resolution v3.1
  scenarios, API integration).
- `python cli.py bench` → the benchmark suite with v2-equivalent baselines
  (strongest available pure-Python implementation of each previous
  approach) and the honest summary printed inline.

## 10. Entity resolution v3.1 — decision record

The feature spec demanded a business-entity-resolution engine that (a)
aggregates the five online channels of one restaurant into a single
canonical entity, (b) never merges two businesses merely because their
names match, (c) keeps branches/franchises of one organization separate
but linked, (d) explains every decision, and (e) can undo its mistakes.

### Why evidence buckets instead of one composite score

v3.0's single composite (name 0.40 / website 0.25 / phone 0.20 / email
0.15, one threshold) cannot express "same organization, different
location" — a shared chain domain plus similar names scored as a merge.
v3.1 splits every signal into three buckets:

- **identity** — evidence of one physical business (shared phone,
  matching social handle, cross-references, exact email, co-location);
- **org** — evidence of one organization (name similarity, a chain's
  shared domain, shared email domain, shared contact channel);
- **conflict** — evidence against (disjoint phones, different cities,
  disjoint verified addresses, different domains).

SAME requires identity ≥ 0.70, conflict ≤ 0.45, name ≥ 0.45, and either a
contact identifier that alone reaches the bar or explicit same-place
evidence (pins < 200 m or address overlap ≥ 0.5). That last clause is
what keeps blind chain-branch pairs (shared domain, pins a few km apart,
no phones) out of auto-merge while still merging a website + Google
profile that share a domain and an address. Location agreement is capped
at 0.55 so two records that merely place themselves in the same
neighbourhood can never reach the merge bar without contact corroboration
— the "two cafés on one street" case goes to review, exactly as the spec
requires ("shared names or generic contact details must not automatically
establish identity").

### Why not ML / embeddings

The measurable failure modes are structural (shared chain domains,
copy-pasted directory addresses, phone-format variance), and the corpus is
small and unlabeled. Deterministic signal weights + thresholds are fully
explainable (each decision log row carries its per-signal scores),
debuggable by reading, and free of training/serving cost — the spec's own
instruction: "choose the architecture based on measurable accuracy and
performance rather than introducing machine learning where simpler,
reliable methods are sufficient". Arabic transliteration (currently
same-script only) is the one place embeddings might earn their keep, and
it is deliberately deferred.

### Blocking, transitivity, and contradiction handling

Six blocking keys (name trigrams, type-word-stripped prefix, every E.164
phone, registrable domain, social platform:handle, wilaya+first-token)
replace name-only trigrams, so cross-channel duplicates with differently
worded names still become candidates. Clustering is union-find applied in
score order with two guards v3.0 lacked: DISTINCT decisions with conflict
≥ 1.0 register as must-not-link constraints that veto later unions (a
strongly-supported disagreement can never be transitively overruled), and
edges lacking a contact identifier cannot chain through existing
components. Both guards log their blocked edges as contradictions.

### Canonical records and conflict resolution

Field-level selection with provenance: names are voted (two-level —
normalized key, then display string), factual fields rank source trust
(manual > OSM > SERP > social) then recency then substance, and any
disagreement is recorded as alternatives rather than overwritten. Aliases
preserve every name variant. Cluster confidence derives from the weakest
merge edge (v3.0 rewarded member count, which big weak clusters gamed).

### Incremental mode

After each campaign the resolver loads the full lead set (for blocking
context) but scores only pairs touching new records; existing clusters
are pre-seeded from `lead.cluster_id` so prior decisions stand and ids
stay stable — the test suite verifies a cluster grows in place (same id,
no duplicate cluster) as new duplicates arrive across campaigns.

### Precision-first calibration trade-off (behaviour change vs v3.0)

Two records sharing a name, a wilaya and nothing else were merged by v3.0
(composite ≈ 0.66 > 0.65); v3.1 queues them for review. That is the spec's
stated preference — an incorrect merge is a more serious error than a
temporary duplicate — made explicit in the classifier rather than hidden
in a weight. The review queue exists precisely so the cheap error stays
correctable by one click.
