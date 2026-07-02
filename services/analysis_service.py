"""Analysis service — runs LLM analysis on pending leads.

Wraps the LLM client with retry/fallback logic and persists the
analysis back to the database. When the LLM is unavailable, the
heuristic fallback is used so the pipeline never stalls.
"""

from __future__ import annotations

import logging
from typing import Optional

from core.interfaces import ILLMClient, ILeadRepository, IRawRecordRepository
from domain.models import LeadAnalysis


_logger = logging.getLogger("services.analysis")


class AnalysisService:
    """Run LLM analysis on leads that don't have one yet."""

    def __init__(
        self,
        llm: Optional[ILLMClient],
        raw_repo: IRawRecordRepository,
        lead_repo: ILeadRepository,
    ) -> None:
        self._llm = llm
        self._raw_repo = raw_repo
        self._lead_repo = lead_repo

    async def analyze_pending(self, limit: int = 50) -> int:
        """Analyse up to ``limit`` leads that have no analysis yet.

        Returns the number of analyses actually produced.
        """
        records = await self._raw_repo.list_unresolved(limit=limit)
        _logger.info("Analysing %d pending leads (llm=%s)", len(records), bool(self._llm))
        analysed = 0
        for rec in records:
            biz = rec.to_business_raw()
            analysis = await self._analyze_one(biz)
            if analysis is not None and rec.id is not None:
                await self._lead_repo.attach_analysis(rec.id, analysis)
                analysed += 1
                _logger.info(
                    "Analysed lead id=%d (%s) — score=%d, solutions=%d",
                    rec.id, biz.name, analysis.digital_presence_score,
                    len(analysis.recommended_solutions),
                )
        _logger.info("Analysis batch complete: %d leads analysed", analysed)
        return analysed

    async def analyze_single(self, lead_id: int) -> Optional[LeadAnalysis]:
        """Analyse a single lead by ID. Returns the analysis or ``None``."""
        rec = await self._raw_repo.get_by_id(lead_id)
        if rec is None:
            return None
        biz = rec.to_business_raw()
        analysis = await self._analyze_one(biz)
        if analysis is not None:
            await self._lead_repo.attach_analysis(lead_id, analysis)
        return analysis

    # ------------------------------------------------------------------

    async def _analyze_one(self, business) -> Optional[LeadAnalysis]:
        if self._llm is None:
            # No LLM configured — use heuristic directly.
            from infrastructure.llm.fallback_heuristic import HeuristicAnalyzer
            return HeuristicAnalyzer().analyze(business)
        try:
            return await self._llm.analyze_business_needs(business)
        except Exception as exc:
            _logger.warning(
                "LLM analysis failed for %r (%s) — using heuristic.",
                business.name, exc,
            )
            from infrastructure.llm.fallback_heuristic import HeuristicAnalyzer
            return HeuristicAnalyzer().analyze(business)
