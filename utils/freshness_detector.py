"""Freshness detector — extracts temporal metadata from scraped text.

The detector looks for human-readable temporal hints ("updated 2 days
ago", "nouvellement ouvert", …) and converts them into structured
``FreshnessMetadata``. When HTTP headers are also supplied, the
``Last-Modified`` header is preferred over text-based heuristics.

Multiple regex patterns are tried in priority order. The first match
wins and short-circuits the rest so we don't waste CPU on long pages.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

from core.constants import FRESHNESS_UNKNOWN
from domain.enums import FreshnessAge
from domain.value_objects import FreshnessMetadata


_logger = logging.getLogger("utils.freshness")


# (pattern, unit, default_count)
# ``default_count`` is used when the regex has no capture group (e.g. "recently opened").
_TEMPORAL_PATTERNS: list[tuple[re.Pattern[str], str, int]] = [
    # English: "updated 3 hours ago"
    (re.compile(r"updated\s+(\d+)\s+hour", re.IGNORECASE), "hour", 1),
    (re.compile(r"updated\s+(\d+)\s+day", re.IGNORECASE), "day", 1),
    (re.compile(r"updated\s+(\d+)\s+week", re.IGNORECASE), "week", 1),
    (re.compile(r"updated\s+(\d+)\s+month", re.IGNORECASE), "month", 1),
    # French: "mis à jour il y a 3 jours"
    (re.compile(r"mis\s+[àa]\s+jour\s+il\s+y\s+a\s+(\d+)\s+heure", re.IGNORECASE), "hour", 1),
    (re.compile(r"mis\s+[àa]\s+jour\s+il\s+y\s+a\s+(\d+)\s+jour", re.IGNORECASE), "day", 1),
    (re.compile(r"mis\s+[àa]\s+jour\s+il\s+y\s+a\s+(\d+)\s+semaine", re.IGNORECASE), "week", 1),
    (re.compile(r"mis\s+[àa]\s+jour\s+il\s+y\s+a\s+(\d+)\s+mois", re.IGNORECASE), "month", 1),
    # Arabic: "تم التحديث منذ 3 أيام"
    (re.compile(r"تم\s+التحديث\s+منذ\s+(\d+)\s+ساعة"), "hour", 1),
    (re.compile(r"تم\s+التحديث\s+منذ\s+(\d+)\s+يوم"), "day", 1),
    (re.compile(r"تم\s+التحديث\s+منذ\s+(\d+)\s+أسبوع"), "week", 1),
    (re.compile(r"تم\s+التحديث\s+منذ\s+(\d+)\s+شهر"), "month", 1),
    # "Recently opened" / "Nouvellement ouvert" / "جديد"
    (re.compile(r"(opened\s+recently|newly\s+opened|nouvellement\s+ouvert|جديد|حديث)", re.IGNORECASE), "recent", 1),
]


class FreshnessDetector:
    """Stateless detector that converts text/headers into ``FreshnessMetadata``."""

    def detect(
        self,
        text: str,
        headers: Optional[dict[str, str]] = None,
    ) -> FreshnessMetadata:
        """Return a ``FreshnessMetadata`` value object.

        Order of priority:
        1. ``Last-Modified`` HTTP header (most reliable).
        2. ``Date`` HTTP header (less reliable, but better than nothing).
        3. First matching regex in the text.
        4. ``FreshnessAge.ARCHIVED`` sentinel.
        """
        metadata = FreshnessMetadata()

        # 1. HTTP headers take priority — they are server-controlled and
        #    more trustworthy than page text.
        if headers:
            header_metadata = self._from_headers(headers)
            if header_metadata is not None:
                return header_metadata

        # 2. Fall back to text patterns.
        if text:
            text_metadata = self._from_text(text)
            if text_metadata is not None:
                return text_metadata

        # 3. Nothing found — leave the default (ARCHIVED).
        return metadata

    # ------------------------------------------------------------------
    #  Internal helpers
    # ------------------------------------------------------------------

    def _from_headers(self, headers: dict[str, str]) -> Optional[FreshnessMetadata]:
        """Try ``Last-Modified`` first, then ``Date``."""
        for header_name in ("last-modified", "date"):
            value = headers.get(header_name) or headers.get(header_name.title())
            if not value:
                continue
            try:
                parsed = parsedate_to_datetime(value)
                if parsed is None:
                    continue
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return FreshnessMetadata(
                    last_updated=parsed,
                    relative_age_hint=f"http:{header_name}",
                    calculated_age_class=self._age_class_for(parsed),
                )
            except (TypeError, ValueError) as exc:
                _logger.debug("Could not parse %s header %r: %s", header_name, value, exc)
        return None

    def _from_text(self, text: str) -> Optional[FreshnessMetadata]:
        for pattern, unit, default_count in _TEMPORAL_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            count = default_count
            if match.groups():
                try:
                    count = int(match.group(1))
                except (ValueError, IndexError):
                    count = default_count
            return self._build_from_unit(unit, count, hint=match.group(0).strip())
        return None

    def _build_from_unit(self, unit: str, count: int, hint: str) -> FreshnessMetadata:
        now = datetime.now(timezone.utc)
        if unit == "hour":
            last_updated = now - timedelta(hours=count)
            age_class = FreshnessAge.HOURLY if count <= 1 else FreshnessAge.DAILY
        elif unit == "day":
            last_updated = now - timedelta(days=count)
            age_class = FreshnessAge.DAILY if count <= 1 else FreshnessAge.WEEKLY
        elif unit == "week":
            last_updated = now - timedelta(weeks=count)
            age_class = FreshnessAge.WEEKLY if count <= 1 else FreshnessAge.MONTHLY
        elif unit == "month":
            last_updated = now - timedelta(days=count * 30)
            age_class = FreshnessAge.MONTHLY
        elif unit == "recent":
            last_updated = now
            age_class = FreshnessAge.HOURLY
        else:
            last_updated = None
            age_class = FreshnessAge.ARCHIVED
            hint = FRESHNESS_UNKNOWN
        return FreshnessMetadata(
            last_updated=last_updated,
            relative_age_hint=hint,
            calculated_age_class=age_class,
        )

    def _age_class_for(self, dt: datetime) -> FreshnessAge:
        """Bucket a datetime into a ``FreshnessAge`` based on age."""
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = now - dt
        if age <= timedelta(hours=1):
            return FreshnessAge.HOURLY
        if age <= timedelta(days=1):
            return FreshnessAge.DAILY
        if age <= timedelta(weeks=1):
            return FreshnessAge.WEEKLY
        if age <= timedelta(days=30):
            return FreshnessAge.MONTHLY
        return FreshnessAge.ARCHIVED
