"""Pair classification: evidence -> SAME / RELATED / DISTINCT / UNRESOLVED.

Decision rules (thresholds in config.settings, calibrated on the spec's
Café Atlas scenarios — see tests/test_resolution.py):

SAME (auto-merge) requires ALL of:
    identity      >= ENTITY_MERGE_IDENTITY      (default 0.70)
    conflict      <= ENTITY_MERGE_MAX_CONFLICT  (default 0.45)
    name_sim      >= ENTITY_MERGE_MIN_NAME      (default 0.45)
    AND a contact identifier strong enough to carry the decision on its
    own (>= ENTITY_MERGE_IDENTITY) OR explicit same-place evidence
    (coordinates < 200 m apart, or address overlap >= 0.5). The last
    clause is what keeps blind chain-branch pairs (shared domain, pins
    a few km apart, no phones/addresses) out of auto-merge: identity
    evidence coming from location alone must prove the SAME place, not
    just the same neighbourhood. A stale wilaya never vetoes a pair
    whose contact evidence is strong.

RELATED (linked, not merged) requires ALL of:
    org evidence  >= ENTITY_RELATED_MIN_ORG     (default 0.90)
    name_sim      >= ENTITY_RELATED_MIN_NAME    (default 0.75)
    a location-level disagreement (conflict above the merge bar, or
    disjoint phones, or different wilayas / disjoint verified addresses)
    proving the records are NOT one place — otherwise they would be SAME
    or UNRESOLVED candidates.
Relationship type: branch_of (shared website domain — the chain
signature), same_owner (shared email domain or phone), else affiliated.

DISTINCT when the total (identity + org - conflict) falls to or below
ENTITY_DISTINCT_TOTAL (default 0.10): disagreement outweighs everything.

UNRESOLVED for everything else — the pair lands in the review queue with
its full evidence attached. Precision-first: an ambiguous pair is a
question for a human, not a guess for the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from config.settings import get_settings
from engine.resolution.comparators import (
    TAG_CONTACT_DISAGREEMENT,
    TAG_LOCATION_DISAGREEMENT,
    TAG_SAME_PLACE,
)
from engine.resolution.scoring import PairEvidence

SAME = "same"
RELATED = "related"
DISTINCT = "distinct"
UNRESOLVED = "unresolved"

# DISTINCT decisions below this name similarity get a terse explanation:
# low-similarity distinct pairs are the common case (summarized in the
# run report), and formatting hundreds of thousands of them was a
# measured hotspot. High-similarity separations ("same name, kept
# apart") always get the full story.
_DISTINCT_EXPLAIN_NAME_SIM = 0.75

# Pairs below this identity+org sum are DISTINCT without review: they
# share no identifier, no meaningful name similarity and no location
# agreement — noise from blocking collisions ("Garage Nour 42" vs
# "Agence Ambre" matched a trigram), not candidate duplicates. The
# review queue is for pairs a human could plausibly merge.
_REVIEW_EVIDENCE_FLOOR = 0.55

RELATIONSHIP_BRANCH = "branch_of"
RELATIONSHIP_OWNER = "same_owner"
RELATIONSHIP_AFFILIATE = "affiliated"

_ENGINE = "engine"


@dataclass(slots=True)
class Decision:
    """The verdict for one candidate pair, with its justification."""

    a_index: int
    b_index: int
    a_lead_id: Optional[int]
    b_lead_id: Optional[int]
    decision: str                     # SAME | RELATED | DISTINCT | UNRESOLVED
    relationship: Optional[str] = None  # for RELATED
    score: float = 0.0                # evidence.total
    decided_by: str = _ENGINE
    explanation: str = ""
    signals: dict = field(default_factory=dict)  # full evidence (log-worthy rows)

    def to_dict(self) -> dict:
        return {
            "lead_a": self.a_lead_id,
            "lead_b": self.b_lead_id,
            "decision": self.decision,
            "relationship": self.relationship,
            "score": round(self.score, 3),
            "decided_by": self.decided_by,
            "explanation": self.explanation,
        }


class MatchClassifier:
    """Thresholds + decision rules over PairEvidence."""

    def __init__(
        self,
        merge_identity: Optional[float] = None,
        merge_max_conflict: Optional[float] = None,
        merge_min_name: Optional[float] = None,
        related_min_org: Optional[float] = None,
        related_min_name: Optional[float] = None,
        distinct_total: Optional[float] = None,
    ) -> None:
        s = get_settings()
        self._merge_identity = merge_identity if merge_identity is not None else s.ENTITY_MERGE_IDENTITY
        self._merge_max_conflict = merge_max_conflict if merge_max_conflict is not None else s.ENTITY_MERGE_MAX_CONFLICT
        self._merge_min_name = merge_min_name if merge_min_name is not None else s.ENTITY_MERGE_MIN_NAME
        self._related_min_org = related_min_org if related_min_org is not None else s.ENTITY_RELATED_MIN_ORG
        self._related_min_name = related_min_name if related_min_name is not None else s.ENTITY_RELATED_MIN_NAME
        self._distinct_total = distinct_total if distinct_total is not None else s.ENTITY_DISTINCT_TOTAL

    # ------------------------------------------------------------------
    def classify(self, ev: PairEvidence) -> Decision:
        d = Decision(
            a_index=ev.a_index,
            b_index=ev.b_index,
            a_lead_id=ev.a_lead_id,
            b_lead_id=ev.b_lead_id,
            decision=UNRESOLVED,
            score=ev.total,
        )

        # --- SAME -----------------------------------------------------
        if (
            ev.identity >= self._merge_identity
            and ev.conflict <= self._merge_max_conflict
            and ev.name_sim >= self._merge_min_name
            and (ev.contact_identity >= self._merge_identity
                 or self._same_place(ev))
        ):
            d.decision = SAME
            d.explanation = self._explain_same(ev)
            return d

        # --- DISTINCT ---------------------------------------------------
        if ev.total <= self._distinct_total or ev.identity + ev.org < _REVIEW_EVIDENCE_FLOOR:
            d.decision = DISTINCT
            if ev.name_sim >= _DISTINCT_EXPLAIN_NAME_SIM:
                d.explanation = self._explain_distinct(ev)
            else:
                d.explanation = (
                    f"distinct: no evidence connects these records "
                    f"(identity {ev.identity:.2f}, org {ev.org:.2f})"
                )
            return d

        # --- RELATED ----------------------------------------------------
        if (
            ev.org >= self._related_min_org
            and ev.name_sim >= self._related_min_name
            and (ev.conflict > self._merge_max_conflict
                 or self._location_disagreement(ev))
        ):
            d.decision = RELATED
            d.relationship = self._relationship_type(ev)
            d.explanation = self._explain_related(ev, d.relationship)
            return d

        # --- UNRESOLVED ---------------------------------------------------
        d.decision = UNRESOLVED
        d.explanation = self._explain_unresolved(ev)
        return d

    # ------------------------------------------------------------------
    @staticmethod
    def _has_tag(ev: PairEvidence, tag: str) -> bool:
        return any(tag in s.tags for s in ev.signals)

    @classmethod
    def _same_place(cls, ev: PairEvidence) -> bool:
        return cls._has_tag(ev, TAG_SAME_PLACE)

    @classmethod
    def _location_disagreement(cls, ev: PairEvidence) -> bool:
        return cls._has_tag(ev, TAG_LOCATION_DISAGREEMENT)

    @classmethod
    def _contact_disagreement(cls, ev: PairEvidence) -> bool:
        return cls._has_tag(ev, TAG_CONTACT_DISAGREEMENT)

    @staticmethod
    def _shared_phones(ev: PairEvidence) -> bool:
        return any(s.signal == "phone" and s.identity > 0 for s in ev.signals)

    @staticmethod
    def _shared_domain(ev: PairEvidence) -> bool:
        return any(
            s.signal == "website" and s.identity > 0 for s in ev.signals
        )

    @staticmethod
    def _shared_email_domain(ev: PairEvidence) -> bool:
        return any(
            s.signal == "email" and s.org > 0 for s in ev.signals
        )

    def _relationship_type(self, ev: PairEvidence) -> str:
        if self._shared_domain(ev):
            return RELATIONSHIP_BRANCH
        if self._shared_email_domain(ev) or self._shared_phones(ev):
            # Shared contact channel + separate locations: one owner
            # behind both businesses (central hotline / shared inbox).
            return RELATIONSHIP_OWNER
        return RELATIONSHIP_AFFILIATE

    # --- explanations (human-readable, stored in the decision log) ------
    @staticmethod
    def _top(ev: PairEvidence, bucket: str, n: int = 2) -> list[str]:
        parts = [
            s.note for s in ev.signals
            if s.note and getattr(s, bucket) > 0
        ]
        return parts[:n]

    def _explain_same(self, ev: PairEvidence) -> str:
        why = "; ".join(self._top(ev, "identity")) or "identity evidence"
        return f"same entity: {why} (identity {ev.identity:.2f}, conflict {ev.conflict:.2f})"

    def _explain_distinct(self, ev: PairEvidence) -> str:
        against = "; ".join(
            s.note for s in ev.signals if s.conflict > 0
        ) or "insufficient shared evidence"
        return (
            f"distinct: {against} "
            f"(total {ev.total:.2f}, name similarity {ev.name_sim:.2f})"
        )

    def _explain_related(self, ev: PairEvidence, relationship: str) -> str:
        shared = "; ".join(self._top(ev, "org")) or "organizational evidence"
        return (
            f"related ({relationship}): {shared}, but location-level "
            f"disagreement keeps the entities separate "
            f"(identity {ev.identity:.2f}, conflict {ev.conflict:.2f})"
        )

    def _explain_unresolved(self, ev: PairEvidence) -> str:
        pro = "; ".join(self._top(ev, "identity")) or "none"
        con = "; ".join(s.note for s in ev.signals if s.conflict > 0) or "none"
        return (
            f"unresolved: identity evidence ({pro}) and disagreement ({con}) "
            f"are both inconclusive (identity {ev.identity:.2f}, org {ev.org:.2f}, "
            f"conflict {ev.conflict:.2f}) — queued for review"
        )
