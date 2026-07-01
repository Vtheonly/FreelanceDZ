"""Custom exception hierarchy for DZ Sales Intelligence.

Centralising exceptions makes error-handling code in services and infrastructure
layers cleaner: callers can catch `DzSalesIntelError` to handle any domain-level
failure, or catch a specific subclass for finer-grained recovery.
"""

from __future__ import annotations


class DzSalesIntelError(Exception):
    """Root exception for the entire platform."""


# ---------- Configuration & startup ----------

class ConfigurationError(DzSalesIntelError):
    """Raised when required configuration (API keys, paths, etc.) is missing or invalid."""


# ---------- Scraping ----------

class ScraperError(DzSalesIntelError):
    """Base class for any failure inside the scraping layer."""


class ScraperTimeoutError(ScraperError):
    """A scraper HTTP call exceeded its configured timeout."""


class ScraperParseError(ScraperError):
    """A scraper retrieved a response but failed to parse business records from it."""


# ---------- LLM ----------

class LLMError(DzSalesIntelError):
    """Base class for any failure inside the LLM client layer."""


class LLMRateLimitError(LLMError):
    """The upstream LLM provider returned 429 Too Many Requests after all retries."""


class LLMAuthError(LLMError):
    """The upstream LLM provider rejected the API key (401/403)."""


class LLMResponseParseError(LLMError):
    """The LLM returned a response that did not conform to the expected JSON schema."""


# ---------- Storage ----------

class StorageError(DzSalesIntelError):
    """Base class for any failure inside the persistence layer."""


class LeadNotFoundError(StorageError):
    """A lead was not found by its identifier."""


# ---------- Pipeline ----------

class PipelineError(DzSalesIntelError):
    """Base class for orchestration failures in the prospecting pipeline."""
