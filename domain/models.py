"""Domain models — strict, validated data structures for the entire platform.

All models are Pydantic v2 `BaseModel` subclasses, ensuring:
  * Type coercion & validation at every layer boundary.
  * JSON-serialisable by default (used for storage, export, LLM payloads).
  * Self-documenting field descriptions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


# ============================================================================
#  ENUMERATIONS
# ============================================================================

class LeadStatus(str, Enum):
    """Lifecycle of a lead inside the pipeline."""
    DISCOVERED = "discovered"     # raw business persisted
    ANALYZED = "analyzed"         # LLM analysis attached
    SCORED = "scored"             # priority score computed
    CONTACTED = "contacted"       # outreach started (manual flag)
    REJECTED = "rejected"         # marked as not-a-fit (manual flag)


class DataSource(str, Enum):
    """Which scraper produced a given record."""
    OVERPASS = "overpass"         # OpenStreetMap Overpass API
    DDG = "duckduckgo"            # DuckDuckGo HTML search
    MOCK = "mock"                 # Built-in mock dataset
    MANUAL = "manual"             # Manually inserted via API/CLI


# ============================================================================
#  CORE BUSINESS / LEAD MODELS
# ============================================================================

class BusinessRaw(BaseModel):
    """A discovered business, exactly as extracted from a source (before any AI work)."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, description="Business name")
    industry: str = Field(..., description="Sector/category (e.g. Restaurant, Pharmacy)")
    wilaya: str = Field(..., description="Algerian wilaya name (e.g. Algiers, Oran)")
    address: Optional[str] = Field(None, description="Street address if available")
    website: Optional[str] = Field(None, description="Website URL if any")
    phone: Optional[str] = Field(None, description="Contact phone number, any format")
    email: Optional[str] = Field(None, description="Public contact email if any")
    social_media_handles: List[str] = Field(
        default_factory=list,
        description="Social profile URLs (Facebook/Instagram/LinkedIn/etc.)",
    )
    rating: float = Field(default=0.0, ge=0.0, le=5.0, description="Average rating out of 5.0")
    review_count: int = Field(default=0, ge=0, description="Total online reviews")
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    source: DataSource = Field(default=DataSource.MOCK, description="Which scraper found this")
    source_url: Optional[str] = Field(None, description="Direct URL of the source page/listing")
    discovered_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of discovery",
    )

    def fingerprint(self) -> str:
        """A stable identity key for deduplication.

        We normalise name + wilaya + phone (if present) into a lowercase
        string. Two records with the same fingerprint are treated as the
        same business.
        """
        normalised_name = "".join(c.lower() for c in self.name if c.isalnum())
        normalised_wilaya = self.wilaya.strip().lower()
        normalised_phone = (self.phone or "").replace(" ", "").replace("+", "")
        return f"{normalised_name}|{normalised_wilaya}|{normalised_phone}"


class ProposedService(BaseModel):
    """A software service that the LLM recommends pitching to the business."""

    model_config = ConfigDict(extra="ignore")

    service_name: str = Field(..., description="Human-readable service name")
    justification: str = Field(..., description="Why this business specifically needs it")
    estimated_value_usd: float = Field(
        ..., ge=0.0, description="Estimated project value in USD"
    )
    priority: int = Field(default=5, ge=1, le=10, description="1 (low) – 10 (must-pitch)")


class LeadAnalysis(BaseModel):
    """LLM-generated analysis of a single business."""

    model_config = ConfigDict(extra="ignore")

    pain_points: List[str] = Field(
        default_factory=list,
        description="Likely operational problems faced by the business",
    )
    recommended_solutions: List[ProposedService] = Field(
        default_factory=list,
        description="Ranked list of software services to pitch",
    )
    digital_presence_score: int = Field(
        default=50, ge=0, le=100,
        description="0 (no presence) – 100 (excellent digital footprint)",
    )
    pitch_angles: List[str] = Field(
        default_factory=list,
        description="Customised sales pitch hooks for outreach",
    )
    estimated_monthly_revenue_usd: Optional[float] = Field(
        None, ge=0.0, description="Rough revenue estimate, if LLM provided one"
    )
    analysis_model: Optional[str] = Field(
        None, description="Which LLM model produced this analysis (for audit)"
    )
    analyzed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    from_cache: bool = Field(default=False, description="True if served from disk cache")


class Lead(BaseModel):
    """A complete lead: raw business + (optional) analysis + score."""

    model_config = ConfigDict(extra="ignore")

    id: Optional[int] = Field(None, description="Database row ID once persisted")
    business: BusinessRaw
    analysis: Optional[LeadAnalysis] = None
    priority_score: float = Field(default=0.0, ge=0.0, le=100.0)
    status: LeadStatus = Field(default=LeadStatus.DISCOVERED)
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


# ============================================================================
#  STATIC REFERENCE MODELS
# ============================================================================

class Wilaya(BaseModel):
    """One of Algeria's 58 wilayas."""
    code: int = Field(..., ge=1, le=58, description="Official wilaya code (1–58)")
    name_en: str = Field(..., description="English name (e.g. 'Algiers')")
    name_fr: str = Field(..., description="French name (e.g. 'Alger')")
    name_ar: str = Field(..., description="Arabic name")


class IndustryTemplate(BaseModel):
    """Default assumptions for an industry, used by the fallback analyzer."""
    key: str = Field(..., description="Lowercase identifier (e.g. 'restaurant')")
    label: str = Field(..., description="Display label (e.g. 'Restaurant')")
    typical_services: List[str] = Field(
        default_factory=list,
        description="Services this industry usually benefits from",
    )
    average_project_value_usd: float = Field(
        default=1500.0, ge=0.0,
        description="Typical project size for this industry",
    )
    expected_digital_gap: int = Field(
        default=50, ge=0, le=100,
        description="Expected digital presence score (lower = bigger gap)",
    )
