"""Proxy pool configuration.

Parses the comma-separated ``PROXY_LIST`` env var into a list of proxy
URLs. The actual proxy *state* (health, success rate) is owned by
``infrastructure.resilience.proxy_orchestrator.ProxyOrchestrator`` — this
module only handles the static configuration.
"""

from __future__ import annotations

from config.settings import settings


def parse_proxy_list(raw: str | None = None) -> list[str]:
    """Split the comma-separated proxy list and strip whitespace.

    Empty entries are silently dropped. The result is deterministic and
    order-preserving so callers can rely on the first proxy being the
    "preferred" one.
    """
    if raw is None:
        raw = settings.PROXY_LIST
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


# Eagerly-parsed pool. Re-import the module after mutating settings to
# refresh this list, or call ``parse_proxy_list()`` directly at call time.
PROXY_POOL: list[str] = parse_proxy_list()
