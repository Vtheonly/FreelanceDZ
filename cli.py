"""CLI entry point — async command-line interface built on ``click``.

Provides subcommands for every operation the engine supports:

* ``discover``  — run a single sourcing campaign.
* ``analyze``   — run LLM analysis on pending leads.
* ``score``     — recompute priority scores.
* ``resolve``   — run the graph entity resolver.
* ``export``    — export leads/entities to disk.
* ``crawler``   — start the autonomous infinite crawler.
* ``serve``     — start the FastAPI server (equivalent to ``uvicorn``).
* ``stats``     — print aggregate database stats.

Every command runs inside an ``ApplicationLifecycle`` context so the
HTTP client pool and database are properly initialised and torn down.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from config.settings import get_settings
from core.lifecycle import ApplicationLifecycle


_console = Console()
_logger = logging.getLogger("cli")


# ============================================================
#  Click group
# ============================================================

@click.group(help="FreelanceDZ Engine — modular B2B lead-discovery CLI.")
@click.version_option(version="2.0.0", prog_name="freelancedz")
def cli() -> None:
    """Entry point — subcommands are registered below."""


# ============================================================
#  discover
# ============================================================

@cli.command(help="Run a sourcing campaign and persist the results.")
@click.option("--query", "-q", required=True, help="Industry/category to search for.")
@click.option("--wilaya", "-w", default=None, help="Algerian wilaya to scope the search.")
@click.option("--limit", "-l", default=30, type=int, help="Target number of leads.")
def discover(query: str, wilaya: Optional[str], limit: int) -> None:
    async def _run():
        async with ApplicationLifecycle.create() as life:
            from infrastructure.http.client_factory import HttpClientFactory
            from infrastructure.scrapers.aggregator import ScraperAggregator
            from infrastructure.scrapers.duckduckgo import AsyncDuckDuckGoScraper
            from infrastructure.scrapers.overpass import AsyncOverpassScraper
            from infrastructure.storage.database import DatabaseManager
            from infrastructure.storage.repositories.raw_record_repo import RawRecordRepository
            from services.discovery_service import DiscoveryService

            settings = life.settings
            client = HttpClientFactory.get_client(settings)
            db = DatabaseManager(settings=settings)
            raw_repo = RawRecordRepository(db)

            scrapers = []
            if settings.ENABLE_DDG_SCRAPER:
                scrapers.append(AsyncDuckDuckGoScraper(client))
            if settings.ENABLE_OVERPASS_SCRAPER:
                scrapers.append(AsyncOverpassScraper(client))
            aggregator = ScraperAggregator(client=client, scrapers=scrapers)

            service = DiscoveryService(aggregator=aggregator, raw_repo=raw_repo)
            result = await service.discover(query=query, wilaya=wilaya, limit=limit)

            table = Table(title="Discovery Result")
            for col in ("Query", "Wilaya", "Limit", "Discovered", "Saved", "Duplicates"):
                table.add_column(col)
            table.add_row(
                result.query, result.wilaya or "—", str(result.requested_limit),
                str(result.discovered_count), str(result.saved_count), str(result.duplicate_count),
            )
            _console.print(table)
    asyncio.run(_run())


# ============================================================
#  analyze
# ============================================================

@cli.command(help="Run LLM analysis on pending leads.")
@click.option("--limit", "-l", default=10, type=int, help="Max leads to analyse.")
def analyze(limit: int) -> None:
    async def _run():
        async with ApplicationLifecycle.create() as life:
            from infrastructure.llm.factory import build_llm_client
            from infrastructure.storage.database import DatabaseManager
            from infrastructure.storage.repositories.lead_repo import LeadRepository
            from infrastructure.storage.repositories.raw_record_repo import RawRecordRepository
            from services.analysis_service import AnalysisService

            db = DatabaseManager(settings=life.settings)
            raw_repo = RawRecordRepository(db)
            lead_repo = LeadRepository(db)
            llm = build_llm_client(life.settings)
            service = AnalysisService(llm=llm, raw_repo=raw_repo, lead_repo=lead_repo)
            count = await service.analyze_pending(limit=limit)
            _console.print(f"[green]Analysed {count} leads.[/green]")
    asyncio.run(_run())


# ============================================================
#  score
# ============================================================

@cli.command(help="Recompute priority scores for every lead.")
@click.option("--limit", "-l", default=500, type=int, help="Max leads to score.")
def score(limit: int) -> None:
    async def _run():
        async with ApplicationLifecycle.create() as life:
            from infrastructure.storage.database import DatabaseManager
            from infrastructure.storage.repositories.lead_repo import LeadRepository
            from services.scoring_service import ScoringService

            db = DatabaseManager(settings=life.settings)
            lead_repo = LeadRepository(db)
            service = ScoringService(lead_repo=lead_repo)
            count = await service.score_all(limit=limit)
            _console.print(f"[green]Scored {count} leads.[/green]")
    asyncio.run(_run())


# ============================================================
#  resolve
# ============================================================

@cli.command(help="Run the graph entity resolver.")
def resolve() -> None:
    async def _run():
        async with ApplicationLifecycle.create() as life:
            from infrastructure.entity_resolution.graph_resolver import GraphEntityResolver
            from infrastructure.storage.database import DatabaseManager
            from infrastructure.storage.repositories.raw_record_repo import RawRecordRepository
            from infrastructure.storage.repositories.resolved_entity_repo import ResolvedEntityRepository
            from services.resolution_service import ResolutionService

            db = DatabaseManager(settings=life.settings)
            raw_repo = RawRecordRepository(db)
            resolved_repo = ResolvedEntityRepository(db)
            resolver = GraphEntityResolver()
            service = ResolutionService(
                raw_repo=raw_repo, resolved_repo=resolved_repo, resolver=resolver,
            )
            result = await service.resolve_all()
            _console.print(
                f"[green]Resolved {result.input_count} → {result.output_count} "
                f"entities ({result.compression_ratio:.2f}x compression in {result.duration_seconds:.2f}s)[/green]"
            )
    asyncio.run(_run())


# ============================================================
#  export
# ============================================================

@cli.command(help="Export leads to CSV/JSON.")
@click.option("--format", "-f", "fmt", default="csv", type=click.Choice(["csv", "json"]))
@click.option("--limit", "-l", default=1000, type=int)
def export(fmt: str, limit: int) -> None:
    async def _run():
        async with ApplicationLifecycle.create() as life:
            from infrastructure.storage.database import DatabaseManager
            from infrastructure.storage.repositories.lead_repo import LeadRepository
            from infrastructure.storage.repositories.resolved_entity_repo import ResolvedEntityRepository
            from services.export_service import ExportService

            db = DatabaseManager(settings=life.settings)
            lead_repo = LeadRepository(db)
            resolved_repo = ResolvedEntityRepository(db)
            service = ExportService(lead_repo=lead_repo, resolved_repo=resolved_repo)
            if fmt == "csv":
                path = await service.export_leads_csv(limit=limit)
            else:
                path = await service.export_leads_json(limit=limit)
            _console.print(f"[green]Exported to {path}[/green]")
    asyncio.run(_run())


# ============================================================
#  crawler
# ============================================================

@cli.command(help="Start the autonomous infinite crawler (foreground).")
@click.option("--query", "-q", "queries", multiple=True, required=True, help="Seed query (repeatable).")
@click.option("--wilaya", "-w", default=None)
def crawler(queries: tuple[str, ...], wilaya: Optional[str]) -> None:
    async def _run():
        async with ApplicationLifecycle.create() as life:
            from infrastructure.http.client_factory import HttpClientFactory
            from infrastructure.scrapers.frontier import CrawlFrontier
            from infrastructure.storage.database import DatabaseManager
            from infrastructure.storage.repositories.crawl_queue_repo import CrawlQueueRepository
            from infrastructure.storage.repositories.raw_record_repo import RawRecordRepository
            from services.infinite_crawler import AutonomousInfiniteCrawler

            settings = life.settings
            client = HttpClientFactory.get_client(settings)
            db = DatabaseManager(settings=settings)
            raw_repo = RawRecordRepository(db)
            queue_repo = CrawlQueueRepository(db)
            frontier = CrawlFrontier(queue_repo)
            crawler_obj = AutonomousInfiniteCrawler(
                client=client, raw_repo=raw_repo, frontier=frontier, settings=settings,
            )
            enqueued = await crawler_obj.bootstrap(list(queries), wilaya=wilaya)
            _console.print(f"[green]Enqueued {enqueued} seed URLs. Starting crawler (Ctrl+C to stop).[/green]")
            crawler_obj.start()
            try:
                while crawler_obj.is_active:
                    await asyncio.sleep(10.0)
                    _console.print(
                        f"[cyan]Stats: {crawler_obj.stats}[/cyan]", end="\r",
                    )
            except KeyboardInterrupt:
                _console.print("\n[yellow]Stopping crawler...[/yellow]")
                await crawler_obj.stop()
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        _console.print("\n[yellow]Interrupted.[/yellow]")


# ============================================================
#  stats
# ============================================================

@cli.command(help="Print aggregate database stats.")
def stats() -> None:
    async def _run():
        async with ApplicationLifecycle.create() as life:
            from infrastructure.storage.database import DatabaseManager
            from infrastructure.storage.repositories.lead_repo import LeadRepository
            from infrastructure.storage.repositories.resolved_entity_repo import ResolvedEntityRepository

            db = DatabaseManager(settings=life.settings)
            lead_repo = LeadRepository(db)
            resolved_repo = ResolvedEntityRepository(db)
            data = await lead_repo.stats()
            entities = await resolved_repo.count()

            table = Table(title="Database Stats")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", style="green")
            for key in ("total_leads", "analyzed_leads", "scored_leads", "unanalyzed_leads", "average_score"):
                table.add_row(key, str(data.get(key)))
            table.add_row("resolved_entities", str(entities))
            _console.print(table)
    asyncio.run(_run())


# ============================================================
#  serve
# ============================================================

@cli.command(help="Start the FastAPI server (uvicorn).")
@click.option("--host", "-h", default=None, help="Bind address (defaults to settings).")
@click.option("--port", "-p", default=None, type=int, help="Bind port (defaults to settings).")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload (dev only).")
def serve(host: Optional[str], port: Optional[int], reload: bool) -> None:
    settings = get_settings()
    host = host or settings.API_HOST
    port = port or settings.API_PORT
    import uvicorn
    _console.print(f"[green]Starting server on http://{host}:{port}[/green]")
    uvicorn.run(
        "api.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    cli()
