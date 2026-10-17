# 14 · Refactoring & Migration History

## Version timeline

| Version | Theme |
|---|---|
| v1 | first consolidation of four competing lead representations |
| v2.0.0 | rewrite that re-split them apart (raw_records + analyses + lead_scores + resolved_entities) |
| v3.0.0 | definitive unified engine: one `leads` table, streaming discovery, C++ "SIMD" core |
| v3.1.0 | evidence-based entity resolution: decision log, review queue, relations |
| **v4.0.0 (this refactor)** | refactorv4.md + refactorv5.md executed in full; Streamlit workspace; geographic intelligence; containerised services |

The raw engineering documents `refactorv4.md` and `refactorv5.md` were
consolidated into this ledger and retired from the repo root (they remain
in git history). Everything below was **verified against the actual
code before implementation** — the previous HEAD (481cc9b) contained none
of these fixes (its "fix the issues" commit added only documentation).

## refactorv4.md task ledger

| Task | Issue | Resolution | Evidence |
|---|---|---|---|
| 1 | queue visibility (`campaigns.length` on an object) | contract documented; the endpoint returns `{"campaigns": [...]}` and the new UI handles the object shape | `TestCampaignContract` |
| 2 | stats crash (`.filter` on dict) | backend keeps the documented dict shape; UI consumes it correctly | `test_stats_has_age_breakdown`, `metrics.py` |
| 3 | 404 on `/api/v2/tags` | alias route added | `TestTask3TagsAlias` |
| 4 | 422 on empty wilaya | validators split; blank → nationwide (`None`) | `TestTask4EmptyWilaya` |
| 5 | search dropped filters | `q` FTS composes with every filter in `/leads` + repo | `TestTask5UnifiedListing` |
| 6 | upsert race | native `ON CONFLICT … RETURNING` in `BEGIN IMMEDIATE` | `TestTask6AtomicUpsert` (50-way concurrent) |
| 7 | stored XSS | scheme allow-list at the Lead model boundary (normalise scheme-less, drop `javascript:`/`data:`) | `TestTask7UrlSanitisation` |
| 8 | OSM coupling | nationwide bbox fallback + silent per-scraper degradation | `TestTask8OverpassDecoupling` |
| 9 | unknown wilayas | `utils/geo_inference.py` (ARPT area codes + text mentions) wired into the DDG scraper | `test_geographic.py` (inference block) |
| 10 | map-absence penalty | opportunity factors (+15 website build, +10 local SEO); acceptance ≥60 | `TestTask10OpportunityScoring` |
| 11 | dialect multiplier bomb | `DISCOVERY_MAX_VARIANTS=2` + all (variant×scraper) streams in parallel | `TestTask11VariantCap` (concurrency proof) |
| 12 | junk results | Business Quality Gate: junk domains + non-business title tokens | `TestTask12QualityGate` |
| 13 | C++ SIMD theater | `engine/fastops.py`; `engine_native/` deleted | `test_fastops.py`, ADR-002 |
| 14 | shared backoff | per-domain `defaultdict(ExponentialBackoff)` | `TestTask14PerDomainBackoff` |
| 15 | WAL re-declaration | WAL once at init; `busy_timeout=5000` | `TestTask15WamlOnce` |
| §5.1 | DNS pre-caching | evaluated, rejected (keep-alive already amortises) — see [12-performance.md](12-performance.md) | documented |
| §5.2 | local SearXNG | optional scraper + compose profile, opt-in via `SEARXNG_URL` | `infrastructure/scrapers/searxng.py` |
| §5.3 | HEAD-first verification | streamed reads cut at 32 KiB | `crawler_service._fetch_bounded` |

## refactorv5.md step ledger

| Step | Resolution |
|---|---|
| S1 enriched catalogue | `config/wilayas.py`: centroids + ARPT area codes, Law 19-12 codes |
| S2 geo inference | same as v4 Task 9 |
| S3 Checkpoint model | `domain/models.Checkpoint` |
| S4 migration 10 + WAL fix | `database.py` |
| S5 CheckpointRepository | full CRUD + aggregations |
| S6 atomic upsert + unified search | same as v4 Tasks 5/6 |
| S7 quality gate | same as v4 Task 12 |
| S8 opportunity scoring | same as v4 Task 10 |
| S9 API updates | checkpoint + geo routers wired; T3/T4 fixes |
| S10 Streamlit UI | built as a **pure API client** (see conflict #2 below) |
| S11 discovery decoupling | same as v4 Tasks 8/11 |
| S12 per-domain backoff | same as v4 Task 14 |
| S13 CLI `ui` command | `python cli.py ui` |
| S14 dependencies | streamlit/streamlit-folium/folium/pandas in `requirements-ui.txt` |
| verification tests | `test_v4_refactor.py` + `test_geographic.py` + `test_ui.py` (superset of the sketched suite) |

## Conflicts between the documents, and how they were resolved

1. **Opportunity weights** — v4 Task 10 says +15/+10; v5 Step 8 says
   +10/+5. **Kept 15/10**: v4's own acceptance test (verified phone, no
   web, no map → ≥60) only passes with the higher weights.
2. **UI data access** — v5's `ui/app.py` sketch imported repositories
   directly, contradicting v5 §7 and the operator's requirement of a pure
   client. **Built the UI as an HTTP API client** (ADR-001).
3. **Map fidelity** — v5's sketch used centroid bubbles; the operator
   demanded real boundaries. **Real GeoJSON geometry** (ADR-005).
4. **Social platforms in the junk list** — v4 Task 12 lists
   facebook/instagram/tiktok as junk, but the codebase's enrichment
   design (and v4 Task 10's own philosophy) treats social-only businesses
   as the highest-value prospects. **Social profile pages stay allowed**;
   their feed/search paths are blocked by path patterns.
5. **is_new via `RETURNING (discovered_at = updated_at)`** (both docs'
   sketch) is unreliable — timestamps legitimately differ on fresh rows.
   **Existence probe inside the same BEGIN IMMEDIATE transaction**
   provides a snapshot-consistent created/merged flag.

## What was removed, and why

| Removed | Reason |
|---|---|
| `engine_native/` + `engine/native.py` | v4 Task 13 (ADR-002) |
| `api/templates/dashboard.html` + dashboard route + `ENABLE_DASHBOARD` + jinja2 dep | legacy UI fully migrated to the Streamlit workspace (feature-by-feature verification, then deletion) |
| `refactorv2/` (6 duplicated readme copies, ~355 KB) | orphaned history; preserved in git |
| `.smartexport/selection-state.json` | editor state accidentally committed |
| `refactorv4.md` / `refactorv5.md` from the root | consolidated into this ledger |
| `ARCHITECTURE.md` (root) | superseded by `docs/02-architecture.md` |

## Latent bugs found and fixed along the way

- `engine/resolution/scoring.py::score_all` referenced undefined `a`/`b`
  (NameError on call) — fixed to `pair[0]`/`pair[1]`; caught by the new
  ruff gate.
- The upstream boundary dataset used non-official codes for the ten
  post-2019 wilayas — re-mapped by name to Law 19-12 codes
  (`scripts/fetch_wilaya_boundaries.py`).
- `pyproject.toml` shipped an uninstallable dependency
  (`"httpxttp2]>=0.28.0"`) — fixed to `httpx[http2]`.
