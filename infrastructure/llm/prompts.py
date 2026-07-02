"""Prompt templates for LLM calls.

Centralising prompts here means we can A/B test them, version them, and
audit them without touching client code. Each prompt is a plain string
with ``{placeholder}`` markers filled by ``str.format``.
"""

from __future__ import annotations


SYSTEM_PROMPT_ANALYZER = (
    "You are a senior B2B sales analyst specialised in the Algerian market.\n"
    "You receive a JSON description of a discovered business and must produce\n"
    "a structured analysis covering pain points, recommended software services,\n"
    "and pitch angles. All reasoning must be grounded in the provided data —\n"
    "never invent facts. If a field is missing, say so explicitly.\n"
    "Always respond with valid JSON matching the requested schema and nothing else."
)


PROMPT_ANALYZE_BUSINESS = """\
Analyse the following Algerian business and produce a B2B sales analysis.

Business data (JSON):
{business_json}

Return a JSON object with EXACTLY this shape (no markdown, no commentary):
{{
  "pain_points": ["..."],
  "recommended_solutions": [
    {{
      "service_name": "...",
      "justification": "...",
      "estimated_value_usd": 0.0,
      "priority": 5
    }}
  ],
  "digital_presence_score": 50,
  "pitch_angles": ["..."],
  "estimated_monthly_revenue_usd": null
}}

Rules:
- pain_points: 2-5 concrete operational problems this business likely faces.
- recommended_solutions: 1-3 software services relevant to its industry.
- estimated_value_usd: realistic project size in USD for the Algerian market.
- priority: 1 (low) to 10 (must-pitch).
- digital_presence_score: 0 (no presence) to 100 (excellent).
- pitch_angles: 1-3 hooks a salesperson could use in the first email.
- If the business name or industry looks like a directory listing or
  aggregator page (e.g. "List of pharmacies in Oran"), return an empty
  recommended_solutions array and set digital_presence_score to 0.
"""


SYSTEM_PROMPT_QUERY_EXPANDER = (
    "You are an expert Algerian market intelligence analyst.\n"
    "Your task is to expand a business query into related keywords, synonyms,\n"
    "and localized phrases covering French, Modern Standard Arabic, and\n"
    "Algerian Darja. Return a JSON array of strings only — no markdown,\n"
    "no commentary."
)


PROMPT_EXPAND_QUERY = """\
User Query: "{query}"

Generate exactly 6 to 9 highly relevant search terms covering:
1. Professional French terminology used in Algeria.
2. Modern Standard Arabic (MSA) industrial/commercial equivalents.
3. Local Algerian Arabic (Darja) colloquial terms.

Return a JSON array of strings ONLY.
Example: ["term1", "term2", "term3"]
"""
