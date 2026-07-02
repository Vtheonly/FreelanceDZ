"""Domain-agnostic exception hierarchy.

Every exception inherits from ``CrawlerError`` so callers can catch the whole
family with a single ``except CrawlerError`` clause. Each subclass carries
enough semantic information for the logging middleware and the API layer to
produce meaningful responses without inspecting message strings.

Design rationale
----------------
* Avoid bare ``Exception`` raises — they force callers to swallow everything.
* Avoid ``except Exception`` blocks that hide bugs — use the most specific
  exception that matches the failure mode.
* Every exception is JSON-serialisable via ``str(exc)`` so it can be surfaced
  to API clients without leaking internals.
"""

from __future__ import annotations

from typing import Optional


class CrawlerError(Exception):
    """Root of every exception raised by the engine.

    Attributes
    ----------
    message:
        Human-readable description.
    cause:
        Optional underlying exception, kept for chaining without losing the
        original traceback (``raise ... from cause`` is preferred at call
        sites, this field is for inspection only).
    """

    def __init__(self, message: str, cause: Optional[BaseException] = None) -> None:
        super().__init__(message)
        self.message = message
        self.cause = cause

    def __str__(self) -> str:
        return self.message


class ConfigurationError(CrawlerError):
    """Raised when settings are missing, malformed, or inconsistent.

    Surfaced as HTTP 500 in the API layer because misconfiguration is a
    deployment-time problem, not a client error.
    """


class StorageError(CrawlerError):
    """Raised when the persistence layer (SQLite) fails.

    Includes schema-migration failures, connection timeouts, and constraint
    violations that the repository chose not to silently swallow.
    """


class ScrapingError(CrawlerError):
    """Raised when a scraper cannot fulfil a discovery request.

    Network timeouts, HTTP errors, and HTML parse failures all map here.
    The aggregator catches this per-scraper so one failing source never
    aborts the whole run.
    """

    def __init__(self, message: str, source: Optional[str] = None, cause: Optional[BaseException] = None) -> None:
        super().__init__(message, cause=cause)
        self.source = source


class DiscoveryError(CrawlerError):
    """Raised when the discovery service cannot orchestrate scrapers.

    Typically wraps a ``ScrapingError`` after all fallbacks are exhausted.
    """


class LLMError(CrawlerError):
    """Raised when every LLM provider in the fallback chain has failed.

    The analyzer catches this and degrades to the deterministic heuristic
    so the pipeline keeps producing results.
    """


class RateLimitError(CrawlerError):
    """Raised when a remote API returns HTTP 429 and retries are exhausted.

    Carries ``retry_after`` (seconds) when the API provided a ``Retry-After``
    header so callers can honour it before retrying.
    """

    def __init__(self, message: str, retry_after: Optional[float] = None, cause: Optional[BaseException] = None) -> None:
        super().__init__(message, cause=cause)
        self.retry_after = retry_after


class EntityResolutionError(CrawlerError):
    """Raised when the entity resolver cannot produce a consistent result.

    Usually indicates corrupted input data or a misconfigured threshold.
    """


class BlockDetectedError(CrawlerError):
    """Raised when the resilience layer detects a CAPTCHA or WAF block.

    Carries the detected signature so the proxy orchestrator can decide
    whether to rotate, back off, or skip the target.
    """

    def __init__(self, message: str, signature: Optional[str] = None, cause: Optional[BaseException] = None) -> None:
        super().__init__(message, cause=cause)
        self.signature = signature
