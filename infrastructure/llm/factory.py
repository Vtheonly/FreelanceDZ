"""LLM client factory.

Builds the right concrete client based on ``settings.LLM_PROVIDER``. When
the primary key is empty, returns ``None`` so the caller can fall back
to the heuristic analyzer without raising.
"""

from __future__ import annotations

import logging
from typing import Optional

from config.settings import AppSettings, get_settings
from core.exceptions import ConfigurationError
from core.interfaces import ILLMClient
from infrastructure.llm.base import BaseLLMClient
from infrastructure.llm.groq_client import GroqLLMClient
from infrastructure.llm.openrouter_client import OpenRouterLLMClient


_logger = logging.getLogger("infrastructure.llm.factory")


def build_llm_client(settings: Optional[AppSettings] = None) -> Optional[ILLMClient]:
    """Return an LLM client, or ``None`` if LLM is disabled.

    Raises ``ConfigurationError`` only when the provider is unknown —
    missing keys are treated as "LLM disabled" so the engine keeps
    running on the heuristic fallback.
    """
    settings = settings or get_settings()
    provider = settings.LLM_PROVIDER.lower()

    if not settings.LLM_API_KEY:
        _logger.info("LLM_API_KEY is empty — LLM features disabled, heuristic fallback active.")
        return None

    client: BaseLLMClient
    if provider == "groq":
        client = GroqLLMClient(settings=settings)
    elif provider == "openrouter":
        client = OpenRouterLLMClient(settings=settings)
    else:
        raise ConfigurationError(f"Unknown LLM_PROVIDER: {provider!r}")

    _logger.info(
        "LLM client built: provider=%s, models=%s, cache=%s",
        provider, client._models, settings.ENABLE_LLM_CACHE,
    )
    return client
