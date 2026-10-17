"""Lead inspector — full detail, digital audit, CRM actions.

All data comes from /api/v2/leads/{id}; every action calls the matching
API mutation (contact toggle, status, tags, analyze). Nothing is computed
client-side beyond presentation.
"""

from __future__ import annotations

import streamlit as st

from ui import state
from ui.api_client import (
    EngineError,
    EngineUnavailable,
    analyze_lead,
    fetch_lead,
    fetch_tags,
    set_lead_contact,
    set_lead_status,
    set_lead_tags,
)
from ui.theme import badge, tokens

_STATUS_CHOICES = ["discovered", "analyzed", "scored", "contacted", "verified", "rejected"]


def render_lead_inspector() -> None:
    lead_id = st.session_state.get(state.SELECTED_LEAD_ID)
    if not lead_id:
        st.caption("Select a row in the leads matrix to inspect a business.")
        return

    try:
        lead = fetch_lead(lead_id)
    except EngineError as exc:
        if exc.status == 404:
            st.session_state[state.SELECTED_LEAD_ID] = None
            st.caption("That lead no longer exists.")
            return
        st.error(f"Could not load lead: {exc}")
        return
    except (EngineUnavailable, EngineError) as exc:
        st.error(f"Engine unreachable: {exc}")
        return

    t = tokens()
    st.markdown(
        f"""
        <div style="font-size:15px; font-weight:700; margin-bottom:2px;">{lead['name']}</div>
        <div style="font-size:11.5px; color:{t['muted']}; margin-bottom:8px;">
        {lead.get('industry') or '—'} · {lead.get('wilaya') or '—'} ·
        score <span style="color:{t['accent']}; font-family:JetBrains Mono;">{float(lead.get('priority_score', 0)):.0f}/100</span>
        · digital <span style="color:{t['ok']}; font-family:JetBrains Mono;">{lead.get('digital_score') or 0}/100</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Contact block.
    contact_bits = []
    if lead.get("phone"):
        wa = "".join(c for c in lead["phone"] if c.isdigit())
        contact_bits.append(f"`{lead['phone']}` · [WhatsApp](https://wa.me/{wa})")
    if lead.get("email"):
        contact_bits.append(f"[{lead['email']}](mailto:{lead['email']})")
    if lead.get("website"):
        contact_bits.append(f"[website]({lead['website']})")
    if lead.get("address"):
        contact_bits.append(f"📍 {lead['address']}")
    if lead.get("source_url"):
        contact_bits.append(f"[source]({lead['source_url']})")
    if contact_bits:
        st.markdown(" · ".join(contact_bits))

    if lead.get("social_links"):
        st.caption(" · ".join(f"[{u.split('//')[-1].split('/')[0]}]({u})" for u in lead["social_links"][:5]))

    # Digital presence audit.
    st.progress(min((lead.get("digital_score") or 0) / 100, 1.0))
    st.caption(
        f"Digital presence: {lead.get('digital_tier') or '—'} · "
        f"analysis model {lead.get('analysis_model') or '—'}"
    )

    breakdown = lead.get("score_breakdown") or {}
    if breakdown:
        factors = ", ".join(
            f"{k.replace('_', ' ')} (+{v:.0f})" for k, v in
            sorted(breakdown.items(), key=lambda kv: -kv[1])[:6]
        )
        st.caption(f"Score factors: {factors}")

    if lead.get("gaps"):
        with st.expander(f"Identified gaps ({len(lead['gaps'])})"):
            for gap in lead["gaps"]:
                st.markdown(f"- ⚠️ {gap}")

    if lead.get("recommended_services"):
        with st.expander(f"Recommended pitches ({len(lead['recommended_services'])})"):
            for service in lead["recommended_services"]:
                budget = service.get("estimated_budget_dzd", 0)
                st.markdown(
                    f"**{service.get('service_name', 'Service')}** "
                    f"(~{budget:,.0f} DZD) — {service.get('pitch_argument', '')}"
                )

    if lead.get("cta_fr"):
        with st.expander("Outreach opener (FR)"):
            st.code(lead["cta_fr"], language="text")
    if lead.get("cta_ar"):
        with st.expander("Outreach opener (AR)"):
            st.code(lead["cta_ar"], language="text")

    if lead.get("notes"):
        st.caption(f"Notes: {lead['notes']}")

    _crm_actions(lead)


def _crm_actions(lead: dict) -> None:
    st.markdown("---")
    action_cols = st.columns(3)
    with action_cols[0]:
        if st.button(
            "Remove contact" if lead.get("is_contact") else "Add to contacts",
            use_container_width=True,
        ):
            try:
                set_lead_contact(lead["id"], not lead.get("is_contact", False))
                st.toast("Contact state updated", icon="✓")
                st.rerun()
            except (EngineUnavailable, EngineError) as exc:
                st.error(str(exc))

    with action_cols[1]:
        status = st.selectbox(
            "status",
            _STATUS_CHOICES,
            index=_STATUS_CHOICES.index(lead.get("status", "discovered")),
            key=f"status_{lead['id']}",
            label_visibility="collapsed",
        )
        if status != lead.get("status"):
            try:
                set_lead_status(lead["id"], status)
                st.toast(f"Status → {status}", icon="✓")
                st.rerun()
            except (EngineUnavailable, EngineError) as exc:
                st.error(str(exc))

    with action_cols[2]:
        if st.button("Re-analyze", use_container_width=True):
            try:
                result = analyze_lead(lead["id"])
                st.toast(
                    f"Re-scored: {result.get('priority_score', 0):.0f}/100",
                    icon="⚡",
                )
                st.rerun()
            except (EngineUnavailable, EngineError) as exc:
                st.error(str(exc))

    try:
        all_tags = fetch_tags()
    except (EngineUnavailable, EngineError):
        all_tags = []
    current = lead.get("tags") or []
    new_tags = st.multiselect(
        "tags", options=all_tags, default=[t for t in current if t in all_tags],
        key=f"tags_{lead['id']}",
    )
    if set(new_tags) != set(current):
        try:
            set_lead_tags(lead["id"], new_tags)
            st.toast("Tags updated", icon="✓")
            st.rerun()
        except (EngineUnavailable, EngineError) as exc:
            st.error(str(exc))
