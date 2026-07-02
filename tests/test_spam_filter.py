"""Tests for the spam filter."""

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


def test_blocks_social_platforms():
    f = SourcingSpamFilter()
    assert f.is_spam("https://facebook.com/somepage", "Some Page") is True
    assert f.is_spam("https://instagram.com/someprofile", "Some Profile") is True


def test_custom_extras():
    f = SourcingSpamFilter(extra_domains=frozenset({"example.com"}))
    assert f.is_spam("https://example.com/page", "Whatever") is True
