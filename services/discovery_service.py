"""Streaming discovery orchestration.

Pipeline (TTFR-optimized):
    query -> dialect expansion (offline, capped) -> all (variant x scraper)
    streams dispatched CONCURRENTLY -> per-lead deterministic audit +
    scoring -> upsert.

v4 Task 11 — the dialect-multiplier bomb is defused on two axes:
    1. the variant list is capped at ``DISCOVERY_MAX_VARIANTS`` (default 2:
       the primary query + its strongest regional counterpart) instead of
       fanning 11 sequential variants;
    2. the remaining variants are dispatched in PARALLEL with every
       scraper — the first result of ANY stream is yielded immediately, so
       time-to-first-result is bound by the fastest source, not the sum of
       all of them.

v4 Task 8 — OpenStreetMap is an asymmetric oracle: its failures degrade
    silently (per-scraper pump isolation) and it no longer requires a
    wilaya (country-wide bbox fallback in the scraper itself).

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
from engine.resolver import GraphEntityResolver
from engine.resolution.canonical import CanonicalBuilder
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
        resolution: Optional["ResolutionService"] = None,
    ) -> None:
        self._aggregator = aggregator
        self._repo = repo
        self._analyzer = analyzer or BusinessAnalyzer()
        self._scorer = scorer or LeadScorer()
        self._expander = expander or AlgerianQueryExpander()
        self._resolution = resolution

    # ------------------------------------------------------------------
    async def discover(
        self, query: str, wilaya: Optional[str] = None, limit: int = 30
    ) -> dict:
        campaign_id = await self._repo.create_campaign(query, wilaya, limit)
        created = merged = 0
        created_ids: list[int] = []
        try:
            async for lead in self.stream(query, wilaya, limit):
                lead_id, was_created = await self._repo.upsert(lead)
                if was_created:
                    created += 1
                    if lead_id is not None:
                        created_ids.append(lead_id)
                else:
                    merged += 1
            status = "completed"
        except Exception:
            await self._repo.finish_campaign(campaign_id, "failed", 0, 0, 0)
            raise

        await self._repo.finish_campaign(
            campaign_id, status, created + merged, created, merged
        )

        # Incremental entity resolution: new records join existing
        # entities without re-litigating prior decisions (and without
        # creating duplicate clusters). Failures never fail the campaign.
        resolution_report: Optional[dict] = None
        if created_ids and self._resolution is not None:
            from config.settings import get_settings
            if get_settings().ENTITY_AUTO_RESOLVE:
                try:
                    resolution_report = await self._resolution.resolve_incremental(
                        created_ids
                    )
                except Exception as exc:
                    logger.warning(
                        "post-campaign entity resolution failed: %s", exc
                    )

        return {
            "query": query,
            "wilaya": wilaya,
            "target_limit": limit,
            "saved_count": created,
            "merged_count": merged,
            "campaign_id": campaign_id,
            "entity_resolution": resolution_report,
        }

    # ------------------------------------------------------------------
    async def stream(
        self, query: str, wilaya: Optional[str] = None, limit: int = 30
    ) -> AsyncIterator[Lead]:
        """Audit + score every streamed candidate before yielding it."""
        all_variants = await self._expander.expand(query)
        if not all_variants:
            return

        # v4 Task 11: primary variant + strongest regional counterpart only.
        from config.settings import get_settings
        max_variants = get_settings().DISCOVERY_MAX_VARIANTS
        variants = all_variants[:max_variants]

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

    v4 Task 11: ALL (variant x scraper) streams start simultaneously and
    fan-in through one queue — results are yielded as they arrive from
    whichever source is fastest. Exhaustive pagination per source is
    preserved; variants are capped upstream by ``DiscoveryService``.
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
        if not self._scrapers or not variants:
            return

        seen: set[str] = set()
        yielded = 0
        over_fetch = max(limit * 2, limit + 5)

        queue: asyncio.Queue = asyncio.Queue(maxsize=256)

        async def pump(name: str, stream) -> None:
            try:
                async for lead in stream:
                    await queue.put((name, lead))
            except Exception as exc:  # one scraper failing must not kill the rest
                logger.warning("Scraper %s failed: %s", name, exc)
            finally:
                await queue.put((name, None))

        # Fan-out: every scraper x every variant, all in flight at once.
        pumps = [
            asyncio.create_task(
                pump(scraper.source_name, scraper.stream_discover(
                    variant, wilaya=wilaya, limit=over_fetch
                )),
                name=f"pump-{scraper.source_name}-{i}",
            )
            for i, variant in enumerate(variants)
            for scraper in self._scrapers
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
    """Entity resolution orchestration over the unified leads table.

    Two automated modes:
    - ``resolve_all``: full batch re-resolution of the loaded lead set.
    - ``resolve_incremental``: after a discovery campaign, only pairs
      touching the new records are scored; existing clusters are
      pre-seeded so prior decisions stand and cluster ids stay stable.

    Three human-in-the-loop operations (all logged as manual decisions
    that the engine treats as pinned overrides on every later run):
    - ``split_cluster``: reverse an incorrect merge.
    - ``merge_entities``: combine clusters a human confirms are one.
    - ``resolve_review``: decide an ambiguous pair from the queue.
    """

    def __init__(
        self,
        repo: LeadRepository,
        clusters: ClusterRepository,
        resolver: Optional[GraphEntityResolver] = None,
    ) -> None:
        self._repo = repo
        self._clusters = clusters
        self._resolver = resolver or GraphEntityResolver()

    # ------------------------------------------------------------------
    # Automated resolution
    # ------------------------------------------------------------------
    async def resolve_all(self, batch_size: Optional[int] = None) -> dict:
        from config.settings import get_settings
        limit = batch_size or get_settings().ENTITY_RESOLUTION_BATCH

        leads = await self._repo.all_for_resolution(limit)
        if not leads:
            return {"input_count": 0, "output_count": 0, "clusters_stored": 0,
                    "duration_seconds": 0.0, "engine": "idle"}

        overrides = await self._clusters.manual_overrides()
        import asyncio as _asyncio
        _, result = await _asyncio.to_thread(
            self._resolver.resolve, leads, overrides
        )
        return await self._persist_result(leads, result, mode="batch")

    async def resolve_incremental(self, new_lead_ids: list[int]) -> dict:
        """Re-evaluate entities after new search results arrive.

        Loads the full lead set (for blocking context and cluster
        pre-seeding) but scores only pairs involving the new records;
        persists only the clusters whose membership changed.
        """
        if not new_lead_ids:
            return {"input_count": 0, "output_count": 0, "clusters_stored": 0,
                    "duration_seconds": 0.0, "engine": "idle", "mode": "incremental"}

        from config.settings import get_settings
        limit = get_settings().ENTITY_RESOLUTION_BATCH
        leads = await self._repo.all_for_resolution(limit)
        new_ids = set(new_lead_ids)
        index_by_id = {lead.id: i for i, lead in enumerate(leads) if lead.id is not None}
        new_indices = {index_by_id[i] for i in new_ids if i in index_by_id}

        overrides = await self._clusters.manual_overrides()
        import asyncio as _asyncio
        _, result = await _asyncio.to_thread(
            self._resolver.resolve, leads, overrides, new_indices
        )
        result.mode = "incremental"
        return await self._persist_result(leads, result, mode="incremental")

    # ------------------------------------------------------------------
    async def _persist_result(
        self,
        leads: list[Lead],
        result,
        mode: str,
    ) -> dict:
        """Persist canonical records, relations, decisions, review items."""
        records = result.canonical_records
        group_lead_ids = {
            gi: [leads[i].id for i in group if leads[i].id is not None]
            for gi, group in enumerate(result.groups)
        }
        persisted = await self._clusters.persist(
            records, scope_lead_ids={l.id for l in leads if l.id is not None}
        )

        # Relations: map resolver group indexes to persisted cluster ids
        # through the freshly-written memberships.
        db_relations = []
        if result.relations:
            member_map = await self._clusters.cluster_id_by_lead()
            for rel in result.relations:
                id_a = self._cluster_id_for_group(rel["group_a"], group_lead_ids, member_map)
                id_b = self._cluster_id_for_group(rel["group_b"], group_lead_ids, member_map)
                if id_a is None or id_b is None or id_a == id_b:
                    continue
                db_relations.append({
                    "cluster_a": id_a, "cluster_b": id_b,
                    "relationship": rel["relationship"],
                    "confidence": rel["confidence"],
                    "explanation": rel["explanation"],
                })
            if db_relations:
                await self._clusters.upsert_relations(db_relations)

        # Decision log (explainability): every SAME / RELATED / UNRESOLVED
        # pair plus DISTINCT pairs with similar names ("same name, kept
        # separate" is the explanation users ask for).
        decision_rows = [
            {
                "lead_a": d.a_lead_id, "lead_b": d.b_lead_id,
                "decision": d.decision, "relationship": d.relationship,
                "score": d.score, "signals": d.signals,
                "explanation": d.explanation, "decided_by": d.decided_by,
            }
            for d in result.decisions
            if d.a_lead_id is not None and d.b_lead_id is not None
        ]
        if decision_rows:
            await self._clusters.record_decisions(decision_rows, mode=mode)

        # Review queue (ambiguous pairs).
        if result.review_items:
            await self._clusters.enqueue_review(result.review_items)

        out = result.to_dict()
        out["clusters_stored"] = persisted["stored"]
        out["clusters_inserted"] = persisted["inserted"]
        out["clusters_updated"] = persisted["updated"]
        out["clusters_pruned"] = persisted["pruned"]
        out["relations_stored"] = len(db_relations)
        return out

    @staticmethod
    def _cluster_id_for_group(
        group_index: int,
        group_lead_ids: dict[int, list[int]],
        member_map: dict[int, int],
    ) -> Optional[int]:
        for lead_id in group_lead_ids.get(group_index, []):
            if lead_id in member_map:
                return member_map[lead_id]
        return None

    # ------------------------------------------------------------------
    # Human-in-the-loop operations (reversibility)
    # ------------------------------------------------------------------
    async def split_cluster(
        self, cluster_id: int, groups: list[list[int]]
    ) -> dict:
        """Split a cluster into the given member groups.

        ``groups`` must be a partition of the cluster's current member
        lead ids (every group non-empty). The group containing the
        current canonical lead keeps the cluster id. Every cross-group
        pair is logged as a manual DISTINCT decision so the engine will
        never re-merge them. Source lead rows are never modified.
        """
        current = await self._clusters.member_lead_ids(cluster_id)
        flat = [lid for g in groups for lid in g]
        if not groups or any(not g for g in groups):
            raise ValueError("every split group must be non-empty")
        if sorted(flat) != sorted(current):
            raise ValueError("groups must partition the cluster membership exactly")

        cluster = await self._clusters.get_cluster(cluster_id)
        if not cluster:
            raise ValueError(f"cluster {cluster_id} not found")
        canonical_lead_id = cluster.get("canonical_lead_id")

        # Order groups so the canonical lead's group survives the id.
        if canonical_lead_id is not None:
            groups = sorted(
                groups, key=lambda g: 0 if canonical_lead_id in g else 1
            )

        leads_by_id: dict[int, Lead] = {}
        for lead in await self._repo.get_many(flat):
            leads_by_id[lead.id] = lead

        records = []
        for group in groups:
            members = [leads_by_id[lid] for lid in group if lid in leads_by_id]
            records.append(CanonicalBuilder.build(
                members, {"top_signals": ["manual_split"], "merge_edges": 0}
            ))

        result_ids = await self._clusters.split_cluster(cluster_id, groups, records)

        # Pin the separation: manual DISTINCT for every cross-group pair.
        decisions = []
        for i, gi in enumerate(groups):
            for j in range(i + 1, len(groups)):
                for la in gi:
                    for lb in groups[j]:
                        decisions.append({
                            "lead_a": la, "lead_b": lb,
                            "decision": "distinct", "score": 1.0,
                            "explanation": "manual split of cluster "
                                           f"{cluster_id}",
                            "decided_by": "manual",
                        })
        if decisions:
            await self._clusters.record_decisions(decisions, mode="manual")

        return {
            "ok": True, "cluster_ids": result_ids,
            "source_cluster": cluster_id,
            "groups": groups,
            "pinned_decisions": len(decisions),
        }

    async def merge_entities(self, cluster_ids: list[int]) -> dict:
        """Merge confirmed-duplicate clusters into one canonical entity.

        The lowest cluster id survives (stable for API consumers); the
        others are absorbed, their relations are repointed, and every
        cross-cluster pair is logged as a manual SAME decision.
        """
        if len(cluster_ids) < 2:
            raise ValueError("at least two clusters are required")
        clusters = []
        for cid in cluster_ids:
            c = await self._clusters.get_cluster(cid)
            if not c:
                raise ValueError(f"cluster {cid} not found")
            clusters.append(c)
        cluster_ids = sorted(cluster_ids)
        surviving, absorbed = cluster_ids[0], cluster_ids[1:]

        # Collect memberships BEFORE merging (absorbed rows disappear).
        members_by_cluster: dict[int, list[int]] = {}
        member_ids: list[int] = []
        for cid in cluster_ids:
            members = await self._clusters.member_lead_ids(cid)
            members_by_cluster[cid] = members
            member_ids.extend(members)
        leads = await self._repo.get_many(sorted(set(member_ids)))
        record = CanonicalBuilder.build(
            leads, {"top_signals": ["manual_merge"], "merge_edges": 0}
        )
        record["strategy"] = "manual_merge"

        await self._clusters.merge_clusters(surviving, absorbed, record)

        decisions = []
        survivor_members = set(members_by_cluster[surviving])
        for cid in absorbed:
            for la in members_by_cluster[cid]:
                for lb in survivor_members:
                    decisions.append({
                        "lead_a": la, "lead_b": lb,
                        "decision": "same", "score": 1.0,
                        "explanation": f"manual merge of clusters "
                                       f"{surviving}+{cid}",
                        "decided_by": "manual",
                    })
        if decisions:
            await self._clusters.record_decisions(decisions, mode="manual")

        return {
            "ok": True, "cluster_id": surviving, "absorbed": absorbed,
            "member_count": len(leads), "pinned_decisions": len(decisions),
        }

    async def resolve_review(self, item_id: int, decision: str) -> dict:
        """Decide an ambiguous pair: 'merge' or 'keep_separate'."""
        item = await self._clusters.get_review_item(item_id)
        if not item:
            raise ValueError(f"review item {item_id} not found")
        if item["status"] != "pending":
            raise ValueError(f"review item {item_id} is already resolved")

        if decision == "merge":
            merged = await self._merge_pair(item["lead_a"], item["lead_b"])
            await self._clusters.resolve_review(item_id, "merged")
            return {"ok": True, "action": "merged", **merged}
        if decision == "keep_separate":
            await self._clusters.record_decisions([{
                "lead_a": item["lead_a"], "lead_b": item["lead_b"],
                "decision": "distinct", "score": 1.0,
                "explanation": "review resolution: kept separate",
                "decided_by": "manual",
            }], mode="manual")
            await self._clusters.resolve_review(item_id, "kept_separate")
            return {"ok": True, "action": "kept_separate"}
        if decision == "dismiss":
            await self._clusters.resolve_review(item_id, "dismissed")
            return {"ok": True, "action": "dismissed"}
        raise ValueError("decision must be merge | keep_separate | dismiss")

    async def _merge_pair(self, lead_a: int, lead_b: int) -> dict:
        """Put two leads into one cluster (merging their clusters if both
        are already clustered)."""
        leads = await self._repo.get_many([lead_a, lead_b])
        if len(leads) != 2:
            raise ValueError("both leads must exist")
        cluster_ids = {l.cluster_id for l in leads if l.cluster_id is not None}

        if len(cluster_ids) == 1:
            cid = cluster_ids.pop()
            unclustered = [l for l in leads if l.cluster_id is None]
            if unclustered:
                members = await self._clusters.member_lead_ids(cid)
                all_leads = await self._repo.get_many(
                    sorted(set(members) | {l.id for l in unclustered})
                )
                record = CanonicalBuilder.build(
                    all_leads, {"top_signals": ["review_merge"], "merge_edges": 0}
                )
                await self._clusters.persist([record], scope_lead_ids=set(members))
                return {"cluster_id": cid}
            return {"cluster_id": cid}

        if len(cluster_ids) == 2:
            return await self.merge_entities(sorted(cluster_ids))

        # Neither lead is clustered: create a fresh two-member cluster.
        record = CanonicalBuilder.build(
            leads, {"top_signals": ["review_merge"], "merge_edges": 0}
        )
        record["strategy"] = "manual_merge"
        await self._clusters.persist(
            [record], scope_lead_ids={lead_a, lead_b}
        )
        member_map = await self._clusters.cluster_id_by_lead()
        return {"cluster_id": member_map.get(lead_a)}

    async def review_queue(self, limit: int = 50) -> list[dict]:
        return await self._clusters.list_review(status="pending", limit=limit)

    async def pending_review_count(self) -> int:
        return await self._clusters.count_pending_review()
