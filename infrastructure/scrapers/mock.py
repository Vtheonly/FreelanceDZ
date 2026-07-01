"""Mock scraper — realistic Algerian business records for offline development.

Always-available source used:
  * During local development without internet.
  * In unit tests.
  * As a last-resort fallback when all real sources fail.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from domain.models import BusinessRaw, DataSource
from infrastructure.scrapers.base import BaseScraper


# A diverse, realistic sample of Algerian businesses across wilayas.
_MOCK_BUSINESSES = [
    {"name": "Pizzeria Bella Ciao",       "industry": "Restaurant",          "wilaya": "Constantine", "website": None,                       "phone": "+213 31 55 66 77", "social": ["https://instagram.com/bellaciao_constantine"], "rating": 4.2, "reviews": 240},
    {"name": "Cabinet Dentaire Dr. Amrani","industry": "Dentist",             "wilaya": "Algiers",     "website": "http://dr-amrani-dentist.com","phone": "+213 21 89 12 34", "social": [],                                                "rating": 4.7, "reviews": 85},
    {"name": "Sarl El Bahi Dist",          "industry": "Logistics",           "wilaya": "Oran",        "website": None,                       "phone": "+213 41 23 45 67", "social": ["https://facebook.com/elbahi.logistics"],        "rating": 3.8, "reviews": 12},
    {"name": "Kalaat El Benaa Spa",        "industry": "Construction",        "wilaya": "Blida",       "website": None,                       "phone": None,               "social": ["https://linkedin.com/company/kalaat-benaa"],   "rating": 3.0, "reviews": 3},
    {"name": "Pharmacie El Baraka",        "industry": "Pharmacy",            "wilaya": "Setif",       "website": None,                       "phone": "+213 36 40 12 12", "social": ["https://facebook.com/pharmacie.elbaraka"],      "rating": 4.5, "reviews": 120},
    {"name": "Restaurant Le Phare",        "industry": "Restaurant",          "wilaya": "Algiers",     "website": "http://lephare-dz.com",    "phone": "+213 21 70 80 90", "social": ["https://facebook.com/restaurant.lephare"],      "rating": 4.0, "reviews": 320},
    {"name": "Beauty Lounge Oran",         "industry": "Beauty Salon",        "wilaya": "Oran",        "website": None,                       "phone": "+213 41 55 66 77", "social": ["https://instagram.com/beautylounge.oran"],      "rating": 4.6, "reviews": 180},
    {"name": "Setif Auto Garage",          "industry": "Car Repair Garage",   "wilaya": "Setif",       "website": None,                       "phone": "+213 36 80 80 80", "social": [],                                                "rating": 3.5, "reviews": 45},
    {"name": "Hotel Es-Salem",             "industry": "Hotel",               "wilaya": "Annaba",      "website": "http://hotel-essalem.com", "phone": "+213 38 86 86 86", "social": ["https://facebook.com/hotel.essalem"],           "rating": 4.1, "reviews": 95},
    {"name": "Constantine Gym Club",       "industry": "Gym",                 "wilaya": "Constantine", "website": None,                       "phone": "+213 31 92 11 22", "social": ["https://instagram.com/constantine.gym"],        "rating": 4.4, "reviews": 220},
    {"name": "Boulangerie Tizi Modern",    "industry": "Bakery",              "wilaya": "Tizi Ouzou",  "website": None,                       "phone": "+213 26 35 11 22", "social": [],                                                "rating": 4.0, "reviews": 60},
    {"name": "Cabinet Medical Ennour",     "industry": "Doctor",              "wilaya": "Blida",       "website": None,                       "phone": "+213 25 41 12 13", "social": [],                                                "rating": 4.3, "reviews": 35},
    {"name": "Electro Plus Oran",          "industry": "Electronics Store",   "wilaya": "Oran",        "website": None,                       "phone": "+213 41 30 30 30", "social": ["https://facebook.com/electropluses"],           "rating": 3.9, "reviews": 70},
    {"name": "Atelier Couture Fedala",     "industry": "Clothing Store",      "wilaya": "Mostaganem",  "website": None,                       "phone": "+213 45 22 22 22", "social": ["https://instagram.com/atelier.fedala"],         "rating": 4.5, "reviews": 110},
    {"name": "Ecole Privée Al-Manar",      "industry": "School",              "wilaya": "Algiers",     "website": "http://almanar-school.dz", "phone": "+213 21 60 60 60", "social": ["https://facebook.com/almanar.school"],          "rating": 4.2, "reviews": 50},
    {"name": "Pharmacie de Garde Setif",   "industry": "Pharmacy",            "wilaya": "Setif",       "website": None,                       "phone": "+213 36 84 84 84", "social": [],                                                "rating": 4.0, "reviews": 25},
    {"name": "Travel Sky Agency",          "industry": "Travel Agency",       "wilaya": "Algiers",     "website": None,                       "phone": "+213 21 70 70 70", "social": ["https://facebook.com/travelsky.dz"],            "rating": 4.3, "reviews": 65},
    {"name": "Pizza Hot Tizi",             "industry": "Pizza Shop",          "wilaya": "Tizi Ouzou",  "website": None,                       "phone": "+213 26 00 11 22", "social": ["https://instagram.com/pizzahot.tizi"],          "rating": 4.1, "reviews": 90},
    {"name": "Cabinet Juridique Benali",   "industry": "Lawyer",              "wilaya": "Algiers",     "website": None,                       "phone": "+213 21 23 45 67", "social": [],                                                "rating": 4.4, "reviews": 22},
    {"name": "Sarl Metal Industries",      "industry": "Factory",             "wilaya": "Oran",        "website": None,                       "phone": "+213 41 70 70 70", "social": ["https://linkedin.com/company/metal-industries"], "rating": 3.7, "reviews": 8},
]


class MockScraper(BaseScraper):
    """Returns hard-coded realistic Algerian business records."""

    source_name = "mock"

    def discover_businesses(
        self,
        query: str,
        wilaya: Optional[str] = None,
        limit: int = 10,
    ) -> List[BusinessRaw]:
        self._logger.info("Mock discovery: query=%r wilaya=%r limit=%d", query, wilaya, limit)
        q_lower = (query or "").lower()
        w_lower = (wilaya or "").lower()

        filtered = []
        for b in _MOCK_BUSINESSES:
            if q_lower and q_lower not in b["industry"].lower() and q_lower not in b["name"].lower():
                continue
            if w_lower and w_lower not in b["wilaya"].lower():
                continue
            filtered.append(b)

        if not filtered:
            # If no filter matches, return the first N mock records anyway.
            filtered = _MOCK_BUSINESSES

        results: List[BusinessRaw] = []
        for b in filtered[:limit]:
            try:
                results.append(BusinessRaw(
                    name=b["name"],
                    industry=b["industry"],
                    wilaya=b["wilaya"],
                    website=b["website"],
                    phone=b["phone"],
                    social_media_handles=b["social"],
                    rating=b["rating"],
                    review_count=b["reviews"],
                    source=DataSource.MOCK,
                ))
            except Exception as e:
                self._logger.debug("Skipped mock record (%s): %s", b["name"], e)

        self._logger.info("Mock scraper returned %d businesses.", len(results))
        return results
