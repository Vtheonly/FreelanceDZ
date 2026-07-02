"""Stateful proxy orchestrator with health tracking.

Tracks each proxy's success rate, latency, and consecutive failures.
Proxies below ``min_health`` are temporarily rotated out; if every
proxy falls below the threshold, all scores are reset (a "recovery
burst") so we don't get stuck with no proxies at all.

The orchestrator is *not* async — it is a pure data structure consulted
by the async scraper loop. This keeps the critical section cheap and
predictable.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from config.settings import get_settings
from domain.models import ProxyNode
from domain.enums import ProxyHealthState


_logger = logging.getLogger("resilience.proxy_orchestrator")


class ProxyOrchestrator:
    """Manage a pool of proxies with health scoring and rotation."""

    def __init__(
        self,
        proxies: Optional[list[str]] = None,
        min_health: Optional[float] = None,
    ) -> None:
        settings = get_settings()
        self._proxies: list[ProxyNode] = [
            ProxyNode(url=url) for url in (proxies if proxies is not None else settings.proxy_list_parsed)
        ]
        self._min_health = min_health if min_health is not None else settings.PROXY_MIN_HEALTH
        self._lock = threading.Lock()
        if self._proxies:
            _logger.info(
                "Proxy orchestrator initialised with %d proxies (min_health=%.0f)",
                len(self._proxies), self._min_health,
            )
        else:
            _logger.info("No proxies configured — direct connections only.")

    @property
    def has_proxies(self) -> bool:
        return bool(self._proxies)

    def get_proxy(self) -> Optional[str]:
        """Return the healthiest active proxy URL, or ``None`` if none configured."""
        if not self._proxies:
            return None
        with self._lock:
            active = [p for p in self._proxies if p.health_score >= self._min_health]
            if not active:
                _logger.warning(
                    "All %d proxies below min_health=%.0f — resetting scores for recovery.",
                    len(self._proxies), self._min_health,
                )
                for p in self._proxies:
                    p.health_score = 100.0
                    p.state = ProxyHealthState.RECOVERING
                active = self._proxies
            # Pick the healthiest, with a small random tiebreak.
            active.sort(key=lambda p: p.health_score, reverse=True)
            chosen = active[0]
            chosen.last_used_at = _now()
            return chosen.url

    def report_outcome(self, proxy_url: str, success: bool) -> None:
        """Update a proxy's health based on a request outcome."""
        with self._lock:
            node = next((p for p in self._proxies if p.url == proxy_url), None)
            if node is None:
                return
            if success:
                node.success_count += 1
                node.consecutive_fails = 0
                node.health_score = min(100.0, node.health_score + 5.0)
                if node.health_score >= 80:
                    node.state = ProxyHealthState.HEALTHY
                elif node.health_score >= 30:
                    node.state = ProxyHealthState.DEGRADED
            else:
                node.fail_count += 1
                node.consecutive_fails += 1
                # Exponential penalty: each consecutive failure hurts more.
                penalty = 15.0 * node.consecutive_fails
                node.health_score = max(0.0, node.health_score - penalty)
                node.last_failure_at = _now()
                if node.health_score < 30:
                    node.state = ProxyHealthState.UNHEALTHY
                else:
                    node.state = ProxyHealthState.DEGRADED
                _logger.debug(
                    "Proxy %s degraded: health=%.0f, consecutive_fails=%d",
                    proxy_url, node.health_score, node.consecutive_fails,
                )

    def snapshot(self) -> list[dict]:
        """Return a JSON-serialisable snapshot of the pool (for the UI)."""
        with self._lock:
            return [p.model_dump(mode="json") for p in self._proxies]


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)
