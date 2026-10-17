"""Async OpenStreetMap Overpass scraper (streaming, adapted to unified Lead).

Carried over from v2.0.0 (its OSM tag mapping and QL construction were
solid): trilingual keyword->tag filters, two rotating endpoints, area
filtering by wilaya. v3 changes: yields Leads through the shared streaming
interface and uses the unified domain model.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

from config.wilayas import get_wilaya_by_name
from domain.enums import DataSource
from domain.models import Lead
from domain.value_objects import FreshnessMetadata
from infrastructure.scrapers.base import BaseAsyncScraper
from utils.freshness_detector import FreshnessDetector
from utils.phone_validator import SmartPhoneValidator

logger = logging.getLogger("scrapers.overpass")

OVERPASS_ENDPOINTS: tuple[str, ...] = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

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

_KEYWORD_TAG_MAP: dict[str, list[str]] = {
    "pharmacie": ["amenity=pharmacy"],
    "pharmacy": ["amenity=pharmacy"],
    "صيدلية": ["amenity=pharmacy"],
    "officine": ["amenity=pharmacy"],
    "clinic": ["amenity=clinic", "amenity=hospital", "amenity=doctors"],
    "clinique": ["amenity=clinic", "amenity=hospital", "amenity=doctors"],
    "hospital": ["amenity=hospital"],
    "hopital": ["amenity=hospital"],
    "مستشفى": ["amenity=hospital"],
    "عيادة": ["amenity=clinic", "amenity=doctors"],
    "doctors": ["amenity=doctors"],
    "dentist": ["amenity=dentist"],
    "dentiste": ["amenity=dentist"],
    "restaurant": ["amenity=restaurant", "amenity=fast_food"],
    "resto": ["amenity=restaurant", "amenity=fast_food"],
    "مطعم": ["amenity=restaurant", "amenity=fast_food"],
    "pizzeria": ["amenity=restaurant"],
    "cafe": ["amenity=cafe"],
    "مقهى": ["amenity=cafe"],
    "bakery": ["shop=bakery"],
    "boulangerie": ["shop=bakery"],
    "مخبزة": ["shop=bakery"],
    "supermarket": ["shop=supermarket"],
    "supermarche": ["shop=supermarket"],
    "supérette": ["shop=convenience", "shop=supermarket"],
    "سوبرماركت": ["shop=supermarket"],
    "hairdresser": ["shop=hairdresser"],
    "coiffure": ["shop=hairdresser"],
    "حلاق": ["shop=hairdresser"],
    "lawyer": ["office=lawyer"],
    "avocat": ["office=lawyer"],
    "محامي": ["office=lawyer"],
    "real_estate": ["office=real_estate_agent"],
    "immobilier": ["office=real_estate_agent"],
    "عقارات": ["office=real_estate_agent"],
    "car_repair": ["amenity=car_repair", "shop=car_repair"],
    "mecanicien": ["amenity=car_repair", "shop=car_repair"],
    "garage": ["amenity=car_repair", "shop=car_repair"],
    "تصليح سيارات": ["amenity=car_repair"],
    "plumber": ["craft=plumber"],
    "plombier": ["craft=plumber"],
    "ترصيص": ["craft=plumber"],
}


class OverpassScraper(BaseAsyncScraper):
    """Streaming OpenStreetMap Overpass scraper."""

    def __init__(self, client, **kwargs) -> None:
        super().__init__(client, **kwargs)
        self._phone_validator = SmartPhoneValidator()
        self._freshness = FreshnessDetector()

    @property
    def source_name(self) -> str:
        return "overpass"

    # ------------------------------------------------------------------
    async def discover(self, query: str, wilaya: Optional[str] = None, limit: int = 30) -> list[Lead]:
        return [lead async for lead in self.stream_discover(query, wilaya, limit)]

    async def stream_discover(
        self, query: str, wilaya: Optional[str] = None, limit: int = 30
    ) -> AsyncIterator[Lead]:
        if not wilaya:
            return  # Overpass requires an area; DDG covers the no-wilaya case.

        area_declaration, area_filter = self._area_filter(wilaya)
        tag_filters = self._osm_filters(query)
        if not tag_filters:
            return

        tag_union = ";\n".join(f"  {t}{area_filter};" for t in tag_filters)
        ql = f"""
        [out:json][timeout:25];
        {area_declaration}
        (
        {tag_union}
        );
        out center {max(limit * 2, 80)};
        """

        data = await self._query(ql)
        if data is None:
            return

        seen: set[str] = set()
        yielded = 0
        for lead in self._parse_elements(data.get("elements", []), query, wilaya):
            fp = lead.fingerprint()
            if fp in seen:
                continue
            seen.add(fp)
            yielded += 1
            yield lead
            if yielded >= limit:
                return

    # ------------------------------------------------------------------
    async def _query(self, ql: str) -> Optional[dict]:
        for endpoint in OVERPASS_ENDPOINTS:
            response = await self._fetch(
                endpoint, params={"data": ql}, timeout=30.0
            )
            if response is None:
                continue
            try:
                return response.json()
            except Exception as exc:
                logger.debug("Overpass JSON decode failed from %s: %s", endpoint, exc)
        return None

    @staticmethod
    def _area_filter(wilaya: str) -> tuple[str, str]:
        w = get_wilaya_by_name(wilaya)
        name = str(w["name_fr"]) if w else wilaya
        safe = name.replace('"', '\\"')
        return f'area["name"~"^{safe}$",i]->.searchArea;', "(area.searchArea)"

    @staticmethod
    def _osm_filters(query: str) -> list[str]:
        q = (query or "").lower().strip()
        matches: list[str] = []
        for key, tags in _KEYWORD_TAG_MAP.items():
            if key in q or q in key:
                matches.extend(tags)
        for tag in _OSM_TAG_TO_INDUSTRY:
            key = tag.partition("=")[2]
            if key and (key in q or q in key):
                matches.append(tag)
        if not matches and any(
            w in q for w in ("shop", "store", "magasin", "hanout", "محل", "دكان")
        ):
            matches.append("shop")
        seen: set[str] = set()
        return [m for m in matches if not (m in seen or seen.add(m))][:5]

    def _parse_elements(
        self, elements: list[dict], query: str, wilaya: str
    ) -> list[Lead]:
        leads: list[Lead] = []
        for el in elements:
            tags = el.get("tags", {}) or {}
            name = tags.get("name") or tags.get("name:fr") or tags.get("name:en")
            if not name:
                continue

            phone = tags.get("phone") or tags.get("contact:phone")
            email = tags.get("email") or tags.get("contact:email")
            website = tags.get("website") or tags.get("contact:website") or tags.get("url")
            address = ", ".join(
                p for p in (
                    tags.get("addr:housenumber"),
                    tags.get("addr:street"),
                    tags.get("addr:city"),
                    tags.get("addr:postcode"),
                ) if p
            ) or None

            lat = el.get("lat") or (el.get("center") or {}).get("lat")
            lon = el.get("lon") or (el.get("center") or {}).get("lon")

            phone_details = self._phone_validator.extract_and_validate(phone) if phone else []
            freshness = FreshnessMetadata()
            if el.get("timestamp"):
                freshness = self._freshness.detect(str(el["timestamp"]))

            leads.append(Lead(
                name=str(name).strip()[:200],
                industry=self._industry_for_tags(tags) or (query.title() if query else "Other"),
                wilaya=wilaya,
                address=address,
                website=website,
                phone=phone_details[0].e164 if phone_details else phone,
                email=(email or "").lower() or None,
                social_links=[],
                rating=float(tags.get("stars", 0.0) or 0.0),
                latitude=float(lat) if lat is not None else None,
                longitude=float(lon) if lon is not None else None,
                source=DataSource.OVERPASS,
                source_url=(
                    f"https://www.openstreetmap.org/{el.get('type', 'node')}/{el.get('id', '')}"
                ),
                phone_details=phone_details,
                freshness=freshness,
            ))
        return leads

    @staticmethod
    def _industry_for_tags(tags: dict) -> Optional[str]:
        for tag_key, industry in _OSM_TAG_TO_INDUSTRY.items():
            key, _, value = tag_key.partition("=")
            if tags.get(key) == value:
                return industry
        return None
