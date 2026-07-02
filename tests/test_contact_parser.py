"""Tests for the centralised contact parser (Task 55)."""

from __future__ import annotations

from utils.contact_parser import (
    classify_social_platform,
    extract_emails,
    extract_first_email,
    extract_social_links,
)


def test_extracts_simple_email():
    assert extract_first_email("Contact us at hello@pharmacie-dz.com") == "hello@pharmacie-dz.com"


def test_lowercases_email():
    assert extract_first_email("Email: John.Doe@Pharmacie.COM") == "john.doe@pharmacie.com"


def test_deduplicates_emails():
    text = "Reach us at a@x.com or a@x.com again"
    assert extract_emails(text) == ["a@x.com"]


def test_filters_blocked_domains():
    # ``example.com`` is in the blocked list.
    assert extract_emails("mail@example.com") == []


def test_returns_none_when_no_email():
    assert extract_first_email("no email here") is None
    assert extract_emails("") == []


def test_rejects_trailing_dot_local_part():
    # Trailing dot before @ is invalid in the local part.
    assert extract_emails("invalid.@x.com") == []


def test_rejects_leading_dot_from_local_part():
    # A leading dot means the email does not start with an alphanumeric,
    # so the regex (which requires an alphanumeric start) rejects it.
    result = extract_emails(".invalid@x.com")
    assert result == []


def test_extract_social_links_filters_share_buttons():
    hrefs = [
        "https://facebook.com/pharmacie.dergal",
        "https://facebook.com/sharer/sharer.php?u=foo",
        "https://www.instagram.com/pharmacie_dergal/",
        "https://example.com/about",  # not a social link
    ]
    result = extract_social_links(hrefs)
    assert "https://facebook.com/pharmacie.dergal" in result
    assert "https://www.instagram.com/pharmacie_dergal/" in result
    assert all("sharer" not in r for r in result)
    assert all("example.com" not in r for r in result)


def test_classify_social_platform():
    assert classify_social_platform("https://facebook.com/x") == "facebook"
    assert classify_social_platform("https://instagram.com/x") == "instagram"
    assert classify_social_platform("https://linkedin.com/company/x") == "linkedin"
    assert classify_social_platform("https://tiktok.com/@x") == "tiktok"
    assert classify_social_platform("https://example.com") is None
