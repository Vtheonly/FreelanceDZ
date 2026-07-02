"""Exponential backoff strategy with jitter.

Used by the infinite crawler when a block is detected: sleep for an
exponentially growing delay, capped at ``max_delay``, with up to 25%
random jitter to avoid thundering-herd retries.

The class is stateful (it tracks the current attempt count) but cheap
to construct — one instance per crawl loop is fine.
"""

from __future__ import annotations

import asyncio
import logging
import random


_logger = logging.getLogger("resilience.backoff")


class ExponentialBackoff:
    """Async exponential backoff with jitter."""

    def __init__(
        self,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        multiplier: float = 2.0,
        jitter: float = 0.25,
    ) -> None:
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._multiplier = multiplier
        self._jitter = jitter
        self._attempt = 0

    def reset(self) -> None:
        """Reset the attempt counter after a successful request."""
        self._attempt = 0

    async def sleep(self) -> float:
        """Sleep for the next backoff delay and return the actual duration."""
        delay = self.next_delay()
        _logger.debug("Backoff: sleeping %.2fs (attempt %d)", delay, self._attempt)
        await asyncio.sleep(delay)
        return delay

    def next_delay(self) -> float:
        """Compute (but do not sleep) the next backoff delay."""
        raw = self._base_delay * (self._multiplier ** self._attempt)
        capped = min(raw, self._max_delay)
        jittered = capped * (1.0 + random.uniform(-self._jitter, self._jitter))
        self._attempt += 1
        return max(0.1, jittered)

    @property
    def attempt(self) -> int:
        return self._attempt
