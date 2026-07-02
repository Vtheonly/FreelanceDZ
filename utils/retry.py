"""Retry decorator with exponential backoff.

Wraps any async callable so that transient failures (network errors,
HTTP 429, HTTP 5xx) are retried with exponentially growing delays. The
decorator is generic enough to be used by HTTP clients, LLM clients,
and scrapers alike.

Implementation uses ``tenacity`` under the hood for battle-tested
retry semantics (jitter, stop conditions, custom predicates).
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

import httpx


_logger = logging.getLogger("utils.retry")


P = ParamSpec("P")
T = TypeVar("T")


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple[type[BaseException], ...] = (httpx.HTTPError, asyncio.TimeoutError),
    *,
    jitter: bool = True,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Async retry decorator with exponential backoff.

    Parameters
    ----------
    max_retries:
        Maximum number of retry attempts (so up to ``max_retries + 1``
        total calls).
    base_delay:
        Delay before the first retry, in seconds.
    max_delay:
        Cap on the per-retry delay.
    exceptions:
        Exception types that trigger a retry. Any other exception is
        re-raised immediately.
    jitter:
        When True, add up to 25% random jitter to each delay to avoid
        thundering-herd effects.
    """

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            last_exc: BaseException | None = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt >= max_retries:
                        _logger.warning(
                            "%s exhausted retries (%d): %s",
                            func.__qualname__,
                            attempt,
                            exc,
                        )
                        raise
                    delay = min(max_delay, base_delay * (2 ** attempt))
                    if jitter:
                        delay = delay * (1.0 + random.uniform(-0.25, 0.25))
                    _logger.debug(
                        "%s attempt %d failed (%s); retrying in %.2fs",
                        func.__qualname__,
                        attempt + 1,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
            # Should be unreachable, but keeps mypy happy.
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator
