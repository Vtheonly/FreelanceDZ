"""Tests for the freshness detector."""

from __future__ import annotations

from datetime import datetime, timezone

from domain.enums import FreshnessAge
from utils.freshness_detector import FreshnessDetector


def test_detects_english_hour_hint():
    d = FreshnessDetector()
    meta = d.detect("Updated 1 hour ago by admin")
    assert meta.calculated_age_class == FreshnessAge.HOURLY
    assert meta.last_updated is not None


def test_detects_french_day_hint():
    d = FreshnessDetector()
    meta = d.detect("Mis à jour il y a 3 jours")
    assert meta.calculated_age_class == FreshnessAge.WEEKLY
    assert meta.relative_age_hint is not None


def test_detects_arabic_hint():
    d = FreshnessDetector()
    meta = d.detect("تم التحديث منذ 2 يوم")
    assert meta.calculated_age_class in (FreshnessAge.DAILY, FreshnessAge.WEEKLY)


def test_falls_back_to_archived():
    d = FreshnessDetector()
    meta = d.detect("no temporal info here")
    assert meta.calculated_age_class == FreshnessAge.ARCHIVED


def test_http_header_takes_priority():
    d = FreshnessDetector()
    headers = {"last-modified": "Mon, 01 Jan 2024 00:00:00 GMT"}
    meta = d.detect("Updated 1 hour ago", headers=headers)
    assert meta.last_updated is not None
    assert meta.last_updated.year == 2024


def test_empty_text_returns_archived():
    d = FreshnessDetector()
    meta = d.detect("")
    assert meta.calculated_age_class == FreshnessAge.ARCHIVED
