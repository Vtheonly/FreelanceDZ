"""Algerian landline area-code and free-text geo-inference (Task 9, v4).

Businesses that live on Facebook/Instagram with only a landline and no map
pin and no address would otherwise be recorded with an unknown wilaya.
Algerian fixed-line numbers are geographic: the first three digits after
the leading 0 (or after the +213 country code) identify the wilaya's ARPT
numbering zone, which recovers the wilaya for a large share of such leads.
Text inference is a secondary, best-effort fallback that scans visible
snippets for wilaya mentions.

Both functions return the canonical *French* catalogue name so the value
feeds directly into ``Lead.wilaya`` and the API/UI filters. They are
pure functions (no I/O) and safe to call from any context.
"""

from __future__ import annotations

import re
from typing import Optional

from config.wilayas import AREA_CODE_TO_WILAYA, WILAYAS, get_wilaya_by_name

# Pre-compiled mention patterns: word-boundary match on every catalogue name.
# Arabic names are matched as substrings (Arabic script has no word breaks
# usable by \b for this purpose).
_NAME_PATTERN_FR_EN = re.compile(
    r"\b(" + "|".join(re.escape(str(w["name_fr"])) for w in WILAYAS) + r")\b",
    re.IGNORECASE,
)
_NAME_PATTERN_AR = re.compile(
    "|".join(re.escape(str(w["name_ar"])) for w in WILAYAS)
)


def infer_wilaya_from_phone(phone: Optional[str]) -> Optional[str]:
    """Map an Algerian landline to its wilaya via the ARPT area code.

    Accepts national (``041 33 22 11``), E.164 (``+21341332211``), and
    digit-soup formats. Mobile prefixes (05/06/07) and short numbers are
    inherently non-geographic and return ``None``.
    """
    if not phone:
        return None
    clean = "".join(ch for ch in phone if ch.isdigit())
    if clean.startswith("00213"):
        clean = "0" + clean[5:]
    elif clean.startswith("213"):
        clean = "0" + clean[3:]
    if len(clean) < 3:
        return None
    prefix = clean[:3]
    return AREA_CODE_TO_WILAYA.get(prefix)


def infer_wilaya_from_text(text: Optional[str]) -> Optional[str]:
    """Best-effort wilaya mention detection in a title/snippet blob.

    French/English names require word boundaries; Arabic names match as
    substrings. First catalogue hit (lowest wilaya code) wins — the goal is
    a hint, not a geocoder.
    """
    if not text:
        return None
    match = _NAME_PATTERN_FR_EN.search(text)
    if match:
        wilaya = get_wilaya_by_name(match.group(1))
        if wilaya:
            return str(wilaya["name_fr"])
    arabic = _NAME_PATTERN_AR.search(text)
    if arabic:
        for w in WILAYAS:
            if str(w["name_ar"]) in text:
                return str(w["name_fr"])
    return None


def get_wilaya_coordinates(wilaya_name: str) -> tuple[float, float]:
    """Representative (lat, lon) for a wilaya; defaults to Algiers."""
    w = get_wilaya_by_name(wilaya_name)
    if w and "lat" in w and "lon" in w:
        return float(w["lat"]), float(w["lon"])  # type: ignore[arg-type]
    return 36.7538, 3.0588
