"""AIMD adaptive concurrency controller (iteration 4, correctness fixed).

v2's version resized an asyncio.Semaphore with acquire_nowait — which cannot
clamp concurrent holders. This implementation gates on an active-counter
against a movable ceiling, so congestion backoff takes effect on the very
next acquire and never over-admits.

Additive increase on success (rate-limited), multiplicative decrease on
HTTP 429/503 congestion — the same policy TCP uses.
"""

from __future__ import annotations

import asyncio


class AdaptiveConcurrency:
    def __init__(self, minimum: int = 4, maximum: int = 32) -> None:
        self._min = max(1, min(minimum, maximum))
        self._max = max(1, maximum)
        self._ceiling = self._min
        self._active = 0
        self._successes_since_increase = 0
        self._cond = asyncio.Condition()

    @property
    def current(self) -> int:
        return self._ceiling

    @property
    def active(self) -> int:
        return self._active

    async def __aenter__(self) -> "AdaptiveConcurrency":
        async with self._cond:
            await self._cond.wait_for(lambda: self._active < self._ceiling)
            self._active += 1
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        async with self._cond:
            self._active -= 1
            self._cond.notify(1)

    async def report_success(self) -> None:
        """Additive increase: +1 after every 8 clean responses."""
        async with self._cond:
            self._successes_since_increase += 1
            if self._successes_since_increase >= 8 and self._ceiling < self._max:
                self._ceiling += 1
                self._successes_since_increase = 0
                self._cond.notify(1)

    async def report_congestion(self) -> None:
        """Multiplicative decrease: halve the ceiling (bounded at minimum)."""
        async with self._cond:
            self._ceiling = max(self._min, self._ceiling // 2)
            self._successes_since_increase = 0
