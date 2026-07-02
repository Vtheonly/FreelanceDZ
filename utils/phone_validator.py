"""Smart phone validator backed by Google's ``libphonenumber``.

Replaces the brittle regex-based extraction that misclassified zip codes
and dimensions as phone numbers. Every extracted number is:

* Parsed with a default region (``DZ``) when no country code is present.
* Validated with ``phonenumbers.is_valid_number`` — invalid numbers are
  silently dropped.
* Classified by line type (Mobile / Landline / VoIP / Toll-free).
* Geocoded to a region name and carrier name when available.
* Formatted into E.164, international, and national representations.

The validator is stateless and thread-safe; the same instance can be
shared across coroutines.
"""

from __future__ import annotations

import logging
from typing import Iterable

import phonenumbers
from phonenumbers import PhoneNumberMatcher, carrier, geocoder

from core.constants import DEFAULT_PHONE_REGION
from domain.enums import PhoneType
from domain.value_objects import PhoneDetails


_logger = logging.getLogger("utils.phone_validator")


# Map libphonenumber's internal PhoneNumberType enum onto our PhoneType.
# FIXED_LINE_OR_MOBILE is treated as LANDLINE because we cannot tell the
# two apart without carrier data — being conservative avoids pitching
# WhatsApp campaigns to landlines.
_PHONE_TYPE_MAP: dict[int, PhoneType] = {
    phonenumbers.PhoneNumberType.MOBILE: PhoneType.MOBILE,
    phonenumbers.PhoneNumberType.FIXED_LINE: PhoneType.LANDLINE,
    phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE: PhoneType.LANDLINE,
    phonenumbers.PhoneNumberType.VOIP: PhoneType.VOIP,
    phonenumbers.PhoneNumberType.TOLL_FREE: PhoneType.TOLL_FREE,
    phonenumbers.PhoneNumberType.PREMIUM_RATE: PhoneType.PREMIUM_RATE,
}


class SmartPhoneValidator:
    """Extract and validate phone numbers from free text.

    Usage
    -----
    >>> validator = SmartPhoneValidator()
    >>> phones = validator.extract_and_validate("Contact: 0555 12 34 56")
    >>> phones[0].e164
    '+213555123456'
    >>> phones[0].phone_type
    <PhoneType.MOBILE: 'MOBILE'>
    """

    def __init__(self, default_region: str = DEFAULT_PHONE_REGION) -> None:
        self._default_region = default_region.upper()

    def extract_and_validate(
        self,
        text: str,
        default_region: str | None = None,
    ) -> list[PhoneDetails]:
        """Scan ``text`` for phone numbers and return validated ``PhoneDetails``.

        Parameters
        ----------
        text:
            Raw text to scan. May contain multiple numbers.
        default_region:
            Override the default region for this call only.

        Returns
        -------
        list[PhoneDetails]
            One entry per *valid, unique* number found. Duplicates (same
            E.164) are collapsed; the first occurrence wins.
        """
        if not text:
            return []
        region = (default_region or self._default_region).upper()
        results: list[PhoneDetails] = []
        seen_e164: set[str] = set()

        for match in PhoneNumberMatcher(text, region):
            try:
                details = self._build_details(match, region)
            except Exception as exc:
                # Never let a single bad number abort the whole scan.
                _logger.debug("Skipped phone candidate %r: %s", match.raw_string, exc)
                continue
            if details is None or details.e164 in seen_e164:
                continue
            seen_e164.add(details.e164)
            results.append(details)

        return results

    def validate_single(self, raw: str, default_region: str | None = None) -> PhoneDetails | None:
        """Validate a single phone string. Returns ``None`` if invalid."""
        if not raw:
            return None
        region = (default_region or self._default_region).upper()
        try:
            num_obj = phonenumbers.parse(raw, region)
        except phonenumbers.NumberParseException:
            return None
        if not phonenumbers.is_valid_number(num_obj):
            return None
        return self._details_from_numobj(num_obj, raw)

    # ------------------------------------------------------------------
    #  Internal helpers
    # ------------------------------------------------------------------

    def _build_details(self, match: PhoneNumberMatcher.Match, region: str) -> PhoneDetails | None:
        num_obj = match.number
        if not phonenumbers.is_valid_number(num_obj):
            return None
        return self._details_from_numobj(num_obj, match.raw_string)

    def _details_from_numobj(self, num_obj: phonenumbers.PhoneNumber, raw_string: str) -> PhoneDetails:
        e164 = phonenumbers.format_number(num_obj, phonenumbers.PhoneNumberFormat.E164)
        intl = phonenumbers.format_number(num_obj, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
        national = phonenumbers.format_number(num_obj, phonenumbers.PhoneNumberFormat.NATIONAL)
        raw_type = phonenumbers.number_type(num_obj)
        phone_type = _PHONE_TYPE_MAP.get(raw_type, PhoneType.UNKNOWN)
        region_name = geocoder.description_for_number(num_obj, "en") or None
        carrier_name = carrier.name_for_number(num_obj, "en") or None
        return PhoneDetails(
            original_string=raw_string,
            e164=e164,
            international=intl,
            national=national,
            phone_type=phone_type,
            region=region_name,
            carrier=carrier_name,
            is_valid=True,
        )

    def deduplicate(self, phones: Iterable[PhoneDetails]) -> list[PhoneDetails]:
        """Drop duplicates by E.164, preserving order."""
        seen: set[str] = set()
        out: list[PhoneDetails] = []
        for p in phones:
            if p.e164 not in seen:
                seen.add(p.e164)
                out.append(p)
        return out
