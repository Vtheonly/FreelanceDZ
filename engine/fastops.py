"""Optimized pure-Python engine hot paths (v4 Task 13).

Replaces the former C++20/ctypes "SIMD" core (``engine_native/`` +
``engine.native``), which carried real costs and no real wins:

    * the HTML scanner did no actual SIMD work — a pre-compiled regex scan
      over the decoded document is at least as fast and needs no compiler,
      no ctypes marshalling, and no cross-platform .so shipping;
    * the global C bloom filter had thread-safety bugs and leaked state
      across engine instances — replaced by a per-instance bounded dedup
      set (correctness first: the SQLite frontier's UNIQUE constraint
      remains the authoritative dedup);
    * the C Levenshtein was slower than ``rapidfuzz``'s C implementation
      for our call pattern (short business names) — rapidfuzz is already
      a pinned dependency.

Every function here has semantics covered by tests (formerly
``test_native_parity``; now ``test_fastops``). The scoring arithmetic is
the single source of truth for both ``LeadScorer`` and the batch path —
including the v4 Task 10 opportunity inversion: absence of web presence
is a *sales opportunity*, not a penalty. Since issue #16 the two
opportunity bonuses are **gated on contactability** (a phone number or
an email address): a record with no way to reach the business can no
longer collect opportunity points from missing fields alone — ghost
records (spam snippets, uncontactable listings) used to score up to
62.5 with zero substance.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field

from rapidfuzz.distance import Levenshtein

logger = logging.getLogger("engine.fastops")

# ---------------------------------------------------------------------------
# Channel flags (bit layout unchanged — persisted score_breakdown depends
# on the *names*, the flags are process-internal).
# ---------------------------------------------------------------------------
FLAG_WEBSITE = 1 << 0
FLAG_SSL = 1 << 1
FLAG_PHONE = 1 << 2
FLAG_MOBILE = 1 << 3
FLAG_WHATSAPP = 1 << 4
FLAG_EMAIL = 1 << 5
FLAG_SOCIAL = 1 << 6
FLAG_ADDRESS = 1 << 7
FLAG_GEO = 1 << 8

# v4 Task 10 — opportunity weights (conflict with refactorv5 Step 8's
# 10/5 resolved in favour of v4's numbers: its acceptance test — "verified
# phone, no website, no map pin -> score >= 60" — only passes with these).
# Issue #16: the two opportunity bonuses are awarded only to *contactable*
# leads (phone or email present) — see the gate in score_batch.
WEIGHTS = {
    "phone_present": 15.0,
    "mobile_direct": 10.0,
    "whatsapp_ready": 5.0,
    "email_present": 5.0,
    "website_active": 10.0,
    "social_channel": 5.0,
    "physical_location": 5.0,
    "geo_verified": 5.0,
    "website_build_opportunity": 15.0,
    "local_seo_opportunity": 10.0,
    "deficit_multiplier": 0.25,
}

FRESHNESS_POINTS = (15.0, 10.0, 7.0, 4.0, 2.0)

_MAX_LINKS = 128
_MAX_PHONES = 16
_JSONLD_CAP = 8192


# ---------------------------------------------------------------------------
# HTML extraction — pre-compiled regex scan (zero DOM allocation)
# ---------------------------------------------------------------------------
@dataclass
class ExtractionResult:
    """Structural signals extracted from a business page."""
    title: str = ""
    meta_description: str = ""
    canonical_url: str = ""
    og_title: str = ""
    og_description: str = ""
    email: str = ""
    lang: str = ""
    json_ld: str = ""
    links: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)

    @property
    def has_signal(self) -> bool:
        return bool(self.title or self.json_ld or self.phones or self.email)


_TITLE_RE = re.compile(rb"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_DESC_RE = re.compile(
    rb"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"']([^\"']*)[\"']"
    rb"|<meta[^>]+content=[\"']([^\"']*)[\"'][^>]+name=[\"']description[\"']",
    re.IGNORECASE,
)
_OG_TITLE_RE = re.compile(rb"<meta[^>]+property=[\"']og:title[\"'][^>]+content=[\"']([^\"']*)[\"']", re.IGNORECASE)
_OG_DESC_RE = re.compile(rb"<meta[^>]+property=[\"']og:description[\"'][^>]+content=[\"']([^\"']*)[\"']", re.IGNORECASE)
_CANONICAL_RE = re.compile(rb"<link[^>]+rel=[\"']canonical[\"'][^>]+href=[\"']([^\"']*)[\"']", re.IGNORECASE)
_HTML_LANG_RE = re.compile(rb"<html[^>]+lang=[\"']([^\"'\s]+)[\"']", re.IGNORECASE)
_JSONLD_RE = re.compile(rb"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
_HREF_RE = re.compile(rb"<a[^>]+href=[\"']([^\"']+)[\"']", re.IGNORECASE)
_PHONE_SCAN_RE = re.compile(r"(?<!\d)(?:\+213|00213|0[567])[\d\s\-.]{7,18}[\d]")
_MAILTO_RE = re.compile(r"mailto:([^\"'>\s?&]+)", re.IGNORECASE)
_WS_RE = re.compile(rb"\s+")


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def _first_group(match: "re.Match[bytes] | None", group: int = 1) -> str:
    if match is None:
        return ""
    try:
        return _decode(match.group(group) or b"").strip()
    except IndexError:
        return ""


def extract_html(html: bytes | str) -> ExtractionResult:
    """Zero-DOM structural scan of a business page.

    One pass of pre-compiled regexes over the raw bytes captures title,
    meta description, OpenGraph tags, canonical URL, language, JSON-LD,
    anchors (tel:/mailto:/links), and Algerian phone patterns from text.
    Malformed markup is tolerated by design — regex scanning does not
    require a parseable tree (the scraper layer keeps a BeautifulSoup
    deep-profile fallback for pages with no signal).
    """
    raw = html.encode("utf-8", errors="ignore") if isinstance(html, str) else html
    result = ExtractionResult()
    if not raw:
        return result

    # Strip script/style bodies from the *text* scan only (keep JSON-LD,
    # which is itself inside a script tag but extracted separately first).
    jsonld_block = b""
    m = _JSONLD_RE.search(raw)
    if m:
        jsonld_block = m.group(1)
        result.json_ld = _decode(jsonld_block).strip()[:_JSONLD_CAP - 1]

    text_scan = raw
    if jsonld_block:
        text_scan = raw.replace(jsonld_block, b"", 1)

    result.title = _first_group(_TITLE_RE.search(text_scan))
    m = _META_DESC_RE.search(text_scan)
    if m:
        result.meta_description = _decode(m.group(1) or m.group(2) or b"").strip()
    result.og_title = _first_group(_OG_TITLE_RE.search(text_scan))
    result.og_description = _first_group(_OG_DESC_RE.search(text_scan))
    result.canonical_url = _first_group(_CANONICAL_RE.search(text_scan))
    result.lang = _first_group(_HTML_LANG_RE.search(raw))

    for anchor in _HREF_RE.finditer(text_scan):
        href = _decode(anchor.group(1)).strip()
        if not href or len(result.links) >= _MAX_LINKS:
            if len(result.links) >= _MAX_LINKS:
                break
            continue
        low = href.lower()
        if low.startswith("tel:"):
            num = href[4:].strip()
            if num and len(result.phones) < _MAX_PHONES:
                result.phones.append(num)
        elif low.startswith("mailto:"):
            if not result.email:
                result.email = href[7:].split("?")[0].split("&")[0].strip()
        elif not href.startswith("#") and not low.startswith("javascript:"):
            result.links.append(href)

    # Visible-text phone scan (cheap: bounded slice of de-tagged text).
    if len(result.phones) < _MAX_PHONES:
        stripped = re.sub(rb"<[^>]+>", b" ", text_scan[:262_144])
        visible = _decode(stripped)
        for match in _PHONE_SCAN_RE.finditer(visible):
            if len(result.phones) >= _MAX_PHONES:
                break
            num = match.group(0).rstrip(" -.")
            if sum(c.isdigit() for c in num) >= 9:
                result.phones.append(num)

    if not result.email:
        mail = _MAILTO_RE.search(_decode(text_scan[:262_144]))
        if mail:
            result.email = mail.group(1).strip()
    return result


# ---------------------------------------------------------------------------
# Scoring (SoA batch) — the single arithmetic source of truth
# ---------------------------------------------------------------------------
# Contactability gate (issue #16): opportunity bonuses require a direct
# contact channel. Stored as a flag mask so both the batch path and
# LeadScorer.explain can share the exact same definition.
FLAG_CONTACTABLE = FLAG_PHONE | FLAG_EMAIL


def _flag_sums(flags: int) -> tuple[float, int, bool]:
    """Scalar reference for the flag-derived scoring components.

    Returns ``(reach + substance + opportunity, digital_health_without_the
    social_count_bonus, has_social_flag)``. This is the exhaustive oracle the
    lookup-table batch path is parity-tested against (tests/test_fastops.py)
    and the definition LeadScorer.explain mirrors factor-by-factor.
    """
    health = 10
    if flags & FLAG_WEBSITE:
        health += 35
        if flags & FLAG_SSL:
            health += 10
    if flags & FLAG_PHONE:
        health += 15
    if flags & FLAG_EMAIL:
        health += 10
    if flags & FLAG_ADDRESS:
        health += 5
    # The social bonus (10 + min(count, 2) * 5) is added by the caller
    # because it depends on the per-lead social count.

    reach = 0.0
    if flags & FLAG_PHONE:
        reach += 15.0
    if flags & FLAG_MOBILE:
        reach += 10.0
    if flags & FLAG_WHATSAPP:
        reach += 5.0
    if flags & FLAG_EMAIL:
        reach += 5.0

    substance = 0.0
    if flags & FLAG_WEBSITE:
        substance += 10.0
    if flags & FLAG_SOCIAL:
        substance += 5.0
    if flags & FLAG_ADDRESS:
        substance += 5.0
    if flags & FLAG_GEO:
        substance += 5.0

    # v4 Task 10 — absence is opportunity, not penalty; issue #16 — but
    # only for businesses we can actually reach (phone or email).
    opportunity = 0.0
    contactable = bool(flags & FLAG_CONTACTABLE)
    if contactable and not flags & FLAG_WEBSITE:
        opportunity += WEIGHTS["website_build_opportunity"]
    if contactable and not flags & FLAG_ADDRESS and not flags & FLAG_GEO:
        opportunity += WEIGHTS["local_seo_opportunity"]

    return reach + substance + opportunity, health, bool(flags & FLAG_SOCIAL)


# The channel flags are a 9-bit word (512 combinations). Every flag-derived
# score component is therefore a pure function of a small integer — so the
# whole space is precomputed once at import into a flat lookup table and the
# batch loop collapses to one list index per lead (issue #16's measured
# hot-path optimization: official harness `python cli.py bench`, 100k flags
# — 3,457,148/s LUT vs 943,656/s for the scalar oracle with identical
# gated semantics, i.e. 3.66x, zero new dependencies, zero per-lead
# allocations; a numpy variant measured 26.8M rec/s but was rejected —
# see docs/12-performance.md). Exhaustive parity with the scalar oracle is
# asserted in tests/test_fastops.py::TestIssue16LUTParity. The table covers
# exactly the 9 channel flags; a future 10th flag must extend it (an
# out-of-range flag word raises IndexError here rather than scoring
# wrongly in silence).
_SCORE_LUT: list[tuple[float, int, bool]] = [_flag_sums(f) for f in range(512)]


def score_batch(
    flags: list[int],
    social_counts: list[int] | None = None,
    freshness_buckets: list[int] | None = None,
) -> tuple[list[float], list[int]]:
    """Batch channel-flag scoring (SoA layout, one pass, no per-lead calls).

    Digital health mirrors ``BusinessAnalyzer``'s audit arithmetic; the
    priority score is reach + substance + opportunity + deficit +
    freshness, capped at 100. The v4 Task 10 opportunity bonuses (no
    website; no address AND no GPS) apply only to contactable leads
    (phone or email) — issue #16's ghost-record fix. Semantics are
    identical to ``_flag_sums`` (the scalar oracle); only the cost model
    differs (precomputed 512-entry lookup table).
    """
    n = len(flags)
    if n == 0:
        return [], []
    socials = social_counts if social_counts is not None else [0] * n
    fresh = freshness_buckets if freshness_buckets is not None else [4] * n

    priorities: list[float] = []
    digitals: list[int] = []
    lut = _SCORE_LUT
    fresh_points = FRESHNESS_POINTS
    priorities_append = priorities.append
    digitals_append = digitals.append

    for f, soc, fb in zip(flags, socials, fresh):
        rsop, health, has_social = lut[f]
        if has_social:
            health += 10 + (soc if soc < 2 else 2) * 5
        if health > 100:
            health = 100
        deficit = (100.0 - health) * WEIGHTS["deficit_multiplier"]
        total = rsop + deficit + fresh_points[fb if 0 <= fb < 5 else 4]
        priorities_append(total if total < 100.0 else 100.0)
        digitals_append(health)
    return priorities, digitals


def score_batch_reference(
    flags: list[int],
    social_counts: list[int] | None = None,
    freshness_buckets: list[int] | None = None,
) -> tuple[list[float], list[int]]:
    """Exhaustive scalar twin of ``score_batch`` (the test oracle).

    Branch-by-branch evaluation of every factor — kept as a permanent
    reference implementation so parity is an assertion, not an assumption
    (issue #16: "keep an exhaustive scorer as a test oracle").
    """
    n = len(flags)
    if n == 0:
        return [], []
    socials = social_counts if social_counts is not None else [0] * n
    fresh = freshness_buckets if freshness_buckets is not None else [4] * n

    priorities: list[float] = []
    digitals: list[int] = []
    for f, soc, fb in zip(flags, socials, fresh):
        rsop, health, has_social = _flag_sums(f)
        if has_social:
            health = min(100, health + 10 + min(soc, 2) * 5)
        deficit = (100.0 - health) * WEIGHTS["deficit_multiplier"]
        fb_idx = fb if 0 <= fb < 5 else 4
        total = rsop + deficit + FRESHNESS_POINTS[fb_idx]
        priorities.append(min(100.0, total))
        digitals.append(health)
    return priorities, digitals


# ---------------------------------------------------------------------------
# String metrics (rapidfuzz-backed, byte-level semantics preserved)
# ---------------------------------------------------------------------------
def levenshtein(a: str, b: str) -> int:
    """Byte-level Levenshtein (business names are compared as UTF-8 bytes,
    matching the historical native semantics)."""
    ab = a.encode("utf-8") if isinstance(a, str) else a
    bb = b.encode("utf-8") if isinstance(b, str) else b
    if not ab or not bb:
        return len(ab) + len(bb)
    return int(Levenshtein.distance(ab, bb))


def trigram_bitset(text: str) -> set[int]:
    """256-bucket trigram presence over UTF-8 bytes (unchanged semantics)."""
    b = text.encode("utf-8")
    return {
        ((b[i] * 961) ^ (b[i + 1] * 31) ^ b[i + 2]) & 255
        for i in range(max(0, len(b) - 2))
    }


def trigram_jaccard(a: str, b: str) -> float:
    sa, sb = trigram_bitset(a), trigram_bitset(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


# ---------------------------------------------------------------------------
# Name-matching session (entity resolution candidate verification)
# ---------------------------------------------------------------------------
class NameMatcher:
    """Bitset prefilter + Levenshtein verification over a registered corpus.

    Instance-scoped (the former global C session crossed engine instances);
    safe to use from any single resolution run.
    """

    def __init__(self) -> None:
        self._names: list[str] = []
        self._bitsets: list[set[int]] = []

    def reset(self, expected_count: int = 4096) -> None:  # noqa: ARG002 - API compat
        self._names.clear()
        self._bitsets.clear()

    def add(self, name: str) -> int:
        if not name:
            return -1
        self._names.append(name)
        self._bitsets.append(trigram_bitset(name))
        return len(self._names) - 1

    def add_many(self, names: list[str]) -> int:
        names = [n for n in names if n]
        if not names:
            return -1
        first = len(self._names)
        self._names.extend(names)
        self._bitsets.extend(trigram_bitset(n) for n in names)
        return first

    def match_pairs(
        self,
        pairs: list[tuple[int, int]],
        jaccard_prefilter: float = 0.4,
        name_threshold: float = 0.78,
    ) -> list[float]:
        if not pairs:
            return []
        results: list[float] = []
        for ia, ib in pairs:
            if ia >= len(self._names) or ib >= len(self._names):
                results.append(0.0)
                continue
            sa, sb = self._bitsets[ia], self._bitsets[ib]
            jac = (len(sa & sb) / len(sa | sb)) if (sa and sb) else 0.0
            if jac < jaccard_prefilter:
                results.append(0.0)
                continue
            a, b = self._names[ia], self._names[ib]
            if not a or not b:
                results.append(0.0)
                continue
            dist = levenshtein(a, b)
            la, lb = len(a.encode("utf-8")), len(b.encode("utf-8"))
            sim = 1.0 - dist / max(la, lb)
            results.append(sim if sim >= name_threshold else 0.0)
        return results

    def __len__(self) -> int:
        return len(self._names)


# ---------------------------------------------------------------------------
# URL dedup — per-instance, bounded, thread-safe (replaces the global bloom)
# ---------------------------------------------------------------------------
class UrlDedup:
    """Bounded seen-URL set with a hard memory ceiling.

    Past the cap the set stops growing and reports every URL as unseen —
    the persistent frontier's UNIQUE(url) constraint in SQLite remains the
    authoritative dedup layer, so correctness is preserved while memory is
    capped. A lock makes the instance safe under the crawler's worker
    threads (the old global C filter had no locking at all).
    """

    def __init__(self, capacity: int = 200_000) -> None:
        self._capacity = capacity
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def test_and_add(self, url: str) -> bool:
        """True = already seen (probable duplicate)."""
        with self._lock:
            if len(self._seen) >= self._capacity:
                return False
            seen = url in self._seen
            self._seen.add(url)
            return seen

    def test(self, url: str) -> bool:
        with self._lock:
            return url in self._seen

    def clear(self) -> None:
        with self._lock:
            self._seen.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._seen)
