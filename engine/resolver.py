"""Entity resolution: trigram blocking -> native pair matching -> DSU -> merge.

Combines the strongest ideas across iterations:
    - v2.0.0: trigram blocking with size caps, composite scoring
      (name/website/phone/email weights), connected components.
    - v3 native core: one batched C call computes the expensive part —
      bitset-Jaccard prefilter + Myers Levenshtein verification — for all
      candidate pairs, with a pure-Python fallback that is bit-identical.

Non-destructive: resolution writes cluster metadata (entity_clusters +
entity_links + leads.cluster_id) and never mutates or deletes lead rows.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from config.settings import get_settings
from domain.models import Lead
from engine.native import NativeEngine

logger = logging.getLogger("engine.resolver")

# Composite weights (domain rules; see core decision record).
WEIGHT_NAME = 0.40
WEIGHT_WEBSITE = 0.25
WEIGHT_PHONE = 0.20
WEIGHT_EMAIL = 0.15


@dataclass
class ResolutionReport:
    input_count: int = 0
    output_count: int = 0
    candidate_pairs: int = 0
    edges: int = 0
    duration_seconds: float = 0.0
    engine: str = "python-fallback"

    @property
    def compression_ratio(self) -> float:
        if self.input_count == 0:
            return 0.0
        return round(1.0 - (self.output_count / self.input_count), 4)

    def to_dict(self) -> dict:
        return {
            "input_count": self.input_count,
            "output_count": self.output_count,
            "candidate_pairs": self.candidate_pairs,
            "edges": self.edges,
            "duration_seconds": round(self.duration_seconds, 4),
            "engine": self.engine,
            "compression_ratio": self.compression_ratio,
        }


@dataclass
class _Member:
    lead: Lead
    norm_name: str
    phones: set[str]


def _normalise_name(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _phone_set(lead: Lead) -> set[str]:
    """Digit-only phone set from structured details or the raw string.

    Both sources normalize to digits-only so '+213550123456' and
    '0550123456'-style national forms compare consistently.
    """
    numbers: set[str] = set()
    for p in lead.phone_details:
        if p.e164:
            digits = "".join(ch for ch in p.e164 if ch.isdigit())
            if digits:
                numbers.add(digits)
    if not numbers and lead.phone:
        digits = "".join(ch for ch in lead.phone if ch.isdigit())
        if digits:
            numbers.add(digits)
    return numbers


def _normalise_website(url: Optional[str]) -> str:
    if not url:
        return ""
    w = url.lower()
    for prefix in ("https://", "http://"):
        if w.startswith(prefix):
            w = w[len(prefix):]
    if w.startswith("www."):
        w = w[4:]
    return w.rstrip("/")


def _trigrams(name: str) -> set[str]:
    return {name[i:i + 3] for i in range(max(0, len(name) - 2))}


class GraphEntityResolver:
    """Blocking + composite scoring + connected components."""

    def __init__(
        self,
        composite_threshold: Optional[float] = None,
        max_block_size: Optional[int] = None,
        jaccard_prefilter: Optional[float] = None,
        native: Optional[NativeEngine] = None,
    ) -> None:
        settings = get_settings()
        self._threshold = composite_threshold or settings.ENTITY_COMPOSITE_THRESHOLD
        self._max_block = max_block_size or settings.ENTITY_MAX_BLOCK_SIZE
        self._prefilter = jaccard_prefilter or settings.ENTITY_JACCARD_PREFILTER
        self._native = native or NativeEngine.get()

    def resolve(self, leads: list[Lead]) -> tuple[list[list[int]], ResolutionReport]:
        """Group lead list-indices into clusters. Returns (clusters, report).

        clusters is a list of index-groups into the input list; singletons
        included (as single-member groups are skipped for merge but counted).
        """
        started = time.monotonic()
        report = ResolutionReport(
            input_count=len(leads),
            engine="native-simd" if self._native.is_native else "python-fallback",
        )
        if len(leads) < 2:
            report.duration_seconds = time.monotonic() - started
            return [[i] for i in range(len(leads))], report

        members = [
            _Member(
                lead=lead,
                norm_name=_normalise_name(lead.name or ""),
                phones=_phone_set(lead),
            )
            for lead in leads
        ]

        # ---------------- blocking (trigram inverted index) -----------------
        blocks: dict[str, list[int]] = {}
        for idx, m in enumerate(members):
            if len(m.norm_name) < 3:
                blocks.setdefault("__short__", []).append(idx)
                continue
            for tri in _trigrams(m.norm_name):
                blocks.setdefault(tri, []).append(idx)

        pair_set: set[tuple[int, int]] = set()
        for block in blocks.values():
            if len(block) < 2 or len(block) > self._max_block:
                continue  # singleton or canopy too broad to be informative
            for i_pos in range(len(block)):
                a = block[i_pos]
                for j_pos in range(i_pos + 1, len(block)):
                    b = block[j_pos]
                    pair_set.add((a, b) if a < b else (b, a))
        pairs = sorted(pair_set)
        report.candidate_pairs = len(pairs)

        # ---------------- native batched name similarity --------------------
        name_scores = [0.0] * len(pairs)
        if pairs:
            self._native.names_reset(len(members))
            self._native.names_add_many([m.norm_name for m in members])
            name_scores = self._native.names_match_pairs(
                pairs, self._prefilter, 0.0  # threshold applied in composite
            )

        # ---------------- composite scoring + edges --------------------------
        parent = list(range(len(members)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        edges = 0
        for (ia, ib), name_sim in zip(pairs, name_scores):
            if name_sim <= 0.0:
                continue
            ma, mb = members[ia], members[ib]
            composite = self._composite(ma, mb, name_sim)
            if composite >= self._threshold:
                union(ia, ib)
                edges += 1
        report.edges = edges

        # ---------------- components ----------------------------------------
        groups: dict[int, list[int]] = {}
        for idx in range(len(members)):
            groups.setdefault(find(idx), []).append(idx)
        clusters = sorted(groups.values(), key=lambda g: g[0])
        report.output_count = len(clusters)
        report.duration_seconds = time.monotonic() - started
        return clusters, report

    # ------------------------------------------------------------------
    def _composite(self, a: _Member, b: _Member, name_sim: float) -> float:
        # Website
        wa, wb = _normalise_website(a.lead.website), _normalise_website(b.lead.website)
        if wa and wb:
            website_score = 1.0 if wa == wb else 0.0
        elif not wa and not wb:
            website_score = 0.5   # neutral: no evidence either way
        else:
            website_score = 0.0

        # Phones (Jaccard over E.164 sets)
        pa, pb = a.phones, b.phones
        if pa and pb:
            phone_score = len(pa & pb) / len(pa | pb)
        elif not pa and not pb:
            phone_score = 0.5
        else:
            phone_score = 0.3    # one side has contact info, other doesn't

        # Email
        ea = (a.lead.email or "").lower()
        eb = (b.lead.email or "").lower()
        if ea and eb:
            email_score = 1.0 if ea == eb else 0.0
        elif not ea and not eb:
            email_score = 0.5
        else:
            email_score = 0.0

        # Wilaya guard: identical names in different wilayas are usually
        # distinct businesses (chains excepted — exact phone/website matches
        # still dominate). Halve the name evidence on a known mismatch.
        effective_name = name_sim
        wa_city = (a.lead.wilaya or "").strip().lower()
        wb_city = (b.lead.wilaya or "").strip().lower()
        if wa_city and wb_city and wa_city != wb_city:
            effective_name = name_sim * 0.5

        return (
            effective_name * WEIGHT_NAME
            + website_score * WEIGHT_WEBSITE
            + phone_score * WEIGHT_PHONE
            + email_score * WEIGHT_EMAIL
        )


class GoldenRecordBuilder:
    """Builds cluster records from grouped leads (most-complete member wins)."""

    @staticmethod
    def build(leads: list[Lead]) -> dict:
        """Return the cluster summary dict for ClusterRepository.replace_all."""
        if not leads:
            return {}

        def completeness(lead: Lead) -> int:
            return (
                sum(1 for v in (lead.address, lead.website, lead.phone, lead.email) if v)
                + len(lead.social_links)
                + len(lead.phone_details)
            )

        canonical = max(leads, key=completeness)
        confidence = min(0.99, 0.70 + 0.10 * len(leads)) if len(leads) > 1 else 1.0
        return {
            "canonical_lead_id": canonical.id,
            "name": canonical.name,
            "industry": canonical.industry,
            "wilaya": canonical.wilaya,
            "confidence": round(confidence, 3),
            "strategy": "graph_merge" if len(leads) > 1 else "single",
            "members": [l.id for l in leads if l.id is not None],
            "reasons": ["name_similarity", "channel_overlap"] if len(leads) > 1 else [],
        }
