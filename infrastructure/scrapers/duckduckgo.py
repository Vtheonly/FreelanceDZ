"""Async, paginated DuckDuckGo scraper.

Key improvements over the original implementation:

1. **Async** — uses the shared ``httpx.AsyncClient`` instead of blocking
   ``requests.get``. Multiple pages can be fetched concurrently when
   configured.
2. **Paginated** — iterates through up to ``MAX_SEARCH_PAGES`` pages of
   DDG results per query expansion, so a request for 30 results does
   not stop after the first page of 10.
3. **Query expansion** — the caller (the aggregator) expands the query
   into FR / MSA / Darja variants before invoking the scraper; this
   scraper just runs each variant until the limit is reached.
4. **Spam filtering** — directory aggregators (Cybo, YellowPages, etc.)
   are dropped *before* building ``BusinessRaw`` objects.
5. **Deep content extraction** — when a result URL looks like a real
   business page (not a directory), the scraper optionally fetches the
   page and runs ``AdvancedContentExtractor`` to pull structured data
   from JSON-LD schemas.
6. **Smart phone validation** — uses ``libphonenumber`` instead of
   fragile regexes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from bs4 import BeautifulSoup

from config.settings import get_settings
from domain.enums import DataSource, FreshnessAge
from domain.models import BusinessRaw
from domain.value_objects import FreshnessMetadata
from infrastructure.http.rate_limiter import AsyncRateLimiter, DomainRateLimiter
from infrastructure.scrapers.base import BaseAsyncScraper
from infrastructure.scrapers.content_extractor import AdvancedContentExtractor
from utils.contact_parser import extract_first_email, classify_social_platform
from utils.freshness_detector import FreshnessDetector
from utils.phone_validator import SmartPhoneValidator
from utils.spam_filter import SourcingSpamFilter
from utils.url_utils import clean_url, unwrap_ddg_url


_logger = logging.getLogger("scrapers.duckduckgo")

DDG_HTML_URL = "https://html.duckduckgo.com/html/"


class AsyncDuckDuckGoScraper(BaseAsyncScraper):
    """Paginated, async DuckDuckGo HTML scraper."""

    def __init__(
        self,
        client,
        spam_filter: Optional[SourcingSpamFilter] = None,
        phone_validator: Optional[SmartPhoneValidator] = None,
        freshness_detector: Optional[FreshnessDetector] = None,
        content_extractor: Optional[AdvancedContentExtractor] = None,
        rate_limiter: Optional[AsyncRateLimiter] = None,
        domain_limiter: Optional[DomainRateLimiter] = None,
        deep_crawl: bool = False,  # Disabled by default for snappy interactive searches
    ) -> None:
        super().__init__(
            client=client,
            spam_filter=spam_filter,
            rate_limiter=rate_limiter,
            domain_limiter=domain_limiter,
        )
        self._phone_validator = phone_validator or SmartPhoneValidator()
        self._freshness = freshness_detector or FreshnessDetector()
        self._content_extractor = content_extractor or AdvancedContentExtractor()
        self._deep_crawl = deep_crawl

    @property
    def source_name(self) -> str:
        return "duckduckgo"

    async def discover(
        self,
        query: str,
        wilaya: Optional[str] = None,
        limit: int = 10,
    ) -> list[BusinessRaw]:
        """Paginated discovery with deep content extraction."""
        if not query:
            return []
        self._logger.info("DDG discover: query=%r wilaya=%r limit=%d", query, wilaya, limit)

        settings = get_settings()
        max_pages = settings.MAX_SEARCH_PAGES
        discovered: list[BusinessRaw] = []
        seen_fingerprints: set[str] = set()

        for page in range(max_pages):
            if len(discovered) >= limit:
                break

            offset = page * 30  # DDG returns ~30 results per page.
            full_query = self._build_query(query, wilaya)
            params = {"q": full_query, "s": str(offset), "kl": "dz-ar"}

            response = await self._fetch(DDG_HTML_URL, params=params, timeout=12.0)
            if response is None:
                self._logger.debug("DDG page %d returned no response — stopping.", page)
                break

            results = self._parse_results(response.text)
            if not results:
                self._logger.debug("DDG page %d had no parseable results — stopping.", page)
                break

            self._logger.debug("DDG page %d: %d raw results", page, len(results))

            # Process results concurrently within the page for speed.
            batch = await asyncio.gather(
                *(
                    self._result_to_business(r, query, wilaya)
                    for r in results
                ),
                return_exceptions=True,
            )
            for item in batch:
                if not isinstance(item, BusinessRaw):
                    continue
                fp = item.fingerprint()
                if fp in seen_fingerprints:
                    continue
                seen_fingerprints.add(fp)
                discovered.append(item)
                if len(discovered) >= limit:
                    break

        self._logger.info("DDG discovered %d businesses for %r", len(discovered), query)
        return discovered

    # ------------------------------------------------------------------
    #  Parsing
    # ------------------------------------------------------------------

    def _build_query(self, query: str, wilaya: Optional[str]) -> str:
        if wilaya:
            return f"{query} {wilaya} Algérie"
        return f"{query} Algérie"

    def _parse_results(self, html: str) -> list[dict[str, str]]:
        """Extract organic result blocks from a DDG HTML page."""
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        results: list[dict[str, str]] = []
        for anchor in soup.find_all("a", class_="result__a"):
            title = anchor.get_text(strip=True)
            raw_href = anchor.get("href", "")
            url = unwrap_ddg_url(raw_href)
            if not title or not url:
                continue
            # Snippet is the next sibling with class result__snippet.
            snippet = ""
            parent = anchor.find_parent(class_="result")
            if parent is not None:
                snippet_tag = parent.find("a", class_="result__snippet")
                if snippet_tag:
                    snippet = snippet_tag.get_text(strip=True)
            results.append({"title": title, "url": url, "snippet": snippet})
        return results

    async def _result_to_business(
        self,
        result: dict[str, str],
        query: str,
        wilaya: Optional[str],
    ) -> Optional[BusinessRaw]:
        title = result.get("title", "").strip()
        url = clean_url(result.get("url", ""))
        snippet = result.get("snippet", "").strip()

        if not title or len(title) < 3 or not url:
            return None

        # Drop directory aggregators before doing any expensive work.
        if self._spam_filter.is_spam(url, title):
            return None

        # Phase 1: build a preliminary record from SERP metadata.
        phone_meta = self._phone_validator.extract_and_validate(f"{title} {snippet}")
        phone_primary = phone_meta[0].e164 if phone_meta else None
        email = extract_first_email(snippet)
        freshness_meta = self._freshness.detect(snippet)

        biz = BusinessRaw(
            name=title[:200],
            industry=query.title() if query else "Other",
            wilaya=wilaya or "Unknown",
            website=url,
            phone=phone_primary,
            email=email,
            source=DataSource.DUCKDUCKGO,
            source_url=url,
            phone_metadata=phone_meta,
            freshness=freshness_meta,
        )

        # Check if URL represents a social profile
        is_social = bool(classify_social_platform(url))

        # Always trigger deep enrichment for social links to pull contact info
        if (self._deep_crawl or is_social) and url:
            await self._enrich_with_deep_crawl(biz)

        return biz

    async def _enrich_with_deep_crawl(self, biz: BusinessRaw) -> None:
        """Fetch the business website and merge structured schema data."""
        if not biz.website:
            return
            
        platform = classify_social_platform(biz.website)
        
        # Route to specialized social scrapers if the lead is social-only
        if platform in ("facebook", "instagram", "tiktok"):
            try:
                from infrastructure.scrapers.plugins.facebook_plugin import FacebookPlugin
                from infrastructure.scrapers.plugins.instagram_plugin import InstagramPlugin
                from infrastructure.scrapers.plugins.tiktok_plugin import TikTokPlugin
                
                plugin = None
                if platform == "facebook":
                    plugin = FacebookPlugin(self.client)
                elif platform == "instagram":
                    plugin = InstagramPlugin(self.client)
                elif platform == "tiktok":
                    plugin = TikTokPlugin(self.client)
                    
                if plugin:
                    social_biz = await plugin.scrape_target(biz.website)
                    if social_biz:
                        if social_biz.name and len(social_biz.name) > 2:
                            biz.name = social_biz.name[:200]
                        if social_biz.phone:
                            biz.phone = social_biz.phone
                            biz.phone_metadata = social_biz.phone_metadata
                        if social_biz.email:
                            biz.email = social_biz.email
                        if social_biz.address and social_biz.address != "Unknown":
                            biz.address = social_biz.address
                        biz.freshness = social_biz.freshness
                        biz.social_media_handles = list(set(biz.social_media_handles + [biz.website]))
                        return
            except Exception as exc:
                self._logger.debug("Social plugin enrichment failed for %s: %s", biz.website, exc)

        # Fallback for standard websites
        response = await self._fetch(biz.website, timeout=8.0)
        if response is None:
            return
        profile = self._content_extractor.extract_deep_profile(response.text, biz.website)

        if profile.get("name") and len(profile["name"]) > 2:
            biz.name = profile["name"][:200]
        if profile.get("address"):
            biz.address = profile["address"]
        if profile.get("email") and not biz.email:
            biz.email = profile["email"]
        if profile.get("socials"):
            merged = list(set((biz.social_media_handles or []) + profile["socials"]))[:10]
            biz.social_media_handles = merged

        # Re-validate newly discovered phone numbers
        raw_phones = " ".join(profile.get("phones", []))
        if raw_phones:
            extra_meta = self._phone_validator.extract_and_validate(raw_phones)
            if extra_meta:
                combined = self._phone_validator.deduplicate(
                    list(biz.phone_metadata) + extra_meta
                )
                biz.phone_metadata = combined
                biz.phone = combined[0].e164

        # Refresh freshness from actual page content
        headers_dict = dict(response.headers) if hasattr(response, "headers") else None
        biz.freshness = self._freshness.detect(response.text, headers=headers_dict)