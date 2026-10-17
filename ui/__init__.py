"""FreelanceDZ Streamlit workspace — a pure API client of the engine.

This package contains NO business logic and NO direct database access:
every read and write goes through the engine's documented HTTP API
(see docs/04-api-reference.md), so the UI is exactly the kind of client
any other consumer would be. The engine runs (and is tested) fully
independently of Streamlit.
"""
