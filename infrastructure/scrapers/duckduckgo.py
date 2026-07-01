"""DuckDuckGo HTML scraper — no API key required.

Uses DuckDuckGo's HTML endpoint (https://html.duckduckgo.com/html/) which is
intended for non-JS clients. We parse organic results and attempt to extract
business name + URL + a snippet. Phone/email/social handles are extracted from
the snippet with simple regexes.

This is a low-fidelity source: we mostly use it as a *discovery hint* that
augments OSM. Many results may not be businesses at all; we filter aggressively.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from config.settings import settings
from domain.models import BusinessRaw, DataSource
from infrastructure.scrapers.base import BaseScraper


DDG_HTML_URL = "https://html.duckduckgo.com/html/"

# Regexes for contact extraction from snippet text.
_PHONE_RE = re.compile(r"\+?2?13?\s?\d[\d\s\-.]{6,}\d")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_SOCIAL_RE = re.compile(
    r"(https?://(?:www\.)?(?:facebook|instagram|linkedin|twitter|tiktok|youtube)\.com/[^\s\"<>]+)",
    re.IGNORECASE,
)


class DuckDuckGoScraper(BaseScraper):
    """Discovers businesses via DuckDuckGo HTML search."""

    source_name = "duckduckgo"

    def discover_businesses(
        self,
        query: str,
        wilaya: Optional[str] = None,
        limit: int = 10,
    ) -> List[BusinessRaw]:
        self._logger.info("DDG discovery: query=%r wilaya=%r limit=%d", query, wilaya, limit)

        full_query = f"{query} {wilaya} Algeria" if wilaya else f"{query} Algeria"
        # DDG HTML page returns up to ~30 results per request.
        resp = self._safe_get(DDG_HTML_URL, params={"q": full_query, "kl": "dz-ar"})
        if resp is None:
            return []

        try:
            from html.parser import HTMLParser
        except ImportError:
            return []

        results = self._parse_ddg_html(resp.text)
        self._logger.info("DDG returned %d parsed results", len(results))

        businesses: List[BusinessRaw] = []
        for r in results[:limit]:
            biz = self._result_to_business(r, query, wilaya)
            if biz is not None:
                businesses.append(biz)

        self._logger.info("Converted %d DDG results into BusinessRaw.", len(businesses))
        return businesses

    # ------------------------------------------------------------------
    # HTML parsing — keep it dependency-free (no BeautifulSoup).
    # ------------------------------------------------------------------

    def _parse_ddg_html(self, html: str) -> List[dict]:
        """Extract organic result blocks from DDG HTML page."""
        results: List[dict] = []
        # Result containers look like:
        # <a class="result__a" href="...">Title</a>
        # <a class="result__snippet" ...>Snippet text</a>
        title_re = re.compile(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.+?)</a>', re.S)
        snippet_re = re.compile(r'<a[^>]+class="result__snippet"[^>]*>(.+?)</a>', re.S)

        titles = title_re.findall(html)
        snippets = snippet_re.findall(html)

        # Pair them by index (DDG outputs them in order).
        for i, (raw_url, raw_title) in enumerate(titles):
            snippet = snippets[i][0] if i < len(snippets) else ""
            clean_title = self._strip_tags(raw_title)
            clean_snippet = self._strip_tags(snippet)
            real_url = self._unwrap_ddg_url(raw_url)
            results.append({
                "title": clean_title,
                "snippet": clean_snippet,
                "url": real_url,
            })
        return results

    @staticmethod
    def _strip_tags(s: str) -> str:
        s = re.sub(r"<[^>]+>", "", s)
        s = re.sub(r"&amp;", "&", s)
        s = re.sub(r"&quot;", '"', s)
        s = re.sub(r"&#x27;", "'", s)
        s = re.sub(r"&nbsp;", " ", s)
        return s.strip()

    @staticmethod
    def _unwrap_ddg_url(raw_url: str) -> str:
        """DDG wraps external URLs in a redirect like //duckduckgo.com/l/?uddg=<URL>."""
        if raw_url.startswith("//"):
            raw_url = "https:" + raw_url
        parsed = urlparse(raw_url)
        if "duckduckgo.com" in parsed.netloc:
            qs = parse_qs(parsed.query)
            if "uddg" in qs:
                return unquote(qs["uddg"][0])
        return raw_url

    # ------------------------------------------------------------------

    def _result_to_business(
        self,
        result: dict,
        query: str,
        wilaya: Optional[str],
    ) -> Optional[BusinessRaw]:
        title = result.get("title", "").strip()
        snippet = result.get("snippet", "").strip()
        url = result.get("url", "").strip()

        if not title or len(title) < 3:
            return None

        # Aggressive filter: title must contain the query OR snippet must mention Algeria.
        q_lower = (query or "").lower()
        title_lower = title.lower()
        snippet_lower = snippet.lower()
        if q_lower and q_lower not in title_lower and q_lower not in snippet_lower:
            if "algeri" not in snippet_lower and "alger" not in snippet_lower:
                return None

        # Try to detect phone / email / social in the snippet.
        phone_match = _PHONE_RE.search(snippet)
        email_match = _EMAIL_RE.search(snippet)
        social_matches = _SOCIAL_RE.findall(snippet)

        # Industry best-guess from query.
        industry = query.title() if query else "Other"

        try:
            return BusinessRaw(
                name=title[:120],
                industry=industry,
                wilaya=wilaya or "Unknown",
                website=url if url.startswith("http") else None,
                phone=phone_match.group(0).strip() if phone_match else None,
                email=email_match.group(0) if email_match else None,
                social_media_handles=[s for s in social_matches][:3],
                source=DataSource.DDG,
                source_url=url,
            )
        except Exception as e:
            self._logger.debug("Skipped DDG result (%s): %s", title[:40], e)
            return None
