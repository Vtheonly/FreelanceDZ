# ADR-001 · The UI is a pure API client, never a second backend

**Status**: accepted (v4 refactor)
**Context**: refactorv5's spec sketch accessed repositories directly from
Streamlit, which contradicts its own §7 ("the Streamlit interface should
call the same application services or APIs… It must not become a second
implementation of the backend") and the operator's requirement that the
engine stay independently testable and container-isolated.
**Decision**: `ui/` talks to the engine exclusively over the documented
HTTP API (`ui/api_client.py`), imports no engine packages, and ships in a
container built from a UI-only dependency file.
**Consequences**: one source of business logic; the engine runs and is
tested without Streamlit; enforced automatically by
`test_repo_hygiene.py::test_ui_never_imports_engine_internals`. Cost:
every interaction pays a localhost round-trip (measured ≤7 ms) — mitigated
with TTL read caches.
