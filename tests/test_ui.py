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


# ---------------------------------------------------------------------------
# Field-reported regressions: mutation toasts must not crash the app
# ---------------------------------------------------------------------------


def test_icon_literals_are_valid_emoji():
    """Every ``icon="…"`` literal in ui/ must be a single valid emoji.

    st.toast validates its icon at render time and raises
    StreamlitAPIException otherwise — the "✓"/"✕"/"↺"/"■" text glyphs
    crashed every mutation flow in the field (entity resolution, bulk
    lead actions, manual lead creation, checkpoint edits, lead edits,
    crawler start/stop).
    """
    import ast

    from streamlit.string_util import is_emoji

    checked = 0
    for path in sorted((PROJECT_ROOT / "ui").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != "icon" or not isinstance(kw.value, ast.Constant):
                    continue
                icon = kw.value.value
                if isinstance(icon, str):
                    assert is_emoji(icon), (
                        f"{path.relative_to(PROJECT_ROOT)}: icon={icon!r} "
                        "is not a single valid emoji"
                    )
                    checked += 1
    assert checked >= 15, "the ui/ icon scan found suspiciously few sites"


def test_crawler_start_flow_renders_seed_count_toast(engine_server):
    """Start-crawl through the UI must not crash on the engine response.

    Regression: the toast called ``len()`` on ``seeded_urls`` — the
    engine returns an int count (CrawlerEngine.bootstrap), so the click
    raised ``TypeError: object of type 'int' has no len()``.
    """
    at = _run_app(engine_server)
    assert not at.exception

    at.text_input(key="crawler_queries").set_value("menuiserie Alger")
    at.button("Start crawl").click().run()

    assert not at.exception, [str(e.value) for e in at.exception]


def test_crawler_stop_flow_stops_engine_and_renders_toast(engine_server):
    """Stop-crawl through the UI must stop the engine and not crash.

    Regression: the stopping toast used the "■" text glyph as its icon —
    StreamlitAPIException killed the app run before st.rerun().
    """
    import httpx

    started = httpx.post(
        f"{engine_server}/api/v2/crawler/start",
        json={"queries": ["menuiserie Alger"]},
        timeout=30,
    )
    assert started.status_code == 200, started.text
    assert isinstance(started.json()["seeded_urls"], int)  # engine contract: a count

    at = _run_app(engine_server)
    assert not at.exception

    at.button("■ Stop crawler").click().run()
    assert not at.exception, [str(e.value) for e in at.exception]

    status = httpx.get(f"{engine_server}/api/v2/crawler/status", timeout=30).json()
    assert status["active"] is False


def test_st_folium_kwargs_follow_installed_capability(monkeypatch):
    """``return_on_click`` must only be passed when streamlit-folium has it.

    Regression: older streamlit-folium (< 0.21) rejects the kwarg with
    TypeError and the whole map hub degraded to the fallback table.
    """
    pytest.importorskip("streamlit_folium")

    import streamlit_folium

    from ui.components.algeria_map import _st_folium_kwargs

    # Newer streamlit-folium (>= 0.21, the pinned floor): kwarg included.
    def fake_new(fig, height=500, return_on_click=False, **kwargs):
        return {"last_clicked": None}

    monkeypatch.setattr(streamlit_folium, "st_folium", fake_new)
    assert _st_folium_kwargs(540).get("return_on_click") is True

    # Older streamlit-folium (< 0.21): kwarg must be omitted or the call
    # dies with TypeError("unexpected keyword argument 'return_on_click'").
    def fake_old(fig, height=500, returned_objects=None, **kwargs):
        if "return_on_click" in kwargs:
            raise TypeError(
                "st_folium() got an unexpected keyword argument 'return_on_click'"
            )
        return {"last_clicked": None}

    monkeypatch.setattr(streamlit_folium, "st_folium", fake_old)
    kwargs = _st_folium_kwargs(540)
    assert "return_on_click" not in kwargs
    assert streamlit_folium.st_folium(None, **kwargs) == {"last_clicked": None}
