"""Enumerations used by domain models.

All enums inherit from ``str`` so they serialise natively to JSON via
Pydantic v2 — no custom encoder required.
"""

from __future__ import annotations

from enum import Enum


class DataSource(str, Enum):
    """Which scraper produced a given record."""

    OVERPASS = "overpass"        # OpenStreetMap Overpass API
    DUCKDUCKGO = "duckduckgo"    # DuckDuckGo HTML search
    SEARXNG = "searxng"          # Self-hosted SearXNG meta-search
    SOCIAL = "social"            # Headless social-media scraper
    MANUAL = "manual"            # Manually inserted via API/CLI
    MOCK = "mock"                # Built-in deterministic mock dataset
    INFINITE = "infinite"        # Autonomous infinite-crawler discovery


class LeadStatus(str, Enum):
    """Lifecycle of a lead inside the pipeline."""

    DISCOVERED = "discovered"    # raw business persisted
    ANALYZED = "analyzed"        # LLM analysis attached
    SCORED = "scored"            # priority score computed
    CONTACTED = "contacted"      # outreach started (manual flag)
    REJECTED = "rejected"        # marked as not-a-fit (manual flag)
    VERIFIED = "verified"        # human-verified as a real business


class PhoneType(str, Enum):
    """Classification produced by ``libphonenumber``."""

    MOBILE = "MOBILE"
    LANDLINE = "LANDLINE"
    VOIP = "VOIP"
    TOLL_FREE = "TOLL_FREE"
    PREMIUM_RATE = "PREMIUM_RATE"
    UNKNOWN = "UNKNOWN"


class FreshnessAge(str, Enum):
    """Coarse age bucket assigned by the freshness detector.

    The buckets are intentionally coarse so they remain useful as a filter
    even when the source only provides a vague "updated recently" hint.
    """

    HOURLY = "hour"        # discovered/updated within the last hour
    DAILY = "day"          # within the last 24 hours
    WEEKLY = "week"        # within the last 7 days
    MONTHLY = "month"      # within the last 30 days
    ARCHIVED = "older"     # older than 30 days, or no signal at all


class CrawlStatus(str, Enum):
    """Status of a URL inside the persistent crawl frontier."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ProxyHealthState(str, Enum):
    """Coarse health bucket for a proxy node."""

    HEALTHY = "healthy"      # success rate > 80%
    DEGRADED = "degraded"    # success rate 30%–80%
    UNHEALTHY = "unhealthy"  # success rate < 30% (rotated out)
    RECOVERING = "recovering"# was unhealthy, cooling down before re-test


class EntityType(str, Enum):
    """Type of a resolved entity — drives downstream routing."""

    BUSINESS = "business"
    PERSON = "person"
    ORGANISATION = "organisation"
    UNKNOWN = "unknown"


class ResolutionStrategy(str, Enum):
    """How a golden record was produced from raw records."""

    SINGLE = "single"            # only one raw record, no merge needed
    GRAPH_MERGE = "graph_merge"  # merged via the graph resolver
    MANUAL_MERGE = "manual_merge"# merged by a human operator via the UI
