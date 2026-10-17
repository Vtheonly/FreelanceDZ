"""Leads matrix — filters, paginated table, and selection for inspection.

Every filter maps 1:1 onto /api/v2/leads query parameters (the unified
endpoint from v4 Task 5): text search composes with the wilaya selected on
the map, status, contact-only, and minimum score. Pagination is
offset-based over the same query.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd
import streamlit as st

from ui import state
from ui.api_client import EngineError, EngineUnavailable, fetch_leads, fetch_wilayas
from ui.theme import panel_header, tokens

PAGE_SIZE = 25

_STATUS_OPTIONS = ["", "discovered", "analyzed", "scored", "contacted", "verified", "rejected"]


def render_leads_matrix() -> None:
    filters = st.session_state.get(state.LEAD_FILTERS, {})
    page = st.session_state.get(state.LEAD_PAGE, 0)
    wilaya = st.session_state.get(state.SELECTED_WILAYA)

    filter_cols = st.columns([3, 2, 2, 2, 2])
    with filter_cols[0]:
        search = st.text_input(
            "Search (name / industry / FTS)",
            value=filters.get("q", ""),
            key="lead_q",
            placeholder="e.g. pharmacie, menuiserie…",
            label_visibility="collapsed",
        )
    with filter_cols[1]:
        status = st.selectbox(
            "Status",
            _STATUS_OPTIONS,
            index=_STATUS_OPTIONS.index(filters.get("status", "")),
            key="lead_status",
            label_visibility="collapsed",
        )
    with filter_cols[2]:
        contact_only = st.checkbox(
            "Contacts only",
            value=bool(filters.get("is_contact", False)),
            key="lead_contact_only",
        )
    with filter_cols[3]:
        min_score = st.number_input(
            "Min score",
            min_value=0, max_value=100, value=int(filters.get("min_score", 0)),
            key="lead_min_score", label_visibility="collapsed",
        )
    with filter_cols[4]:
        sort_by = st.selectbox(
            "Sort",
            ["priority_score", "updated_at", "name", "wilaya"],
            index=["priority_score", "updated_at", "name", "wilaya"].index(
                filters.get("sort_by", "priority_score")
            ),
            key="lead_sort",
            label_visibility="collapsed",
        )

    try:
        payload = fetch_leads(
            q=search or None,
            wilaya=wilaya,
            status=status or None,
            is_contact=True if contact_only else None,
            min_score=float(min_score),
            sort_by=sort_by,
            sort_order="desc",
            limit=PAGE_SIZE,
            offset=page * PAGE_SIZE,
        )
    except (EngineUnavailable, EngineError) as exc:
        st.error(f"Leads unavailable: {exc}")
        return

    leads = payload.get("leads", [])
    if not leads:
        st.info(
            "No leads match the current filters. Launch a discovery campaign "
            "below to populate the database."
        )
        return

    df = pd.DataFrame(
        [
            {
                "id": l["id"],
                "score": round(float(l.get("priority_score", 0))),
                "business": l["name"],
                "wilaya": l.get("wilaya") or "—",
                "phone": l.get("phone") or "—",
                "web": "✓" if l.get("website") else "○",
                "status": l.get("status", ""),
                "contact": "★" if l.get("is_contact") else "·",
            }
            for l in leads
        ]
    )
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=380,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "score": st.column_config.ProgressColumn(
                "score", min_value=0, max_value=100, format="%d", width="medium"
            ),
            "id": None,
        },
        key="leads_table",
    )

    selected = _selected_row()
    if selected is not None:
        st.session_state[state.SELECTED_LEAD_ID] = selected

    nav_l, nav_m, nav_r, _ = st.columns([1, 2, 1, 4])
    with nav_l:
        if st.button("◀ Prev", disabled=page == 0, use_container_width=True):
            st.session_state[state.LEAD_PAGE] = max(0, page - 1)
            st.rerun()
    with nav_m:
        st.caption(f"page {page + 1} · showing {len(leads)} of {payload.get('count', len(leads))} matches")
    with nav_r:
        if st.button("Next ▶", disabled=len(leads) < PAGE_SIZE, use_container_width=True):
            st.session_state[state.LEAD_PAGE] = page + 1
            st.rerun()


def _selected_row() -> Optional[int]:
    """Extract the lead id from the dataframe's single-row selection."""
    el = st.session_state.get("leads_table")
    if not el:
        return None
    selection = el if isinstance(el, dict) else el.selection
    rows = (selection or {}).get("rows", []) if hasattr(selection, "get") else []
    if not rows:
        return None
    try:
        row_index = rows[0]
        el_df = el if hasattr(el, "data") else None
        if el_df is not None:
            return int(el_df.data["id"].iloc[int(row_index)])
    except Exception:
        return None
    return None
