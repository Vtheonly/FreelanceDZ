"""Schema.org JSON-LD and DOM content extractor.

Replaces the brittle regex-only extraction of the original codebase with
a two-layer strategy:

1. **Structured schema extraction** — parse ``<script type="application/ld+json">``
   blocks and look for ``LocalBusiness``, ``Organization``, ``Store``,
   or ``Restaurant`` schemas. These give us canonical name, address,
   phone, email, and social links for free.

2. **DOM fallback** — when no schema is present, parse the HTML with
   BeautifulSoup and extract:
     * ``<title>`` for the business name.
     * ``mailto:`` and ``tel:`` links.
     * Social profile links (Facebook, Instagram, LinkedIn).
     * Email regex on visible text.

The extractor is stateless — every method is a classmethod/staticmethod
so it can be called from anywhere without instantiation.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from utils.contact_parser import extract_emails, extract_social_links


_logger = logging.getLogger("scrapers.content_extractor")


# Schema.org types we treat as business profiles.
_BUSINESS_SCHEMA_TYPES: frozenset[str] = frozenset({
    "localbusiness", "organization", "store", "restaurant",
    "industrialorganization", "corporation", "educationalorganization",
    "medicalbusiness", "pharmacy", "healthandsafetybusiness",
})


class AdvancedContentExtractor:
    """Extract structured business data from raw HTML."""

    # ------------------------------------------------------------------
    #  Schema.org JSON-LD
    # ------------------------------------------------------------------

    @classmethod
    def parse_schema_org(cls, html: str) -> Optional[dict[str, Any]]:
        """Return the first business-relevant JSON-LD block, or ``None``.

        Some sites wrap multiple schemas in a JSON array; others nest them
        under ``@graph``. We handle both.
        """
        if not html:
            return None
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        for script in soup.find_all("script", type="application/ld+json"):
            raw = script.string or script.text
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            for candidate in cls._iter_schema_candidates(data):
                if cls._is_business_schema(candidate):
                    return candidate
        return None

    @staticmethod
    def _iter_schema_candidates(data: Any):
        """Yield every dict inside ``data`` (handles arrays and ``@graph``)."""
        if isinstance(data, list):
            for item in data:
                yield from AdvancedContentExtractor._iter_schema_candidates(item)
        elif isinstance(data, dict):
            yield data
            graph = data.get("@graph")
            if isinstance(graph, list):
                for item in graph:
                    if isinstance(item, dict):
                        yield item

    @staticmethod
    def _is_business_schema(data: dict[str, Any]) -> bool:
        schema_type = str(data.get("@type", "")).lower()
        if not schema_type:
            return False
        # @type can be a string or a list — check both.
        types = [schema_type] if isinstance(schema_type, str) else [str(t).lower() for t in schema_type]
        return any(t in _BUSINESS_SCHEMA_TYPES for t in types)

    # ------------------------------------------------------------------
    #  Deep profile (schema + DOM fallback)
    # ------------------------------------------------------------------

    @classmethod
    def extract_deep_profile(cls, html: str, url: str) -> dict[str, Any]:
        """Return a structured profile dict.

        Keys: ``name``, ``address``, ``phones``, ``email``, ``socials``,
        ``rating``, ``reviews``.
        """
        output: dict[str, Any] = {
            "name": "",
            "address": None,
            "phones": [],
            "email": None,
            "socials": [],
            "rating": 0.0,
            "reviews": 0,
        }
        if not html:
            return output

        # 1. Schema-first.
        schema = cls.parse_schema_org(html)
        if schema:
            cls._merge_schema(output, schema)

        # 2. DOM fallback.
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        if not output["name"]:
            title = soup.find("title")
            if title and title.get_text(strip=True):
                output["name"] = title.get_text(strip=True)
            else:
                h1 = soup.find("h1")
                if h1 and h1.get_text(strip=True):
                    output["name"] = h1.get_text(strip=True)

        # Visible-text email scan (only if schema didn't provide one).
        if not output["email"]:
            text = soup.get_text(separator=" ", strip=True)
            emails = extract_emails(text)
            if emails:
                output["email"] = emails[0]

        # Link-level extraction for tel:, mailto:, and socials.
        all_hrefs = [link["href"] for link in soup.find_all("a", href=True)]
        for href in all_hrefs:
            if not href:
                continue
            lower = href.lower()
            if lower.startswith("mailto:") and not output["email"]:
                output["email"] = href[len("mailto:"):].split("?")[0].strip().lower()
            elif lower.startswith("tel:"):
                tel = href[len("tel:"):].strip()
                if tel and tel not in output["phones"]:
                    output["phones"].append(tel)

        # Centralised social-link extraction (filters share buttons).
        social_links = extract_social_links(all_hrefs)
        for sl in social_links:
            if sl not in output["socials"]:
                output["socials"].append(sl)

        return output

    # ------------------------------------------------------------------

    @staticmethod
    def _merge_schema(output: dict[str, Any], schema: dict[str, Any]) -> None:
        name = schema.get("name") or schema.get("legalName")
        if name:
            output["name"] = str(name).strip()

        address = schema.get("address")
        if isinstance(address, dict):
            parts = [
                address.get("streetAddress"),
                address.get("addressLocality"),
                address.get("postalCode"),
                address.get("addressRegion"),
            ]
            output["address"] = ", ".join(str(p) for p in parts if p) or None
        elif isinstance(address, str) and address.strip():
            output["address"] = address.strip()

        tel = schema.get("telephone")
        if tel:
            phones = [tel] if isinstance(tel, str) else [str(t) for t in tel]
            output["phones"] = phones

        email = schema.get("email")
        if email:
            output["email"] = str(email).lower()

        same_as = schema.get("sameAs")
        if isinstance(same_as, list):
            output["socials"] = [str(u) for u in same_as if isinstance(u, str)]
        elif isinstance(same_as, str):
            output["socials"] = [same_as]

        rating = schema.get("aggregateRating")
        if isinstance(rating, dict):
            try:
                output["rating"] = float(rating.get("ratingValue", 0.0) or 0.0)
            except (TypeError, ValueError):
                pass
            try:
                output["reviews"] = int(rating.get("reviewCount", 0) or 0)
            except (TypeError, ValueError):
                pass
