"""Domain models — the canonical data shapes used across the engine.

Every model is a Pydantic v2 "BaseModel" so we get validation, JSON
serialisation, and OpenAPI generation for free. Models are deliberately
*immutable* ("model_config = ConfigDict(frozen=True)") for the value
objects and mutable for the aggregate roots ("Lead", "ResolvedEntity")
because their lifecycle is owned by the application.

Design rules
------------
* A "BusinessRaw" represents **exactly one scrape** — never a merged view.
  Two scrapes of the same real-world business produce two "BusinessRaw"
  instances; the entity resolver merges them later.
* The "fingerprint()" method is the **only** identity key used for
  deduplication inside a single scrape run. Cross-run deduplication is the
  resolver's job (it uses graph similarity, not exact fingerprints).
* Every timestamp is timezone-aware UTC.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from domain.enums import (
    CrawlStatus,
    DataSource,
    EntityType,
    FreshnessAge,
    LeadStatus,
    PhoneType,
    ProxyHealthState,
    ResolutionStrategy,
)
from domain.value_objects import FreshnessMetadata, GeoPoint, PhoneDetails


# ============================================================
#  RAW BUSINESS (one per scrape)
# ============================================================

class BusinessRaw(BaseModel):
    """A discovered business, exactly as extracted from a single source.

    This is the *immutable* unit of ingestion: every scraper produces a
    stream of "BusinessRaw" instances, and the storage layer persists
    them verbatim into "raw_records". Merging happens later, in the
    entity-resolution phase, and never mutates these objects.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, description="Business name as scraped")
    industry: str = Field(..., description="Sector/category supplied by the caller")
    wilaya: str = Field(..., description="Algerian wilaya name (or 'Unknown')")
    address: Optional[str] = Field(None, description="Street address if available")
    website: Optional[str] = Field(None, description="Canonical website URL")
    phone: Optional[str] = Field(None, description="Primary phone in E.164 (may be None)")
    email: Optional[str] = Field(None, description="Public contact email if any")
    social_media_handles: list[str] = Field(
        default_factory=list,
        description="Social profile URLs (Facebook/Instagram/LinkedIn/etc.)",
    )
    rating: float = Field(default=0.0, ge=0.0, le=5.0)
    review_count: int = Field(default=0, ge=0)
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    source: DataSource = Field(default=DataSource.MOCK)
    source_url: Optional[str] = Field(None, description="Direct URL of the source page")
    phone_metadata: list[PhoneDetails] = Field(default_factory=list)
    freshness: FreshnessMetadata = Field(default_factory=FreshnessMetadata)
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_html_hash: Optional[str] = Field(
        None,
        description="SHA-256 of the scraped HTML — used to skip re-processing unchanged pages",
    )

    def fingerprint(self) -> str:
        """A stable identity key for *intra-run* deduplication.

        Combines normalised name + wilaya + phone + website. When the phone
        is missing we fall back to the website so two scrapes of the same
        site don't collide on the empty-phone branch.
        """
        norm_name = "".join(c.lower() for c in self.name if c.isalnum())
        norm_wilaya = (self.wilaya or "").strip().lower()
        norm_phone = "".join(c for c in (self.phone or "") if c.isdigit())
        norm_web = ""
        if self.website:
            norm_web = (
                self.website.lower()
                .replace("https://", "")
                .replace("http://", "")
                .replace("www.", "")
                .strip("/")
            )
        return f"{norm_name}|{norm_wilaya}|{norm_phone}|{norm_web}"

    def to_resolver_dict(self) -> dict[str, Any]:
        """Project to the minimal dict shape consumed by the graph resolver."""
        return {
            "name": self.name,
            "website": self.website,
            "phones": [p.e164 for p in self.phone_metadata] or ([self.phone] if self.phone else []),
            "email": self.email,
            "address": self.address,
            "wilaya": self.wilaya,
            "industry": self.industry,
        }


# ============================================================
#  LEAD (business + analysis + score)
# ============================================================

class ProposedService(BaseModel):
    """A software service the LLM recommends pitching to the business."""

    model_config = ConfigDict(extra="ignore")

    service_name: str
    justification: str
    estimated_value_usd: float = Field(..., ge=0.0)
    priority: int = Field(default=5, ge=1, le=10)


class LeadAnalysis(BaseModel):
    """LLM-generated analysis of a single business."""

    model_config = ConfigDict(extra="ignore")

    pain_points: list[str] = Field(default_factory=list)
    recommended_solutions: list[ProposedService] = Field(default_factory=list)
    digital_presence_score: int = Field(default=50, ge=0, le=100)
    pitch_angles: list[str] = Field(default_factory=list)
    estimated_monthly_revenue_usd: Optional[float] = Field(None, ge=0.0)
    analysis_model: Optional[str] = Field(None, description="LLM model that produced this")
    from_cache: bool = Field(default=False)
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Lead(BaseModel):
    """A complete lead: raw business + (optional) analysis + score."""

    model_config = ConfigDict(extra="ignore")

    id: Optional[int] = None
    business: BusinessRaw
    analysis: Optional[LeadAnalysis] = None
    priority_score: float = Field(default=0.0, ge=0.0, le=100.0)
    score_breakdown: Optional[dict[str, float]] = None
    status: LeadStatus = Field(default=LeadStatus.DISCOVERED)
    tags: list[str] = Field(default_factory=list)
    is_contact: bool = Field(default=False, description="Whether this lead is saved to the contacts/outreach queue")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_analyzed(self) -> bool:
        return self.analysis is not None

    @property
    def total_estimated_value_usd(self) -> float:
        if not self.analysis:
            return 0.0
        return round(
            sum(s.estimated_value_usd for s in self.analysis.recommended_solutions), 2
        )


# ============================================================
#  RAW RECORD (storage projection)
# ============================================================

class RawRecord(BaseModel):
    """Storage-layer projection of a "BusinessRaw" row.

    Adds the database "id" and the "fingerprint" used as the unique
    constraint. This is what the entity resolver reads from the database.
    """

    model_config = ConfigDict(extra="ignore")

    id: int
    fingerprint: str
    name: str
    industry: str
    wilaya: str
    address: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    social_media_handles: list[str] = Field(default_factory=list)
    rating: float = 0.0
    review_count: int = 0
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    source: DataSource = DataSource.MOCK
    source_url: Optional[str] = None
    phone_metadata: list[PhoneDetails] = Field(default_factory=list)
    freshness: FreshnessMetadata = Field(default_factory=FreshnessMetadata)
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_business_raw(self) -> BusinessRaw:
        """Reconstruct the in-memory "BusinessRaw" for downstream processing."""
        return BusinessRaw(
            name=self.name,
            industry=self.industry,
            wilaya=self.wilaya,
            address=self.address,
            website=self.website,
            phone=self.phone,
            email=self.email,
            social_media_handles=list(self.social_media_handles),
            rating=self.rating,
            review_count=self.review_count,
            latitude=self.latitude,
            longitude=self.longitude,
            source=self.source,
            source_url=self.source_url,
            phone_metadata=list(self.phone_metadata),
            freshness=self.freshness,
            discovered_at=self.discovered_at,
        )

    def to_resolver_dict(self) -> dict[str, Any]:
        """Project to the minimal dict shape consumed by the graph resolver.

        Mirrors "BusinessRaw.to_resolver_dict" so the resolver can work
        uniformly with either type.
        """
        return {
            "name": self.name,
            "website": self.website,
            "phones": [p.e164 for p in self.phone_metadata] or ([self.phone] if self.phone else []),
            "email": self.email,
            "address": self.address,
            "wilaya": self.wilaya,
            "industry": self.industry,
        }


# ============================================================
#  RESOLVED ENTITY (golden record)
# ============================================================

class ResolvedEntity(BaseModel):
    """A golden record produced by merging one or more "RawRecord" rows.

    The "raw_record_ids" list preserves lineage: a user can click through
    from a resolved entity back to every raw scrape that contributed to it.
    """

    model_config = ConfigDict(extra="ignore")

    id: Optional[int] = None
    entity_type: EntityType = Field(default=EntityType.BUSINESS)
    name: str
    industry: Optional[str] = None
    wilaya: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    phones: list[str] = Field(default_factory=list)
    email: Optional[str] = None
    social_media_handles: list[str] = Field(default_factory=list)
    rating: float = Field(default=0.0, ge=0.0, le=5.0)
    review_count: int = Field(default=0, ge=0)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    strategy: ResolutionStrategy = Field(default=ResolutionStrategy.SINGLE)
    raw_record_ids: list[int] = Field(default_factory=list)
    last_resolved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================
#  CRAWL TASK (frontier queue item)
# ============================================================

class CrawlTask(BaseModel):
    """A single URL pending in (or retrieved from) the crawl frontier."""

    model_config = ConfigDict(extra="ignore")

    id: int
    url: str
    domain: str
    priority: int = 1
    depth: int = 0
    status: CrawlStatus = CrawlStatus.PENDING
    last_attempted: Optional[datetime] = None
    fail_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _normalise_domain(self) -> "CrawlTask":
        if self.domain:
            self.domain = self.domain.lower().lstrip(".")
        return self


# ============================================================
#  PROXY NODE (resilience layer)
# ============================================================

class ProxyNode(BaseModel):
    """Stateful proxy descriptor used by the resilience orchestrator."""

    model_config = ConfigDict(extra="ignore")

    url: str
    health_score: float = Field(default=100.0, ge=0.0, le=100.0)
    state: ProxyHealthState = Field(default=ProxyHealthState.HEALTHY)
    success_count: int = 0
    fail_count: int = 0
    consecutive_fails: int = 0
    last_used_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")