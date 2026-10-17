"""Business Entity Resolution & Aggregation — v3.1 test suite.

The acceptance scenarios come verbatim from the feature spec:

- five Café Atlas records (website, Google profile, Facebook, Instagram,
  directory) are ONE entity with five source records;
- Café Atlas Algiers and Café Atlas Oran are TWO entities despite
  identical names;
- chain branches share an organization but stay separate location-level
  entities, linked by a relation;
- names alone never merge; ambiguous pairs wait in the review queue;
- merges are explainable (decision log with per-signal evidence) and
  reversible (split + pinned manual decisions);
- incremental resolution grows existing clusters without duplicating them.
"""

from __future__ import annotations

import pytest

from domain.enums import DataSource
from domain.models import Lead
from engine.resolution import EntityResolver
from engine.resolution.canonical import CanonicalBuilder
from engine.resolution.classifier import DISTINCT, RELATED, SAME, UNRESOLVED
from engine.resolution.features import extract_features, name_key, phone_digits


def _lead(**kw) -> Lead:
    defaults = dict(name="", industry="restaurant", source=DataSource.MOCK)
    defaults.update(kw)
    return Lead(**defaults)


# ---------------------------------------------------------------------------
# Scenario 1: five channels, one restaurant -> one canonical entity
# ---------------------------------------------------------------------------

def _cafe_atlas_five() -> list[Lead]:
    leads = [
        _lead(
            name="Café Atlas", wilaya="Alger",
            website="https://cafeatlas.dz", phone="+213555112233",
            address="12 Rue Didouche Mourad, Alger",
            social_links=["https://facebook.com/cafeatlas",
                          "https://instagram.com/cafeatlas"],
        ),
        _lead(
            name="Cafe Atlas", wilaya="Alger",
            website="https://www.cafeatlas.dz/", phone="+213 555 112 233",
            address="12 rue Didouche Mourad, Alger",
            latitude=36.7753, longitude=3.0602,
        ),
        _lead(
            name="Café Atlas", wilaya="Alger", phone="+213555112233",
            website="https://cafeatlas.dz",
            source_url="https://facebook.com/cafeatlas",
        ),
        _lead(
            name="cafe_atlas", wilaya="Alger", website="cafeatlas.dz",
            source_url="https://instagram.com/cafeatlas",
        ),
        _lead(
            name="Café Atlas Restaurant", wilaya="Alger",
            website="http://cafeatlas.dz/contact", phone="0555 11 22 33",
            address="12 Rue Didouche Mourad, Alger",
        ),
    ]
    for i, lead in enumerate(leads, start=1):
        lead.id = i
    return leads


def test_five_channel_aggregation():
    leads = _cafe_atlas_five()
    groups, result = EntityResolver().resolve(leads)

    assert len(groups) == 1 and len(groups[0]) == 5, \
        "all five records must aggregate into one entity"
    assert result.decisions_same >= 4

    record = result.canonical_records[0]
    # Canonical name is the majority display variant, not the snake_case
    # Instagram export and not the directory's suffixed form.
    assert record["name"] == "Café Atlas"
    assert "Café Atlas Restaurant" in record["aliases"]
    assert len(record["members"]) == 5
    # Provenance is recorded per field.
    assert record["canonical_fields"]["name"]["source"] == "mock"
    # The entity carries its resolution evidence.
    assert record["evidence"]["merge_edges"] >= 4
    assert "phone" in record["evidence"]["top_signals"]


def test_five_channel_evidence_explanations():
    _, result = EntityResolver().resolve(_cafe_atlas_five())
    same = [d for d in result.decisions if d.decision == SAME]
    assert same
    for d in same:
        assert d.explanation.startswith("same entity:")
        # Full per-signal evidence rides along for the decision log.
        assert d.signals["signals"], "logged decisions carry signal detail"


# ---------------------------------------------------------------------------
# Scenario 2: identical names, different businesses
# ---------------------------------------------------------------------------

def _cafe_atlas_two_cities() -> list[Lead]:
    leads = [
        _lead(name="Café Atlas", wilaya="Alger", industry="restaurant",
              website="https://cafeatlas-alger.dz", phone="+213555112233",
              address="12 Rue Didouche Mourad, Alger",
              email="contact@cafeatlas-alger.dz"),
        _lead(name="Café Atlas", wilaya="Oran", industry="restaurant",
              website="https://cafeatlas-oran.dz", phone="+213661445566",
              address="45 Boulevard de la Soummam, Oran",
              email="contact@cafeatlas-oran.dz"),
    ]
    for i, lead in enumerate(leads, start=1):
        lead.id = i
    return leads


def test_same_name_different_cities_stay_separate():
    groups, result = EntityResolver().resolve(_cafe_atlas_two_cities())

    assert len(groups) == 2, "two distinct businesses must remain separate"
    assert result.decisions_distinct == 1
    assert result.decisions_same == 0

    d = result.decisions[0]
    assert d.decision == DISTINCT
    # The explanation must say WHY identical names were kept apart.
    assert "disjoint phones" in d.explanation
    assert "different wilayas" in d.explanation
    assert d.signals["name_sim"] == 1.0, "names match perfectly and still distinct"


def test_same_name_same_city_no_evidence_goes_to_review():
    leads = [
        _lead(name="Café Atlas", wilaya="Alger"),
        _lead(name="Café Atlas", wilaya="Alger"),
    ]
    groups, result = EntityResolver().resolve(leads)

    assert len(groups) == 2, "names alone must never establish identity"
    assert result.review_queued == 1
    item = result.review_items[0]
    assert item["explanation"].startswith("unresolved:")
    assert item["evidence"]["identity"] < 0.7


# ---------------------------------------------------------------------------
# Scenario 3: related entities (branches, shared owner) — linked, not merged
# ---------------------------------------------------------------------------

def test_chain_branches_related_not_merged():
    leads = [
        _lead(name="Café Atlas Alger", wilaya="Alger",
              website="https://cafeatlas.dz/alger", phone="+213555112233",
              address="12 Rue Didouche Mourad, Alger"),
        _lead(name="Café Atlas Oran", wilaya="Oran",
              website="https://cafeatlas.dz/oran", phone="+213661445566",
              address="45 Boulevard de la Soummam, Oran"),
    ]
    groups, result = EntityResolver().resolve(leads)

    assert len(groups) == 2, "branches stay separate location-level entities"
    assert result.decisions_related == 1
    assert len(result.relations) == 1

    rel = result.relations[0]
    assert rel["relationship"] == "branch_of"
    assert rel["group_a"] != rel["group_b"]
    assert "shared domain" in rel["explanation"]

    # Both singletons participate in a relation -> both get stored as
    # entities (so the relation has endpoints).
    stored_groups = {r["group_index"] for r in result.canonical_records}
    assert stored_groups == {0, 1}


def test_shared_owner_hotline_related_not_merged():
    """Two different restaurants run by one owner: shared central phone
    and email domain, different verified addresses -> RELATED."""
    leads = [
        _lead(name="Restaurant Le Dauphin", wilaya="Alger",
              website="https://dauphin-alger.dz", phone="+213770100100",
              email="contact@groupe-dauphin.dz",
              address="10 Rue Larbi Ben Mhidi, Alger"),
        _lead(name="Restaurant Le Dauphin Oran", wilaya="Oran",
              website="https://dauphin-oran.dz", phone="+213770100100",
              email="reservations@groupe-dauphin.dz",
              address="20 Boulevard Millenium, Oran"),
    ]
    groups, result = EntityResolver().resolve(leads)

    # Same phone would normally merge (identity 0.8), but two verified
    # disjoint addresses in different wilayas prove two locations.
    assert len(groups) == 2, "shared owner must not merge two businesses"
    assert result.decisions_related == 1
    assert result.relations[0]["relationship"] == "same_owner"


# ---------------------------------------------------------------------------
# Scenario 4: geography never vetoes strong identity evidence
# ---------------------------------------------------------------------------

def test_stale_wilaya_does_not_veto_strong_identity():
    """One restaurant whose Facebook profile still carries an old wilaya:
    shared phone + domain + address outweighs the geographic mismatch."""
    leads = [
        _lead(name="Café Atlas", wilaya="Alger", phone="+213555112233",
              website="https://cafeatlas.dz",
              address="12 Rue Didouche Mourad, Alger"),
        _lead(name="Cafe Atlas", wilaya="Oran", phone="+213555112233",
              website="https://cafeatlas.dz",
              address="12 Rue Didouche Mourad, Alger"),
    ]
    groups, result = EntityResolver().resolve(leads)

    assert len(groups) == 1, "identity evidence survives stale geography"
    assert result.decisions_same == 1


def test_domain_plus_neighbourhood_pins_do_not_auto_merge():
    """Blind chain branches: shared domain, pins a few km apart, no
    phones/addresses. Ambiguous by construction -> review, not merge."""
    leads = [
        _lead(name="Café Atlas Alger", wilaya="Alger",
              website="https://cafeatlas.dz",
              latitude=36.7500, longitude=3.0500),
        _lead(name="Café Atlas Bab Ezzouar", wilaya="Alger",
              website="https://cafeatlas.dz",
              latitude=36.7700, longitude=3.1800),   # ~12 km apart
    ]
    groups, result = EntityResolver().resolve(leads)

    assert len(groups) == 2, "no same-place proof -> no auto-merge"
    assert result.decisions_same == 0


# ---------------------------------------------------------------------------
# Feature normalization
# ---------------------------------------------------------------------------

def test_phone_digit_normalization():
    intl = _lead(name="X", phone="+213 555 112 233")
    national = _lead(name="Y", phone="0555 11 22 33")
    intl0 = _lead(name="Z", phone="+213(0)555 112 233")
    assert phone_digits(intl) == phone_digits(national) == {"213555112233"}
    assert phone_digits(intl0) == {"213555112233"}


def test_name_normalization_folds_variants():
    assert name_key("Café Atlas") == name_key("cafe atlas") == "cafeatlas"
    assert name_key("Boulangerie ETS Benali") == name_key("boulangerie benali")


def test_social_platform_urls_are_not_websites():
    f = extract_features(0, _lead(
        name="X", website="https://facebook.com/somepage",
        source_url="https://facebook.com/somepage",
    ))
    assert f.website_domain == "", "social URLs are identities, not websites"
    assert f.socials == {"facebook": "somepage"}


def test_wilaya_normalization_accepts_french_forms():
    f = extract_features(0, _lead(name="X", wilaya="Béjaïa"))
    g = extract_features(1, _lead(name="Y", wilaya="bejaia"))
    assert f.wilaya == g.wilaya


# ---------------------------------------------------------------------------
# Constrained clustering
# ---------------------------------------------------------------------------

def test_must_not_link_blocks_contradictory_transitive_merge():
    """A shares a phone with B, B shares (as a second listed number) a
    phone with C, but A and C are strongly-supported distinct businesses.
    Union-find would transitively merge A and C through B; the must-not-
    link constraint must block the weaker edge instead."""
    from domain.value_objects import PhoneDetails
    from domain.enums import PhoneType

    a = _lead(name="Café Atlas", wilaya="Alger", phone="+213555112233",
              website="https://cafeatlas-alger.dz",
              address="12 Rue Didouche Mourad, Alger",
              email="a@cafeatlas-alger.dz")
    c = _lead(name="Café Atlas", wilaya="Oran", phone="+213661445566",
              website="https://cafeatlas-oran.dz",
              address="45 Boulevard de la Soummam, Oran",
              email="b@cafeatlas-oran.dz")
    # B lists BOTH numbers (directories aggregate contact channels), so
    # B is SAME with A (shared phone) and SAME with C (shared phone).
    b = _lead(name="Cafe Atlas", phone_details=[
        PhoneDetails(original_string="0555 11 22 33", e164="+213555112233",
                     international="+213 555 112 233",
                     phone_type=PhoneType.MOBILE, is_valid=True),
        PhoneDetails(original_string="0661 44 55 66", e164="+213661445566",
                     international="+213 661 445 566",
                     phone_type=PhoneType.MOBILE, is_valid=True),
    ])
    leads = [a, c, b]
    for i, lead in enumerate(leads, start=1):
        lead.id = i

    groups, result = EntityResolver().resolve(leads)

    # A (0) and C (1) may never share a cluster, no matter what B ties to.
    by_lead = {}
    for gi, group in enumerate(groups):
        for idx in group:
            by_lead[idx] = gi
    assert by_lead[0] != by_lead[1], \
        "a must-not-link pair must never end up merged transitively"
    # The blocked edge is reported, not silently dropped.
    assert result.edges_skipped >= 1
    assert result.contradictions


def test_incremental_mode_preseeds_existing_clusters():
    """Incremental run: existing memberships are ground truth; the new
    record joins its cluster without re-litigating old decisions."""
    base = _cafe_atlas_five()
    groups, first = EntityResolver().resolve(base)
    assert len(groups) == 1

    # Persist a hypothetical cluster id, then add a new directory record.
    for lead in base:
        lead.cluster_id = 7
    extra = _lead(name="Café Atlas (Alger)", wilaya="Alger",
                  website="https://cafeatlas.dz", phone="+213555112233")
    extra.id = 6
    new_leads = base + [extra]
    new_indices = {len(new_leads) - 1}
    groups2, second = EntityResolver().resolve(
        new_leads, new_indices=new_indices
    )

    assert second.mode == "incremental"
    # Only pairs involving the new record were scored.
    assert second.candidate_pairs < first.candidate_pairs
    # The new record joined the existing entity.
    merged = next(g for g in groups2 if len(g) > 1)
    assert len(merged) == 6
    # Only the affected cluster is marked for persistence.
    assert len(second.canonical_records) == 1
    assert len(second.canonical_records[0]["members"]) == 6


def test_manual_overrides_beat_the_engine():
    """A pinned manual DISTINCT survives even overwhelming evidence; a
    pinned manual SAME forces a merge the engine would not make."""
    leads = _cafe_atlas_five()
    ids = [101, 102, 103, 104, 105]
    for lead, i in zip(leads, ids):
        lead.id = i

    overrides = [{"lead_a": 101, "lead_b": 102, "decision": "distinct"}]
    groups, result = EntityResolver().resolve(leads, manual_overrides=overrides)

    by_lead = {}
    for gi, group in enumerate(groups):
        for idx in group:
            by_lead[idx] = gi
    assert by_lead[0] != by_lead[1], "manual distinct is pinned"
    assert any(d.decided_by == "manual" for d in result.decisions)

    # Pinned same forces a merge between two unrelated records.
    leads = _cafe_atlas_two_cities()
    leads[0].id, leads[1].id = 201, 202
    overrides = [{"lead_a": 201, "lead_b": 202, "decision": "same"}]
    groups, result = EntityResolver().resolve(leads, manual_overrides=overrides)
    assert len(groups) == 1, "manual same is pinned"
    assert result.decisions_same == 1


def test_native_fallback_parity_v31():
    """Native SIMD and pure-Python paths produce identical clusters,
    relations, and review queues."""
    from engine.native import NativeEngine

    leads = _cafe_atlas_five() + _cafe_atlas_two_cities()
    native_resolver = EntityResolver()
    fallback_resolver = EntityResolver(native=NativeEngine.__new__(NativeEngine))
    fallback_resolver._native._lib = None

    g_native, r_native = native_resolver.resolve(leads)
    g_fallback, r_fallback = fallback_resolver.resolve(leads)

    assert g_native == g_fallback
    assert r_native.relations == r_fallback.relations
    assert r_native.review_queued == r_fallback.review_queued


# ---------------------------------------------------------------------------
# Canonical record: conflict resolution with provenance
# ---------------------------------------------------------------------------

def test_canonical_conflict_resolution_records_alternatives():
    manual = _lead(name="Café Atlas", wilaya="Alger", phone="+213999000111",
                   website="https://official.dz", email="x@official.dz",
                   source=DataSource.MANUAL)
    social = _lead(name="Cafe Atlas", wilaya="Alger", phone="+213555112233",
                   website="https://old-site.dz", source=DataSource.SOCIAL)
    manual.id, social.id = 1, 2

    record = CanonicalBuilder.build([manual, social])

    # Manual curation outranks a social profile for factual fields.
    assert record["canonical_fields"]["phone"]["value"] == "+213999000111"
    assert record["canonical_fields"]["phone"]["lead_id"] == 1
    # The disagreement is recorded, not overwritten.
    assert record["canonical_fields"]["phone"]["conflict"] is True
    assert record["canonical_fields"]["phone"]["alternatives"] == [
        {"value": "+213555112233", "lead_id": 2, "source": "social"}
    ]
    # Names are voted (both variants normalize identically -> display vote
    # falls back to trust: manual wins).
    assert record["name"] == "Café Atlas"


def test_canonical_confidence_reflects_weakest_edge():
    strong = CanonicalBuilder.confidence(3, {"min_edge_identity": 1.5})
    weak = CanonicalBuilder.confidence(3, {"min_edge_identity": 0.75})
    assert strong > weak
    assert weak >= 0.8, "even weak-edge clusters stay reasonably confident"
    assert CanonicalBuilder.confidence(1, None) == 1.0


# ---------------------------------------------------------------------------
# Service + API level: persistence, review queue, split, merge, incremental
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "er_test.db"))
    monkeypatch.setenv("ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))

    from config import settings as settings_mod
    settings_mod.get_settings.cache_clear()

    from api.server import create_app
    from fastapi.testclient import TestClient

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    from infrastructure.http import HttpClientFactory
    HttpClientFactory.reset()
    settings_mod.get_settings.cache_clear()


def _seed(client, **overrides) -> int:
    payload = dict(name="Café Atlas", industry="restaurant", wilaya="Alger")
    payload.update(overrides)
    resp = client.post("/api/v2/leads/manual", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()["lead_id"]


def test_api_full_resolution_flow_with_relations(client):
    """The spec's three outcomes end-to-end over the API:
    aggregation, separation, and related-but-distinct.

    Seeds are fingerprint-distinct (national vs international phone
    formats, website presence) but evidence-compatible, so all records
    insert and the resolver does the aggregation.
    """
    # One restaurant, five channels. Fingerprints differ (website path,
    # name variants, phone presence) so every record inserts; the
    # evidence (registrable domain, normalized phones, addresses, social
    # links) is what drives the aggregation.
    _seed(client, name="Café Atlas", website="https://cafeatlas.dz",
          phone="+213555112233", address="12 Rue Didouche Mourad, Alger")
    _seed(client, name="Cafe Atlas", website="https://cafeatlas.dz/fr",
          phone="0555 11 22 33", address="12 rue Didouche Mourad, Alger")
    _seed(client, name="Café Atlas", phone="+213555112233")
    _seed(client, name="cafe_atlas", website="cafeatlas.dz/contact",
          address="12 Rue Didouche Mourad, Alger")
    _seed(client, name="Café Atlas Restaurant", website="https://cafeatlas.dz",
          phone="0555 11 22 33", address="12 Rue Didouche Mourad, Alger")
    # A second, independently operated restaurant with the same name.
    oran_id = _seed(client, name="Café Atlas", wilaya="Oran",
                    website="https://cafeatlas-oran.dz",
                    phone="+213661445566", address="45 Boulevard de la Soummam, Oran")
    # A branch of the first restaurant's chain in a third city.
    _seed(client, name="Café Atlas Constantine", wilaya="Constantine",
          website="https://cafeatlas.dz/constantine", phone="+213771223344",
          address="5 Rue Mellah Ali, Constantine")

    body = client.post("/api/v2/entities/resolve").json()
    assert body["clusters_stored"] >= 2

    entities = client.get("/api/v2/entities").json()["entities"]
    by_members = {e["member_count"]: e for e in entities}

    # Outcome 1: five channels -> ONE entity with five source records.
    assert 5 in by_members
    merged = by_members[5]
    assert merged["name"] == "Café Atlas"
    assert merged["aliases"], "name variants survive as aliases"
    lineage = client.get(f"/api/v2/entities/{merged['id']}/lineage").json()["lineage"]
    assert len(lineage) == 5, "source records preserved with provenance"

    # Outcome 2: the Oran restaurant stays its own entity — never merged
    # despite the identical name. As a plain distinct singleton it is not
    # part of any cluster at all.
    oran_lead = client.get(f"/api/v2/leads/{oran_id}").json()
    assert oran_lead["cluster_id"] is None
    assert oran_id not in [l["id"] for l in lineage]
    # And the decision that kept them apart is queryable with evidence.
    evidence = client.get(f"/api/v2/entities/{merged['id']}/evidence").json()["evidence"]
    assert any(e["decision"] == "distinct" for e in evidence)

    # Outcome 3: the Constantine branch is related, not merged.
    branch = next(e for e in entities if e["wilaya"] == "Constantine")
    assert branch["member_count"] == 1
    relations = client.get(f"/api/v2/entities/{merged['id']}/relations").json()["relations"]
    assert len(relations) == 1
    assert relations[0]["relationship"] == "branch_of"
    assert relations[0]["other_cluster_id"] == branch["id"]


def test_api_incremental_resolution_grows_clusters_without_duplicates(client):
    _seed(client, name="Café Atlas", website="https://cafeatlas.dz",
          phone="+213555112233")
    _seed(client, name="Cafe Atlas", website="https://cafeatlas.dz/fr",
          phone="0555 11 22 33")

    first = client.post("/api/v2/entities/resolve").json()
    assert first["clusters_stored"] == 1
    cluster_id = client.get("/api/v2/entities").json()["entities"][0]["id"]
    assert client.get("/api/v2/entities").json()["entities"][0]["member_count"] == 2

    # A new duplicate record arrives in a later campaign.
    _seed(client, name="Café Atlas", website="https://cafeatlas.dz/en",
          phone="0555 11 22 33")

    entities = client.get("/api/v2/entities").json()["entities"]
    assert len(entities) == 1, "no duplicate cluster before re-resolution"

    # Incremental mode: drive the service directly against the same DB.
    import asyncio
    from infrastructure.storage.cluster_repo import ClusterRepository
    from infrastructure.storage.database import DatabaseManager
    from infrastructure.storage.lead_repo import LeadRepository
    from services.discovery_service import ResolutionService

    leads_list = client.get("/api/v2/leads", params={"limit": 50}).json()["leads"]
    latest = max(l["id"] for l in leads_list)

    db = DatabaseManager()
    service = ResolutionService(
        LeadRepository(db), ClusterRepository(db)
    )
    report = asyncio.run(service.resolve_incremental([latest]))

    assert report["mode"] == "incremental"
    entities = client.get("/api/v2/entities").json()["entities"]
    assert len(entities) == 1, "the cluster grew, no duplicate was created"
    assert entities[0]["member_count"] == 3
    assert entities[0]["id"] == cluster_id, "cluster id is stable"


def test_api_review_queue_flow(client):
    """An ambiguous pair lands in the review queue with its evidence;
    a human keeps it separate; the engine respects that forever."""
    _seed(client, name="Café Atlas", wilaya="Alger", phone=None)      # no contact data
    _seed(client, name="Café Atlas", wilaya="Alger",
          phone="+213555112233")                                       # one-sided phone

    client.post("/api/v2/entities/resolve")
    queue = client.get("/api/v2/entities/review").json()["items"]
    assert len(queue) == 1
    item = queue[0]
    assert item["explanation"].startswith("unresolved:")
    assert item["evidence"]["signals"], "review items carry full evidence"

    stats = client.get("/api/v2/entities/stats").json()
    assert stats["pending_review"] == 1

    resp = client.post(
        f"/api/v2/entities/review/{item['id']}/resolve",
        json={"decision": "keep_separate"},
    )
    assert resp.status_code == 200
    assert resp.json()["action"] == "kept_separate"

    # The queue is drained and the pair is pinned distinct.
    assert client.get("/api/v2/entities/review").json()["count"] == 0
    client.post("/api/v2/entities/resolve")
    queue = client.get("/api/v2/entities/review").json()["items"]
    assert len(queue) == 0, "pinned decisions are not re-queued"
    entities = client.get("/api/v2/entities").json()["entities"]
    assert all(e["member_count"] == 1 for e in entities)


def test_api_review_merge_decision(client):
    _seed(client, name="Café Atlas", wilaya="Alger", phone="+213555112233",
          website=None, address=None)
    _seed(client, name="Café Atlas DZ", wilaya="Alger",
          website="https://cafeatlas.dz", phone=None, address=None)

    client.post("/api/v2/entities/resolve")
    queue = client.get("/api/v2/entities/review").json()["items"]
    assert queue, "ambiguous pair is queued"

    resp = client.post(
        f"/api/v2/entities/review/{queue[0]['id']}/resolve",
        json={"decision": "merge"},
    )
    assert resp.status_code == 200
    assert resp.json()["action"] == "merged"

    entities = client.get("/api/v2/entities").json()["entities"]
    assert any(e["member_count"] == 2 for e in entities)


def test_api_split_reverses_incorrect_merge(client):
    """A wrong merge is split back apart; source records survive and the
    split is pinned against future automated runs."""
    a = _seed(client, name="Café Atlas", phone="+213555112233")
    b = _seed(client, name="Cafe Atlas", phone="0555 11 22 33")
    _seed(client, name="Café Atlas Oran", wilaya="Oran", phone="+213661445566")

    client.post("/api/v2/entities/resolve")
    entities = client.get("/api/v2/entities").json()["entities"]
    merged = next(e for e in entities if e["member_count"] == 2)

    # A human realizes the two records are different businesses.
    resp = client.post(
        f"/api/v2/entities/{merged['id']}/split",
        json={"groups": [[a], [b]]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["cluster_ids"]) == 2
    assert body["pinned_decisions"] >= 1

    # Source records untouched: both leads still exist with their data.
    lead_a = client.get(f"/api/v2/leads/{a}").json()
    lead_b = client.get(f"/api/v2/leads/{b}").json()
    assert lead_a["name"] == "Café Atlas" and lead_b["name"] == "Cafe Atlas"
    assert lead_a["cluster_id"] != lead_b["cluster_id"]

    # Re-running the engine must NOT re-merge a human split. (Singleton
    # clusters may be pruned by a full re-resolve — the pins live in the
    # decision log, not in the cluster rows.)
    client.post("/api/v2/entities/resolve")
    lead_a = client.get(f"/api/v2/leads/{a}").json()
    lead_b = client.get(f"/api/v2/leads/{b}").json()
    co_clustered = (
        lead_a["cluster_id"] is not None
        and lead_a["cluster_id"] == lead_b["cluster_id"]
    )
    assert not co_clustered, "split is pinned across runs"

    # Invalid partitions are rejected with a clear error.
    surviving = lead_a["cluster_id"] or merged["id"]
    resp = client.post(
        f"/api/v2/entities/{surviving}/split",
        json={"groups": [[999], [b]]},
    )
    assert resp.status_code == 400


def test_api_manual_merge_clusters(client):
    """Two clusters a human confirms are one entity get merged, with a
    stable surviving id and pinned decisions."""
    _seed(client, name="Café Atlas", phone="+213555112233",
          website="https://cafeatlas.dz", address="12 Rue Didouche, Alger")
    _seed(client, name="Cafe Atlas", phone="0555 11 22 33",
          website="https://cafeatlas.dz", address="12 Rue Didouche, Alger")
    _seed(client, name="Atlas Café", wilaya="Oran", phone="+213661445566",
          website="https://atlas-oran.dz", address="1 Rue Emir, Oran")
    _seed(client, name="Atlas Cafe", wilaya="Oran", phone="0661 44 55 66",
          website="https://atlas-oran.dz", address="1 Rue Emir, Oran")

    client.post("/api/v2/entities/resolve")
    entities = client.get("/api/v2/entities").json()["entities"]
    ids = [e["id"] for e in entities]
    assert len(ids) == 2, "two multi-member clusters before the manual merge"

    resp = client.post("/api/v2/entities/merge", json={"cluster_ids": ids})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cluster_id"] == min(ids)
    assert body["absorbed"] == [max(ids)]

    entities = client.get("/api/v2/entities").json()["entities"]
    assert len(entities) == 1 and entities[0]["member_count"] == 4

    # The merge is pinned: re-resolution keeps them together.
    client.post("/api/v2/entities/resolve")
    entities = client.get("/api/v2/entities").json()["entities"]
    assert len(entities) == 1 and entities[0]["member_count"] == 4
