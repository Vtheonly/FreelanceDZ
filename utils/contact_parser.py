"""Centralised contact-channel extraction utilities.

Previously the email regex was duplicated across ``duckduckgo.py`` and
``content_extractor.py``. This module is the single source of truth for
email and social-link extraction so patterns can be updated in one place.

The email regex is intentionally strict: it rejects leading/trailing
dots, consecutive dots, and TLDs shorter than 2 characters. This filters
out common false positives like file paths (``foo.bar``) and CSS class
names (``contact.us``) that the original permissive regex captured.
"""

from __future__ import annotations

import re
from typing import Iterable


# --- Email ---------------------------------------------------------------

#: Strict email regex.
#:
#: Breakdown:
#:   * Local part: ``[a-zA-Z0-9._%+-]+`` — alphanumerics plus a small set
#:     of allowed punctuation. Must not start or end with a dot.
#:   * ``@`` separator.
#:   * Domain: ``[a-zA-Z0-9.-]+`` — alphanumerics, hyphens, dots.
#:   * TLD: ``[a-zA-Z]{2,}`` — at least 2 alphabetic characters.
_EMAIL_RE = re.compile(
    r"(?:^|(?<=\s))([a-zA-Z0-9](?:[a-zA-Z0-9._%+-]*[a-zA-Z0-9])?@"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?\."
    r"[a-zA-Z]{2,})"
)

#: Common disposable / fake email domains that pollute lead data. Emails
#: from these domains are dropped silently.
_BLOCKED_EMAIL_DOMAINS: frozenset[str] = frozenset({
    "example.com", "example.org", "example.net",
    "test.com", "test.org", "fake.com", "fake.org",
    "domain.com", "domain.tld", "yourdomain.com",
    "sentry.io", "wixpress.com",  # platform defaults
    "email.com", "mail.com",  # too generic to be real
})


def extract_emails(text: str) -> list[str]:
    """Return a de-duplicated list of valid-looking emails found in ``text``.

    The result is lowercased and ordered by first occurrence. Emails from
    disposable/fake domains are filtered out.
    """
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in _EMAIL_RE.finditer(text):
        email = match.group(1).lower().strip(".")
        domain = email.rsplit("@", 1)[-1] if "@" in email else ""
        if domain in _BLOCKED_EMAIL_DOMAINS:
            continue
        if email not in seen:
            seen.add(email)
            out.append(email)
    return out


def extract_first_email(text: str) -> str | None:
    """Return the first valid email in ``text``, or ``None``."""
    emails = extract_emails(text)
    return emails[0] if emails else None


# --- Social links --------------------------------------------------------

#: Social-media hosts we treat as profile links. Each entry maps the host
#: fragment to the platform name for downstream tagging.
_SOCIAL_HOSTS: tuple[tuple[str, str], ...] = (
    ("facebook.com", "facebook"),
    ("instagram.com", "instagram"),
    ("linkedin.com", "linkedin"),
    ("twitter.com", "twitter"),
    ("x.com", "twitter"),
    ("tiktok.com", "tiktok"),
    ("youtube.com", "youtube"),
    ("pinterest.com", "pinterest"),
)

#: URL substrings that indicate a share button, not a profile.
_SOCIAL_SKIP_PATTERNS: tuple[str, ...] = (
    "/sharer", "/share?", "/share/", "sharer.php",
    "/intent/", "/plugins/", "/widgets/",
)


def extract_social_links(href_list: Iterable[str]) -> list[str]:
    """Filter an iterable of ``href`` values and return social profile URLs.

    Drops share-button URLs and de-duplicates while preserving order.
    """
    seen: set[str] = set()
    out: list[str] = []
    for href in href_list:
        if not href:
            continue
        lower = href.lower()
        if any(skip in lower for skip in _SOCIAL_SKIP_PATTERNS):
            continue
        if not any(host in lower for host, _ in _SOCIAL_HOSTS):
            continue
        if href not in seen:
            seen.add(href)
            out.append(href)
    return out


def classify_social_platform(url: str) -> str | None:
    """Return the platform name (e.g. ``"facebook"``) for a social URL."""
    if not url:
        return None
    lower = url.lower()
    for host, platform in _SOCIAL_HOSTS:
        if host in lower:
            return platform
    return None
