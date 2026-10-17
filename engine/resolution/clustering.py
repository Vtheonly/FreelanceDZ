"""Constrained clustering: SAME decisions -> canonical entity groups.

A plain union-find (v3.0) silently absorbs two failure modes this
clusterer explicitly guards against:

1. **Transitive drift.** A~B and B~C merge A and C even when A and C were
   never compared, or were compared and scored DISTINCT. Every edge here
   carries a tier: ``strong`` edges are backed by a contact identifier
   (phone / social handle / cross reference / exact email) and may carry
   transitive merges; ``weak`` edges (location-only identity, e.g. same
   address with no contact corroboration) merge only their direct pair —
   they never chain through a component to merge records that were not
   themselves compared.

2. **Contradictory merges.** Pairs classified DISTINCT with strong
   disagreement (conflict >= 1.0) are registered as *must-not-link*
   constraints. Before any union, the clusterer checks whether the merged
   component would contain a must-not-link pair; if so the edge is
   dropped and the contradiction is logged (visible in the report and
   persisted to the decision log), and the higher-confidence edges that
   were applied first win.

Manual overrides (from splits and merges performed by a human through
the API) enter as pinned edges / pinned must-not-links that outrank
everything the engine derives.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.resolution.classifier import SAME, DISTINCT, Decision
from engine.resolution.scoring import PairEvidence

STRONG_CONFLICT_BAR = 1.0   # DISTINCT conflict magnitude -> must-not-link


@dataclass(slots=True)
class ClusterEdge:
    """A SAME decision promoted to a clustering edge."""

    a_index: int
    b_index: int
    score: float
    strong: bool       # backed by a contact identifier -> may transit
    evidence: dict     # for the decision log

    @property
    def pair(self) -> tuple[int, int]:
        return (self.a_index, self.b_index)


@dataclass(slots=True)
class ClusterResult:
    """Output of the clusterer over one resolve run."""

    groups: list[list[int]]                      # index groups, sorted
    edges_applied: int = 0
    edges_skipped: int = 0
    contradictions: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "edges_applied": self.edges_applied,
            "edges_skipped": self.edges_skipped,
            "contradictions": self.contradictions,
        }


class ConstraintClusterer:
    """Union-find with must-not-link constraints and edge tiers."""

    def __init__(self) -> None:
        self._parent: dict[int, int] = {}
        self._members: dict[int, list[int]] = {}
        self._forbidden: set[tuple[int, int]] = set()   # must-not-link pairs

    # ------------------------------------------------------------------
    def _find(self, x: int) -> int:
        parent = self._parent
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:      # path compression
            parent[x], x = root, parent[x]
        return root

    def _component(self, x: int) -> list[int]:
        return self._members.setdefault(self._find(x), [x])

    def _register(self, x: int) -> None:
        if x not in self._parent:
            self._parent[x] = x
            self._members[x] = [x]

    def _would_violate(self, a: int, b: int) -> tuple[int, int] | None:
        """Return the must-not-link pair that a union of a and b would
        place in one component, if any."""
        comp_a = set(self._component(a)) | {a}
        comp_b = set(self._component(b)) | {b}
        for x in comp_a:
            for y in comp_b:
                if (min(x, y), max(x, y)) in self._forbidden:
                    return (min(x, y), max(x, y))
        return None

    def _union(self, a: int, b: int) -> None:
        ra, rb = self._find(a), self._find(b)
        if ra == rb:
            return
        # Merge smaller into larger, keep member lists concatenated.
        if len(self._members.get(ra, [ra])) < len(self._members.get(rb, [rb])):
            ra, rb = rb, ra
        self._parent[rb] = ra
        merged = self._members.get(ra, [ra]) + self._members.get(rb, [rb])
        self._members[ra] = merged
        self._members.pop(rb, None)

    # ------------------------------------------------------------------
    def add_must_not_link(self, a: int, b: int) -> None:
        self._register(a)
        self._register(b)
        self._forbidden.add((min(a, b), max(a, b)))

    def pin_same(self, a: int, b: int) -> None:
        """Manual merge override: union unconditionally (a human decided)."""
        self._register(a)
        self._register(b)
        self._union(a, b)

    # ------------------------------------------------------------------
    def cluster(
        self,
        decisions: list[Decision],
        evidences: list[PairEvidence],
    ) -> ClusterResult:
        """Apply SAME decisions (score-descending) under constraints.

        DISTINCT decisions whose conflict magnitude clears
        ``STRONG_CONFLICT_BAR`` become must-not-link constraints first,
        so a strong disagreement discovered early can veto a later,
        weaker agreement — regardless of decision ordering.
        """
        result = ClusterResult(groups=[], edges_applied=0, edges_skipped=0,
                               contradictions=[])

        ev_by_pair = {
            (min(ev.a_index, ev.b_index), max(ev.a_index, ev.b_index)): ev
            for ev in evidences
        }

        for d in decisions:
            self._register(d.a_index)
            self._register(d.b_index)
            if d.decision == DISTINCT:
                ev = ev_by_pair.get((min(d.a_index, d.b_index),
                                     max(d.a_index, d.b_index)))
                if ev is not None and ev.conflict >= STRONG_CONFLICT_BAR:
                    self.add_must_not_link(d.a_index, d.b_index)

        edges: list[ClusterEdge] = []
        for d in decisions:
            if d.decision != SAME:
                continue
            pair = (min(d.a_index, d.b_index), max(d.a_index, d.b_index))
            ev = ev_by_pair.get(pair)
            strong = ev is not None and ev.contact_identity > 0
            edges.append(ClusterEdge(
                a_index=d.a_index, b_index=d.b_index,
                score=d.score, strong=strong,
                evidence=(ev.to_dict() if ev else {}),
            ))
        edges.sort(key=lambda e: (-e.score, e.pair))

        for edge in edges:
            ra, rb = self._find(edge.a_index), self._find(edge.b_index)
            if ra == rb:
                continue  # already same component via stronger edges

            # Weak (location-only) edges may not chain: they only merge
            # records that are both singletons or directly paired.
            if not edge.strong:
                comp_a = self._component(edge.a_index)
                comp_b = self._component(edge.b_index)
                if len(comp_a) > 1 or len(comp_b) > 1:
                    result.edges_skipped += 1
                    result.contradictions.append({
                        "kind": "weak_edge_chain",
                        "pair": edge.pair,
                        "score": edge.score,
                        "detail": "location-only evidence cannot chain "
                                  "through existing components",
                    })
                    continue

            violation = self._would_violate(edge.a_index, edge.b_index)
            if violation is not None:
                result.edges_skipped += 1
                result.contradictions.append({
                    "kind": "must_not_link",
                    "pair": edge.pair,
                    "score": edge.score,
                    "violates": violation,
                    "detail": "merge blocked by a strong-distinct decision",
                })
                continue

            self._union(edge.a_index, edge.b_index)
            result.edges_applied += 1

        groups: dict[int, list[int]] = {}
        for node in sorted(self._parent):
            root = self._find(node)
            groups.setdefault(root, []).append(node)
        result.groups = sorted(groups.values(), key=lambda g: g[0])
        return result
