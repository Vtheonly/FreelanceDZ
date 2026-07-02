"""OpenRouter LLM client adapter.

OpenRouter aggregates many providers (Anthropic, Mistral, Meta, etc.)
behind a single OpenAI-compatible endpoint. Useful as a fallback when
the primary Groq key hits free-tier limits.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config.settings import AppSettings, get_settings
from infrastructure.llm.base import BaseLLMClient


_logger = logging.getLogger("infrastructure.llm.openrouter")


OPENROUTER_DEFAULT_BASE = "https://openrouter.ai/api/v1"


class OpenRouterLLMClient(BaseLLMClient):
    """LLM client that talks to the OpenRouter aggregator endpoint."""

    def __init__(
        self,
        settings: AppSettings | None = None,
        api_base: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(settings=settings, **kwargs)
        self._api_key = self._settings.LLM_API_KEY
        self._api_base = (api_base or OPENROUTER_DEFAULT_BASE).rstrip("/")
        _logger.debug("OpenRouter client ready (base=%s)", self._api_base)

    @property
    def provider_name(self) -> str:
        return "openrouter"

    async def _call_provider(
        self,
        *,
        prompt: str,
        system_prompt: str,
        model: str,
        timeout: float,
    ) -> str:
        if not self._api_key:
            raise httpx.HTTPError("OpenRouter API key is not configured")
        url = f"{self._api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            # OpenRouter recommends these for app attribution / ranking.
            "HTTP-Referer": "https://github.com/Vtheonly/FreelanceDZ",
            "X-Title": "FreelanceDZ Engine",
        }
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 2048,
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
