"""Persistent crawl frontier for the infinite crawler.

Wraps ``CrawlQueueRepository`` with higher-level operations:

* ``enqueue_seed()`` — add a search-URL seed with high priority.
* ``next_task()`` — atomically pick the next eligible URL.
* ``complete()`` / ``fail()`` — update status with retry semantics.
* ``expand()`` — extract outbound links from a fetched page and enqueue
  them (respecting ``MAX_CRAWL_DEPTH`` and the spam filter).

The frontier is *persistent*: every URL and its status survive process
restarts. This is what makes the infinite crawler truly resumable.
"""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from config.settings import get_settings
from core.interfaces import ICrawlQueueRepository
from domain.models import CrawlTask
from infrastructure.storage.repositories.crawl_queue_repo import CrawlQueueRepository
from utils.spam_filter import SourcingSpamFilter


_logger = logging.getLogger("scrapers.frontier")


class CrawlFrontier:
    """High-level facade over ``CrawlQueueRepository``.

    Adds link-extraction and depth-tracking logic that the bare queue
    repository does not have.
    """

    def __init__(
        self,
        queue_repo: Optional[ICrawlQueueRepository] = None,
        spam_filter: Optional[SourcingSpamFilter] = None,
        max_depth: Optional[int] = None,
    ) -> None:
        # Lazy import to avoid a circular dependency at module load time.
        if queue_repo is None:
            from infrastructure.storage.database import DatabaseManager
            queue_repo = CrawlQueueRepository(DatabaseManager())
        self._queue = queue_repo
        self._spam_filter = spam_filter or SourcingSpamFilter()
        self._max_depth = max_depth or get_settings().MAX_CRAWL_DEPTH

    async def enqueue_seed(self, url: str, priority: int = 10) -> bool:
        """Add a seed URL (depth 0, high priority)."""
        return await self._queue.add_url(url, priority=priority, depth=0)

    async def next_task(self) -> Optional[CrawlTask]:
        """Atomically fetch the next URL to crawl, or ``None`` if idle."""
        result = await self._queue.get_next_url()
        if result is None:
            return None
        queue_id, url, depth = result
        # Fetch the full row to populate all CrawlTask fields.
        # The repository's get_next_url marks the row as 'processing'
        # and only returns the bare tuple, so we reconstruct a minimal
        # CrawlTask here.
        return CrawlTask(
            id=queue_id,
            url=url,
            domain=urlparse(url).netloc.lower(),
            priority=0,  # Already consumed by get_next_url.
            depth=depth,
        )

    async def complete(self, queue_id: int) -> None:
        await self._queue.update_status(queue_id, success=True)

    async def fail(self, queue_id: int) -> None:
        await self._queue.update_status(queue_id, success=False)

    async def expand(
        self,
        html: str,
        parent_url: str,
        current_depth: int,
        max_links: int = 20,
    ) -> int:
        """Extract outbound links from a page and enqueue the valid ones.

        Returns the number of links actually enqueued (duplicates and
        spam links are silently dropped).
        """
        if current_depth >= self._max_depth:
            return 0
        if not html or not parent_url:
            return 0

        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        parent_domain = urlparse(parent_url).netloc.lower()
        enqueued = 0

        for anchor in soup.find_all("a", href=True):
            if enqueued >= max_links:
                break
            href = anchor["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            absolute = urljoin(parent_url, href)
            # Strip fragments.
            absolute = absolute.split("#", 1)[0]
            if not absolute.startswith(("http://", "https://")):
                continue

            # Spam-filter — drop directories and social index pages.
            if self._spam_filter.is_spam(absolute, anchor.get_text(strip=True)):
                continue

            # Prefer same-domain links for depth-limited crawling.
            target_domain = urlparse(absolute).netloc.lower()
            priority = 5 if target_domain == parent_domain else 1
            added = await self._queue.add_url(absolute, priority=priority, depth=current_depth + 1)
            if added:
                enqueued += 1

        if enqueued:
            _logger.debug(
                "Frontier expanded: +%d links from %s (depth %d → %d)",
                enqueued, parent_url, current_depth, current_depth + 1,
            )
        return enqueued

    async def reset_stale(self, older_than_seconds: int = 600) -> int:
        """Re-queue any task stuck in ``processing`` for too long."""
        return await self._queue.reset_stale_processing(older_than_seconds)
