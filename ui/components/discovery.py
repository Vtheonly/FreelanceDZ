"""Discovery panel — campaign launcher and live sourcing queue.

Campaigns run in the engine's background (POST /api/v2/discover with
background=true) so a Streamlit rerun is never blocked by network
scraping; the queue panel polls /api/v2/discover/campaigns. The campaign
contract (object with a ``campaigns`` array — the v4 Task 1 shape) is
handled explicitly.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui import state
from ui.api_client import (
    EngineError,
    EngineUnavailable,
    fetch_campaigns,
    fetch_wilayas,
    launch_discovery,
)
from ui.theme import badge, tokens

_STATUS_BADGE = {
    "completed": ("ok", "✓"),
    "processing": ("info", "…"),
    "failed": ("bad", "✗"),
}


def render_discovery_panel() -> None:
    tab_launch, tab_queue = st.tabs(["Launch campaign", "Sourcing queue"])

    with tab_launch:
        _render_launcher()

    with tab_queue:
        _render_queue()


def _render_launcher() -> None:
    selected = st.session_state.get(state.SELECTED_WILAYA)
    with st.form("discovery_form"):
        q_col, w_col, l_col = st.columns([4, 3, 2])
        with q_col:
            query = st.text_input(
                "Target business / category",
                placeholder="e.g. pharmacie, menuiserie, tolier…",
            )
        with w_col:
            nationwide = st.checkbox("Nationwide (ignore wilaya filter)", value=False)
            wilaya_hint = st.caption(
                f"Wilaya filter active: {selected}" if (selected and not nationwide) else "No wilaya filter"
            )
        with l_col:
            limit = st.number_input("Limit", min_value=5, max_value=150, value=30, step=5)

        launched = st.form_submit_button("Launch discovery campaign", type="primary", use_container_width=True)

    if launched:
        if not query.strip():
            st.error("A query is required.")
            return
        wilaya = None if nationwide else selected
        try:
            with st.spinner(f"Campaign '{query.strip()}' dispatched to the engine…"):
                result = launch_discovery(
                    query.strip(), wilaya, int(limit), background=True
                )
            st.success(
                f"Campaign accepted (#{result.get('campaign_id', '?')}) — "
                "results stream into the database as they arrive; watch the queue."
            )
        except EngineError as exc:
            st.error(f"Engine rejected the campaign ({exc.status}): {exc.detail}")
        except (EngineUnavailable, EngineError) as exc:
            st.error(str(exc))


def _render_queue() -> None:
    try:
        payload = fetch_campaigns(limit=10)
    except (EngineUnavailable, EngineError) as exc:
        st.error(f"Queue unavailable: {exc}")
        return

    campaigns = payload.get("campaigns", []) if isinstance(payload, dict) else payload
    if not campaigns:
        st.caption("No sourcing history yet — launch the first campaign above.")
        return

    t = tokens()
    for campaign in campaigns:
        badge_kind, icon = _STATUS_BADGE.get(campaign.get("status", ""), ("mono", "·"))
        saved = campaign.get("saved_count")
        saved_str = f"+{saved}" if saved is not None else ""
        st.markdown(
            f'<div class="row-item">'
            f'<span><b>{campaign.get("query", "?")}</b> · '
            f'{campaign.get("wilaya") or "Nationwide"}</span>'
            f'<span>{badge(f"{icon} {campaign.get("status", "?")} {saved_str}", badge_kind)}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    if st.button("Refresh queue", use_container_width=True):
        from ui.api_client import fetch_campaigns as _fc

        _fc.clear()
        st.rerun()
