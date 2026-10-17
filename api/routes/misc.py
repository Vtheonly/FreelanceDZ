"""Discovery, entity, export, crawler, analytics, and health routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from api.dependencies import (
    get_cluster_repo,
    get_crawler,
    get_database,
    get_discovery_service,
    get_export_service,
    get_lead_repo,
    get_resolution_service,
    get_settings_dep,
)
from infrastructure.storage.cluster_repo import ClusterRepository
from infrastructure.storage.lead_repo import LeadRepository
from services.crawler_service import CrawlerEngine
from services.discovery_service import DiscoveryService, ResolutionService
from services.export_service import ExportService
from utils.query_expander import sanitise_query

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

discovery_router = APIRouter(prefix="/api/v2/discover", tags=["discovery"])


class DiscoverRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    wilaya: Optional[str] = Field(None, max_length=100)
    limit: int = Field(default=30, ge=1, le=200)
    background: bool = False

    @field_validator("query", "wilaya")
    @classmethod
    def _sanitise(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return sanitise_query(v)  # raises ValueError -> FastAPI 422


@discovery_router.post("")
async def discover(
    req: DiscoverRequest,
    background: BackgroundTasks,
    service: DiscoveryService = Depends(get_discovery_service),
):
    if req.background:
        background.add_task(service.discover, req.query, req.wilaya, req.limit)
        return {"status": "processing", "query": req.query, "wilaya": req.wilaya}
    try:
        return await service.discover(req.query, req.wilaya, req.limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"discovery failed: {exc}")


@discovery_router.get("/campaigns")
async def campaigns(
    limit: int = Query(5, ge=1, le=50),
    repo: LeadRepository = Depends(get_lead_repo),
):
    return {"campaigns": await repo.list_campaigns(limit=limit)}


# ---------------------------------------------------------------------------
# Entities (clusters) — static paths before parameterized ones
# ---------------------------------------------------------------------------

entities_router = APIRouter(prefix="/api/v2/entities", tags=["entities"])


@entities_router.get("/stats")
async def entity_stats(clusters: ClusterRepository = Depends(get_cluster_repo)):
    return {"total_clusters": await clusters.count()}


@entities_router.post("/resolve")
async def resolve_entities(service: ResolutionService = Depends(get_resolution_service)):
    return await service.resolve_all()


@entities_router.get("")
async def list_entities(
    wilaya: Optional[str] = None,
    industry: Optional[str] = None,
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    clusters: ClusterRepository = Depends(get_cluster_repo),
):
    entities = await clusters.list_clusters(
        wilaya=wilaya, industry=industry,
        min_confidence=min_confidence, limit=limit, offset=offset,
    )
    return {"count": len(entities), "entities": entities}


@entities_router.get("/{cluster_id}")
async def get_entity(
    cluster_id: int, clusters: ClusterRepository = Depends(get_cluster_repo)
):
    entity = await clusters.get_cluster(cluster_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return entity


@entities_router.get("/{cluster_id}/lineage")
async def entity_lineage(
    cluster_id: int, clusters: ClusterRepository = Depends(get_cluster_repo)
):
    return {"lineage": await clusters.get_lineage(cluster_id)}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

export_router = APIRouter(prefix="/api/v2/export", tags=["export"])


@export_router.get("/leads/csv")
async def export_csv(
    limit: int = Query(1000, ge=1, le=10000),
    service: ExportService = Depends(get_export_service),
):
    path = await service.export_leads_csv(limit=limit)
    return FileResponse(path, media_type="text/csv", filename=path.name)


@export_router.get("/leads/json")
async def export_json(
    limit: int = Query(1000, ge=1, le=10000),
    service: ExportService = Depends(get_export_service),
):
    path = await service.export_leads_json(limit=limit)
    return FileResponse(path, media_type="application/json", filename=path.name)


@export_router.get("/entities/json")
async def export_entities_json(
    limit: int = Query(1000, ge=1, le=10000),
    service: ExportService = Depends(get_export_service),
):
    path = await service.export_clusters_json(limit=limit)
    return FileResponse(path, media_type="application/json", filename=path.name)


# ---------------------------------------------------------------------------
# Crawler control
# ---------------------------------------------------------------------------

crawler_router = APIRouter(prefix="/api/v2/crawler", tags=["crawler"])


class CrawlStartRequest(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=50)
    wilaya: Optional[str] = Field(None, max_length=100)

    @field_validator("queries")
    @classmethod
    def _sanitise_queries(cls, queries: list[str]) -> list[str]:
        cleaned = []
        for q in queries:
            try:
                cleaned.append(sanitise_query(q))
            except ValueError:
                continue
        if not cleaned:
            raise ValueError("no valid queries")
        return cleaned


@crawler_router.post("/start")
async def start_crawler(
    req: CrawlStartRequest, crawler: CrawlerEngine = Depends(get_crawler)
):
    seeded = await crawler.bootstrap(req.queries, req.wilaya)
    crawler.start()
    return {"status": "running", "seeded_urls": seeded, "stats": crawler.stats}


@crawler_router.post("/stop")
async def stop_crawler(crawler: CrawlerEngine = Depends(get_crawler)):
    await crawler.stop()
    return {"status": "stopped", "stats": crawler.stats}


@crawler_router.get("/status")
async def crawler_status(crawler: CrawlerEngine = Depends(get_crawler)):
    return crawler.stats


# ---------------------------------------------------------------------------
# Analytics + health
# ---------------------------------------------------------------------------

analytics_router = APIRouter(prefix="/api/v2", tags=["analytics"])


@analytics_router.get("/stats")
async def stats(repo: LeadRepository = Depends(get_lead_repo)):
    return await repo.stats()


health_router = APIRouter(tags=["health"])


@health_router.get("/health")
async def health(
    full: bool = Query(False, description="Run the (slow) full integrity check"),
    settings=Depends(get_settings_dep),
    db=Depends(get_database),
):
    import asyncio
    # v2 ran a full PRAGMA integrity_check on every health probe, blocking
    # the event loop for seconds on large DBs. Default is a metadata-only
    # response; opt in for the real check (offloaded to a thread).
    database_ok = True
    if full:
        database_ok = await asyncio.to_thread(db.integrity_check, False)
    return {
        "status": "ok" if database_ok else "degraded",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "database": database_ok,
    }
