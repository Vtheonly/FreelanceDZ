"""Parity tests: native C++ core vs pure-Python fallbacks.

These run the SAME logical inputs through both implementations and require
identical (or tolerance-bounded) results. If the native library is absent,
native-side assertions are skipped — CI still exercises the fallbacks.
"""

from __future__ import annotations

import random

import pytest

from engine.native import (
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
    NativeEngine,
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


@pytest.fixture(scope="module")
def native() -> NativeEngine:
    return NativeEngine.get()


@pytest.fixture(scope="module")
def fallback() -> NativeEngine:
    """A NativeEngine instance guaranteed to use Python paths."""
    eng = NativeEngine.__new__(NativeEngine)
    eng._lib = None
    eng._isa_level = 0
    return eng


# ---------------------------------------------------------------------------
# Levenshtein
# ---------------------------------------------------------------------------

def test_levenshtein_known_cases(native, fallback):
    cases = [
        ("kitten", "sitting", 3),
        ("flaw", "lawn", 2),
        ("", "abc", 3),
        ("abc", "", 3),
        ("identical", "identical", 0),
        ("pharmacie centrale", "pharmacie central", 1),
    ]
    for a, b, expected in cases:
        assert fallback.levenshtein(a, b) == expected
        if native.is_native:
            assert native.levenshtein(a, b) == expected


def test_levenshtein_fuzz_parity(native, fallback):
    rng = random.Random(1234)
    for _ in range(400):
        a = "".join(rng.choices("abcdef ", k=rng.randint(0, 40)))
        b = "".join(rng.choices("abcdef ", k=rng.randint(0, 40)))
        py = fallback.levenshtein(a, b)
        if native.is_native:
            assert native.levenshtein(a, b) == py, (a, b)


def test_levenshtein_unicode_bytes_parity(native, fallback):
    pairs = [
        ("صيدلية المركز", "صيدلية المركزية"),
        ("Café Central", "Cafe Central"),
        ("Ets Benaïcha", "Ets Benaicha"),
    ]
    for a, b in pairs:
        py = fallback.levenshtein(a, b)
        if native.is_native:
            assert native.levenshtein(a, b) == py, (a, b)


# ---------------------------------------------------------------------------
# Trigram Jaccard
# ---------------------------------------------------------------------------

def test_trigram_jaccard_parity(native, fallback):
    names = [
        "pharmacie centrale alger",
        "pharmacie central alger",
        "menuiserie aluminium oran",
        "menuiserie alu oran",
        "completely different string",
    ]
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            py = fallback.trigram_jaccard(a, b)
            if native.is_native:
                assert abs(native.trigram_jaccard(a, b) - py) < 1e-6, (a, b)


def test_trigram_jaccard_properties(fallback):
    assert fallback.trigram_jaccard("", "abc") == 0.0
    assert abs(fallback.trigram_jaccard("abcde", "abcde") - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Batch scoring
# ---------------------------------------------------------------------------

def test_score_batch_parity(native, fallback):
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

    py_p, py_d = fallback.score_batch(flags_list, socials, fresh)
    if native.is_native:
        n_p, n_d = native.score_batch(flags_list, socials, fresh)
        assert len(n_p) == len(py_p)
        for got, want in zip(n_p, py_p):
            assert abs(got - want) < 1e-5
        assert n_d == py_d


def test_score_batch_invariants(fallback):
    # Perfect digital presence, stale freshness.
    full = (FLAG_WEBSITE | FLAG_SSL | FLAG_PHONE | FLAG_MOBILE | FLAG_WHATSAPP |
            FLAG_EMAIL | FLAG_SOCIAL | FLAG_ADDRESS | FLAG_GEO)
    priorities, digitals = fallback.score_batch([full], [3], [4])
    assert digitals[0] == 100
    assert 0.0 <= priorities[0] <= 100.0

    # Nothing at all -> maximal deficit, minimum freshness.
    priorities, digitals = fallback.score_batch([0], [0], [4])
    assert digitals[0] == 10
    assert priorities[0] == pytest.approx(22.5 + 2.0, abs=1e-6)  # deficit 22.5 + fresh 2

    priorities, digitals = fallback.score_batch([], [], [])
    assert priorities == [] and digitals == []


# ---------------------------------------------------------------------------
# Name-matching session
# ---------------------------------------------------------------------------

def test_names_session_parity(native, fallback):
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

    fallback.names_reset(len(names))
    for n in names:
        fallback.names_add(n)
    py_scores = fallback.names_match_pairs(pairs, 0.4, 0.78)

    if native.is_native:
        native.names_reset(len(names))
        for n in names:
            native.names_add(n)
        n_scores = native.names_match_pairs(pairs, 0.4, 0.78)
        for got, want in zip(n_scores, py_scores):
            assert abs(got - want) < 1e-5

    # The near-duplicate pairs must exceed zero; distant pairs must not.
    by_pair = dict(zip(pairs, py_scores))
    assert by_pair[(0, 1)] > 0.78       # centrale/central alger
    assert by_pair[(6, 7)] > 0.78       # larosedor/larose
    assert by_pair[(0, 2)] == 0.0       # pharmacie vs menuiserie


def test_names_session_empty_inputs(native, fallback):
    fallback.names_reset(8)
    assert fallback.names_add("") == -1
    assert fallback.names_match_pairs([], 0.4, 0.78) == []


# ---------------------------------------------------------------------------
# Bloom filter
# ---------------------------------------------------------------------------

def test_bloom_semantics(fallback):
    fallback.bloom_init(10000, 0.01)
    fallback.bloom_clear()
    assert fallback.bloom_test_and_add("https://a.dz/1") is False
    assert fallback.bloom_test_and_add("https://a.dz/1") is True
    assert fallback.bloom_test("https://a.dz/1") is True
    assert fallback.bloom_test("https://a.dz/2") is False
    assert fallback.bloom_size() == 1


def test_bloom_native_semantics(native):
    if not native.is_native:
        pytest.skip("native library absent")
    native.bloom_init(10000, 0.01)
    native.bloom_clear()
    assert native.bloom_test_and_add("https://a.dz/1") is False
    assert native.bloom_test_and_add("https://a.dz/1") is True
    assert native.bloom_test("https://a.dz/1") is True
    native.bloom_clear()
    assert native.bloom_test("https://a.dz/1") is False


def test_bloom_false_positive_rate(native):
    """1% target FPR — accept up to 3% to stay robust across hash seeds."""
    if not native.is_native:
        pytest.skip("native library absent")
    n = 20000
    native.bloom_init(n, 0.01)
    native.bloom_clear()
    for i in range(n):
        native.bloom_test_and_add(f"https://site-{i}.dz/page")
    fp = sum(1 for i in range(n, n * 2) if native.bloom_test(f"https://site-{i}.dz/page"))
    assert fp / n < 0.03


# ---------------------------------------------------------------------------
# HTML extraction
# ---------------------------------------------------------------------------

def test_extract_html_fallback_fields(fallback):
    res = fallback.extract_html(SAMPLE_HTML)
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


def test_extract_html_native_fields(native):
    if not native.is_native:
        pytest.skip("native library absent")
    res = native.extract_html(SAMPLE_HTML)
    assert res.title == "Pharmacie Centrale - Bab El Oued, Alger"
    assert res.canonical_url == "https://pharmacie-centrale.dz/"
    assert res.og_title == "Pharmacie Centrale"
    assert res.email == "contact@pharmacie-centrale.dz"
    assert res.lang == "fr"
    assert '"@type":"Pharmacy"' in res.json_ld
    assert "https://facebook.com/pharmacie.centrale" in res.links
    assert "/catalogue/produits" in res.links
    assert any("0550" in p for p in res.phones)
    assert any("21321961234" in p.replace(" ", "") for p in res.phones)


def test_extract_html_empty(native, fallback):
    for eng in (fallback, native):
        res = eng.extract_html(b"")
        assert res.title == "" and res.links == [] and res.phones == []


def test_extract_html_malformed(native, fallback):
    garbage = b"<html><body><p>0550 12 34 56</p>"  # unclosed tags
    for eng in (fallback, native):
        res = eng.extract_html(garbage)
        assert any("0550" in p for p in res.phones)


def test_isa_report(native):
    assert native.isa_level in (0, 1, 2, 3)
