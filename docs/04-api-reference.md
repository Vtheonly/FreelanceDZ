# 04 · API Reference

Base URL: `http://localhost:8080` (engine service). All payloads are JSON.
Interactive OpenAPI docs: `http://localhost:8080/docs`.

Conventions:
- Errors use appropriate status codes with a `{"detail": "..."}` body;
  the UI surfaces `detail` verbatim.
- List endpoints paginate with `limit` (max 500) + `offset` and return
  `{"count": n, "<resource>": [...]}`.
- Empty optional filters mean "not filtered"; an empty `wilaya` string is
  normalised to *nationwide*, never a 422 (v4 Task 4).

## Health

| Method | Path | Notes |
|---|---|---|
| GET | `/health?full=false` | metadata-only probe (~1 ms). `full=true` runs the slow integrity check off the event loop |

## Leads

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v2/leads` | unified listing: `q` (FTS) composes with `wilaya`, `industry`, `status`, `is_contact`, `tag`, `age_class`, `min_score`, `sort_by`, `sort_order`, `limit`, `offset` (v4 Task 5) |
| GET | `/api/v2/leads/search?q=&limit=` | FTS search endpoint (legacy shape) |
| GET | `/search/autocomplete?q=` | vocabulary suggestions |
| GET | `/api/v2/leads/tags` | all tags (also aliased at `/api/v2/tags`, v4 Task 3) |
| POST | `/api/v2/leads/manual` | manual lead creation (website scheme sanitised at the model boundary) |
| POST | `/api/v2/leads/analyze-pending?limit=` | deterministic audit + score for unanalyzed leads |
| POST | `/api/v2/leads/score-all?limit=` | score leads with zero priority |
| POST | `/api/v2/leads/bulk-contact` / `bulk-status` | bulk CRM (`lead_ids`, value) |
| GET | `/api/v2/leads/{id}` | full detail (audit, gaps, services, CTAs, breakdown) |
| POST | `/api/v2/leads/{id}/analyze` | re-audit + re-score (CRM status preserved) |
| POST | `/api/v2/leads/{id}/edit` | field edit |
| POST | `/api/v2/leads/{id}/contact` | `{"is_contact": bool}` (status-preserving policy) |
| POST | `/api/v2/leads/{id}/status` | `{"status": "discovered\|analyzed\|scored\|contacted\|verified\|rejected"}` |
| POST | `/api/v2/leads/{id}/tags` | `{"tags": [...]}` |
| POST | `/api/v2/leads/{id}/attachments` | multipart upload (≤10 MiB) |
| GET | `/api/v2/leads/{id}/attachments` | attachment metadata |
| GET/DELETE | `/api/v2/attachments/{id}` | download / delete |

## Discovery & campaigns

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v2/discover` | `{query, wilaya?, limit, background}` — `background=true` returns immediately and processes in the background; response: campaign report with `saved_count` / `merged_count` |
| GET | `/api/v2/discover/campaigns?limit=` | `{"campaigns": [...]}` (object-with-array contract, v4 Task 1) |

## Entities (resolution)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v2/entities/stats` | totals + pending review |
| POST | `/api/v2/entities/resolve` | full batch resolution |
| GET | `/api/v2/entities` | filter by `wilaya`, `industry`, `min_confidence`, paginated |
| GET | `/api/v2/entities/{id}` / `lineage` / `evidence` / `relations` | canonical record, members, decision log, related entities |
| POST | `/api/v2/entities/{id}/split` | partition members into separate entities (pinned) |
| POST | `/api/v2/entities/merge` | merge confirmed duplicates (pinned) |
| GET | `/api/v2/entities/review` | ambiguous pairs queue |
| POST | `/api/v2/entities/review/{id}/resolve` | `merge \| keep_separate \| dismiss` |

## Geographic intelligence

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v2/geo/wilayas` | 58-wilaya catalogue with live `leads_count` / `checkpoints_count` and geometry-derived centroids |
| GET | `/api/v2/geo/boundaries` | WGS84 GeoJSON FeatureCollection, 58 features (~113 KB) — immutable per dataset version; cache client-side |
| POST | `/api/v2/geo/lookup` | `{latitude, longitude}` → wilaya via point-in-polygon; near-miss coast points return the nearest wilaya with `approximate: true` |
| GET | `/api/v2/geo/overview` | country-level summary (geolocated leads, checkpoints, bbox) |

## Checkpoints (POIs)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v2/checkpoints` | filter by `wilaya`, `category`, `status` |
| POST | `/api/v2/checkpoints` | `{name, category, latitude, longitude, wilaya?, notes?, status?}` — wilaya is derived from the real boundary geometry when omitted; a caller-supplied mismatching wilaya is **422** |
| GET/PATCH/DELETE | `/api/v2/checkpoints/{id}` | inspect / partial update (moving re-derives wilaya) / delete |

Categories: `prospect | client | partner | hub | competitor`.
Statuses: `active | visited | archived`.

## Crawler & exports

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v2/crawler/start` | `{queries: [...], wilaya?}` |
| POST | `/api/v2/crawler/stop` | graceful stop |
| GET | `/api/v2/crawler/status` | live stats |
| GET | `/api/v2/export/leads/csv?limit=` / `leads/json` / `entities/json` | file downloads |

## Rate & timeout guidance for clients

- Read endpoints are millisecond-scale; `/geo/boundaries` (~27 ms) is the
  one heavyweight — fetch once, cache, refetch only on dataset version
  change.
- `/discover` with `background=false` can run minutes (network-bound);
  prefer `background=true` + campaign polling.
