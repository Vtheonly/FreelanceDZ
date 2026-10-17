"""Resilience: proxy orchestration, exponential backoff, block detection.

Consolidated from v2's infrastructure/resilience/ package into one module.
Fixes applied:
    - ProxyOrchestrator now implements the random tiebreak its comment
      promised (v2 always hammered `active[0]`).
    - ProxyNode lives here (domain-level value object was never used
      outside this module).
Backoff and BlockDetector are carried over unchanged — the audit found
them sound.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from config.settings import get_settings
from core.constants import BLOCK_STATUS_CODES, MIN_VALID_BODY_SIZE

logger = logging.getLogger("infrastructure.resilience")


# ---------------------------------------------------------------------------
# Backoff
# ---------------------------------------------------------------------------

class ExponentialBackoff:
    """Async exponential backoff with jitter (base 1s, x2, cap 60s, ±25%)."""

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
        self._attempt = 0

    async def sleep(self) -> float:
        delay = self.next_delay()
        logger.debug("Backoff: sleeping %.2fs (attempt %d)", delay, self._attempt)
        await asyncio.sleep(delay)
        return delay

    def next_delay(self) -> float:
        raw = self._base_delay * (self._multiplier ** self._attempt)
        capped = min(raw, self._max_delay)
        jittered = capped * (1.0 + random.uniform(-self._jitter, self._jitter))
        self._attempt += 1
        return max(0.1, jittered)

    @property
    def attempt(self) -> int:
        return self._attempt


# ---------------------------------------------------------------------------
# Block detection
# ---------------------------------------------------------------------------

_BLOCK_SIGNATURES: tuple[re.Pattern[str], ...] = (
    re.compile(r"captcha", re.IGNORECASE),
    re.compile(r"robot\s*check", re.IGNORECASE),
    re.compile(r"security\s*check", re.IGNORECASE),
    re.compile(r"cloudflare", re.IGNORECASE),
    re.compile(r"cf-browser-verification", re.IGNORECASE),
    re.compile(r"ip\s*blocked", re.IGNORECASE),
    re.compile(r"access\s*denied", re.IGNORECASE),
    re.compile(r"rate\s*limit\s*exceeded", re.IGNORECASE),
    re.compile(r"request\s*blocked", re.IGNORECASE),
    re.compile(r"please\s*verify\s*you\s*are\s*a\s*human", re.IGNORECASE),
    re.compile(r"_dd_s\b", re.IGNORECASE),
    re.compile(r"datadome", re.IGNORECASE),
)


class BlockDetector:
    """Stateless block/CAPTCHA/WAF detector."""

    @classmethod
    def is_blocked(cls, response: Any) -> bool:
        return cls.detect_signature(response) is not None

    @classmethod
    def detect_signature(cls, response: Any) -> Optional[str]:
        status = getattr(response, "status_code", None)
        if status in BLOCK_STATUS_CODES:
            return f"http:{status}"

        content = getattr(response, "content", b"")
        if content and len(content) < MIN_VALID_BODY_SIZE:
            return "body:too_small"

        headers = getattr(response, "headers", {}) or {}
        content_type = str(headers.get("content-type", "")).lower()
        if content_type and "text/html" not in content_type and "application/json" not in content_type:
            return f"content-type:{content_type.split(';')[0]}"

        text = getattr(response, "text", "") or ""
        for pattern in _BLOCK_SIGNATURES:
            match = pattern.search(text)
            if match:
                return f"signature:{match.group(0).lower()}"
        return None


# ---------------------------------------------------------------------------
# Proxy orchestration
# ---------------------------------------------------------------------------

@dataclass
class ProxyNode:
    url: str
    health_score: float = 100.0
    consecutive_fails: int = 0
    total_requests: int = 0
    state: str = "healthy"        # healthy | degraded | unhealthy | recovering
    last_used: float = field(default_factory=time.monotonic)


class ProxyOrchestrator:
    """Health-tracked proxy pool with rotation and recovery bursts."""

    def __init__(self, proxies: Optional[list[str]] = None, min_health: Optional[float] = None) -> None:
        settings = get_settings()
        self._proxies: list[ProxyNode] = [
            ProxyNode(url=url)
            for url in (proxies if proxies is not None else settings.proxy_list_parsed)
        ]
        self._min_health = min_health if min_health is not None else settings.PROXY_MIN_HEALTH
        self._lock = threading.Lock()
        if self._proxies:
            logger.info(
                "Proxy orchestrator initialised with %d proxies (min_health=%.0f)",
                len(self._proxies), self._min_health,
            )
        else:
            logger.info("No proxies configured — direct connections only.")

    @property
    def has_proxies(self) -> bool:
        return bool(self._proxies)

    def get_proxy(self) -> Optional[str]:
        """Healthiest active proxy URL, or None. Ties are broken randomly
        so equal-health proxies share load (v2 always picked index 0)."""
        if not self._proxies:
            return None
        with self._lock:
            active = [p for p in self._proxies if p.health_score >= self._min_health]
            if not active:
                logger.warning(
                    "All %d proxies below min_health=%.0f — resetting for recovery.",
                    len(self._proxies), self._min_health,
                )
                for p in self._proxies:
                    p.health_score = 100.0
                    p.state = "recovering"
                active = list(self._proxies)

            best_score = max(p.health_score for p in active)
            finalists = [p for p in active if p.health_score >= best_score - 1e-9]
            chosen = random.choice(finalists)
            chosen.last_used = time.monotonic()
            return chosen.url

    def record_success(self, proxy_url: str) -> None:
        with self._lock:
            node = next((p for p in self._proxies if p.url == proxy_url), None)
            if node is None:
                return
            node.total_requests += 1
            node.consecutive_fails = 0
            node.health_score = min(100.0, node.health_score + 5.0)
            if node.health_score >= 80:
                node.state = "healthy"
            elif node.health_score >= 30:
                node.state = "degraded"

    def record_failure(self, proxy_url: str) -> None:
        with self._lock:
            node = next((p for p in self._proxies if p.url == proxy_url), None)
            if node is None:
                return
            node.total_requests += 1
            node.consecutive_fails += 1
            node.health_score = max(
                0.0, node.health_score - 15.0 * node.consecutive_fails
            )
            if node.health_score < 30:
                node.state = "unhealthy"
            elif node.health_score < 80:
                node.state = "degraded"

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "url": p.url,
                    "health_score": round(p.health_score, 1),
                    "state": p.state,
                    "consecutive_fails": p.consecutive_fails,
                    "total_requests": p.total_requests,
                }
                for p in self._proxies
            ]
