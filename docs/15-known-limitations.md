# 15 · Known Limitations & Remaining Issues

## Verified limitations

1. **Docker images were not runtime-tested in the sandbox** used for this
   refactor (no Docker daemon available). The compose file and both
   Dockerfiles are structurally validated (YAML, dependency split,
   healthcheck wiring) and mirror the locally-verified process model —
   run `docker compose config && docker compose build` on your machine
   before relying on them. This is the one item on the definition-of-done
   list that could not be executed here.
2. **SearXNG integration is opt-in and untested against a live instance**
   (the scraper follows the documented JSON API; no local instance was
   available in the sandbox). Enable via `SEARXNG_URL` + the compose
   profile.
3. **UI tests cannot drive the folium component headlessly** — Leaflet
   interactions are browser-only. Coverage compensates by asserting the
   boundary/catalogue payloads the map consumes and exercising the map's
   no-component fallback path; the click→lookup→selection chain is
   covered at the API level (`/geo/lookup` tests).
4. **Single-writer SQLite** bounds write throughput (~900 upserts/s
   measured). Fine for personal/team scale; not a multi-tenant service.
5. **Overpass nationwide queries** return a bounded sample (60 features)
   by design — per-wilaya campaigns remain the thorough path.
6. **The crawler's 32 KiB read cap** means pages whose identity signals
   load late in the DOM (heavy JS shells) may extract less than a full
   download would; the BeautifulSoup deep-profile fallback still runs for
   no-signal pages.
7. **Map tiles are external** (CartoDB/OSM). Offline, the polygons and
   markers render on a plain background — functionality is preserved but
   the basemap is absent.
8. **Checkpoint wilaya for offshore points** is assigned by
   nearest-wilaya (marked `approximate` in lookups) — correct for ports,
   approximate by definition for open sea.

## Deliberately deferred

- Streaming/SSE progress for foreground discovery campaigns (the
  background mode + campaign polling covers the UX need today).
- Entity-resolution review UI in the workspace (the API is complete;
  the panel is a straightforward follow-up).
- A second export format family (Excel/Parquet) — CSV/JSON are wired.
- Session-persistent grid layout beyond `st.session_state` (per-session
  today; a localStorage hook is a small addition if wanted).

## Compatibility notes

- Databases from v2/v3 upgrade automatically (migrations 8–10; the
  legacy-shape reconciliation pre-pass handles pre-v3.0.1 files).
- The legacy dashboard is gone; its API surface (all `/api/v2/*` routes)
  is unchanged or extended — external scripts keep working.
- `requirements.txt` no longer installs Streamlit; UI development
  installs `requirements-ui.txt` too.
