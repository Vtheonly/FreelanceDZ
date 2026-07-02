"""Scraper plugins — platform-specific scrapers loaded dynamically.

Each plugin lives in its own module and implements ``IScraperPlugin``.
The aggregator can load plugins at runtime based on configuration, so
adding support for a new platform (e.g. TikTok) requires no changes to
the aggregator code.

Plugins are intentionally separate from the core scrapers because they
often need heavier dependencies (Playwright for JS-rendered pages) that
should not be required for the base engine to run.
"""

from infrastructure.scrapers.plugins.base_plugin import BaseScraperPlugin
from infrastructure.scrapers.plugins.facebook_plugin import FacebookPlugin
from infrastructure.scrapers.plugins.instagram_plugin import InstagramPlugin
from infrastructure.scrapers.plugins.tiktok_plugin import TikTokPlugin

__all__ = [
    "BaseScraperPlugin",
    "FacebookPlugin",
    "InstagramPlugin",
    "TikTokPlugin",
]
