"""Shared, immutable constants used across the engine.

Centralising these values prevents magic strings and numbers from leaking
into business logic. Everything here is a final, hashable primitive — never
mutate at runtime.
"""

from __future__ import annotations

# ============================================================
#  HTTP & Networking
# ============================================================

#: Default User-Agent rotation pool. Real browsers are mimicked to bypass
#: naive fingerprinting. The pool is intentionally small to keep logs
#: readable; expand via configuration if a wider rotation is required.
DEFAULT_USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/17.2 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
)

#: Mobile User-Agent pool, used by the social-media scrapers to mimic
#: real mobile traffic (which is less aggressively blocked on social
#: platforms than desktop traffic).
MOBILE_USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Android 13; Mobile; rv:121.0) Gecko/121.0 Firefox/121.0",
)

#: HTTP status codes that signal a block / rate-limit / service unavailable.
BLOCK_STATUS_CODES: frozenset[int] = frozenset({401, 403, 429, 503})

#: HTTP status codes that indicate the response is permanently unusable.
PERMANENT_ERROR_STATUS_CODES: frozenset[int] = frozenset({400, 404, 410})

#: Minimum response body size (bytes) below which we suspect a block page
#: or an empty redirect. Real business pages are almost always larger.
MIN_VALID_BODY_SIZE: int = 200

# ============================================================
#  Geographic / Market
# ============================================================

#: ISO 3166-1 alpha-2 code for Algeria — used by libphonenumber and HTTP
#: ``Accept-Language`` headers.
ALGERIA_COUNTRY_CODE: str = "DZ"

#: Default region passed to ``phonenumbers.PhoneNumberMatcher`` when the
#: scraped number has no country code prefix.
DEFAULT_PHONE_REGION: str = "DZ"

#: Language priority for HTTP requests. French first (business language),
#: then English, then Arabic — matches the Algerian web reality.
HTTP_ACCEPT_LANGUAGE: str = "fr,fr-FR;q=0.9,en-US;q=0.5,en;q=0.3,ar;q=0.2"

# ============================================================
#  Crawl Frontier
# ============================================================

#: Status values used by the persistent crawl queue.
QUEUE_STATUS_PENDING: str = "pending"
QUEUE_STATUS_PROCESSING: str = "processing"
QUEUE_STATUS_COMPLETED: str = "completed"
QUEUE_STATUS_FAILED: str = "failed"

ALL_QUEUE_STATUSES: tuple[str, ...] = (
    QUEUE_STATUS_PENDING,
    QUEUE_STATUS_PROCESSING,
    QUEUE_STATUS_COMPLETED,
    QUEUE_STATUS_FAILED,
)

#: Maximum crawl depth beyond which the frontier stops following links.
#: Depth 0 = search-result page; depth 1 = first business page; etc.
DEFAULT_MAX_CRAWL_DEPTH: int = 3

# ============================================================
#  Freshness
# ============================================================

#: Sentinel value used when no freshness signal could be extracted.
FRESHNESS_UNKNOWN: str = "unknown"

# ============================================================
#  Entity Resolution
# ============================================================

#: Default weights for the composite similarity score in the graph resolver.
#: These are exposed here so callers can tune them without instantiating
#: the resolver.
DEFAULT_ENTITY_WEIGHTS: dict[str, float] = {
    "name": 0.40,
    "website": 0.25,
    "phone": 0.20,
    "email": 0.15,
}

# ============================================================
#  Application Metadata
# ============================================================

APP_NAME: str = "FreelanceDZ Engine"
APP_VERSION: str = "2.0.0"
APP_DESCRIPTION: str = (
    "Modular, async, fault-tolerant B2B lead-discovery engine "
    "for the Algerian market."
)
