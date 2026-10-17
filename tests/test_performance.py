"""Performance smoke tests — repeatable regression thresholds.

The thresholds are deliberately generous (machines vary) while still
catching order-of-magnitude regressions in the hot paths measured in
docs/12-performance.md. Run with `pytest tests/test_performance.py`.
"""

from __future__ import annotations

import asyncio
import os
import random
import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from domain.models import Lead

SAMPLE_HTML = (
    b"""<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">
<title>Pharmacie Centrale - Bab El Oued, Alger</title>
<meta name="description" content="Officine pharmaceutique de garde a Alger.">
<meta property="og:title" content="Pharmacie Centrale">
<link rel="canonical" href="https://pharmacie-centrale.dz/">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Pharmacy","name":"Pharmacie Centrale",
 "telephone":"+213 21 96 12 34","address":"Bab El Oued, Alger"}
</script></head>
<body><h1>Bienvenue</h1>
<p>Contactez notre pharmacien au 0550 12 34 56 ou 0770 98 76 54.</p>
<a href="/catalogue/produits">Nos produits</a>
<a href="https://facebook.com/pharmacie.centrale">Facebook</a>
</body></html>""" * 8
)


@pytest.fixture(scope="module", autouse=True)
def _isolated_db(tmp_path_factory):
    db = tempfile.mktemp(suffix=".db")
    os.environ["DATABASE_PATH"] = db
    os.environ["LOG_LEVEL"] = "ERROR"
    from config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    yield db
    settings_mod.get_settings.cache_clear()


def test_html_extraction_throughput():
    from engine.fastops import extract_html

    n = 500
    t0 = time.perf_counter()
    for _ in range(n):
        result = extract_html(SAMPLE_HTML)
    elapsed = time.perf_counter() - t0
    rate = n / elapsed
    assert result.title.startswith("Pharmacie")
    assert rate >= 2000, f"html extraction regressed: {rate:,.0f}/s (< 2000/s)"


def test_scoring_batch_throughput():
    from engine.fastops import score_batch

    rng = random.Random(3)
    n = 50_000
    flags = [rng.getrandbits(9) for _ in range(n)]
    soc = [rng.randint(0, 3) for _ in range(n)]
    fr = [rng.randint(0, 4) for _ in range(n)]
    t0 = time.perf_counter()
    priorities, _ = score_batch(flags, soc, fr)
    elapsed = time.perf_counter() - t0
    assert len(priorities) == n
    assert elapsed < 1.0, f"score_batch regressed: {elapsed:.2f}s for 50k leads"


def test_upsert_throughput_and_atomicity():
    from infrastructure.storage import DatabaseManager, LeadRepository

    repo = LeadRepository(DatabaseManager(Path(os.environ["DATABASE_PATH"])))

    async def sequential() -> None:
        for i in range(100):
            await repo.upsert(Lead(name=f"Biz {i}", wilaya="Alger", phone=f"+213555{i:07d}"))

    t0 = time.perf_counter()
    asyncio.run(sequential())
    rate = 100 / (time.perf_counter() - t0)
    assert rate >= 100, f"upsert throughput regressed: {rate:,.0f}/s"

    async def concurrent_same() -> tuple[set[int], int]:
        lead = Lead(name="Atlas", wilaya="Oran", website="https://atlas.dz")
        results = await asyncio.gather(*[repo.upsert(lead) for _ in range(30)])
        return {r[0] for r in results}, sum(1 for r in results if isinstance(r, Exception))

    ids, exceptions = asyncio.run(concurrent_same())
    assert exceptions == 0
    assert len(ids) == 1


def test_unified_listing_latency():
    from infrastructure.storage import DatabaseManager, LeadRepository

    repo = LeadRepository(DatabaseManager(Path(os.environ["DATABASE_PATH"])))
    t0 = time.perf_counter()
    n = 30
    for _ in range(n):
        asyncio.run(repo.list_leads(q="Biz", wilaya="Alger", limit=50))
    per_call = (time.perf_counter() - t0) / n
    assert per_call < 0.25, f"composed listing regressed: {per_call * 1000:.0f} ms/call"


def test_geo_lookup_latency():
    from engine.geo import get_geo_service

    geo = get_geo_service()
    rng = random.Random(11)
    points = [(rng.uniform(-8.5, 11.8), rng.uniform(19.5, 36.9)) for _ in range(5000)]
    t0 = time.perf_counter()
    hits = sum(1 for lon, lat in points if geo.lookup(lon, lat) is not None)
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, f"point-in-wilaya regressed: {elapsed:.2f}s for 5k points"
    assert hits > 2000  # roughly country-shaped coverage


def test_api_endpoint_latencies():
    from api.server import create_app

    with TestClient(create_app()) as app_client:
        budgets = {
            "/health": 0.1,
            "/api/v2/stats": 0.15,
            "/api/v2/geo/wilayas": 0.15,
            "/api/v2/leads?limit=50": 0.15,
        }
        for path, budget in budgets.items():
            t0 = time.perf_counter()
            n = 10
            for _ in range(n):
                response = app_client.get(path)
                assert response.status_code == 200, f"{path}: {response.status_code}"
            per_call = (time.perf_counter() - t0) / n
            assert per_call < budget, f"{path} regressed: {per_call * 1000:.0f} ms/call"
