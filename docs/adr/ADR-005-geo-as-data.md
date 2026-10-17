# ADR-005 · Geographic intelligence as versioned data + engine service

**Status**: accepted (v4 refactor)
**Context**: Administrative divisions change (48 → 58 wilayas in 2019;
further reforms are proposed). Hardcoding geometry, or shipping it as UI
constants, would make every reform a code refactor.
**Decision**: boundaries live in `engine/geodata/` as a validated,
attributed dataset (ODbL/OSM) re-mapped to official Law 19-12 codes by
`scripts/fetch_wilaya_boundaries.py`; `engine/geo.py` exposes lookup,
centroids, catalogue joins, and transport payloads as an engine service
(`/api/v2/geo/*`); the catalogue in `config/wilayas.py` stays data-only.
**Consequences**: reforms become a dataset swap + catalogue sync; the UI
consumes geometry like any other client; integrity is test-enforced
(codes 1–58, closed rings, known-city lookups).
