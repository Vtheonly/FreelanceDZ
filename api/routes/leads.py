"""Leads routes — list, search, inspect, and mutate leads."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.dependencies import get_analysis_service, get_lead_repo, get_scoring_service
from core.interfaces import ILeadRepository
from domain.enums import FreshnessAge, LeadStatus
from services.analysis_service import AnalysisService
from services.scoring_service import ScoringService


_logger = logging.getLogger("api.routes.leads")
router = APIRouter(prefix="/api/v2", tags=["leads"])


class TagsUpdate(BaseModel):
    tags: list[str]


class StatusUpdate(BaseModel):
    status: str


@router.get("/leads")
async def list_leads(
    wilaya: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    age_class: Optional[FreshnessAge] = Query(None),
    min_score: float = Query(0.0, ge=0.0, le=100.0),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    repo: ILeadRepository = Depends(get_lead_repo),
):
    """List leads with optional filters. Supports pagination + freshness filter."""
    leads = await repo.list_leads(
        wilaya=wilaya,
        industry=industry,
        age_class=age_class,
        min_score=min_score,
        limit=limit,
        offset=offset,
    )
    return {
        "count": len(leads),
        "limit": limit,
        "offset": offset,
        "leads": [_lead_summary(l) for l in leads],
    }


@router.get("/leads/{lead_id}")
async def get_lead(
    lead_id: int,
    repo: ILeadRepository = Depends(get_lead_repo),
):
    lead = await repo.get_lead(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return _lead_detail(lead)


@router.get("/leads/search")
async def search_leads(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    repo: ILeadRepository = Depends(get_lead_repo),
):
    leads = await repo.search(term=q, limit=limit)
    return {"count": len(leads), "leads": [_lead_summary(l) for l in leads]}


@router.post("/leads/{lead_id}/tags")
async def update_tags(
    lead_id: int,
    body: TagsUpdate,
    repo: ILeadRepository = Depends(get_lead_repo),
):
    lead = await repo.get_lead(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    await repo.set_tags(lead_id, body.tags)
    return {"ok": True, "id": lead_id, "tags": body.tags}


@router.post("/leads/{lead_id}/status")
async def update_status(
    lead_id: int,
    body: StatusUpdate,
    repo: ILeadRepository = Depends(get_lead_repo),
):
    try:
        status = LeadStatus(body.status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")
    lead = await repo.get_lead(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    await repo.set_status(lead_id, status)
    return {"ok": True, "id": lead_id, "status": status.value}


@router.post("/leads/{lead_id}/analyze")
async def analyze_lead(
    lead_id: int,
    analysis_service: AnalysisService = Depends(get_analysis_service),
    scoring: ScoringService = Depends(get_scoring_service),
):
    """Run LLM analysis on a single lead, then recompute its score."""
    analysis = await analysis_service.analyze_single(lead_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    new_score = await scoring.score_single(lead_id)
    return {
        "ok": True,
        "id": lead_id,
        "analysis": analysis.model_dump(mode="json"),
        "new_score": new_score,
    }


@router.post("/leads/analyze-pending")
async def analyze_pending(
    limit: int = Query(10, ge=1, le=200),
    analysis_service: AnalysisService = Depends(get_analysis_service),
    scoring: ScoringService = Depends(get_scoring_service),
):
    """Run LLM analysis on pending leads, then rescore them."""
    analysed = await analysis_service.analyze_pending(limit=limit)
    await scoring.score_all(limit=500)
    return {"ok": True, "analysed_count": analysed}


@router.post("/leads/score-all")
async def score_all(
    scoring: ScoringService = Depends(get_scoring_service),
):
    """Recompute priority scores for every lead."""
    scored = await scoring.score_all(limit=1000)
    return {"ok": True, "scored_count": scored}


# ---------------------------------------------------------------------------
#  Serialisation helpers
# ---------------------------------------------------------------------------

def _lead_summary(lead) -> dict:
    return {
        "id": lead.id,
        "name": lead.business.name,
        "industry": lead.business.industry,
        "wilaya": lead.business.wilaya,
        "website": lead.business.website,
        "phone": lead.business.phone,
        "has_social": bool(lead.business.social_media_handles),
        "rating": lead.business.rating,
        "review_count": lead.business.review_count,
        "source": lead.business.source.value,
        "priority_score": lead.priority_score,
        "status": lead.status.value,
        "tags": getattr(lead, "tags", []),
        "freshness": lead.business.freshness.calculated_age_class.value,
        "digital_presence_score": lead.analysis.digital_presence_score if lead.analysis else None,
        "discovered_at": lead.business.discovered_at.isoformat() if lead.business.discovered_at else None,
    }


def _lead_detail(lead) -> dict:
    summary = _lead_summary(lead)
    summary.update({
        "address": lead.business.address,
        "email": lead.business.email,
        "social_media": lead.business.social_media_handles,
        "latitude": lead.business.latitude,
        "longitude": lead.business.longitude,
        "source_url": lead.business.source_url,
        "phone_metadata": [p.model_dump(mode="json") for p in lead.business.phone_metadata],
        "freshness": lead.business.freshness.model_dump(mode="json"),
        "score_breakdown": lead.score_breakdown,
        "analysis": (
            lead.analysis.model_dump(mode="json")
            if lead.analysis
            else None
        ),
    })
    return summary
