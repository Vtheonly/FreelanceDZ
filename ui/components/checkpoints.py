"""Checkpoint manager — create, inspect, edit, and retire field POIs.

Creation is seeded from map clicks (exact coordinates + engine-derived
wilaya) or typed manually; the wilaya is validated server-side against
the real boundary geometry (mismatch -> 422 shown inline). Edits change
status/category/notes through PATCH; deletion asks for confirmation.
"""

from __future__ import annotations

from typing import Any, Optional

import streamlit as st

from ui import state
from ui.api_client import (
    EngineError,
    EngineUnavailable,
    create_checkpoint,
    delete_checkpoint,
    fetch_checkpoints,
    update_checkpoint,
)
from ui.theme import badge

CATEGORIES = ["prospect", "client", "partner", "hub", "competitor"]
STATUSES = ["active", "visited", "archived"]


def render_checkpoints_panel() -> None:
    wilaya = st.session_state.get(state.SELECTED_WILAYA)
    try:
        payload = fetch_checkpoints(wilaya=wilaya, limit=500)
    except (EngineUnavailable, EngineError) as exc:
        st.error(f"Checkpoints unavailable: {exc}")
        return
    checkpoints = payload.get("checkpoints", [])

    tab_list, tab_create = st.tabs([f"Checkpoints ({len(checkpoints)})", "+ Place checkpoint"])

    with tab_create:
        _render_create_form(checkpoints)

    with tab_list:
        if not checkpoints:
            scope = f" in {wilaya}" if wilaya else ""
            st.info(
                f"No checkpoints{scope}. Click anywhere on the map (or use the "
                "form) to place the first point of interest."
            )
        else:
            _render_checkpoint_list(checkpoints)


def _render_create_form(checkpoints: list[dict[str, Any]]) -> None:
    seed: Optional[dict[str, Any]] = st.session_state.get(state.CP_FORM)
    st.caption(
        "Click the map to pre-fill coordinates — the wilaya is derived from "
        "the official boundary geometry by the engine."
    )
    with st.form("create_checkpoint", clear_on_submit=True):
        name = st.text_input("Name *", placeholder="e.g. Alger Port Logistics Hub")

        cat_col, status_col = st.columns(2)
        with cat_col:
            category = st.selectbox("Category", CATEGORIES, index=0)
        with status_col:
            status = st.selectbox("Status", STATUSES, index=0)

        lat_col, lon_col = st.columns(2)
        with lat_col:
            latitude = st.number_input(
                "Latitude", value=float(seed["lat"]) if seed else 36.7538,
                min_value=18.0, max_value=38.0, format="%.5f",
            )
        with lon_col:
            longitude = st.number_input(
                "Longitude", value=float(seed["lon"]) if seed else 3.0588,
                min_value=-9.5, max_value=12.5, format="%.5f",
            )
        notes = st.text_area("Notes", placeholder="Visit scheduled, contact on site…", height=70)

        submitted = st.form_submit_button("Save checkpoint", use_container_width=True, type="primary")

    if submitted:
        if not name.strip():
            st.error("A name is required.")
        else:
            payload = {
                "name": name.strip(),
                "category": category,
                "latitude": float(latitude),
                "longitude": float(longitude),
                "notes": notes.strip() or None,
                "status": status,
            }
            try:
                result = create_checkpoint(payload)
                st.session_state[state.CP_FORM] = None
                st.toast(
                    f"Checkpoint '{name.strip()}' saved "
                    f"(wilaya {result.get('wilaya') or '—'})",
                    icon="📍",
                )
                st.rerun()
            except EngineError as exc:
                st.error(f"Rejected by the engine ({exc.status}): {exc.detail}")
            except (EngineUnavailable, EngineError) as exc:
                st.error(str(exc))


def _render_checkpoint_list(checkpoints: list[dict[str, Any]]) -> None:
    for cp in checkpoints:
        color = {
            "prospect": "info", "client": "ok", "partner": "warn",
            "hub": "warn", "competitor": "bad",
        }.get(cp.get("category", "prospect"), "mono")
        header = (
            f"<b>{cp['name']}</b> &nbsp;{badge(cp.get('category', ''), color)}"
            f"&nbsp;{badge(cp.get('status', ''), 'mono')}"
        )
        with st.expander(header):
            st.caption(
                f"{cp.get('wilaya') or '—'} · "
                f"{cp['latitude']:.4f}, {cp['longitude']:.4f} · "
                f"updated {str(cp.get('updated_at', ''))[:19]}"
            )
            if cp.get("notes"):
                st.caption(f"📝 {cp['notes']}")

            edit_col, delete_col = st.columns([3, 1])
            with edit_col:
                new_status = st.selectbox(
                    "status", STATUSES, index=STATUSES.index(cp.get("status", "active")),
                    key=f"cp_status_{cp['id']}",
                )
                new_category = st.selectbox(
                    "category", CATEGORIES, index=CATEGORIES.index(cp.get("category", "prospect")),
                    key=f"cp_cat_{cp['id']}",
                )
                if new_status != cp.get("status") or new_category != cp.get("category"):
                    try:
                        update_checkpoint(cp["id"], {"status": new_status, "category": new_category})
                        st.toast(f"{cp['name']} updated", icon="✓")
                        st.rerun()
                    except (EngineUnavailable, EngineError) as exc:
                        st.error(str(exc))
            with delete_col:
                st.markdown(
                    '<div style="height:24px"></div>', unsafe_allow_html=True
                )
                if st.button("Delete", key=f"cp_del_{cp['id']}", use_container_width=True):
                    try:
                        delete_checkpoint(cp["id"])
                        st.toast(f"{cp['name']} removed", icon="🗑️")
                        st.rerun()
                    except (EngineUnavailable, EngineError) as exc:
                        st.error(str(exc))
