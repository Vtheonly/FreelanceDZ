"""Tests for the phone validator."""

from __future__ import annotations

from utils.phone_validator import SmartPhoneValidator


def test_extracts_valid_algerian_mobile():
    validator = SmartPhoneValidator()
    results = validator.extract_and_validate("Call us at 0555 12 34 56 today")
    assert len(results) == 1
    assert results[0].e164 == "+213555123456"
    assert results[0].is_valid is True


def test_deduplicates_repeated_numbers():
    validator = SmartPhoneValidator()
    text = "Tel: 0555 12 34 56 / 0555123456"
    results = validator.extract_and_validate(text)
    assert len(results) == 1


def test_returns_empty_for_no_numbers():
    validator = SmartPhoneValidator()
    assert validator.extract_and_validate("no phone here") == []


def test_returns_empty_for_empty_input():
    validator = SmartPhoneValidator()
    assert validator.extract_and_validate("") == []


def test_validate_single_invalid_returns_none():
    validator = SmartPhoneValidator()
    assert validator.validate_single("not-a-number") is None


def test_validate_single_valid():
    validator = SmartPhoneValidator()
    details = validator.validate_single("+213 770 11 22 33")
    assert details is not None
    assert details.e164 == "+213770112233"
