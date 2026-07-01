"""OpenRouter LLM client — uses OpenRouter's OpenAI-compatible API (free models).

OpenRouter requires two extra HTTP headers:
  * `HTTP-Referer`: a site URL representing the calling app (optional but recommended).
  * `X-Title`: app name (optional but recommended).
"""

from __future__ import annotations

from infrastructure.llm.base import BaseLLMClient


class OpenRouterLLMClient(BaseLLMClient):
    """Free-tier OpenRouter chat completions client."""

    provider_name = "openrouter"

    def _provider_extra_headers(self):
        return {
            "HTTP-Referer": "https://github.com/local/dz-sales-intelligence",
            "X-Title": "DZ Sales Intelligence",
        }

    def _provider_specific_payload_modifier(self, payload):
        # OpenRouter supports `response_format: {"type": "json_object"}` for many models,
        # but some free models ignore it. We keep it; if it fails the base class's
        # markdown-fence-stripping logic will still recover the JSON.
        return payload
