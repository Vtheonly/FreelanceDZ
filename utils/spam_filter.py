"""Directory & spam filter — the Business Quality Gate.

Decides whether a URL/title pair represents a real business page or
something that must never become a lead: directory aggregators (Cybo,
YellowPages, Ouedkniss, ...), e-commerce giants and encyclopedias (Amazon,
Wikipedia), government portals and legal texts (.gov.dz, JORADP), media
and streaming content, and non-business documents (laws, guides, TV
series, recruitment notices). The filter is applied *before* any
expensive parsing so we don't waste CPU building ``Lead`` objects for
index pages.

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



_logger = logging.getLogger("utils.spam_filter")


# Domains that are pure directories or index aggregators.
# Social platforms are deliberately excluded here so individual business profiles
# can be scraped and pitched web-design services.
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
})

# v4 Task 12 — Business Quality Gate: marketplaces, encyclopedias,
# media/streaming, and government/legal portals are never individual
# businesses. Social platforms (facebook, instagram, tiktok, ...) are
# deliberately NOT junked: their individual business pages are prime
# "no website yet" prospects (Task 10's core segment) and the DDG scraper
# deep-crawls them for enrichment; their feed/search pages are already
# blocked by PATH_PATTERNS.
JUNK_DOMAINS: frozenset[str] = frozenset({
    "amazon.com", "amazon.fr", "amazon.dz", "etsy.com", "aliexpress.com",
    "ebay.com", "france.tv", "allocine.fr", "livreshebdo.fr",
    "wikipedia.org", "wikimedia.org", "youtube.com", "vimeo.com",
    "interieur.gov.dz", "mfa.gov.dz", "sante.gov.dz", "commerce.gov.dz",
    "education.gov.dz", "mf.gov.dz", "joradp.dz", "cnr.dz", "ons.dz",
    "douane.gov.dz", "elpais.com", "lemonde.fr", "bbc.com", "cnn.com",
    "dzfoot.com", "competic.com", "e-chorouk.com", "tsa-algerie.com",
})

_ALL_BLOCKED_DOMAINS: frozenset[str] = EXACT_DOMAINS | JUNK_DOMAINS


# Path-level patterns that signal a directory listing rather than a real
# business page. Matched as substrings of the URL path.
PATH_PATTERNS: frozenset[str] = frozenset({
    "/search/",
    "/directory/",
    "/annuaire/",
    "/liste-",
    "/results",
    "/classement",
    "/wiki/",
    "/watch?",
    "/channel/",
    "/product/",
    "/dp/",
    "/gp/product",
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

# v4 Task 12 — title tokens that guarantee a page is not an individual
# business (laws, guides, ministries, TV, recruitment, scholarships...).
NON_BUSINESS_TITLE_TOKENS: tuple[str, ...] = (
    "loi ",
    "guide complet",
    "ministère",
    "actualités",
    "provinces of algeria",
    "série tv",
    "téléchargements",
    "avis de recrutement",
    "avis de concours",
    "concours",
    "décret",
    "journal officiel",
    "wikipédia",
    "recrutement",
    "bourse d'étude",
    "thèse",
    "mémoire pdf",
)


class SourcingSpamFilter:
    """Stateless business quality gate."""

    def __init__(
        self,
        extra_domains: frozenset[str] | None = None,
        extra_title_indicators: tuple[str, ...] | None = None,
    ) -> None:
        self._domains: frozenset[str] = _ALL_BLOCKED_DOMAINS | (extra_domains or frozenset())
        self._title_indicators: tuple[str, ...] = (
            TITLE_INDICATORS + NON_BUSINESS_TITLE_TOKENS + (extra_title_indicators or ())
        )

    def is_spam(self, url: str, title: str) -> bool:
        """Return True if the URL/title fails the business quality gate.

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

        # 1. Domain match (exact or parent, covers fr.amazon.com etc.).
        if domain in self._domains:
            return True
        for blacklisted in self._domains:
            if domain.endswith("." + blacklisted):
                return True

        # 2. Path-level patterns.
        path = parsed.path
        for pattern in PATH_PATTERNS:
            if pattern in path:
                return True

        # 3. Title-level indicators (directories, lists, rankings) and
        #    non-business tokens (laws, guides, ministries, TV, ...).
        if title:
            title_lower = title.lower()
            for indicator in self._title_indicators:
                if indicator in title_lower:
                    return True

        return False

    def is_directory_listing(self, url: str) -> bool:
        """Convenience method: spam-check by URL alone (no title)."""
        return self.is_spam(url, "")