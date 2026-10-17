# ADR-006 · Two containers, not microservices

**Status**: accepted (v4 refactor)
**Context**: The operator asked for the engine "in its own container"
with a documented interface — and also warned against "artificial
services that duplicate logic, introduce unnecessary network hops, or
make the application harder to operate."
**Decision**: deploy exactly two services — engine (API, owns data and
logic) and UI (presentation) — while keeping the engine a modular
monolith with enforced internal boundaries (layer import rules, no
package cycles, hygiene tests).
**Decision**: optional third service (SearXNG) is a compose profile,
opt-in via SEARXNG_URL.
**Consequences**: health-gated startup, isolated lifecycles and images,
zero duplicated logic, no intra-engine network hops; scaling beyond
personal use would first exhaust SQLite's single-writer model before
this topology becomes the constraint.
