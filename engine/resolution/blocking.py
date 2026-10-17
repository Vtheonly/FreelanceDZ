"""Candidate generation (blocking) — avoid comparing every record with
every other record while never missing a pair that shares an identifier.

v3.0 blocked on name trigrams only: two records sharing a phone or a
website but carrying differently-worded names ("Café Atlas" official site
vs "Atlas Restaurant" Google profile) never became candidates. v3.1
builds five complementary blocking keys and unions their pair sets:

- name trigrams (fuzzy recall for spelling variants / typos)
- name prefix after type-word strip ("Café Atlas Restaurant" -> "cafeatlas")
- every normalized E.164 phone digit string
- registrable website domain
- social identity "platform:handle"

(A wilaya+first-token key was evaluated and dropped: the type-stripped
prefix covers its recall, and on realistic corpora it produced ~40%
junk pairs — same city, same business-type word, unrelated businesses.)

Each key skips canopies wider than ``max_block_size`` (uninformative at
that width) except phone/domain/social keys, which are exact-match and
therefore informative at any width — a shared E.164 number is candidate
evidence even when 500 directory records carry it.
"""

from __future__ import annotations

from typing import Iterable

from engine.resolution.features import RecordFeatures

_EXACT_KEYS = ("phone", "domain", "social")   # informative at any block width


def _trigrams(key: str) -> set[str]:
    return {key[i:i + 3] for i in range(max(0, len(key) - 2))}


class BlockingIndex:
    """Multi-key inverted index producing the candidate pair set."""

    def __init__(self, max_block_size: int = 100) -> None:
        self._max_block = max_block_size
        self._blocks: dict[str, list[int]] = {}
        self._block_kind: dict[str, str] = {}

    # ------------------------------------------------------------------
    def add(self, f: RecordFeatures) -> None:
        """Register every blocking key of one record."""
        idx = f.index

        def _put(kind: str, key: str) -> None:
            if not key:
                return
            bkey = f"{kind}|{key}"
            self._blocks.setdefault(bkey, []).append(idx)
            self._block_kind[bkey] = kind

        if len(f.name_k) >= 3:
            for tri in _trigrams(f.name_k):
                _put("tri", tri)
        if len(f.prefix) >= 3:
            _put("prefix", f.prefix[:8])
        for phone in f.phones:
            _put("phone", phone)
        if f.website_domain:
            _put("domain", f.website_domain)
        for platform, handle in f.socials.items():
            _put("social", f"{platform}:{handle}")

    # ------------------------------------------------------------------
    def candidate_pairs(self) -> tuple[list[tuple[int, int]], dict[str, int]]:
        """Union of within-block pairs, (a, b) with a < b, plus per-kind
        candidate counts for the resolution report."""
        pair_set: set[tuple[int, int]] = set()
        kind_counts: dict[str, int] = {k: 0 for k in
                                       ("tri", "prefix", "phone", "domain", "social")}

        for bkey, members in self._blocks.items():
            if len(members) < 2:
                continue
            kind = self._block_kind[bkey]
            if len(members) > self._max_block and kind not in _EXACT_KEYS:
                continue  # canopy too broad to be informative
            members.sort()
            kind_counts[kind] += len(members)
            for i_pos in range(len(members)):
                a = members[i_pos]
                for j_pos in range(i_pos + 1, len(members)):
                    b = members[j_pos]
                    pair_set.add((a, b))

        return sorted(pair_set), kind_counts


def build_candidate_pairs(
    features: Iterable[RecordFeatures], max_block_size: int = 100
) -> tuple[list[tuple[int, int]], dict[str, int]]:
    """Convenience wrapper: index every record, return the pair set."""
    index = BlockingIndex(max_block_size)
    for f in features:
        index.add(f)
    return index.candidate_pairs()
