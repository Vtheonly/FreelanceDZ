"""Lead analyzer service — wraps an `ILLMClient` and persists results to a repo.

This is the only place where:
  * The LLM client is called.
  * The result is attached to the persistence layer.

Keeping this orchestration in a service (rather than in the LLM client) lets
us swap clients freely without touching the persistence logic.
"""

from __future__ import annotations

import logging
import time
from typing import List

from config.settings import settings
from core.interfaces import ILLMClient, ILeadRepository
from domain.models import Lead


class LeadAnalyzerService:
    """Runs LLM analysis for unanalyzed leads and persists results."""

    def __init__(self, llm: ILLMClient, repo: ILeadRepository) -> None:
        self._llm = llm
        self._repo = repo
        self._logger = logging.getLogger("services.analyzer")

    def analyze_pending(self, limit: int = 50, force: bool = False) -> int:
        """Analyze up to `limit` unanalyzed leads. Returns the count analyzed.

        Args:
            limit: max leads to process in this run.
            force: if True, re-analyze leads that already have an analysis.
        """
        if force:
            leads = self._repo.list_leads(min_score=0.0, limit=limit)
            self._logger.info("Force mode: re-analyzing up to %d leads.", len(leads))
        else:
            leads = self._repo.list_unanalyzed(limit=limit)
            self._logger.info("Found %d unanalyzed leads to process.", len(leads))

        analyzed_count = 0
        for idx, lead in enumerate(leads, start=1):
            if lead.id is None:
                continue
            self._logger.info(
                "[%d/%d] Analyzing: %s (%s, %s)",
                idx, len(leads), lead.business.name, lead.business.industry, lead.business.wilaya,
            )
            try:
                analysis = self._llm.analyze_business_needs(lead.business)
                self._repo.attach_analysis(lead.id, analysis)
                analyzed_count += 1
                self._logger.debug(
                    "  → digital_presence_score=%d, solutions=%d, from_cache=%s",
                    analysis.digital_presence_score,
                    len(analysis.recommended_solutions),
                    analysis.from_cache,
                )
            except Exception as e:
                # A single lead failure must not stop the run.
                self._logger.error("  → FAILED: %s", e)

            # Throttle between calls to protect free-tier quota.
            if idx < len(leads) and not (analysis.from_cache if 'analysis' in locals() else False):
                self._logger.debug("Throttling %.1fs...", settings.RATE_LIMIT_DELAY_SECONDS)
                time.sleep(settings.RATE_LIMIT_DELAY_SECONDS)

        self._logger.info("Analyzed %d/%d leads successfully.", analyzed_count, len(leads))
        return analyzed_count

    def analyze_one(self, lead: Lead) -> Lead:
        """Analyze a single in-memory lead (no persistence). Useful for tests."""
        analysis = self._llm.analyze_business_needs(lead.business)
        lead.analysis = analysis
        return lead
