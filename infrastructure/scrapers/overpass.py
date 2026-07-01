"""Overpass (OpenStreetMap) scraper — free, no API key, low-resource.

Queries the public Overpass API for businesses tagged inside a wilaya's
bounding box. Falls back to a country-wide query if the wilaya has no
registered bbox in `config.wilayas.WILAYA_BBOXES`.

This scraper never raises; on any error it logs and returns an empty list.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from config.settings import settings
from config.wilayas import WILAYA_BBOXES
from domain.models import BusinessRaw, DataSource
from infrastructure.scrapers.base import BaseScraper


OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"
# Alternate endpoint in case the primary is overloaded.
OVERPASS_FALLBACK = "https://overpass.kumi.systems/api/interpreter"


class OverpassScraper(BaseScraper):
    """Discovers businesses via OpenStreetMap Overpass API."""

    source_name = "overpass"

    def discover_businesses(
        self,
        query: str,
        wilaya: Optional[str] = None,
        limit: int = 10,
    ) -> List[BusinessRaw]:
        self._logger.info("Overpass discovery: query=%r wilaya=%r limit=%d", query, wilaya, limit)

        bbox = WILAYA_BBOXES.get(wilaya or "") if wilaya else None
        if bbox is None:
            # Country-wide bbox (rough bounds for Algeria).
            bbox = (18.0, -9.0, 38.0, 12.0)
            self._logger.debug("No specific bbox for wilaya=%r — using Algeria-wide bbox.", wilaya)

        # Build a query that looks for any node/way with a name AND a business-y tag.
        # `query` is used as a name filter (case-insensitive via regex).
        overpass_query = self._build_query(query, bbox, limit * 3)

        for endpoint in (OVERPASS_ENDPOINT, OVERPASS_FALLBACK):
            resp = self._safe_get(endpoint, params={"data": overpass_query})
            if resp is None:
                continue
            try:
                data = resp.json()
            except ValueError as e:
                self._logger.warning("Overpass returned invalid JSON from %s: %s", endpoint, e)
                continue

            elements = data.get("elements", [])
            self._logger.info("Overpass returned %d elements from %s", len(elements), endpoint)
            return self._parse_elements(elements, wilaya, limit)

        self._logger.warning("All Overpass endpoints failed. Returning 0 results.")
        return []

    # ------------------------------------------------------------------

    @staticmethod
    def _build_query(query: str, bbox: tuple, limit: int) -> str:
        """Build an Overpass QL query.

        We fetch any amenity/shop/tourism/office/healthcare/craft element
        with a `name` tag, optionally name-filtered.
        """
        south, west, north, east = bbox
        bbox_str = f"{south},{west},{north},{east}"

        # Use a regex case-insensitive name filter when a query is provided.
        name_filter = f'["name"~"{query}",i]' if query else '["name"]'

        # Query multiple tag categories at once. Order matters: nodes first, then ways.
        statements = []
        for category in ("amenity", "shop", "tourism", "office", "healthcare", "craft"):
            statements.append(
                f'  node{name_filter}["{category}"]({bbox_str});\n'
                f'  way{name_filter}["{category}"]({bbox_str});'
            )

        body = "[out:json][timeout:25];\n(\n" + "\n".join(statements) + "\n);\nout center 1000;"
        return body

    def _parse_elements(self, elements: List[dict], wilaya: Optional[str], limit: int) -> List[BusinessRaw]:
        results: List[BusinessRaw] = []
        seen_names = set()

        for el in elements:
            tags = el.get("tags") or {}
            name = tags.get("name", "").strip()
            if not name or name.lower() in seen_names:
                continue

            lat = el.get("lat") or el.get("center", {}).get("lat")
            lon = el.get("lon") or el.get("center", {}).get("lon")

            industry = self._tags_to_industry(tags)
            website = tags.get("website") or tags.get("contact:website") or tags.get("url")
            phone = tags.get("phone") or tags.get("contact:phone")
            email = tags.get("email") or tags.get("contact:email")
            address_parts = [
                tags.get("addr:housenumber"), tags.get("addr:street"),
                tags.get("addr:city"), tags.get("addr:postcode"),
            ]
            address = ", ".join(p for p in address_parts if p) or None

            social = self._extract_social(tags)

            try:
                biz = BusinessRaw(
                    name=name,
                    industry=industry,
                    wilaya=wilaya or "Unknown",
                    address=address,
                    website=website,
                    phone=phone,
                    email=email,
                    social_media_handles=social,
                    rating=0.0,
                    review_count=0,
                    latitude=self._safe_float(lat),
                    longitude=self._safe_float(lon),
                    source=DataSource.OVERPASS,
                    source_url=f"https://www.openstreetmap.org/{el.get('type','node')}/{el.get('id','')}",
                )
                results.append(biz)
                seen_names.add(name.lower())
                if len(results) >= limit:
                    break
            except Exception as e:
                self._logger.debug("Skipped element due to validation: %s", e)
                continue

        self._logger.info("Parsed %d valid businesses from Overpass.", len(results))
        return results
