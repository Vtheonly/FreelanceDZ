"""LLM prompt templates — single source of truth for what we ask the model.

Keeping prompts here (rather than inline in client code) makes them easy to
iterate on without touching Python logic.
"""

from __future__ import annotations

from config.industries import resolve_industry
from config.services_catalog import all_service_names


SYSTEM_PROMPT = (
    "You are an expert Algerian enterprise software development consultant.\n"
    "You analyse local businesses and identify which custom software services "
    "they would genuinely benefit from, given the Algerian market reality "
    "(low web adoption, heavy reliance on Facebook/Instagram, growing e-payments via CIB / Edahabia).\n\n"
    "Your output MUST be valid JSON matching the schema requested. "
    "Do not include any markdown, code fences, or commentary outside the JSON.\n"
)


def build_user_prompt(business) -> str:
    """Build the user-side prompt for a single business.

    Args:
        business: a `domain.models.BusinessRaw` instance.

    Returns:
        A multi-line prompt string ending with the strict JSON schema.
    """
    industry_template = resolve_industry(business.industry)
    typical = ", ".join(industry_template.typical_services[:5]) or "n/a"
    services_list = ", ".join(all_service_names())

    has_website = "YES" if business.website else "NO"
    has_social = "YES" if business.social_media_handles else "NO"
    social_str = ", ".join(business.social_media_handles) if business.social_media_handles else "NONE"

    return f"""Analyse the following Algerian business and recommend which custom software services we should pitch to them.

BUSINESS DETAILS:
- Name: {business.name}
- Industry: {business.industry}
- Wilaya (Province): {business.wilaya}, Algeria
- Has Website: {has_website}
- Website URL: {business.website or 'NONE'}
- Phone: {business.phone or 'NONE'}
- Email: {business.email or 'NONE'}
- Social Media: {social_str}
- Public Rating: {business.rating}/5.0 from {business.review_count} reviews
- Address: {business.address or 'NONE'}

INDUSTRY CONTEXT:
- Typical services needed for {business.industry}: {typical}
- Average project value in this industry (USD): {industry_template.average_project_value_usd}

ALLOWED SERVICES (use these exact names when relevant):
{services_list}

Return a SINGLE JSON object matching EXACTLY this schema (no extra keys, no markdown):

{{
  "pain_points": [
    "specific operational pain point 1",
    "specific operational pain point 2",
    "specific operational pain point 3"
  ],
  "recommended_solutions": [
    {{
      "service_name": "exact service name from the allowed list",
      "justification": "one-sentence reason this specific business needs it",
      "estimated_value_usd": 1500.00,
      "priority": 8
    }}
  ],
  "digital_presence_score": 45,
  "pitch_angles": [
    "sales hook 1 — appeal to revenue growth or cost cutting",
    "sales hook 2 — appeal to competitor pressure or customer expectations"
  ],
  "estimated_monthly_revenue_usd": 8000.00
}}

Rules:
- Provide 2 to 4 pain_points.
- Provide 2 to 5 recommended_solutions, ordered by priority (highest first).
- `priority` is an integer 1–10 (10 = must pitch immediately).
- `digital_presence_score` is 0–100 (0 = no presence, 100 = excellent).
- `estimated_value_usd` should reflect Algerian market rates (lower than EU/US).
- All text in English.
"""


def build_health_check_prompt() -> str:
    """A minimal prompt used by `health_check()` to verify the API works."""
    return 'Reply with the JSON object: {"status":"ok"}. No other text.'
