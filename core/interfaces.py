"""Abstract base classes (contracts) for the entire platform.

Every concrete adapter in `infrastructure/` MUST implement one of these
interfaces. This guarantees that:
  * Services depend on abstractions, not concrete classes (Dependency Inversion).
  * Any scraper / LLM / repository can be swapped without touching services.
  * Unit tests can inject mock implementations trivially.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from domain.models import BusinessRaw, Lead, LeadAnalysis


# ============================================================================
#  SCRAPERS
# ============================================================================

class IScraper(ABC):
    """Discovers raw business records from a single source (OSM, DDG, mock, ...)."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """A short, stable identifier (e.g. 'overpass', 'duckduckgo', 'mock')."""

    @abstractmethod
    def discover_businesses(
        self,
        query: str,
        wilaya: Optional[str] = None,
        limit: int = 10,
    ) -> List[BusinessRaw]:
        """Return up to `limit` businesses matching `query` near `wilaya`.

        Implementations MUST:
          * Be safe to call when offline / rate-limited (return [] rather than raise).
          * Tag every returned BusinessRaw with the correct `DataSource`.
          * Never block forever — respect the configured timeout.
        """


# ============================================================================
#  LLM CLIENTS
# ============================================================================

class ILLMClient(ABC):
    """Calls an LLM provider to analyse a business and produce a `LeadAnalysis`."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider identifier (e.g. 'groq', 'openrouter')."""

    @abstractmethod
    def analyze_business_needs(self, business: BusinessRaw) -> LeadAnalysis:
        """Analyse a business and return a structured `LeadAnalysis`.

        Implementations MUST:
          * Handle HTTP 429 with exponential backoff.
          * Cache responses when caching is enabled.
          * Fall back to a deterministic heuristic if all retries fail.
        """

    @abstractmethod
    def health_check(self) -> bool:
        """Lightweight ping — returns True if the provider is reachable & authed."""


# ============================================================================
#  LEAD PRIORITIZER
# ============================================================================

class ILeadPrioritizer(ABC):
    """Computes a deterministic priority score (0–100) for a lead."""

    @abstractmethod
    def calculate_score(self, lead: Lead) -> float:
        """Return a score in [0.0, 100.0]."""

    @abstractmethod
    def explain_score(self, lead: Lead) -> Dict[str, float]:
        """Return a per-factor breakdown of the score for transparency/debug."""


# ============================================================================
#  REPOSITORY
# ============================================================================

class ILeadRepository(ABC):
    """Persistent storage for leads."""

    @abstractmethod
    def init_schema(self) -> None:
        """Create tables/indexes if they don't exist (idempotent)."""

    @abstractmethod
    def save_business(self, business: BusinessRaw) -> Optional[int]:
        """Insert (or skip if duplicate by fingerprint). Return row id or None if dup."""

    @abstractmethod
    def attach_analysis(self, business_id: int, analysis: LeadAnalysis) -> None:
        """Persist the LLM analysis for an existing business."""

    @abstractmethod
    def update_score(self, business_id: int, score: float) -> None:
        """Update the priority score of an existing business."""

    @abstractmethod
    def list_unanalyzed(self, limit: int = 100) -> List[Lead]:
        """Return leads that have no analysis attached yet."""

    @abstractmethod
    def list_leads(
        self,
        wilaya: Optional[str] = None,
        industry: Optional[str] = None,
        min_score: float = 0.0,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Lead]:
        """Filter/sort leads. Sorted by priority_score desc."""

    @abstractmethod
    def get_lead(self, lead_id: int) -> Optional[Lead]:
        """Fetch a single lead by ID."""

    @abstractmethod
    def count_leads(self) -> int:
        """Total number of leads in the database."""

    @abstractmethod
    def count_analyzed(self) -> int:
        """Number of leads with an analysis attached."""

    @abstractmethod
    def search(self, term: str, limit: int = 50) -> List[Lead]:
        """Full-text search across business name / industry / wilaya."""

    @abstractmethod
    def stats(self) -> Dict[str, Any]:
        """Aggregate statistics for the dashboard."""
    
    @abstractmethod
    def set_tags(self, business_id: int, tags: List[str]) -> None:
        """Update custom user tags for a business."""