"""Groq LLM client — uses Groq's OpenAI-compatible API (free tier)."""

from __future__ import annotations

from infrastructure.llm.base import BaseLLMClient


class GroqLLMClient(BaseLLMClient):
    """Free-tier Groq chat completions client.

    Groq's API is OpenAI-compatible, so the base class does all the work.
    We just set the provider name and let the base class handle the rest.
    """

    provider_name = "groq"

    def _provider_specific_payload_modifier(self, payload):
        # Groq supports `response_format: {"type": "json_object"}` natively.
        return payload
