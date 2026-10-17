# 03 · Engine Design

## Discovery pipeline

```
query
  → sanitise (injection guard)                    utils/query_expander.py
  → dialect expansion (offline FR/MSA/Darja)      config/dialect_matrix.py
  → cap at DISCOVERY_MAX_VARIANTS (default 2)     v4 Task 11
  → fan-out: every (variant × scraper) in parallel
       ├─ DuckDuckGo HTML SERP   infrastructure/scrapers/duckduckgo.py
       ├─ Overpass (OSM)         infrastructure/scrapers/overpass.py
       └─ SearXNG (optional)     infrastructure/scrapers/searxng.py
  → fan-in queue (first result of ANY source yields immediately)
  → per lead: spam gate → phone validation → geo inference (area code)
              → deterministic audit → scoring
  → atomic upsert (ON CONFLICT)                   infrastructure/storage/lead_repo.py
  → campaign accounting (created vs merged)
  → incremental entity resolution (new records only)
```

### Business Quality Gate (issue #8 — trusted directory tier)

`utils/spam_filter.py` classifies sources in three tiers:

1. **Trusted local directories** — Ouedkniss, CACI El Mouchir,
   Pages Jaunes DZ. Their *profile* pages (store/company/fiche URLs)
   pass the gate as structured business sources; their *search/index*
   pages, homepages, result-wording titles, and non-business titles
   stay blocked. Profile provenance is exposed via
   `SourcingSpamFilter.is_trusted_directory(url)` so downstream code can
   distinguish a directory profile from an ordinary website.
2. **SEO aggregators & international directory giants** (Cybo,
   YellowPages, TripAdvisor, annuaire-algerie, …) — always blocked.
3. **Junk domains** (marketplaces, encyclopedias, media, gov/legal) —
   always blocked; social platforms stay allowed (their business pages
   are the prime "no website yet" segment and get deep-crawled).

Hostless/malformed URLs are rejected like empty ones.

Time-to-first-result is bound by the *fastest* source, not the sum of
sequential variant searches (the v4 "dialect multiplier bomb").

### OpenStreetMap as an asymmetric oracle (v4 Task 8)

Overpass enriches geolocated businesses but never gates discovery: a
missing wilaya falls back to the national bounding box, and any Overpass
failure degrades silently inside the per-scraper pump — web discovery
proceeds regardless.

### Optional SearXNG (v4 §5.2)

`SEARXNG_URL` (e.g. `http://searxng:8080` with the compose profile)
switches in a local metasearch: clean aggregated JSON, no DDG anti-bot
limits. Empty = disabled; DDG remains the default source.

## Scoring (v4 Task 10 — inverted opportunity model)

Single arithmetic source of truth: `engine/fastops.score_batch`.

```
priority = reach (≤35) + substance (≤25) + opportunity (≤25)
         + deficit ((100 − digital) × 0.25) + freshness (≤15)   [cap 100]
```

- **reach**: phone 15, mobile +10, WhatsApp +5, email +5
- **substance**: website 10, social 5, address 5, GPS 5
- **opportunity** (the v4 inversion): no website → +15
  `website_build_opportunity`; no address AND no GPS → +10
  `local_seo_opportunity`. A reachable business with no web presence is
  the prime web-design prospect, so absence *raises* the score.
- Acceptance: a verified-phone lead with no website and no map pin scores
  ≥ 60 (`tests/test_v4_refactor.py::TestTask10OpportunityScoring`).

`digital_score` (the audit "health" column) mirrors `engine/analyzer.py`'s
deterministic audit and is untouched by the opportunity factors.

## Entity resolution (v3.1 pipeline, unchanged semantics)

`engine/resolution/` — features → blocking (token/prefix/phone/domain
blocks) → name similarity (trigram bit-set prefilter + rapidfuzz
Levenshtein via `engine/fastops.NameMatcher`) → evidence scoring →
classification (SAME / RELATED / DISTINCT / UNRESOLVED) with manual
override pinning → constrained clustering (pre-seeded from existing
`cluster_id`s in incremental mode) → canonical records, relations,
decision log, review queue.

Human decisions (merge, split, review) are logged as manual decisions the
engine treats as pinned overrides on every later run.

## fastops — the pure-Python kernel (v4 Task 13)

`engine/fastops.py` replaced the former C++20/ctypes core:

| Concern | Implementation | Why |
|---|---|---|
| HTML structural scan | pre-compiled regex pass over raw bytes | the C scanner did no real SIMD; regex scan measured **9.2× faster** than the BS4 fallback path that production actually ran (see [12-performance.md](12-performance.md)) |
| Levenshtein | `rapidfuzz.distance.Levenshtein` (C) | already a pinned dependency; faster than the C session for short business names |
| URL dedup | per-instance bounded `UrlDedup` (locked set, capacity-capped) | the global C bloom had thread-safety bugs and leaked state across instances; SQLite `UNIQUE(url)` remains authoritative past the cap |
| Scoring | SoA batch pass | one pass per batch; same arithmetic as the single-lead path |

## Geographic engine

`engine/geo.py` loads the versioned boundary dataset once per process and
provides bbox-prefiltered ray-casting point-in-wilaya (~40k lookups/s),
area-weighted centroids, per-wilaya bboxes, and catalogue joins with live
counts (SQL `GROUP BY` results — never full-row loads). See
[06-geographic-data.md](06-geographic-data.md) for the dataset itself.

## Crawler

Persistent SQLite frontier with atomic `BEGIN IMMEDIATE` claims; N
workers; AIMD adaptive concurrency; per-domain token-bucket politeness;
**per-domain** exponential backoff (v4 Task 14 — one blocked host never
slows unrelated hosts); bounded reads — the body is streamed and cut off
at 32 KiB (v4 §5.3) since identity signals live in `<head>` and the top
of the document.
