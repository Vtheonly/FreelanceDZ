"""Evidence aggregation: signal results -> three-bucket pair evidence.

The scorer is deliberately simple — summation with one structural rule —
because all the judgment lives in the calibrated signal weights
(comparators.py) and the decision thresholds (classifier.py).

The structural rule is the *location cap*: location agreement (geo
coordinates, address text, wilaya) alone can contribute at most
``LOCATION_CAP`` (0.55) to the identity bucket. Two records that place
themselves in the same neighbourhood with similar names but share no
contact identifier are exactly the "two cafés on the same street" case
the spec warns about — they go to review, not to an automatic merge.
Contact-level evidence (phone, social handle, cross reference, exact
email, shared domain) has no cap: any single one of those plus a
consistent name is enough.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from engine.resolution.comparators import SignalResult, compare_pair
from engine.resolution.features import RecordFeatures

LOCATION_CAP = 0.55


@dataclass(slots=True)
class PairEvidence:
    """Aggregated evidence for one candidate pair."""

    a_index: int
    b_index: int
    a_lead_id: int | None
    b_lead_id: int | None

    name_sim: float = 0.0

    identity: float = 0.0        # contact + capped location evidence
    contact_identity: float = 0.0  # phone/social/xref/email/domain only
    location_identity: float = 0.0  # geo/address/wilaya (capped)
    org: float = 0.0             # organizational evidence
    conflict: float = 0.0        # disagreement magnitude
    total: float = 0.0           # precomputed scalar (identity + org - conflict)

    signals: list[SignalResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "lead_a": self.a_lead_id,
            "lead_b": self.b_lead_id,
            "name_sim": self.name_sim,
            "identity": self.identity,
            "contact_identity": self.contact_identity,
            "location_identity": self.location_identity,
            "org": self.org,
            "conflict": self.conflict,
            "total": self.total,
            "signals": [s.to_dict() for s in self.signals],
        }


class EvidenceScorer:
    """Aggregates comparator output into bucketed pair evidence."""

    def score(
        self,
        a: RecordFeatures,
        b: RecordFeatures,
        name_sim: float,
        pair: tuple[int, int],
    ) -> PairEvidence:
        signals = compare_pair(a, b, name_sim)

        contact = 0.0
        location = 0.0
        org = 0.0
        conflict = 0.0

        for s in signals:
            if s.signal in ("phone", "social", "cross_reference", "email", "website"):
                # Contact identifiers (exact email / domain identity share
                # included) feed the contact bucket.
                contact += s.identity
            elif s.signal in ("geo", "address"):
                location += s.identity
            # Organizational credit (shared domain / email domain / shared
            # phone channel / name / industry) accumulates from any signal.
            org += s.org
            conflict += s.conflict

        capped_location = min(location, LOCATION_CAP)
        return PairEvidence(
            a_index=pair[0],
            b_index=pair[1],
            a_lead_id=a.lead_id,
            b_lead_id=b.lead_id,
            name_sim=round(name_sim, 4),
            identity=round(contact + capped_location, 4),
            contact_identity=round(contact, 4),
            location_identity=round(capped_location, 4),
            org=round(org, 4),
            conflict=round(conflict, 4),
            total=round(contact + capped_location + org - conflict, 4),
            signals=signals,
        )

    def score_all(
        self,
        features: list[RecordFeatures],
        pairs: list[tuple[int, int]],
        name_sims: Iterable[float],
    ) -> list[PairEvidence]:
        return [
            self.score(features[a], features[b], sim, pair)
            for pair, sim in zip(pairs, name_sims)
        ]
