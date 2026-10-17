"""Design system — modern, minimalist, information-dense.

Dark-first (Linear/Grafana-style technical workspace) with a light mode
toggle. Streamlit's native chrome is hidden; the token set below is the
single source of truth for every custom element so panels stay consistent
without decorative noise (no gradients, no oversized headings, no filler).
"""

from __future__ import annotations

import streamlit as st

from ui.state import THEME

TOKENS = {
    "dark": {
        "bg": "#0b0e14",
        "panel": "#11141d",
        "panel_border": "#1e2433",
        "text": "#e7ecf3",
        "muted": "#8b93a7",
        "accent": "#38bdf8",
        "accent_soft": "rgba(56, 189, 248, 0.14)",
        "ok": "#34d399",
        "warn": "#fbbf24",
        "bad": "#fb7185",
        "violet": "#a78bfa",
        "tiles": "CartoDB dark_all",
    },
    "light": {
        "bg": "#f6f8fa",
        "panel": "#ffffff",
        "panel_border": "#d9dee8",
        "text": "#111827",
        "muted": "#5b6472",
        "accent": "#0369a1",
        "accent_soft": "rgba(3, 105, 161, 0.10)",
        "ok": "#059669",
        "warn": "#b45309",
        "bad": "#be123c",
        "violet": "#7c3aed",
        "tiles": "CartoDB positron",
    },
}


def tokens() -> dict[str, str]:
    return TOKENS[st.session_state.get(THEME, "dark")]


def _css(t: dict[str, str]) -> str:
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');

html, body, .stApp, [class*="css"] {{
    font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif;
    color: {t["text"]};
    background: {t["bg"]};
}}
code, kbd, samp, pre, .stCode, [data-testid="stCode"] {{
    font-family: 'JetBrains Mono', ui-monospace, monospace !important;
}}

/* Hide Streamlit chrome — the workspace defines its own navigation. */
#MainMenu, header[data-testid="stHeader"], footer {{
    visibility: hidden;
    height: 0;
}}
.stDeployButton {{ display: none; }}

.block-container {{
    padding-top: 1.1rem !important;
    padding-bottom: 2rem !important;
    max-width: 97% !important;
}}

/* Metric cards */
.metric-box {{
    background: {t["panel"]};
    border: 1px solid {t["panel_border"]};
    border-radius: 10px;
    padding: 12px 16px;
    min-height: 68px;
}}
.metric-label {{
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: {t["muted"]};
    font-weight: 600;
}}
.metric-val {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 24px;
    font-weight: 600;
    color: {t["accent"]};
    margin-top: 3px;
    line-height: 1.15;
}}
.metric-sub {{
    font-size: 11px;
    color: {t["muted"]};
    margin-top: 3px;
}}

/* Panel chrome */
.panel-card {{
    background: {t["panel"]};
    border: 1px solid {t["panel_border"]};
    border-radius: 10px;
    padding: 14px 16px 10px 16px;
    margin-bottom: 14px;
}}
.panel-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 10px;
    margin-bottom: 10px;
    border-bottom: 1px solid {t["panel_border"]};
}}
.panel-title {{
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: {t["muted"]};
}}

/* Status badges */
.badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 5px;
    font-size: 10px;
    font-weight: 600;
    font-family: 'JetBrains Mono', monospace;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}}
.badge-ok   {{ background: rgba(52, 211, 153, 0.14); color: {t["ok"]}; border: 1px solid rgba(52, 211, 153, 0.35); }}
.badge-info {{ background: {t["accent_soft"]}; color: {t["accent"]}; border: 1px solid rgba(56, 189, 248, 0.35); }}
.badge-warn {{ background: rgba(251, 191, 36, 0.13); color: {t["warn"]}; border: 1px solid rgba(251, 191, 36, 0.35); }}
.badge-bad  {{ background: rgba(251, 113, 133, 0.13); color: {t["bad"]}; border: 1px solid rgba(251, 113, 133, 0.35); }}
.badge-mono {{ background: transparent; color: {t["muted"]}; border: 1px solid {t["panel_border"]}; }}

/* Compact list rows (campaigns, checkpoints) */
.row-item {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 6px 2px;
    border-bottom: 1px solid {t["panel_border"]};
    font-size: 12.5px;
}}
.row-item:last-child {{ border-bottom: none; }}

/* Sidebar */
section[data-testid="stSidebar"] .block-container {{ padding-top: 0.6rem; }}
.sidebar-brand {{
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 0.01em;
    color: {t["text"]};
}}
.sidebar-brand small {{ color: {t["muted"]}; font-weight: 500; }}

/* Dataframe */
[data-testid="stDataFrame"] {{ border: 1px solid {t["panel_border"]}; border-radius: 8px; }}

/* Tighten widget labels inside panels */
.panel-card .stTextInput > label,
.panel-card .stSelectbox > label,
.panel-card .stNumberInput > label,
.panel-card .stMultiSelect > label {{
    font-size: 11.5px;
    margin-bottom: 2px;
    color: {t["muted"]};
}}
div[data-testid="stExpander"] {{
    border: 1px solid {t["panel_border"]};
    border-radius: 8px;
}}
</style>
"""


def apply() -> None:
    st.markdown(_css(tokens()), unsafe_allow_html=True)


def badge(text: str, kind: str = "info") -> str:
    return f'<span class="badge badge-{kind}">{text}</span>'


def metric_card(label: str, value: str, sub: str = "", color: str | None = None) -> str:
    style = f' style="color: {color}"' if color else ""
    sub_html = f'<div class="metric-sub">{sub}</div>' if sub else ""
    return (
        f'<div class="metric-box"><div class="metric-label">{label}</div>'
        f'<div class="metric-val"{style}>{value}</div>{sub_html}</div>'
    )


def panel_header(title: str, right_html: str = "") -> str:
    right = f'<span>{right_html}</span>' if right_html else ""
    return (
        f'<div class="panel-header"><span class="panel-title">{title}</span>'
        f"{right}</div>"
    )
