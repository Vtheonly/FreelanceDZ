"""Block / CAPTCHA / WAF detector.

Inspects HTTP responses and decides whether the response represents a
real business page or a block / CAPTCHA / rate-limit page. Used by the
scraper loop to skip parsing of blocked responses and trigger proxy
rotation.

Detection layers
----------------
1. **Status code** — 401/403/429/503 → blocked.
2. **Body size** — responses smaller than ``MIN_VALID_BODY_SIZE`` are
   suspicious (usually redirects or empty block pages).
3. **Content-Type** — non-HTML/non-JSON responses are not business pages.
4. **Signature scan** — regex search for known block indicators
   ("captcha", "cloudflare", "access denied", …).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from core.constants import BLOCK_STATUS_CODES, MIN_VALID_BODY_SIZE


_logger = logging.getLogger("resilience.block_detector")


# Pre-compiled block-signature patterns. The list is intentionally short
# to avoid false positives — a page containing the word "security" should
# not be flagged as a block.
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
    re.compile(r"_dd_s\b", re.IGNORECASE),  # Datadome cookie name
    re.compile(r"datadome", re.IGNORECASE),
)


class BlockDetector:
    """Stateless detector — all methods are classmethods."""

    @classmethod
    def is_blocked(cls, response: Any) -> bool:
        """Return True if the response looks like a block / CAPTCHA page."""
        signature = cls.detect_signature(response)
        return signature is not None

    @classmethod
    def detect_signature(cls, response: Any) -> str | None:
        """Return the first matched block signature, or ``None`` if clean."""
        # 1. Status code.
        status = getattr(response, "status_code", None)
        if status in BLOCK_STATUS_CODES:
            return f"http:{status}"

        # 2. Body size.
        content = getattr(response, "content", b"")
        if content and len(content) < MIN_VALID_BODY_SIZE:
            return "body:too_small"

        # 3. Content-Type.
        headers = getattr(response, "headers", {}) or {}
        content_type = str(headers.get("content-type", "")).lower()
        if content_type and "text/html" not in content_type and "application/json" not in content_type:
            # Not a page we can parse — treat as a soft block.
            return f"content-type:{content_type.split(';')[0]}"

        # 4. Body signature scan.
        text = getattr(response, "text", "") or ""
        for pattern in _BLOCK_SIGNATURES:
            match = pattern.search(text)
            if match:
                return f"signature:{match.group(0).lower()}"

        return None
