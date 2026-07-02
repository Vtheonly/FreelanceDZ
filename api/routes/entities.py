"""Entities routes — list and inspect resolved golden records."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_resolution_service, get_resolved_repo
from core.interfaces import IResolvedEntityRepository
from services.resolution_service import ResolutionService


router = APIRouter(prefix="/api/v2", tags=["entities"])


@router.get("/entities")
async def list_entities(
    wilaya: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    repo: IResolvedEntityRepository = Depends(get_resolved_repo),
):
    """List resolved golden records, sorted by confidence."""
    entities = await repo.list_all(
        wilaya=wilaya,
        industry=industry,
        min_confidence=min_confidence,
        limit=limit,
        offset=offset,
    )
    return {
        "count": len(entities),
        "limit": limit,
        "offset": offset,
        "entities": [e.model_dump(mode="json") for e in entities],
    }


@router.get("/entities/{entity_id}")
async def get_entity(
    entity_id: int,
    repo: IResolvedEntityRepository = Depends(get_resolved_repo),
):
    entity = await repo.get_by_id(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity.model_dump(mode="json")


@router.get("/entities/{entity_id}/lineage")
async def get_entity_lineage(
    entity_id: int,
    repo: IResolvedEntityRepository = Depends(get_resolved_repo),
):
    """Return every raw record that contributed to this golden entity.

    Uses the ``entity_links`` join table for relational lineage tracing.
    """
    entity = await repo.get_by_id(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    lineage = await repo.get_lineage(entity_id)
    return {
        "entity_id": entity_id,
        "entity_name": entity.name,
        "raw_record_count": len(lineage),
        "lineage": lineage,
    }


@router.post("/entities/resolve")
async def resolve_entities(
    resolution: ResolutionService = Depends(get_resolution_service),
):
    """Run the graph-based entity resolver on every raw record."""
    result = await resolution.resolve_all()
    return result.to_dict()


@router.get("/entities/stats")
async def entities_stats(
    repo: IResolvedEntityRepository = Depends(get_resolved_repo),
):
    total = await repo.count()
    return {"total_entities": total}
