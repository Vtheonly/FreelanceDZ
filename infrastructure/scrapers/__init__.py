"""Scrapers infrastructure — async, paginated, plugin-based."""

from infrastructure.scrapers.base import BaseAsyncScraper
from infrastructure.scrapers.aggregator import ScraperAggregator
from infrastructure.scrapers.duckduckgo import AsyncDuckDuckGoScraper
from infrastructure.scrapers.overpass import AsyncOverpassScraper
from infrastructure.scrapers.content_extractor import AdvancedContentExtractor
from infrastructure.scrapers.frontier import CrawlFrontier
from infrastructure.scrapers.social_scraper import SocialScraper

__all__ = [
    "BaseAsyncScraper",
    "ScraperAggregator",
    "AsyncDuckDuckGoScraper",
    "AsyncOverpassScraper",
    "AdvancedContentExtractor",
    "CrawlFrontier",
    "SocialScraper",
]
