"""Async OpenStreetMap Overpass scraper.

Queries the Overpass API for businesses (amenity, shop, office, craft
tags) near a given wilaya. Returns structured ``BusinessRaw`` records
with geographic coordinates and OSM metadata.

This replaces the original synchronous ``requests.get``-based scraper
that blocked the FastAPI event loop. The async version uses the shared
``httpx.AsyncClient`` and respects the global rate limiter.
"""

from __future__ import annotations

import logging
from typing import Optional

from domain.enums import DataSource
from domain.models import BusinessRaw
from domain.value_objects import FreshnessMetadata
from infrastructure.http.rate_limiter import AsyncRateLimiter, DomainRateLimiter
from infrastructure.scrapers.base import BaseAsyncScraper
from utils.freshness_detector import FreshnessDetector
from utils.phone_validator import SmartPhoneValidator


_logger = logging.getLogger("scrapers.overpass")


# Overpass endpoints — we rotate between the two public instances for
# resilience. The local SearXNG/proxy layer could also be used.
OVERPASS_ENDPOINTS: tuple[str, ...] = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)


# Mapping from OSM top-level tags to our industry labels.
_OSM_TAG_TO_INDUSTRY: dict[str, str] = {
    "amenity=pharmacy": "Pharmacy",
    "amenity=clinic": "Clinic",
    "amenity=hospital": "Clinic",
    "amenity=doctors": "Clinic",
    "amenity=dentist": "Clinic",
    "amenity=restaurant": "Restaurant",
    "amenity=cafe": "Restaurant",
    "amenity=fast_food": "Restaurant",
    "amenity=bar": "Restaurant",
    "amenity=bank": "Bank",
    "amenity=fuel": "Fuel Station",
    "amenity=car_repair": "Auto Repair",
    "shop=supermarket": "Supermarket",
    "shop=convenience": "Supermarket",
    "shop=bakery": "Bakery",
    "shop=hairdresser": "Hair Salon",
    "shop=car": "Car Dealer",
    "shop=car_repair": "Auto Repair",
    "office=company": "Office",
    "office=lawyer": "Law Firm",
    "office=accountant": "Accounting",
    "office=real_estate_agent": "Real Estate Agency",
    "craft=carpenter": "Carpentry",
    "craft=electrician": "Electrician",
    "craft=plumber": "Plumber",
}


class AsyncOverpassScraper(BaseAsyncScraper):
    """Async OpenStreetMap Overpass scraper."""

    def __init__(
        self,
        client,
        phone_validator: Optional[SmartPhoneValidator] = None,
        freshness_detector: Optional[FreshnessDetector] = None,
        rate_limiter: Optional[AsyncRateLimiter] = None,
        domain_limiter: Optional[DomainRateLimiter] = None,
    ) -> None:
        super().__init__(
            client=client,
            rate_limiter=rate_limiter,
            domain_limiter=domain_limiter,
        )
        self._phone_validator = phone_validator or SmartPhoneValidator()
        self._freshness = freshness_detector or FreshnessDetector()

    @property
    def source_name(self) -> str:
        return "overpass"

    async def discover(
        self,
        query: str,
        wilaya: Optional[str] = None,
        limit: int = 10,
    ) -> list[BusinessRaw]:
        """Query Overpass for businesses matching the query near ``wilaya``."""
        if not query:
            return []
        self._logger.info("Overpass discover: query=%r wilaya=%r limit=%d", query, wilaya, limit)

        # Build the Overpass QL query.
        area_filter = self._area_filter(wilaya)
        osm_filters = self._osm_filters_for_query(query)
        if not osm_filters:
            self._logger.warning("No OSM tag mapping for query %r — skipping Overpass.", query)
            return []

        # Compose the union of every relevant tag.
        union_parts = []
        for tag_filter in osm_filters:
            union_parts.append(
                f'node[{tag_filter}]{area_filter};'
                f'way[{tag_filter}]{area_filter};'
            )
        union = "".join(union_parts)
        overpass_ql = f"[out:json][timeout:25];({union});out center 80;"

        # Try each endpoint until one responds.
        for endpoint in OVERPASS_ENDPOINTS:
            response = await self._fetch(
                endpoint,
                params={"data": overpass_ql},
                timeout=30.0,
            )
            if response is None:
                continue
            try:
                data = response.json()
            except Exception as exc:
                self._logger.warning("Overpass returned invalid JSON from %s: %s", endpoint, exc)
                continue
            businesses = self._parse_overpass_response(data, query, wilaya, limit)
            self._logger.info("Overpass returned %d businesses from %s", len(businesses), endpoint)
            return businesses

        self._logger.warning("Every Overpass endpoint failed for query %r", query)
        return []

    # ------------------------------------------------------------------

    def _area_filter(self, wilaya: Optional[str]) -> str:
        """Build the ``area[...]`` filter for the Overpass query.

        Falls back to a country-wide query when no wilaya is given.
        """
        if not wilaya:
            # Algeria's ISO 3166-2 area code in OSM is 3600193111 (relation).
            return '(area:3600193111)'
        # Use name-based area lookup. OSM area names for Algerian wilayas
        # are typically in French.
        safe = wilaya.replace('"', '\\"')
        return f'(area["name"="{safe}"]'

    def _osm_filters_for_query(self, query: str) -> list[str]:
        """Map the user query to one or more OSM tag filters."""
        q = query.lower().strip()
        matches: list[str] = []
        for tag, _ in _OSM_TAG_TO_INDUSTRY.items():
            # Match if the industry label (right-hand side) or the tag
            # value appears in the query.
            if any(word in tag for word in q.split()):
                matches.append(tag)
        # Also allow a generic "shop" fallback for retail queries.
        if not matches and any(w in q for w in ("shop", "store", "magasin", "hanout")):
            matches.append("shop")
        return matches[:5]  # Cap to avoid huge queries.

    def _parse_overpass_response(
        self,
        data: dict,
        query: str,
        wilaya: Optional[str],
        limit: int,
    ) -> list[BusinessRaw]:
        elements = data.get("elements", [])
        businesses: list[BusinessRaw] = []
        seen: set[str] = set()

        for el in elements:
            tags = el.get("tags", {}) or {}
            name = tags.get("name") or tags.get("name:fr") or tags.get("name:en")
            if not name:
                continue

            # Determine industry from the most specific OSM tag present.
            industry = self._industry_for_tags(tags) or (query.title() if query else "Other")

            phone = tags.get("phone") or tags.get("contact:phone")
            email = tags.get("email") or tags.get("contact:email")
            website = tags.get("website") or tags.get("contact:website") or tags.get("url")
            address_parts = [
                tags.get("addr:housenumber"),
                tags.get("addr:street"),
                tags.get("addr:city"),
                tags.get("addr:postcode"),
            ]
            address = ", ".join(p for p in address_parts if p) or None

            # Coordinates — elements can be nodes (lat/lon) or ways (center).
            lat = el.get("lat") or el.get("center", {}).get("lat")
            lon = el.get("lon") or el.get("center", {}).get("lon")

            phone_meta = []
            if phone:
                phone_meta = self._phone_validator.extract_and_validate(phone)

            freshness = FreshnessMetadata()
            # OSM elements carry a timestamp in the ``timestamp`` field.
            osm_ts = el.get("timestamp")
            if osm_ts:
                freshness = self._freshness.detect(osm_ts)

            biz = BusinessRaw(
                name=name.strip()[:200],
                industry=industry,
                wilaya=wilaya or "Unknown",
                address=address,
                website=website,
                phone=phone_meta[0].e164 if phone_meta else phone,
                email=email.lower() if email else None,
                social_media_handles=[],
                rating=float(tags.get("stars", 0.0) or 0.0),
                latitude=float(lat) if lat is not None else None,
                longitude=float(lon) if lon is not None else None,
                source=DataSource.OVERPASS,
                source_url=f"https://www.openstreetmap.org/{el.get('type', 'node')}/{el.get('id', '')}",
                phone_metadata=phone_meta,
                freshness=freshness,
            )
            fp = biz.fingerprint()
            if fp in seen:
                continue
            seen.add(fp)
            businesses.append(biz)
            if len(businesses) >= limit:
                break
        return businesses

    def _industry_for_tags(self, tags: dict) -> Optional[str]:
        for tag_key, industry in _OSM_TAG_TO_INDUSTRY.items():
            key, _, value = tag_key.partition("=")
            if tags.get(key) == value:
                return industry
        return None
