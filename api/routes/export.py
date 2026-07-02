"""Export routes — download leads/entities as CSV or JSON."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from api.dependencies import get_export_service
from services.export_service import ExportService


_logger = logging.getLogger("api.routes.export")
router = APIRouter(prefix="/api/v2/export", tags=["export"])


@router.get("/leads/csv")
async def export_leads_csv(
    limit: int = 1000,
    export: ExportService = Depends(get_export_service),
):
    """Download the top ``limit`` leads as a CSV file."""
    path = await export.export_leads_csv(limit=limit)
    return FileResponse(
        path=str(path),
        media_type="text/csv",
        filename=path.name,
    )


@router.get("/leads/json")
async def export_leads_json(
    limit: int = 1000,
    export: ExportService = Depends(get_export_service),
):
    """Download leads as a JSON file."""
    path = await export.export_leads_json(limit=limit)
    return FileResponse(
        path=str(path),
        media_type="application/json",
        filename=path.name,
    )


@router.get("/entities/json")
async def export_entities_json(
    limit: int = 1000,
    export: ExportService = Depends(get_export_service),
):
    """Download resolved entities as a JSON file."""
    path = await export.export_entities_json(limit=limit)
    return FileResponse(
        path=str(path),
        media_type="application/json",
        filename=path.name,
    )
