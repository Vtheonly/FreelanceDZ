"""KPI ribbon — six metrics from /api/v2/stats + /api/v2/geo/overview."""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui.api_client import (
    EngineError,
    EngineUnavailable,
    fetch_campaigns,
    fetch_geo_overview,
    fetch_stats,
)
from ui.theme import metric_card, tokens


def render_metrics_ribbon() -> None:
    t = tokens()
    try:
        stats = fetch_stats()
        overview = fetch_geo_overview()
    except (EngineUnavailable, EngineError) as exc:
        st.error(f"Stats unavailable: {exc}")
        return

    age = stats.get("age_breakdown") or {}
    fresh = int(age.get("hour", 0) + age.get("day", 0))
    campaigns = _recent_campaign_count()

    cols = st.columns(6)
    cards = [
        ("Total Leads", f"{stats.get('total_leads', 0):,}", "all non-rejected", t["accent"]),
        ("Avg Priority", f"{float(stats.get('average_score', 0)):.1f}", "opportunity score", t["ok"]),
        ("Active Contacts", f"{stats.get('active_contacts', 0):,}", "outreach pipeline", t["warn"]),
        ("Resolved Entities", f"{stats.get('total_resolved_entities', 0):,}", "cluster groups", None),
        ("Field Checkpoints", f"{overview.get('checkpoints', 0):,}", f"{overview.get('leads_geolocated', 0):,} geolocated leads", t["violet"]),
        ("Fresh Signals", f"{fresh}", f"{campaigns} campaigns (24h window)", t["accent"]),
    ]
    for col, (label, value, sub, color) in zip(cols, cards):
        with col:
            st.markdown(metric_card(label, value, sub, color), unsafe_allow_html=True)


def _recent_campaign_count() -> int:
    try:
        return len(fetch_campaigns(limit=8).get("campaigns", []))
    except (EngineUnavailable, EngineError):
        return 0
