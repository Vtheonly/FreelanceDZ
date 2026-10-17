"""Lead routes — CRM operations, search, autocomplete, analysis.

v3 fixes over v2:
    - Static paths (/leads/search, /leads/tags, /leads/bulk-*, ...) are
      registered BEFORE /leads/{lead_id}; v2's ordering made /leads/search
      match {lead_id} first and 422 on every dashboard search.
    - /search/autocomplete now exists (the dashboard called it in v2 and
      got a 404).
    - score-all uses list_unscored (v2 re-scored only the top-N leads that
      already had scores, leaving new leads at zero forever).
    - analyze-pending uses list_unanalyzed (v2 re-analyzed the newest N
      records every run regardless of state).
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from api.dependencies import get_lead_repo
from domain.enums import LeadStatus
from domain.models import Lead
from domain.value_objects import PhoneDetails
from infrastructure.storage.lead_repo import LeadRepository
from utils.phone_validator import SmartPhoneValidator

router = APIRouter(prefix="/api/v2", tags=["leads"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class LeadEditRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    industry: str = Field(default="", max_length=100)
    wilaya: str = Field(default="", max_length=100)
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    notes: Optional[str] = None


class StatusUpdate(BaseModel):
    status: LeadStatus


class ContactUpdate(BaseModel):
    is_contact: bool


class TagsUpdate(BaseModel):
    tags: list[str]


class BulkContactRequest(BaseModel):
    lead_ids: list[int] = Field(min_length=1)
    is_contact: bool


class BulkStatusRequest(BaseModel):
    lead_ids: list[int] = Field(min_length=1)
    status: LeadStatus


class ManualLeadCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    industry: str = Field(default="", max_length=100)
    wilaya: str = Field(default="", max_length=100)
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _lead_summary(l: Lead) -> dict:
    return {
        "id": l.id,
        "name": l.name,
        "industry": l.industry,
        "wilaya": l.wilaya,
        "website": l.website,
        "phone": l.phone,
        "has_social": bool(l.social_links),
        "rating": l.rating,
        "review_count": l.review_count,
        "source": l.source.value,
        "priority_score": l.priority_score,
        "status": l.status.value,
        "tags": l.tags,
        "is_contact": l.is_contact,
        "freshness_class": l.freshness.calculated_age_class.value,
        "digital_score": l.digital_score,
        "cluster_id": l.cluster_id,
        "discovered_at": l.discovered_at.isoformat(),
    }


def _lead_detail(l: Lead) -> dict:
    data = _lead_summary(l)
    data.update({
        "address": l.address,
        "email": l.email,
        "social_links": l.social_links,
        "latitude": l.latitude,
        "longitude": l.longitude,
        "source_url": l.source_url,
        "phone_details": [p.model_dump(mode="json") for p in l.phone_details],
        "freshness": l.freshness.model_dump(mode="json"),
        "score_breakdown": l.score_breakdown,
        "digital_tier": l.digital_tier,
        "gaps": l.gaps,
        "recommended_services": l.recommended_services,
        "cta_fr": l.cta_fr,
        "cta_ar": l.cta_ar,
        "analysis_model": l.analysis_model,
        "notes": l.notes,
        "updated_at": l.updated_at.isoformat(),
    })
    return data


# ---------------------------------------------------------------------------
# STATIC ROUTS FIRST (order matters: /leads/search must precede /leads/{id})
# ---------------------------------------------------------------------------

@router.get("/leads/search")
async def search_leads(
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(20, ge=1, le=100),
    repo: LeadRepository = Depends(get_lead_repo),
):
    hits = await repo.search(q, limit=limit)
    return {"count": len(hits), "leads": [_lead_summary(l) for l in hits]}


@router.get("/search/autocomplete")
async def autocomplete(
    q: str = Query(min_length=1, max_length=100),
    repo: LeadRepository = Depends(get_lead_repo),
):
    vocab = await repo.search_vocabulary()
    term = q.lower()
    return {"suggestions": [w for w in vocab if w.startswith(term)][:10]}


@router.get("/leads/tags")
async def list_tags(repo: LeadRepository = Depends(get_lead_repo)):
    return {"tags": await repo.all_tags()}


@router.post("/leads/manual")
async def create_manual_lead(
    payload: ManualLeadCreate, repo: LeadRepository = Depends(get_lead_repo)
):
    phones = SmartPhoneValidator().extract_and_validate(payload.phone or "")
    lead = Lead(
        name=payload.name,
        industry=payload.industry,
        wilaya=payload.wilaya,
        address=payload.address,
        website=payload.website,
        phone=phones[0].e164 if phones else payload.phone,
        email=payload.email,
        tags=payload.tags,
        notes=payload.notes,
        phone_details=phones,
        source=__import__("domain.enums", fromlist=["DataSource"]).DataSource.MANUAL,
    )
    lead_id, _ = await repo.upsert(lead)
    return {"ok": True, "lead_id": lead_id}


@router.post("/leads/analyze-pending")
async def analyze_pending(
    limit: int = Query(50, ge=1, le=500),
    repo: LeadRepository = Depends(get_lead_repo),
):
    from engine.analyzer import BusinessAnalyzer
    from engine.scorer import LeadScorer

    analyzer = BusinessAnalyzer()
    scorer = LeadScorer()
    pending = await repo.list_unanalyzed(limit=limit)
    for lead in pending:
        audit = analyzer.audit(lead)
        lead.digital_score = audit.digital_score
        lead.digital_tier = audit.digital_tier
        lead.gaps = audit.gaps
        lead.recommended_services = [s.to_dict() for s in audit.recommended_services]
        lead.cta_fr = audit.cta_fr
        lead.cta_ar = audit.cta_ar
        lead.analysis_model = audit.analysis_model
        scorer.score(lead)
        await repo.upsert(lead)
    return {"analyzed": len(pending)}


@router.post("/leads/score-all")
async def score_all(
    limit: int = Query(500, ge=1, le=5000),
    repo: LeadRepository = Depends(get_lead_repo),
):
    from engine.scorer import LeadScorer

    scorer = LeadScorer()
    unscored = await repo.list_unscored(limit=limit)
    for lead in unscored:
        scorer.score(lead)
        await repo.upsert(lead)
    return {"scored": len(unscored)}


@router.post("/leads/bulk-contact")
async def bulk_contact(
    payload: BulkContactRequest, repo: LeadRepository = Depends(get_lead_repo)
):
    updated = await repo.set_bulk_contact(payload.lead_ids, payload.is_contact)
    return {"ok": True, "updated": updated}


@router.post("/leads/bulk-status")
async def bulk_status(
    payload: BulkStatusRequest, repo: LeadRepository = Depends(get_lead_repo)
):
    updated = await repo.set_bulk_status(payload.lead_ids, payload.status)
    return {"ok": True, "updated": updated}


# ---------------------------------------------------------------------------
# Parameterized routes
# ---------------------------------------------------------------------------

@router.get("/leads")
async def list_leads(
    wilaya: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    is_contact: Optional[bool] = Query(None),
    tag: Optional[str] = Query(None),
    age_class: Optional[str] = Query(None),
    min_score: float = Query(0.0, ge=0.0, le=100.0),
    sort_by: str = Query("priority_score"),
    sort_order: str = Query("desc"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    repo: LeadRepository = Depends(get_lead_repo),
):
    leads = await repo.list_leads(
        wilaya=wilaya, industry=industry, status=status, is_contact=is_contact,
        tag=tag, age_class=age_class, min_score=min_score,
        sort_by=sort_by, sort_order=sort_order, limit=limit, offset=offset,
    )
    return {"count": len(leads), "leads": [_lead_summary(l) for l in leads]}


@router.get("/leads/{lead_id}")
async def get_lead(lead_id: int, repo: LeadRepository = Depends(get_lead_repo)):
    lead = await repo.get(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return _lead_detail(lead)


@router.post("/leads/{lead_id}/analyze")
async def analyze_lead(lead_id: int, repo: LeadRepository = Depends(get_lead_repo)):
    from engine.analyzer import BusinessAnalyzer
    from engine.scorer import LeadScorer

    lead = await repo.get(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    analyzer = BusinessAnalyzer()
    audit = analyzer.audit(lead)
    lead.digital_score = audit.digital_score
    lead.digital_tier = audit.digital_tier
    lead.gaps = audit.gaps
    lead.recommended_services = [s.to_dict() for s in audit.recommended_services]
    lead.cta_fr = audit.cta_fr
    lead.cta_ar = audit.cta_ar
    lead.analysis_model = audit.analysis_model
    LeadScorer().score(lead)
    await repo.upsert(lead)
    return {"ok": True, "digital_score": lead.digital_score, "priority_score": lead.priority_score}


@router.post("/leads/{lead_id}/edit")
async def edit_lead(
    lead_id: int, payload: LeadEditRequest, repo: LeadRepository = Depends(get_lead_repo)
):
    lead = await repo.get(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    await repo.update_fields(
        lead_id,
        name=payload.name, industry=payload.industry, wilaya=payload.wilaya,
        phone=payload.phone, email=payload.email, website=payload.website,
        address=payload.address, tags=payload.tags, notes=payload.notes,
    )
    return {"ok": True}


@router.post("/leads/{lead_id}/contact")
async def set_contact(
    lead_id: int, payload: ContactUpdate, repo: LeadRepository = Depends(get_lead_repo)
):
    await repo.set_contact(lead_id, payload.is_contact)
    return {"ok": True, "is_contact": payload.is_contact}


@router.post("/leads/{lead_id}/status")
async def set_status(
    lead_id: int, payload: StatusUpdate, repo: LeadRepository = Depends(get_lead_repo)
):
    await repo.set_status(lead_id, payload.status)
    return {"ok": True, "status": payload.status.value}


@router.post("/leads/{lead_id}/tags")
async def set_tags(
    lead_id: int, payload: TagsUpdate, repo: LeadRepository = Depends(get_lead_repo)
):
    await repo.set_tags(lead_id, payload.tags)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.post("/leads/{lead_id}/attachments")
async def upload_attachment(
    lead_id: int,
    request: Request,
    file: UploadFile,
    repo: LeadRepository = Depends(get_lead_repo),
):
    lead = await repo.get(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    from config.settings import get_settings
    attachments_dir = get_settings().resolved_attachments_dir

    filename = file.filename or "upload.bin"
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    safe_name = f"{lead_id}_{uuid.uuid4().hex[:12]}.{suffix}"
    dest = attachments_dir / safe_name

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MiB)")
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    import asyncio
    await asyncio.to_thread(dest.write_bytes, content)
    # The DB stores the on-disk (safe, unique) name; the original name is
    # returned to the caller for display.
    attachment_id = await repo.add_attachment(
        lead_id, safe_name, file.content_type or "application/octet-stream", len(content)
    )
    return {"ok": True, "attachment_id": attachment_id,
            "filename": filename, "stored_as": safe_name}


@router.get("/leads/{lead_id}/attachments")
async def list_attachments(lead_id: int, repo: LeadRepository = Depends(get_lead_repo)):
    return {"attachments": await repo.list_attachments(lead_id)}


@router.get("/attachments/{attachment_id}")
async def download_attachment(
    attachment_id: int, repo: LeadRepository = Depends(get_lead_repo)
):
    from fastapi.responses import FileResponse

    record = await repo.get_attachment(attachment_id)
    if not record:
        raise HTTPException(status_code=404, detail="Attachment not found")

    from config.settings import get_settings
    path = get_settings().resolved_attachments_dir / record["filename"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="Attachment file missing on disk")
    return FileResponse(path, media_type=record["mime_type"], filename=record["filename"])


@router.delete("/attachments/{attachment_id}")
async def delete_attachment(
    attachment_id: int, repo: LeadRepository = Depends(get_lead_repo)
):
    record = await repo.get_attachment(attachment_id)
    if not record:
        raise HTTPException(status_code=404, detail="Attachment not found")
    await repo.delete_attachment(attachment_id)
    from config.settings import get_settings
    path = get_settings().resolved_attachments_dir / record["filename"]
    import asyncio
    await asyncio.to_thread(_silent_unlink, path)
    return {"ok": True}


def _silent_unlink(path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
