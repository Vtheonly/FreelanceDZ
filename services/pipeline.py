"""Prospecting pipeline — orchestrates discovery → analysis → scoring.

The pipeline is intentionally sequential to stay friendly with free-tier
rate limits. Each phase is independently invocable from the CLI.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from config.settings import settings
from core.interfaces import ILLMClient, ILeadPrioritizer, ILeadRepository, IScraper
from domain.models import Lead
from services.analyzer import LeadAnalyzerService
from services.scorer import LeadScoringEngine


class ProspectingPipeline:
    """End-to-end orchestrator: discover → persist → analyze → score → rank."""

    def __init__(
        self,
        scraper: IScraper,
        llm: ILLMClient,
        repo: ILeadRepository,
        prioritizer: Optional[ILeadPrioritizer] = None,
    ) -> None:
        self._scraper = scraper
        self._llm = llm
        self._repo = repo
        self._prioritizer = prioritizer or LeadScoringEngine()
        self._analyzer = LeadAnalyzerService(llm=llm, repo=repo)
        self._logger = logging.getLogger("services.pipeline")

    # ------------------------------------------------------------------
    # Phase 1: Discovery
    # ------------------------------------------------------------------

    def discover(
        self,
        query: str,
        wilaya: Optional[str] = None,
        limit: int = 10,
    ) -> int:
        """Run scrapers, persist new businesses. Returns the count of NEW leads saved."""
        self._logger.info("=== Phase 1: Discovery === (query=%r wilaya=%r limit=%d)", query, wilaya, limit)
        businesses = self._scraper.discover_businesses(query, wilaya, limit)
        self._logger.info("Scraper returned %d raw businesses.", len(businesses))

        new_count = 0
        for biz in businesses:
            biz_id = self._repo.save_business(biz)
            if biz_id is not None:
                new_count += 1
                self._logger.info("  + NEW lead id=%d: %s (%s, %s)", biz_id, biz.name, biz.industry, biz.wilaya)
            else:
                self._logger.debug("  = skip duplicate: %s", biz.name)
        self._logger.info("Phase 1 complete: %d new leads persisted (out of %d).", new_count, len(businesses))
        return new_count

    # ------------------------------------------------------------------
    # Phase 2: Analysis
    # ------------------------------------------------------------------

    def analyze(self, limit: int = 50, force: bool = False) -> int:
        """Run LLM analysis on pending leads. Returns count analyzed."""
        self._logger.info("=== Phase 2: LLM Analysis === (limit=%d, force=%s)", limit, force)
        return self._analyzer.analyze_pending(limit=limit, force=force)

    # ------------------------------------------------------------------
    # Phase 3: Scoring
    # ------------------------------------------------------------------

    def score(self, limit: int = 500) -> int:
        """Recompute scores for up to `limit` leads. Returns count scored."""
        self._logger.info("=== Phase 3: Scoring === (limit=%d)", limit)
        leads = self._repo.list_leads(min_score=0.0, limit=limit)
        scored = 0
        for lead in leads:
            if lead.id is None:
                continue
            score = self._prioritizer.calculate_score(lead)
            breakdown = (
                self._prioritizer.explain_score(lead)
                if hasattr(self._prioritizer, "explain_score")
                else None
            )
            self._repo.update_score(lead.id, score, breakdown)
            scored += 1
        self._logger.info("Phase 3 complete: %d leads scored.", scored)
        return scored

    # ------------------------------------------------------------------
    # Full run
    # ------------------------------------------------------------------

    def run_full_pipeline(
        self,
        query: str,
        wilaya: Optional[str] = None,
        discover_limit: int = 10,
        analyze_limit: int = 50,
    ) -> List[Lead]:
        """Discover → analyze → score, then return the top leads sorted by score."""
        self._logger.info("####### FULL PIPELINE RUN #######")
        self.discover(query, wilaya, discover_limit)
        self.analyze(limit=analyze_limit)
        self.score(limit=max(discover_limit * 5, 100))
        top_n = settings.TOP_LEADS_N
        leads = self._repo.list_leads(min_score=0.0, limit=top_n)
        self._logger.info("####### PIPELINE COMPLETE — top %d leads: #######", len(leads))
        for i, lead in enumerate(leads, start=1):
            self._logger.info(
                "  %2d. [%5.1f] %s (%s, %s) — est. value $%.0f",
                i, lead.priority_score, lead.business.name,
                lead.business.industry, lead.business.wilaya,
                lead.total_estimated_value_usd,
            )
        return leads
