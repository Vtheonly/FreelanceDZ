"""Autonomous infinite crawler.

A self-improving, resumable crawler that runs continuously until
manually stopped. It:

1. Bootstraps the frontier with expanded query seeds.
2. Pulls the next URL from the persistent queue.
3. Fetches it (with anti-blocking, proxy rotation, jitter).
4. Detects blocks and backs off / rotates proxies accordingly.
5. Expands the frontier by extracting outbound links (depth-limited).
6. Extracts business entities via the content extractor.
7. Persists every discovered entity to ``raw_records``.
8. Periodically re-queues stalled ``processing`` rows (crash recovery).

The crawler is fully async and designed to run as a background task
inside the FastAPI process. It can be started/stopped via the API or
the CLI.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from config.settings import AppSettings, get_settings
from core.interfaces import IRawRecordRepository
from domain.enums import DataSource
from domain.models import BusinessRaw
from domain.value_objects import FreshnessMetadata
from infrastructure.resilience.backoff import ExponentialBackoff
from infrastructure.resilience.block_detector import BlockDetector
from infrastructure.resilience.proxy_orchestrator import ProxyOrchestrator
from infrastructure.scrapers.content_extractor import AdvancedContentExtractor
from infrastructure.scrapers.frontier import CrawlFrontier
from utils.anti_block_engine import CrawlerAntiBlockEngine
from utils.freshness_detector import FreshnessDetector
from utils.phone_validator import SmartPhoneValidator
from utils.query_expander import AlgerianQueryExpander
from utils.spam_filter import SourcingSpamFilter


_logger = logging.getLogger("services.infinite_crawler")


class AutonomousInfiniteCrawler:
    """Continuous, self-recovering crawler.

    Parameters
    ----------
    client:
        The shared ``httpx.AsyncClient``.
    raw_repo:
        Where to persist discovered businesses.
    frontier:
        Persistent crawl queue. When ``None``, a default one backed by
        the shared ``DatabaseManager`` is created.
    proxy_orchestrator:
        Optional stateful proxy pool. When ``None``, direct connections
        are used.
    query_expander:
        Optional query expander for seed generation.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        raw_repo: IRawRecordRepository,
        frontier: Optional[CrawlFrontier] = None,
        proxy_orchestrator: Optional[ProxyOrchestrator] = None,
        query_expander: Optional[AlgerianQueryExpander] = None,
        settings: Optional[AppSettings] = None,
    ) -> None:
        self._client = client
        self._raw_repo = raw_repo
        self._frontier = frontier or CrawlFrontier()
        self._proxies = proxy_orchestrator or ProxyOrchestrator()
        self._expander = query_expander or AlgerianQueryExpander()
        self._settings = settings or get_settings()
        self._anti_block = CrawlerAntiBlockEngine()
        self._content_extractor = AdvancedContentExtractor()
        self._phone_validator = SmartPhoneValidator()
        self._freshness = FreshnessDetector()
        self._spam_filter = SourcingSpamFilter()
        self._backoff = ExponentialBackoff()
        self._active = False
        self._task: Optional[asyncio.Task] = None
        self._stats = {"pages_crawled": 0, "entities_saved": 0, "blocks_detected": 0}

    # ------------------------------------------------------------------
    #  Lifecycle
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    async def bootstrap(self, queries: list[str], wilaya: Optional[str] = None) -> int:
        """Expand seed queries and enqueue the resulting search URLs.

        Returns the number of URLs enqueued.
        """
        enqueued = 0
        for q in queries:
            variants = await self._expander.expand(q)
            for term in variants:
                # Use the DDG HTML endpoint as the seed — the crawler
                # will follow outbound links from there.
                url = f"https://html.duckduckgo.com/html/?q={term.replace(' ', '+')}+Algérie"
                if await self._frontier.enqueue_seed(url):
                    enqueued += 1
        _logger.info("Bootstrap complete: enqueued %d seed URLs", enqueued)
        return enqueued

    def start(self) -> None:
        """Start the crawl loop as a background task."""
        if self._active:
            _logger.warning("Crawler already active — ignoring start().")
            return
        self._active = True
        self._task = asyncio.create_task(self._run(), name="infinite-crawler")
        _logger.info("Infinite crawler started.")

    async def stop(self) -> None:
        """Signal the crawl loop to stop and wait for it to finish."""
        self._active = False
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=10.0)
            except asyncio.TimeoutError:
                self._task.cancel()
                _logger.warning("Crawler did not stop gracefully — task cancelled.")
        self._task = None
        _logger.info("Infinite crawler stopped.")

    # ------------------------------------------------------------------
    #  Main loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        """The main crawl loop — runs until ``stop()`` is called."""
        _logger.info("Crawl loop entering main cycle.")
        while self._active:
            try:
                # Periodic housekeeping: re-queue stalled tasks.
                if self._stats["pages_crawled"] % 50 == 0:
                    await self._frontier.reset_stale()

                task = await self._frontier.next_task()
                if task is None:
                    idle = self._settings.FRONTIER_IDLE_SLEEP
                    _logger.debug("Frontier empty — sleeping %ds", idle)
                    await asyncio.sleep(idle)
                    continue

                await self._crawl_one(task)
            except asyncio.CancelledError:
                _logger.info("Crawl loop cancelled.")
                raise
            except Exception as exc:
                _logger.exception("Unexpected error in crawl loop: %s", exc)
                await asyncio.sleep(5.0)

    async def _crawl_one(self, task) -> None:
        """Fetch and process a single URL from the frontier."""
        from urllib.parse import urlparse
        host = urlparse(task.url).netloc
        headers = self._anti_block.generate_headers(host=host)
        await self._anti_block.introduce_jitter(base_delay=self._settings.JITTER_BASE_DELAY)

        proxy_url = self._proxies.get_proxy()
        proxy_kwargs: dict = {}
        if proxy_url:
            proxy_kwargs["proxy"] = proxy_url  # httpx uses kwarg "proxy"

        try:
            response = await self._client.get(
                task.url,
                headers=headers,
                timeout=self._settings.SCRAPER_TIMEOUT_SECONDS,
                **proxy_kwargs,
            )
        except httpx.HTTPError as exc:
            _logger.debug("Fetch failed for %s: %s", task.url, exc)
            if proxy_url:
                self._proxies.report_outcome(proxy_url, success=False)
            await self._frontier.fail(task.id)
            return

        # Block detection.
        if BlockDetector.is_blocked(response):
            self._stats["blocks_detected"] += 1
            _logger.warning("Block detected on %s — backing off.", task.url)
            if proxy_url:
                self._proxies.report_outcome(proxy_url, success=False)
            await self._frontier.fail(task.id)
            await self._backoff.sleep()
            return

        # Success.
        self._backoff.reset()
        if proxy_url:
            self._proxies.report_outcome(proxy_url, success=True)
        self._stats["pages_crawled"] += 1

        # Expand the frontier with outbound links.
        await self._frontier.expand(response.text, task.url, task.depth)

        # Extract and persist business entities.
        saved = await self._extract_and_save(response.text, task.url)
        if saved:
            self._stats["entities_saved"] += saved

        await self._frontier.complete(task.id)

    async def _extract_and_save(self, html: str, url: str) -> int:
        """Extract business entities from a page and persist them."""
        profile = self._content_extractor.extract_deep_profile(html, url)
        name = profile.get("name", "").strip()
        if not name or len(name) < 3:
            return 0
        if self._spam_filter.is_spam(url, name):
            return 0

        raw_text = f"{name} {profile.get('address', '')} {' '.join(profile.get('phones', []))}"
        phone_meta = self._phone_validator.extract_and_validate(raw_text)
        freshness = self._freshness.detect(html)

        biz = BusinessRaw(
            name=name[:200],
            industry="Auto-Discovered",
            wilaya="Unknown",
            address=profile.get("address"),
            website=url,
            phone=phone_meta[0].e164 if phone_meta else None,
            email=profile.get("email"),
            social_media_handles=profile.get("socials", []),
            source=DataSource.INFINITE,
            source_url=url,
            phone_metadata=phone_meta,
            freshness=freshness,
        )
        row_id = await self._raw_repo.save(biz)
        if row_id is not None:
            _logger.info("Infinite crawler saved entity: %s (id=%d)", biz.name, row_id)
            return 1
        return 0
