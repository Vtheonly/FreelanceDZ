"""Async FastAPI application factory.

Wires every route blueprint into a single app, configures CORS, and
mounts the dashboard HTML at the root path. The app is created via a
factory function so tests can build a fresh instance with overridden
dependencies.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from api.routes import analytics, crawler, discovery, entities, export, health, leads
from config.settings import get_settings
from core.constants import APP_DESCRIPTION, APP_NAME, APP_VERSION
from core.logging_setup import configure_logging
from infrastructure.http.client_factory import HttpClientFactory
from infrastructure.storage.database import DatabaseManager


_logger = logging.getLogger("api.server")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown hooks for the FastAPI app."""
    settings = get_settings()
    configure_logging(
        level=settings.LOG_LEVEL,
        log_dir=Path(settings.LOG_DIR),
        log_format=settings.LOG_FORMAT,
    )
    # Initialise the database and run migrations.
    app.state.database = DatabaseManager()
    # Create the shared HTTP client.
    app.state.http_client = HttpClientFactory.get_client(settings)
    _logger.info("FastAPI startup complete — app=%s v%s", APP_NAME, APP_VERSION)
    try:
        yield
    finally:
        await HttpClientFactory.close()
        _logger.info("FastAPI shutdown complete.")


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    settings = get_settings()
    app = FastAPI(
        title=APP_NAME,
        description=APP_DESCRIPTION,
        version=APP_VERSION,
        lifespan=lifespan,
    )

    # Register every route blueprint.
    app.include_router(health.router)
    app.include_router(discovery.router)
    app.include_router(leads.router)
    app.include_router(entities.router)
    app.include_router(export.router)
    app.include_router(crawler.router)
    app.include_router(analytics.router)

    # Dashboard HTML at the root.
    if settings.ENABLE_DASHBOARD:
        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        async def dashboard(request: Request):
            return TEMPLATES.TemplateResponse(
                request=request, name="dashboard.html",
                context={"app_name": APP_NAME, "app_version": APP_VERSION},
            )

    @app.get("/api", include_in_schema=False)
    async def api_root():
        """API root — lists the available route prefixes."""
        return {
            "app": APP_NAME,
            "version": APP_VERSION,
            "routes": [
                "/api/v2/discover",
                "/api/v2/leads",
                "/api/v2/leads/search",
                "/api/v2/entities",
                "/api/v2/entities/resolve",
                "/api/v2/crawler/start",
                "/api/v2/crawler/stop",
                "/api/v2/crawler/status",
                "/api/v2/stats",
                "/health",
            ],
        }

    return app


# Module-level instance for ``uvicorn api.server:app``.
app = create_app()
