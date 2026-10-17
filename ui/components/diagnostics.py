"""Engine diagnostics — health, latency, crawler, and data-quality signals.

Everything here is a real measurement from the running engine: /health
(round-trip latency), /api/v2/crawler/status, entity-resolution backlog,
and lead fill-rates from /api/v2/stats. No fabricated metrics.
"""

from __future__ import annotations

import time

import streamlit as st

from ui.api_client import (
    EngineError,
    EngineUnavailable,
    fetch_crawler_status,
    fetch_entities_stats,
    fetch_geo_overview,
    fetch_health,
    fetch_stats,
)
from ui.theme import badge, tokens


def render_diagnostics_panel() -> None:
    diag_cols = st.columns([1, 1, 1])

    with diag_cols[0]:
        _health_card()
    with diag_cols[1]:
        _engine_card()
    with diag_cols[2]:
        _data_quality_card()


def _health_card() -> None:
    st.markdown("**Engine health**")
    try:
        started = time.perf_counter()
        health = fetch_health()
        latency_ms = (time.perf_counter() - started) * 1000
        status = health.get("status", "?")
        kind = "ok" if status == "ok" else "bad"
        st.markdown(badge(f"{status}", kind), unsafe_allow_html=True)
        st.caption(
            f"{health.get('app', 'engine')} v{health.get('version', '?')} · "
            f"probe {latency_ms:.0f} ms · database "
            f"{'ok' if health.get('database') else 'degraded'}"
        )
    except (EngineUnavailable, EngineError) as exc:
        st.markdown(badge("unreachable", "bad"), unsafe_allow_html=True)
        st.caption(str(exc)[:120])


def _engine_card() -> None:
    st.markdown("**Engine services**")
    try:
        crawler = fetch_crawler_status()
        entities = fetch_entities_stats()
        active = crawler.get("active", False)
        st.markdown(
            badge("crawler running" if active else "crawler idle", "info" if active else "mono"),
            unsafe_allow_html=True,
        )
        st.caption(
            f"{crawler.get('pages_crawled', 0):,} pages crawled · "
            f"{crawler.get('entities_saved', 0):,} saved · "
            f"{crawler.get('blocks_detected', 0):,} blocks · "
            f"concurrency {crawler.get('concurrency', 0)}"
        )
        st.caption(
            f"entities: {entities.get('total_clusters', 0):,} clusters · "
            f"{entities.get('pending_review', 0):,} pending review"
        )
    except (EngineUnavailable, EngineError) as exc:
        st.caption(f"unavailable: {str(exc)[:80]}")


def _data_quality_card() -> None:
    st.markdown("**Data quality**")
    try:
        stats = fetch_stats()
        overview = fetch_geo_overview()
        total = max(stats.get("total_leads", 0), 1)
        analyzed = stats.get("analyzed_leads", 0)
        contacts = stats.get("active_contacts", 0)
        geoloc = overview.get("leads_geolocated", 0)
        st.caption(
            f"analyzed {(analyzed / total):.0%} · contacts {(contacts / total):.0%} · "
            f"geolocated {(geoloc / total):.0%}"
        )
        st.caption(
            f"checkpoints {overview.get('checkpoints', 0):,} · "
            f"avg score {stats.get('average_score', 0)}"
        )
    except (EngineUnavailable, EngineError) as exc:
        st.caption(f"unavailable: {str(exc)[:80]}")
