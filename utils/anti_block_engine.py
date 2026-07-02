"""Anti-blocking engine — header rotation, jitter, and fingerprint diversity.

Modern WAFs (Cloudflare, Akamai, F5) fingerprint clients by:

  * TLS handshake parameters (handled by ``httpx[http2]``).
  * Header order and presence (handled here).
  * Request cadence (handled by ``introduce_jitter``).

This module produces realistic, browser-like header sets and introduces
randomised delays so the engine blends in with organic traffic. It is
deliberately stateless — every call returns a fresh, randomised result.
"""

from __future__ import annotations

import asyncio
import random
from typing import Optional

from core.constants import DEFAULT_USER_AGENTS, HTTP_ACCEPT_LANGUAGE, MOBILE_USER_AGENTS


class CrawlerAntiBlockEngine:
    """Generate realistic headers and natural delays.

    The class is fully static — there is no instance state. Call
    ``generate_headers()`` per request and ``introduce_jitter()`` between
    requests to the same domain.
    """

    DEFAULT_DESKTOP_ACCEPT = (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    )
    DEFAULT_MOBILE_ACCEPT = (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/webp,*/*;q=0.8"
    )

    @classmethod
    def generate_headers(
        cls,
        host: Optional[str] = None,
        *,
        mobile: bool = False,
        referer: Optional[str] = None,
        extra: Optional[dict[str, str]] = None,
    ) -> dict[str, str]:
        """Return a realistic header set for a single request.

        Parameters
        ----------
        host:
            Value for the ``Host`` header. Pass ``None`` to omit it
            (``httpx`` fills it automatically from the URL).
        mobile:
            When True, pick a mobile User-Agent and adjust the Accept
            header.
        referer:
            Optional ``Referer`` header — set this to a search engine
            URL to look like organic traffic.
        extra:
            Additional headers to merge in. These override generated
            values when keys collide.
        """
        user_agent = random.choice(MOBILE_USER_AGENTS if mobile else DEFAULT_USER_AGENTS)
        accept = cls.DEFAULT_MOBILE_ACCEPT if mobile else cls.DEFAULT_DESKTOP_ACCEPT

        headers: dict[str, str] = {
            "User-Agent": user_agent,
            "Accept": accept,
            "Accept-Language": HTTP_ACCEPT_LANGUAGE,
            # Let the HTTP client manage Accept-Encoding automatically
            # based on installed packages to avoid decompression errors.
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none" if referer is None else "same-origin",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }
        if host:
            headers["Host"] = host
        if referer:
            headers["Referer"] = referer

        # Chrome-specific client hints (omitted for Firefox UAs).
        if "Chrome" in user_agent and not mobile:
            headers["sec-ch-ua"] = (
                '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"'
            )
            headers["sec-ch-ua-mobile"] = "?0"
            platform = '"Windows"' if "Windows" in user_agent else (
                '"macOS"' if "Macintosh" in user_agent else '"Linux"'
            )
            headers["sec-ch-ua-platform"] = platform
        elif "Chrome" in user_agent and mobile:
            headers["sec-ch-ua"] = (
                '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"'
            )
            headers["sec-ch-ua-mobile"] = "?1"
            headers["sec-ch-ua-platform"] = '"Android"' if "Android" in user_agent else '"iOS"'

        if extra:
            headers.update(extra)
        return headers

    @staticmethod
    async def introduce_jitter(base_delay: float = 1.5) -> float:
        """Sleep for a randomised duration around ``base_delay`` seconds.

        The actual delay is in ``[max(0.2, base_delay * 0.5), base_delay * 2.5]``.
        Returns the actual delay so callers can log it.
        """
        if base_delay <= 0:
            return 0.0
        # Uniform between half and 2.5x the base, clamped to >=0.2s.
        delay = max(0.2, base_delay * random.uniform(0.5, 2.5))
        await asyncio.sleep(delay)
        return delay

    @staticmethod
    def pick_user_agent(mobile: bool = False) -> str:
        """Return a single random User-Agent string."""
        return random.choice(MOBILE_USER_AGENTS if mobile else DEFAULT_USER_AGENTS)