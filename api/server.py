"""FastAPI dashboard — browse, search, and inspect leads in the browser.

Routes:
  GET  /                    — HTML dashboard (Jinja2 template)
  GET  /api/leads           — JSON list of leads (filters: wilaya, industry, min_score, limit, offset)
  GET  /api/leads/{id}      — JSON detail for a single lead
  GET  /api/stats           — JSON aggregate stats
  GET  /api/search?q=...    — JSON full-text search
  POST /api/leads/{id}/status — Update lead status (contacted | rejected | ...)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from core.logging_setup import configure_logging
from domain.models import LeadStatus
from infrastructure.storage.sqlite_repo import SQLiteLeadRepository


# Configure logging the same way the CLI does.
configure_logging(level="INFO", log_dir=Path("data/logs"))

# Wire up FastAPI.
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(
    title="DZ Sales Intelligence",
    description="AI-powered business discovery & lead scoring platform for Algeria",
    version="1.0.0",
)


def _repo() -> SQLiteLeadRepository:
    """Build a fresh repository per request (SQLite handles concurrency)."""
    return SQLiteLeadRepository()


# ----------------------------------------------------------------------------
#  HTML pages
# ----------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    """Main dashboard page — loads data via /api/* endpoints from JS."""
    return TEMPLATES.TemplateResponse(request=request, name="dashboard.html")


# ----------------------------------------------------------------------------
#  JSON API
# ----------------------------------------------------------------------------

@app.get("/api/stats")
def stats():
    return _repo().stats()


@app.get("/api/leads")
def list_leads(
    wilaya: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    min_score: float = Query(0.0, ge=0.0, le=100.0),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    leads = _repo().list_leads(
        wilaya=wilaya, industry=industry, min_score=min_score,
        limit=limit, offset=offset,
    )
    return {
        "count": len(leads),
        "limit": limit,
        "offset": offset,
        "leads": [_lead_summary(l) for l in leads],
    }


@app.get("/api/leads/{lead_id}")
def get_lead(lead_id: int):
    lead = _repo().get_lead(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return _lead_detail(lead)


@app.get("/api/search")
def search(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=100)):
    leads = _repo().search(term=q, limit=limit)
    return {"count": len(leads), "leads": [_lead_summary(l) for l in leads]}


class StatusUpdate(BaseModel):
    status: str


@app.post("/api/leads/{lead_id}/status")
def update_status(lead_id: int, body: StatusUpdate):
    try:
        status = LeadStatus(body.status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")
    repo = _repo()
    lead = repo.get_lead(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    repo.set_status(lead_id, status)
    return {"ok": True, "id": lead_id, "status": status.value}


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ----------------------------------------------------------------------------
#  Serialisation helpers
# ----------------------------------------------------------------------------

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
        "digital_presence_score": lead.analysis.digital_presence_score if lead.analysis else None,
        "estimated_value_usd": lead.total_estimated_value_usd,
        "top_service": (
            lead.analysis.recommended_solutions[0].service_name
            if lead.analysis and lead.analysis.recommended_solutions
            else None
        ),
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
        "discovered_at": lead.business.discovered_at.isoformat() if lead.business.discovered_at else None,
        "analysis": (
            {
                "pain_points": lead.analysis.pain_points,
                "recommended_solutions": [
                    s.model_dump(mode="json") for s in lead.analysis.recommended_solutions
                ],
                "digital_presence_score": lead.analysis.digital_presence_score,
                "pitch_angles": lead.analysis.pitch_angles,
                "estimated_monthly_revenue_usd": lead.analysis.estimated_monthly_revenue_usd,
                "analysis_model": lead.analysis.analysis_model,
                "from_cache": lead.analysis.from_cache,
                "analyzed_at": lead.analysis.analyzed_at.isoformat() if lead.analysis.analyzed_at else None,
            }
            if lead.analysis
            else None
        ),
    })
    return summary
