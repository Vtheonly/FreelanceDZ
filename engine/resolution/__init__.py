"""Business Entity Resolution & Aggregation — v3.1 evidence pipeline.

Replaces v3.0's single-threshold composite scorer with a staged
entity-resolution pipeline:

    features -> blocking -> comparators -> scoring -> classification
            -> constrained clustering -> canonical records

Design contract (see ARCHITECTURE.md "Entity Resolution v3.1"):

- Three relationships, not one: SAME (aggregate), RELATED (linked but
  distinct — branches, franchises, shared owner), DISTINCT (no supported
  relationship), plus UNRESOLVED for ambiguous pairs (review queue).
- Names are organizational evidence, never identity evidence: two records
  with identical names and nothing else cannot auto-merge (the two
  "Café Atlas" restaurants in Algiers and Oran must stay separate), while
  strong identity evidence (shared phone, matching social handle,
  cross-references, co-location) merges records even when names differ.
- Organizational identifiers (shared website domain of a chain, shared
  email domain) establish RELATED, not SAME: two branches of one chain
  stay separate location-level entities linked by a relation.
- Precision over recall: an incorrect merge is a more serious error than
  a temporary duplicate, so auto-merge requires identity corroboration
  and everything ambiguous is queued for review instead of guessed.
- Non-destructive + reversible: source leads are never mutated; clusters
  are memberships; every decision is logged with its evidence; manual
  splits/merges are pinned so the engine respects them on later runs.
"""

from engine.resolution.features import RecordFeatures, extract_features
from engine.resolution.blocking import BlockingIndex
from engine.resolution.comparators import SignalResult, compare_pair
from engine.resolution.scoring import EvidenceScorer, PairEvidence
from engine.resolution.classifier import (
    Decision,
    MatchClassifier,
    RELATIONSHIP_BRANCH,
    RELATIONSHIP_OWNER,
    RELATIONSHIP_AFFILIATE,
)
from engine.resolution.clustering import ConstraintClusterer, ClusterEdge
from engine.resolution.canonical import CanonicalBuilder, SourceTrust
from engine.resolution.resolver import EntityResolver, ResolutionResult

__all__ = [
    "RecordFeatures", "extract_features",
    "BlockingIndex",
    "SignalResult", "compare_pair",
    "EvidenceScorer", "PairEvidence",
    "Decision", "MatchClassifier",
    "RELATIONSHIP_BRANCH", "RELATIONSHIP_OWNER", "RELATIONSHIP_AFFILIATE",
    "ConstraintClusterer", "ClusterEdge",
    "CanonicalBuilder", "SourceTrust",
    "EntityResolver", "ResolutionResult",
]
