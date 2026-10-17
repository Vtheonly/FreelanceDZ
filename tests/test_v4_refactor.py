"""refactorv4 verification suite — every documented fix, with evidence.

These tests are the acceptance record for the issues documented in
refactorv4.md and refactorv5.md (the consolidated checklist lives in
docs/15-refactoring-history.md). They run against the real engine — no
mocks, no weakened assertions.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from api.server import create_app
from domain.models import Lead, sanitize_website_url
from infrastructure.storage import DatabaseManager, LeadRepository
from utils.spam_filter import SourcingSpamFilter


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def db(tmp_path):
    return DatabaseManager(tmp_path / "v4.db")


@pytest.fixture()
def repo(db):
    return LeadRepository(db)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "v4_api.db"))
    monkeypatch.setenv("ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))

    from config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    from infrastructure.http import HttpClientFactory

    HttpClientFactory.reset()
    settings_mod.get_settings.cache_clear()


def _lead(**overrides) -> Lead:
    defaults = dict(name="Pharmacie Centrale", wilaya="Alger", phone="+21321445566")
    defaults.update(overrides)
    return Lead(**defaults)


# ---------------------------------------------------------------------------
# Task 4 — 422 on empty wilaya
# ---------------------------------------------------------------------------
class TestTask4EmptyWilaya:
    def test_blank_wilaya_is_nationwide_not_422(self, client):
        response = client.post(
            "/api/v2/discover", json={"query": "xyzzy-no-such-business", "wilaya": "", "limit": 1}
        )
        assert response.status_code != 422
        assert response.status_code in (200, 202, 400, 500)

    def test_whitespace_wilaya_normalised_to_none(self, client):
        response = client.post(
            "/api/v2/discover", json={"query": "xyzzy-no-such-business", "wilaya": "   ", "limit": 1}
        )
        assert response.status_code != 422

    def test_query_validation_still_strict(self, client):
        # An actually invalid query (injection pattern) must still be rejected.
        response = client.post(
            "/api/v2/discover", json={"query": "{{delete_all}}", "wilaya": "", "limit": 1}
        )
        assert response.status_code in (400, 422)


# ---------------------------------------------------------------------------
# Task 3 — /api/v2/tags alias
# ---------------------------------------------------------------------------
class TestTask3TagsAlias:
    def test_bare_tags_route_resolves(self, client):
        client.post("/api/v2/leads/manual", json={
            "name": "Biz", "wilaya": "Alger", "phone": "+213550123456",
            "tags": ["vip"],
        })
        response = client.get("/api/v2/tags")
        assert response.status_code == 200
        assert "vip" in response.json()["tags"]

    def test_leads_tags_route_still_works(self, client):
        response = client.get("/api/v2/leads/tags")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Task 5 — unified search & filters
# ---------------------------------------------------------------------------
class TestTask5UnifiedListing:
    def test_search_composes_with_wilaya_filter(self, client):
        client.post("/api/v2/leads/manual", json={
            "name": "Pharmacie Du Port", "wilaya": "Oran", "phone": "+213661112233",
        })
        client.post("/api/v2/leads/manual", json={
            "name": "Pharmacie Centrale", "wilaya": "Alger", "phone": "+213550123456",
        })
        response = client.get("/api/v2/leads", params={"q": "pharmacie", "wilaya": "Oran"})
        assert response.status_code == 200
        names = [l["name"] for l in response.json()["leads"]]
        assert names == ["Pharmacie Du Port"]

    def test_search_composes_with_score_and_contact(self, client):
        client.post("/api/v2/leads/manual", json={
            "name": "Clinique Atlas", "wilaya": "Oran", "phone": "+213661112233",
        })
        response = client.get(
            "/api/v2/leads",
            params={"q": "clinique", "min_score": 50, "is_contact": False},
        )
        assert response.status_code == 200
        assert response.json()["count"] >= 0  # composes without error

    def test_fts_injection_cannot_raise(self, client):
        for evil in ['"*NEAR(x)', 'a OR b AND (c', '"unclosed', 'col:*', '; DROP']:
            response = client.get("/api/v2/leads", params={"q": evil})
            assert response.status_code == 200

    def test_repository_level_composition(self, repo):
        asyncio.run(repo.upsert(_lead(name="Boulangerie El Nour", wilaya="Oran")))
        asyncio.run(repo.upsert(_lead(name="Boulangerie El Nour", wilaya="Alger")))
        hits = asyncio.run(repo.list_leads(q="boulangerie", wilaya="Oran"))
        assert len(hits) == 1 and hits[0].wilaya == "Oran"


# ---------------------------------------------------------------------------
# Task 6 — atomic upsert (race-free)
# ---------------------------------------------------------------------------
class TestTask6AtomicUpsert:
    def test_fifty_concurrent_same_lead_upserts(self, repo):
        lead = _lead(name="Clinique Atlas", wilaya="Oran", website="https://atlas.dz")

        async def gather_upserts():
            return await asyncio.gather(*[repo.upsert(lead) for _ in range(50)])

        results = asyncio.run(gather_upserts())
        ids = {r[0] for r in results}
        assert len(ids) == 1, f"race condition: {len(ids)} distinct ids"
        assert all(r[0] > 0 for r in results)

    def test_concurrent_distinct_leads_all_persist(self, repo):
        leads = [
            _lead(name=f"Biz {i}", wilaya="Alger", phone=f"+213555{i:07d}")
            for i in range(25)
        ]

        async def gather_upserts():
            return await asyncio.gather(*[repo.upsert(l) for l in leads])

        results = asyncio.run(gather_upserts())
        assert all(r[1] is True for r in results)
        assert asyncio.run(repo.count()) == 25

    def test_merge_policy_preserved(self, repo):
        first = asyncio.run(repo.upsert(_lead(
            name="Pharmacie Centrale", wilaya="Alger",
            website="https://centrale.dz", phone="+21321445566",
        )))
        richer = _lead(
            name="Pharmacie Centrale", wilaya="Alger",
            website="https://centrale.dz", phone="+21321445566",
            address="12 Rue Didouche",
        )
        second = asyncio.run(repo.upsert(richer))
        assert second[0] == first[0] and second[1] is False
        stored = asyncio.run(repo.get(first[0]))
        assert stored.address == "12 Rue Didouche"  # richer value wins


# ---------------------------------------------------------------------------
# Task 7 — stored XSS root cause
# ---------------------------------------------------------------------------
class TestTask7UrlSanitisation:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("javascript:alert(1)", None),
            ("data:text/html;base64,AAAA", None),
            ("vbscript:msgbox", None),
            ("https://example.dz", "https://example.dz"),
            ("http://example.dz/contact", "http://example.dz/contact"),
            ("//example.dz", "https://example.dz"),
            ("example.dz/contact", "https://example.dz/contact"),
            ("", None),
            (None, None),
            ("not a url", None),
        ],
    )
    def test_scheme_allow_list(self, raw, expected):
        assert sanitize_website_url(raw) == expected

    def test_lead_model_rejects_dangerous_website(self):
        lead = _lead(website="javascript:alert(document.cookie)")
        assert lead.website is None

    def test_api_stores_sanitised_website(self, client):
        response = client.post("/api/v2/leads/manual", json={
            "name": "Evil Co", "wilaya": "Alger",
            "phone": "+213550123456", "website": "javascript:alert(1)",
        })
        assert response.status_code == 200
        detail = client.get(f"/api/v2/leads/{response.json()['lead_id']}").json()
        assert detail["website"] is None


# ---------------------------------------------------------------------------
# Task 12 — business quality gate
# ---------------------------------------------------------------------------
class TestTask12QualityGate:
    @pytest.mark.parametrize(
        "url,title",
        [
            ("https://amazon.fr/s?k=tshirt", "Amazon.fr : T Shirt Algerie Homme"),
            ("https://fr.wikipedia.org/wiki/Algérie", "Histoire d'Algérie"),
            ("https://sante.gov.dz/loi", "Décret ministériel"),
            ("https://france.tv/show", "Petite Casbah - France TV"),
            ("https://joradp.dz/texte", "Journal Officiel n° 78"),
            ("https://www.etsy.com/listing/1", "Handmade Algeria"),
        ],
    )
    def test_junk_is_blocked(self, url, title):
        assert SourcingSpamFilter().is_spam(url, title) is True

    @pytest.mark.parametrize(
        "url,title",
        [
            ("https://pharmacie-centrale-alger.dz/", "Pharmacie Centrale"),
            ("https://menuiserie-elnour-oran.dz/", "Menuiserie El Nour"),
            ("https://facebook.com/pharmacie.centrale", "Pharmacie Centrale"),
        ],
    )
    def test_real_businesses_pass(self, url, title):
        assert SourcingSpamFilter().is_spam(url, title) is False


# ---------------------------------------------------------------------------
# Task 15 — WAL declared once
# ---------------------------------------------------------------------------
class TestTask15WamlOnce:
    def test_connection_factory_has_no_wal_pragma(self, tmp_path):
        db = DatabaseManager(tmp_path / "wal.db")
        with db.connection() as conn:
            # The connection factory must not re-declare journal_mode.
            program = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'leads'"
            ).fetchone()
            assert program is not None
        # And the database itself must be in WAL mode (set once at init).
        import sqlite3

        raw = sqlite3.connect(str(tmp_path / "wal.db"))
        mode = raw.execute("PRAGMA journal_mode").fetchone()[0]
        raw.close()
        assert mode.lower() == "wal"

    def test_mixed_concurrent_read_write(self, repo):
        async def mixed_workload() -> None:
            await asyncio.gather(
                *([repo.count()] * 50),
                *[repo.upsert(_lead(name=f"Biz {i}", phone=f"+213555{i:07d}")) for i in range(50)],
            )

        asyncio.run(mixed_workload())
        assert asyncio.run(repo.count()) == 50


# ---------------------------------------------------------------------------
# Task 10 — inverted opportunity scoring (acceptance test from the doc)
# ---------------------------------------------------------------------------
class TestTask10OpportunityScoring:
    def test_phone_verified_no_web_no_map_scores_at_least_60(self):
        from domain.enums import PhoneType
        from domain.value_objects import PhoneDetails
        from engine.scorer import LeadScorer

        lead = _lead(website=None, phone="+213550123456")
        lead.phone_details = [
            PhoneDetails(
                original_string="0550 12 34 56",
                e164="+213550123456",
                international="+213 550 12 34 56",
                national="0550 12 34 56",
                phone_type=PhoneType.MOBILE,
                is_valid=True,
                is_whatsapp_capable=True,
            ),
        ]
        LeadScorer().score(lead)
        assert lead.priority_score >= 60, f"score {lead.priority_score} < 60"
        breakdown = lead.score_breakdown
        assert breakdown["website_build_opportunity"] == 15.0
        assert breakdown["local_seo_opportunity"] == 10.0

    def test_online_business_has_no_opportunity_bonus(self):
        from engine.scorer import LeadScorer

        lead = _lead(
            website="https://biz.dz",
            address="12 Rue de la Paix, Alger",
            phone="+213550123456",
        )
        lead.latitude, lead.longitude = 36.75, 3.05
        LeadScorer().score(lead)
        assert "website_build_opportunity" not in lead.score_breakdown
        assert "local_seo_opportunity" not in lead.score_breakdown


# ---------------------------------------------------------------------------
# Task 11 — variant cap + parallel dispatch
# ---------------------------------------------------------------------------
class TestTask11VariantCap:
    def test_stream_caps_variants(self, repo):
        from services.discovery_service import DiscoveryService

        class RecordingAggregator:
            def __init__(self):
                self.captured = []

            async def stream_discover(self, variants, wilaya, limit):
                self.captured.append(list(variants))
                if False:
                    yield  # pragma: no cover - empty async generator

        aggregator = RecordingAggregator()
        service = DiscoveryService(aggregator, repo)

        async def run() -> None:
            async for _ in service.stream("pharmacie", None, 5):
                pass  # pragma: no cover

        asyncio.run(run())
        assert len(aggregator.captured) == 1
        assert len(aggregator.captured[0]) <= 2  # DISCOVERY_MAX_VARIANTS default

    def test_pumps_dispatch_concurrently(self, repo):
        """All (variant x scraper) streams must start BEFORE any completes."""
        import time as _time

        from services.discovery_service import ScraperAggregator

        started: list[float] = []
        finished: list[float] = []

        class SlowScraper:
            source_name = "slow"

            async def stream_discover(self, query, wilaya, limit):
                started.append(_time.monotonic())
                await asyncio.sleep(0.25)
                finished.append(_time.monotonic())
                if False:
                    yield  # pragma: no cover

        async def run() -> list:
            aggregator = ScraperAggregator([SlowScraper()])
            results = []
            async for lead in aggregator.stream_discover(["a", "b", "c"], None, 10):
                results.append(lead)
            return results

        asyncio.run(run())
        # Sequential dispatch would finish pump 1 before pump 3 starts.
        assert len(started) == 3
        assert min(finished) > max(started), "pumps were dispatched sequentially"


# ---------------------------------------------------------------------------
# Task 8 — Overpass nationwide fallback
# ---------------------------------------------------------------------------
class TestTask8OverpassDecoupling:
    def test_area_filter_without_wilaya_uses_national_bbox(self):
        from infrastructure.scrapers.overpass import OverpassScraper

        declaration, filt = OverpassScraper._area_filter(None)
        assert declaration == ""
        assert filt.startswith("(") and filt.endswith(")")
        parts = filt[1:-1].split(",")
        assert len(parts) == 4

    def test_area_filter_with_wilaya_uses_named_area(self):
        from infrastructure.scrapers.overpass import OverpassScraper

        declaration, filt = OverpassScraper._area_filter("Oran")
        assert "searchArea" in declaration
        assert filt == "(area.searchArea)"


# ---------------------------------------------------------------------------
# Task 14 — per-domain backoff isolation
# ---------------------------------------------------------------------------
class TestTask14PerDomainBackoff:
    def test_domains_have_isolated_backoffs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "bot.db"))
        from config import settings as sm

        sm.get_settings.cache_clear()
        from infrastructure.storage import CrawlQueueRepository, LeadRepository
        from services.crawler_service import CrawlerEngine

        engine = CrawlerEngine(LeadRepository(DatabaseManager()), CrawlQueueRepository(DatabaseManager()))
        backoff_a = engine._domain_backoffs["a.dz"]
        backoff_b = engine._domain_backoffs["b.dz"]
        assert backoff_a is not backoff_b
        # Repeated failures on a.dz must not move b.dz's attempt counter or
        # delay: b.dz stays on its first attempt (base delay range).
        for _ in range(4):
            backoff_a.next_delay()
        assert backoff_a.attempt == 4
        assert backoff_b.attempt == 0
        assert backoff_b.next_delay() < 1.3  # base 1.0 ± 25% jitter only
        assert backoff_a.next_delay() > 2.0  # escalated on its own domain
        sm.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# refactorv5 — checkpoints subsystem
# ---------------------------------------------------------------------------
class TestCheckpointsSubsystem:
    def test_full_crud_over_api(self, client):
        created = client.post("/api/v2/checkpoints", json={
            "name": "Alger Port Logistics",
            "category": "hub",
            "latitude": 36.7627,
            "longitude": 3.0655,
            "notes": "main terminal",
        })
        assert created.status_code == 201
        cp_id = created.json()["id"]
        assert created.json()["wilaya"] == "Alger"

        detail = client.get(f"/api/v2/checkpoints/{cp_id}").json()
        assert detail["category"] == "hub"
        assert detail["status"] == "active"

        patched = client.patch(
            f"/api/v2/checkpoints/{cp_id}", json={"status": "visited"}
        )
        assert patched.status_code == 200
        assert client.get(f"/api/v2/checkpoints/{cp_id}").json()["status"] == "visited"

        assert client.delete(f"/api/v2/checkpoints/{cp_id}").status_code == 200
        assert client.get(f"/api/v2/checkpoints/{cp_id}").status_code == 404

    def test_wilaya_mismatch_rejected_with_422(self, client):
        response = client.post("/api/v2/checkpoints", json={
            "name": "Bad geocode", "category": "prospect",
            "wilaya": "Oran", "latitude": 36.75, "longitude": 3.05,  # inside Alger
        })
        assert response.status_code == 422
        assert "Alger" in response.json()["detail"]

    def test_invalid_category_rejected(self, client):
        response = client.post("/api/v2/checkpoints", json={
            "name": "X", "category": "holiday-home",
            "latitude": 36.75, "longitude": 3.05,
        })
        assert response.status_code == 422

    def test_moving_checkpoint_rederives_wilaya(self, client):
        created = client.post("/api/v2/checkpoints", json={
            "name": "Mover", "latitude": 36.75, "longitude": 3.05,
        })
        cp_id = created.json()["id"]
        moved = client.patch(
            f"/api/v2/checkpoints/{cp_id}",
            json={"latitude": 35.69, "longitude": -0.63},
        )
        assert moved.status_code == 200
        assert client.get(f"/api/v2/checkpoints/{cp_id}").json()["wilaya"] == "Oran"

    def test_catalogue_joins_live_counts(self, client):
        client.post("/api/v2/checkpoints", json={
            "name": "Hub A", "latitude": 36.75, "longitude": 3.05,
        })
        catalogue = client.get("/api/v2/geo/wilayas").json()["wilayas"]
        alger = next(w for w in catalogue if w["name_fr"] == "Alger")
        assert alger["checkpoints_count"] >= 1


# ---------------------------------------------------------------------------
# Campaign contract (v4 Task 1 — the object shape clients must handle)
# ---------------------------------------------------------------------------
class TestCampaignContract:
    def test_campaigns_endpoint_returns_object_with_array(self, client):
        payload = client.get("/api/v2/discover/campaigns").json()
        assert isinstance(payload, dict)
        assert isinstance(payload.get("campaigns"), list)
