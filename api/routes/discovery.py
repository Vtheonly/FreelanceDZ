"""Discovery routes — trigger and monitor scraping campaigns."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field, field_validator

from api.dependencies import get_discovery_service, get_settings_dep
from services.discovery_service import DiscoveryService
from utils.query_expander import sanitise_query


_logger = logging.getLogger("api.routes.discovery")
router = APIRouter(prefix="/api/v2", tags=["discovery"])


class DiscoverRequest(BaseModel):
    """Body for ``POST /api/v2/discover``.

    All fields are constrained at the API boundary (Task 70) so invalid
    payloads are rejected with a clear 422 before they reach the
    services layer.
    """
    query: str = Field(..., min_length=2, max_length=200, description="Business category to search for")
    wilaya: Optional[str] = Field(None, max_length=100, description="Algerian wilaya to scope the search")
    limit: int = Field(default=30, ge=1, le=200, description="Target number of leads")
    background: bool = Field(
        default=False,
        description="When true, return immediately and crawl in the background.",
    )

    @field_validator("query")
    @classmethod
    def _validate_query(cls, v: str) -> str:
        """Sanitise the query at the API boundary (Task 43 + Task 70)."""
        try:
            return sanitise_query(v)
        except ValueError as exc:
            raise ValueError(f"Invalid query: {exc}") from exc

    @field_validator("wilaya")
    @classmethod
    def _validate_wilaya(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        try:
            return sanitise_query(v)
        except ValueError as exc:
            raise ValueError(f"Invalid wilaya: {exc}") from exc


class DiscoverResponse(BaseModel):
    status: str
    query: str
    wilaya: Optional[str]
    discovered_count: int
    saved_count: int
    duplicate_count: int


@router.post("/discover", response_model=DiscoverResponse)
async def discover(
    body: DiscoverRequest,
    background_tasks: BackgroundTasks,
    discovery: DiscoveryService = Depends(get_discovery_service),
):
    """Kick off an exhaustive sourcing campaign.

    When ``background`` is true, the response returns immediately with
    ``status=processing`` and the crawl runs in the background. Poll
    ``/api/v2/leads`` to see results appear.
    """
    if body.background:
        background_tasks.add_task(
            discovery.discover,
            query=body.query,
            wilaya=body.wilaya,
            limit=body.limit,
        )
        return DiscoverResponse(
            status="processing",
            query=body.query,
            wilaya=body.wilaya,
            discovered_count=0,
            saved_count=0,
            duplicate_count=0,
        )
    try:
        result = await discovery.discover(
            query=body.query, wilaya=body.wilaya, limit=body.limit
        )
        return DiscoverResponse(
            status="success",
            query=result.query,
            wilaya=result.wilaya,
            discovered_count=result.discovered_count,
            saved_count=result.saved_count,
            duplicate_count=result.duplicate_count,
        )
    except Exception as exc:
        _logger.exception("Discovery failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
