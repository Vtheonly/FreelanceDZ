"""Abstract contracts (ports) for every adapter in the engine.

The application depends on these interfaces, never on concrete classes.
This is the Dependency Inversion Principle in action: high-level policy
(services) does not import low-level detail (httpx, sqlite3, openai);
both depend on the abstractions defined here.

Concrete implementations live in "infrastructure/" and are wired into
services by "api/dependencies.py".
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, AsyncIterator, Optional, Protocol

from domain.enums import CrawlStatus, FreshnessAge, LeadStatus
from domain.models import BusinessRaw, Lead, LeadAnalysis, RawRecord, ResolvedEntity
from domain.value_objects import PhoneDetails


# ============================================================
#  SCRAPERS
# ============================================================

class IScraper(ABC):
    """Discovers raw business records from a single source.

    Every scraper is async because the whole engine is async — there is no
    synchronous fallback. Implementations MUST:

    * Return an empty list (not raise) on network failure so the aggregator
      can continue with the next source.
    * Tag every "BusinessRaw" with the correct "DataSource".
    * Honour the configured timeout per request.
    * Apply pagination internally when "limit" exceeds a single page.
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Short, stable identifier (e.g. 'duckduckgo', 'overpass')."""

    @abstractmethod
    async def discover(
        self,
        query: str,
        wilaya: Optional[str] = None,
        limit: int = 10,
    ) -> list[BusinessRaw]:
        """Return up to "limit" businesses matching "query" near "wilaya"."""


class IScraperPlugin(IScraper):
    """Extension point for platform-specific scrapers (Facebook, Instagram, etc.).

    Plugins are loaded dynamically by the aggregator based on configuration.
    A plugin differs from a base scraper in that it accepts a *target URL*
    (a specific profile/page) rather than a free-text query.
    """

    @abstractmethod
    async def scrape_target(self, url: str) -> Optional[BusinessRaw]:
        """Scrape a specific profile/page URL and return a business record."""


# ============================================================
#  AGGREGATOR
# ============================================================

class IDiscoveryAggregator(ABC):
    """Coordinates multiple scrapers to exhaustively reach a target limit.

    The aggregator is responsible for:

    * Expanding the query (FR / AR / Darja) before dispatching.
    * Cycling through scrapers and paginated queries until "limit" valid
      records are gathered (or every source is genuinely exhausted).
    * Deduplicating within the run via "BusinessRaw.fingerprint()".
    * Never raising — partial results are always returned.
    """

    @abstractmethod
    async def discover_exhaustive(
        self,
        query: str,
        wilaya: Optional[str] = None,
        limit: int = 30,
    ) -> list[BusinessRaw]:
        ...


# ============================================================
#  HTTP CLIENT (managed pool)
# ============================================================

class IHttpClient(Protocol):
    """Minimal async HTTP contract — subset of "httpx.AsyncClient".

    Defined as a Protocol so any duck-typed async client works, but in
    practice we always use the managed "httpx.AsyncClient" singleton.
    """

    async def get(self, url: str, **kwargs: Any) -> Any: ...
    async def post(self, url: str, **kwargs: Any) -> Any: ...
    async def aclose(self) -> None: ...


# ============================================================
#  LLM CLIENTS
# ============================================================

class ILLMClient(ABC):
    """Calls an LLM provider to analyse a business and produce a "LeadAnalysis".

    Implementations MUST:
    * Handle HTTP 429 with exponential backoff (delegated to "tenacity").
    * Cache responses when caching is enabled.
    * Fall back to a deterministic heuristic if all retries fail.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    async def analyze_business_needs(self, business: BusinessRaw) -> LeadAnalysis: ...

    @abstractmethod
    async def expand_query(self, query: str) -> list[str]:
        """Return FR / MSA / Darja variants of "query"."""

    @abstractmethod
    async def health_check(self) -> bool: ...


# ============================================================
#  LEAD PRIORITIZER
# ============================================================

class ILeadPrioritizer(ABC):
    """Computes a deterministic priority score (0–100) for a lead."""

    @abstractmethod
    def calculate_score(self, lead: Lead) -> float: ...

    @abstractmethod
    def explain_score(self, lead: Lead) -> dict[str, float]: ...


# ============================================================
#  REPOSITORIES
# ============================================================

class IRawRecordRepository(ABC):
    """CRUD for the "raw_records" table (immutable scrape results)."""

    @abstractmethod
    async def save(self, business: BusinessRaw) -> Optional[int]:
        """Insert or update on fingerprint conflict. Returns row id."""

    @abstractmethod
    async def get_by_id(self, record_id: int) -> Optional[RawRecord]: ...

    @abstractmethod
    async def list_all(self, limit: int = 1000, offset: int = 0) -> list[RawRecord]: ...

    @abstractmethod
    async def list_unresolved(self, limit: int = 1000) -> list[RawRecord]: ...

    @abstractmethod
    async def count(self) -> int: ...


class IResolvedEntityRepository(ABC):
    """CRUD for the "resolved_entities" table (golden records)."""

    @abstractmethod
    async def upsert(self, entity: ResolvedEntity) -> Optional[int]: ...

    @abstractmethod
    async def get_by_id(self, entity_id: int) -> Optional[ResolvedEntity]: ...

    @abstractmethod
    async def list_all(
        self,
        wilaya: Optional[str] = None,
        industry: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ResolvedEntity]: ...

    @abstractmethod
    async def count(self) -> int: ...

    @abstractmethod
    async def delete_all(self) -> int: ...

    @abstractmethod
    async def get_lineage(self, entity_id: int) -> list[dict]:
        """Return every raw record that contributed to "entity_id"."""


class ILeadRepository(ABC):
    """Read-side repository that joins raw records + analyses + scores."""

    @abstractmethod
    async def attach_analysis(self, business_id: int, analysis: LeadAnalysis) -> None: ...

    @abstractmethod
    async def update_score(
        self, business_id: int, score: float, breakdown: Optional[dict[str, float]] = None
    ) -> None: ...

    @abstractmethod
    async def set_status(self, business_id: int, status: LeadStatus) -> None: ...

    @abstractmethod
    async def set_tags(self, business_id: int, tags: list[str]) -> None: ...

    @abstractmethod
    async def get_lead(self, lead_id: int) -> Optional[Lead]: ...

    @abstractmethod
    async def list_leads(
        self,
        wilaya: Optional[str] = None,
        industry: Optional[str] = None,
        age_class: Optional[FreshnessAge] = None,
        min_score: float = 0.0,
        is_contact: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Lead]: ...

    @abstractmethod
    async def count_leads(self) -> int: ...

    @abstractmethod
    async def count_analyzed(self) -> int: ...

    @abstractmethod
    async def search(self, term: str, is_contact: Optional[bool] = None, limit: int = 50) -> list[Lead]: ...

    @abstractmethod
    async def stats(self) -> dict[str, Any]: ...

    @abstractmethod
    async def set_contact_status(self, business_id: int, is_contact: bool) -> None:
        """Mark a lead as a contact or remove it from the contacts list."""

    @abstractmethod
    async def update_lead_details(
        self,
        business_id: int,
        name: str,
        tags: list[str],
        address: Optional[str] = None,
        website: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
    ) -> None:
        """Persist user overrides and inline modifications directly to raw records and metadata scores."""

    @abstractmethod
    async def get_search_vocabulary(self) -> list[str]:
        """Tokenize and compile all unique, queryable words in the database for instant suggestions."""

    @abstractmethod
    async def bulk_set_contact_status(self, business_ids: list[int], is_contact: bool) -> None:
        """Mark multiple leads as contacts or remove them from the contacts list in a single batch."""

    @abstractmethod
    async def bulk_set_status(self, business_ids: list[int], status: LeadStatus) -> None:
        """Set the workflow status of multiple leads concurrently."""


class ICrawlQueueRepository(ABC):
    """Persistent priority queue for the infinite crawler."""

    @abstractmethod
    async def add_url(self, url: str, priority: int = 1, depth: int = 0) -> bool: ...

    @abstractmethod
    async def get_next_url(self) -> Optional[tuple[int, str, int]]:
        """Returns "(queue_id, url, depth)" or "None" if queue is empty."""

    @abstractmethod
    async def update_status(self, queue_id: int, success: bool) -> None: ...

    @abstractmethod
    async def count_by_status(self, status: CrawlStatus) -> int: ...

    @abstractmethod
    async def reset_stale_processing(self, older_than_seconds: int = 600) -> int: ...


# ============================================================
#  ENTITY RESOLVER
# ============================================================

class IEntityResolver(ABC):
    """Merges duplicate raw records into golden "ResolvedEntity" rows."""

    @abstractmethod
    async def resolve(self, records: list[RawRecord]) -> list[ResolvedEntity]:
        """Run graph-based resolution and return the merged entities."""


# ============================================================
#  RESILIENCE
# ============================================================

class IProxyOrchestrator(ABC):
    """Stateful proxy pool with health tracking and block detection."""

    @abstractmethod
    def get_proxy(self) -> Optional[str]: ...

    @abstractmethod
    def report_outcome(self, proxy_url: str, success: bool) -> None: ...

    @abstractmethod
    def evaluate_response(self, response: Any) -> bool:
        """Return True if the response looks like a block / CAPTCHA page."""


# ============================================================
#  PHONE VALIDATOR
# ============================================================

class IPhoneValidator(ABC):
    """Extracts and validates phone numbers from raw text."""

    @abstractmethod
    def extract_and_validate(
        self, text: str, default_region: str = "DZ"
    ) -> list[PhoneDetails]: ...


# ============================================================
#  FRESHNESS DETECTOR
# ============================================================

class IFreshnessDetector(ABC):
    """Extracts temporal metadata from text/headers."""

    @abstractmethod
    def detect(
        self,
        text: str,
        headers: Optional[dict[str, str]] = None,
    ) -> "Any":
        """Return a "FreshnessMetadata" value object."""


# ============================================================
#  SPAM FILTER
# ============================================================

class ISpamFilter(ABC):
    """Decides whether a URL/title is a directory aggregator or spam."""

    @abstractmethod
    def is_spam(self, url: str, title: str) -> bool: ...


# ============================================================
#  QUERY EXPANDER
# ============================================================

class IQueryExpander(ABC):
    """Expands a base query into FR / MSA / Darja variants."""

    @abstractmethod
    async def expand(self, base_query: str) -> list[str]: ...