"""Core package — cross-cutting concerns shared by every layer.

This package deliberately contains no business logic. It only exposes:
  * Domain-agnostic exceptions (``core.exceptions``).
  * Abstract contracts every adapter must implement (``core.interfaces``).
  * Structured logging configuration (``core.logging_setup``).
  * Application lifecycle helpers (``core.lifecycle``).
  * Shared constants and enums (``core.constants``).

Note: ``ApplicationLifecycle`` is *not* imported eagerly here because it
depends on ``config.settings``, which itself depends on ``core.constants``.
Importing it lazily avoids a circular import at package-load time.
"""

from core.exceptions import (
    ConfigurationError,
    CrawlerError,
    DiscoveryError,
    EntityResolutionError,
    LLMError,
    RateLimitError,
    ScrapingError,
    StorageError,
)

__all__ = [
    "ConfigurationError",
    "CrawlerError",
    "DiscoveryError",
    "EntityResolutionError",
    "LLMError",
    "RateLimitError",
    "ScrapingError",
    "StorageError",
]
