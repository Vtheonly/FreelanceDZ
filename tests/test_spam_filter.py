"""Tests for the spam filter (Business Quality Gate).

Issue #8: legitimate structured Algerian directories (Ouedkniss,
CACI El Mouchir, Pages Jaunes DZ) must pass their *profile* pages while
their search/index pages stay blocked; low-quality SEO aggregators and
international directory giants remain blocked outright.
"""

from __future__ import annotations

from utils.spam_filter import SourcingSpamFilter


def test_blocks_directory_domains():
    f = SourcingSpamFilter()
    assert f.is_spam("https://www.cybo.com/algeria/oran/pharmacies", "Pharmacies in Oran") is True
    assert f.is_spam("https://www.yellowpages.com/oran", "Yellow Pages") is True


def test_blocks_aggregator_titles():
    f = SourcingSpamFilter()
    assert f.is_spam("https://example.com/list", "321 Résultats de Pharmacie à Oran") is True
    assert f.is_spam("https://example.com/page1", "Pharmacie à Oran - Page 1") is True


def test_allows_real_business_url():
    f = SourcingSpamFilter()
    assert f.is_spam("https://pharmacie-dergal.dz", "Pharmacie Dergal") is False


def test_blocks_empty_url():
    f = SourcingSpamFilter()
    assert f.is_spam("", "Some title") is True


def test_allows_social_platforms():
    """Social URLs are deliberately allowed: the DDG scraper deep-crawls them
    to enrich business profiles (v2's stale test asserted the opposite and
    contradicted both the implementation and the enrichment design)."""
    f = SourcingSpamFilter()
    assert f.is_spam("https://facebook.com/somepage", "Some Page") is False
    assert f.is_spam("https://instagram.com/someprofile", "Some Profile") is False


def test_custom_extras():
    f = SourcingSpamFilter(extra_domains=frozenset({"example.com"}))
    assert f.is_spam("https://example.com/page", "Whatever") is True


# ---------------------------------------------------------------------------
# Issue #8 — trusted local directories
# ---------------------------------------------------------------------------
class TestOuedkniss:
    """Algeria's dominant classifieds marketplace: store profiles pass."""

    def test_store_profile_passes(self):
        f = SourcingSpamFilter()
        assert f.is_spam(
            "https://www.ouedkniss.com/store/pharmacie-en-nour",
            "Pharmacie En Nour - Ouedkniss",
        ) is False

    def test_legacy_style_profile_path_passes(self):
        f = SourcingSpamFilter()
        assert f.is_spam(
            "https://www.ouedkniss.com/fr/store/climatisation-dz-services",
            "Climatisation DZ Services",
        ) is False

    def test_search_pages_blocked(self):
        f = SourcingSpamFilter()
        assert f.is_spam(
            "https://www.ouedkniss.com/search?keyword=pharmacie",
            "Recherche pharmacie",
        ) is True

    def test_listing_and_index_paths_blocked(self):
        f = SourcingSpamFilter()
        for path in ("/categories/23-sante", "/annonces/123456", "/offre/xyz",
                     "/demande/xyz", "/stores"):
            assert f.is_spam(f"https://www.ouedkniss.com{path}", "Whatever") is True, path

    def test_homepage_is_a_landing_page_not_a_business(self):
        f = SourcingSpamFilter()
        assert f.is_spam("https://www.ouedkniss.com/", "Ouedkniss") is True
        assert f.is_spam("https://www.ouedkniss.com", "Ouedkniss") is True

    def test_result_wording_still_blocked_on_profiles_domain(self):
        """A listing-shaped page stays blocked even on a trusted domain."""
        f = SourcingSpamFilter()
        assert f.is_spam(
            "https://www.ouedkniss.com/store/anything",
            "321 résultats pour pharmacie",
        ) is True

    def test_non_business_tokens_still_blocked(self):
        f = SourcingSpamFilter()
        assert f.is_spam(
            "https://www.ouedkniss.com/store/whatever",
            "Avis de recrutement - Pharmacie",
        ) is True

    def test_brand_word_in_profile_title_is_not_spam(self):
        """Profile pages legitimately brand themselves with directory names —
        the brand-word indicators are relaxed on trusted domains (issue #8)."""
        f = SourcingSpamFilter()
        assert f.is_spam(
            "https://www.ouedkniss.com/store/1234",
            "Annuaire Santé Store",
        ) is False


class TestElMouchirCaci:
    """The Algerian chamber-of-commerce directory: company profiles pass."""

    def test_company_profile_passes(self):
        f = SourcingSpamFilter()
        assert f.is_spam(
            "https://elmouchir.caci.dz/company/12345/pharmacie-centrale",
            "Pharmacie Centrale - El Mouchir",
        ) is False

    def test_fiche_detail_passes(self):
        f = SourcingSpamFilter()
        assert f.is_spam(
            "https://www.elmouchir.caci.dz/fr/fiche/sarl-benaicha-123",
            "SARL Benaicha",
        ) is False

    def test_search_and_categories_blocked(self):
        f = SourcingSpamFilter()
        assert f.is_spam("https://elmouchir.caci.dz/recherche?q=pharmacie", "Recherche") is True
        assert f.is_spam("https://elmouchir.caci.dz/categories/sante", "Santé") is True

    def test_homepage_blocked(self):
        f = SourcingSpamFilter()
        assert f.is_spam("https://elmouchir.caci.dz/", "El Mouchir") is True


class TestPagesJaunesDz:
    """The Algerian yellow pages: business profiles pass."""

    def test_business_profile_passes_with_brand_title(self):
        """The historical gate blocked the domain outright; profile pages
        carrying the brand in their title are exactly what issue #8 frees."""
        f = SourcingSpamFilter()
        assert f.is_spam(
            "https://www.lespagesjaunes-algerie.com/lieu/pharmacie-centrale-alger.html",
            "Pharmacie Centrale Alger - Pages Jaunes Algérie",
        ) is False

    def test_search_blocked(self):
        f = SourcingSpamFilter()
        assert f.is_spam(
            "https://www.lespagesjaunes-algerie.com/recherche/pharmacie/alger",
            "Pharmacie Alger",
        ) is True

    def test_villes_and_categories_blocked(self):
        f = SourcingSpamFilter()
        assert f.is_spam("https://www.lespagesjaunes-algerie.com/villes/alger", "Alger") is True
        assert f.is_spam("https://www.lespagesjaunes-algerie.com/categories/sante", "Santé") is True


class TestTrustedDirectoryBoundaries:
    """Canonical URLs, subdomains, lookalikes, malformed hosts (issue #8)."""

    def test_canonical_www_and_bare_hosts(self):
        f = SourcingSpamFilter()
        assert f.is_spam("https://ouedkniss.com/store/x", "X") is False
        assert f.is_spam("https://www.ouedkniss.com/store/x", "X") is False
        assert f.is_spam("https://WWW.OUEDKNISS.COM/STORE/x", "X") is False

    def test_real_subdomains_are_trusted(self):
        f = SourcingSpamFilter()
        assert f.is_spam("https://m.ouedkniss.com/store/x", "X") is False
        assert f.is_spam("https://fr.ouedkniss.com/store/x", "X") is False

    def test_deceptive_lookalikes_get_no_trusted_provenance(self):
        """A lookalike host is NOT a subdomain of the trusted registrable
        domain: it must never be classified as a trusted directory."""
        f = SourcingSpamFilter()
        assert f.is_trusted_directory("https://ouedkniss.com.evil.tld/store/x") is False
        assert f.is_trusted_directory("https://ouedkniss-clone.com/store/x") is False
        assert f.is_trusted_directory("https://evil-ouedkniss.com/store/x") is False
        # And listing-shaped lookalikes are still caught by the ordinary
        # title/path rules.
        assert f.is_spam(
            "https://ouedkniss-clone.com/store/x",
            "Top 10 pharmacies à Alger",
        ) is True

    def test_malformed_hosts(self):
        f = SourcingSpamFilter()
        assert f.is_spam("http://", "Title") is True
        assert f.is_spam("not a url", "Title") is True
        assert f.is_spam("https:///store/x", "Title") is True

    def test_low_quality_aggregators_remain_blocked(self):
        """The trusted tier opens ONLY for the vetted local directories;
        SEO aggregators and international giants stay blocked."""
        f = SourcingSpamFilter()
        for url, title in [
            ("https://annuaire-algerie.com/pharmacie-centrale.html", "Pharmacie Centrale"),
            ("https://www.pagesjaunes.fr/pharmacie/alger", "Pharmacie Alger"),
            ("https://www.cybo.com/algeria/pharmacie-x", "Pharmacie X"),
            ("https://www.yellowpages.com/algeria/x", "X"),
            ("https://africabizinfo.com/companies/x", "X"),
            ("https://sante-dz.com/pharmacie/x", "X"),
        ]:
            assert f.is_spam(url, title) is True, url

    def test_subdomains_of_blocked_domains_still_blocked(self):
        f = SourcingSpamFilter()
        assert f.is_spam("https://fr.yellowpages.com/x", "X") is True
        assert f.is_spam("https://algeria.tripadvisor.com/x", "X") is True


class TestTrustedDirectoryProvenance:
    """Issue #8: downstream code can distinguish a verified profile on a
    trusted directory from an ordinary page or a blocked source."""

    def test_is_trusted_directory_true_for_trusted_hosts(self):
        f = SourcingSpamFilter()
        assert f.is_trusted_directory("https://www.ouedkniss.com/store/x") is True
        assert f.is_trusted_directory("https://elmouchir.caci.dz/company/1") is True
        assert f.is_trusted_directory("https://www.lespagesjaunes-algerie.com/lieu/x.html") is True

    def test_is_trusted_directory_false_elsewhere(self):
        f = SourcingSpamFilter()
        assert f.is_trusted_directory("https://pharmacie-centrale.dz") is False
        assert f.is_trusted_directory("https://www.cybo.com/x") is False
        assert f.is_trusted_directory("") is False
        assert f.is_trusted_directory("not a url") is False

    def test_is_directory_listing_consistent_with_is_spam(self):
        f = SourcingSpamFilter()
        assert f.is_directory_listing("https://www.ouedkniss.com/store/x") is False
        assert f.is_directory_listing("https://www.ouedkniss.com/search?q=x") is True


# ---------------------------------------------------------------------------
# End-to-end through the real DDG SERP parse + gate path (no mocks of the
# filter itself — only the network is replaced by a fixture page)
# ---------------------------------------------------------------------------
DDG_SERP_FIXTURE = """<!DOCTYPE html><html><body>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.ouedkniss.com%2Fstore%2Fpharmacie-en-nour">Pharmacie En Nour - Ouedkniss</a>
  <a class="result__snippet" href="#">Pharmacie de garde a Alger, contactez le 0550 12 34 56.</a>
</div>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.lespagesjaunes-algerie.com%2Flieu%2Fpharmacie-centrale.html">Pharmacie Centrale Alger - Pages Jaunes Algérie</a>
  <a class="result__snippet" href="#">Pharmacie Centrale, 12 rue Didouche Mourad, Alger.</a>
</div>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.cybo.com%2Falgeria%2Foran%2Fpharmacies">Best Pharmacies in Oran - Cybo</a>
  <a class="result__snippet" href="#">Directory of pharmacies in Oran.</a>
</div>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.ouedkniss.com%2Fsearch%3Fkeyword%3Dpharmacie">Recherche: pharmacie - Ouedkniss</a>
  <a class="result__snippet" href="#">321 annonces.</a>
</div>
</body></html>"""


def test_ddg_pipeline_keeps_directory_profiles_and_blocks_listings():
    """The real SERP-parse + gate call-site contract (issue #8 acceptance).

    Ouedkniss store pages and Pages Jaunes DZ business profiles must
    survive the quality gate; the Cybo aggregator and Ouedkniss's own
    search page must not.
    """
    import httpx

    from infrastructure.scrapers.duckduckgo import DuckDuckGoScraper

    scraper = DuckDuckGoScraper(httpx.AsyncClient())
    results = scraper._parse_serp(DDG_SERP_FIXTURE)
    assert len(results) == 4, "fixture SERP must parse to 4 results"

    kept_urls = [
        r["url"] for r in results
        if not scraper._spam_filter.is_spam(r["url"], r["title"])
    ]
    assert "https://www.ouedkniss.com/store/pharmacie-en-nour" in kept_urls
    assert "https://www.lespagesjaunes-algerie.com/lieu/pharmacie-centrale.html" in kept_urls
    assert not any("cybo.com" in u for u in kept_urls)
    assert not any("ouedkniss.com/search" in u for u in kept_urls)
