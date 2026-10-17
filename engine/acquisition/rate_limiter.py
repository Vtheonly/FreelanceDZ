"""Per-domain token-bucket rate limiter (non-blocking, no thread sleeps).

Restored from iteration 4: politeness without blocking the event loop.
The bucket refills at `rate` tokens/sec up to `burst`; callers await only
the deficit time for their own domain.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from urllib.parse import urlparse


class DomainTokenBucketLimiter:
    def __init__(self, rate: float = 2.0, burst: int = 4) -> None:
        self._rate = max(0.1, rate)
        self._burst = max(1, burst)
        self._tokens: dict[str, float] = defaultdict(lambda: float(self._burst))
        self._last: dict[str, float] = defaultdict(time.monotonic)
        self._lock = asyncio.Lock()

    async def acquire(self, url: str) -> None:
        domain = (urlparse(url).netloc or "").lower()
        if not domain:
            return
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last[domain]
                self._last[domain] = now
                self._tokens[domain] = min(
                    float(self._burst), self._tokens[domain] + elapsed * self._rate
                )
                if self._tokens[domain] >= 1.0:
                    self._tokens[domain] -= 1.0
                    return
                wait = (1.0 - self._tokens[domain]) / self._rate
            await asyncio.sleep(wait)

    def prune(self, max_domains: int = 4096) -> None:
        """Bound memory: drop state for the least-recently-seen domains."""
        if len(self._last) <= max_domains:
            return
        for domain in sorted(self._last, key=self._last.get)[:-max_domains // 2]:
            self._last.pop(domain, None)
            self._tokens.pop(domain, None)
