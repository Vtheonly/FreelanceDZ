"""Crawler routes — start/stop/inspect the autonomous infinite crawler."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from api.dependencies import get_infinite_crawler
from services.infinite_crawler import AutonomousInfiniteCrawler
from utils.query_expander import sanitise_query


_logger = logging.getLogger("api.routes.crawler")
router = APIRouter(prefix="/api/v2/crawler", tags=["crawler"])


class CrawlStartRequest(BaseModel):
    """Body for ``POST /api/v2/crawler/start``.

    Every seed query is sanitised at the API boundary (Task 43 + Task 70)
    so a malicious payload cannot reach the frontier queue or the search
    engine URL builder.
    """
    queries: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Seed queries to bootstrap the frontier (1–50 queries).",
    )
    wilaya: Optional[str] = Field(None, max_length=100)

    @field_validator("queries")
    @classmethod
    def _validate_queries(cls, queries: list[str]) -> list[str]:
        cleaned: list[str] = []
        for q in queries:
            try:
                cleaned.append(sanitise_query(q))
            except ValueError as exc:
                raise ValueError(f"Invalid seed query {q!r}: {exc}") from exc
        if not cleaned:
            raise ValueError("At least one valid seed query is required.")
        return cleaned

    @field_validator("wilaya")
    @classmethod
    def _validate_wilaya(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        try:
            return sanitise_query(v)
        except ValueError as exc:
            raise ValueError(f"Invalid wilaya: {exc}") from exc


@router.post("/start")
async def start_crawler(
    body: CrawlStartRequest,
    crawler: AutonomousInfiniteCrawler = Depends(get_infinite_crawler),
):
    """Bootstrap the frontier with seed queries and start the crawl loop."""
    enqueued = await crawler.bootstrap(body.queries, wilaya=body.wilaya)
    if not crawler.is_active:
        crawler.start()
    return {
        "status": "started",
        "seed_urls_enqueued": enqueued,
        "stats": crawler.stats,
    }


@router.post("/stop")
async def stop_crawler(
    crawler: AutonomousInfiniteCrawler = Depends(get_infinite_crawler),
):
    """Stop the crawl loop gracefully."""
    await crawler.stop()
    return {"status": "stopped", "stats": crawler.stats}


@router.get("/status")
async def crawler_status(
    crawler: AutonomousInfiniteCrawler = Depends(get_infinite_crawler),
):
    """Return whether the crawler is running and its lifetime stats."""
    return {
        "is_active": crawler.is_active,
        "stats": crawler.stats,
    }
