"""Leads matrix — filters, paginated table, bulk ops, and selection.

Every filter maps 1:1 onto /api/v2/leads query parameters (the unified
endpoint from v4 Task 5): text search composes with the wilaya selected on
the map, status, freshness, contact-only, and minimum score. Pagination is
offset-based; multi-row selection drives bulk CRM operations; CSV/JSON
exports stream through the engine's export endpoints.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd
import streamlit as st

from ui import state
from ui.api_client import (
    EngineError,
    EngineUnavailable,
    bulk_contact,
    bulk_status,
    export_bytes,
    fetch_leads,
)
from ui.theme import panel_header

PAGE_SIZE = 25

_STATUS_OPTIONS = ["", "discovered", "analyzed", "scored", "contacted", "verified", "rejected"]
_AGE_OPTIONS = ["", "hour", "day", "week", "month", "older"]


def render_leads_matrix() -> None:
    filters = st.session_state.get(state.LEAD_FILTERS, {})
    page = st.session_state.get(state.LEAD_PAGE, 0)
    wilaya = st.session_state.get(state.SELECTED_WILAYA)

    filter_cols = st.columns([3, 2, 2, 2, 2, 1.6])
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
        age_class = st.selectbox(
            "Freshness",
            _AGE_OPTIONS,
            index=_AGE_OPTIONS.index(filters.get("age_class", "")),
            key="lead_age",
            label_visibility="collapsed",
        )
    with filter_cols[3]:
        contact_only = st.checkbox(
            "Contacts only",
            value=bool(filters.get("is_contact", False)),
            key="lead_contact_only",
        )
    with filter_cols[4]:
        min_score = st.number_input(
            "Min score",
            min_value=0, max_value=100, value=int(filters.get("min_score", 0)),
            key="lead_min_score", label_visibility="collapsed",
        )
    with filter_cols[5]:
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
            age_class=age_class or None,
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
        _export_row()
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
        selection_mode="multi-row",
        column_config={
            "score": st.column_config.ProgressColumn(
                "score", min_value=0, max_value=100, format="%d", width="medium"
            ),
            "id": None,
        },
        key="leads_table",
    )

    _selected_rows(leads)
    _bulk_actions(leads)
    _export_row()

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


def _selection() -> list[int]:
    """Lead ids currently selected in the dataframe (multi-row)."""
    el = st.session_state.get("leads_table")
    if not el:
        return []
    try:
        selection = el.selection if hasattr(el, "selection") else el
        rows = list((selection or {}).get("rows", []))
    except Exception:
        return []
    if not rows:
        return []
    try:
        el_df = el.data if hasattr(el, "data") else None
        if el_df is not None:
            return [int(el_df["id"].iloc[int(r)]) for r in rows]
    except Exception:
        return []
    return []


def _selected_rows(leads: list[dict[str, Any]]) -> None:
    ids = _selection()
    if len(ids) == 1:
        st.session_state[state.SELECTED_LEAD_ID] = ids[0]


def _bulk_actions(leads: list[dict[str, Any]]) -> None:
    ids = _selection()
    if not ids:
        return
    st.markdown(
        f"<span class='badge badge-info'>{len(ids)} selected</span>",
        unsafe_allow_html=True,
    )
    b1, b2, b3, _ = st.columns([1.4, 1.4, 1.4, 3])
    with b1:
        if st.button("★ Add to contacts", use_container_width=True):
            try:
                result = bulk_contact(ids, True)
                st.toast(f"{result.get('updated', 0)} leads → contacts", icon="✓")
                st.rerun()
            except (EngineUnavailable, EngineError) as exc:
                st.error(str(exc))
    with b2:
        if st.button("✕ Block (reject)", use_container_width=True):
            try:
                result = bulk_status(ids, "rejected")
                st.toast(f"{result.get('updated', 0)} leads rejected", icon="✕")
                st.rerun()
            except (EngineUnavailable, EngineError) as exc:
                st.error(str(exc))
    with b3:
        if st.button("↺ Re-contact", use_container_width=True):
            try:
                result = bulk_contact(ids, False)
                st.toast(f"{result.get('updated', 0)} leads updated", icon="↺")
                st.rerun()
            except (EngineUnavailable, EngineError) as exc:
                st.error(str(exc))


def _export_row() -> None:
    """CSV/JSON exports served by the engine's export endpoints."""
    try:
        csv_bytes, _ = export_bytes("csv")
        json_bytes, _ = export_bytes("json")
        e1, e2, _ = st.columns([1, 1, 5])
        with e1:
            st.download_button(
                "⬇ CSV", data=csv_bytes, file_name="freelancedz_leads.csv",
                mime="text/csv", use_container_width=True,
            )
        with e2:
            st.download_button(
                "⬇ JSON", data=json_bytes, file_name="freelancedz_leads.json",
                mime="application/json", use_container_width=True,
            )
    except (EngineUnavailable, EngineError) as exc:
        st.caption(f"exports unavailable: {str(exc)[:60]}")


def render_manual_lead_form() -> None:
    """Create a lead by hand (migrated from the legacy dashboard modal)."""
    from ui.api_client import create_manual_lead

    with st.expander("＋ Add a lead manually"):
        with st.form("manual_lead"):
            c1, c2 = st.columns(2)
            with c1:
                name = st.text_input("Name *", placeholder="Pharmacie Centrale")
                industry = st.text_input("Industry", placeholder="pharmacie")
                wilaya = st.text_input("Wilaya", placeholder="Alger")
            with c2:
                phone = st.text_input("Phone", placeholder="+213 5xx xx xx xx")
                email = st.text_input("Email")
                website = st.text_input("Website", placeholder="https://…")
            address = st.text_input("Address")
            submitted = st.form_submit_button("Save lead", use_container_width=True)
        if submitted:
            if not name.strip():
                st.error("A name is required.")
            else:
                payload = {
                    "name": name.strip(),
                    "industry": industry.strip(),
                    "wilaya": wilaya.strip(),
                    "phone": phone.strip() or None,
                    "email": email.strip() or None,
                    "website": website.strip() or None,
                    "address": address.strip() or None,
                }
                try:
                    result = create_manual_lead(payload)
                    st.toast(f"Lead #{result.get('lead_id')} created", icon="✓")
                    st.rerun()
                except EngineError as exc:
                    st.error(f"Rejected ({exc.status}): {exc.detail}")
                except (EngineUnavailable, EngineError) as exc:
                    st.error(str(exc))
