"""String-similarity functions used by the entity resolver.

We use ``rapidfuzz`` for the heavy lifting (it is ~10x faster than a
pure-Python Levenshtein) and provide thin wrappers so the rest of the
codebase doesn't import rapidfuzz directly.

All functions return a float in ``[0.0, 1.0]`` where ``1.0`` means
identical and ``0.0`` means completely different.
"""

from __future__ import annotations

from typing import Iterable, Set

try:
    from rapidfuzz import fuzz, distance
    _HAS_RAPIDFUZZ = True
except ImportError:  # pragma: no cover — rapidfuzz is in requirements
    _HAS_RAPIDFUZZ = False


def levenshtein_ratio(s1: str, s2: str) -> float:
    """Normalised Levenshtein similarity (0..1).

    Uses ``rapidfuzz.distance.Levenshtein.normalized_similarity`` when
    available; falls back to a pure-Python implementation otherwise.
    """
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0
    if _HAS_RAPIDFUZZ:
        return float(distance.Levenshtein.normalized_similarity(s1.lower(), s2.lower()))
    return _levenshtein_ratio_pure(s1, s2)


def jaccard_similarity(set1: Iterable[str], set2: Iterable[str]) -> float:
    """Jaccard similarity between two iterables of tokens (0..1)."""
    s1 = set(set1) if not isinstance(set1, Set) else set1
    s2 = set(set2) if not isinstance(set2, Set) else set2
    if not s1 or not s2:
        return 0.0
    intersection = s1 & s2
    union = s1 | s2
    return len(intersection) / len(union)


def jaro_winkler_similarity(s1: str, s2: str) -> float:
    """Jaro-Winkler similarity (0..1) — better than Levenshtein for names."""
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0
    if _HAS_RAPIDFUZZ:
        return float(fuzz.QRatio(s1.lower(), s2.lower())) / 100.0
    return _levenshtein_ratio_pure(s1, s2)


# ---------------------------------------------------------------------------
#  Pure-Python fallback (used only if rapidfuzz is not installed)
# ---------------------------------------------------------------------------

def _levenshtein_ratio_pure(s1: str, s2: str) -> float:
    """Pure-Python Levenshtein ratio — O(n*m) but correct."""
    s1, s2 = s1.lower(), s2.lower()
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0
    # Two-row optimisation to keep memory O(min(n,m)).
    if len1 > len2:
        s1, s2 = s2, s1
        len1, len2 = len2, len1
    prev = list(range(len1 + 1))
    for j in range(1, len2 + 1):
        curr = [j] + [0] * len1
        for i in range(1, len1 + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            curr[i] = min(
                prev[i] + 1,        # deletion
                curr[i - 1] + 1,    # insertion
                prev[i - 1] + cost, # substitution
            )
        prev = curr
    distance_val = prev[len1]
    return 1.0 - (distance_val / max(len1, len2))
