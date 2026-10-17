"""API integration tests (TestClient) — route ordering, search, autocomplete,
stats, and the v2 regressions that must never come back."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from api.server import create_app
from domain.enums import DataSource
from domain.models import Lead
from infrastructure.storage.lead_repo import LeadRepository


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api_test.db"))
    monkeypatch.setenv("ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))

    # Fresh app per test (settings are lru_cached; env is set first).
    from config import settings as settings_mod
    settings_mod.get_settings.cache_clear()

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    from infrastructure.http import HttpClientFactory
    HttpClientFactory.reset()
    settings_mod.get_settings.cache_clear()


def _seed_lead(app_client, **overrides) -> dict:
    defaults = dict(
        name="Pharmacie Centrale",
        industry="pharmacie",
        wilaya="Alger",
        website="https://pharmacie-centrale.dz",
        phone="+213550123456",
    )
    defaults.update(overrides)
    resp = app_client.post("/api/v2/leads/manual", json=defaults)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# The v2 regressions
# ---------------------------------------------------------------------------

def test_search_route_not_shadowed(client):
    """v2 bug: /leads/search matched /leads/{lead_id} first -> 422."""
    _seed_lead(client)
    resp = client.get("/api/v2/leads/search", params={"q": "pharmacie"})
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


def test_search_survives_fts_injection(client):
    _seed_lead(client)
    for evil in ['"*NEAR(x)', 'a OR b AND (c', '"unclosed', 'col:*', '; DROP']:
        resp = client.get("/api/v2/leads/search", params={"q": evil})
        assert resp.status_code == 200, f"{evil!r} -> {resp.status_code}"


def test_autocomplete_endpoint_exists(client):
    """v2 bug: the dashboard called /search/autocomplete -> 404."""
    _seed_lead(client)
    resp = client.get("/api/v2/search/autocomplete", params={"q": "phar"})
    assert resp.status_code == 200
    assert isinstance(resp.json()["suggestions"], list)


def test_entities_stats_not_shadowed(client):
    resp = client.get("/api/v2/entities/stats")
    assert resp.status_code == 200
    assert "total_clusters" in resp.json()


def test_stats_has_age_breakdown(client):
    """v2 bug: stats() hardcoded age_breakdown to [] (Fresh-24h always 0)."""
    _seed_lead(client)
    resp = client.get("/api/v2/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert "age_breakdown" in body
    assert sum(body["age_breakdown"].values()) == body["total_leads"]


def test_health_is_fast_and_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Core flows
# ---------------------------------------------------------------------------

def test_manual_lead_flow(client):
    data = _seed_lead(client)
    resp = client.get(f"/api/v2/leads/{data['lead_id']}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["name"] == "Pharmacie Centrale"
    assert detail["source"] == "manual"


def test_analyze_lead_attaches_audit(client):
    data = _seed_lead(client)
    resp = client.post(f"/api/v2/leads/{data['lead_id']}/analyze")
    assert resp.status_code == 200
    body = resp.json()
    assert body["digital_score"] is not None
    assert body["priority_score"] > 0

    detail = client.get(f"/api/v2/leads/{data['lead_id']}").json()
    assert detail["analysis_model"] == "deterministic-v3"
    assert isinstance(detail["recommended_services"], list)


def test_analyze_pending_then_score_all(client):
    _seed_lead(client, name="Clinique A")
    _seed_lead(client, name="Boulangerie B", industry="boulangerie", wilaya="Oran")

    resp = client.post("/api/v2/leads/analyze-pending")
    assert resp.status_code == 200 and resp.json()["analyzed"] == 2

    resp = client.post("/api/v2/leads/score-all")
    assert resp.status_code == 200
    # Already scored by analyze -> nothing left unscored.
    assert resp.json()["scored"] == 0

    listed = client.get("/api/v2/leads").json()["leads"]
    assert all(l["priority_score"] > 0 for l in listed)


def test_status_and_contact_transitions(client):
    data = _seed_lead(client)
    lid = data["lead_id"]

    resp = client.post(f"/api/v2/leads/{lid}/status", json={"status": "contacted"})
    assert resp.status_code == 200

    # A later re-analysis must not clobber the CRM status.
    client.post(f"/api/v2/leads/{lid}/analyze")
    detail = client.get(f"/api/v2/leads/{lid}").json()
    assert detail["status"] == "contacted"

    resp = client.post(f"/api/v2/leads/{lid}/contact", json={"is_contact": True})
    assert resp.status_code == 200
    detail = client.get(f"/api/v2/leads/{lid}").json()
    assert detail["is_contact"] is True


def test_bulk_operations(client):
    a = _seed_lead(client, name="Biz A")
    b = _seed_lead(client, name="Biz B", industry="menuiserie", wilaya="Oran")
    ids = [a["lead_id"], b["lead_id"]]

    resp = client.post("/api/v2/leads/bulk-contact", json={"lead_ids": ids, "is_contact": True})
    assert resp.status_code == 200 and resp.json()["updated"] == 2

    resp = client.post("/api/v2/leads/bulk-status", json={"lead_ids": ids, "status": "rejected"})
    assert resp.status_code == 200

    listed = client.get("/api/v2/leads", params={"status": "rejected"}).json()["leads"]
    assert len(listed) == 2


def test_list_filters_and_sorting(client):
    _seed_lead(client, name="Pharmacie A", wilaya="Alger")
    _seed_lead(client, name="Menuiserie B", industry="menuiserie", wilaya="Oran")

    resp = client.get("/api/v2/leads", params={"wilaya": "Alger"})
    assert resp.json()["count"] == 1

    resp = client.get("/api/v2/leads", params={"sort_by": "name", "sort_order": "asc"})
    names = [l["name"] for l in resp.json()["leads"]]
    assert names == sorted(names)

    resp = client.get("/api/v2/leads", params={"tag": "nope"})
    assert resp.json()["count"] == 0


def test_entity_resolution_flow(client):
    _seed_lead(client, name="Pharmacie Centrale", phone="+213550123456",
               website="https://pharmacie-centrale.dz")
    _seed_lead(client, name="Pharmacie Central", phone="+213550123456", website=None)

    resp = client.post("/api/v2/entities/resolve")
    assert resp.status_code == 200
    body = resp.json()
    assert body["multi_member_clusters"] >= 1

    listed = client.get("/api/v2/entities").json()["entities"]
    assert any(e["member_count"] == 2 for e in listed)

    cluster_id = next(e["id"] for e in listed if e["member_count"] == 2)
    lineage = client.get(f"/api/v2/entities/{cluster_id}/lineage").json()["lineage"]
    assert len(lineage) == 2


def test_export_endpoints(client):
    _seed_lead(client)
    csv_resp = client.get("/api/v2/export/leads/csv")
    assert csv_resp.status_code == 200
    assert "name" in csv_resp.text

    json_resp = client.get("/api/v2/export/leads/json")
    assert json_resp.status_code == 200


def test_route_index_generated_from_app(client):
    resp = client.get("/api")
    assert resp.status_code == 200
    endpoints = resp.json()["endpoints"]
    assert "GET /api/v2/leads/search" in endpoints
    assert "GET /api/v2/search/autocomplete" in endpoints


def test_crawler_status_and_stop(client):
    resp = client.get("/api/v2/crawler/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is False

    resp = client.post("/api/v2/crawler/stop")
    assert resp.status_code == 200
