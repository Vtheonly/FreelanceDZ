"""FreelanceDZ CLI — discover, analyze, resolve, crawl, serve, stats, export."""

from __future__ import annotations

import asyncio
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

console = Console()


def _bootstrap():
    """Shared runtime bootstrap: logging + DB + repos + HTTP client."""
    from config.settings import get_settings
    from core.logging_setup import configure_logging
    from infrastructure.storage import (
        ClusterRepository,
        CrawlQueueRepository,
        DatabaseManager,
        LeadRepository,
    )

    settings = get_settings()
    configure_logging(settings.LOG_LEVEL, settings.LOG_DIR, settings.LOG_FORMAT)
    db = DatabaseManager()
    return settings, db, LeadRepository(db), ClusterRepository(db), CrawlQueueRepository(db)


async def _shutdown() -> None:
    from infrastructure.http import HttpClientFactory
    await HttpClientFactory.close_all()


@click.group(help="FreelanceDZ Engine v3 — deterministic B2B discovery for Algeria")
def cli():
    pass


@cli.command(help="Run a discovery campaign (search -> audit -> score -> persist)")
@click.option("--query", "-q", required=True, help="Business category to search")
@click.option("--wilaya", "-w", default=None, help="Target wilaya")
@click.option("--limit", "-l", default=30, type=int, help="Number of leads")
def discover(query: str, wilaya: Optional[str], limit: int):
    async def _run():
        from engine.analyzer import BusinessAnalyzer
        from engine.scorer import LeadScorer
        from infrastructure.scrapers.duckduckgo import DuckDuckGoScraper
        from infrastructure.scrapers.overpass import OverpassScraper
        from infrastructure.http import HttpClientFactory
        from services.discovery_service import DiscoveryService, ScraperAggregator

        settings, db, repo, _, _ = _bootstrap()
        client = HttpClientFactory.get_client(settings)
        scrapers = []
        if settings.ENABLE_DDG_SCRAPER:
            scrapers.append(DuckDuckGoScraper(client))
        if settings.ENABLE_OVERPASS_SCRAPER:
            scrapers.append(OverpassScraper(client))
        service = DiscoveryService(
            ScraperAggregator(scrapers), repo,
            analyzer=BusinessAnalyzer(), scorer=LeadScorer(),
        )
        console.print(f"[bold cyan]Discovery: {query} ({wilaya or 'Algeria'}) target={limit}[/bold cyan]")
        result = await service.discover(query, wilaya, limit)
        console.print(
            f"[green]Done: {result['saved_count']} new, {result['merged_count']} merged[/green]"
        )
        await _shutdown()

    asyncio.run(_run())


@cli.command(help="Analyze + score every pending lead")
@click.option("--limit", "-l", default=200, type=int)
def analyze(limit: int):
    async def _run():
        from engine.analyzer import BusinessAnalyzer
        from engine.scorer import LeadScorer

        _, _, repo, _, _ = _bootstrap()
        analyzer, scorer = BusinessAnalyzer(), LeadScorer()
        pending = await repo.list_unanalyzed(limit=limit)
        for lead in pending:
            audit = analyzer.audit(lead)
            lead.digital_score = audit.digital_score
            lead.digital_tier = audit.digital_tier
            lead.gaps = audit.gaps
            lead.recommended_services = [s.to_dict() for s in audit.recommended_services]
            lead.cta_fr = audit.cta_fr
            lead.cta_ar = audit.cta_ar
            lead.analysis_model = audit.analysis_model
            scorer.score(lead)
            await repo.upsert(lead)
        console.print(f"[green]Analyzed {len(pending)} leads[/green]")
        await _shutdown()

    asyncio.run(_run())


@cli.command(help="Run entity resolution (non-destructive clustering)")
def resolve():
    async def _run():
        from services.discovery_service import ResolutionService
        from engine.resolver import GraphEntityResolver

        _, _, repo, clusters, _ = _bootstrap()
        service = ResolutionService(repo, clusters, GraphEntityResolver())
        result = await service.resolve_all()
        table = Table(title="Entity Resolution")
        for key, value in result.items():
            table.add_row(str(key), str(value))
        console.print(table)
        await _shutdown()

    asyncio.run(_run())


@cli.command(help="Start the API server + dashboard")
@click.option("--host", "-h", default=None, help="Bind address (default from settings)")
@click.option("--port", "-p", default=None, type=int, help="Port (default from settings)")
def serve(host: Optional[str], port: Optional[int]):
    import uvicorn
    from config.settings import get_settings
    from core.dependency_guard import verify_runtime_dependencies

    # Issue #3: fail fast (with the documented remediation) if pip left the
    # environment with an incompatible FastAPI/Starlette/Streamlit trio.
    verify_runtime_dependencies()

    settings = get_settings()
    bind_host = host or settings.API_HOST
    bind_port = port or settings.API_PORT
    console.print(f"[bold green]Serving on http://{bind_host}:{bind_port}[/bold green]")
    uvicorn.run("api.server:app", host=bind_host, port=bind_port, reload=False)


@cli.command(help="Show database statistics")
def stats():
    async def _run():
        _, _, repo, clusters, queue = _bootstrap()
        data = await repo.stats()
        data["pending_crawl_urls"] = await queue.count_by_status("pending")
        table = Table(title="FreelanceDZ Engine Stats")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        for key, value in data.items():
            table.add_row(key, str(value))
        console.print(table)
        await _shutdown()

    asyncio.run(_run())


@cli.command(help="Export leads to CSV/JSON")
@click.option("--format", "-f", "fmt", type=click.Choice(["csv", "json"]), default="csv")
@click.option("--limit", "-l", default=1000, type=int)
def export(fmt: str, limit: int):
    async def _run():
        from services.export_service import ExportService

        _, _, repo, clusters, _ = _bootstrap()
        service = ExportService(repo, clusters)
        if fmt == "csv":
            path = await service.export_leads_csv(limit=limit)
        else:
            path = await service.export_leads_json(limit=limit)
        console.print(f"[green]Exported to {path}[/green]")
        await _shutdown()

    asyncio.run(_run())


@cli.command(help="Start the Streamlit Dynamic Grid & Interactive Map Workspace")
@click.option("--port", "-p", default=8501, type=int, help="Streamlit port")
@click.option("--engine", "-e", default=None, help="Engine API base URL (default http://localhost:8080)")
def ui(port: int, engine: Optional[str]):
    """Launch the modern Streamlit workspace (a pure API client of the engine)."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    app_path = Path(__file__).resolve().parent / "ui" / "app.py"
    if engine:
        os.environ["ENGINE_URL"] = engine
    console.print(
        f"[bold green]Starting FreelanceDZ Streamlit Workspace on "
        f"http://localhost:{port}[/bold green] "
        f"(engine: {os.environ.get('ENGINE_URL', 'http://localhost:8080')})"
    )
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(app_path),
        "--server.port", str(port),
        "--server.headless", "true",
    ]
    raise SystemExit(subprocess.run(cmd).returncode)


@cli.command(help="Run the benchmarks (fastops core + storage + geo)")
def bench():
    from benchmarks.bench_engine import main
    main()


@cli.command(help="Run the test suite")
def test():
    import sys
    sys.exit(click.echo("Use: python -m pytest tests/"))


if __name__ == "__main__":
    cli()
