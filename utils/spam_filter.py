"""Directory & spam filter.

Decides whether a URL/title pair represents a real business page or a
directory aggregator (Cybo, YellowPages, Ouedkniss, …). The filter is
applied *before* any expensive parsing so we don't waste CPU building
``BusinessRaw`` objects for index pages.

The blacklist is split into:
  * ``EXACT_DOMAINS`` — matched against the bare registrable domain.
  * ``PATH_PATTERNS`` — matched against the full URL path (catches
    ``/pages/`` on social platforms, ``/company/`` on LinkedIn, etc.).
  * ``TITLE_INDICATORS`` — substring matches on the page title.

Adding a new entry is a one-line change — no code refactor needed.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from utils.url_utils import domain_of


_logger = logging.getLogger("utils.spam_filter")


# Domains that are pure directories / aggregators / social platforms.
# We never want to treat these as standalone businesses.
EXACT_DOMAINS: frozenset[str] = frozenset({
    "cybo.com",
    "yellowpages.com",
    "pagesjaunes.fr",
    "lespagesjaunes-algerie.com",
    "ouedkniss.com",
    "ouedkniss.fr",
    "tripadvisor.com",
    "tripadvisor.fr",
    "yelp.com",
    "reddit.com",
    "youtube.com",
    "findhealthclinics.com",
    "rentechdigital.com",
    "sante-dz.com",
    "sante-dz.org",
    "med.tn",
    "expat.com",
    "petitfute.com",
    "africabizinfo.com",
    "annuaire-algerie.com",
    "elmouchir.caci.dz",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "pinterest.com",
    "vk.com",
})


# Path-level patterns that signal a directory listing rather than a real
# business page. Matched as substrings of the URL path.
PATH_PATTERNS: frozenset[str] = frozenset({
    "/pages/",
    "/company/",
    "/search/",
    "/directory/",
    "/annuaire/",
    "/liste-",
    "/results",
    "/classement",
})


# Title-level indicators (lowercased substring match).
TITLE_INDICATORS: tuple[str, ...] = (
    "résultats",
    "results",
    "liste des",
    "list of",
    "page 1",
    "page 2",
    "les meilleurs",
    "the best",
    "annuaire",
    "directory",
    "classement",
    "top 10",
    "top 20",
    "yellow pages",
    "pages jaunes",
)


class SourcingSpamFilter:
    """Stateless filter — all methods are classmethods for easy calling."""

    def __init__(
        self,
        extra_domains: frozenset[str] | None = None,
        extra_title_indicators: tuple[str, ...] | None = None,
    ) -> None:
        self._domains: frozenset[str] = EXACT_DOMAINS | (extra_domains or frozenset())
        self._title_indicators: tuple[str, ...] = (
            TITLE_INDICATORS + (extra_title_indicators or ())
        )

    def is_spam(self, url: str, title: str) -> bool:
        """Return True if the URL/title looks like a directory or aggregator.

        A *True* result means "skip this record". A *False* result means
        "probably a real business page — keep processing".
        """
        if not url:
            # No URL at all is suspicious — treat as spam.
            return True

        try:
            parsed = urlparse(url.lower())
        except (ValueError, TypeError):
            return True

        domain = parsed.netloc
        if domain.startswith("www."):
            domain = domain[4:]

        # 1. Exact-domain match.
        if domain in self._domains:
            return True

        # 2. Parent-domain match (e.g. ``fr.cybo.com`` → ``cybo.com``).
        for blacklisted in self._domains:
            if domain.endswith("." + blacklisted):
                return True

        # 3. Path-level patterns.
        path = parsed.path
        for pattern in PATH_PATTERNS:
            if pattern in path:
                return True

        # 4. Title-level indicators.
        if title:
            title_lower = title.lower()
            for indicator in self._title_indicators:
                if indicator in title_lower:
                    return True

        return False

    def is_directory_listing(self, url: str) -> bool:
        """Convenience method: spam-check by URL alone (no title)."""
        return self.is_spam(url, "")
