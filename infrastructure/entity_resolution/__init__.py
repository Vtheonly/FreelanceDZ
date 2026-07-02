"""Entity resolution infrastructure — graph-based duplicate detection & merging."""

from infrastructure.entity_resolution.similarity import (
    levenshtein_ratio,
    jaccard_similarity,
    jaro_winkler_similarity,
)
from infrastructure.entity_resolution.blocking import TrigramBlocker
from infrastructure.entity_resolution.merger import GoldenRecordMerger
from infrastructure.entity_resolution.graph_resolver import GraphEntityResolver

__all__ = [
    "levenshtein_ratio",
    "jaccard_similarity",
    "jaro_winkler_similarity",
    "TrigramBlocker",
    "GoldenRecordMerger",
    "GraphEntityResolver",
]
