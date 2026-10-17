# FreelanceDZ Engine v3.0.1

A deterministic, high-performance **B2B lead-discovery engine for the Algerian
market**, engineered for **personal use on one powerful machine**.

v3 is the synthesis of every previous engineering iteration: it restores the
strongest ideas that were lost along the way (the unified data model from
iteration 1, the deterministic analyzer from iterations 1-3, the C++20 SIMD
native core from iteration 3, streaming web acquisition from iteration 4) and
combines them with the strongest ideas from the v2.0.0 rewrite (two-layer
SERP + schema.org extraction, freshness detection, trigram blocking,
persistent crawl frontier). See **ARCHITECTURE.md** for the full decision
record and measured benchmarks.

## Architecture

```mermaid
flowchart TD
    UI["FastAPI + Dashboard (api/)"] --> SVC["Services — thin orchestration<br/>(services/)"]

    SVC --> ENG
    subgraph ENG["Engine (engine/)"]
        direction LR
        AN["analyzer<br/>deterministic audit"]
        SC["scorer<br/>explainable 0-100"]
        RE["resolver<br/>blocking to clusters"]
        ACQ["acquisition<br/>token bucket, AIMD, streaming"]
        NB["native bridge<br/>ctypes + pure-Python fallbacks"]
    end

    ENG --> CPP["engine_native/<br/>C++20 AVX2 / AVX-512 core<br/>Myers Levenshtein, trigram Jaccard,<br/>SoA scoring, blocked Bloom,<br/>zero-copy HTML scan"]

    ENG --> INFRA
    subgraph INFRA["Infrastructure (infrastructure/)"]
        direction LR
        STORE["storage<br/>SQLite WAL + FTS5"]
        SCRAPE["scrapers<br/>DuckDuckGo, Overpass"]
        HTTP["http<br/>pooled, per-proxy clients"]
        RES["resilience<br/>backoff, block detection"]
    end

    classDef layerA fill:#e8f0fe,stroke:#5b7bd5,color:#1a2b4a
    classDef layerB fill:#e9f7ec,stroke:#4caf6d,color:#12331d
    classDef native fill:#fdeaea,stroke:#d9534f,color:#4a1411
    classDef layerC fill:#fff7e0,stroke:#d9a514,color:#4a3b07
    class UI,SVC layerA
    class AN,SC,RE,ACQ,NB layerB
    class CPP native
    class STORE,SCRAPE,HTTP,RES layerC
```

## Quick start

```bash
# 1. Install Python dependencies (runtime + test)
pip install -r requirements.txt -r requirements-dev.txt

# 2. Build the native C++20 SIMD core (falls back to pure Python if skipped)
bash engine_native/build.sh

# 3. Run the test suite (107 tests, no network required)
python -m pytest tests/ -q

# 4. Start the engine + dashboard
python main.py                      # serves http://localhost:8080
```

### CLI

```bash
python cli.py discover -q "pharmacie" -w "Alger" -l 30   # streaming campaign
python cli.py analyze                                     # audit + score pending
python cli.py resolve                                     # entity clustering
python cli.py stats                                       # database metrics
python cli.py export -f csv                               # export leads
python cli.py bench                                       # run benchmarks
python cli.py serve --port 8080                           # API + dashboard
```

## What it does

1. **Discover** — expands a query into FR / MSA / Darja variants (offline
   dialect matrix), searches DuckDuckGo (paginated) and OpenStreetMap
   Overpass concurrently, streams results the moment each SERP page is
   parsed (sub-second time-to-first-result).
2. **Extract** — two layers: SERP title/snippet signals, then an optional
   deep crawl of business pages using the native SIMD zero-copy scanner
   (JSON-LD schema.org, phones, emails, socials), with a BeautifulSoup
   fallback for malformed pages.
3. **Audit** — a fully deterministic analyzer (no LLM, no network, no API
   cost) scores digital presence 0-100, lists concrete gaps, and matches
   high-margin freelance service pitches from the Algerian catalog with DZD
   budgets and FR/AR outreach openers.
4. **Score** — explainable 0-100 priority (reachability + substance +
   opportunity deficit + freshness) with a per-factor breakdown.
5. **Resolve** — non-destructive entity clustering: trigram blocking →
   256-bit Jaccard prefilter → Myers Levenshtein verification (native SIMD)
   → composite scoring → union-find → golden records with lineage.
6. **Crawl** — autonomous concurrent crawler with a persistent, resumable
   frontier, per-domain politeness, AIMD adaptive concurrency, proxy
   rotation, block detection, and Bloom-filter URL dedup.

```mermaid
flowchart TD
    Q["Seed query<br/>FR / MSA / Darja variants"] --> DDG["DuckDuckGo SERP<br/>(paginated)"]
    Q --> OSM["OpenStreetMap<br/>Overpass API"]
    DDG --> STREAM["Stream results as each<br/>SERP page parses (fast TTFR)"]
    OSM --> STREAM
    STREAM --> EXTRACT["Two-layer extraction<br/>SERP signals, then deep crawl<br/>(SIMD zero-copy scanner, JSON-LD)"]
    EXTRACT --> DEDUP["Bloom-filter dedup +<br/>upsert-merge into leads"]
    DEDUP --> AUDIT["Deterministic audit<br/>0-100 score, gaps, DZD pitches, FR/AR CTAs"]
    AUDIT --> SCORE["Explainable priority score<br/>reachability + substance +<br/>opportunity deficit + freshness"]
    SCORE --> RESOLVE["Entity resolution<br/>clusters + lineage"]
    RESOLVE --> OUT["Dashboard + CSV/JSON export"]

    classDef input fill:#e8f0fe,stroke:#5b7bd5,color:#1a2b4a
    classDef process fill:#e9f7ec,stroke:#4caf6d,color:#12331d
    classDef store fill:#f3eafb,stroke:#8e6bbf,color:#2c1a4a
    class Q,DDG,OSM input
    class STREAM,EXTRACT,DEDUP,AUDIT,SCORE,RESOLVE process
    class OUT store
```

## Entity resolution

Non-destructive by design: clustering never merges or deletes lead rows —
membership lives in `cluster_id` + `entity_links`, so re-running resolution
can always be undone or refined.

```mermaid
flowchart TD
    LEADS["leads"] --> BLOCK["Trigram blocking<br/>(candidate groups)"]
    BLOCK --> PREF{"256-bit Jaccard<br/>above prefilter threshold?"}
    PREF -->|"no"| DISCARD["Keep records separate"]
    PREF -->|"yes"| MYERS["Myers Levenshtein verification<br/>(bit-parallel, native SIMD)"]
    MYERS --> COMP{"Composite score above merge<br/>threshold? (name + phone + wilaya guard)"}
    COMP -->|"no"| DISCARD
    COMP -->|"yes"| DSU["Union-find merge"]
    DSU --> GOLDEN["Golden records<br/>cluster_id + lineage links"]

    classDef input fill:#e8f0fe,stroke:#5b7bd5,color:#1a2b4a
    classDef process fill:#e9f7ec,stroke:#4caf6d,color:#12331d
    classDef decision fill:#fff7e0,stroke:#d9a514,color:#4a3b07
    classDef store fill:#f3eafb,stroke:#8e6bbf,color:#2c1a4a
    class LEADS input
    class BLOCK,MYERS,DSU process
    class PREF,COMP decision
    class DISCARD,GOLDEN store
```

## Crawler

The crawler runs N concurrent workers over a persistent SQLite frontier —
crash-safe, resumable, and polite by construction.

```mermaid
flowchart TD
    START["CrawlerEngine start"] --> CLAIM["Claim highest-priority URL<br/>(atomic claim, BEGIN IMMEDIATE)"]
    CLAIM --> POLITE{"Domain polite?<br/>(per-domain token bucket)"}
    POLITE -->|"not yet"| WAIT["Wait for domain token"]
    WAIT --> CLAIM
    POLITE -->|"ready"| FETCH["Fetch via pooled<br/>per-proxy client"]
    FETCH --> BLOCKED{"Blocked or<br/>rate-limited?"}
    BLOCKED -->|"yes"| ADAPT["Backoff + rotate proxy<br/>AIMD lowers concurrency"]
    ADAPT --> CLAIM
    BLOCKED -->|"no"| PARSE["Native zero-copy scan<br/>JSON-LD, phones, emails, links"]
    PARSE --> UPSERT["Upsert-merge lead data"]
    PARSE --> NEWURLS["Enqueue new URLs<br/>(Bloom-filter dedup)"]
    UPSERT --> CLAIM
    NEWURLS --> CLAIM

    classDef input fill:#e8f0fe,stroke:#5b7bd5,color:#1a2b4a
    classDef process fill:#e9f7ec,stroke:#4caf6d,color:#12331d
    classDef decision fill:#fff7e0,stroke:#d9a514,color:#4a3b07
    classDef adapt fill:#fdeaea,stroke:#d9534f,color:#4a1411
    class START input
    class CLAIM,FETCH,PARSE,UPSERT,NEWURLS,WAIT process
    class POLITE,BLOCKED decision
    class ADAPT adapt
```

## Upgrading from v2.0.0

Existing v2.0.0 databases upgrade automatically on first start. Startup now
reconciles legacy-shaped tables out of the way, applies the v2 baseline
atomically (no more half-applied schema), and migration 8 consolidates the
v1 quartet (`raw_records` + `analyses` + `lead_scores` + `resolved_entities`)
into unified `leads` — preserving CRM status, contact flags, tags, clusters,
attachments, and campaign history. Databases left half-migrated by the v3.0.0
startup crash are detected and completed. Nothing to run manually; back up
`data/leads.db` first if you want a safety net.

## Configuration

All operational parameters live in `config/settings.py` (env-overridable via
`.env`). Hardware-derived defaults (worker counts, concurrency, connection
pools) are computed from `os.cpu_count()` with sanity bounds — nothing is
hardcoded to a specific machine, and nothing is unbounded. Scoring weights
and entity-resolution thresholds are named domain constants in
`engine/scorer.py` / `engine/resolver.py`, not scattered magic numbers.

## Performance

Measured on the development host (2 cores, g++ 14.2, AVX-512 available) —
run `python cli.py bench` to reproduce:

| Path | v2 baseline | v3 native | Speedup |
|---|---|---|---|
| HTML extraction (11 KB page) | 418 pages/s (BS4+lxml) | 44,147 pages/s | **~106x** |
| Batch scoring (100k leads) | 1.15M/s (Python loop) | 3.43M/s | **~3.0x** |
| Entity resolution (4.4k leads) | 11.6k leads/s | 18.0k leads/s | **~1.55x** |
| URL dedup memory (1M URLs) | ~95 MB (Python set) | ~2 MB (blocked Bloom) | **~47x** |

Honest notes: raw per-pair Levenshtein is faster in rapidfuzz than in the
native session, so rapidfuzz remains the *fallback* implementation; the
native core wins where batch amortization and the prefilter cascade apply.
End-to-end throughput is network-bound by design — the CPU-bound stages are
now fast enough that the wire is the limit.

## Project layout

```
engine_native/     C++20 SIMD core (one shared library, plain g++ build)
engine/            Python engine: native bridge, analyzer, scorer, resolver,
                   acquisition (rate limiting, AIMD, streaming)
domain/            Unified Lead model, enums, value objects
infrastructure/    storage (schema v2, repos, legacy reconciliation), scrapers,
                   http, resilience
services/          discovery, crawler, export orchestration
api/               FastAPI routes + dashboard
config/            settings + static catalogs (58 wilayas, dialects, services)
utils/             phone validator, spam filter, freshness, query sanitiser
tests/             107 tests — no network, includes native/fallback parity
                   and the real-v2.0.0-database upgrade path
benchmarks/        reproducible benchmark suite
```
