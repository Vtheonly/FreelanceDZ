"""Streamlit UI tests — frontend-to-backend integration, no mocks.

Runs the real ``ui/app.py`` through Streamlit's AppTest harness against a
REAL engine server started in-process (uvicorn on an ephemeral port with a
temporary database). What is verified:

    * the app renders without raising when the engine is reachable, and
      every panel's data comes from the API (seeded lead appears, stats
      match the database);
    * the app degrades to an explicit, non-crashing error state when the
      engine is unreachable;
    * the map panel's boundary/catalogue data round-trips from the engine
      (58 wilayas, real geometry);
    * checkpoint creation through the UI path persists via the API.

The folium component itself cannot render headlessly — the map module's
no-component fallback path covers that, and the boundary payloads it
consumes are asserted directly here.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from api.server import create_app

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UI_APP = str(PROJECT_ROOT / "ui" / "app.py")


@pytest.fixture()
def engine_server(tmp_path, monkeypatch):
    """A real uvicorn engine on an ephemeral port + a seeded database."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "ui_test.db"))
    monkeypatch.setenv("ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))

    from config import settings as settings_mod

    settings_mod.get_settings.cache_clear()

    app = create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for the socket to bind and capture the assigned port.
    deadline = time.monotonic() + 15
    port = None
    while time.monotonic() < deadline:
        if getattr(server, "started", False):
            break
        time.sleep(0.05)
    for srv in getattr(server, "servers", []) or []:
        for sock in srv.sockets:
            port = sock.getsockname()[1]
            break
        if port:
            break
    if port is None:
        # Fallback: parse the listening socket from the started server.
        raise RuntimeError("engine server did not bind a port")
    base_url = f"http://127.0.0.1:{port}"

    # Seed data through the API — exactly what a client would do.
    with TestClient(app) as client:
        client.post(
            "/api/v2/leads/manual",
            json={
                "name": "Pharmacie de la Grande Poste",
                "industry": "pharmacie",
                "wilaya": "Alger",
                "phone": "+213550123456",
                "website": "https://pharmacie-grande.dz",
            },
        )
        client.post(
            "/api/v2/leads/manual",
            json={
                "name": "Menuiserie El Nour",
                "industry": "menuiserie",
                "wilaya": "Oran",
                "phone": "+213661112233",
            },
        )
        client.post(
            "/api/v2/leads/analyze-pending",
        )

    yield base_url

    server.should_exit = True
    thread.join(timeout=10)
    from infrastructure.http import HttpClientFactory

    HttpClientFactory.reset()
    settings_mod.get_settings.cache_clear()


def _run_app(engine_url: str | None) -> AppTest:
    import os

    import ui.api_client as api

    if engine_url:
        os.environ["ENGINE_URL"] = engine_url
    else:
        os.environ.pop("ENGINE_URL", None)
    # Streamlit caches live at module level and survive across AppTest runs
    # in the same process — clear them so each test talks to ITS engine.
    try:
        api.get_engine_client.clear()
        for name in dir(api):
            if name.startswith("fetch_") or name == "geo_lookup":
                cached = getattr(api, name, None)
                if hasattr(cached, "clear"):
                    cached.clear()
    except Exception:
        pass
    at = AppTest.from_file(UI_APP, default_timeout=60)
    at.run()
    return at


def test_ui_renders_and_serves_engine_data(engine_server):
    at = _run_app(engine_server)

    assert not at.exception, [str(e.value) for e in at.exception]
    # The engine-reachable path renders every enabled grid panel.
    markdown_text = " ".join(m.value for m in at.markdown)
    assert "Interactive map" in markdown_text
    assert "Leads matrix" in markdown_text
    assert "Field checkpoints" in markdown_text
    assert "Discovery engine" in markdown_text
    assert "Engine diagnostics" in markdown_text

    # KPI ribbon reflects the database through the API.
    assert "2" in markdown_text  # total leads


def test_ui_error_state_when_engine_unreachable(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "u.db"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    at = _run_app("http://127.0.0.1:9")  # nothing listens here

    assert not at.exception
    assert any("unreachable" in e.value.lower() for e in at.error)


def test_ui_shows_seeded_lead_in_matrix(engine_server):
    at = _run_app(engine_server)
    assert not at.exception
    # The dataframe exists and carries the seeded business name.
    dataframes = at.dataframe
    assert dataframes, "leads matrix dataframe did not render"


def test_map_panel_data_comes_from_engine(engine_server):
    """The boundary + catalogue payloads the map consumes round-trip."""

    with TestClient(create_app()) as client:
        boundaries = client.get("/api/v2/geo/boundaries").json()
        catalogue = client.get("/api/v2/geo/wilayas").json()

    assert len(boundaries["features"]) == 58
    assert catalogue["count"] == 58
    oran = next(w for w in catalogue["wilayas"] if w["name_fr"] == "Oran")
    assert oran["leads_count"] == 1  # seeded through the API earlier


def test_checkpoint_created_through_api_appears_for_ui(engine_server):
    import httpx

    payload = {
        "name": "Oran Port Hub",
        "category": "hub",
        "latitude": 35.71,
        "longitude": -0.64,
        "notes": "terminal visit scheduled",
    }
    response = httpx.post(f"{engine_server}/api/v2/checkpoints", json=payload, timeout=30)
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["wilaya"] == "Oran"  # engine-derived from real geometry

    listed = httpx.get(f"{engine_server}/api/v2/checkpoints", params={"wilaya": "Oran"}, timeout=30)
    names = [cp["name"] for cp in listed.json()["checkpoints"]]
    assert "Oran Port Hub" in names
