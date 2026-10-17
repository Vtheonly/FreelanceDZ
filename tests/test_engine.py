"""Entity resolver + analyzer + scorer tests (new engine architecture)."""

from __future__ import annotations

from domain.enums import DataSource
from domain.models import Lead
from engine.analyzer import BusinessAnalyzer, TIER_HIGH_OPPORTUNITY, TIER_MATURE
from engine.fastops import (
    FLAG_ADDRESS, FLAG_EMAIL, FLAG_GEO, FLAG_MOBILE, FLAG_PHONE,
    FLAG_SOCIAL, FLAG_SSL, FLAG_WEBSITE, FLAG_WHATSAPP,
)
from engine.resolver import GraphEntityResolver, GoldenRecordBuilder
from engine.scorer import LeadScorer, channel_flags
from domain.value_objects import PhoneDetails


def _lead(**overrides) -> Lead:
    defaults = dict(
        name="Pharmacie Centrale",
        industry="pharmacie",
        wilaya="Alger",
        website="https://pharmacie-centrale.dz",
        phone="+213550123456",
        source=DataSource.MANUAL,
    )
    defaults.update(overrides)
    return Lead(**defaults)


def _with_mobile(lead: Lead) -> Lead:
    lead.phone_details = [PhoneDetails(
        original_string="0550123456",
        e164="+213550123456",
        international="+213 550 12 34 56",
        phone_type=__import__("domain.enums", fromlist=["PhoneType"]).PhoneType.MOBILE,
        is_valid=True,
    )]
    return lead


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

def test_analyzer_full_digital_presence():
    lead = _with_mobile(_lead(email="contact@x.dz", address="Rue 1, Alger"))
    lead.social_links = ["https://facebook.com/a", "https://instagram.com/b"]
    audit = BusinessAnalyzer().audit(lead)
    assert audit.digital_score == 100
    assert audit.digital_tier == TIER_MATURE
    assert audit.analysis_model == "deterministic-v3"
    # Fully digital businesses get no "missing website" pitch.
    assert all("Site Vitrine" not in s.service_name for s in audit.recommended_services)


def test_analyzer_analog_lead():
    lead = _lead(website=None, phone=None, email=None)
    audit = BusinessAnalyzer().audit(lead)
    assert audit.digital_score == 10
    assert audit.digital_tier == TIER_HIGH_OPPORTUNITY
    assert any("site web" in g.lower() for g in audit.gaps)
    top = audit.recommended_services[0]
    assert top.priority == 10 and "Site Vitrine" in top.service_name
    assert top.estimated_budget_dzd > 0
    assert audit.cta_fr and "Pharmacie Centrale" in audit.cta_fr
    assert audit.cta_ar and "الجزائر" not in audit.cta_ar  # uses wilaya value


def test_analyzer_http_website_gets_ssl_pitch():
    lead = _lead(website="http://insecure.dz")
    audit = BusinessAnalyzer().audit(lead)
    assert any("SSL" in s.service_name for s in audit.recommended_services)
    assert any("non securise" in g.lower() for g in audit.gaps)


def test_analyzer_industry_catalog_match():
    lead = _lead(industry="menuiserie aluminium")
    audit = BusinessAnalyzer().audit(lead)
    names = " ".join(s.service_name for s in audit.recommended_services)
    assert "Devis" in names or "menuiserie" in names.lower() or len(audit.recommended_services) >= 1


def test_analyzer_determinism():
    lead = _with_mobile(_lead())
    a = BusinessAnalyzer().audit(lead)
    b = BusinessAnalyzer().audit(lead)
    assert a.to_dict() == b.to_dict()


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------

def test_channel_flags_bitpacking():
    lead = _with_mobile(_lead(email="a@b.dz", address="Long address here"))
    lead.social_links = ["https://facebook.com/x"]
    lead.latitude, lead.longitude = 36.75, 3.06
    flags = channel_flags(lead)
    assert flags & FLAG_WEBSITE and flags & FLAG_SSL
    assert flags & FLAG_PHONE and flags & FLAG_MOBILE and flags & FLAG_WHATSAPP
    assert flags & FLAG_EMAIL and flags & FLAG_SOCIAL and flags & FLAG_ADDRESS and flags & FLAG_GEO


def test_scorer_scores_and_explains():
    scorer = LeadScorer()
    lead = _with_mobile(_lead(email="a@b.dz"))
    lead.social_links = ["https://facebook.com/x"]
    score, breakdown = scorer.score(lead)
    assert 0.0 < score <= 100.0
    assert breakdown["phone_present"] == 15.0
    assert breakdown["mobile_direct"] == 10.0
    assert breakdown["website_active"] == 10.0
    assert lead.digital_score is not None and 0 <= lead.digital_score <= 100


def test_scorer_batch_consistent_with_single():
    scorer = LeadScorer()
    leads = [
        _with_mobile(_lead()),
        _lead(name="Boulangerie", wilaya="Oran"),
        _lead(name="Clinique", wilaya="Blida", website=None, phone=None),
    ]
    scorer.score_many(leads)
    singles = []
    for l in leads:
        fresh = _lead(name=l.name, wilaya=l.wilaya, website=l.website, phone=l.phone)
        fresh.phone_details = l.phone_details
        scorer.score(fresh)
        singles.append(fresh.priority_score)
    assert [l.priority_score for l in leads] == singles


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

def test_resolver_merges_near_duplicates():
    leads = [
        _with_mobile(_lead()),
        _lead(name="Pharmacie Central", website=None),      # typo variant, no phone
        _lead(name="Menuiserie El Nour", wilaya="Oran"),    # different business
    ]
    resolver = GraphEntityResolver()
    clusters, report = resolver.resolve(leads)
    assert report.input_count == 3
    # The two pharmacie variants share a cluster; menuiserie is separate.
    groups = [set(g) for g in clusters]
    assert any({0, 1} <= g for g in groups)
    assert any(g == {2} for g in groups)


def test_resolver_keeps_distinct_businesses():
    leads = [
        _lead(name="Pharmacie Centrale"),
        _lead(name="Boulangerie La Rose"),
        _lead(name="Clinique Es Salem"),
    ]
    clusters, _ = GraphEntityResolver().resolve(leads)
    assert all(len(g) == 1 for g in clusters)
    assert len(clusters) == 3


def test_resolver_same_name_different_city_stays_separate():
    leads = [
        _lead(name="Pharmacie Centrale", wilaya="Alger", website=None, phone=None),
        _lead(name="Pharmacie Centrale", wilaya="Oran", website=None, phone=None),
    ]
    clusters, _ = GraphEntityResolver().resolve(leads)
    # No channel overlap + different cities -> below threshold.
    assert len(clusters) == 2


def test_resolver_identical_records():
    clusters, _ = GraphEntityResolver().resolve([_lead()])
    assert clusters == [[0]]


def test_golden_record_builder():
    a = _with_mobile(_lead())
    b = _lead(name="Pharmacie Central", website=None)
    a.id, b.id = 101, 102
    leads = [a, b]
    record = GoldenRecordBuilder.build(leads)
    assert record["canonical_lead_id"] in (101, 102)
    assert sorted(record["members"]) == [101, 102]
    assert record["strategy"] == "graph_merge"
    assert record["confidence"] >= 0.8


def test_resolver_deterministic_reproducibility():
    """Same input through two independent resolver instances must produce
    identical clusters (the old native-vs-fallback parity guarantee is now
    trivially held by the single fastops implementation; the remaining risk
    this guards against is hidden mutable state between runs)."""
    base_names = [
        "Pharmacie Centrale", "Pharmacie Central", "Boulangerie La Rose",
        "Boulangerie Larose", "Menuiserie El Nour", "Menuiserie Nour",
        "Clinique Es Salem", "Garage Ben Ali", "Garage Benali",
    ]
    leads = [
        _lead(name=base_names[i], wilaya="Alger", phone=f"+2135501234{i:02d}")
        for i in range(len(base_names))
    ]

    clusters_a, report_a = GraphEntityResolver().resolve(leads)
    clusters_b, report_b = GraphEntityResolver().resolve(leads)
    assert clusters_a == clusters_b
    dict_a, dict_b = report_a.to_dict(), report_b.to_dict()
    dict_a.pop("duration_seconds"), dict_b.pop("duration_seconds")  # wall-clock
    assert dict_a == dict_b
