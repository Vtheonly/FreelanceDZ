"""Session-state contract for the workspace.

Centralising every key in one module keeps widgets and callbacks from
reaching into each other's state ad hoc. Values fall back to documented
defaults on first run, and ``panel_enabled`` powers the dynamic grid.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

# Wilaya filter shared by map, leads, and checkpoints panels.
SELECTED_WILAYA = "selected_wilaya"          # None => nationwide
SELECTED_WILAYA_CODE = "selected_wilaya_code"

# Map interaction state (click-to-select / click-to-place).
MAP_LAST_CLICK = "map_last_click"            # (lat, lon) of last map click
MAP_CLICKED_WILAYA = "map_clicked_wilaya"    # lookup result for the click

# Leads matrix state.
LEAD_PAGE = "lead_page"                      # 0-based page index
SELECTED_LEAD_ID = "selected_lead_id"
LEAD_FILTERS = "lead_filters"                # dict of current filters

# Checkpoint creation flow (seeded from a map click).
CP_FORM = "cp_form_seed"                     # {lat, lon, wilaya} prefill

# Dynamic grid: which panels are visible.
GRID_PANELS = "grid_panels"

# Theme: "dark" | "light".
THEME = "theme"

DEFAULT_PANELS: dict[str, bool] = {
    "map": True,
    "checkpoints": True,
    "discovery": True,
    "leads": True,
    "diagnostics": True,
}


def init_state() -> None:
    """Idempotent session-state initialisation."""
    defaults: dict[str, Any] = {
        SELECTED_WILAYA: None,
        SELECTED_WILAYA_CODE: None,
        MAP_LAST_CLICK: None,
        MAP_CLICKED_WILAYA: None,
        LEAD_PAGE: 0,
        SELECTED_LEAD_ID: None,
        LEAD_FILTERS: {},
        CP_FORM: None,
        GRID_PANELS: dict(DEFAULT_PANELS),
        THEME: "dark",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def panel_enabled(panel: str) -> bool:
    return bool(st.session_state.get(GRID_PANELS, {}).get(panel, False))


def set_wilaya(name: str | None, code: int | None) -> None:
    """Selecting a wilaya resets pagination so leads re-anchor to page 1."""
    st.session_state[SELECTED_WILAYA] = name
    st.session_state[SELECTED_WILAYA_CODE] = code
    st.session_state[LEAD_PAGE] = 0


def seed_checkpoint_form(lat: float, lon: float, wilaya: str | None) -> None:
    st.session_state[CP_FORM] = {
        "lat": round(float(lat), 5),
        "lon": round(float(lon), 5),
        "wilaya": wilaya or "",
    }
