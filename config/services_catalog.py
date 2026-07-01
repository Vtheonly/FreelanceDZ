"""Catalogue of software services we sell, with default pricing.

Used by:
  * The LLM prompt (to constrain recommendations to what we actually deliver).
  * The fallback analyzer.
  * The CLI `stats` command (revenue potential per service).
"""

from __future__ import annotations

from typing import Dict, List


# Each entry: (key, display_name, default_price_usd, category).
SERVICES_CATALOG: List[Dict[str, object]] = [
    # -------- Web --------
    {"key": "custom_website",            "name": "Custom Website",                  "price": 2000, "category": "Web"},
    {"key": "landing_page",              "name": "Professional Landing Page",       "price": 800,  "category": "Web"},
    {"key": "ecommerce_website",         "name": "E-commerce Website",              "price": 3500, "category": "Web"},
    {"key": "website_redesign",          "name": "Website Redesign",                "price": 1800, "category": "Web"},
    {"key": "real_estate_platform",      "name": "Real Estate Platform",            "price": 4000, "category": "Web"},

    # -------- Industry-specific platforms --------
    {"key": "restaurant_ordering",       "name": "Restaurant Ordering System",      "price": 2500, "category": "Industry"},
    {"key": "hotel_booking",             "name": "Hotel Booking Platform",          "price": 4500, "category": "Industry"},
    {"key": "appointment_booking",       "name": "Appointment Booking System",      "price": 1800, "category": "Industry"},
    {"key": "online_reservation",        "name": "Online Reservation System",       "price": 2000, "category": "Industry"},

    # -------- Management systems --------
    {"key": "medical_management",        "name": "Medical Management System",       "price": 3500, "category": "Management"},
    {"key": "clinic_management",         "name": "Clinic Management System",        "price": 3000, "category": "Management"},
    {"key": "hospital_management",       "name": "Hospital Management System",      "price": 8000, "category": "Management"},
    {"key": "gym_management",            "name": "Gym Management System",           "price": 3000, "category": "Management"},
    {"key": "school_management",         "name": "School Management System",        "price": 4500, "category": "Management"},
    {"key": "university_management",     "name": "University Management System",    "price": 10000,"category": "Management"},
    {"key": "construction_management",   "name": "Construction Management System",  "price": 6000, "category": "Management"},

    # -------- Operations --------
    {"key": "employee_management",       "name": "Employee Management System",      "price": 2500, "category": "Operations"},
    {"key": "hr_system",                 "name": "Human Resource System",           "price": 3500, "category": "Operations"},
    {"key": "inventory_management",      "name": "Inventory Management System",     "price": 2500, "category": "Operations"},
    {"key": "warehouse_management",      "name": "Warehouse Management System",     "price": 4000, "category": "Operations"},
    {"key": "delivery_management",       "name": "Delivery Management Platform",    "price": 3000, "category": "Operations"},
    {"key": "fleet_management",          "name": "Fleet Management System",         "price": 4000, "category": "Operations"},
    {"key": "workflow_automation",       "name": "Workflow Automation",             "price": 3500, "category": "Operations"},
    {"key": "business_automation",       "name": "Business Automation",             "price": 4000, "category": "Operations"},

    # -------- POS / finance --------
    {"key": "restaurant_pos",            "name": "Restaurant POS System",           "price": 1800, "category": "POS"},
    {"key": "retail_pos",                "name": "Retail POS System",               "price": 1800, "category": "POS"},
    {"key": "accounting_system",         "name": "Accounting System",               "price": 3000, "category": "Finance"},
    {"key": "invoice_system",            "name": "Invoice System",                  "price": 1500, "category": "Finance"},
    {"key": "payroll_system",            "name": "Payroll System",                  "price": 1800, "category": "Finance"},

    # -------- Enterprise / BI --------
    {"key": "crm",                       "name": "Customer Relationship Management","price": 3500, "category": "Enterprise"},
    {"key": "erp",                       "name": "Enterprise Resource Planning",    "price": 8000, "category": "Enterprise"},
    {"key": "scheduling_system",         "name": "Scheduling System",               "price": 2000, "category": "Enterprise"},
    {"key": "customer_portal",           "name": "Customer Portal",                 "price": 2500, "category": "Enterprise"},
    {"key": "admin_dashboard",           "name": "Admin Dashboard",                 "price": 2000, "category": "Enterprise"},
    {"key": "analytics_dashboard",       "name": "Business Analytics Dashboard",    "price": 3000, "category": "BI"},
    {"key": "data_visualization",        "name": "Data Visualization Platform",     "price": 4000, "category": "BI"},
    {"key": "bi_dashboard",              "name": "Business Intelligence Dashboard", "price": 4500, "category": "BI"},

    # -------- AI --------
    {"key": "ai_chatbot",                "name": "AI Chatbot",                      "price": 2500, "category": "AI"},
    {"key": "ai_customer_support",       "name": "AI Customer Support",             "price": 3000, "category": "AI"},
    {"key": "ai_voice_assistant",        "name": "AI Voice Assistant",              "price": 4000, "category": "AI"},
    {"key": "ai_sales_assistant",        "name": "AI Sales Assistant",              "price": 3000, "category": "AI"},
    {"key": "ai_lead_qualification",     "name": "AI Lead Qualification System",    "price": 2500, "category": "AI"},
    {"key": "ai_document_processing",    "name": "AI Document Processing",          "price": 3500, "category": "AI"},
    {"key": "ai_ocr",                    "name": "AI OCR System",                   "price": 3000, "category": "AI"},
    {"key": "ai_automation",             "name": "AI Automation System",            "price": 3500, "category": "AI"},
    {"key": "ai_knowledge_base",         "name": "AI Knowledge Base",               "price": 2800, "category": "AI"},
    {"key": "ai_internal_assistant",     "name": "AI Internal Assistant",           "price": 3000, "category": "AI"},
    {"key": "ai_search_engine",          "name": "AI Search Engine",                "price": 4000, "category": "AI"},
    {"key": "ai_recommendation",         "name": "AI Recommendation System",        "price": 3500, "category": "AI"},
    {"key": "machine_learning",          "name": "Machine Learning Solutions",      "price": 6000, "category": "AI"},
    {"key": "computer_vision",           "name": "Computer Vision Solutions",       "price": 6000, "category": "AI"},

    # -------- Engineering --------
    {"key": "custom_api",                "name": "Custom APIs",                     "price": 2500, "category": "Engineering"},
    {"key": "backend_systems",           "name": "Backend Systems",                 "price": 4000, "category": "Engineering"},
    {"key": "desktop_application",       "name": "Desktop Application",             "price": 3500, "category": "Engineering"},
    {"key": "android_application",       "name": "Android Application",             "price": 4500, "category": "Engineering"},

    # -------- Modernization --------
    {"key": "database_modernization",    "name": "Database Modernization",          "price": 3500, "category": "Modernization"},
    {"key": "legacy_modernization",      "name": "Legacy Software Modernization",   "price": 5000, "category": "Modernization"},
    {"key": "performance_optimization",  "name": "Performance Optimization",        "price": 2500, "category": "Modernization"},
    {"key": "digital_transformation",    "name": "Digital Transformation",          "price": 8000, "category": "Modernization"},
    {"key": "custom_software",           "name": "Custom Software Engineering",     "price": 5000, "category": "Modernization"},
    {"key": "portfolio_platform",        "name": "Portfolio Platform",              "price": 1500, "category": "Web"},
    {"key": "membership_management",     "name": "Membership Management System",    "price": 2000, "category": "Management"},
    {"key": "lms",                       "name": "Learning Management System",      "price": 3500, "category": "Industry"},
    {"key": "loyalty_program",           "name": "Loyalty Program System",          "price": 1500, "category": "Operations"},
    {"key": "repair_tracking",           "name": "Repair Tracking System",          "price": 1800, "category": "Industry"},
    {"key": "donation_portal",           "name": "Donation Portal",                 "price": 1500, "category": "Web"},
    {"key": "event_management",          "name": "Event Management System",         "price": 2500, "category": "Industry"},
]


# Indexes.
SERVICES_BY_KEY: Dict[str, Dict[str, object]] = {s["key"]: s for s in SERVICES_CATALOG}
SERVICES_BY_NAME: Dict[str, Dict[str, object]] = {
    s["name"].lower(): s for s in SERVICES_CATALOG
}


def all_service_names() -> List[str]:
    """All service display names — injected into the LLM prompt."""
    return [s["name"] for s in SERVICES_CATALOG]


def find_service_by_name(name: str) -> Dict[str, object] | None:
    """Look up a service by display name (case-insensitive)."""
    return SERVICES_BY_NAME.get((name or "").strip().lower())


def default_price_for(service_name: str) -> float:
    """Return the catalogue default price for a service, or 2000 USD fallback."""
    svc = find_service_by_name(service_name)
    if svc:
        return float(svc["price"])
    return 2000.0
