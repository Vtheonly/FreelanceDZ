"""Base LLM client — shared HTTP + retry + cache + fallback logic.

Concrete providers (Groq, OpenRouter) inherit from this and only need to
implement `_provider_specific_payload_modifier()` (which is usually a no-op,
since both providers speak the OpenAI-compatible Chat Completions API).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

import requests

from config.industries import resolve_industry
from config.services_catalog import default_price_for
from config.settings import settings
from core.interfaces import ILLMClient
from domain.exceptions import (
    LLMAuthError,
    LLMError,
    LLMRateLimitError,
    LLMResponseParseError,
)
from domain.models import BusinessRaw, LeadAnalysis, ProposedService
from infrastructure.llm.cache import LLMCache
from infrastructure.llm.prompts import SYSTEM_PROMPT, build_health_check_prompt, build_user_prompt


# Bumped whenever we change the prompt meaningfully — invalidates all cached entries.
PROMPT_VERSION = "v1.0.0"


class BaseLLMClient(ILLMClient):
    """Common LLM client logic for OpenAI-compatible APIs."""

    provider_name: str = "base"

    def __init__(self) -> None:
        self._api_key = settings.LLM_API_KEY
        self._api_base = settings.LLM_API_BASE.rstrip("/")
        self._model = settings.LLM_MODEL
        self._timeout = settings.LLM_TIMEOUT_SECONDS
        self._max_retries = settings.LLM_MAX_RETRIES
        self._base_delay = settings.RATE_LIMIT_DELAY_SECONDS
        self._cache = LLMCache()
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        })
        self._logger = logging.getLogger(f"llm.{self.provider_name}")

    # ------------------------------------------------------------------
    # To be overridden by subclasses if needed.
    # ------------------------------------------------------------------

    def _provider_specific_payload_modifier(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Hook for provider-specific quirks (extra headers, body fields, ...)."""
        return payload

    def _provider_extra_headers(self) -> Dict[str, str]:
        """Hook for extra HTTP headers (e.g. OpenRouter's HTTP-Referer)."""
        return {}

    # ------------------------------------------------------------------
    # ILLMClient implementation
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """Send a tiny prompt to verify the API key and connectivity."""
        if not self._api_key:
            return False
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": "Reply with JSON only."},
                {"role": "user", "content": build_health_check_prompt()},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "max_tokens": 20,
        }
        try:
            resp = self._session.post(
                f"{self._api_base}/chat/completions",
                json=self._provider_specific_payload_modifier(payload),
                headers=self._provider_extra_headers() or None,
                timeout=self._timeout,
            )
            if resp.status_code in (401, 403):
                self._logger.error("Auth failed (%d) for %s.", resp.status_code, self.provider_name)
                return False
            return resp.status_code == 200
        except requests.RequestException as e:
            self._logger.warning("Health check request failed: %s", e)
            return False

    def analyze_business_needs(self, business: BusinessRaw) -> LeadAnalysis:
        """Analyse a business, with cache + retry + fallback."""
        if not self._api_key:
            self._logger.warning(
                "No API key configured — using fallback analyzer for %s.", business.name
            )
            return self._generate_fallback_analysis(business)

        # 1. Check cache.
        cached = self._cache.get(
            self.provider_name, self._model, business.fingerprint(), PROMPT_VERSION
        )
        if cached is not None:
            self._logger.info("Cache hit for %s — skipping LLM call.", business.name)
            analysis = self._parse_response(cached, business)
            analysis.from_cache = True
            analysis.analysis_model = self._model
            return analysis

        # 2. Build request payload.
        user_prompt = build_user_prompt(business)
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 1200,
        }
        payload = self._provider_specific_payload_modifier(payload)

        # 3. Call with exponential backoff.
        raw_response = self._call_with_retry(payload, business.name)
        if raw_response is None:
            self._logger.warning(
                "All LLM retries exhausted — using fallback for %s.", business.name
            )
            return self._generate_fallback_analysis(business)

        # 4. Parse + cache.
        try:
            analysis = self._parse_response(raw_response, business)
        except LLMResponseParseError as e:
            self._logger.error("Failed to parse LLM output for %s: %s", business.name, e)
            return self._generate_fallback_analysis(business)

        self._cache.set(
            self.provider_name,
            self._model,
            business.fingerprint(),
            PROMPT_VERSION,
            raw_response,
        )
        analysis.analysis_model = self._model
        return analysis

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _call_with_retry(self, payload: Dict[str, Any], business_name: str) -> Optional[dict]:
        """POST /chat/completions with exponential backoff. Returns parsed JSON or None."""
        delay = self._base_delay
        last_status: Optional[int] = None

        for attempt in range(1, self._max_retries + 1):
            try:
                self._logger.debug(
                    "[%s] Attempt %d/%d — calling %s",
                    business_name, attempt, self._max_retries, self.provider_name,
                )
                resp = self._session.post(
                    f"{self._api_base}/chat/completions",
                    json=payload,
                    headers=self._provider_extra_headers() or None,
                    timeout=self._timeout,
                )
                last_status = resp.status_code

                if resp.status_code == 200:
                    return self._extract_content_json(resp)

                if resp.status_code == 429:
                    self._logger.warning(
                        "[%s] HTTP 429 (rate limited) on attempt %d. Backing off %.1fs.",
                        business_name, attempt, delay,
                    )
                    time.sleep(delay)
                    delay *= 2
                    continue

                if resp.status_code in (401, 403):
                    raise LLMAuthError(
                        f"{self.provider_name} rejected API key (HTTP {resp.status_code})."
                    )

                if resp.status_code >= 500:
                    self._logger.warning(
                        "[%s] HTTP %d on attempt %d. Backing off %.1fs.",
                        business_name, resp.status_code, attempt, delay,
                    )
                    time.sleep(delay)
                    delay *= 2
                    continue

                # Other 4xx — log body, do not retry.
                self._logger.error(
                    "[%s] Unrecoverable HTTP %d: %s",
                    business_name, resp.status_code, resp.text[:300],
                )
                return None

            except LLMAuthError:
                raise
            except requests.exceptions.Timeout:
                self._logger.warning(
                    "[%s] Timeout on attempt %d. Backing off %.1fs.",
                    business_name, attempt, delay,
                )
                time.sleep(delay)
                delay *= 2
            except requests.RequestException as e:
                self._logger.warning(
                    "[%s] Request error on attempt %d: %s", business_name, attempt, e
                )
                time.sleep(delay)
                delay *= 2

        if last_status == 429:
            self._logger.error("[%s] Hit rate limit after all retries.", business_name)
        return None

    @staticmethod
    def _extract_content_json(resp: requests.Response) -> dict:
        """Pull `choices[0].message.content` and parse it as JSON."""
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        # Some models wrap JSON in markdown fences — strip them defensively.
        content = content.strip()
        if content.startswith("```"):
            content = content.strip("`")
            # Drop leading language tag like "json\n"
            if content.lower().startswith("json"):
                content = content[4:].lstrip()
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMResponseParseError(f"LLM output is not valid JSON: {e}") from e

    def _parse_response(self, data: dict, business: BusinessRaw) -> LeadAnalysis:
        """Convert raw LLM JSON dict into a strict `LeadAnalysis`."""
        if not isinstance(data, dict):
            raise LLMResponseParseError("LLM output is not a JSON object.")

        pain_points = data.get("pain_points", [])
        if not isinstance(pain_points, list):
            pain_points = []

        solutions: list[ProposedService] = []
        for sol in data.get("recommended_solutions", []) or []:
            if not isinstance(sol, dict):
                continue
            name = str(sol.get("service_name", "Custom Software")).strip()
            # Snap to known catalogue price if possible.
            value = float(sol.get("estimated_value_usd") or default_price_for(name))
            priority = int(sol.get("priority", 5))
            priority = max(1, min(10, priority))
            solutions.append(ProposedService(
                service_name=name,
                justification=str(sol.get("justification", ""))[:500],
                estimated_value_usd=value,
                priority=priority,
            ))

        digital_score = int(data.get("digital_presence_score", 50))
        digital_score = max(0, min(100, digital_score))

        pitch_angles = data.get("pitch_angles", [])
        if not isinstance(pitch_angles, list):
            pitch_angles = []

        est_revenue = data.get("estimated_monthly_revenue_usd")
        if est_revenue is not None:
            try:
                est_revenue = float(est_revenue)
            except (TypeError, ValueError):
                est_revenue = None

        if not solutions:
            # If LLM returned no usable solutions, fallback for this field.
            solutions = self._fallback_solutions(business)

        return LeadAnalysis(
            pain_points=[str(p) for p in pain_points][:10],
            recommended_solutions=solutions[:5],
            digital_presence_score=digital_score,
            pitch_angles=[str(p) for p in pitch_angles][:5],
            estimated_monthly_revenue_usd=est_revenue,
            analyzed_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )

    # ------------------------------------------------------------------
    # Deterministic fallback (no LLM required)
    # ------------------------------------------------------------------

    def _generate_fallback_analysis(self, business: BusinessRaw) -> LeadAnalysis:
        """Produce a usable analysis without calling the LLM."""
        self._logger.info("Generating fallback analysis for %s.", business.name)
        template = resolve_industry(business.industry)

        pain_points = [
            f"Limited digital presence for a {template.label} in {business.wilaya}.",
            "Heavy reliance on manual / phone-based customer interactions.",
            "No integrated software to track sales, inventory, or customers.",
        ]
        if business.website:
            pain_points[0] = (
                f"Website exists but may be outdated or not mobile-friendly for a {template.label}."
            )

        solutions = self._fallback_solutions(business)

        digital_score = template.expected_digital_gap
        if business.website:
            digital_score = min(100, digital_score + 25)
        if business.social_media_handles:
            digital_score = min(100, digital_score + 15)

        pitch_angles = [
            f"Help {business.name} modernise its operations with custom software tailored to Algerian {template.label}s.",
            f"Compete with larger chains in {business.wilaya} by improving online visibility and customer experience.",
        ]

        return LeadAnalysis(
            pain_points=pain_points,
            recommended_solutions=solutions,
            digital_presence_score=digital_score,
            pitch_angles=pitch_angles,
            estimated_monthly_revenue_usd=None,
            analysis_model=f"{self.provider_name}-fallback",
        )

    @staticmethod
    def _fallback_solutions(business: BusinessRaw) -> list[ProposedService]:
        """Generate 2-3 ProposedService objects based on the industry template."""
        template = resolve_industry(business.industry)
        services = []
        for svc_name in template.typical_services[:3]:
            services.append(ProposedService(
                service_name=svc_name,
                justification=(
                    f"Standard need for a {template.label} "
                    f"{'with no online presence' if not business.website else 'looking to upgrade its digital tools'}."
                ),
                estimated_value_usd=default_price_for(svc_name) or template.average_project_value_usd,
                priority=7,
            ))
        return services
