"""Value objects — small, immutable, self-validating domain concepts.

A value object has no identity of its own: two ``PhoneDetails`` with the
same E.164 number are interchangeable. They exist to give domain models
richer typed fields instead of bare strings.
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


class FreshnessMetadata(BaseModel):
    """Temporal metadata attached to every discovered business.

    The freshness detector fills this from HTTP headers, SERP snippets, and
    on-page text. When no signal is found, ``calculated_age_class`` falls
    back to ``FreshnessAge.ARCHIVED`` so the lead still appears in filters.
    """

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


class GeoPoint(BaseModel):
    """A WGS-84 geographic coordinate."""

    model_config = ConfigDict(extra="ignore")

    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)


class Contact(BaseModel):
    """A unified contact channel — phone, email, or social profile."""

    model_config = ConfigDict(extra="ignore")

    kind: str = Field(..., description="phone | email | social")
    value: str = Field(..., description="The contact value (E.164, email, or URL)")
    source_url: Optional[str] = Field(None, description="URL where this contact was found")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Extraction confidence 0..1")
