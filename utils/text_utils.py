"""Pure string-manipulation helpers.

These functions are intentionally tiny and side-effect free. Keeping them
in one place makes it easy to write targeted unit tests and to swap the
normalisation strategy without touching call sites.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse


# Pre-compiled regexes — compiled once, used many times.
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_ENTITY_MAP = {
    "&amp;": "&",
    "&quot;": '"',
    "&#x27;": "'",
    "&#39;": "'",
    "&nbsp;": " ",
    "&lt;": "<",
    "&gt;": ">",
}
_WHITESPACE_RE = re.compile(r"\s+")


def strip_html_tags(html: str) -> str:
    """Remove HTML tags and decode common entities.

    Does *not* attempt a full HTML5 parse — for that, use BeautifulSoup.
    This is the fast path for snippet cleanup where a full parse would
    be wasteful.
    """
    if not html:
        return ""
    text = _HTML_TAG_RE.sub("", html)
    for entity, char in _HTML_ENTITY_MAP.items():
        text = text.replace(entity, char)
    return _WHITESPACE_RE.sub(" ", text).strip()


def normalise_name(name: str) -> str:
    """Normalise a business name for fingerprinting.

    Strips accents, lowercases, and keeps only alphanumerics. The result
    is intentionally aggressive: two names that differ only in
    punctuation or diacritics must produce the same key.
    """
    if not name:
        return ""
    # Decompose accents then drop the combining marks.
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    return "".join(c.lower() for c in ascii_only if c.isalnum())


def normalise_phone(phone: str | None) -> str:
    """Return only the digits of a phone string (no +, spaces, or dashes)."""
    if not phone:
        return ""
    return "".join(c for c in phone if c.isdigit())


def normalise_url(url: str | None) -> str:
    """Canonicalise a URL for fingerprinting.

    Drops the scheme and ``www.`` prefix, lowercases the host, and strips
    the trailing slash. Query strings and fragments are preserved because
    they sometimes carry meaningful identifiers.
    """
    if not url:
        return ""
    parsed = urlparse(url.lower())
    host = parsed.netloc
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{host}{path}{query}"


def truncate(text: str, max_length: int = 120) -> str:
    """Truncate text to ``max_length`` characters, adding an ellipsis if cut."""
    if not text or len(text) <= max_length:
        return text or ""
    if max_length <= 3:
        return text[:max_length]
    return text[: max_length - 3] + "…"
