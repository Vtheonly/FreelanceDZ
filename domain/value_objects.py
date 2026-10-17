"""Value objects — small, immutable, self-validating domain concepts.

PhoneDetails and FreshnessMetadata survive from v2 (they are well-designed
and produced by phone_validator / freshness_detector). The unused GeoPoint
and Contact value objects were removed in v3 (never instantiated anywhere).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from domain.enums import FreshnessAge, PhoneType


class PhoneDetails(BaseModel):
    """Structured representation of a single phone number.

    Produced by ``utils.phone_validator.SmartPhoneValidator`` from raw text
    using Google's ``libphonenumber``. Storing the full structured object
    (rather than just the E.164 string) lets the UI display the original
    formatting, the carrier, and the line type without re-querying.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    original_string: str = Field(..., description="Exact substring of the source text that matched")
    e164: str = Field(..., description="Canonical E.164 format, e.g. +213555123456")
    international: str = Field(..., description="International display format, e.g. +213 555 12 34 56")
    national: Optional[str] = Field(None, description="National display format")
    phone_type: PhoneType = Field(default=PhoneType.UNKNOWN, description="Line type classification")
    region: Optional[str] = Field(None, description="Geographic region (geocoder)")
    carrier: Optional[str] = Field(None, description="Mobile carrier (Mobilis/Djezzy/Ooredoo)")
    is_valid: bool = Field(default=False, description="Whether libphonenumber considers the number valid")

    @property
    def is_whatsapp_capable(self) -> bool:
        """Algerian mobile prefixes (05/06/07) are WhatsApp-reachable in practice."""
        return self.phone_type == PhoneType.MOBILE and self.is_valid


class FreshnessMetadata(BaseModel):
    """Temporal metadata attached to every discovered business."""

    model_config = ConfigDict(extra="ignore")

    discovered_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of first discovery by the engine",
    )
    last_updated: Optional[datetime] = Field(
        None, description="When the source claims the listing was last updated"
    )
    domain_created_at: Optional[datetime] = Field(
        None, description="WHOIS creation date of the business domain (when available)"
    )
    relative_age_hint: Optional[str] = Field(
        None, description="Raw textual hint, e.g. 'Updated 2 days ago'"
    )
    calculated_age_class: FreshnessAge = Field(
        default=FreshnessAge.ARCHIVED,
        description="Coarse bucket computed from the available signals",
    )

    @property
    def age_class(self) -> str:
        return self.calculated_age_class.value
