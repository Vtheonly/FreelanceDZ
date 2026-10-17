"""Directory & spam filter — the Business Quality Gate.

Decides whether a URL/title pair represents a real business page or
something that must never become a lead. The filter is applied *before*
any expensive parsing so we don't waste CPU building ``Lead`` objects for
index pages.

Three tiers of sources exist:

  * ``TRUSTED_DIRECTORIES`` — legitimate Algerian marketplaces and
    directories (Ouedkniss, CACI El Mouchir, Pages Jaunes DZ). Their
    *store/business profile* pages are prime structured sources and pass
    the gate; their *search/index/listing* pages stay blocked via
    per-directory path rules, the generic listing path patterns, and the
    directory-safe title indicators (issue #8: blocking these domains
    outright discarded commercial business profiles before their
    structured data could be extracted).
  * ``EXACT_DOMAINS`` — low-quality SEO aggregators and international
    directory giants whose pages are never individual Algerian
    businesses. Always blocked.
  * ``JUNK_DOMAINS`` — e-commerce giants, encyclopedias, media/streaming,
    and government/legal portals (v4 Task 12). Always blocked.

Additionally:

  * ``PATH_PATTERNS`` — substring matches on the URL path (catches
    ``/pages/`` on social platforms, ``/company/`` on LinkedIn, search
    and listing paths everywhere).
  * ``TITLE_INDICATORS`` / ``NON_BUSINESS_TITLE_TOKENS`` — substring
    matches on the page title (lists, rankings, laws, recruitment...).
    On trusted directories a *directory-safe* subset is applied: the
    brand-word indicators ("annuaire", "yellow pages", "pages jaunes",
    "directory") are skipped there because profile pages routinely
    brand themselves with exactly those words ("Pharmacie X - Pages
    Jaunes Algérie"), while result/ranking indicators and non-business
    tokens still apply.

Adding a new entry is a one-line change — no code refactor needed.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse


_logger = logging.getLogger("utils.spam_filter")


# Trusted local marketplaces & directories: profile pages pass, index
# pages stay blocked. Mapping: registrable domain -> per-directory path
# substrings that identify listing/search/index pages on that site.
# (Issue #8 — these are legitimate structured sources for the Algerian
# market, not SEO spam.)
TRUSTED_DIRECTORIES: dict[str, frozenset[str]] = {
    # Ouedkniss — Algeria's dominant classifieds marketplace. Store
    # pages (e.g. /store/<slug>) are structured business profiles.
    "ouedkniss.com": frozenset({
        "/search", "/categories", "/annonces", "/offre", "/demande", "/stores",
    }),
    "ouedkniss.fr": frozenset({
        "/search", "/categories", "/annonces", "/offre", "/demande", "/stores",
    }),
    # CACI El Mouchir — the Algerian chamber-of-commerce directory.
    "elmouchir.caci.dz": frozenset({
        "/recherche", "/categorie", "/categories",
    }),
    # Pages Jaunes DZ — the Algerian yellow pages.
    "lespagesjaunes-algerie.com": frozenset({
        "/recherche", "/categories", "/villes",
    }),
}

# Brand-word title indicators that are ONLY applied to non-trusted
# sources (trusted-directory profile pages routinely carry them as
# legitimate branding suffixes — see module docstring).
_BRAND_TITLE_INDICATORS: frozenset[str] = frozenset({
    "annuaire",
    "directory",
    "yellow pages",
    "pages jaunes",
})


# Low-quality SEO aggregators and international directory giants — never
# individual Algerian businesses. Social platforms are deliberately
# excluded here so individual business profiles can be scraped and
# pitched web-design services.
EXACT_DOMAINS: frozenset[str] = frozenset({
    "cybo.com",
    "yellowpages.com",
    "pagesjaunes.fr",
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


# Title-level indicators (lowercased substring match) that mark a page as
# a listing/ranking rather than an individual business. Applied in full
# to ordinary sources; the brand-word subset is skipped on trusted
# directories (see module docstring).
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
        # Directory-safe subset for trusted directories (issue #8): the
        # result/ranking indicators and every non-business token still
        # apply; only the brand words are relaxed.
        self._directory_title_indicators: tuple[str, ...] = (
            tuple(i for i in TITLE_INDICATORS if i not in _BRAND_TITLE_INDICATORS)
            + NON_BUSINESS_TITLE_TOKENS
            + (extra_title_indicators or ())
        )

    # ------------------------------------------------------------------
    # Provenance (issue #8): downstream code can distinguish a lead whose
    # URL is a verified profile on a trusted local directory from an
    # ordinary website or a blocked source.
    # ------------------------------------------------------------------
    def _trusted_directory(self, domain: str) -> str | None:
        """Return the trusted registrable domain this host belongs to."""
        if domain in TRUSTED_DIRECTORIES:
            return domain
        for trusted in TRUSTED_DIRECTORIES:
            if domain.endswith("." + trusted):
                return trusted
        return None

    def is_trusted_directory(self, url: str) -> bool:
        """True when the URL points at a trusted local directory host."""
        domain = self._host_of(url)
        return domain is not None and self._trusted_directory(domain) is not None

    @staticmethod
    def _host_of(url: str) -> str | None:
        """Normalised registrable host (``www.`` stripped) or None."""
        try:
            parsed = urlparse(url.lower())
        except (ValueError, TypeError):
            return None
        domain = parsed.netloc
        if domain.startswith("www."):
            domain = domain[4:]
        return domain or None

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
        if not domain:
            # Hostless/malformed URL ("not a url", "https:///x", "mailto:…")
            # cannot be fetched, enriched, or contacted — same verdict as an
            # empty URL. (Issue #8 hardening; the old gate let these pass.)
            return True
        if domain.startswith("www."):
            domain = domain[4:]
        path = parsed.path

        # 0. Trusted local directories (issue #8): the domain gate opens
        #    ONLY for profile-like pages — the homepage and every
        #    listing/search/index path stays blocked.
        trusted = self._trusted_directory(domain)
        if trusted is not None:
            if path in ("", "/"):
                return True  # directory landing page, not a business
            index_paths = TRUSTED_DIRECTORIES[trusted]
            for pattern in index_paths:
                if pattern in path:
                    return True
            for pattern in PATH_PATTERNS:
                if pattern in path:
                    return True
            # Directory-safe title indicators: result/ranking wording and
            # non-business tokens still block; brand words don't.
            if title:
                title_lower = title.lower()
                for indicator in self._directory_title_indicators:
                    if indicator in title_lower:
                        return True
            return False  # profile page on a trusted directory — keep

        # 1. Domain match (exact or parent, covers fr.amazon.com etc.).
        if domain in self._domains:
            return True
        for blacklisted in self._domains:
            if domain.endswith("." + blacklisted):
                return True

        # 2. Path-level patterns.
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
