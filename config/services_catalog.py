"""Catalogue of B2B software services the engine can recommend.

This is the deterministic fallback used by the heuristic analyser when
the LLM is unreachable. Each service has a base price and a list of
industries it is most relevant to.
"""

from __future__ import annotations


SERVICES_CATALOG: tuple[dict[str, object], ...] = (
    {
        "name": "Restaurant POS & Online Ordering",
        "base_value_usd": 1800.0,
        "priority": 8,
        "relevant_industries": ("restaurant", "boulangerie", "supermarche"),
        "pitch_angle": "Accept online orders 24/7 and reduce phone order errors.",
    },
    {
        "name": "Pharmacy Inventory & Refill System",
        "base_value_usd": 2500.0,
        "priority": 9,
        "relevant_industries": ("pharmacy", "clinique"),
        "pitch_angle": "Automate stock alerts and let customers refill online.",
    },
    {
        "name": "Field Service Dispatch App",
        "base_value_usd": 3000.0,
        "priority": 7,
        "relevant_industries": ("climatisation", "tolier", "construction"),
        "pitch_angle": "Dispatch technicians from your phone and track jobs in real time.",
    },
    {
        "name": "Quote & Order Management CRM",
        "base_value_usd": 2800.0,
        "priority": 7,
        "relevant_industries": ("menuiserie aluminium", "construction", "automobile"),
        "pitch_angle": "Generate professional quotes in 60 seconds and track every order.",
    },
    {
        "name": "Appointment Booking Widget",
        "base_value_usd": 900.0,
        "priority": 6,
        "relevant_industries": ("coiffure", "clinique", "avocat"),
        "pitch_angle": "Let clients book online and cut no-shows by 40% with SMS reminders.",
    },
    {
        "name": "E-commerce Website",
        "base_value_usd": 2200.0,
        "priority": 8,
        "relevant_industries": ("supermarche", "immobilier", "automobile"),
        "pitch_angle": "Sell online with a fast, mobile-first storefront.",
    },
    {
        "name": "Fleet Tracking Dashboard",
        "base_value_usd": 4500.0,
        "priority": 8,
        "relevant_industries": ("logistics", "construction"),
        "pitch_angle": "See every vehicle on a live map and optimise routes automatically.",
    },
    {
        "name": "Customer Loyalty & SMS Marketing",
        "base_value_usd": 1200.0,
        "priority": 5,
        "relevant_industries": ("restaurant", "coiffure", "boulangerie", "supermarche"),
        "pitch_angle": "Bring customers back with automated SMS offers and loyalty stamps.",
    },
    {
        "name": "WhatsApp Business Automation",
        "base_value_usd": 800.0,
        "priority": 6,
        "relevant_industries": ("restaurant", "pharmacy", "coiffure", "boulangerie"),
        "pitch_angle": "Auto-reply to customers on WhatsApp and capture leads 24/7.",
    },
    {
        "name": "Document & Case Management",
        "base_value_usd": 2800.0,
        "priority": 7,
        "relevant_industries": ("avocat", "immobilier"),
        "pitch_angle": "Find any file in seconds and never lose a deadline again.",
    },
)
