"""Streaming discovery orchestration.

Pipeline (TTFR-optimized — iteration 4's core insight):
    query -> dialect expansion (offline) -> scrapers streamed concurrently
    -> per-lead deterministic audit + scoring (native batch) -> upsert.

Leads are persisted as they stream in; the campaign record reflects
created vs merged counts accurately (fixing v2's duplicate accounting,
where the repo returned the existing row id on conflict and everything
was counted as "saved").
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Optional

from domain.models import Lead
from engine.analyzer import BusinessAnalyzer
from engine.resolver import GoldenRecordBuilder, GraphEntityResolver
from engine.scorer import LeadScorer
from infrastructure.storage.cluster_repo import ClusterRepository
from infrastructure.storage.lead_repo import LeadRepository
from utils.query_expander import AlgerianQueryExpander

logger = logging.getLogger("services.discovery")


class DiscoveryService:
    def __init__(
        self,
        aggregator,                     # ScraperAggregator
        repo: LeadRepository,
        analyzer: Optional[BusinessAnalyzer] = None,
        scorer: Optional[LeadScorer] = None,
        expander: Optional[AlgerianQueryExpander] = None,
    ) -> None:
        self._aggregator = aggregator
        self._repo = repo
        self._analyzer = analyzer or BusinessAnalyzer()
        self._scorer = scorer or LeadScorer()
        self._expander = expander or AlgerianQueryExpander()

    # ------------------------------------------------------------------
    async def discover(
        self, query: str, wilaya: Optional[str] = None, limit: int = 30
    ) -> dict:
        campaign_id = await self._repo.create_campaign(query, wilaya, limit)
        created = merged = 0
        try:
            async for lead in self.stream(query, wilaya, limit):
                _, was_created = await self._repo.upsert(lead)
                if was_created:
                    created += 1
                else:
                    merged += 1
            status = "completed"
        except Exception:
            await self._repo.finish_campaign(campaign_id, "failed", 0, 0, 0)
            raise

        await self._repo.finish_campaign(
            campaign_id, status, created + merged, created, merged
        )
        return {
            "query": query,
            "wilaya": wilaya,
            "target_limit": limit,
            "saved_count": created,
            "merged_count": merged,
            "campaign_id": campaign_id,
        }

    # ------------------------------------------------------------------
    async def stream(
        self, query: str, wilaya: Optional[str] = None, limit: int = 30
    ) -> AsyncIterator[Lead]:
        """Audit + score every streamed candidate before yielding it."""
        variants = await self._expander.expand(query)
        if not variants:
            return

        async for lead in self._aggregator.stream_discover(variants, wilaya, limit):
            audit = self._analyzer.audit(lead)
            lead.digital_score = audit.digital_score
            lead.digital_tier = audit.digital_tier
            lead.gaps = audit.gaps
            lead.recommended_services = [s.to_dict() for s in audit.recommended_services]
            lead.cta_fr = audit.cta_fr
            lead.cta_ar = audit.cta_ar
            lead.analysis_model = audit.analysis_model
            self._scorer.score(lead)
            yield lead


class ScraperAggregator:
    """Coordinates every enabled scraper concurrently over query variants.

    Exhaustive pagination is preserved from v2.0.0: variants are cycled
    until the limit is met or all sources are dry.
    """

    def __init__(self, scrapers: list) -> None:
        self._scrapers = list(scrapers)

    def add_scraper(self, scraper) -> None:
        self._scrapers.append(scraper)

    async def stream_discover(
        self,
        variants: list[str],
        wilaya: Optional[str],
        limit: int,
    ) -> AsyncIterator[Lead]:
        if not self._scrapers:
            return

        seen: set[str] = set()
        yielded = 0

        for variant in variants:
            if yielded >= limit:
                break
            over_fetch = max(limit * 2, limit + 5)

            tasks = {
                scraper.source_name: scraper.stream_discover(
                    variant, wilaya=wilaya, limit=over_fetch
                )
                for scraper in self._scrapers
            }

            # Fan-in: consume every scraper's stream as results arrive.
            queue: asyncio.Queue = asyncio.Queue(maxsize=256)

            async def pump(name: str, stream) -> None:
                try:
                    async for lead in stream:
                        await queue.put((name, lead))
                except Exception as exc:  # one scraper failing must not kill the rest
                    logger.warning("Scraper %s failed on %r: %s", name, variant, exc)
                finally:
                    await queue.put((name, None))

            pumps = [
                asyncio.create_task(pump(name, stream), name=f"pump-{name}")
                for name, stream in tasks.items()
            ]
            try:
                finished = 0
                while finished < len(pumps):
                    name, lead = await queue.get()
                    if lead is None:
                        finished += 1
                        continue
                    fp = lead.fingerprint()
                    if fp in seen:
                        continue
                    seen.add(fp)
                    yielded += 1
                    yield lead
                    if yielded >= limit:
                        break
            finally:
                for task in pumps:
                    task.cancel()
                await asyncio.gather(*pumps, return_exceptions=True)


class ResolutionService:
    """Non-destructive entity resolution over the unified leads table."""

    def __init__(
        self,
        repo: LeadRepository,
        clusters: ClusterRepository,
        resolver: Optional[GraphEntityResolver] = None,
    ) -> None:
        self._repo = repo
        self._clusters = clusters
        self._resolver = resolver or GraphEntityResolver()

    async def resolve_all(self, batch_size: Optional[int] = None) -> dict:
        from config.settings import get_settings
        limit = batch_size or get_settings().ENTITY_RESOLUTION_BATCH

        leads = await self._repo.all_for_resolution(limit)
        if not leads:
            return {"input_count": 0, "output_count": 0, "clusters_stored": 0,
                    "duration_seconds": 0.0, "engine": "idle"}

        import asyncio as _asyncio
        clusters, report = await _asyncio.to_thread(self._resolver.resolve, leads)

        records = []
        for group in clusters:
            if len(group) < 2:
                continue  # singletons: nothing to store
            members = [leads[i] for i in group]
            records.append(GoldenRecordBuilder.build(members))

        stored = 0
        if records:
            stored = await self._clusters.replace_all(records)

        result = report.to_dict()
        result["clusters_stored"] = stored
        result["multi_member_clusters"] = len(records)
        return result
