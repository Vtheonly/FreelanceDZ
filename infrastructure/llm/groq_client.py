"""Groq LLM client adapter.

Uses the OpenAI-compatible Groq API (``https://api.groq.com/openai/v1``).
Groq offers a generous free tier with low latency, making it ideal for
the primary model slot.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config.settings import AppSettings, get_settings
from infrastructure.llm.base import BaseLLMClient


_logger = logging.getLogger("infrastructure.llm.groq")


class GroqLLMClient(BaseLLMClient):
    """LLM client that talks to the Groq OpenAI-compatible endpoint."""

    def __init__(self, settings: AppSettings | None = None, **kwargs: Any) -> None:
        super().__init__(settings=settings, **kwargs)
        # Groq shares the OpenAI client surface; we use httpx directly to
        # avoid a hard dependency on the ``openai`` package at import time.
        self._api_key = self._settings.LLM_API_KEY
        self._api_base = self._settings.LLM_API_BASE.rstrip("/")
        _logger.debug("Groq client ready (base=%s, models=%s)", self._api_base, self._models)

    @property
    def provider_name(self) -> str:
        return "groq"

    async def _call_provider(
        self,
        *,
        prompt: str,
        system_prompt: str,
        model: str,
        timeout: float,
    ) -> str:
        if not self._api_key:
            raise httpx.HTTPError("Groq API key is not configured")
        url = f"{self._api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
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
