"""Catalogue of industries the engine knows how to prospect.

Each industry carries a default set of typical B2B services it benefits
from, plus an expected digital-presence gap. These defaults drive the
heuristic fallback analyser when the LLM is unreachable.
"""

from __future__ import annotations

from typing import Optional


INDUSTRIES: tuple[dict[str, object], ...] = (
    {
        "key": "restaurant",
        "label": "Restaurant",
        "typical_services": [
            "Online ordering system",
            "Table reservation widget",
            "Loyalty program platform",
        ],
        "average_project_value_usd": 1800.0,
        "expected_digital_gap": 55,
    },
    {
        "key": "pharmacy",
        "label": "Pharmacy",
        "typical_services": [
            "Inventory management system",
            "Online prescription refill",
            "Customer notification SMS gateway",
        ],
        "average_project_value_usd": 2500.0,
        "expected_digital_gap": 60,
    },
    {
        "key": "climatisation",
        "label": "Climatisation & HVAC",
        "typical_services": [
            "Field service dispatch app",
            "Customer portal for maintenance contracts",
            "Invoicing & quote generator",
        ],
        "average_project_value_usd": 3000.0,
        "expected_digital_gap": 65,
    },
    {
        "key": "menuiserie aluminium",
        "label": "Aluminium Joinery",
        "typical_services": [
            "Quote & order management system",
            "Customer design visualisation tool",
            "Production scheduling dashboard",
        ],
        "average_project_value_usd": 3200.0,
        "expected_digital_gap": 70,
    },
    {
        "key": "tolier",
        "label": "Auto Body Repair",
        "typical_services": [
            "Repair tracking portal",
            "Photo estimation tool",
            "Insurance claim automation",
        ],
        "average_project_value_usd": 2800.0,
        "expected_digital_gap": 65,
    },
    {
        "key": "supermarche",
        "label": "Supermarket / Grocery",
        "typical_services": [
            "POS integration",
            "Inventory & expiry tracking",
            "Home delivery ordering app",
        ],
        "average_project_value_usd": 3500.0,
        "expected_digital_gap": 50,
    },
    {
        "key": "logistics",
        "label": "Logistics & Transport",
        "typical_services": [
            "Fleet tracking dashboard",
            "Route optimisation engine",
            "Customer shipment tracking portal",
        ],
        "average_project_value_usd": 4500.0,
        "expected_digital_gap": 60,
    },
    {
        "key": "clinique",
        "label": "Private Clinic",
        "typical_services": [
            "Appointment booking system",
            "Electronic medical records",
            "Patient SMS reminders",
        ],
        "average_project_value_usd": 5500.0,
        "expected_digital_gap": 55,
    },
    {
        "key": "avocat",
        "label": "Law Firm",
        "typical_services": [
            "Case management system",
            "Client portal",
            "Document automation tool",
        ],
        "average_project_value_usd": 2800.0,
        "expected_digital_gap": 50,
    },
    {
        "key": "immobilier",
        "label": "Real Estate Agency",
        "typical_services": [
            "Property listing website",
            "CRM for agents",
            "Virtual tour integration",
        ],
        "average_project_value_usd": 3500.0,
        "expected_digital_gap": 55,
    },
    {
        "key": "automobile",
        "label": "Car Dealer",
        "typical_services": [
            "Inventory showcase website",
            "Financing calculator",
            "Lead capture CRM",
        ],
        "average_project_value_usd": 3200.0,
        "expected_digital_gap": 60,
    },
    {
        "key": "construction",
        "label": "Construction & BTP",
        "typical_services": [
            "Project management dashboard",
            "Quote & invoice generator",
            "Worksite progress tracker",
        ],
        "average_project_value_usd": 4500.0,
        "expected_digital_gap": 65,
    },
    {
        "key": "coiffure",
        "label": "Hair Salon / Barber",
        "typical_services": [
            "Online appointment booking",
            "Loyalty program",
            "Instagram-style portfolio",
        ],
        "average_project_value_usd": 1200.0,
        "expected_digital_gap": 70,
    },
    {
        "key": "boulangerie",
        "label": "Bakery",
        "typical_services": [
            "Pre-order app",
            "Loyalty stamps",
            "WhatsApp notification integration",
        ],
        "average_project_value_usd": 1500.0,
        "expected_digital_gap": 65,
    },
)


def get_industry_by_key(key: str) -> Optional[dict[str, object]]:
    if not key:
        return None
    needle = key.strip().lower()
    for ind in INDUSTRIES:
        if str(ind["key"]) == needle or str(ind["label"]).lower() == needle:
            return ind
    return None
