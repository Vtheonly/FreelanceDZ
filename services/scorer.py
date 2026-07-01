"""Lead scoring engine — deterministic multi-factor priority score (0–100).

Factors & weights (must sum to 100):
  * Digital Presence Gap      : 40 pts  (no website, no social, low digital score)
  * Business Activity Signal  : 30 pts  (review_count, rating)
  * Deal Size Potential       : 20 pts  (sum of recommended_services.estimated_value_usd)
  * Industry Multiplier       : 10 pts  (high-value industries get a bonus)

The `explain_score` method returns the per-factor breakdown so dashboards
and CLI output can show *why* a lead was ranked where it was.
"""

from __future__ import annotations

import logging
from typing import Dict

from config.industries import resolve_industry
from core.interfaces import ILeadPrioritizer
from domain.models import Lead


class LeadScoringEngine(ILeadPrioritizer):
    """Deterministic, fully explainable lead scoring engine."""

    def __init__(self) -> None:
        self._logger = logging.getLogger("services.scorer")

    # ------------------------------------------------------------------

    def calculate_score(self, lead: Lead) -> float:
        breakdown = self.explain_score(lead)
        total = sum(breakdown.values())
        # Clamp to [0, 100].
        return round(min(max(total, 0.0), 100.0), 2)

    def explain_score(self, lead: Lead) -> Dict[str, float]:
        b = lead.business
        a = lead.analysis
        template = resolve_industry(b.industry)

        # ----------------------- Factor 1: Digital Gap (40 pts) -----------------------
        digital_gap = 0.0
        if not b.website:
            digital_gap += 20.0   # No website = huge opportunity
        elif a and a.digital_presence_score < 50:
            digital_gap += 10.0   # Poor website = moderate opportunity

        if not b.social_media_handles:
            digital_gap += 10.0   # No social = bigger gap
        elif a and a.digital_presence_score < 30:
            digital_gap += 5.0    # Very weak social presence

        if not b.phone:
            digital_gap += 5.0    # No public phone = harder to reach but bigger gap
        digital_gap = min(digital_gap, 40.0)

        # ----------------------- Factor 2: Activity (30 pts) -------------------------
        # Reviews (cap at 250 → 20 pts).
        review_pts = min((b.review_count / 250.0) * 20.0, 20.0)
        # Rating: lower rating = bigger upside for reputation software (cap 10 pts).
        if b.rating > 0:
            rating_pts = min((5.0 - b.rating) * 2.0, 10.0)
        else:
            rating_pts = 5.0  # Unknown rating — assume mid-gap.
        activity = review_pts + rating_pts

        # ----------------------- Factor 3: Deal Size (20 pts) ------------------------
        deal_size = 0.0
        if a and a.recommended_solutions:
            total_value = sum(s.estimated_value_usd for s in a.recommended_solutions)
            # 0 → 0 pts, 10 000 USD → 20 pts (linear, capped).
            deal_size = min((total_value / 10_000.0) * 20.0, 20.0)
        else:
            # Use the industry template's average value as a baseline.
            deal_size = min((template.average_project_value_usd / 10_000.0) * 20.0, 20.0)

        # ----------------------- Factor 4: Industry Multiplier (10 pts) --------------
        # Industries with > 5000 USD avg project get the full bonus.
        industry_pts = min((template.average_project_value_usd / 5_000.0) * 10.0, 10.0)

        breakdown = {
            "digital_gap": round(digital_gap, 2),
            "activity_signal": round(activity, 2),
            "deal_size": round(deal_size, 2),
            "industry_multiplier": round(industry_pts, 2),
        }
        self._logger.debug(
            "Score breakdown for %s: %s", b.name, breakdown
        )
        return breakdown
