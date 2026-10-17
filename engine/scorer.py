"""Explainable 0-100 lead priority scoring.

Factor weights are domain rules (justified constants, not runtime config):
    reachability  <= 35   phone 15, mobile +10, whatsapp +5, email +5
    substance     <= 25   website 10, social 5, address 5, geo 5
    opportunity   <= 25   website_build 15, local_seo 10 (v4 Task 10 —
                          absence of digital presence is a sales lead, not
                          a penalty). Issue #16: both bonuses are gated on
                          contactability — a phone number or email — so
                          ghost records with no contact channel cannot
                          earn opportunity points from missing fields
                          alone.
    deficit       <= 25   (100 - digital_score) * 0.25  (inverse opportunity)
    freshness     <= 15   hour 15, day 10, week 7, month 4, older 2

The arithmetic lives in ``engine.fastops.score_batch`` — the single
source of truth shared by the single-lead and batch paths (asserted by
tests/test_fastops.py). ``LeadScorer.explain`` mirrors the same factors
one-for-one, including the contactability gate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from engine.fastops import (
    FLAG_ADDRESS,
    FLAG_EMAIL,
    FLAG_GEO,
    FLAG_MOBILE,
    FLAG_PHONE,
    FLAG_SOCIAL,
    FLAG_SSL,
    FLAG_WEBSITE,
    FLAG_WHATSAPP,
    WEIGHTS,
    FRESHNESS_POINTS,
    score_batch,
)

if TYPE_CHECKING:  # pragma: no cover
    from domain.models import Lead

FRESHNESS_BUCKET = {"hour": 0, "day": 1, "week": 2, "month": 3, "older": 4}


def channel_flags(lead: "Lead") -> int:
    """Bit-pack the hot state (flag layout shared with fastops)."""
    f = 0
    if lead.website:
        f |= FLAG_WEBSITE
        if lead.website.startswith("https://"):
            f |= FLAG_SSL
    if lead.phone:
        f |= FLAG_PHONE
        if any(p.phone_type.value == "MOBILE" for p in lead.phone_details):
            f |= FLAG_MOBILE
        if any(getattr(p, "is_whatsapp_capable", False) for p in lead.phone_details):
            f |= FLAG_WHATSAPP
    if lead.email:
        f |= FLAG_EMAIL
    if lead.social_links:
        f |= FLAG_SOCIAL
    if lead.address and len(lead.address) > 5:
        f |= FLAG_ADDRESS
    if lead.latitude is not None and lead.longitude is not None:
        f |= FLAG_GEO
    return f


class LeadScorer:
    """Single-lead and batch scoring with an explainable breakdown."""

    def score(self, lead: "Lead") -> tuple[float, dict[str, float]]:
        flags = channel_flags(lead)
        social_count = min(len(lead.social_links), 255)
        bucket = FRESHNESS_BUCKET.get(
            getattr(getattr(lead, "freshness", None), "age_class", "older"), 4
        )
        priorities, digitals = score_batch([flags], [social_count], [bucket])
        lead.priority_score = round(priorities[0], 1)
        lead.digital_score = digitals[0]
        lead.score_breakdown = self.explain(lead)
        return lead.priority_score, lead.score_breakdown

    def score_many(self, leads: list["Lead"]) -> None:
        """Batch path: one arithmetic pass for the whole list (SoA layout)."""
        if not leads:
            return
        flags = [channel_flags(l) for l in leads]
        socials = [min(len(l.social_links), 255) for l in leads]
        buckets = [
            FRESHNESS_BUCKET.get(
                getattr(getattr(l, "freshness", None), "age_class", "older"), 4
            )
            for l in leads
        ]
        priorities, digitals = score_batch(flags, socials, buckets)
        for lead, priority, digital in zip(leads, priorities, digitals):
            lead.priority_score = round(priority, 1)
            lead.digital_score = digital
            lead.score_breakdown = self.explain(lead)

    @staticmethod
    def explain(lead: "Lead") -> dict[str, float]:
        factors: dict[str, float] = {}
        if lead.phone:
            factors["phone_present"] = WEIGHTS["phone_present"]
            if any(p.phone_type.value == "MOBILE" for p in lead.phone_details):
                factors["mobile_direct"] = WEIGHTS["mobile_direct"]
            if any(getattr(p, "is_whatsapp_capable", False) for p in lead.phone_details):
                factors["whatsapp_ready"] = WEIGHTS["whatsapp_ready"]
        if lead.email:
            factors["email_present"] = WEIGHTS["email_present"]
        if lead.website:
            factors["website_active"] = WEIGHTS["website_active"]
        if lead.social_links:
            factors["social_channel"] = WEIGHTS["social_channel"]
        if lead.address and len(lead.address) > 5:
            factors["physical_location"] = WEIGHTS["physical_location"]
        if lead.latitude is not None and lead.longitude is not None:
            factors["geo_verified"] = WEIGHTS["geo_verified"]

        # v4 Task 10 — inverted map/web-absence scoring: award the missing-
        # presence opportunity instead of burying offline businesses.
        # Issue #16 — gate both bonuses on contactability (phone or email):
        # an uncontactable record is not a sales opportunity, whatever it
        # lacks. Mirrors FLAG_CONTACTABLE in engine.fastops exactly.
        contactable = bool(lead.phone or lead.email)
        has_address = bool(lead.address and len(lead.address) > 5)
        has_geo = lead.latitude is not None and lead.longitude is not None
        if contactable and not lead.website:
            factors["website_build_opportunity"] = WEIGHTS["website_build_opportunity"]
        if contactable and not has_address and not has_geo:
            factors["local_seo_opportunity"] = WEIGHTS["local_seo_opportunity"]

        digital = getattr(lead, "digital_score", None)
        if digital is None:
            digital = 10
            if lead.website:
                digital += 35
                if lead.website.startswith("https://"):
                    digital += 10
            if lead.phone:
                digital += 15
            if lead.email:
                digital += 10
            if lead.social_links:
                digital += 10 + min(len(lead.social_links), 2) * 5
            if lead.address:
                digital += 5
            digital = min(100, digital)
        factors["opportunity_deficit"] = round(
            (100.0 - digital) * WEIGHTS["deficit_multiplier"], 1
        )

        bucket = FRESHNESS_BUCKET.get(
            getattr(getattr(lead, "freshness", None), "age_class", "older"), 4
        )
        factors["freshness"] = FRESHNESS_POINTS[bucket]
        return factors
