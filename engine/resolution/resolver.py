"""Entity resolver orchestrator: the full v3.1 pipeline over a lead set.

    leads -> features -> blocking -> batched name similarity (rapidfuzz)
          -> evidence scoring -> classification (+ manual overrides)
          -> constrained clustering (existing clusters pre-seeded)
          -> canonical records + relations + review queue + decision log

Two modes share one code path:

- **Batch** (``new_indices=None``): every candidate pair is scored.
  Used by POST /entities/resolve and the CLI.
- **Incremental** (``new_indices={...}``): only pairs involving at least
  one new record are scored; existing cluster structure is pre-seeded
  into the clusterer from ``lead.cluster_id`` so prior decisions are
  never re-litigated and cluster ids stay stable. Used automatically
  after every discovery campaign.

Manual overrides (from human splits, merges and review resolutions)
enter ahead of the classifier: a pinned "same" forces the merge edge, a
pinned "distinct" forces separation AND suppresses relations — the
engine is not allowed to undo a human decision on a later run.

Name similarity uses ``engine.fastops.NameMatcher`` (bit-set prefilter +
rapidfuzz Levenshtein, one pass over candidate pairs) and combines it
with token-set Jaccard: ``max(levenshtein_ratio, token_jaccard)`` so
"Café Atlas" vs "Café Atlas Restaurant" and "Pharmacie Centrale" vs
"Pharmacie Central" both score as the variants they are. A sentinel
name is registered for records whose normalized name is empty: the
matcher skips empty strings, which would silently shift every later
index (latent v3.0 bug, now impossible).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from config.settings import get_settings
from domain.models import Lead
from engine.fastops import NameMatcher
from engine.resolution.blocking import build_candidate_pairs
from engine.resolution.canonical import CanonicalBuilder
from engine.resolution.classifier import (
    DISTINCT,
    RELATED,
    SAME,
    UNRESOLVED,
    Decision,
    MatchClassifier,
)
from engine.resolution.clustering import ConstraintClusterer
from engine.resolution.features import RecordFeatures, extract_features
from engine.resolution.scoring import EvidenceScorer, PairEvidence

# Registered for records whose normalized name is empty (see module doc).
_NAME_SENTINEL = "\x00"

# DISTINCT decisions with at least this name similarity are persisted to
# the decision log: "same name, kept separate" is the explanation users
# ask for (the Café Atlas Algiers/Oran case). Low-similarity distinct
# pairs are the common case and are summarized in counts only.
_LOG_DISTINCT_NAME_SIM = 0.75


@dataclass
class ResolutionResult:
    """Everything one resolve run produced."""

    # v3.0 report fields (compat: attributes + to_dict keys).
    input_count: int = 0
    output_count: int = 0
    candidate_pairs: int = 0
    edges: int = 0
    duration_seconds: float = 0.0
    engine: str = "python-fallback"
    mode: str = "batch"

    # v3.1 additions.
    decisions_same: int = 0
    decisions_related: int = 0
    decisions_distinct: int = 0
    decisions_unresolved: int = 0
    edges_skipped: int = 0
    contradictions: list[dict] = field(default_factory=list)
    review_queued: int = 0
    blocking: dict[str, int] = field(default_factory=dict)
    affected_groups: list[int] = field(default_factory=list)  # group indexes

    # Payload the service persists.
    groups: list[list[int]] = field(default_factory=list)      # index groups
    decisions: list[Decision] = field(default_factory=list)    # log-worthy
    relations: list[dict] = field(default_factory=list)        # group-to-group
    review_items: list[dict] = field(default_factory=list)
    canonical_records: list[dict] = field(default_factory=list)

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
            "mode": self.mode,
            "decisions": {
                "same": self.decisions_same,
                "related": self.decisions_related,
                "distinct": self.decisions_distinct,
                "unresolved": self.decisions_unresolved,
            },
            "edges_skipped": self.edges_skipped,
            "contradictions": len(self.contradictions),
            "review_queued": self.review_queued,
            "blocking": self.blocking,
        }


class EntityResolver:
    """The v3.1 entity-resolution pipeline."""

    def __init__(
        self,
        matcher: Optional[NameMatcher] = None,
        max_block_size: Optional[int] = None,
        jaccard_prefilter: Optional[float] = None,
        classifier: Optional[MatchClassifier] = None,
    ) -> None:
        settings = get_settings()
        self._matcher = matcher or NameMatcher()
        self._max_block = max_block_size or settings.ENTITY_MAX_BLOCK_SIZE
        self._prefilter = jaccard_prefilter or settings.ENTITY_JACCARD_PREFILTER
        self._classifier = classifier or MatchClassifier()
        self._scorer = EvidenceScorer()

    # ------------------------------------------------------------------
    def resolve(
        self,
        leads: list[Lead],
        manual_overrides: Optional[list[dict]] = None,
        new_indices: Optional[set[int]] = None,
    ) -> tuple[list[list[int]], ResolutionResult]:
        """Group lead indices into canonical entities.

        ``manual_overrides``: [{lead_a, lead_b, decision: same|distinct}]
        (latest human decisions, loaded by the service).
        ``new_indices``: indices of newly-arrived records — incremental
        mode scores only pairs touching them and pre-seeds existing
        clusters from ``lead.cluster_id``.
        """
        started = time.monotonic()
        mode = "incremental" if new_indices is not None else "batch"
        result = ResolutionResult(
            input_count=len(leads),
            engine="fastops-python",
            mode=mode,
        )
        if len(leads) < 2:
            result.groups = [[i] for i in range(len(leads))]
            result.output_count = len(leads)
            result.duration_seconds = time.monotonic() - started
            return result.groups, result

        features = [extract_features(i, lead) for i, lead in enumerate(leads)]

        # ---------------- candidate generation --------------------------
        pairs, kind_counts = build_candidate_pairs(features, self._max_block)
        if new_indices is not None:
            pairs = [p for p in pairs if p[0] in new_indices or p[1] in new_indices]
        result.candidate_pairs = len(pairs)
        result.blocking = kind_counts

        # ---------------- name similarity (batched matcher) -------------
        name_sims: list[float] = []
        if pairs:
            self._matcher.reset(len(features))
            self._matcher.add_many([f.name_k or _NAME_SENTINEL for f in features])
            raw_sims = self._matcher.match_pairs(
                pairs, self._prefilter, 0.0
            )
            for (ia, ib), sim in zip(pairs, raw_sims):
                tok = _token_jaccard(features[ia].tokens, features[ib].tokens)
                name_sims.append(max(sim, tok))

        # ---------------- evidence + classification ---------------------
        evidences: list[PairEvidence] = []
        decisions: list[Decision] = []
        override_map = self._override_index(manual_overrides, features)

        for pair, name_sim in zip(pairs, name_sims):
            ev = self._scorer.score(
                features[pair[0]], features[pair[1]], name_sim, pair
            )
            evidences.append(ev)
            decision = self._classifier.classify(ev)
            override = override_map.get(pair)
            if override is not None:
                decision = override
            decisions.append(decision)

        ev_by_pair = {(ev.a_index, ev.b_index): ev for ev in evidences}
        decisions_by_pair = {(d.a_index, d.b_index): d for d in decisions}

        result.decisions_same = sum(1 for d in decisions if d.decision == SAME)
        result.decisions_related = sum(1 for d in decisions if d.decision == RELATED)
        result.decisions_distinct = sum(1 for d in decisions if d.decision == DISTINCT)
        result.decisions_unresolved = sum(1 for d in decisions if d.decision == UNRESOLVED)

        # ---------------- constrained clustering ------------------------
        clusterer = ConstraintClusterer()

        # Pre-seed existing cluster structure (incremental mode): prior
        # merges are ground truth until a human splits them.
        if new_indices is not None:
            by_cluster: dict[int, list[int]] = {}
            for f in features:
                if f.lead.cluster_id is not None and f.index not in new_indices:
                    by_cluster.setdefault(f.lead.cluster_id, []).append(f.index)
            for members in by_cluster.values():
                for other in members[1:]:
                    clusterer.pin_same(members[0], other)

        # Manual pins.
        for pair, override in override_map.items():
            if override.decision == SAME:
                clusterer.pin_same(pair[0], pair[1])
            else:  # manual distinct
                clusterer.add_must_not_link(pair[0], pair[1])

        cluster_result = clusterer.cluster(decisions, evidences)
        result.groups = cluster_result.groups
        result.edges = cluster_result.edges_applied
        result.edges_skipped = cluster_result.edges_skipped
        result.contradictions = cluster_result.contradictions
        result.output_count = len(cluster_result.groups)

        # ---------------- group index map + affected groups --------------
        group_of: dict[int, int] = {}
        for gi, group in enumerate(result.groups):
            for idx in group:
                group_of[idx] = gi
        if new_indices is not None:
            affected = {group_of[i] for i in new_indices if i in group_of}
        else:
            affected = set(range(len(result.groups)))
        result.affected_groups = sorted(affected)

        # ---------------- relations (group-to-group) ----------------------
        relations: list[dict] = []
        relation_groups: set[int] = set()
        for d in decisions:
            if d.decision != RELATED:
                continue
            ga, gb = group_of.get(d.a_index), group_of.get(d.b_index)
            if ga is None or gb is None or ga == gb:
                continue
            ev = ev_by_pair.get((d.a_index, d.b_index))
            relations.append({
                "group_a": ga,
                "group_b": gb,
                "relationship": d.relationship,
                "confidence": round(min(0.95, 0.5 + (ev.org if ev else 0.0) / 4), 3),
                "explanation": d.explanation,
            })
            relation_groups.update((ga, gb))
        result.relations = _dedupe_relations(relations)

        # ---------------- review queue ------------------------------------
        review_items = []
        for d, ev in zip(decisions, evidences):
            if d.decision != UNRESOLVED:
                continue
            if new_indices is not None and not (
                d.a_index in new_indices or d.b_index in new_indices
            ):
                continue
            review_items.append({
                "lead_a": d.a_lead_id,
                "lead_b": d.b_lead_id,
                "score": d.score,
                "evidence": ev.to_dict(),
                "explanation": d.explanation,
            })
        result.review_items = review_items
        result.review_queued = len(review_items)

        # ---------------- canonical records --------------------------------
        all_group_evidence = self._all_group_evidence(
            group_of, decisions_by_pair, evidences
        )
        records = []
        for gi, group in enumerate(result.groups):
            multi = len(group) > 1
            in_relation = gi in relation_groups
            if not (multi or in_relation):
                continue  # plain singletons are not stored (v3.0 semantics)
            if new_indices is not None and gi not in affected and not in_relation:
                continue  # untouched by this incremental run
            members = [leads[i] for i in group]
            group_evidence = all_group_evidence.get(gi) or {
                "min_edge_identity": None, "avg_edge_identity": None,
                "merge_edges": 0, "top_signals": [],
            }
            record = CanonicalBuilder.build(members, group_evidence)
            record["group_index"] = gi
            records.append(record)
        result.canonical_records = records

        # ---------------- decision log (explainability) --------------------
        logged = []
        for d in decisions:
            if d.decision in (SAME, RELATED, UNRESOLVED):
                d.signals = ev_by_pair.get((d.a_index, d.b_index),
                                           PairEvidence(d.a_index, d.b_index,
                                                        d.a_lead_id, d.b_lead_id)).to_dict()
                logged.append(d)
            elif d.decision == DISTINCT:
                ev = ev_by_pair.get((d.a_index, d.b_index))
                if ev is not None and ev.name_sim >= _LOG_DISTINCT_NAME_SIM:
                    d.signals = ev.to_dict()
                    logged.append(d)
        result.decisions = logged

        result.duration_seconds = time.monotonic() - started
        return result.groups, result

    # ------------------------------------------------------------------
    @staticmethod
    def _override_index(
        manual_overrides: Optional[list[dict]], features: list[RecordFeatures]
    ) -> dict[tuple[int, int], Decision]:
        """Map manual override lead-id pairs to batch indices."""
        if not manual_overrides:
            return {}
        index_by_lead: dict[int, int] = {}
        for f in features:
            if f.lead_id is not None:
                index_by_lead[f.lead_id] = f.index
        overrides: dict[tuple[int, int], Decision] = {}
        for o in manual_overrides:
            a, b = index_by_lead.get(o.get("lead_a")), index_by_lead.get(o.get("lead_b"))
            decision_value = o.get("decision")
            if a is None or b is None or a == b or decision_value not in (SAME, DISTINCT):
                continue
            pair = (min(a, b), max(a, b))
            overrides[pair] = Decision(
                a_index=pair[0], b_index=pair[1],
                a_lead_id=features[pair[0]].lead_id,
                b_lead_id=features[pair[1]].lead_id,
                decision=decision_value,
                score=1.0,
                decided_by="manual",
                explanation="manual decision (split, merge, or review resolution)",
            )
        return overrides

    @staticmethod
    def _all_group_evidence(
        group_of: dict[int, int],
        decisions_by_pair: dict[tuple[int, int], Decision],
        evidences: list[PairEvidence],
    ) -> dict[int, dict]:
        """Per-group evidence for every group in one pass over the pairs
        (the per-group scan was O(groups x pairs) and a measured hotspot
        on 100k+ candidate corpora)."""
        stats: dict[int, dict] = {}
        for ev in evidences:
            d = decisions_by_pair.get((ev.a_index, ev.b_index))
            if d is None or d.decision != SAME:
                continue
            gi = group_of.get(ev.a_index)
            if gi is None or group_of.get(ev.b_index) != gi:
                continue
            s = stats.setdefault(gi, {
                "identity": [], "signals": {},
            })
            s["identity"].append(ev.identity)
            for sig in ev.signals:
                if sig.identity > 0 or sig.org > 0:
                    s["signals"][sig.signal] = s["signals"].get(sig.signal, 0) + 1
        out: dict[int, dict] = {}
        for gi, s in stats.items():
            identities = s["identity"]
            top = sorted(s["signals"].items(), key=lambda kv: -kv[1])
            out[gi] = {
                "min_edge_identity": round(min(identities), 3),
                "avg_edge_identity": round(sum(identities) / len(identities), 3),
                "merge_edges": len(identities),
                "top_signals": [name for name, _ in top],
            }
        return out


def _token_jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _dedupe_relations(relations: list[dict]) -> list[dict]:
    """Collapse duplicate group-pair relations, keeping the highest
    confidence and its explanation."""
    best: dict[tuple[int, int, str], dict] = {}
    for rel in relations:
        key = (min(rel["group_a"], rel["group_b"]),
               max(rel["group_a"], rel["group_b"]),
               rel["relationship"])
        if key not in best or rel["confidence"] > best[key]["confidence"]:
            best[key] = rel
    return sorted(best.values(), key=lambda r: (r["group_a"], r["group_b"]))
