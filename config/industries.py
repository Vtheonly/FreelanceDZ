"""Industry templates — defaults for 50+ Algerian business categories.

Each template tells the analyzer what services are *typically* needed
for that industry, an average project size, and an expected digital gap
(0–100, lower = bigger gap to fill). These are used by:
  1. The fallback analyzer (when LLM is unavailable).
  2. The lead scorer (as baseline expectations).
  3. The CLI `stats` command (to break down leads by industry).
"""

from __future__ import annotations

from typing import Dict, List

from domain.models import IndustryTemplate


def _t(
    key: str,
    label: str,
    services: List[str],
    value_usd: float = 1500.0,
    gap: int = 50,
) -> IndustryTemplate:
    return IndustryTemplate(
        key=key,
        label=label,
        typical_services=services,
        average_project_value_usd=value_usd,
        expected_digital_gap=gap,
    )


# Ordered list of templates.
INDUSTRY_TEMPLATES: List[IndustryTemplate] = [
    # -------- Food & hospitality --------
    _t("restaurant", "Restaurant",
       ["Restaurant Ordering System", "Restaurant POS", "Custom Website"], 2500, 40),
    _t("pizza", "Pizza Shop",
       ["Restaurant Ordering System", "Custom Website", "Delivery Management Platform"], 2200, 40),
    _t("fast_food", "Fast Food",
       ["Restaurant Ordering System", "Delivery Management Platform", "Mobile App"], 2500, 40),
    _t("bakery", "Bakery",
       ["Custom Website", "Inventory Management System", "POS"], 1500, 50),
    _t("hotel", "Hotel",
       ["Hotel Booking Platform", "Custom Website", "CRM"], 4500, 40),
    _t("resort", "Resort",
       ["Hotel Booking Platform", "Custom Website", "Business Analytics Dashboard"], 6000, 35),
    _t("cafe", "Cafe / Coffee Shop",
       ["Custom Website", "POS", "Loyalty Program System"], 1500, 50),

    # -------- Fitness & wellness --------
    _t("gym", "Gym",
       ["Gym Management System", "Scheduling System", "Custom Website"], 3000, 45),
    _t("sports_club", "Sports Club",
       ["Scheduling System", "Membership Management", "Custom Website"], 3500, 45),
    _t("beauty_salon", "Beauty Salon",
       ["Appointment Booking System", "Custom Website", "CRM"], 2000, 40),
    _t("barber", "Barber Shop",
       ["Appointment Booking System", "Custom Website"], 1200, 50),
    _t("spa", "Spa",
       ["Appointment Booking System", "Custom Website", "CRM"], 2500, 45),

    # -------- Retail --------
    _t("clothing_store", "Clothing Store",
       ["E-commerce Website", "Inventory Management System", "Retail POS"], 3500, 45),
    _t("shoe_store", "Shoe Store",
       ["E-commerce Website", "Inventory Management System", "Retail POS"], 3000, 45),
    _t("jewelry_store", "Jewelry Store",
       ["E-commerce Website", "Custom Website", "CRM"], 4000, 40),
    _t("electronics_store", "Electronics Store",
       ["E-commerce Website", "Inventory Management System", "Retail POS"], 4500, 40),
    _t("phone_repair", "Phone Repair Shop",
       ["Custom Website", "Repair Tracking System", "CRM"], 1800, 50),
    _t("computer_store", "Computer Store",
       ["E-commerce Website", "Inventory Management System", "Retail POS"], 3500, 45),
    _t("supermarket", "Supermarket",
       ["Retail POS", "Inventory Management System", "ERP"], 5000, 40),
    _t("ecommerce", "E-commerce Store",
       ["Custom Website", "Inventory Management System", "AI Recommendation System"], 4000, 50),

    # -------- Health --------
    _t("pharmacy", "Pharmacy",
       ["Inventory Management System", "POS", "Custom Website"], 3500, 45),
    _t("doctor", "Doctor",
       ["Appointment Booking System", "Medical Management System", "Custom Landing Page"], 2000, 50),
    _t("dentist", "Dentist",
       ["Appointment Booking System", "Clinic Management System", "Custom Landing Page"], 2500, 45),
    _t("hospital", "Hospital",
       ["Hospital Management System", "Custom Website", "AI Customer Support"], 8000, 40),
    _t("medical_lab", "Medical Laboratory",
       ["Custom Website", "Customer Portal", "AI OCR System"], 4000, 45),

    # -------- Education --------
    _t("school", "School",
       ["School Management System", "Custom Website", "Parent Portal"], 4500, 40),
    _t("university", "University",
       ["University Management System", "Custom Website", "Student Portal"], 10000, 35),
    _t("training_center", "Training Center",
       ["Custom Website", "Scheduling System", "CRM"], 3000, 45),
    _t("language_school", "Language School",
       ["Custom Website", "Scheduling System", "LMS"], 3000, 45),

    # -------- Professional services --------
    _t("lawyer", "Lawyer",
       ["Custom Landing Page", "Appointment Booking System", "CRM"], 2000, 50),
    _t("accountant", "Accountant",
       ["Accounting System", "Custom Landing Page", "Invoice System"], 2500, 50),
    _t("architect", "Architect",
       ["Custom Website", "Portfolio Platform", "CRM"], 2500, 45),
    _t("consultant", "Consultant",
       ["Custom Landing Page", "CRM", "AI Lead Qualification System"], 2000, 50),

    # -------- Construction & industrial --------
    _t("construction", "Construction Company",
       ["Construction Management System", "Custom Website", "ERP"], 6000, 40),
    _t("interior_design", "Interior Designer",
       ["Custom Website", "Portfolio Platform", "CRM"], 2500, 45),
    _t("furniture", "Furniture Manufacturer",
       ["E-commerce Website", "Inventory Management System", "Custom Website"], 4000, 45),
    _t("industrial", "Industrial Company",
       ["ERP", "Inventory Management System", "Business Analytics Dashboard"], 8000, 35),
    _t("factory", "Factory",
       ["ERP", "Warehouse Management System", "Workflow Automation"], 10000, 35),
    _t("import_export", "Import/Export Company",
       ["ERP", "Inventory Management System", "Custom Website"], 7000, 40),
    _t("logistics", "Logistics Company",
       ["Fleet Management System", "Delivery Management Platform", "ERP"], 7000, 40),

    # -------- Automotive --------
    _t("car_dealership", "Car Dealership",
       ["Custom Website", "CRM", "Inventory Management System"], 5000, 45),
    _t("car_repair", "Car Repair Garage",
       ["Custom Website", "Scheduling System", "CRM"], 2000, 50),
    _t("car_rental", "Car Rental",
       ["Online Reservation System", "Custom Website", "Fleet Management System"], 4000, 45),

    # -------- Events & media --------
    _t("travel_agency", "Travel Agency",
       ["Online Reservation System", "Custom Website", "CRM"], 3500, 45),
    _t("event_planner", "Event Planner",
       ["Custom Website", "Scheduling System", "CRM"], 3000, 50),
    _t("wedding_hall", "Wedding Hall",
       ["Online Reservation System", "Custom Website", "Event Management System"], 4000, 45),
    _t("photographer", "Photographer",
       ["Custom Website", "Portfolio Platform", "Online Reservation System"], 1800, 50),
    _t("marketing_agency", "Marketing Agency",
       ["Custom Website", "CRM", "AI Automation System"], 3500, 45),
    _t("software_company", "Software Company",
       ["Custom Website", "CRM", "Business Analytics Dashboard"], 4000, 50),

    # -------- Social-media-first businesses --------
    _t("instagram_business", "Instagram Business",
       ["E-commerce Website", "CRM", "AI Chatbot"], 2200, 40),
    _t("tiktok_business", "TikTok Business",
       ["E-commerce Website", "CRM", "AI Chatbot"], 2200, 40),
    _t("facebook_business", "Facebook Business",
       ["E-commerce Website", "CRM", "AI Chatbot"], 2200, 40),

    # -------- Other --------
    _t("ngo", "NGO / Association",
       ["Custom Website", "CRM", "Donation Portal"], 2500, 50),
    _t("freelancer", "Freelancer",
       ["Custom Landing Page", "CRM", "Invoice System"], 1500, 50),
    _t("local_shop", "Local Shop",
       ["Custom Landing Page", "Inventory Management System", "POS"], 1500, 50),
    _t("other", "Other",
       ["Custom Website", "CRM"], 2000, 50),
]


# Indexes for fast lookup.
INDUSTRY_BY_KEY: Dict[str, IndustryTemplate] = {t.key: t for t in INDUSTRY_TEMPLATES}
INDUSTRY_BY_LABEL: Dict[str, IndustryTemplate] = {t.label.lower(): t for t in INDUSTRY_TEMPLATES}


def resolve_industry(raw: str) -> IndustryTemplate:
    """Resolve a free-form industry string to its template.

    Matching is fuzzy (lowercase substring). Falls back to 'other'.
    """
    raw_lower = (raw or "").strip().lower()
    if not raw_lower:
        return INDUSTRY_BY_KEY["other"]

    # Exact key match
    if raw_lower in INDUSTRY_BY_KEY:
        return INDUSTRY_BY_KEY[raw_lower]

    # Exact label match
    if raw_lower in INDUSTRY_BY_LABEL:
        return INDUSTRY_BY_LABEL[raw_lower]

    # Substring match (key or label contains the input string)
    for t in INDUSTRY_TEMPLATES:
        if raw_lower in t.key or raw_lower in t.label.lower():
            return t

    # Heuristic: try common keywords
    keyword_map = {
        "food": "restaurant", "pizza": "pizza", "burger": "fast_food",
        "cafe": "cafe", "coffee": "cafe",
        "hotel": "hotel", "resort": "resort",
        "gym": "gym", "fitness": "gym",
        "salon": "beauty_salon", "barber": "barber", "spa": "spa",
        "clothing": "clothing_store", "shoe": "shoe_store", "jewel": "jewelry_store",
        "electronic": "electronics_store", "phone": "phone_repair", "computer": "computer_store",
        "pharmac": "pharmacy", "doctor": "doctor", "dentist": "dentist",
        "hospital": "hospital", "lab": "medical_lab",
        "school": "school", "universit": "university", "training": "training_center",
        "language": "language_school",
        "lawyer": "lawyer", "attorney": "lawyer", "account": "accountant",
        "architect": "architect", "consult": "consultant",
        "construct": "construction", "interior": "interior_design",
        "furniture": "furniture", "industr": "industrial", "factor": "factory",
        "import": "import_export", "export": "import_export",
        "logist": "logistics",
        "car": "car_dealership", "auto": "car_dealership",
        "rental": "car_rental",
        "travel": "travel_agency", "event": "event_planner",
        "wedding": "wedding_hall", "photo": "photographer",
        "marketing": "marketing_agency", "software": "software_company",
        "instagram": "instagram_business", "tiktok": "tiktok_business",
        "facebook": "facebook_business",
        "ngo": "ngo", "association": "ngo",
        "freelanc": "freelancer",
        "shop": "local_shop", "store": "local_shop",
    }
    for kw, industry_key in keyword_map.items():
        if kw in raw_lower:
            return INDUSTRY_BY_KEY[industry_key]

    return INDUSTRY_BY_KEY["other"]


def all_industry_labels() -> List[str]:
    return [t.label for t in INDUSTRY_TEMPLATES]
