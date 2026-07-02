"""Repository for the ``crawl_queue`` and ``domain_politeness`` tables."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

from core.interfaces import ICrawlQueueRepository
from domain.enums import CrawlStatus
from domain.models import CrawlTask
from infrastructure.storage.database import DatabaseManager


_logger = logging.getLogger("storage.crawl_queue_repo")


class CrawlQueueRepository(ICrawlQueueRepository):
    """Persistent priority queue with per-domain politeness."""

    def __init__(self, db: DatabaseManager, politeness_delay: Optional[int] = None) -> None:
        self._db = db
        # Import here to avoid a circular import at module load time.
        from config.settings import get_settings
        self._politeness_delay = (
            politeness_delay
            if politeness_delay is not None
            else get_settings().FRONTIER_POLITENESS_DELAY
        )

    async def add_url(self, url: str, priority: int = 1, depth: int = 0) -> bool:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if not domain:
            return False
        now = _now_iso()

        def _execute():
            with self._db.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO crawl_queue (url, domain, priority, depth, status, created_at)
                    VALUES (?, ?, ?, ?, 'pending', ?)
                    ON CONFLICT(url) DO NOTHING
                    """,
                    (url, domain, priority, depth, now),
                )
                return conn.total_changes > 0
        try:
            return await asyncio.to_thread(_execute)
        except Exception as exc:
            _logger.error("Failed to enqueue URL %s: %s", url, exc)
            return False

    async def get_next_url(self) -> Optional[tuple[int, str, int]]:
        """Atomically pick the next eligible URL and mark it ``processing``.

        Honours the per-domain politeness delay: a domain that was visited
        within the last ``politeness_delay`` seconds is skipped.
        """
        threshold = (
            datetime.now(timezone.utc) - timedelta(seconds=self._politeness_delay)
        ).isoformat()

        def _execute():
            with self._db.connection() as conn:
                row = conn.execute(
                    """
                    SELECT q.id, q.url, q.depth, q.domain
                    FROM crawl_queue q
                    LEFT JOIN domain_politeness dp ON dp.domain = q.domain
                    WHERE q.status = 'pending'
                      AND q.fail_count < ?
                      AND (dp.last_visited_at IS NULL OR dp.last_visited_at <= ?)
                    ORDER BY q.priority DESC, q.created_at ASC
                    LIMIT 1
                    """,
                    (self._max_failures(), threshold),
                ).fetchone()
                if row is None:
                    return None
                now = _now_iso()
                conn.execute(
                    "UPDATE crawl_queue SET status = 'processing', last_attempted = ? WHERE id = ?",
                    (now, row["id"]),
                )
                conn.execute(
                    """
                    INSERT INTO domain_politeness (domain, last_visited_at)
                    VALUES (?, ?)
                    ON CONFLICT(domain) DO UPDATE SET last_visited_at = excluded.last_visited_at
                    """,
                    (row["domain"], now),
                )
                return row["id"], row["url"], row["depth"]
        return await asyncio.to_thread(_execute)

    async def update_status(self, queue_id: int, success: bool) -> None:
        status = CrawlStatus.COMPLETED if success else CrawlStatus.PENDING
        max_failures = self._max_failures()

        def _execute():
            with self._db.connection() as conn:
                if success:
                    conn.execute(
                        "UPDATE crawl_queue SET status = 'completed', fail_count = 0 WHERE id = ?",
                        (queue_id,),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE crawl_queue
                        SET status = CASE WHEN fail_count >= ? THEN 'failed' ELSE 'pending' END,
                            fail_count = fail_count + 1
                        WHERE id = ?
                        """,
                        (max_failures - 1, queue_id),
                    )
        await asyncio.to_thread(_execute)

    async def count_by_status(self, status: CrawlStatus) -> int:
        def _execute():
            with self._db.connection() as conn:
                return conn.execute(
                    "SELECT COUNT(*) FROM crawl_queue WHERE status = ?",
                    (status.value,),
                ).fetchone()[0]
        return await asyncio.to_thread(_execute)

    async def reset_stale_processing(self, older_than_seconds: int = 600) -> int:
        """Move ``processing`` rows back to ``pending`` if they stalled.

        Returns the number of rows reset. Called periodically by the
        infinite crawler to recover from crashes mid-fetch.
        """
        threshold = (
            datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
        ).isoformat()

        def _execute():
            with self._db.connection() as conn:
                result = conn.execute(
                    """
                    UPDATE crawl_queue
                    SET status = 'pending'
                    WHERE status = 'processing' AND last_attempted <= ?
                    """,
                    (threshold,),
                )
                return result.rowcount
        reset = await asyncio.to_thread(_execute)
        if reset:
            _logger.info("Reset %d stalled crawl_queue rows back to pending", reset)
        return reset

    async def list_pending(self, limit: int = 100) -> list[CrawlTask]:
        def _execute():
            with self._db.connection() as conn:
                return conn.execute(
                    "SELECT * FROM crawl_queue WHERE status = 'pending' ORDER BY priority DESC, created_at ASC LIMIT ?",
                    (limit,),
                ).fetchall()
        rows = await asyncio.to_thread(_execute)
        return [self._row_to_task(r) for r in rows]

    def _row_to_task(self, row) -> CrawlTask:
        last_attempted = None
        if row["last_attempted"]:
            try:
                last_attempted = datetime.fromisoformat(row["last_attempted"])
            except (ValueError, TypeError):
                pass
        created_at = datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(timezone.utc)
        return CrawlTask(
            id=row["id"],
            url=row["url"],
            domain=row["domain"],
            priority=row["priority"],
            depth=row["depth"],
            status=CrawlStatus(row["status"]),
            last_attempted=last_attempted,
            fail_count=row["fail_count"],
            created_at=created_at,
        )

    def _max_failures(self) -> int:
        from config.settings import get_settings
        return get_settings().FRONTIER_MAX_FAILURES
