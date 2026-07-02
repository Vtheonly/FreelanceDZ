"""Health check route."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from api.dependencies import get_database, get_settings_dep
from config.settings import AppSettings
from infrastructure.storage.database import DatabaseManager


router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    settings: AppSettings = Depends(get_settings_dep),
    db: DatabaseManager = Depends(get_database),
):
    """Lightweight health check — used by Docker/K8s liveness probes."""
    db_ok = db.integrity_check()
    return {
        "status": "ok" if db_ok else "degraded",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "database": "online" if db_ok else "offline",
        "db_path": str(db.db_path),
    }
