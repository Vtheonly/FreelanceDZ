"""Graph-based entity resolver.

The resolver treats each raw record as a node in a graph. Edges are
added between two nodes when their composite similarity score exceeds a
threshold. Connected components in the resulting graph are clusters of
duplicate records that should be merged into a single golden entity.

Pipeline
--------
1. **Blocking** — trigram blocking groups records into candidate pairs
   so we don't do O(N²) comparisons.
2. **Edge construction** — for each candidate pair, compute a weighted
   composite score (name + website + phone + email) and add an edge if
   the score exceeds ``composite_threshold``.
3. **Connected components** — BFS/DFS to find every cluster.
4. **Merge** — for each cluster, run ``GoldenRecordMerger`` to produce
   the final ``ResolvedEntity``.

The resolver is async to match the ``IEntityResolver`` contract, but
the heavy lifting is CPU-bound and runs in a thread pool via
``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Optional

from config.settings import get_settings
from core.constants import DEFAULT_ENTITY_WEIGHTS
from core.interfaces import IEntityResolver
from domain.models import RawRecord, ResolvedEntity
from infrastructure.entity_resolution.blocking import TrigramBlocker
from infrastructure.entity_resolution.merger import GoldenRecordMerger
from infrastructure.entity_resolution.similarity import (
    jaccard_similarity,
    levenshtein_ratio,
)


_logger = logging.getLogger("entity_resolution.graph_resolver")


class GraphEntityResolver(IEntityResolver):
    """Async graph-based entity resolver with trigram blocking."""

    def __init__(
        self,
        name_threshold: Optional[float] = None,
        composite_threshold: Optional[float] = None,
        weights: Optional[dict[str, float]] = None,
        max_block_size: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self._name_threshold = name_threshold or settings.ENTITY_NAME_THRESHOLD
        self._composite_threshold = composite_threshold or settings.ENTITY_COMPOSITE_THRESHOLD
        self._weights = weights or DEFAULT_ENTITY_WEIGHTS
        self._blocker = TrigramBlocker(
            max_block_size=max_block_size or settings.ENTITY_MAX_BLOCK_SIZE
        )
        self._merger = GoldenRecordMerger()

    async def resolve(self, records: list[RawRecord]) -> list[ResolvedEntity]:
        if not records:
            return []
        if len(records) == 1:
            return [self._merger.merge(records)]

        _logger.info("Resolving %d raw records...", len(records))
        # Run the CPU-bound work in a thread so we don't block the event loop.
        entities = await asyncio.to_thread(self._resolve_sync, records)
        _logger.info(
            "Resolution complete: %d records → %d entities (compression ratio: %.2fx)",
            len(records), len(entities),
            len(records) / max(len(entities), 1),
        )
        return entities

    # ------------------------------------------------------------------
    #  Synchronous implementation (offloaded to a thread)
    # ------------------------------------------------------------------

    def _resolve_sync(self, records: list[RawRecord]) -> list[ResolvedEntity]:
        projections = [r.to_resolver_dict() | {"id": r.id} for r in records]
        candidate_pairs = self._blocker.candidate_pairs(projections)

        adjacency: dict[int, set[int]] = defaultdict(set)
        for i, j in candidate_pairs:
            score, _ = self._match_score(projections[i], projections[j])
            if score >= self._composite_threshold:
                adjacency[i].add(j)
                adjacency[j].add(i)

        # Find connected components via BFS.
        visited = [False] * len(records)
        entities: list[ResolvedEntity] = []
        for start in range(len(records)):
            if visited[start]:
                continue
            component = self._bfs(start, adjacency, visited)
            cluster = [records[idx] for idx in component]
            entities.append(self._merger.merge(cluster))
        return entities

    def _bfs(
        self,
        start: int,
        adjacency: dict[int, set[int]],
        visited: list[bool],
    ) -> list[int]:
        queue = [start]
        visited[start] = True
        component: list[int] = []
        while queue:
            current = queue.pop(0)
            component.append(current)
            for neighbor in adjacency.get(current, ()):
                if not visited[neighbor]:
                    visited[neighbor] = True
                    queue.append(neighbor)
        return component

    def _match_score(self, r1: dict[str, Any], r2: dict[str, Any]) -> tuple[float, list[str]]:
        """Return ``(composite_score, reasons)`` for a pair of records.

        Missing-data handling: when both records lack a given attribute
        (e.g., neither has a phone), that attribute contributes its full
        weight as a *neutral* score (0.5) rather than 0.0. This prevents
        two records of the same business from being scored low just
        because the scraper couldn't find a phone on one of them.
        """
        reasons: list[str] = []
        scores: dict[str, float] = {}

        # 1. Name similarity (Levenshtein).
        name_score = levenshtein_ratio(
            str(r1.get("name", "")), str(r2.get("name", ""))
        )
        scores["name"] = name_score
        if name_score >= self._name_threshold:
            reasons.append(f"name:{name_score:.2f}")

        # 2. Website exact match (normalised).
        w1 = _normalise_web(r1.get("website"))
        w2 = _normalise_web(r2.get("website"))
        if w1 and w2:
            web_score = 1.0 if w1 == w2 else 0.0
        elif not w1 and not w2:
            web_score = 0.5  # both missing → neutral
        else:
            web_score = 0.0  # one has, one doesn't → mild negative
        scores["website"] = web_score
        if web_score > 0.9:
            reasons.append("website:exact")

        # 3. Phone set overlap (Jaccard) with missing-data handling.
        p1 = set(r1.get("phones") or [])
        p2 = set(r2.get("phones") or [])
        if p1 and p2:
            phone_score = jaccard_similarity(p1, p2)
        elif not p1 and not p2:
            phone_score = 0.5  # both missing → neutral
        else:
            phone_score = 0.3  # one missing → mildly negative (not 0)
        scores["phone"] = phone_score
        if phone_score > 0.0:
            reasons.append(f"phone:{phone_score:.2f}")

        # 4. Email exact match.
        em1 = (r1.get("email") or "").lower().strip()
        em2 = (r2.get("email") or "").lower().strip()
        if em1 and em2:
            email_score = 1.0 if em1 == em2 else 0.0
        elif not em1 and not em2:
            email_score = 0.5  # both missing → neutral
        else:
            email_score = 0.0
        scores["email"] = email_score
        if email_score > 0.9:
            reasons.append("email:exact")

        composite = sum(scores.get(k, 0.0) * self._weights.get(k, 0.0) for k in self._weights)
        return composite, reasons


def _normalise_web(url: str | None) -> str:
    if not url:
        return ""
    return (
        url.lower()
        .replace("https://", "")
        .replace("http://", "")
        .replace("www.", "")
        .strip("/")
    )
