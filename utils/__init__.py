"""Utilities package — stateless helpers shared across the engine.

Every module here is pure (no I/O, no global state) so it can be unit
tested in isolation and safely imported from anywhere.
"""

from utils.text_utils import (
    normalise_name,
    normalise_phone,
    normalise_url,
    strip_html_tags,
    truncate,
)
from utils.url_utils import (
    clean_url,
    domain_of,
    is_same_domain,
    resolve_relative,
    unwrap_ddg_url,
)
from utils.contact_parser import (
    extract_emails,
    extract_first_email,
    extract_social_links,
    classify_social_platform,
)
from utils.phone_validator import SmartPhoneValidator
from utils.freshness_detector import FreshnessDetector
from utils.spam_filter import SourcingSpamFilter
from utils.query_expander import AlgerianQueryExpander, sanitise_query
from utils.anti_block_engine import CrawlerAntiBlockEngine
from utils.retry import retry_with_backoff

__all__ = [
    # text
    "normalise_name",
    "normalise_phone",
    "normalise_url",
    "strip_html_tags",
    "truncate",
    # url
    "clean_url",
    "domain_of",
    "is_same_domain",
    "resolve_relative",
    "unwrap_ddg_url",
    # contact parsing
    "extract_emails",
    "extract_first_email",
    "extract_social_links",
    "classify_social_platform",
    # services
    "SmartPhoneValidator",
    "FreshnessDetector",
    "SourcingSpamFilter",
    "AlgerianQueryExpander",
    "sanitise_query",
    "CrawlerAntiBlockEngine",
    "retry_with_backoff",
]
