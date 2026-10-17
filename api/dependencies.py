"""FastAPI dependency graph (singleton cache on app.state)."""

from __future__ import annotations

from fastapi import Request

from config.settings import AppSettings, get_settings
from engine.analyzer import BusinessAnalyzer
from engine.resolver import GraphEntityResolver
from engine.scorer import LeadScorer
from infrastructure.http import HttpClientFactory
from infrastructure.resilience import ProxyOrchestrator
from infrastructure.scrapers.duckduckgo import DuckDuckGoScraper
from infrastructure.scrapers.overpass import OverpassScraper
from infrastructure.storage import (
    ClusterRepository,
    CrawlQueueRepository,
    DatabaseManager,
    LeadRepository,
)
from services.crawler_service import CrawlerEngine
from services.discovery_service import DiscoveryService, ResolutionService, ScraperAggregator
from services.export_service import ExportService


def _get_or_create(request: Request, key: str, factory):
    if not hasattr(request.app.state, key):
        setattr(request.app.state, key, factory())
    return getattr(request.app.state, key)


def get_settings_dep() -> AppSettings:
    return get_settings()


def get_database(request: Request) -> DatabaseManager:
    return _get_or_create(request, "database", DatabaseManager)


def get_lead_repo(request: Request) -> LeadRepository:
    return _get_or_create(
        request, "lead_repo", lambda: LeadRepository(get_database(request))
    )


def get_cluster_repo(request: Request) -> ClusterRepository:
    return _get_or_create(
        request, "cluster_repo", lambda: ClusterRepository(get_database(request))
    )


def get_crawl_queue(request: Request) -> CrawlQueueRepository:
    return _get_or_create(
        request, "crawl_queue", lambda: CrawlQueueRepository(get_database(request))
    )


def get_http_client(request: Request):
    return _get_or_create(request, "http_client", HttpClientFactory.get_client)


def get_aggregator(request: Request) -> ScraperAggregator:
    def _build() -> ScraperAggregator:
        settings = get_settings()
        client = get_http_client(request)
        scrapers = []
        if settings.ENABLE_DDG_SCRAPER:
            scrapers.append(DuckDuckGoScraper(client))
        if settings.ENABLE_OVERPASS_SCRAPER:
            scrapers.append(OverpassScraper(client))
        return ScraperAggregator(scrapers)

    return _get_or_create(request, "aggregator", _build)


def get_discovery_service(request: Request) -> DiscoveryService:
    def _build() -> DiscoveryService:
        return DiscoveryService(
            aggregator=get_aggregator(request),
            repo=get_lead_repo(request),
            analyzer=BusinessAnalyzer(),
            scorer=LeadScorer(),
        )

    return _get_or_create(request, "discovery_service", _build)


def get_resolution_service(request: Request) -> ResolutionService:
    def _build() -> ResolutionService:
        return ResolutionService(
            repo=get_lead_repo(request),
            clusters=get_cluster_repo(request),
            resolver=GraphEntityResolver(),
        )

    return _get_or_create(request, "resolution_service", _build)


def get_export_service(request: Request) -> ExportService:
    def _build() -> ExportService:
        return ExportService(
            repo=get_lead_repo(request),
            clusters=get_cluster_repo(request),
        )

    return _get_or_create(request, "export_service", _build)


def get_crawler(request: Request) -> CrawlerEngine:
    def _build() -> CrawlerEngine:
        return CrawlerEngine(
            repo=get_lead_repo(request),
            queue=get_crawl_queue(request),
            proxy_orchestrator=ProxyOrchestrator(),
        )

    return _get_or_create(request, "crawler", _build)
