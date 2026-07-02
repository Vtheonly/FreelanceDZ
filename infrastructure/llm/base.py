"""Base LLM client — shared logic for every provider adapter.

Concrete providers (Groq, OpenRouter) inherit from this class and only
need to implement ``_call_provider``. The base class handles:

* Multi-model fallback chain (try each model in order until one works).
* Disk-based caching (via ``LLMCache``).
* Exponential backoff on rate-limit errors (HTTP 429).
* Heuristic fallback when every model and retry is exhausted.

This eliminates the original codebase's brittle single-model dependency.
"""

from __future__ import annotations

import json
import logging
from abc import abstractmethod
from typing import Any, Optional

import httpx

from config.settings import AppSettings, get_settings
from core.exceptions import LLMError, RateLimitError
from core.interfaces import ILLMClient
from domain.models import BusinessRaw, LeadAnalysis, ProposedService
from infrastructure.llm.cache import LLMCache
from infrastructure.llm.fallback_heuristic import HeuristicAnalyzer
from infrastructure.llm.prompts import (
    PROMPT_ANALYZE_BUSINESS,
    PROMPT_EXPAND_QUERY,
    SYSTEM_PROMPT_ANALYZER,
    SYSTEM_PROMPT_QUERY_EXPANDER,
)
from utils.retry import retry_with_backoff


_logger = logging.getLogger("infrastructure.llm.base")


class BaseLLMClient(ILLMClient):
    """Abstract base implementing the shared LLM orchestration logic.

    Subclasses implement ``_call_provider`` (the actual HTTP call to the
    provider) and ``provider_name``. Everything else — caching, retries,
    fallback chain, JSON parsing — is handled here.
    """

    def __init__(
        self,
        settings: Optional[AppSettings] = None,
        cache: Optional[LLMCache] = None,
        heuristic: Optional[HeuristicAnalyzer] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._cache = cache or LLMCache(enabled=self._settings.ENABLE_LLM_CACHE)
        self._heuristic = heuristic or HeuristicAnalyzer()
        self._models = self._settings.llm_models_list or ["llama-3.1-8b-instant"]
        self._api_key = self._settings.LLM_API_KEY
        self._api_base = self._settings.LLM_API_BASE

    # ------------------------------------------------------------------
    #  Public API (from ILLMClient)
    # ------------------------------------------------------------------

    async def analyze_business_needs(self, business: BusinessRaw) -> LeadAnalysis:
        """Analyse a business and return a structured ``LeadAnalysis``.

        Strategy:
        1. Build the prompt.
        2. Try cache.
        3. Try each model in the fallback chain (with retries).
        4. On total failure, return the heuristic analysis.
        """
        if not self._api_key:
            _logger.debug("No LLM_API_KEY — using heuristic for %r", business.name)
            return self._heuristic.analyze(business)

        prompt = PROMPT_ANALYZE_BUSINESS.format(
            business_json=business.model_dump_json(indent=2)
        )

        # 1. Cache lookup.
        for model in self._models:
            cached = self._cache.get(prompt, model)
            if cached is not None:
                _logger.debug("Cache hit for %r on model %s", business.name, model)
                return self._parse_analysis(cached["response"], model, from_cache=True)

        # 2. Live call with model fallback.
        last_error: Optional[Exception] = None
        for model in self._models:
            try:
                raw = await self._call_with_retry(
                    prompt=prompt,
                    system_prompt=SYSTEM_PROMPT_ANALYZER,
                    model=model,
                )
                parsed = self._safe_json(raw)
                if parsed is None:
                    _logger.warning("Model %s returned non-JSON; trying next.", model)
                    continue
                self._cache.set(prompt, model, parsed)
                return self._parse_analysis(parsed, model, from_cache=False)
            except RateLimitError as exc:
                last_error = exc
                _logger.warning("Rate-limited on model %s; trying next.", model)
                continue
            except (httpx.HTTPError, LLMError) as exc:
                last_error = exc
                _logger.warning("Model %s failed (%s); trying next.", model, exc)
                continue

        _logger.error(
            "Every LLM model failed for %r; falling back to heuristic. Last error: %s",
            business.name,
            last_error,
        )
        return self._heuristic.analyze(business)

    async def expand_query(self, query: str) -> list[str]:
        """Generate FR / MSA / Darja query variants via the LLM."""
        if not self._api_key:
            return []
        prompt = PROMPT_EXPAND_QUERY.format(query=query)
        for model in self._models:
            try:
                raw = await self._call_with_retry(
                    prompt=prompt,
                    system_prompt=SYSTEM_PROMPT_QUERY_EXPANDER,
                    model=model,
                )
                parsed = self._safe_json(raw)
                if isinstance(parsed, list):
                    return [str(t).strip() for t in parsed if str(t).strip()]
                _logger.warning("Query expander returned non-list from %s", model)
            except (RateLimitError, httpx.HTTPError, LLMError) as exc:
                _logger.warning("Query expansion failed on %s: %s", model, exc)
                continue
        return []

    async def health_check(self) -> bool:
        """Lightweight check — returns True if any model responds."""
        if not self._api_key:
            return False
        for model in self._models:
            try:
                await self._call_with_retry(
                    prompt="ping",
                    system_prompt="Reply with the single word: pong",
                    model=model,
                )
                return True
            except Exception:
                continue
        return False

    # ------------------------------------------------------------------
    #  Abstract — provider-specific HTTP call
    # ------------------------------------------------------------------

    @abstractmethod
    async def _call_provider(
        self,
        *,
        prompt: str,
        system_prompt: str,
        model: str,
        timeout: float,
    ) -> str:
        """Make a single HTTP call to the provider and return raw text."""

    # ------------------------------------------------------------------
    #  Internals
    # ------------------------------------------------------------------

    @retry_with_backoff(
        max_retries=3,
        base_delay=2.0,
        exceptions=(httpx.HTTPStatusError, httpx.NetworkError, httpx.TimeoutException),
    )
    async def _call_with_retry(self, *, prompt: str, system_prompt: str, model: str) -> str:
        """Wrap the provider call with retry + rate-limit detection."""
        try:
            return await self._call_provider(
                prompt=prompt,
                system_prompt=system_prompt,
                model=model,
                timeout=float(self._settings.LLM_TIMEOUT_SECONDS),
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                retry_after = exc.response.headers.get("Retry-After")
                raise RateLimitError(
                    f"HTTP 429 from {model}",
                    retry_after=float(retry_after) if retry_after else None,
                    cause=exc,
                ) from exc
            raise

    @staticmethod
    def _safe_json(raw: str) -> Any:
        """Parse JSON from an LLM response that may include code fences."""
        if not raw:
            return None
        # Strip markdown code fences if present.
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            # Remove the opening fence (with optional language) and the closing fence.
            first_newline = cleaned.find("\n")
            if first_newline != -1:
                cleaned = cleaned[first_newline + 1:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to find the first JSON object/array in the text.
            for start_char, end_char in [("{", "}"), ("[", "]")]:
                start = cleaned.find(start_char)
                end = cleaned.rfind(end_char)
                if start != -1 and end != -1 and end > start:
                    try:
                        return json.loads(cleaned[start : end + 1])
                    except json.JSONDecodeError:
                        continue
            return None

    def _parse_analysis(
        self,
        payload: dict[str, Any],
        model: str,
        *,
        from_cache: bool,
    ) -> LeadAnalysis:
        """Convert the parsed JSON dict into a validated ``LeadAnalysis``."""
        solutions = []
        for s in payload.get("recommended_solutions", []):
            try:
                solutions.append(ProposedService(**s))
            except Exception as exc:
                _logger.debug("Skipped malformed solution %r: %s", s, exc)
        return LeadAnalysis(
            pain_points=list(payload.get("pain_points", [])),
            recommended_solutions=solutions,
            digital_presence_score=int(payload.get("digital_presence_score", 50)),
            pitch_angles=list(payload.get("pitch_angles", [])),
            estimated_monthly_revenue_usd=payload.get("estimated_monthly_revenue_usd"),
            analysis_model=model,
            from_cache=from_cache,
        )
