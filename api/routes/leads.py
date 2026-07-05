"""Leads routes — list, search, inspect, and mutate leads."""

from __future__ import annotations

import logging
from typing import Optional
from pathlib import Path
import shutil
import uuid
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.dependencies import get_analysis_service, get_lead_repo, get_scoring_service, get_settings_dep
from config.settings import AppSettings
from core.interfaces import ILeadRepository
from domain.enums import FreshnessAge, LeadStatus, DataSource
from domain.models import BusinessRaw
from domain.value_objects import FreshnessMetadata
from services.analysis_service import AnalysisService
from services.scoring_service import ScoringService


_logger = logging.getLogger("api.routes.leads")
router = APIRouter(prefix="/api/v2", tags=["leads"])


class TagsUpdate(BaseModel):
    tags: list[str]


class StatusUpdate(BaseModel):
    status: str


class LeadEditRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Corrected legal name override")
    tags: list[str] = Field(default_factory=list, description="Associated custom classification tags")
    address: Optional[str] = Field(None, description="Optional street address corrections")
    website: Optional[str] = Field(None, description="Optional website URL corrections")
    phone: Optional[str] = Field(None, description="Optional phone number corrections")
    email: Optional[str] = Field(None, description="Optional contact email corrections")


class ContactUpdateRequest(BaseModel):
    is_contact: bool


class BulkContactRequest(BaseModel):
    lead_ids: list[int] = Field(..., min_length=1)
    is_contact: bool


class BulkStatusRequest(BaseModel):
    lead_ids: list[int] = Field(..., min_length=1)
    status: str


class ManualLeadCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Business name")
    industry: str = Field(..., min_length=1, max_length=100, description="Category/Industry")
    wilaya: str = Field(..., min_length=1, max_length=100, description="Wilaya localization")
    address: Optional[str] = Field(None, description="Optional street address")
    website: Optional[str] = Field(None, description="Optional website URL")
    phone: Optional[str] = Field(None, description="Optional phone number")
    email: Optional[str] = Field(None, description="Optional email address")
    tags: list[str] = Field(default_factory=list, description="Initial list of classification tags")


@router.get("/leads")
async def list_leads(
    wilaya: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    age_class: Optional[FreshnessAge] = Query(None),
    min_score: float = Query(0.0, ge=0.0, le=100.0),
    is_contact: Optional[bool] = Query(None),
    tag: Optional[str] = Query(None, description="Filter leads by a specific tag"),
    sort_by: Optional[str] = Query(None, description="Field to sort by"),
    sort_order: str = Query("desc", description="Sorting direction: asc or desc"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    repo: ILeadRepository = Depends(get_lead_repo),
):
    """List leads with optional filters. Supports pagination, sorting, tags filter, + freshness filter."""
    leads = await repo.list_leads(
        wilaya=wilaya,
        industry=industry,
        age_class=age_class,
        min_score=min_score,
        is_contact=is_contact,
        tag=tag,
        sort_by=sort_by,
        sort_order=sort_order,
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
    is_contact: Optional[bool] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    repo: ILeadRepository = Depends(get_lead_repo),
):
    leads = await repo.search(term=q, is_contact=is_contact, limit=limit)
    return {"count": len(leads), "leads": [_lead_summary(l) for l in leads]}


@router.get("/tags")
async def list_tags(
    repo: ILeadRepository = Depends(get_lead_repo),
):
    """Fetch all unique custom tags created inside the system."""
    tags = await repo.get_all_tags()
    return {"tags": tags}


@router.post("/leads/manual")
async def create_manual_lead(
    body: ManualLeadCreate,
    repo: ILeadRepository = Depends(get_lead_repo),
):
    """Manually add a fresh customized B2B lead to the localized database."""
    phone_metadata = []
    if body.phone:
        from utils.phone_validator import SmartPhoneValidator
        validator = SmartPhoneValidator()
        phone_metadata = validator.extract_and_validate(body.phone)

    biz = BusinessRaw(
        name=body.name,
        industry=body.industry,
        wilaya=body.wilaya,
        address=body.address,
        website=body.website,
        phone=body.phone,
        email=body.email,
        source=DataSource.MANUAL,
        phone_metadata=phone_metadata,
        freshness=FreshnessMetadata(),
        discovered_at=datetime.now(timezone.utc)
    )

    lead_id = await repo.create_manual_lead(biz, body.tags)
    return {"ok": True, "id": lead_id}


@router.post("/leads/{lead_id}/attachments")
async def upload_attachment(
    lead_id: int,
    file: UploadFile = File(...),
    repo: ILeadRepository = Depends(get_lead_repo),
    settings: AppSettings = Depends(get_settings_dep),
):
    """Save an image or file screenshot pinned to a specific lead permanently."""
    attachments_dir = Path(settings.DATABASE_PATH).parent / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    unique_id = uuid.uuid4().hex
    ext = Path(file.filename).suffix or ".png"
    disk_filename = f"{unique_id}{ext}"
    target_path = attachments_dir / disk_filename

    try:
        with target_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as exc:
        _logger.exception("Failed to write screenshot file on disk")
        raise HTTPException(status_code=500, detail=f"File save failure: {exc}")

    attachment_id = await repo.add_attachment(
        raw_record_id=lead_id,
        filename=file.filename,
        mime_type=file.content_type or "image/png",
        file_path=str(target_path)
    )

    return {
        "ok": True,
        "attachment_id": attachment_id,
        "filename": file.filename,
        "mime_type": file.content_type or "image/png"
    }


@router.get("/leads/{lead_id}/attachments")
async def list_attachments(
    lead_id: int,
    repo: ILeadRepository = Depends(get_lead_repo),
):
    """Get all file attachment records attached to a lead."""
    attachments = await repo.get_attachments(lead_id)
    return {"attachments": attachments}


@router.delete("/attachments/{attachment_id}")
async def delete_attachment(
    attachment_id: int,
    repo: ILeadRepository = Depends(get_lead_repo),
):
    """Remove file reference and physically delete the file on server disk."""
    success = await repo.delete_attachment(attachment_id)
    if not success:
         raise HTTPException(status_code=404, detail="Attachment reference not found")
    return {"ok": True}


@router.get("/attachments/{attachment_id}")
async def retrieve_attachment(
    attachment_id: int,
    repo: ILeadRepository = Depends(get_lead_repo),
):
    """Stream raw binary content of a localized screenshot file."""
    def _fetch_attachment_path():
        with repo._db.connection() as conn:
            return conn.execute(
                "SELECT file_path, mime_type, filename FROM lead_attachments WHERE id = ?",
                (attachment_id,)
            ).fetchone()

    row = await asyncio.to_thread(_fetch_attachment_path)
    if not row:
        raise HTTPException(status_code=404, detail="Attachment reference not found")

    file_path = Path(row["file_path"])
    if not file_path.exists():
         raise HTTPException(status_code=404, detail="File lost or missing on disk server")

    return FileResponse(
        path=str(file_path),
        media_type=row["mime_type"],
        filename=row["filename"]
    )


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


@router.post("/leads/{lead_id}/edit")
async def edit_lead(
    lead_id: int,
    body: LeadEditRequest,
    repo: ILeadRepository = Depends(get_lead_repo),
):
    """Edit core text fields, tags, and inline properties. Changes are immediately saved and apply to index."""
    lead = await repo.get_lead(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    await repo.update_lead_details(
        business_id=lead_id,
        name=body.name,
        tags=body.tags,
        address=body.address,
        website=body.website,
        phone=body.phone,
        email=body.email
    )
    return {"ok": True, "id": lead_id, "name": body.name, "tags": body.tags}


@router.post("/leads/{lead_id}/contact")
async def update_contact_status(
    lead_id: int,
    body: ContactUpdateRequest,
    repo: ILeadRepository = Depends(get_lead_repo),
):
    """Toggle a lead's inclusion in the Contacts/Outreach view tab."""
    lead = await repo.get_lead(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    await repo.set_contact_status(lead_id, body.is_contact)
    return {"ok": True, "id": lead_id, "is_contact": body.is_contact}


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


@router.post("/leads/bulk-contact")
async def bulk_contact(
    body: BulkContactRequest,
    repo: ILeadRepository = Depends(get_lead_repo),
):
    """Add or remove multiple selected leads from Contacts in a single transaction."""
    await repo.bulk_set_contact_status(body.lead_ids, body.is_contact)
    return {"ok": True, "count": len(body.lead_ids)}


@router.post("/leads/bulk-status")
async def bulk_status(
    body: BulkStatusRequest,
    repo: ILeadRepository = Depends(get_lead_repo),
):
    """Update workflow status of selected leads concurrently (e.g. Bulk blocking)."""
    try:
        status = LeadStatus(body.status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")
    await repo.bulk_set_status(body.lead_ids, status)
    return {"ok": True, "count": len(body.lead_ids)}


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
        "is_contact": getattr(lead, "is_contact", False),
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