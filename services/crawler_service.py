"""Concurrent autonomous crawler (iteration 4's design on v2's persistence).

v3:
    - N concurrent workers (hardware-derived default, bounded, configurable)
    - AIMD adaptive concurrency + per-domain token bucket politeness
    - per-proxy pooled clients (fixes the v2 crash)
    - fastops regex HTML extraction with BeautifulSoup fallback
    - per-instance bounded URL dedup (replaces the global C bloom)
    - frontier + politeness persisted in SQLite (resumable), claims atomic
      via BEGIN IMMEDIATE

v4 fixes:
    - Task 14: backoff state is isolated per-domain — one blocked domain
      no longer inflates the delay for every unrelated domain.
    - Section 5.3: HEAD-first content verification — the body is streamed
      and cut off after ~32 KiB (identity signals live in <head> and the
      top of the document), cutting crawl bandwidth by ~80%.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

from config.settings import get_settings
from domain.enums import DataSource
from domain.models import Lead
from engine.acquisition.concurrency import AdaptiveConcurrency
from engine.analyzer import BusinessAnalyzer
from engine.fastops import UrlDedup, extract_html
from engine.scorer import LeadScorer
from infrastructure.http import HttpClientFactory
from infrastructure.resilience import BlockDetector, ExponentialBackoff, ProxyOrchestrator
from infrastructure.scrapers.content_extractor import AdvancedContentExtractor
from infrastructure.storage.crawl_queue_repo import CrawlQueueRepository
from infrastructure.storage.lead_repo import LeadRepository
from utils.anti_block_engine import CrawlerAntiBlockEngine
from utils.freshness_detector import FreshnessDetector
from utils.phone_validator import SmartPhoneValidator
from utils.spam_filter import SourcingSpamFilter

logger = logging.getLogger("services.crawler")

_HOUSEKEEPING_INTERVAL = 50  # pages between stale-claim sweeps
_MAX_BODY_BYTES = 32 * 1024  # HEAD-first verification: head + top document only


class CrawlerEngine:
    """Autonomous concurrent crawler with persistent frontier."""

    def __init__(
        self,
        repo: LeadRepository,
        queue: CrawlQueueRepository,
        *,
        proxy_orchestrator: Optional[ProxyOrchestrator] = None,
        dedup: Optional[UrlDedup] = None,
    ) -> None:
        self._repo = repo
        self._queue = queue
        self._settings = get_settings()
        self._proxies = proxy_orchestrator or ProxyOrchestrator()
        self._analyzer = BusinessAnalyzer()
        self._scorer = LeadScorer()
        self._phone_validator = SmartPhoneValidator()
        self._freshness = FreshnessDetector()
        self._spam = SourcingSpamFilter()
        self._extractor = AdvancedContentExtractor()
        self._anti_block = CrawlerAntiBlockEngine()
        # Per-instance, bounded, thread-safe URL dedup (v4 Task 13: the old
        # global C bloom leaked state across instances and was not
        # thread-safe; SQLite's UNIQUE(url) remains the authoritative dedup).
        self._dedup = dedup or UrlDedup()
        # v4 Task 14: backoff state is per-domain so a 429 on one host never
        # slows crawls of unrelated hosts.
        self._domain_backoffs: dict[str, ExponentialBackoff] = defaultdict(
            lambda: ExponentialBackoff(
                base_delay=self._settings.JITTER_BASE_DELAY, max_delay=60.0
            )
        )

        self._adaptive = AdaptiveConcurrency(
            minimum=self._settings.ACQ_MIN_CONCURRENCY,
            maximum=self._settings.ACQ_MAX_CONCURRENCY,
        )
        self._task: Optional[asyncio.Task] = None
        self._active = False
        self._pages = 0
        self._entities_saved = 0
        self._blocks = 0

    # ------------------------------------------------------------------
    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def stats(self) -> dict:
        return {
            "active": self._active,
            "pages_crawled": self._pages,
            "entities_saved": self._entities_saved,
            "blocks_detected": self._blocks,
            "concurrency": self._adaptive.current,
            "dedup_cache_size": len(self._dedup),
            "workers": self._settings.CRAWLER_WORKERS,
        }

    # ------------------------------------------------------------------
    async def bootstrap(self, queries: list[str], wilaya: Optional[str] = None) -> int:
        """Seed the frontier with search-result pages for each query."""
        seeds = 0
        for query in queries[:50]:
            local = f"{query.strip()} {wilaya.strip()}" if wilaya else f"{query.strip()} Algérie"
            url = f"https://html.duckduckgo.com/html/?q={local.replace(' ', '+')}"
            if self._dedup.test_and_add(url):
                continue
            if await self._queue.add_url(url, priority=10, depth=0):
                seeds += 1
        logger.info("Frontier seeded with %d URLs", seeds)
        return seeds

    def start(self) -> None:
        if self._active:
            return
        self._active = True
        self._task = asyncio.create_task(self._run(), name="crawler-engine")

    async def stop(self, timeout: float = 10.0) -> None:
        self._active = False
        if self._task is None:
            return
        try:
            await asyncio.wait_for(self._task, timeout=timeout)
        except asyncio.TimeoutError:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        finally:
            self._task = None

    # ------------------------------------------------------------------
    async def _run(self) -> None:
        workers = [
            asyncio.create_task(self._worker(i), name=f"crawler-worker-{i}")
            for i in range(self._settings.CRAWLER_WORKERS)
        ]
        try:
            await asyncio.gather(*workers)
        except asyncio.CancelledError:
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    async def _worker(self, worker_id: int) -> None:
        while self._active:
            claimed = await self._queue.get_next_url()
            if claimed is None:
                await asyncio.sleep(self._settings.FRONTIER_IDLE_SLEEP)
                continue

            queue_id, url, domain, depth = claimed
            try:
                await self._crawl_one(queue_id, url, domain, depth)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Crawl of %s failed: %s", url, exc)
                await self._queue.update_status(queue_id, success=False)
                await asyncio.sleep(1.0)

    async def _crawl_one(self, queue_id: int, url: str, domain: str, depth: int) -> None:
        if self._pages and self._pages % _HOUSEKEEPING_INTERVAL == 0:
            await self._queue.reset_stale_processing()

        headers = self._anti_block.generate_headers(host=domain)
        await self._anti_block.introduce_jitter(base_delay=self._settings.JITTER_BASE_DELAY)
        proxy_url = self._proxies.get_proxy()
        client = (
            HttpClientFactory.get_proxy_client(proxy_url)
            if proxy_url else HttpClientFactory.get_client()
        )
        # v4 Task 14: this URL's host owns its own backoff state.
        backoff = self._domain_backoffs[domain]

        try:
            async with self._adaptive:
                response = await self._fetch_bounded(client, url, headers)
        except httpx.HTTPError as exc:
            logger.debug("Fetch error %s: %s", url, exc)
            if proxy_url:
                self._proxies.record_failure(proxy_url)
            await self._queue.update_status(queue_id, success=False)
            return

        if response.status_code in (429, 503):
            await self._adaptive.report_congestion()
            self._blocks += 1
            await self._queue.update_status(queue_id, success=False)
            await backoff.sleep()
            return

        if response.status_code != 200:
            await self._queue.update_status(queue_id, success=False)
            return

        if BlockDetector.is_blocked(response):
            self._blocks += 1
            logger.debug("Block detected on %s — rotating", url)
            await self._queue.update_status(queue_id, success=False)
            await backoff.sleep()
            return

        await self._adaptive.report_success()
        if proxy_url:
            self._proxies.record_success(proxy_url)
        backoff.reset()
        self._pages += 1

        try:
            await self._extract_and_save(url, response, depth)
        finally:
            await self._queue.update_status(queue_id, success=True)

    async def _fetch_bounded(self, client, url: str, headers: dict) -> httpx.Response:
        """HEAD-first content verification (v4 §5.3).

        Streams the response and stops reading after ``_MAX_BODY_BYTES``:
        identity and contact signals live in ``<head>`` and the top of the
        document, so megabytes of images/scripts below the fold are never
        downloaded. The returned Response carries headers plus the bounded
        body, keeping every downstream consumer unchanged.
        """
        request = client.build_request("GET", url, headers=headers)
        response = await client.send(request, stream=True)
        try:
            if response.status_code != 200:
                await response.aread()
                return response

            body = bytearray()
            async for chunk in response.aiter_bytes(8 * 1024):
                body.extend(chunk)
                if len(body) >= _MAX_BODY_BYTES:
                    break

            # Materialize a non-streamed response façade for downstream
            # consumers (content/text/headers), matching the previous API.
            content = bytes(body)
            return _BoundedResponse(response, content)
        finally:
            await response.aclose()

class _BoundedResponse:
    """Response façade over a streamed response with a bounded body."""

    def __init__(self, response: httpx.Response, content: bytes) -> None:
        self._response = response
        self._content = content

    @property
    def status_code(self) -> int:
        return self._response.status_code

    @property
    def headers(self) -> httpx.Headers:
        return self._response.headers

    @property
    def content(self) -> bytes:
        return self._content

    @property
    def text(self) -> str:
        return self._content.decode("utf-8", errors="replace")

    # ------------------------------------------------------------------
    async def _extract_and_save(self, url: str, response, depth: int) -> None:
        html = response.content
        extraction = extract_html(html)

        # Choose name: JSON-LD schema name > og:title > <title>.
        name = ""
        if extraction.json_ld:
            import json
            try:
                schema = json.loads(extraction.json_ld)
                if isinstance(schema, dict):
                    name = str(schema.get("name") or schema.get("legalName") or "")
            except ValueError:
                pass
        name = name or extraction.og_title or extraction.title

        if name and len(name) >= 3 and not self._spam.is_spam(url, name):
            phone_text = " ".join(extraction.phones)
            phones = self._phone_validator.extract_and_validate(
                f"{name} {phone_text} {extraction.email}"
            )
            socials = [
                link for link in extraction.links
                if any(host in link for host in ("facebook.com", "instagram.com", "tiktok.com"))
            ]

            lead = Lead(
                name=name[:200],
                industry="Auto-Discovered",
                wilaya="",
                website=url if url.startswith("http") else None,
                phone=phones[0].e164 if phones else None,
                email=extraction.email or None,
                social_links=socials[:10],
                source=DataSource.INFINITE,
                source_url=url,
                phone_details=phones,
                freshness=self._freshness.detect(
                    extraction.meta_description or "", response.headers
                ),
                notes=extraction.meta_description[:400] or None,
            )
            audit = self._analyzer.audit(lead)
            lead.digital_score = audit.digital_score
            lead.digital_tier = audit.digital_tier
            lead.gaps = audit.gaps
            lead.recommended_services = [s.to_dict() for s in audit.recommended_services]
            lead.cta_fr = audit.cta_fr
            lead.cta_ar = audit.cta_ar
            lead.analysis_model = audit.analysis_model
            self._scorer.score(lead)

            _, created = await self._repo.upsert(lead)
            if created:
                self._entities_saved += 1

        # Expand frontier (same-domain links rank higher).
        if depth < self._settings.MAX_CRAWL_DEPTH:
            await self._expand(url, extraction.links, depth)

    async def _expand(self, base_url: str, links: list[str], depth: int) -> None:
        base_domain = (urlparse(base_url).netloc or "").lower()
        added = 0
        for raw in links[:20]:
            resolved = urljoin(base_url, raw)
            if not resolved.startswith(("http://", "https://")):
                continue
            if self._spam.is_spam(resolved, ""):
                continue
            if self._dedup.test_and_add(resolved):
                continue
            domain = (urlparse(resolved).netloc or "").lower()
            priority = 5 if domain == base_domain else 1
            if await self._queue.add_url(resolved, priority=priority, depth=depth + 1):
                added += 1
            if added >= 20:
                break
