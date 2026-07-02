"""Deterministic, rule-based fallback analyzer.

Used when every LLM provider is unreachable. The output is intentionally
predictable so the pipeline keeps producing consistent results even
without network access. The rules are driven by the static catalogues
in ``config/`` so adding a new industry or service requires no code
changes.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from config.industries import get_industry_by_key
from config.services_catalog import SERVICES_CATALOG
from domain.models import BusinessRaw, LeadAnalysis, ProposedService


_logger = logging.getLogger("infrastructure.llm.fallback")


# Heuristic digital-presence indicators — counted and summed into a score.
_PRESENCE_POSITIVE = (
    "website", "www", "http", "facebook", "instagram", "linkedin",
    "menu", "online order", "réservation", "booking",
)
_PRESENCE_NEGATIVE = (
    "no website", "pas de site", "site web en construction",
)


class HeuristicAnalyzer:
    """Rule-based fallback that produces a ``LeadAnalysis`` without an LLM."""

    def analyze(self, business: BusinessRaw) -> LeadAnalysis:
        industry_key = (business.industry or "").lower().strip()
        industry_meta = get_industry_by_key(industry_key)

        # Pick the services whose ``relevant_industries`` mentions this one.
        relevant_services = [
            s for s in SERVICES_CATALOG
            if industry_key in (s.get("relevant_industries") or ())
            or industry_key in str(s.get("relevant_industries", "")).lower()
        ]
        if not relevant_services:
            # Fall back to the top 3 by priority.
            relevant_services = sorted(SERVICES_CATALOG, key=lambda s: -int(s["priority"]))[:3]

        solutions = [
            ProposedService(
                service_name=str(s["name"]),
                justification=f"Heuristic match for industry '{business.industry}'.",
                estimated_value_usd=float(s["base_value_usd"]),
                priority=int(s["priority"]),
            )
            for s in relevant_services[:3]
        ]

        digital_score = self._estimate_digital_presence(business)
        pain_points = self._derive_pain_points(business, digital_score)
        pitch_angles = [str(s["pitch_angle"]) for s in relevant_services[:2]]

        avg_value = (
            sum(s.estimated_value_usd for s in solutions) / len(solutions)
            if solutions
            else 0.0
        )

        _logger.debug(
            "Heuristic analysis for %r (industry=%s, score=%d, value=$%.0f)",
            business.name, industry_key, digital_score, avg_value,
        )

        return LeadAnalysis(
            pain_points=pain_points,
            recommended_solutions=solutions,
            digital_presence_score=digital_score,
            pitch_angles=pitch_angles,
            estimated_monthly_revenue_usd=None,
            analysis_model="heuristic-fallback",
            from_cache=False,
            analyzed_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------

    def _estimate_digital_presence(self, business: BusinessRaw) -> int:
        """Score 0–100 based on the presence of digital channels."""
        score = 30  # baseline
        text = " ".join([
            business.name or "",
            business.website or "",
            " ".join(business.social_media_handles or []),
            business.email or "",
        ]).lower()

        for indicator in _PRESENCE_POSITIVE:
            if indicator in text:
                score += 10
        for indicator in _PRESENCE_NEGATIVE:
            if indicator in text:
                score -= 15

        if business.phone:
            score += 5
        if business.email:
            score += 5
        if business.social_media_handles:
            score += 10
        if not business.website:
            score -= 10

        return max(0, min(100, score))

    def _derive_pain_points(self, business: BusinessRaw, digital_score: int) -> list[str]:
        points: list[str] = []
        if digital_score < 50:
            points.append("Weak online presence — customers struggle to find the business online.")
        if not business.phone:
            points.append("No public phone number — leads cannot easily reach out.")
        if not business.email:
            points.append("No public email — outbound sales outreach will be harder.")
        if not business.website:
            points.append("No website — competitor with a website will capture online demand.")
        if not business.social_media_handles:
            points.append("No social media presence — limited discoverability by younger demographics.")
        if not points:
            points.append("No obvious pain points detected — likely already digitally mature.")
        return points
