# 07 · Streamlit UI Architecture

`ui/` is a complete replacement for the legacy Jinja2 dashboard: a
modern, minimalist, information-dense workspace and a **pure API client**
of the engine.

## Module map

```
ui/
  app.py               entry point: grid composition, sidebar, theme
  api_client.py        EngineClient (httpx) + TTL-cached reads + mutations
  state.py             session-state contract (single source for keys)
  theme.py             design tokens (dark/light) + panel chrome
  components/
    metrics.py         KPI ribbon
    algeria_map.py     interactive map (isolated behind a stable interface)
    leads_table.py     filters + paginated table + bulk ops + exports
    lead_detail.py     inspector: audit, CRM actions, attachments, editing
    checkpoints.py     POI manager
    discovery.py       campaign launcher + queue
    diagnostics.py     health/latency, crawler control, data quality
```

## The dynamic grid

Panels are registry-driven and independently toggleable (sidebar →
"Grid panels"): map hub, wilaya inspector, checkpoints, discovery +
engine operations, leads matrix + inspector, diagnostics. Layout state
lives in `st.session_state`; the wilaya filter is shared state that
re-anchors map, leads, and checkpoints together (map click →
`state.set_wilaya` → every panel re-scopes).

## Interactive map (the custom component)

- **Renderer**: `streamlit-folium` + Folium/Leaflet — chosen after
  evaluating Plotly (choropleth traces expose no click/selection events
  in Streamlit) and hand-rolled bidirectional components (unnecessary
  complexity for a solved problem). The component is isolated inside
  `components/algeria_map.py`; the rest of the app never touches folium.
- **Boundaries**: the engine's `/api/v2/geo/boundaries` GeoJSON (real
  geometry — 58 selectable polygons, not an image and not centroid
  bubbles).
- **Interaction**: `return_on_click=True` where the installed
  streamlit-folium supports it (>= 0.21; on older installs the kwarg is
  omitted — clicks still return `last_clicked` and trigger a rerun, so
  selection keeps working). The click resolves to a wilaya through the
  **engine's** `/api/v2/geo/lookup` (geographic logic stays
  server-side) — selecting the wilaya filters the whole workspace and
  seeds the checkpoint form with the clicked coordinates
  ("place a POI here").
- **Layers**: boundaries + category-coloured checkpoint markers +
  geolocated-lead dots, with layer control; tooltips join live counts.
- **Theming**: tiles switch CartoDB dark/positron with the app theme;
  when tiles are unreachable (offline), polygons and markers still render.
- **Fallback**: headless/component-less environments degrade to a data
  table instead of crashing (exercised by the AppTest suite).

## Performance contract (rerun economy)

Streamlit reruns the script on every interaction, so the client is
engineered around it:
- `st.cache_resource` — one `httpx.Client` per process (connection
  pooling).
- `st.cache_data` with per-endpoint TTLs (stats/leads 10 s, campaigns
  5 s, catalogue 30 s, boundaries 1 h — immutable per dataset version);
  mutations invalidate exactly the affected caches.
- No engine data is recomputed client-side; the boundaries payload is
  fetched once.

## Error & state model

- Engine down → top-level error banner, no panels crash.
- Per-panel failures → inline `st.error` with the API's `detail`.
- Empty states explain the next action ("launch a discovery campaign…").
- Mutations surface toasts; 422s render the engine's rejection reason.
  Toast icons must be single valid emoji — text glyphs like `✓`/`■`
  make Streamlit raise `StreamlitAPIException` at render time; every
  `icon="…"` literal in `ui/` is scanned and validated by
  `tests/test_ui.py::test_icon_literals_are_valid_emoji`.

## Testing

`tests/test_ui.py` runs the real `ui/app.py` under Streamlit's AppTest
against an **in-process uvicorn engine** with a seeded database — genuine
frontend-to-backend integration without mocks, plus an explicit
unreachable-engine error-state test.
