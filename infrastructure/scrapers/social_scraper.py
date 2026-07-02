"""Async scraper for social-media profile pages (Facebook, Instagram, TikTok).

Social platforms are *much* harder to scrape than regular websites:
they render content with client-side JavaScript, return login walls to
anonymous clients, and aggressively block datacenter IPs.

This scraper is intentionally *defensive*:

* It does NOT attempt to log in or bypass authentication.
* It only extracts publicly-visible metadata (Open Graph tags,
  JSON-LD, ``<meta>`` description).
* It rotates mobile User-Agents because mobile social pages expose
  more public metadata than desktop pages.
* It gracefully degrades — if a profile is private or returns a login
  wall, the scraper returns ``None`` and the aggregator moves on.

For production use behind aggressive WAFs, swap this module for a
Playwright-backed implementation (see ``scraper_plugins`` package).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from domain.enums import DataSource
from domain.models import BusinessRaw
from domain.value_objects import FreshnessMetadata
from infrastructure.scrapers.base import BaseAsyncScraper
from infrastructure.scrapers.content_extractor import AdvancedContentExtractor
from utils.anti_block_engine import CrawlerAntiBlockEngine
from utils.freshness_detector import FreshnessDetector
from utils.phone_validator import SmartPhoneValidator


_logger = logging.getLogger("scrapers.social")


class SocialScraper(BaseAsyncScraper):
    """Public-profile scraper for social-media pages."""

    def __init__(
        self,
        client,
        phone_validator: Optional[SmartPhoneValidator] = None,
        freshness_detector: Optional[FreshnessDetector] = None,
        content_extractor: Optional[AdvancedContentExtractor] = None,
    ) -> None:
        super().__init__(client=client)
        self._phone_validator = phone_validator or SmartPhoneValidator()
        self._freshness = freshness_detector or FreshnessDetector()
        self._content_extractor = content_extractor or AdvancedContentExtractor()

    @property
    def source_name(self) -> str:
        return "social"

    async def discover(
        self,
        query: str,
        wilaya: Optional[str] = None,
        limit: int = 10,
    ) -> list[BusinessRaw]:
        """Social discovery is not query-driven — use ``scrape_target`` instead.

        This method exists to satisfy the ``IScraper`` contract so the
        aggregator can include the social scraper in its rotation, but
        it returns an empty list by default. The aggregator should call
        ``scrape_target`` with specific profile URLs discovered via SERP.
        """
        return []

    async def scrape_target(self, url: str) -> Optional[BusinessRaw]:
        """Scrape a single social-media profile URL.

        Returns ``None`` if the page is private, returns a login wall,
        or otherwise cannot be parsed.
        """
        if not url:
            return None
        host = urlparse(url).netloc.lower()
        if not any(h in host for h in ("facebook.com", "instagram.com", "tiktok.com", "linkedin.com")):
            return None

        self._logger.info("Social scrape target: %s", url)
        # Use a mobile UA — social platforms expose more public metadata
        # to mobile clients.
        response = await self._fetch(url, mobile=True, timeout=12.0)
        if response is None:
            return None

        html = response.text
        if self._looks_like_login_wall(html):
            self._logger.debug("Login wall detected for %s — skipping.", url)
            return None

        profile = self._extract_social_profile(html, url)
        if not profile.get("name"):
            return None

        phone_meta = self._phone_validator.extract_and_validate(
            f"{profile.get('name', '')} {profile.get('description', '')}"
        )
        freshness = self._freshness.detect(html, headers=dict(response.headers))

        return BusinessRaw(
            name=profile["name"][:200],
            industry=profile.get("industry", "Social Profile"),
            wilaya="Unknown",
            address=profile.get("address"),
            website=url,
            phone=phone_meta[0].e164 if phone_meta else None,
            email=profile.get("email"),
            social_media_handles=[url],
            rating=float(profile.get("rating", 0.0) or 0.0),
            review_count=int(profile.get("reviews", 0) or 0),
            source=DataSource.SOCIAL,
            source_url=url,
            phone_metadata=phone_meta,
            freshness=freshness,
        )

    # ------------------------------------------------------------------

    def _looks_like_login_wall(self, html: str) -> bool:
        """Heuristic: detect login walls / captcha pages."""
        if not html:
            return True
        lower = html.lower()
        # Very small responses are almost always login redirects.
        if len(html) < 1500:
            return True
        indicators = (
            "log in to facebook", "log into facebook",
            "log in to instagram", "sign up for tiktok",
            "you must log in", "please log in",
            "captcha", "are you a robot",
        )
        return any(ind in lower for ind in indicators)

    def _extract_social_profile(self, html: str, url: str) -> dict:
        """Pull Open Graph, JSON-LD, and meta-description data."""
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        profile: dict = {"name": "", "description": "", "email": None, "address": None}

        # Open Graph tags.
        og_title = soup.find("meta", property="og:title")
        og_desc = soup.find("meta", property="og:description")
        og_type = soup.find("meta", property="og:type")
        if og_title and og_title.get("content"):
            profile["name"] = og_title["content"].strip()
        if og_desc and og_desc.get("content"):
            profile["description"] = og_desc["content"].strip()
        if og_type and og_type.get("content"):
            profile["industry"] = og_type["content"].strip()

        # JSON-LD schema (some social pages embed it).
        schema = self._content_extractor.parse_schema_org(html)
        if schema:
            if not profile["name"]:
                profile["name"] = str(schema.get("name", "")).strip()
            if not profile["description"]:
                profile["description"] = str(schema.get("description", "")).strip()
            if schema.get("email"):
                profile["email"] = str(schema.get("email")).lower()
            addr = schema.get("address")
            if isinstance(addr, dict):
                profile["address"] = str(addr.get("streetAddress", "")).strip() or None
            elif isinstance(addr, str):
                profile["address"] = addr

        # Fallback to <title> tag.
        if not profile["name"]:
            title = soup.find("title")
            if title and title.get_text(strip=True):
                # Strip platform suffix ("... | Facebook", "... - Instagram").
                raw = title.get_text(strip=True)
                profile["name"] = re.split(r"\s*[|\-–]\s*", raw)[0].strip()

        return profile
