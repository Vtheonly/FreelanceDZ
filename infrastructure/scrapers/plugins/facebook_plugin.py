"""Facebook profile/page scraper plugin.

Extracts publicly-visible metadata from Facebook pages without logging
in. Relies on Open Graph tags and JSON-LD blocks; falls back to the
generic ``AdvancedContentExtractor`` when neither is present.

For pages behind aggressive WAFs, swap this implementation for a
Playwright-backed one (the contract stays the same).
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from domain.enums import DataSource
from domain.models import BusinessRaw
from domain.value_objects import FreshnessMetadata
from infrastructure.scrapers.content_extractor import AdvancedContentExtractor
from infrastructure.scrapers.plugins.base_plugin import BaseScraperPlugin
from utils.freshness_detector import FreshnessDetector
from utils.phone_validator import SmartPhoneValidator


_logger = logging.getLogger("scrapers.plugins.facebook")


class FacebookPlugin(BaseScraperPlugin):
    """Public Facebook page scraper."""

    platform_domain = "facebook.com"
    _PHONE_RE = re.compile(r"\+?\d[\d\s\-.]{6,}\d")

    def __init__(self, client, **kwargs) -> None:
        super().__init__(client, **kwargs)
        self._content_extractor = AdvancedContentExtractor()
        self._phone_validator = SmartPhoneValidator()
        self._freshness = FreshnessDetector()

    @property
    def source_name(self) -> str:
        return "facebook"

    async def scrape_target(self, url: str) -> Optional[BusinessRaw]:
        if "facebook.com" not in urlparse(url).netloc.lower():
            return None
        response = await self._fetch(url, mobile=True, timeout=12.0)
        if response is None:
            return None
        html = response.text
        if self._is_login_wall(html):
            _logger.debug("Facebook login wall: %s", url)
            return None

        soup = self._make_soup(html)
        name = self._extract_name(soup)
        if not name:
            return None

        description = self._extract_meta(soup, "description")
        phone_text = " ".join(self._extract_phones(soup))
        phone_meta = self._phone_validator.extract_and_validate(
            f"{name} {description} {phone_text}"
        )

        return BusinessRaw(
            name=name[:200],
            industry="Facebook Page",
            wilaya="Unknown",
            website=url,
            phone=phone_meta[0].e164 if phone_meta else None,
            email=None,
            social_media_handles=[url],
            source=DataSource.SOCIAL,
            source_url=url,
            phone_metadata=phone_meta,
            freshness=self._freshness.detect(html, headers=dict(response.headers)),
        )

    # ------------------------------------------------------------------

    def _is_login_wall(self, html: str) -> bool:
        if not html or len(html) < 2000:
            return True
        lower = html.lower()
        return any(s in lower for s in (
            "log in to facebook", "you must log in", "sign up for facebook",
            "captcha-block",
        ))

    def _make_soup(self, html: str) -> BeautifulSoup:
        try:
            return BeautifulSoup(html, "lxml")
        except Exception:
            return BeautifulSoup(html, "html.parser")

    def _extract_name(self, soup: BeautifulSoup) -> str:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            return og["content"].strip()
        title = soup.find("title")
        if title and title.get_text(strip=True):
            return title.get_text(strip=True).split(" - ")[0].split(" | ")[0].strip()
        return ""

    def _extract_meta(self, soup: BeautifulSoup, prop: str) -> str:
        meta = soup.find("meta", attrs={"name": prop}) or soup.find("meta", property=f"og:{prop}")
        return meta.get("content", "").strip() if meta and meta.get("content") else ""

    def _extract_phones(self, soup: BeautifulSoup) -> list[str]:
        phones: list[str] = []
        for a in soup.find_all("a", href=True):
            if a["href"].lower().startswith("tel:"):
                phones.append(a["href"][4:].strip())
        return phones
