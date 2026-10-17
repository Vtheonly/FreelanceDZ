# ADR-003 · streamlit-folium for the interactive Algeria map

**Status**: accepted (v4 refactor)
**Context**: The map must use REAL boundary geometry with click-to-select
wilayas, markers, and checkpoint placement. Plotly choropleth renders
boundaries beautifully but its traces expose no click/selection events in
Streamlit (`st.plotly_chart(on_select=...)` supports scatter-like traces,
not choropleth). A hand-rolled bidirectional custom component would mean
maintaining a React build for a solved problem. refactorv5's sketch used
centroid bubbles, which the operator explicitly rejected ("do not
approximate the country's borders").
**Decision**: streamlit-folium (maintained community component) over
Leaflet/Folium: GeoJSON boundary layer from the engine, `return_on_click`
for click handling, marker layers per data class, layer control, dark/
light tiles — isolated entirely inside `ui/components/algeria_map.py`.
**Consequences**: one extra UI-only dependency (not in the engine image);
clicks resolve to wilayas via the ENGINE's `/geo/lookup` (logic stays
server-side); tiles are decorative — offline the polygons still render; a
no-component fallback table keeps headless/test environments functional.
