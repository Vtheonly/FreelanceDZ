"""FastAPI application factory — the engine's public API surface.

The legacy Jinja2 dashboard was fully replaced by the Streamlit workspace
(``ui/``) in the v4 refactor and removed; this server now serves only the
documented JSON API (see docs/04-api-reference.md). The Streamlit UI is a
separate service that talks to this API like any other client.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes import checkpoints as checkpoints_routes
from api.routes import geo as geo_routes
from api.routes import leads as leads_routes
from api.routes import misc as misc_routes
from config.settings import get_settings
from core.logging_setup import configure_logging
from infrastructure.http import HttpClientFactory
from infrastructure.storage.database import DatabaseManager

logger = logging.getLogger("api.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL, settings.LOG_DIR, settings.LOG_FORMAT)
    app.state.database = DatabaseManager()
    logger.info("%s v%s ready (API only)", settings.APP_NAME, settings.APP_VERSION)
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
            "Deterministic B2B sales-intelligence engine for the Algerian "
            "market: discovery, audit, scoring, entity resolution, and "
            "geographic intelligence over the 58 wilayas."
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
    app.include_router(geo_routes.geo_router)
    app.include_router(checkpoints_routes.checkpoints_router)

    @app.get("/api", include_in_schema=False)
    async def route_index():
        return {
            "endpoints": sorted(
                f"{list(route.methods)[0]} {route.path}"
                for route in app.routes
                if hasattr(route, "methods") and route.methods
            )
        }

    return app


app = create_app()
