"""TikTok profile scraper plugin.

Like Instagram, TikTok gates most content behind a login wall for
anonymous clients. This plugin extracts whatever Open Graph metadata
is publicly visible (username, bio, profile picture) and falls back
to ``None`` when the page is gated.
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlparse

from domain.enums import DataSource
from domain.models import BusinessRaw
from domain.value_objects import FreshnessMetadata
from infrastructure.scrapers.plugins.base_plugin import BaseScraperPlugin
from utils.freshness_detector import FreshnessDetector
from utils.phone_validator import SmartPhoneValidator


_logger = logging.getLogger("scrapers.plugins.tiktok")


class TikTokPlugin(BaseScraperPlugin):
    """Public TikTok profile scraper."""

    platform_domain = "tiktok.com"

    def __init__(self, client, **kwargs) -> None:
        super().__init__(client, **kwargs)
        self._phone_validator = SmartPhoneValidator()
        self._freshness = FreshnessDetector()

    @property
    def source_name(self) -> str:
        return "tiktok"

    async def scrape_target(self, url: str) -> Optional[BusinessRaw]:
        if "tiktok.com" not in urlparse(url).netloc.lower():
            return None
        response = await self._fetch(url, mobile=True, timeout=12.0)
        if response is None:
            return None
        html = response.text
        if self._is_login_wall(html):
            _logger.debug("TikTok login wall: %s", url)
            return None

        name = self._extract_og_title(html)
        description = self._extract_og_description(html)
        if not name:
            return None

        phone_meta = self._phone_validator.extract_and_validate(f"{name} {description}")

        return BusinessRaw(
            name=name[:200],
            industry="TikTok Profile",
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
        if not html or len(html) < 1500:
            return True
        lower = html.lower()
        return any(s in lower for s in (
            "log in to tiktok", "sign up for tiktok",
            "are you a robot", "captcha",
        ))

    def _extract_og_title(self, html: str) -> str:
        match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
        if match:
            return match.group(1).strip()
        t = re.search(r"<title>([^<]+)</title>", html)
        return t.group(1).strip() if t else ""

    def _extract_og_description(self, html: str) -> str:
        match = re.search(r'<meta\s+property="og:description"\s+content="([^"]+)"', html)
        return match.group(1).strip() if match else ""
