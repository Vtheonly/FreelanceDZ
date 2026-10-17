# ADR-004 · Atomic upsert and WAL-once: correctness over raw throughput

**Status**: accepted (v4 Tasks 6 & 15)
**Context**: The old upsert was SELECT-then-INSERT inside a deferred
transaction — a documented race under concurrent writers — and every
connection re-declared `PRAGMA journal_mode = WAL`, taking an exclusive
lock per operation (which also masked the race by serialising writers).
**Decision**: single native `INSERT ... ON CONFLICT(fingerprint) DO
UPDATE ... RETURNING id` executed inside `BEGIN IMMEDIATE`; WAL declared
exactly once at initialisation; `busy_timeout = 5000` on every
connection.
**Consequences**: race-free by construction (50-way concurrent test
proves one id, zero exceptions); sequential upsert throughput drops ~13%,
documented and accepted; merge policy encoded once, in the SQL.
