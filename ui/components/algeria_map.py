"""Interactive map of Algeria — real boundaries, genuine interaction.

Architecture (isolated behind this module per refactorv5 §3):

    * geometry: the engine's versioned 58-wilaya boundary GeoJSON
      (/api/v2/geo/boundaries), rendered as a selectable Folium layer;
    * selection: a map click resolves to a wilaya through the ENGINE's
      point-in-polygon endpoint (/api/v2/geo/lookup) — geographic logic
      stays server-side, the UI never reimplements it;
    * layers: checkpoints (category-coloured markers) and geolocated leads
      (compact dots) overlay the boundaries, with layer control;
    * placement: a click also seeds the checkpoint form (place a POI at the
      clicked coordinates);
    * fallback: if the map component cannot render (no browser/component
      host), the panel degrades to a data table instead of crashing.

Tiles: CartoDB dark/positron match the app theme. When tiles are
unreachable (offline), the GeoJSON polygons and markers still render —
the map remains functional without external map services.
"""

from __future__ import annotations

from typing import Any, Optional

import streamlit as st

from ui import state
from ui.api_client import (
    EngineError,
    EngineUnavailable,
    fetch_boundaries,
    fetch_checkpoints,
    fetch_leads,
    geo_lookup,
)
from ui.theme import badge, tokens

CHECKPOINT_CATEGORY_COLORS = {
    "prospect": "#38bdf8",
    "client": "#34d399",
    "partner": "#a78bfa",
    "hub": "#fbbf24",
    "competitor": "#fb7185",
}

_ALGERIA_FIT = [[18.9, -8.7], [37.1, 12.0]]


def _style_for(t: dict[str, str]):
    def style(feature: dict[str, Any]) -> dict[str, Any]:
        props = feature["properties"]
        selected = (
            state.st.session_state.get(state.SELECTED_WILAYA_CODE) is not None
            and props.get("code") == state.st.session_state[state.SELECTED_WILAYA_CODE]
        )
        if selected:
            return {
                "fillColor": t["accent"],
                "color": "#ffffff",
                "weight": 2.2,
                "fillOpacity": 0.45,
            }
        return {
            "fillColor": t["accent"],
            "color": t["panel_border"],
            "weight": 0.8,
            "fillOpacity": 0.10,
        }

    return style


def _highlight_for(t: dict[str, str]):
    def highlight(feature: dict[str, Any]) -> dict[str, Any]:
        return {
            "fillColor": t["accent"],
            "color": t["accent"],
            "weight": 1.8,
            "fillOpacity": 0.30,
        }

    return highlight


def _wilaya_tooltip(feature: dict[str, Any]) -> str:
    props = feature["properties"]
    return (
        f"<b>{props.get('code', '?')}. {props.get('name_fr', '?')} "
        f"({props.get('name_ar', '')})</b>"
    )


def render_map(height: int = 540) -> None:
    """Render the interactive map panel and process click interactions."""
    t = tokens()
    try:
        boundaries = fetch_boundaries()
        wilaya_rows = st.session_state.get("_wilaya_rows_cache") or []
    except (EngineUnavailable, EngineError) as exc:
        st.error(f"Boundary data unavailable: {exc}")
        return

    try:
        checkpoints = fetch_checkpoints(limit=2000).get("checkpoints", [])
    except (EngineUnavailable, EngineError):
        checkpoints = []

    try:
        selected_wilaya_name = st.session_state.get(state.SELECTED_WILAYA)
        leads_payload = fetch_leads(
            wilaya=selected_wilaya_name, limit=300, sort_by="priority_score"
        )
        leads = leads_payload.get("leads", [])
    except (EngineUnavailable, EngineError):
        leads = []

    geo_data = _enrich_boundaries(boundaries, wilaya_rows)

    try:
        import folium
        from streamlit_folium import st_folium
    except ImportError:  # pragma: no cover — dependency guard
        st.warning(
            "Map components (folium / streamlit-folium) are not installed — "
            "showing the wilaya table instead."
        )
        _fallback_table(wilaya_rows)
        return

    m = folium.Map(
        location=[28.0, 2.65],
        zoom_start=5,
        tiles=t["tiles"],
        attr="© OpenStreetMap contributors © CARTO",
    )
    m.fit_bounds(_ALGERIA_FIT)

    folium.GeoJson(
        geo_data,
        style_function=_style_for(t),
        highlight_function=_highlight_for(t),
        tooltip=folium.GeoJsonTooltip(
            fields=["code", "name_fr", "name_ar"],
            aliases=["#", "Wilaya", "ولاية"],
            style=(
                "font-family: Inter, sans-serif; font-size: 12px; "
                "background: #11141d; color: #e7ecf3; border: 1px solid #1e2433;"
            ),
        ),
    ).add_to(m)

    # Checkpoint markers (category-coloured).
    cp_layer = folium.FeatureGroup(name="Checkpoints", show=True)
    for cp in checkpoints:
        color = CHECKPOINT_CATEGORY_COLORS.get(cp.get("category", "prospect"), "#38bdf8")
        folium.CircleMarker(
            location=[cp["latitude"], cp["longitude"]],
            radius=7,
            color="#0b0e14",
            weight=1.2,
            fill=True,
            fill_color=color,
            fill_opacity=0.95,
            tooltip=(
                f"<b>{cp['name']}</b><br>{cp.get('category', '').upper()} · "
                f"{cp.get('wilaya', '—')}<br>{cp.get('status', '')}"
            ),
        ).add_to(cp_layer)
    cp_layer.add_to(m)

    # Geolocated leads as compact dots.
    lead_layer = folium.FeatureGroup(name="Leads (GPS)", show=True)
    for lead in leads:
        lat, lon = lead.get("latitude"), lead.get("longitude")
        if lat is None or lon is None:
            continue
        folium.CircleMarker(
            location=[lat, lon],
            radius=3.5,
            color="#34d399",
            weight=0.6,
            fill=True,
            fill_color="#34d399",
            fill_opacity=0.8,
            tooltip=(
                f"<b>{lead['name']}</b><br>Score {lead.get('priority_score', 0):.0f}/100"
                f"<br>{lead.get('wilaya') or '—'}"
            ),
        ).add_to(lead_layer)
    lead_layer.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    try:
        output = st_folium(
            m,
            height=height,
            use_container_width=True,
            return_on_click=True,
            key="algeria_map",
        )
    except Exception as exc:  # component host unavailable (headless/test)
        st.info(f"Map rendering unavailable in this environment ({exc}).")
        _fallback_table(wilaya_rows)
        return

    _handle_click(output)


def _handle_click(output: Optional[dict[str, Any]]) -> None:
    """Resolve the last map click: select the wilaya + seed a checkpoint."""
    if not output:
        return
    clicked = output.get("last_object_clicked") or output.get("last_clicked")
    if not clicked:
        return
    try:
        lat, lon = float(clicked[0]), float(clicked[1])
    except (TypeError, ValueError, IndexError):
        return

    if st.session_state.get(state.MAP_LAST_CLICK) == (lat, lon):
        return  # same click already processed (rerun echo)
    st.session_state[state.MAP_LAST_CLICK] = (lat, lon)

    try:
        result = geo_lookup(lat, lon)
    except (EngineUnavailable, EngineError):
        st.toast("Could not resolve the clicked coordinates.", icon="⚠️")
        return

    st.session_state[state.MAP_CLICKED_WILAYA] = result
    wilaya = result.get("wilaya")
    if wilaya:
        if result.get("found") and not result.get("approximate"):
            state.set_wilaya(wilaya["name_fr"], wilaya["code"])
            st.toast(f"Selected wilaya: {wilaya['name_fr']}", icon="🗺️")
        else:
            st.toast(
                f"Near {wilaya['name_fr']} (outside exact boundary)", icon="📍"
            )
        state.seed_checkpoint_form(lat, lon, wilaya.get("name_fr"))


def _enrich_boundaries(
    boundaries: dict[str, Any], wilaya_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Join live counts onto boundary features for tooltips."""
    counts = {
        int(w["code"]): (w.get("leads_count", 0), w.get("checkpoints_count", 0))
        for w in wilaya_rows
    }
    features = []
    for feature in boundaries.get("features", []):
        props = dict(feature.get("properties", {}))
        leads_n, cps_n = counts.get(int(props.get("code", 0)), (0, 0))
        props["leads_n"] = leads_n
        props["checkpoints_n"] = cps_n
        features.append({**feature, "properties": props})
    return {**boundaries, "features": features}


def _fallback_table(wilaya_rows: list[dict[str, Any]]) -> None:
    """No-map fallback: the geographic data still inspects as a table."""
    import pandas as pd

    if not wilaya_rows:
        st.caption("No wilaya data available.")
        return
    df = pd.DataFrame(
        [
            {
                "code": w["code"],
                "wilaya": w["name_fr"],
                "name_ar": w["name_ar"],
                "leads": w.get("leads_count", 0),
                "checkpoints": w.get("checkpoints_count", 0),
                "area_code": w.get("area_code", ""),
            }
            for w in wilaya_rows
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True, height=420)


def render_wilaya_inspector() -> None:
    """Detail panel for the currently selected wilaya."""
    rows = st.session_state.get("_wilaya_rows_cache") or []
    name = st.session_state.get(state.SELECTED_WILAYA)
    if not name:
        st.caption("Click a wilaya on the map (or choose one in the sidebar) to inspect it.")
        return

    row = next((w for w in rows if w.get("name_fr") == name), None)
    if row is None:
        st.caption(f"WILAYA · {name}")
        return

    st.markdown(
        f"""
        <div style="font-size:13px; line-height:1.75;">
        <div style="font-size:16px; font-weight:700;">{row['code']:02d} · {row['name_fr']}
        <span style="color:{tokens()['muted']}; font-weight:500;">&nbsp;{row['name_ar']}</span></div>
        <table style="width:100%; font-size:12px; color:{tokens()['muted']};">
        <tr><td>Leads</td><td style="color:{tokens()['accent']}; font-family:JetBrains Mono; text-align:right;">{row.get('leads_count', 0)}</td></tr>
        <tr><td>Checkpoints</td><td style="color:{tokens()['violet']}; font-family:JetBrains Mono; text-align:right;">{row.get('checkpoints_count', 0)}</td></tr>
        <tr><td>Landline area code</td><td style="font-family:JetBrains Mono; text-align:right;">{row.get('area_code', '—')}</td></tr>
        <tr><td>Centroid</td><td style="font-family:JetBrains Mono; text-align:right;">{row.get('lat', 0):.3f}, {row.get('lon', 0):.3f}</td></tr>
        </table></div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(badge("filters leads + checkpoints", "mono"), unsafe_allow_html=True)
