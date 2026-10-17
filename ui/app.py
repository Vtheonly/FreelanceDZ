"""FreelanceDZ — modern sourcing & geospatial intelligence workspace.

Complete replacement for the legacy dashboard: a dynamic-grid Streamlit
client over the engine API. Layout: KPI ribbon, then configurable panels
(map + wilaya inspector, checkpoints, discovery, leads matrix + lead
inspector, diagnostics) arranged in an information-dense grid. Every
interaction goes through the engine's HTTP API (no mock data, no direct
database access, no duplicated business logic).

Run: streamlit run ui/app.py   (or: python cli.py ui)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from ui import state  # noqa: E402
from ui.api_client import (  # noqa: E402
    EngineError,
    EngineUnavailable,
    analyze_pending,
    fetch_wilayas,
    resolve_entities,
)
from ui.components import algeria_map, checkpoints, diagnostics, discovery, lead_detail, leads_table, metrics  # noqa: E402
from ui.theme import apply, badge, tokens  # noqa: E402

st.set_page_config(
    page_title="FreelanceDZ · Geospatial Workspace",
    page_icon="🇩🇿",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    state.init_state()
    apply()

    _render_sidebar()

    # Health banner: unmistakable when the engine is down, invisible when up.
    if not _engine_reachable():
        st.error(
            "The FreelanceDZ engine is unreachable — panels will show empty "
            "states until it responds. Start it with `python cli.py serve` "
            "(or `docker compose up engine`)."
        )
        return

    # ------------------------------------------------------------------
    # KPI ribbon (row 0)
    # ------------------------------------------------------------------
    metrics.render_metrics_ribbon()

    st.markdown("---")

    # ------------------------------------------------------------------
    # Grid row 1: interactive map + wilaya inspector + checkpoints
    # ------------------------------------------------------------------
    if state.panel_enabled("map") or state.panel_enabled("checkpoints"):
        col_map, col_side = st.columns([8, 4])

        with col_map:
            if state.panel_enabled("map"):
                _panel("🗺️ Interactive map · 58 wilayas", _scope_badge())
                algeria_map.render_map()

        with col_side:
            if state.panel_enabled("map"):
                _panel("Wilaya inspector", "")
                algeria_map.render_wilaya_inspector()
            if state.panel_enabled("checkpoints"):
                _panel("📍 Field checkpoints", _cp_scope_badge())
                checkpoints.render_checkpoints_panel()

    # ------------------------------------------------------------------
    # Grid row 2: discovery + queue
    # ------------------------------------------------------------------
    if state.panel_enabled("discovery"):
        st.markdown("---")
        col_disc, col_q = st.columns([5, 4])
        with col_disc:
            _panel("⚡ Discovery engine", _scope_badge())
            discovery.render_discovery_panel()
        with col_q:
            _panel("Engine operations", "")
            _engine_operations()

    # ------------------------------------------------------------------
    # Grid row 3: leads matrix + inspector
    # ------------------------------------------------------------------
    if state.panel_enabled("leads"):
        st.markdown("---")
        col_table, col_detail = st.columns([7, 5])
        with col_table:
            _panel("🎯 Leads matrix", _scope_badge())
            leads_table.render_leads_matrix()
        with col_detail:
            _panel("🔎 Lead inspector", "")
            lead_detail.render_lead_inspector()

    # ------------------------------------------------------------------
    # Grid row 4: diagnostics
    # ------------------------------------------------------------------
    if state.panel_enabled("diagnostics"):
        st.markdown("---")
        _panel("🩺 Engine diagnostics", "")
        diagnostics.render_diagnostics_panel()

    st.markdown(
        f'<div style="margin-top:18px; font-size:10.5px; color:{tokens()["muted"]};">'
        f"FreelanceDZ workspace · engine API client · "
        f"boundaries © OpenStreetMap contributors (ODbL)</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
def _panel(title: str, right_html: str) -> None:
    from ui.theme import panel_header

    st.markdown(panel_header(title, right_html), unsafe_allow_html=True)


def _scope_badge() -> str:
    wilaya = st.session_state.get(state.SELECTED_WILAYA)
    return badge(wilaya or "NATIONWIDE", "info" if wilaya else "mono")


def _cp_scope_badge() -> str:
    wilaya = st.session_state.get(state.SELECTED_WILAYA)
    return badge(wilaya or "all checkpoints", "mono")


def _engine_reachable() -> bool:
    try:
        from ui.api_client import fetch_health

        fetch_health()
        return True
    except (EngineUnavailable, EngineError):
        return False


def _engine_operations() -> None:
    st.caption("Deterministic engine operations — same services the API exposes.")
    op_cols = st.columns(2)
    with op_cols[0]:
        if st.button("Run entity resolution", use_container_width=True):
            try:
                with st.spinner("Resolving entities…"):
                    report = resolve_entities()
                st.toast(
                    f"{report.get('output_count', 0)} entities · "
                    f"{report.get('compression_ratio', 0)}x compression",
                    icon="✓",
                )
                st.rerun()
            except (EngineUnavailable, EngineError) as exc:
                st.error(str(exc))
    with op_cols[1]:
        if st.button("Analyze pending leads", use_container_width=True):
            try:
                with st.spinner("Auditing pending leads…"):
                    result = analyze_pending(limit=100)
                st.toast(f"Analyzed {result.get('analyzed', 0)} leads", icon="⚡")
                st.rerun()
            except (EngineUnavailable, EngineError) as exc:
                st.error(str(exc))


def _render_sidebar() -> None:
    with st.sidebar:
        t = tokens()
        st.markdown(
            f'<div class="sidebar-brand">FreelanceDZ <small>· geospatial workspace</small></div>',
            unsafe_allow_html=True,
        )
        st.caption("B2B sourcing intelligence for Algeria · 58 wilayas")

        # Theme toggle.
        theme_col1, theme_col2 = st.columns([3, 2])
        with theme_col2:
            if st.button("🌗" if st.session_state[state.THEME] == "dark" else "☀️",
                         use_container_width=True):
                st.session_state[state.THEME] = (
                    "light" if st.session_state[state.THEME] == "dark" else "dark"
                )
                st.rerun()

        st.markdown("---")

        # Wilaya selection: type-to-search over the engine catalogue.
        try:
            wilaya_rows = fetch_wilayas()
            st.session_state["_wilaya_rows_cache"] = wilaya_rows
        except (EngineUnavailable, EngineError):
            wilaya_rows = st.session_state.get("_wilaya_rows_cache") or []

        if wilaya_rows:
            names = ["Nationwide — all wilayas"] + [w["name_fr"] for w in wilaya_rows]
            current = st.session_state.get(state.SELECTED_WILAYA)
            index = 0
            if current:
                try:
                    index = names.index(current)
                except ValueError:
                    index = 0
            choice = st.selectbox(
                "Active wilaya filter",
                names,
                index=index,
                help="Filters the map, leads matrix, and checkpoints together. "
                "Clicking a wilaya on the map selects it too.",
            )
            if choice.startswith("Nationwide"):
                if st.session_state.get(state.SELECTED_WILAYA) is not None:
                    state.set_wilaya(None, None)
            else:
                row = next((w for w in wilaya_rows if w["name_fr"] == choice), None)
                if row and choice != st.session_state.get(state.SELECTED_WILAYA):
                    state.set_wilaya(row["name_fr"], row["code"])
        else:
            st.caption("Wilaya catalogue unavailable (engine offline).")

        st.markdown("---")

        # Dynamic grid configuration.
        st.markdown("**Grid panels**")
        grid = st.session_state[state.GRID_PANELS]
        labels = {
            "map": "Geospatial map hub",
            "checkpoints": "Field checkpoints",
            "discovery": "Discovery + operations",
            "leads": "Leads matrix + inspector",
            "diagnostics": "Engine diagnostics",
        }
        for key, label in labels.items():
            grid[key] = st.checkbox(label, value=grid.get(key, True), key=f"panel_{key}")

        st.markdown("---")
        st.caption(
            "Every panel reads and writes through the engine's HTTP API — "
            "the same interface any other client uses."
        )


if __name__ == "__main__":
    main()
