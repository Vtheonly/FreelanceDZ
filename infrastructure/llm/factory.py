"""LLM client factory — picks the right client based on settings."""

from __future__ import annotations

import logging

from config.settings import settings
from core.interfaces import ILLMClient
from domain.exceptions import ConfigurationError
from infrastructure.llm.groq_client import GroqLLMClient
from infrastructure.llm.openrouter_client import OpenRouterLLMClient


def build_llm_client() -> ILLMClient:
    """Build the configured LLM client.

    Raises:
        ConfigurationError: if the provider is unknown.
    """
    logger = logging.getLogger("llm.factory")
    provider = settings.LLM_PROVIDER.lower()

    if provider == "groq":
        logger.info("Building Groq LLM client (model=%s).", settings.LLM_MODEL)
        return GroqLLMClient()
    if provider == "openrouter":
        logger.info("Building OpenRouter LLM client (model=%s).", settings.LLM_MODEL)
        return OpenRouterLLMClient()
    raise ConfigurationError(f"Unknown LLM_PROVIDER: {provider!r}")
