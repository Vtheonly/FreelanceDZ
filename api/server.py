"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from api.routes import leads as leads_routes
from api.routes import misc as misc_routes
from config.settings import get_settings
from core.logging_setup import configure_logging
from infrastructure.http import HttpClientFactory
from infrastructure.storage.database import DatabaseManager

logger = logging.getLogger("api.server")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL, settings.LOG_DIR, settings.LOG_FORMAT)
    app.state.database = DatabaseManager()
    logger.info(
        "%s v%s ready (dashboard=%s)", settings.APP_NAME, settings.APP_VERSION,
        settings.ENABLE_DASHBOARD,
    )
    try:
        yield
    finally:
        await HttpClientFactory.close_all()
        logger.info("Shutdown complete.")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Deterministic B2B sales-intelligence engine for the Algerian market. "
            "Python asyncio orchestration + C++20 SIMD native core."
        ),
        lifespan=lifespan,
    )

    # Order matters: leads routes register their static paths before the
    # parameterized /leads/{lead_id}; misc registers /entities/stats before
    # /entities/{cluster_id}.
    app.include_router(misc_routes.health_router)
    app.include_router(leads_routes.router)
    app.include_router(misc_routes.discovery_router)
    app.include_router(misc_routes.entities_router)
    app.include_router(misc_routes.export_router)
    app.include_router(misc_routes.crawler_router)
    app.include_router(misc_routes.analytics_router)

    @app.get("/api", include_in_schema=False)
    async def route_index():
        return {
            "endpoints": sorted(
                f"{list(route.methods)[0]} {route.path}"
                for route in app.routes
                if hasattr(route, "methods") and route.methods
            )
        }

    if settings.ENABLE_DASHBOARD:

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        async def dashboard(request: Request):
            return TEMPLATES.TemplateResponse(
                request=request,
                name="dashboard.html",
                context={
                    "app_name": settings.APP_NAME,
                    "app_version": settings.APP_VERSION,
                },
            )

    return app


app = create_app()
