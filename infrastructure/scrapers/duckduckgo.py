"""Streaming DuckDuckGo HTML scraper.

v3 restructures discovery around iteration 4's streaming insight: results are
yielded the moment a SERP page is parsed, so the engine's audit + scoring +
persistence start on the FIRST page while later pages are still in flight
(sub-second time-to-first-result instead of full-campaign latency).

Two-layer extraction is preserved from v2.0.0 (its strongest idea):
    Layer 1 — SERP title/snippet -> Lead with phones/email/freshness.
    Layer 2 — optional deep crawl of result pages using the NATIVE SIMD
    zero-copy scanner first (title/meta/links/tel/mailto/JSON-LD pointer),
    falling back to BeautifulSoup + AdvancedContentExtractor only when the
    fast scanner finds no signal (malformed pages, heavy JS markup).
"""

from __future__ import annotations

import asyncio
import logging
from json import JSONDecodeError
from typing import AsyncIterator, Optional

from bs4 import BeautifulSoup

from domain.enums import DataSource
from domain.models import Lead
from domain.value_objects import FreshnessMetadata
from engine.native import NativeEngine
from infrastructure.scrapers.base import BaseAsyncScraper
from infrastructure.scrapers.content_extractor import AdvancedContentExtractor
from utils.anti_block_engine import CrawlerAntiBlockEngine
from utils.contact_parser import extract_first_email, extract_social_links
from utils.freshness_detector import FreshnessDetector
from utils.phone_validator import SmartPhoneValidator
from utils.url_utils import clean_url, unwrap_ddg_url

logger = logging.getLogger("scrapers.duckduckgo")

DDG_HTML_URL = "https://html.duckduckgo.com/html/"
_RESULTS_PER_PAGE = 30


class DuckDuckGoScraper(BaseAsyncScraper):
    """Paginated, streaming DDG search scraper."""

    def __init__(self, client, *, deep_crawl: bool = False, **kwargs) -> None:
        super().__init__(client, **kwargs)
        self._phone_validator = SmartPhoneValidator()
        self._freshness = FreshnessDetector()
        self._extractor = AdvancedContentExtractor()
        self._native = NativeEngine.get()
        self._deep_crawl = deep_crawl

    @property
    def source_name(self) -> str:
        return "duckduckgo"

    # ------------------------------------------------------------------
    async def discover(self, query: str, wilaya: Optional[str] = None, limit: int = 30) -> list[Lead]:
        return [lead async for lead in self.stream_discover(query, wilaya, limit)]

    async def stream_discover(
        self, query: str, wilaya: Optional[str] = None, limit: int = 30
    ) -> AsyncIterator[Lead]:
        if not query:
            return
        full_query = self._build_query(query, wilaya)
        seen: set[str] = set()
        max_pages = get_settings_max_pages()
        yielded = 0

        for page in range(max_pages):
            if yielded >= limit:
                break
            params = {"q": full_query, "s": str(page * _RESULTS_PER_PAGE), "kl": "dz-ar"}
            response = await self._fetch(DDG_HTML_URL, params=params, timeout=12.0)
            if response is None:
                break

            results = self._parse_serp(response.text)
            if not results:
                break

            # Concurrently convert + (optionally) deep-enrich this page.
            enriched = await asyncio.gather(
                *(self._result_to_lead(r, query, wilaya) for r in results),
                return_exceptions=True,
            )
            for item in enriched:
                if not isinstance(item, Lead):
                    continue
                fp = item.fingerprint()
                if fp in seen:
                    continue
                seen.add(fp)
                yielded += 1
                yield item
                if yielded >= limit:
                    return

    # ------------------------------------------------------------------
    @staticmethod
    def _build_query(query: str, wilaya: Optional[str]) -> str:
        return f"{query} {wilaya} Algérie" if wilaya else f"{query} Algérie"

    @staticmethod
    def _parse_serp(html: str) -> list[dict]:
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        results: list[dict] = []
        for result in soup.find_all("div", class_="result"):
            anchor = result.find("a", class_="result__a")
            if not anchor:
                continue
            raw_url = anchor.get("href", "")
            url = clean_url(unwrap_ddg_url(raw_url))
            title = anchor.get_text(strip=True)
            snippet_tag = result.find("a", class_="result__snippet")
            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
            if url and title:
                results.append({"url": url, "title": title, "snippet": snippet})
        return results

    async def _result_to_lead(
        self, result: dict, query: str, wilaya: Optional[str]
    ) -> Optional[Lead]:
        url, title, snippet = result["url"], result["title"], result["snippet"]
        if not url or not title or self._spam_filter.is_spam(url, title):
            return None

        text = f"{title} {snippet}"
        phones = self._phone_validator.extract_and_validate(text)
        freshness = self._freshness.detect(snippet)

        lead = Lead(
            name=title[:200],
            industry=query.strip()[:100],
            wilaya=(wilaya or "").strip()[:100],
            website=url,
            phone=phones[0].e164 if phones else None,
            email=extract_first_email(text),
            phone_details=phones,
            social_links=[],
            source=DataSource.DUCKDUCKGO,
            source_url=url,
            notes=snippet[:400] or None,
            freshness=freshness,
        )

        # Layer 2: deep enrichment for business-looking pages.
        try:
            is_social = any(
                host in url.lower()
                for host in ("facebook.com", "instagram.com", "tiktok.com")
            )
            if self._deep_crawl or is_social:
                await self._enrich(lead)
        except Exception as exc:  # enrichment is best-effort
            logger.debug("Deep enrichment failed for %s: %s", url, exc)
        return lead

    # ------------------------------------------------------------------
    async def _enrich(self, lead: Lead) -> None:
        """Fetch the target page and merge structured signals into the lead."""
        response = await self._fetch(lead.website, timeout=8.0, mobile=True)
        if response is None:
            return
        html = response.content

        # Native SIMD fast path (zero-copy structural scan).
        extraction = self._native.extract_html(html)
        json_ld_text = extraction.json_ld or None

        if extraction.has_signal and json_ld_text:
            self._merge_native(lead, extraction, json_ld_text, response)
            return

        # Fallback: full DOM parse (handles malformed pages the scanner misses).
        profile = self._extractor.extract_deep_profile(
            response.text, lead.website or ""
        )
        if profile:
            if profile.get("name"):
                lead.name = str(profile["name"])[:200]
            if profile.get("address") and not lead.address:
                lead.address = str(profile["address"])[:400]
            if profile.get("email") and not lead.email:
                lead.email = str(profile["email"])
            if profile.get("phones"):
                raw = " ".join(str(p) for p in profile["phones"])
                extra = self._phone_validator.extract_and_validate(raw)
                if extra and not lead.phone:
                    lead.phone = extra[0].e164
                lead.phone_details = self._merge_phones(lead.phone_details, extra)
            socials = profile.get("social_links") or []
            if socials:
                merged = list(dict.fromkeys(
                    lead.social_links + [str(s) for s in socials]
                ))
                lead.social_links = merged[:10]
            if profile.get("rating") is not None:
                lead.rating = max(lead.rating, float(profile["rating"]))
            if profile.get("review_count"):
                lead.review_count = max(lead.review_count, int(profile["review_count"]))
        refreshed = self._freshness.detect(response.text, response.headers)
        if refreshed.calculated_age_class.value != "older":
            lead.freshness = refreshed

    def _merge_native(self, lead: Lead, extraction, json_ld_text: str, response) -> None:
        """Apply the native scanner's findings (JSON-LD parsed in Python)."""
        import json
        try:
            schema = json.loads(json_ld_text)
        except JSONDecodeError:
            schema = None

        if isinstance(schema, dict):
            name = schema.get("name") or schema.get("legalName")
            if name:
                lead.name = str(name)[:200]
            if schema.get("telephone") and not lead.phone:
                phones = self._phone_validator.extract_and_validate(str(schema["telephone"]))
                if phones:
                    lead.phone = phones[0].e164
                    lead.phone_details = phones
            if schema.get("email") and not lead.email:
                lead.email = str(schema["email"])
            if schema.get("address"):
                addr = schema["address"]
                if isinstance(addr, dict):
                    parts = [str(addr.get(k, "")) for k in
                             ("streetAddress", "addressLocality", "addressRegion")]
                    addr = ", ".join(p for p in parts if p)
                if addr and not lead.address:
                    lead.address = str(addr)[:400]
            same_as = schema.get("sameAs") or []
            if isinstance(same_as, list):
                socials = extract_social_links_from_urls([str(s) for s in same_as])
                if socials:
                    lead.social_links = list(dict.fromkeys(lead.social_links + socials))[:10]

        if extraction.email and not lead.email:
            lead.email = extraction.email
        if extraction.phones and not lead.phone_details:
            raw = " ".join(extraction.phones)
            lead.phone_details = self._phone_validator.extract_and_validate(raw)
            if lead.phone_details and not lead.phone:
                lead.phone = lead.phone_details[0].e164
        socials = extract_social_links_from_urls(extraction.links)
        if socials:
            lead.social_links = list(dict.fromkeys(lead.social_links + socials))[:10]
        refreshed = self._freshness.detect(
            extraction.meta_description or "", response.headers
        )
        if refreshed.calculated_age_class.value != "older":
            lead.freshness = refreshed

    @staticmethod
    def _merge_phones(existing: list, extra: list) -> list:
        seen = {p.e164 for p in existing}
        return existing + [p for p in extra if p.e164 not in seen]


def extract_social_links_from_urls(urls: list[str]) -> list[str]:
    from utils.contact_parser import classify_social_platform
    out: list[str] = []
    for u in urls:
        if u.startswith(("http://", "https://", "//")) and classify_social_platform(u):
            out.append(u)
    return out


def get_settings_max_pages() -> int:
    from config.settings import get_settings
    return get_settings().MAX_SEARCH_PAGES
