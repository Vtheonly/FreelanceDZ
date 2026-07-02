"""Dependency-injection wiring for the FastAPI app.

Centralises the construction of every service and repository so the
route handlers stay thin. FastAPI's ``Depends()`` mechanism pulls from
these functions; the actual instances are cached on the app state so
they are shared across requests.

The wiring uses the ``ApplicationLifecycle`` for the HTTP client, so
the pool is properly closed on shutdown.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Request

from config.settings import AppSettings, get_settings
from core.interfaces import (
    IDiscoveryAggregator,
    ILLMClient,
    ILeadRepository,
    IRawRecordRepository,
    IResolvedEntityRepository,
)
from infrastructure.entity_resolution.graph_resolver import GraphEntityResolver
from infrastructure.http.client_factory import HttpClientFactory
from infrastructure.llm.factory import build_llm_client
from infrastructure.scrapers.aggregator import ScraperAggregator
from infrastructure.scrapers.duckduckgo import AsyncDuckDuckGoScraper
from infrastructure.scrapers.overpass import AsyncOverpassScraper
from infrastructure.storage.database import DatabaseManager
from infrastructure.storage.repositories.crawl_queue_repo import CrawlQueueRepository
from infrastructure.storage.repositories.lead_repo import LeadRepository
from infrastructure.storage.repositories.raw_record_repo import RawRecordRepository
from infrastructure.storage.repositories.resolved_entity_repo import ResolvedEntityRepository
from services.analysis_service import AnalysisService
from services.discovery_service import DiscoveryService
from services.export_service import ExportService
from services.infinite_crawler import AutonomousInfiniteCrawler
from services.resolution_service import ResolutionService
from services.scoring_service import ScoringService


_logger = logging.getLogger("api.dependencies")


# ---------------------------------------------------------------------------
#  Singletons (lazily created on first request and cached on app.state)
# ---------------------------------------------------------------------------

def _get_or_create(request: Request, key: str, factory):
    """Get a cached singleton from ``app.state`` or create it via ``factory``."""
    if not hasattr(request.app.state, key):
        setattr(request.app.state, key, factory())
    return getattr(request.app.state, key)


def get_settings_dep() -> AppSettings:
    return get_settings()


def get_database(request: Request) -> DatabaseManager:
    return _get_or_create(request, "database", lambda: DatabaseManager())


def get_raw_repo(request: Request) -> RawRecordRepository:
    return _get_or_create(
        request,
        "raw_repo",
        lambda: RawRecordRepository(get_database(request)),
    )


def get_resolved_repo(request: Request) -> ResolvedEntityRepository:
    return _get_or_create(
        request,
        "resolved_repo",
        lambda: ResolvedEntityRepository(get_database(request)),
    )


def get_lead_repo(request: Request) -> LeadRepository:
    return _get_or_create(
        request,
        "lead_repo",
        lambda: LeadRepository(get_database(request)),
    )


def get_crawl_queue_repo(request: Request) -> CrawlQueueRepository:
    return _get_or_create(
        request,
        "crawl_queue_repo",
        lambda: CrawlQueueRepository(get_database(request)),
    )


def get_llm_client(request: Request) -> Optional[ILLMClient]:
    return _get_or_create(request, "llm_client", lambda: build_llm_client())


def get_aggregator(request: Request) -> ScraperAggregator:
    def _factory():
        settings = get_settings()
        client = HttpClientFactory.get_client(settings)
        scrapers = []
        if settings.ENABLE_DDG_SCRAPER:
            scrapers.append(AsyncDuckDuckGoScraper(client))
        if settings.ENABLE_OVERPASS_SCRAPER:
            scrapers.append(AsyncOverpassScraper(client))
        return ScraperAggregator(client=client, scrapers=scrapers, llm=get_llm_client(request))
    return _get_or_create(request, "aggregator", _factory)


def get_discovery_service(request: Request) -> DiscoveryService:
    return _get_or_create(
        request,
        "discovery_service",
        lambda: DiscoveryService(get_aggregator(request), get_raw_repo(request)),
    )


def get_analysis_service(request: Request) -> AnalysisService:
    return _get_or_create(
        request,
        "analysis_service",
        lambda: AnalysisService(get_llm_client(request), get_raw_repo(request), get_lead_repo(request)),
    )


def get_scoring_service(request: Request) -> ScoringService:
    return _get_or_create(
        request,
        "scoring_service",
        lambda: ScoringService(get_lead_repo(request)),
    )


def get_resolution_service(request: Request) -> ResolutionService:
    return _get_or_create(
        request,
        "resolution_service",
        lambda: ResolutionService(
            get_raw_repo(request),
            get_resolved_repo(request),
            GraphEntityResolver(),
        ),
    )


def get_export_service(request: Request) -> ExportService:
    return _get_or_create(
        request,
        "export_service",
        lambda: ExportService(get_lead_repo(request), get_resolved_repo(request)),
    )


def get_infinite_crawler(request: Request) -> AutonomousInfiniteCrawler:
    def _factory():
        from infrastructure.http.client_factory import HttpClientFactory
        from infrastructure.scrapers.frontier import CrawlFrontier
        settings = get_settings()
        client = HttpClientFactory.get_client(settings)
        frontier = CrawlFrontier(get_crawl_queue_repo(request))
        return AutonomousInfiniteCrawler(
            client=client,
            raw_repo=get_raw_repo(request),
            frontier=frontier,
            settings=settings,
        )
    return _get_or_create(request, "infinite_crawler", _factory)
