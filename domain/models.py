"""Unified domain models.

v3.0.0 — ONE canonical Lead model replaces the v2 quartet
(BusinessRaw / RawRecord / Lead / ResolvedEntity view). Iteration 1
consolidated four competing representations into one `leads` table; the v2.0.0
rewrite split them apart again (raw_records + analyses + lead_scores +
resolved_entities), reintroducing the exact duplication iteration 1 had
eliminated and forcing a 3-way LEFT JOIN on every read. v3 returns to the
single source of truth and keeps entity resolution as non-destructive
cluster metadata (`cluster_id` + entity_clusters/entity_links tables).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from domain.enums import DataSource, FreshnessAge, LeadStatus, PhoneType
from domain.value_objects import FreshnessMetadata, PhoneDetails


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Lead(BaseModel):
    """Canonical B2B lead — discovery state, deterministic audit, score, CRM."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=False)

    id: Optional[int] = None

    # --- identity / discovery -------------------------------------------
    name: str = Field(..., min_length=1, max_length=300)
    industry: str = Field(default="", max_length=200)
    wilaya: str = Field(default="", max_length=120)
    address: Optional[str] = Field(default=None, max_length=500)
    website: Optional[str] = Field(default=None, max_length=500)
    phone: Optional[str] = Field(default=None, max_length=40)
    email: Optional[str] = Field(default=None, max_length=200)
    social_links: list[str] = Field(default_factory=list)

    rating: float = Field(default=0.0, ge=0.0, le=5.0)
    review_count: int = Field(default=0, ge=0)
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    source: DataSource = DataSource.DUCKDUCKGO
    source_url: Optional[str] = Field(default=None, max_length=1000)
    phone_details: list[PhoneDetails] = Field(default_factory=list)
    freshness: FreshnessMetadata = Field(default_factory=FreshnessMetadata)

    # --- deterministic audit (engine.analyzer) ---------------------------
    digital_score: Optional[int] = Field(default=None, ge=0, le=100)
    digital_tier: Optional[str] = None
    gaps: list[str] = Field(default_factory=list)
    recommended_services: list[dict[str, Any]] = Field(default_factory=list)
    cta_fr: str = ""
    cta_ar: str = ""
    analysis_model: Optional[str] = None

    # --- scoring (engine.scorer) -----------------------------------------
    priority_score: float = Field(default=0.0, ge=0.0, le=100.0)
    score_breakdown: dict[str, float] = Field(default_factory=dict)

    # --- entity resolution ------------------------------------------------
    cluster_id: Optional[int] = None

    # --- CRM state ---------------------------------------------------------
    status: LeadStatus = LeadStatus.DISCOVERED
    tags: list[str] = Field(default_factory=list)
    is_contact: bool = False
    notes: Optional[str] = None

    discovered_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    # ------------------------------------------------------------------
    def fingerprint(self) -> str:
        """Deterministic multi-attribute identity for rapid deduplication.

        name | wilaya | phone-digits | normalized-website — the strongest
        cheap identity available before graph resolution runs.
        """
        clean_name = "".join(ch for ch in self.name.lower() if ch.isalnum())
        clean_wilaya = (self.wilaya or "").strip().lower()
        clean_phone = "".join(ch for ch in (self.phone or "") if ch.isdigit())
        clean_web = (self.website or "").lower()
        for prefix in ("https://", "http://", "www."):
            if clean_web.startswith(prefix):
                clean_web = clean_web[len(prefix):]
        clean_web = clean_web.rstrip("/")
        return f"{clean_name}|{clean_wilaya}|{clean_phone}|{clean_web}"

    @property
    def age_class(self) -> FreshnessAge:
        return self.freshness.calculated_age_class

    def primary_phone_details(self) -> Optional[PhoneDetails]:
        return self.phone_details[0] if self.phone_details else None

    def is_mobile_reachable(self) -> bool:
        return any(p.phone_type == PhoneType.MOBILE for p in self.phone_details)


class CrawlTask(BaseModel):
    """A unit of crawl work pulled from the persistent frontier."""

    model_config = ConfigDict(extra="ignore")

    url: str
    domain: str
    priority: int = 0
    depth: int = 0

    @staticmethod
    def normalise_domain(host: str) -> str:
        """Lowercase, strip a trailing dot (FQDN root), drop the port."""
        host = (host or "").strip().lower()
        if ":" in host:
            host = host.split(":", 1)[0]
        return host.rstrip(".")
