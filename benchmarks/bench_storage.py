"""Storage & API throughput benchmarks.

Measures the engine's data-path performance with realistic workloads:
sequential and concurrent upserts, unified listing under filter
composition, aggregated wilaya counts, the geo catalogue endpoint
round-trip, and point-in-wilaya latency.

Usage: python benchmarks/bench_storage.py
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

WILAYAS = ["Alger", "Oran", "Blida", "Setif", "Annaba", "Constantine", "Tizi Ouzou"]


def _fmt_rate(n: int, seconds: float) -> str:
    return f"{n / max(seconds, 1e-9):>12,.0f}/s"


def _prepare(db_path: str) -> None:
    from domain.models import Lead
    from infrastructure.storage import DatabaseManager, LeadRepository

    db = DatabaseManager(Path(db_path))
    repo = LeadRepository(db)
    rng = random.Random(5)

    async def seed() -> None:
        for i in range(2000):
            await repo.upsert(Lead(
                name=f"Pharmacie {rng.choice(['Centrale', 'El Nour', 'Es Salem', 'Ennasr'])} {i}",
                wilaya=rng.choice(WILAYAS),
                phone=f"+213555{i:07d}",
                website=f"https://pharma-{i}.dz" if i % 2 else None,
            ))

    asyncio.run(seed())


def main() -> None:
    print("=" * 78)
    print("FREELANCEDZ STORAGE & API BENCHMARKS (v4)")
    print("=" * 78)

    db_path = tempfile.mktemp(suffix=".db")
    os.environ["DATABASE_PATH"] = db_path
    os.environ["LOG_LEVEL"] = "ERROR"
    from config import settings as settings_mod

    settings_mod.get_settings.cache_clear()

    from domain.models import Lead
    from engine.geo import get_geo_service
    from infrastructure.storage import DatabaseManager, LeadRepository

    db = DatabaseManager(Path(db_path))
    repo = LeadRepository(db)

    # ------------------------------------------------------------------
    print("\n[1] Upsert throughput (fresh database)")
    async def seq_upserts() -> None:
        for i in range(500):
            await repo.upsert(Lead(name=f"Biz {i}", wilaya="Alger", phone=f"+213555{i:07d}"))

    t0 = time.perf_counter()
    asyncio.run(seq_upserts())
    print(f"  sequential x500 (atomic ON CONFLICT)     {_fmt_rate(500, time.perf_counter() - t0)}")

    async def concurrent_same() -> tuple[int, int]:
        lead = Lead(name="Clinique Atlas", wilaya="Oran", website="https://atlas.dz")
        results = await asyncio.gather(*[repo.upsert(lead) for _ in range(50)])
        return len({r[0] for r in results}), sum(1 for r in results if isinstance(r, Exception))

    ids, errs = asyncio.run(concurrent_same())
    print(f"  50 concurrent same-lead upserts          ids={ids} exceptions={errs}")

    # ------------------------------------------------------------------
    print("\n[2] Seeding 2000 leads, then read paths")
    _prepare(db_path)
    settings_mod.get_settings.cache_clear()
    db = DatabaseManager(Path(db_path))
    repo = LeadRepository(db)

    async def measure(label: str, fn, n: int = 50) -> None:
        t0 = time.perf_counter()
        for _ in range(n):
            await fn()
        print(f"  {label:<42} {_fmt_rate(n, time.perf_counter() - t0)}")

    asyncio.run(measure("list_leads() page of 50", lambda: repo.list_leads(limit=50)))
    asyncio.run(measure("list_leads(wilaya=Oran) filtered", lambda: repo.list_leads(wilaya="Oran", limit=50)))
    asyncio.run(measure("list_leads(q='pharmacie' FTS)", lambda: repo.list_leads(q="pharmacie", limit=50)))
    asyncio.run(measure(
        "list_leads(q + wilaya + min_score composed)",
        lambda: repo.list_leads(q="pharmacie", wilaya="Oran", min_score=30, limit=50),
    ))
    asyncio.run(measure("stats()", lambda: repo.stats()))
    asyncio.run(measure("count_by_wilaya() (catalogue agg)", lambda: repo.count_by_wilaya()))
    asyncio.run(measure("all_tags()", lambda: repo.all_tags()))

    # ------------------------------------------------------------------
    print("\n[3] Geographic engine")
    geo = get_geo_service()
    rng = random.Random(11)
    points = [(rng.uniform(-8.5, 11.8), rng.uniform(19.5, 36.9)) for _ in range(20000)]
    t0 = time.perf_counter()
    hits = sum(1 for lon, lat in points if geo.lookup(lon, lat) is not None)
    elapsed = time.perf_counter() - t0
    print(f"  point-in-wilaya (20k random points)      {_fmt_rate(20000, elapsed)}  hit-rate={hits / 20000:.0%}")
    t0 = time.perf_counter()
    for _ in range(200):
        geo.wilaya_catalogue({"oran": 5}, {"oran": 2})
    print(f"  catalogue join (58 wilayas + counts)      {_fmt_rate(200, time.perf_counter() - t0)}")

    # ------------------------------------------------------------------
    print("\n[4] API round-trips (TestClient, no network)")
    from fastapi.testclient import TestClient

    from api.server import create_app

    with TestClient(create_app()) as client:
        endpoints = [
            ("GET /api/v2/stats", lambda: client.get("/api/v2/stats")),
            ("GET /api/v2/leads?limit=50", lambda: client.get("/api/v2/leads", params={"limit": 50})),
            ("GET /api/v2/leads?q=pharmacie&wilaya=Oran", lambda: client.get(
                "/api/v2/leads", params={"q": "pharmacie", "wilaya": "Oran"})),
            ("GET /api/v2/geo/wilayas", lambda: client.get("/api/v2/geo/wilayas")),
            ("GET /api/v2/geo/boundaries", lambda: client.get("/api/v2/geo/boundaries")),
            ("GET /health", lambda: client.get("/health")),
        ]
        for label, fn in endpoints:
            t0 = time.perf_counter()
            n = 50
            for _ in range(n):
                response = fn()
                assert response.status_code == 200, response.text
            elapsed = time.perf_counter() - t0
            per_call = elapsed / n * 1000
            print(f"  {label:<44} {per_call:6.2f} ms/call")

    print("\n" + "=" * 78)
    print("Regression thresholds live in tests/test_performance.py.")
    print("=" * 78)


if __name__ == "__main__":
    main()
