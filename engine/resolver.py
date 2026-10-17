"""Entity resolution — public entry point (compatibility shim).

v3.1 moved the engine to ``engine/resolution/`` (features, blocking,
comparators, scoring, classification, constrained clustering, canonical
records). This module keeps the v3.0 import surface stable:

    from engine.resolver import GraphEntityResolver, GoldenRecordBuilder

``GraphEntityResolver`` is the v3.1 ``EntityResolver`` — same
``resolve(leads) -> (clusters, report)`` call shape, now returning the
richer ``ResolutionResult`` report (a superset of the old
``ResolutionReport`` fields). ``GoldenRecordBuilder`` is the v3.1
``CanonicalBuilder`` with the same ``build(leads) -> dict`` shape plus
aliases / per-field provenance / conflict alternatives.
"""

from __future__ import annotations

from engine.resolution.canonical import CanonicalBuilder
from engine.resolution.resolver import EntityResolver, ResolutionResult

# v3.0 names kept alive for services / api / cli / tests / benchmarks.
GraphEntityResolver = EntityResolver
GoldenRecordBuilder = CanonicalBuilder
ResolutionReport = ResolutionResult

__all__ = [
    "GraphEntityResolver",
    "GoldenRecordBuilder",
    "EntityResolver",
    "CanonicalBuilder",
    "ResolutionResult",
    "ResolutionReport",
]
