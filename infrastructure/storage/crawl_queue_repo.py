"""Repository for the ``crawl_queue`` and ``domain_politeness`` tables.

v3 changes:
    - get_next_url claims under BEGIN IMMEDIATE (fixes the v2
      SELECT-then-UPDATE race between concurrent crawler workers).
    - Dead ``list_pending`` removed; interface inheritance dropped
      (core/interfaces is reduced to genuinely polymorphic contracts).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from infrastructure.storage.database import DatabaseManager

logger = logging.getLogger("storage.crawl_queue_repo")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CrawlQueueRepository:
    """Persistent priority queue with per-domain politeness."""

    def __init__(self, db: DatabaseManager, politeness_delay: Optional[float] = None) -> None:
        self._db = db
        from config.settings import get_settings  # local import avoids cycle
        self._politeness_delay = (
            politeness_delay
            if politeness_delay is not None
            else get_settings().FRONTIER_POLITENESS_DELAY
        )

    async def add_url(self, url: str, priority: int = 1, depth: int = 0) -> bool:
        from urllib.parse import urlparse
        domain = (urlparse(url).netloc or "").lower()
        if not domain:
            return False
        now = _now_iso()

        def _execute() -> bool:
            with self._db.connection() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO crawl_queue (url, domain, priority, depth, status, created_at)
                    VALUES (?, ?, ?, ?, 'pending', ?)
                    ON CONFLICT(url) DO NOTHING
                    """,
                    (url, domain, priority, depth, now),
                )
                return cur.rowcount > 0
        try:
            return await asyncio.to_thread(_execute)
        except Exception as exc:
            logger.error("Failed to enqueue URL %s: %s", url, exc)
            return False

    async def get_next_url(self) -> Optional[tuple[int, str, str, int]]:
        """Atomically claim the next eligible URL.

        Returns (queue_id, url, domain, depth) or None. Uses BEGIN IMMEDIATE
        so concurrent workers can never claim the same row.
        """
        threshold = (
            datetime.now(timezone.utc) - timedelta(seconds=self._politeness_delay)
        ).isoformat()
        max_failures = self._max_failures()

        def _execute() -> Optional[tuple[int, str, str, int]]:
            with self._db.immediate_connection() as conn:
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
                    (max_failures, threshold),
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
                return row["id"], row["url"], row["domain"], row["depth"]
        return await asyncio.to_thread(_execute)

    async def update_status(self, queue_id: int, success: bool) -> None:
        max_failures = self._max_failures()

        def _execute() -> None:
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

    async def count_by_status(self, status: str) -> int:
        def _execute() -> int:
            with self._db.connection() as conn:
                return conn.execute(
                    "SELECT COUNT(*) FROM crawl_queue WHERE status = ?", (status,)
                ).fetchone()[0]
        return await asyncio.to_thread(_execute)

    async def reset_stale_processing(self, older_than_seconds: float = 600.0) -> int:
        """Recover ``processing`` rows whose fetch stalled (crash recovery)."""
        threshold = (
            datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
        ).isoformat()

        def _execute() -> int:
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
            logger.info("Reset %d stalled crawl_queue rows back to pending", reset)
        return reset

    def _max_failures(self) -> int:
        from config.settings import get_settings
        return get_settings().FRONTIER_MAX_FAILURES
