"""Scoring service — computes deterministic priority scores for leads.

The scoring engine is intentionally simple and explainable: every
factor contributes a fixed number of points, and the breakdown is
returned alongside the total so users can see *why* a lead scored
the way it did.

Factors
-------
* ``has_phone``      — 15 pts (a reachable lead is more valuable)
* ``has_email``      — 10 pts
* ``has_website``    — 10 pts
* ``has_social``     — 5  pts
* ``verified_phone`` — 10 pts (libphonenumber validated)
* ``mobile_phone``   — 10 pts (mobile > landline for outreach)
* ``freshness``      — 0–20 pts (newer = better)
* ``digital_presence``— 0–20 pts (from LLM analysis, 0 if unanalysed)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from core.interfaces import ILeadPrioritizer, ILeadRepository
from domain.enums import FreshnessAge, PhoneType
from domain.models import Lead


_logger = logging.getLogger("services.scoring")


_FRESHNESS_POINTS: dict[FreshnessAge, float] = {
    FreshnessAge.HOURLY: 20.0,
    FreshnessAge.DAILY: 15.0,
    FreshnessAge.WEEKLY: 10.0,
    FreshnessAge.MONTHLY: 5.0,
    FreshnessAge.ARCHIVED: 2.0,
}


class LeadScoringEngine(ILeadPrioritizer):
    """Deterministic, explainable priority scorer."""

    def calculate_score(self, lead: Lead) -> float:
        breakdown = self.explain_score(lead)
        return min(100.0, sum(breakdown.values()))

    def explain_score(self, lead: Lead) -> dict[str, float]:
        biz = lead.business
        breakdown: dict[str, float] = {}

        if biz.phone:
            breakdown["has_phone"] = 15.0
        if biz.email:
            breakdown["has_email"] = 10.0
        if biz.website:
            breakdown["has_website"] = 10.0
        if biz.social_media_handles:
            breakdown["has_social"] = 5.0

        # Phone metadata bonuses.
        if biz.phone_metadata:
            primary = biz.phone_metadata[0]
            if primary.is_valid:
                breakdown["verified_phone"] = 10.0
            if primary.phone_type == PhoneType.MOBILE:
                breakdown["mobile_phone"] = 10.0
            elif primary.phone_type == PhoneType.LANDLINE:
                breakdown["landline_phone"] = 3.0

        # Freshness bonus.
        age_class = biz.freshness.calculated_age_class
        breakdown["freshness"] = _FRESHNESS_POINTS.get(age_class, 2.0)

        # Digital presence (from analysis, if present).
        if lead.analysis:
            presence = lead.analysis.digital_presence_score
            breakdown["digital_presence"] = (presence / 100.0) * 20.0
        else:
            breakdown["digital_presence"] = 0.0

        return breakdown


class ScoringService:
    """Recalculate scores for many leads at once."""

    def __init__(
        self,
        lead_repo: ILeadRepository,
        prioritizer: Optional[ILeadPrioritizer] = None,
    ) -> None:
        self._repo = lead_repo
        self._prioritizer = prioritizer or LeadScoringEngine()

    async def score_all(self, limit: int = 500) -> int:
        """Recompute scores for up to ``limit`` leads."""
        leads = await self._repo.list_leads(min_score=0.0, limit=limit)
        _logger.info("Scoring %d leads", len(leads))
        scored = 0
        for lead in leads:
            if lead.id is None:
                continue
            score = self._prioritizer.calculate_score(lead)
            breakdown = self._prioritizer.explain_score(lead)
            await self._repo.update_score(lead.id, score, breakdown)
            scored += 1
        _logger.info("Scored %d leads", scored)
        return scored

    async def score_single(self, lead_id: int) -> Optional[float]:
        lead = await self._repo.get_lead(lead_id)
        if lead is None:
            return None
        score = self._prioritizer.calculate_score(lead)
        breakdown = self._prioritizer.explain_score(lead)
        await self._repo.update_score(lead_id, score, breakdown)
        return score
