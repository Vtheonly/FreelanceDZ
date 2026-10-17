"""Optional SearXNG metasearch scraper (v4 Section 5.2).

A local SearXNG instance (``docker compose --profile searxng up``) returns
clean, aggregated JSON results from multiple search backends in a few
hundred milliseconds — bypassing DuckDuckGo HTML scraping and its anti-bot
rate limits entirely.

The scraper is disabled unless ``SEARXNG_URL`` is set (e.g.
``http://localhost:8888``); the engine then adds it to the aggregator
alongside DDG/Overpass, and every result flows through the same spam
gate, phone validation, and geo inference as any other source.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

from domain.enums import DataSource
from domain.models import Lead
from domain.value_objects import FreshnessMetadata
from infrastructure.scrapers.base import BaseAsyncScraper
from utils.contact_parser import extract_first_email
from utils.freshness_detector import FreshnessDetector
from utils.geo_inference import infer_wilaya_from_phone, infer_wilaya_from_text
from utils.phone_validator import SmartPhoneValidator

logger = logging.getLogger("scrapers.searxng")


class SearxngScraper(BaseAsyncScraper):
    """JSON-API client for a self-hosted SearXNG metasearch instance."""

    def __init__(self, client, base_url: str, **kwargs) -> None:
        super().__init__(client, **kwargs)
        self._base_url = base_url.rstrip("/")
        self._phone_validator = SmartPhoneValidator()
        self._freshness = FreshnessDetector()

    @property
    def source_name(self) -> str:
        return "searxng"

    # ------------------------------------------------------------------
    async def discover(self, query: str, wilaya: Optional[str] = None, limit: int = 30) -> list[Lead]:
        return [lead async for lead in self.stream_discover(query, wilaya, limit)]

    async def stream_discover(
        self, query: str, wilaya: Optional[str] = None, limit: int = 30
    ) -> AsyncIterator[Lead]:
        if not query:
            return

        full_query = f"{query} {wilaya}" if wilaya else f"{query} Algérie"
        params = {
            "q": full_query,
            "format": "json",
            "language": "fr",
            "safesearch": "0",
            "categories": "web",
        }
        response = await self._fetch(
            f"{self._base_url}/search", params=params, timeout=15.0
        )
        if response is None:
            return

        try:
            payload = response.json()
        except ValueError:
            logger.debug("SearXNG returned non-JSON payload")
            return

        seen: set[str] = set()
        yielded = 0
        for result in payload.get("results", []):
            if yielded >= limit:
                return
            url = str(result.get("url") or "")
            title = str(result.get("title") or "")
            snippet = str(result.get("content") or "")
            if not url or not title:
                continue
            if self._spam_filter.is_spam(url, title):
                continue

            text = f"{title} {snippet}"
            phones = self._phone_validator.extract_and_validate(text)
            lead = Lead(
                name=title[:200],
                industry=query.strip()[:100],
                wilaya=(wilaya or "").strip()[:100],
                website=url,
                phone=phones[0].e164 if phones else None,
                email=extract_first_email(text),
                phone_details=phones,
                social_links=[],
                source=DataSource.SEARXNG,
                source_url=url,
                notes=snippet[:400] or None,
                freshness=self._freshness.detect(snippet),
            )
            if not lead.wilaya:
                inferred = (
                    infer_wilaya_from_phone(lead.phone)
                    or infer_wilaya_from_text(text)
                )
                if inferred:
                    lead.wilaya = inferred

            fp = lead.fingerprint()
            if fp in seen:
                continue
            seen.add(fp)
            yielded += 1
            yield lead
