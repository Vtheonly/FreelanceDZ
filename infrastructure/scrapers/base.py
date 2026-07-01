"""Base scraper — shared utilities for every concrete scraper.

Concrete scrapers inherit from `BaseScraper` to get:
  * Configured `requests.Session` with timeout + user agent.
  * Safe HTTP GET that never raises (logs + returns None).
  * Common OSM tag → BusinessRaw mapping helper.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

from config.settings import settings
from core.interfaces import IScraper
from domain.models import BusinessRaw, DataSource


class BaseScraper(IScraper):
    """Common scaffolding for all scrapers."""

    source_name: str = "base"

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": settings.SCRAPER_USER_AGENT,
            "Accept-Language": "en,fr;q=0.9,ar;q=0.8",
        })
        self._timeout = settings.SCRAPER_TIMEOUT_SECONDS
        self._logger = logging.getLogger(f"scraper.{self.source_name}")

    # -------- HTTP helpers --------

    def _safe_get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[requests.Response]:
        """GET that swallows exceptions and logs them. Returns None on failure."""
        try:
            self._logger.debug("GET %s params=%s", url, params)
            resp = self._session.get(url, params=params, timeout=self._timeout)
            if resp.status_code != 200:
                self._logger.warning(
                    "%s returned HTTP %d (len=%d)", url, resp.status_code, len(resp.content)
                )
                return None
            return resp
        except requests.exceptions.Timeout:
            self._logger.warning("Timeout fetching %s", url)
        except requests.exceptions.RequestException as e:
            self._logger.warning("Request failed for %s: %s", url, e)
        return None

    # -------- Common mapping helpers --------

    @staticmethod
    def _extract_social(tags: Dict[str, str]) -> List[str]:
        """Pull social-media URLs from an OSM-style tag dict."""
        out: List[str] = []
        for key in ("contact:facebook", "contact:instagram", "contact:linkedin",
                    "contact:twitter", "contact:youtube", "contact:tiktok"):
            val = tags.get(key)
            if val:
                if not val.startswith("http"):
                    val = f"https://{val}"
                out.append(val)
        if "website" in tags:
            pass  # website is handled separately
        return out

    @staticmethod
    def _safe_float(val: Any) -> Optional[float]:
        try:
            return float(val) if val not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _tags_to_industry(tags: Dict[str, str]) -> str:
        """Best-effort mapping of OSM amenity/shop tags to our industry labels."""
        amenity = tags.get("amenity", "")
        shop = tags.get("shop", "")
        tourism = tags.get("tourism", "")
        office = tags.get("office", "")
        healthcare = tags.get("healthcare", "")
        craft = tags.get("craft", "")

        mapping = {
            # amenity
            "restaurant": "Restaurant", "fast_food": "Fast Food",
            "cafe": "Cafe / Coffee Shop", "bar": "Cafe / Coffee Shop",
            "pharmacy": "Pharmacy", "hospital": "Hospital",
            "clinic": "Doctor", "dentist": "Dentist",
            "doctors": "Doctor", "school": "School",
            "college": "University", "university": "University",
            "kindergarten": "School",
            "fuel": "Car Repair Garage", "car_wash": "Car Repair Garage",
            "car_rental": "Car Rental",
            "bank": "Accountant", "atm": "Accountant",
            # shop
            "supermarket": "Supermarket", "convenience": "Local Shop",
            "clothes": "Clothing Store", "shoes": "Shoe Store",
            "jewelry": "Jewelry Store", "electronics": "Electronics Store",
            "computer": "Computer Store", "mobile_phone": "Phone Repair Shop",
            "bakery": "Bakery", "butcher": "Local Shop",
            "furniture": "Furniture Manufacturer", "hardware": "Local Shop",
            "books": "Local Shop", "gift": "Local Shop",
            "beauty": "Beauty Salon", "hairdresser": "Barber Shop",
            # tourism
            "hotel": "Hotel", "motel": "Hotel", "resort": "Resort",
            "guest_house": "Hotel",
            # office
            "lawyer": "Lawyer", "accountant": "Accountant",
            "architect": "Architect", "company": "Software Company",
            "consulting": "Consultant", "estate_agent": "Real Estate Platform",
            # healthcare
            "doctor": "Doctor", "dentist": "Dentist", "clinic": "Doctor",
            "hospital": "Hospital", "optometrist": "Doctor",
            # craft
            "carpenter": "Furniture Manufacturer", "electrician": "Local Shop",
            "plumber": "Local Shop",
        }

        for tag_val in (amenity, shop, tourism, office, healthcare, craft):
            if tag_val and tag_val in mapping:
                return mapping[tag_val]

        # Fallbacks based on individual tags
        if amenity or shop or tourism or office or healthcare or craft:
            return "Local Shop"
        return "Other"
