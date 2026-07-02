"""FastAPI dashboard — browse, search, and inspect leads in the browser."""

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
from infrastructure.scrapers.overpass import OverpassScraper
from infrastructure.scrapers.duckduckgo import DuckDuckGoScraper
from infrastructure.scrapers.mock import MockScraper
from infrastructure.scrapers.aggregator import ScraperAggregator
from infrastructure.llm.factory import build_llm_client
from services.pipeline import ProspectingPipeline
from services.analyzer import LeadAnalyzerService
from services.scorer import LeadScoringEngine
from config.wilayas import all_wilaya_names

configure_logging(level="INFO", log_dir=Path("data/logs"))

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(
    title="DZ Sales Intelligence",
    description="AI-powered business discovery & lead scoring platform for Algeria",
    version="1.0.0",
)

def _repo() -> SQLiteLeadRepository:
    return SQLiteLeadRepository()

class DiscoverRequest(BaseModel):
    query: str
    wilaya: Optional[str] = None
    limit: int = 10
    enable_overpass: bool = True
    enable_ddg: bool = True
    enable_mock: bool = True

class BatchAnalyzeRequest(BaseModel):
    limit: int = 5

class TagsUpdate(BaseModel):
    tags: list[str]

class StatusUpdate(BaseModel):
    status: str

# ----------------------------------------------------------------------------
#  HTML Pages & Wilayas Catalog List
# ----------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return TEMPLATES.TemplateResponse(request=request, name="dashboard.html")

@app.get("/api/wilayas")
def get_wilayas():
    """Retrieve all 58 Algerian wilaya names."""
    return {"wilayas": all_wilaya_names()}

# ----------------------------------------------------------------------------
#  Discovery Crawl & Custom Label Tag Endpoints
# ----------------------------------------------------------------------------

@app.post("/api/discover")
def trigger_discovery(body: DiscoverRequest):
    """Launch search aggregator with custom modules in real-time and save matching leads."""
    repo = _repo()
    scrapers = []
    if body.enable_overpass:
        scrapers.append(OverpassScraper())
    if body.enable_ddg:
        scrapers.append(DuckDuckGoScraper())
    if body.enable_mock:
        scrapers.append(MockScraper())
        
    if not scrapers:
        scrapers.append(MockScraper())
        
    scraper = ScraperAggregator(scrapers=scrapers)
    
    try:
        llm = build_llm_client()
    except Exception:
        llm = None
    
    pipeline = ProspectingPipeline(scraper=scraper, llm=llm, repo=repo)
    new_count = pipeline.discover(query=body.query, wilaya=body.wilaya, limit=body.limit)
    return {"success": True, "new_leads_count": new_count}

@app.post("/api/leads/{lead_id}/tags")
def update_tags(lead_id: int, body: TagsUpdate):
    """Update custom labels/tags applied to the lead."""
    repo = _repo()
    lead = repo.get_lead(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    repo.set_tags(lead_id, body.tags)
    return {"ok": True, "id": lead_id, "tags": body.tags}

# ----------------------------------------------------------------------------
#  Direct UI Real-Time Analysis & Global Pipeline Commands
# ----------------------------------------------------------------------------

@app.post("/api/leads/{lead_id}/analyze")
def analyze_single_lead(lead_id: int):
    """Trigger LLM analysis for a single lead, recalculate its score, and save both."""
    repo = _repo()
    lead = repo.get_lead(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    try:
        llm = build_llm_client()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM configuration error: {e}")
        
    # Analyze the business
    analyzer = LeadAnalyzerService(llm=llm, repo=repo)
    analysis = llm.analyze_business_needs(lead.business)
    repo.attach_analysis(lead_id, analysis)
    
    # Retrieve updated lead and recalculate prioritize score
    updated_lead = repo.get_lead(lead_id)
    scorer = LeadScoringEngine()
    score = scorer.calculate_score(updated_lead)
    breakdown = scorer.explain_score(updated_lead)
    repo.update_score(lead_id, score, breakdown)
    
    return {"success": True, "score": score, "lead": _lead_detail(updated_lead)}

@app.post("/api/analyze-pending")
def analyze_pending_leads(body: BatchAnalyzeRequest):
    """Trigger batch LLM analysis on unanalyzed database rows, then rescore them."""
    repo = _repo()
    try:
        llm = build_llm_client()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM configuration error: {e}")
        
    analyzer = LeadAnalyzerService(llm=llm, repo=repo)
    analyzed_count = analyzer.analyze_pending(limit=body.limit)
    
    # Re-evaluate database priority scores
    pipeline = ProspectingPipeline(scraper=ScraperAggregator(), llm=llm, repo=repo)
    pipeline.score(limit=500)
    
    return {"success": True, "analyzed_count": analyzed_count}

@app.post("/api/score-all")
def score_all_leads():
    """Recalculate lead scoring across the entire database."""
    repo = _repo()
    pipeline = ProspectingPipeline(scraper=ScraperAggregator(), llm=None, repo=repo)
    scored_count = pipeline.score(limit=1000)
    return {"success": True, "scored_count": scored_count}

# ----------------------------------------------------------------------------
#  Core JSON endpoints
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
        "tags": getattr(lead, "tags", []),
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