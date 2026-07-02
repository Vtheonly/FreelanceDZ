"""Analytics routes — aggregate stats for the dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import get_lead_repo, get_resolved_repo
from core.interfaces import ILeadRepository, IResolvedEntityRepository


router = APIRouter(prefix="/api/v2", tags=["analytics"])


@router.get("/stats")
async def stats(
    repo: ILeadRepository = Depends(get_lead_repo),
    resolved: IResolvedEntityRepository = Depends(get_resolved_repo),
):
    """Return aggregate statistics for the dashboard."""
    lead_stats = await repo.stats()
    entities_count = await resolved.count()
    lead_stats["total_resolved_entities"] = entities_count
    return lead_stats
