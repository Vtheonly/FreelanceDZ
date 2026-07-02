"""DZ Sales Intelligence — Command Line Interface.

Built with Click. Run `python cli.py --help` for the full command list.

Examples:
    python cli.py discover --query "restaurant" --wilaya "Algiers" --limit 20
    python cli.py analyze --limit 50
    python cli.py score
    python cli.py stats
    python cli.py top --n 20
    python cli.py export --format csv --out ./data/exports/leads.csv
    python cli.py search --term "pharmacie"
    python cli.py pipeline --query "gym" --wilaya "Oran" --limit 15
    python cli.py serve --port 8080
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from config.settings import settings
from core.logging_setup import configure_logging
from domain.exceptions import ConfigurationError, DzSalesIntelError
from domain.models import Lead, LeadStatus
from infrastructure.llm.factory import build_llm_client
from infrastructure.scrapers.aggregator import ScraperAggregator
from infrastructure.storage.sqlite_repo import SQLiteLeadRepository
from services.analyzer import LeadAnalyzerService
from services.pipeline import ProspectingPipeline
from services.scorer import LeadScoringEngine


console = Console()


# ============================================================================
#  Helpers
# ============================================================================

def _bootstrap_logging() -> None:
    configure_logging(level=settings.LOG_LEVEL, log_dir=Path("data/logs"))


def _build_repo() -> SQLiteLeadRepository:
    return SQLiteLeadRepository()


def _build_llm():
    try:
        return build_llm_client()
    except ConfigurationError as e:
        console.print(f"[red]LLM config error:[/red] {e}")
        sys.exit(2)


def _print_lead_table(leads: list[Lead], title: str = "Leads") -> None:
    if not leads:
        console.print(f"[yellow]No leads found for:[/yellow] {title}")
        return
    table = Table(title=title, show_lines=False)
    table.add_column("#", style="dim", width=3)
    table.add_column("Score", justify="right", style="bold cyan")
    table.add_column("Business", style="white")
    table.add_column("Industry", style="magenta")
    table.add_column("Wilaya", style="green")
    table.add_column("Website?", justify="center")
    table.add_column("Reviews", justify="right")
    table.add_column("Est. $", justify="right", style="yellow")
    table.add_column("Status", style="dim")

    for i, lead in enumerate(leads, start=1):
        website_flag = "" if lead.business.website else ""
        table.add_row(
            str(i),
            f"{lead.priority_score:.1f}",
            lead.business.name[:30],
            lead.business.industry[:18],
            lead.business.wilaya[:14],
            website_flag,
            str(lead.business.review_count),
            f"${lead.total_estimated_value_usd:,.0f}",
            lead.status.value,
        )
    console.print(table)


def _lead_to_dict(lead: Lead) -> dict:
    """Flatten a Lead into a CSV/JSON-friendly dict."""
    return {
        "id": lead.id,
        "name": lead.business.name,
        "industry": lead.business.industry,
        "wilaya": lead.business.wilaya,
        "address": lead.business.address or "",
        "website": lead.business.website or "",
        "phone": lead.business.phone or "",
        "email": lead.business.email or "",
        "social_media": " | ".join(lead.business.social_media_handles),
        "rating": lead.business.rating,
        "review_count": lead.business.review_count,
        "source": lead.business.source.value,
        "priority_score": lead.priority_score,
        "status": lead.status.value,
        "digital_presence_score": lead.analysis.digital_presence_score if lead.analysis else "",
        "estimated_value_usd": lead.total_estimated_value_usd,
        "top_service": (
            lead.analysis.recommended_solutions[0].service_name
            if lead.analysis and lead.analysis.recommended_solutions
            else ""
        ),
        "pain_points": (
            " | ".join(lead.analysis.pain_points)
            if lead.analysis and lead.analysis.pain_points
            else ""
        ),
    }


# ============================================================================
#  CLI group
# ============================================================================

@click.group(help="DZ Sales Intelligence — AI-powered Algerian business discovery & lead scoring.")
@click.version_option("1.0.0", prog_name="dz-sales-intel")
def cli() -> None:
    """Entry point."""
    _bootstrap_logging()


# ----------------------------------------------------------------------------
#  discover
# ----------------------------------------------------------------------------

@cli.command(help="Crawl enabled scrapers and persist new businesses.")
@click.option("--query", "-q", required=True, help="Industry/category search term (e.g. 'restaurant').")
@click.option("--wilaya", "-w", default=None, help="Wilaya name (e.g. 'Algiers'). Defaults to no filter.")
@click.option("--limit", "-l", default=10, show_default=True, help="Max businesses to save.")
def discover(query: str, wilaya: Optional[str], limit: int) -> None:
    scraper = ScraperAggregator()
    repo = _build_repo()
    pipeline = ProspectingPipeline(scraper=scraper, llm=_build_llm(), repo=repo)
    new_count = pipeline.discover(query=query, wilaya=wilaya, limit=limit)
    console.print(f"[green]Discovery complete.[/green] New leads saved: [bold]{new_count}[/bold]")


# ----------------------------------------------------------------------------
#  analyze
# ----------------------------------------------------------------------------

@cli.command(help="Run LLM analysis on unanalyzed (or all) leads.")
@click.option("--limit", "-l", default=50, show_default=True, help="Max leads to analyze.")
@click.option("--force", is_flag=True, help="Re-analyze leads that already have an analysis.")
@click.option("--health-check", is_flag=True, help="Just check that the LLM API is reachable & authed.")
def analyze(limit: int, force: bool, health_check: bool) -> None:
    llm = _build_llm()
    if health_check:
        ok = llm.health_check()
        console.print(f"LLM health check: [{'green' if ok else 'red'}]{'OK' if ok else 'FAILED'}[/]")
        sys.exit(0 if ok else 1)
    repo = _build_repo()
    service = LeadAnalyzerService(llm=llm, repo=repo)
    count = service.analyze_pending(limit=limit, force=force)
    console.print(f"[green]Analysis complete.[/green] Leads analyzed: [bold]{count}[/bold]")


# ----------------------------------------------------------------------------
#  score
# ----------------------------------------------------------------------------

@cli.command(help="Recompute priority scores for all leads.")
@click.option("--limit", "-l", default=500, show_default=True, help="Max leads to score.")
def score(limit: int) -> None:
    repo = _build_repo()
    pipeline = ProspectingPipeline(scraper=ScraperAggregator(), llm=_build_llm(), repo=repo)
    n = pipeline.score(limit=limit)
    console.print(f"[green]Scoring complete.[/green] Leads scored: [bold]{n}[/bold]")


# ----------------------------------------------------------------------------
#  pipeline (full run)
# ----------------------------------------------------------------------------

@cli.command(help="Full pipeline: discover → analyze → score → top-N.")
@click.option("--query", "-q", required=True, help="Industry/category search term.")
@click.option("--wilaya", "-w", default=None, help="Wilaya name.")
@click.option("--limit", "-l", default=10, show_default=True, help="Discovery limit.")
def pipeline(query: str, wilaya: Optional[str], limit: int) -> None:
    repo = _build_repo()
    p = ProspectingPipeline(
        scraper=ScraperAggregator(),
        llm=_build_llm(),
        repo=repo,
    )
    leads = p.run_full_pipeline(query=query, wilaya=wilaya, discover_limit=limit)
    _print_lead_table(leads, title=f"Top {len(leads)} leads — query='{query}' wilaya='{wilaya or 'any'}'")


# ----------------------------------------------------------------------------
#  top
# ----------------------------------------------------------------------------

@cli.command(help="Show top-N prioritized leads.")
@click.option("--n", default=20, show_default=True, help="Number of leads to display.")
@click.option("--wilaya", "-w", default=None, help="Filter by wilaya.")
@click.option("--industry", "-i", default=None, help="Filter by industry (substring match).")
def top(n: int, wilaya: Optional[str], industry: Optional[str]) -> None:
    repo = _build_repo()
    leads = repo.list_leads(wilaya=wilaya, industry=industry, min_score=0.0, limit=n)
    _print_lead_table(leads, title=f"Top {n} leads")


# ----------------------------------------------------------------------------
#  search
# ----------------------------------------------------------------------------

@cli.command(help="Full-text search across business name / industry / wilaya / phone.")
@click.option("--term", "-t", required=True, help="Search term.")
@click.option("--limit", "-l", default=20, show_default=True, help="Max results.")
def search(term: str, limit: int) -> None:
    repo = _build_repo()
    leads = repo.search(term=term, limit=limit)
    _print_lead_table(leads, title=f"Search: '{term}'")


# ----------------------------------------------------------------------------
#  stats
# ----------------------------------------------------------------------------

@cli.command(help="Show database statistics.")
def stats() -> None:
    repo = _build_repo()
    s = repo.stats()

    console.print("\n[bold cyan]DZ Sales Intelligence — Database Stats[/bold cyan]\n")

    summary = Table(title="Summary", show_header=False)
    summary.add_column("Metric", style="white")
    summary.add_column("Value", style="bold green", justify="right")
    summary.add_row("Total leads", str(s["total_leads"]))
    summary.add_row("Analyzed", str(s["analyzed_leads"]))
    summary.add_row("Scored", str(s["scored_leads"]))
    summary.add_row("Unanalyzed", str(s["unanalyzed_leads"]))
    summary.add_row("Average score", f"{s['average_score']:.2f}")
    summary.add_row("Estimated pipeline (USD)", f"${s['estimated_pipeline_usd']:,.2f}")
    console.print(summary)

    if s["top_wilayas"]:
        t = Table(title="Top 10 Wilayas")
        t.add_column("Wilaya", style="green")
        t.add_column("Count", justify="right")
        for row in s["top_wilayas"]:
            t.add_row(row["wilaya"], str(row["count"]))
        console.print(t)

    if s["top_industries"]:
        t = Table(title="Top 10 Industries")
        t.add_column("Industry", style="magenta")
        t.add_column("Count", justify="right")
        for row in s["top_industries"]:
            t.add_row(row["industry"], str(row["count"]))
        console.print(t)

    if s["sources"]:
        t = Table(title="Sources")
        t.add_column("Source", style="cyan")
        t.add_column("Count", justify="right")
        for row in s["sources"]:
            t.add_row(row["source"], str(row["count"]))
        console.print(t)


# ----------------------------------------------------------------------------
#  export
# ----------------------------------------------------------------------------

@cli.command(help="Export leads to CSV / JSON / Markdown.")
@click.option("--format", "fmt", type=click.Choice(["csv", "json", "md"]), default="csv", show_default=True)
@click.option("--out", "-o", required=True, type=click.Path(dir_okay=False), help="Output file path.")
@click.option("--limit", "-l", default=1000, show_default=True, help="Max leads to export.")
def export(fmt: str, out: str, limit: int) -> None:
    repo = _build_repo()
    leads = repo.list_leads(min_score=0.0, limit=limit)
    if not leads:
        console.print("[yellow]No leads to export.[/yellow]")
        return

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "csv":
        rows = [_lead_to_dict(l) for l in leads]
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    elif fmt == "json":
        payload = [l.model_dump(mode="json") for l in leads]
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    elif fmt == "md":
        lines = ["# DZ Sales Intelligence — Lead Export\n"]
        lines.append("| # | Score | Name | Industry | Wilaya | Website | Est. $ |")
        lines.append("|---|-------|------|----------|--------|---------|--------|")
        for i, l in enumerate(leads, 1):
            lines.append(
                f"| {i} | {l.priority_score:.1f} | {l.business.name} | "
                f"{l.business.industry} | {l.business.wilaya} | "
                f"{'' if l.business.website else ''} | ${l.total_estimated_value_usd:,.0f} |"
            )
        out_path.write_text("\n".join(lines), encoding="utf-8")

    console.print(f"[green]Exported[/green] {len(leads)} leads → [bold]{out_path}[/bold]")


# ----------------------------------------------------------------------------
#  status (mark a lead as contacted / rejected)
# ----------------------------------------------------------------------------

@cli.command(help="Update a lead's status (contacted / rejected / discovered).")
@click.argument("lead_id", type=int)
@click.argument("status", type=click.Choice(["discovered", "analyzed", "scored", "contacted", "rejected"]))
def status(lead_id: int, status: str) -> None:
    repo = _build_repo()
    lead = repo.get_lead(lead_id)
    if lead is None:
        console.print(f"[red]Lead {lead_id} not found.[/red]")
        sys.exit(1)
    repo.set_status(lead_id, LeadStatus(status))
    console.print(f"[green]Lead {lead_id} status →[/green] [bold]{status}[/bold]")


# ----------------------------------------------------------------------------
#  serve (FastAPI dashboard)
# ----------------------------------------------------------------------------

@cli.command(help="Launch the FastAPI dashboard.")
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", "-p", default=8080, show_default=True, type=int)
def serve(host: str, port: int) -> None:
    try:
        import uvicorn
    except ImportError:
        console.print("[red]uvicorn not installed. Run:[/red] pip install uvicorn")
        sys.exit(1)
    console.print(f"[cyan]Starting dashboard on[/cyan] http://{host}:{port}")
    uvicorn.run("api.server:app", host=host, port=port, log_level="info", reload=False)


# ----------------------------------------------------------------------------
#  cache (clear LLM cache)
# ----------------------------------------------------------------------------

@cli.command("cache-clear", help="Clear all cached LLM responses.")
def cache_clear() -> None:
    from infrastructure.llm.cache import LLMCache
    n = LLMCache().clear()
    console.print(f"[green]Cleared[/green] {n} cached LLM responses.")


# ----------------------------------------------------------------------------
#  config (show effective config)
# ----------------------------------------------------------------------------

@cli.command("config", help="Print effective configuration (API key is masked).")
def show_config() -> None:
    masked = (settings.LLM_API_KEY[:6] + "..." + settings.LLM_API_KEY[-4:]) if len(settings.LLM_API_KEY) > 12 else "(not set)"
    console.print("\n[bold cyan]Effective Configuration[/bold cyan]\n")
    cfg = Table(show_header=False)
    cfg.add_column("Key", style="white")
    cfg.add_column("Value", style="green")
    cfg.add_row("LLM_PROVIDER", settings.LLM_PROVIDER)
    cfg.add_row("LLM_API_KEY", masked)
    cfg.add_row("LLM_API_BASE", settings.LLM_API_BASE)
    cfg.add_row("LLM_MODEL", settings.LLM_MODEL)
    cfg.add_row("DATABASE_PATH", settings.DATABASE_PATH)
    cfg.add_row("CACHE_DIR", settings.CACHE_DIR)
    cfg.add_row("EXPORT_DIR", settings.EXPORT_DIR)
    cfg.add_row("LOG_LEVEL", settings.LOG_LEVEL)
    cfg.add_row("RATE_LIMIT_DELAY_SECONDS", str(settings.RATE_LIMIT_DELAY_SECONDS))
    cfg.add_row("ENABLE_OVERPASS_SCRAPER", str(settings.ENABLE_OVERPASS_SCRAPER))
    cfg.add_row("ENABLE_DDG_SCRAPER", str(settings.ENABLE_DDG_SCRAPER))
    cfg.add_row("ENABLE_MOCK_SCRAPER", str(settings.ENABLE_MOCK_SCRAPER))
    console.print(cfg)


if __name__ == "__main__":
    cli()
