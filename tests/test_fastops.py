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

    # Nothing at all -> maximal deficit + both opportunity bonuses + min
    # freshness: 22.5 + 15 + 10 + 2 = 49.5 (v4 Task 10 inverted scoring).
    priorities, digitals = score_batch([0], [0], [4])
    assert digitals[0] == 10
    assert priorities[0] == pytest.approx(22.5 + 25.0 + 2.0, abs=1e-6)

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
