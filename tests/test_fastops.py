"""fastops tests — semantic guarantees of the pure-Python engine core.

Migrated from ``test_native_parity.py`` when the C++ core was retired
(v4 Task 13): the value assertions (Levenshtein cases, trigram properties,
score invariants, name-matching semantics, HTML extraction fields) carry
over unchanged; the native-vs-fallback comparisons became determinism
guards in test_engine/test_resolution; bloom semantics moved to UrlDedup.

The scoring invariants are updated for the v4 Task 10 opportunity
arithmetic: absence of web presence now *adds* opportunity points.
"""

from __future__ import annotations

import random

import pytest

from engine.fastops import (
    FLAG_ADDRESS,
    FLAG_EMAIL,
    FLAG_GEO,
    FLAG_MOBILE,
    FLAG_PHONE,
    FLAG_SOCIAL,
    FLAG_SSL,
    FLAG_WEBSITE,
    FLAG_WHATSAPP,
    ExtractionResult,
    NameMatcher,
    UrlDedup,
    extract_html,
    levenshtein,
    score_batch,
    score_batch_reference,
    trigram_jaccard,
)

SAMPLE_HTML = b"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Pharmacie Centrale - Bab El Oued, Alger</title>
<meta name="description" content="Officine pharmaceutique de garde a Alger.">
<meta property="og:title" content="Pharmacie Centrale">
<meta property="og:description" content="Medicaments et parapharmacie">
<link rel="canonical" href="https://pharmacie-centrale.dz/">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Pharmacy","name":"Pharmacie Centrale",
 "telephone":"+213 21 96 12 34","address":"Bab El Oued, Alger"}
</script>
</head>
<body>
<h1>Bienvenue</h1>
<p>Contactez notre pharmacien de garde au 0550 12 34 56 ou 0770 98 76 54.</p>
<a href="/catalogue/produits">Nos produits</a>
<a href="https://facebook.com/pharmacie.centrale">Facebook</a>
<a href="tel:+21321961234">Ligne fixe</a>
<a href="mailto:contact@pharmacie-centrale.dz">Email pro</a>
<a href="#top">Top</a>
<a href="javascript:void(0)">JS</a>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Levenshtein
# ---------------------------------------------------------------------------

def test_levenshtein_known_cases():
    cases = [
        ("kitten", "sitting", 3),
        ("flaw", "lawn", 2),
        ("", "abc", 3),
        ("abc", "", 3),
        ("identical", "identical", 0),
        ("pharmacie centrale", "pharmacie central", 1),
    ]
    for a, b, expected in cases:
        assert levenshtein(a, b) == expected, (a, b)


def test_levenshtein_unicode_bytes():
    """Byte-level semantics: accented/Arabic variants cost their UTF-8 deltas."""
    pairs = [
        ("صيدلية المركز", "صيدلية المركزية"),
        ("Café Central", "Cafe Central"),
        ("Ets Benaïcha", "Ets Benaicha"),
    ]
    for a, b in pairs:
        assert levenshtein(a, b) >= 1
        assert levenshtein(a, b) == levenshtein(b, a)


def test_levenshtein_fuzz_deterministic():
    rng = random.Random(1234)
    for _ in range(400):
        a = "".join(rng.choices("abcdef ", k=rng.randint(0, 40)))
        b = "".join(rng.choices("abcdef ", k=rng.randint(0, 40)))
        assert levenshtein(a, b) == levenshtein(a, b)


# ---------------------------------------------------------------------------
# Trigram Jaccard
# ---------------------------------------------------------------------------

def test_trigram_jaccard_ordering():
    assert trigram_jaccard("pharmacie centrale alger", "pharmacie central alger") > 0.5
    assert trigram_jaccard("pharmacie centrale alger", "menuiserie aluminium oran") < 0.2


def test_trigram_jaccard_properties():
    assert trigram_jaccard("", "abc") == 0.0
    assert abs(trigram_jaccard("abcde", "abcde") - 1.0) < 1e-9
    assert trigram_jaccard("abcde", "edcba") >= 0.0


# ---------------------------------------------------------------------------
# Batch scoring — invariants + v4 Task 10 opportunity arithmetic
# ---------------------------------------------------------------------------

def test_score_batch_invariants():
    # Perfect digital presence, stale freshness -> health 100, no opportunity.
    full = (FLAG_WEBSITE | FLAG_SSL | FLAG_PHONE | FLAG_MOBILE | FLAG_WHATSAPP |
            FLAG_EMAIL | FLAG_SOCIAL | FLAG_ADDRESS | FLAG_GEO)
    priorities, digitals = score_batch([full], [3], [4])
    assert digitals[0] == 100
    assert 0.0 <= priorities[0] <= 100.0

    # Nothing at all (ghost record, issue #16): the opportunity bonuses are
    # contactability-gated, so flags=0 earns ONLY deficit + min freshness:
    # 22.5 + 2 = 24.5. (Pre-#16 it collected both bonuses too: 49.5 — the
    # incentive defect where uncontactable snippets outranked real leads.)
    priorities, digitals = score_batch([0], [0], [4])
    assert digitals[0] == 10
    assert priorities[0] == pytest.approx(22.5 + 2.0, abs=1e-6)

    priorities, digitals = score_batch([], [], [])
    assert priorities == [] and digitals == []


def test_score_batch_v4_task10_acceptance():
    """v4 Task 10's acceptance test: a verified-phone business with no
    website and no map pin must score >= 60 (it is the prime prospect)."""
    flags = FLAG_PHONE | FLAG_MOBILE | FLAG_WHATSAPP  # verified, reachable
    priorities, digitals = score_batch([flags], [0], [4])  # oldest freshness
    assert priorities[0] >= 60.0
    assert priorities[0] <= 100.0


def test_score_batch_opportunity_not_double_counted():
    """A lead with a website earns website_active but NOT the build
    opportunity; address/geo earn their presence points and suppress the
    local-seo opportunity."""
    with_web = FLAG_WEBSITE | FLAG_ADDRESS | FLAG_GEO
    priorities_web, _ = score_batch([with_web], [0], [4])
    priorities_bare, _ = score_batch([0], [0], [4])
    # Presence earns reach/substance but loses the opportunity bonus.
    assert priorities_web[0] > priorities_bare[0] - 25.0


def test_score_batch_length_consistency():
    rng = random.Random(99)
    flags_list, socials, fresh = [], [], []
    for _ in range(500):
        f = 0
        for bit in (FLAG_WEBSITE, FLAG_SSL, FLAG_PHONE, FLAG_MOBILE,
                    FLAG_WHATSAPP, FLAG_EMAIL, FLAG_SOCIAL, FLAG_ADDRESS, FLAG_GEO):
            if rng.random() < 0.5:
                f |= bit
        flags_list.append(f)
        socials.append(rng.randint(0, 5))
        fresh.append(rng.randint(0, 4))
    priorities, digitals = score_batch(flags_list, socials, fresh)
    assert len(priorities) == len(digitals) == 500
    assert all(0.0 <= p <= 100.0 for p in priorities)
    assert all(10 <= d <= 100 for d in digitals)


# ---------------------------------------------------------------------------
# Issue #16 — contactability gate + lookup-table batch parity
# ---------------------------------------------------------------------------
class TestIssue16GhostRecords:
    """Ghost records must not achieve high scores from missing fields."""

    def test_ghost_never_earns_opportunity_points(self):
        # Every *reachable* flag word without a contact channel must score
        # strictly below the v4 Task 10 acceptance bar of 60. Reachable =
        # words channel_flags can actually produce (MOBILE/WHATSAPP imply
        # PHONE; SSL implies WEBSITE).
        def reachable(f: int) -> bool:
            if f & FLAG_MOBILE and not f & FLAG_PHONE:
                return False
            if f & FLAG_WHATSAPP and not f & FLAG_PHONE:
                return False
            if f & FLAG_SSL and not f & FLAG_WEBSITE:
                return False
            return True

        worst = 0.0
        for f in range(512):
            if f & (FLAG_PHONE | FLAG_EMAIL) or not reachable(f):
                continue
            for fb in range(5):
                p, _ = score_batch([f], [0], [fb])
                worst = max(worst, p[0])
        assert worst < 60.0, f"non-contactable record scored {worst}"

    def test_ghost_ceiling_is_deficit_plus_freshness_only(self):
        # flags=0 with freshest bucket: 0 reach + 0 substance + 0 opportunity
        # (gated) + 22.5 deficit + 15 freshness = 37.5 — the hard ceiling for
        # a completely empty record.
        p, d = score_batch([0], [0], [0])
        assert p[0] == pytest.approx(37.5, abs=1e-9)
        assert d[0] == 10

    def test_contactable_no_website_still_gets_both_bonuses(self):
        # The Task-10 prime prospect is untouched by the gate.
        flags = FLAG_PHONE | FLAG_MOBILE | FLAG_WHATSAPP
        p, _ = score_batch([flags], [0], [4])
        assert p[0] >= 60.0
        p, _ = score_batch([flags | FLAG_GEO | FLAG_ADDRESS], [0], [4])
        # with address+geo the local-seo bonus disappears, build bonus stays
        assert p[0] >= 45.0

    def test_email_only_is_contactable(self):
        # Email is a direct contact channel: qualifies for the bonuses.
        p, d = score_batch([FLAG_EMAIL], [0], [4])
        # reach 5 + opportunity 25 + deficit (100-20)*0.25=20 + freshness 2 = 52
        assert p[0] == pytest.approx(5.0 + 25.0 + 20.0 + 2.0, abs=1e-6)
        assert d[0] == 20

    def test_social_only_record_gets_no_opportunity(self):
        # A social page with no phone/email: real presence (social points)
        # but not directly contactable — no opportunity bonuses.
        p, d = score_batch([FLAG_SOCIAL], [1], [4])
        # substance 5 + deficit (100-25)*0.25=18.75 + freshness 2 = 25.75
        assert p[0] == pytest.approx(5.0 + 18.75 + 2.0, abs=1e-6)
        assert d[0] == 25

    def test_address_only_record_gets_no_opportunity(self):
        p, _ = score_batch([FLAG_ADDRESS], [0], [4])
        # substance 5 + deficit 21.25 + freshness 2 = 28.25 (no local-seo
        # bonus: not contactable)
        assert p[0] == pytest.approx(5.0 + 21.25 + 2.0, abs=1e-6)

    def test_website_does_not_earn_build_opportunity_even_when_contactable(self):
        flags = FLAG_PHONE | FLAG_WEBSITE
        p, _ = score_batch([flags], [0], [4])
        # reach 15 + substance 10 + local_seo 10 (contactable, no address/geo)
        # + deficit (100-60)*0.25=10 + freshness 2 = 47 — and no build bonus.
        assert p[0] == pytest.approx(15.0 + 10.0 + 10.0 + 10.0 + 2.0, abs=1e-6)


class TestIssue16LUTParity:
    """The 512-entry lookup-table batch path must be exactly the scalar oracle.

    Exhaustive over the full flag space x social counts x freshness buckets
    (including out-of-range freshness values clamped to the oldest bucket).
    """

    def test_exhaustive_flag_space_parity(self):
        flags = list(range(512))
        socials = [i % 6 for i in range(512)]        # 0..5 (past min(soc,2))
        fresh = [i % 7 for i in range(512)]         # 0..6 (6 is invalid -> 4)
        p_fast, d_fast = score_batch(flags, socials, fresh)
        p_ref, d_ref = score_batch_reference(flags, socials, fresh)
        assert p_fast == p_ref, "priority mismatch between LUT and oracle"
        assert d_fast == d_ref, "digital mismatch between LUT and oracle"

    def test_randomized_parity(self):
        rng = random.Random(161)
        for _ in range(20):
            n = 500
            flags = [rng.getrandbits(9) for _ in range(n)]
            socials = [rng.randint(0, 255) for _ in range(n)]
            fresh = [rng.randint(0, 9) for _ in range(n)]
            assert score_batch(flags, socials, fresh) == score_batch_reference(flags, socials, fresh)

    def test_default_argument_parity(self):
        rng = random.Random(162)
        flags = [rng.getrandbits(9) for _ in range(200)]
        assert score_batch(flags) == score_batch_reference(flags)


class TestIssue16ExplainMirrorsBatch:
    """LeadScorer.explain must mirror the gated batch arithmetic factor-for-factor."""

    def _score(self, lead):
        from engine.scorer import LeadScorer

        LeadScorer().score(lead)
        return lead.priority_score, lead.score_breakdown

    def test_ghost_lead_breakdown_has_no_opportunity_keys(self):
        from domain.models import Lead

        lead = Lead(name="Some Directory Listing", wilaya="Alger")
        score, breakdown = self._score(lead)
        assert "website_build_opportunity" not in breakdown
        assert "local_seo_opportunity" not in breakdown
        assert score <= 37.5

    def test_phone_lead_keeps_both_opportunity_factors(self):
        from domain.enums import PhoneType
        from domain.models import Lead
        from domain.value_objects import PhoneDetails

        lead = Lead(name="Pharmacie Centrale", wilaya="Alger", phone="+213550123456")
        lead.phone_details = [PhoneDetails(
            original_string="0550 12 34 56", e164="+213550123456",
            international="+213 550 12 34 56", national="0550 12 34 56",
            phone_type=PhoneType.MOBILE, is_valid=True, is_whatsapp_capable=True,
        )]
        score, breakdown = self._score(lead)
        assert breakdown["website_build_opportunity"] == 15.0
        assert breakdown["local_seo_opportunity"] == 10.0
        assert score >= 60.0  # the v4 Task 10 contract

    def test_email_lead_keeps_both_opportunity_factors(self):
        from domain.models import Lead

        lead = Lead(name="Clinique El Nour", wilaya="Oran", email="contact@elnour.dz")
        score, breakdown = self._score(lead)
        assert breakdown["website_build_opportunity"] == 15.0
        assert breakdown["local_seo_opportunity"] == 10.0

    def test_explain_matches_score_batch_across_flag_grid(self):
        """For every flag word, explain()'s factor sum equals the batch score."""
        from domain.models import Lead

        # Build a lead per flag word via field-level controls, then compare
        # explain-sum against a direct score_batch call with the same flags.
        from engine.scorer import LeadScorer, channel_flags

        scorer = LeadScorer()
        rng = random.Random(163)
        for _ in range(300):
            lead = Lead(name=f"Biz {rng.randint(0, 9999)}", wilaya="Alger")
            if rng.random() < 0.5:
                lead.phone = "+213550123456"
            if rng.random() < 0.4:
                lead.email = "contact@biz.dz"
            if rng.random() < 0.5:
                lead.website = "https://biz.dz" if rng.random() < 0.7 else "http://biz.dz"
            if rng.random() < 0.4:
                lead.social_links = ["https://facebook.com/x"]
            if rng.random() < 0.4:
                lead.address = "12 Rue de la Paix, Alger"
            if rng.random() < 0.3:
                lead.latitude, lead.longitude = 36.75, 3.05

            scorer.score(lead)
            flags = channel_flags(lead)
            p_batch, _ = score_batch([flags], [min(len(lead.social_links), 255)], [4])
            # explain's factor sum must reproduce the batch priority exactly
            # (same arithmetic, single source of truth).
            assert lead.priority_score == round(p_batch[0], 1), (
                f"explain/batch divergence: {lead.score_breakdown} vs {p_batch[0]}"
            )


# ---------------------------------------------------------------------------
# Name-matching session
# ---------------------------------------------------------------------------

def test_names_session_semantics():
    names = [
        "pharmaciecentralealger",
        "pharmaciecentralalger",
        "menuiseriealuminiumoran",
        "menuiseriealuoran",
        "cliniqueelamoutdjelfa",
        "garagemecaniquebenha",
        "boulangerielarosedor",
        "boulangerielarose",
    ]
    pairs = [(i, j) for i in range(len(names)) for j in range(i + 1, len(names))]

    matcher = NameMatcher()
    matcher.reset(len(names))
    for n in names:
        matcher.add(n)
    scores = matcher.match_pairs(pairs, 0.4, 0.78)

    by_pair = dict(zip(pairs, scores))
    assert by_pair[(0, 1)] > 0.78       # centrale/central alger
    assert by_pair[(6, 7)] > 0.78       # larosedor/larose
    assert by_pair[(0, 2)] == 0.0       # pharmacie vs menuiserie


def test_names_session_empty_inputs():
    matcher = NameMatcher()
    matcher.reset(8)
    assert matcher.add("") == -1
    assert matcher.match_pairs([], 0.4, 0.78) == []
    assert matcher.match_pairs([(0, 99)], 0.4, 0.78) == [0.0]  # out-of-range pair


def test_names_session_instance_isolation():
    """Two matchers hold independent corpora (the old global C session
    leaked state between engine instances)."""
    a = NameMatcher()
    b = NameMatcher()
    a.add_many(["pharmacie centrale", "pharmacie central"])
    scores_b = b.match_pairs([(0, 1)], 0.4, 0.78)
    assert scores_b == [0.0]
    assert len(a) == 2 and len(b) == 0


# ---------------------------------------------------------------------------
# URL dedup (replaces the global bloom filter)
# ---------------------------------------------------------------------------

def test_url_dedup_semantics():
    dedup = UrlDedup()
    assert dedup.test_and_add("https://a.dz/1") is False
    assert dedup.test_and_add("https://a.dz/1") is True
    assert dedup.test("https://a.dz/1") is True
    assert dedup.test("https://a.dz/2") is False
    assert len(dedup) == 1
    dedup.clear()
    assert dedup.test("https://a.dz/1") is False


def test_url_dedup_bounded():
    """Past capacity the set stops growing and admits everything new —
    memory is capped while SQLite's UNIQUE(url) stays authoritative."""
    dedup = UrlDedup(capacity=3)
    for i in range(3):
        assert dedup.test_and_add(f"https://s{i}.dz/") is False
    assert dedup.test_and_add("https://new.dz/") is False  # over cap: unseen
    assert len(dedup) == 3


# ---------------------------------------------------------------------------
# HTML extraction
# ---------------------------------------------------------------------------

def test_extract_html_fields():
    res = extract_html(SAMPLE_HTML)
    assert isinstance(res, ExtractionResult)
    assert res.title == "Pharmacie Centrale - Bab El Oued, Alger"
    assert res.meta_description == "Officine pharmaceutique de garde a Alger."
    assert res.canonical_url == "https://pharmacie-centrale.dz/"
    assert res.og_title == "Pharmacie Centrale"
    assert res.email == "contact@pharmacie-centrale.dz"
    assert res.lang == "fr"
    assert '"@type":"Pharmacy"' in res.json_ld
    assert "https://facebook.com/pharmacie.centrale" in res.links
    assert "/catalogue/produits" in res.links
    assert any("0550" in p for p in res.phones)
    assert any("0770" in p for p in res.phones)
    assert any("21321961234" in p.replace(" ", "") for p in res.phones)
    # Anchors and JS links excluded.
    assert all(not l.startswith("#") for l in res.links)
    assert all(not l.startswith("javascript") for l in res.links)


def test_extract_html_empty():
    res = extract_html(b"")
    assert res.title == "" and res.links == [] and res.phones == []


def test_extract_html_malformed():
    garbage = b"<html><body><p>0550 12 34 56</p>"  # unclosed tags
    res = extract_html(garbage)
    assert any("0550" in p for p in res.phones)


def test_extract_html_json_ld_capped():
    payload = b'<script type="application/ld+json">' + b'{"pad":"' + b"x" * 20000 + b'"}</script>'
    res = extract_html(payload)
    assert len(res.json_ld) < 8192
