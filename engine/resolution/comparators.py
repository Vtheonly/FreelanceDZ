"""Per-signal comparison of two feature records.

Every comparator returns one ``SignalResult`` whose contributions are
pre-weighted and sorted into three evidence buckets:

- ``identity`` — evidence that both records describe the SAME physical
  business/location (shared phone, matching social handle, cross
  references, co-location, shared email address).
- ``org`` — evidence of a shared ORGANIZATION without implying one
  location (name similarity, a chain's shared website domain, shared
  email domain, industry overlap).
- ``conflict`` — evidence of disagreement (disjoint phones, different
  cities, disjoint verified addresses, different official domains).

The three-bucket split is what lets the classifier distinguish the
relationships the spec demands: identity evidence merges records,
organizational evidence links them (branches/franchises), and conflicts
block merging without blocking linking.

Weighted signals (agreement / disagreement), calibrated on the Café Atlas
scenarios in the feature spec:

    phone            identity +0.80 | conflict 0.40 (disjoint);
                     org +0.35 (shared channel — a hotline used by two
                     locations is organizational evidence, and never merges
                     them by itself)
    social handle    identity +0.90 same-platform equal,
                                +0.75 cross-platform equal,
                                scaled by handle similarity otherwise
                     conflict 0.25 (same platform, different handles)
    cross reference  identity +0.80 (social), +0.60 (domain link)
    email exact      identity +0.70
    website domain   org +1.00, identity +0.50 (chains share domains,
                     so domain agreement alone must not merge)
    geo coords       identity +0.60 (<200m) / 0.40 (<2km) / 0.20 (<10km)
    wilaya           identity +0.15 agree | conflict 0.30 differ
    address tokens   identity +0.40 * jaccard | conflict 0.50 when both
                     substantive and disjoint (two verified different
                     locations — the branch signature)
    name             org +0.50 * similarity (never identity: identical
                     names must not merge, different names must not veto)
    email domain     org +0.30 | conflict 0.15
    domain mismatch  conflict 0.35
    industry         org +0.15 | conflict 0.05
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from engine.resolution.features import RecordFeatures

IDENTITY = "identity"
ORG = "org"
CONFLICT = "conflict"

# Structured tags the classifier reasons over (no note-string matching).
TAG_SAME_PLACE = "same_place"                 # geo < 200 m or address overlap >= 0.5
TAG_LOCATION_DISAGREEMENT = "location_disagreement"  # different wilaya / disjoint addresses
TAG_CONTACT_DISAGREEMENT = "contact_disagreement"    # disjoint phones

# Phone/email/domain weights.
W_PHONE_MATCH = 0.80
W_PHONE_ORG = 0.35
W_PHONE_CONFLICT = 0.40
W_SOCIAL_SAME_PLATFORM = 0.90
W_SOCIAL_CROSS_PLATFORM = 0.75
W_SOCIAL_CONFLICT = 0.25
W_XREF_SOCIAL = 0.80
W_XREF_DOMAIN = 0.60
W_EMAIL_EXACT = 0.70
W_EMAIL_DOMAIN = 0.30
W_EMAIL_CONFLICT = 0.15
W_DOMAIN_ORG = 1.00
W_DOMAIN_IDENTITY = 0.50
W_DOMAIN_CONFLICT = 0.35

# Location weights.
W_GEO_SAME_PLACE = 0.60     # < 200 m
W_GEO_NEIGHBOURHOOD = 0.40  # < 2 km
W_GEO_CITY = 0.20           # < 10 km
W_WILAYA_AGREE = 0.15
W_WILAYA_CONFLICT = 0.30
W_ADDRESS_MATCH = 0.40
W_ADDRESS_CONFLICT = 0.50

# Organizational weights.
W_NAME = 0.50
W_INDUSTRY = 0.15
W_INDUSTRY_CONFLICT = 0.05

# Handle-similarity bar below which two handles on the same platform are
# treated as different accounts rather than variants of one account.
HANDLE_SIMILARITY_BAR = 0.80


@dataclass(slots=True)
class SignalResult:
    """One comparator's weighted contribution to the evidence buckets."""

    signal: str
    identity: float = 0.0
    org: float = 0.0
    conflict: float = 0.0
    note: str = ""
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "signal": self.signal,
            "identity": self.identity,
            "org": self.org,
            "conflict": self.conflict,
            "note": self.note,
            "tags": list(self.tags),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _lev_ratio(a: str, b: str) -> float:
    """Plain Levenshtein ratio for short strings (handles, addresses)."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return 1.0 - (prev[-1] / max(len(a), len(b)))


def _token_jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _substantive(tokens: set[str]) -> bool:
    """An address is substantive (comparable) with >= 2 content tokens —
    real DZ addresses like '45 Boulevard de la Soummam, Oran' carry only
    two content tokens once street words and numbers are stripped."""
    return len(tokens) >= 2


# ---------------------------------------------------------------------------
# Comparators
# ---------------------------------------------------------------------------

def _compare_name(a: RecordFeatures, b: RecordFeatures, name_sim: float) -> SignalResult:
    note = f"name similarity {name_sim:.2f}"
    if not a.name_k or not b.name_k:
        return SignalResult("name", org=0.0, note="name unavailable after normalization")
    return SignalResult("name", org=W_NAME * name_sim, note=note)


def _compare_phone(a: RecordFeatures, b: RecordFeatures) -> SignalResult:
    pa, pb = a.phones, b.phones
    if not pa or not pb:
        return SignalResult("phone", note="phone unavailable on one side")
    shared = pa & pb
    if shared:
        ratio = len(shared) / min(len(pa), len(pb))
        return SignalResult(
            "phone", identity=W_PHONE_MATCH * ratio, org=W_PHONE_ORG,
            note=f"shared phone {'+'.join(sorted(shared)[:2])}",
        )
    return SignalResult(
        "phone", conflict=W_PHONE_CONFLICT, tags=(TAG_CONTACT_DISAGREEMENT,),
        note=f"disjoint phones ({len(pa)} vs {len(pb)})",
    )


def _compare_domain(a: RecordFeatures, b: RecordFeatures) -> SignalResult:
    da, db = a.website_domain, b.website_domain
    if not da or not db:
        return SignalResult("website", note="website unavailable on one side")
    if da == db:
        return SignalResult(
            "website", org=W_DOMAIN_ORG, identity=W_DOMAIN_IDENTITY,
            note=f"shared domain {da}",
        )
    return SignalResult("website", conflict=W_DOMAIN_CONFLICT,
                        note=f"different domains {da} vs {db}")


def _compare_social(a: RecordFeatures, b: RecordFeatures) -> SignalResult:
    if not a.socials or not b.socials:
        return SignalResult("social", note="social identity unavailable on one side")

    best = 0.0
    best_note = ""
    conflict = 0.0
    for platform, ha in a.socials.items():
        hb = b.socials.get(platform)
        if hb is None:
            continue
        if ha == hb:
            score = W_SOCIAL_SAME_PLATFORM
            best_note = f"same {platform} handle @{ha}"
        else:
            sim = _lev_ratio(ha, hb)
            if sim >= HANDLE_SIMILARITY_BAR:
                score = W_SOCIAL_SAME_PLATFORM * sim
                best_note = f"near-equal {platform} handles @{ha}/@{hb}"
            else:
                conflict = max(conflict, W_SOCIAL_CONFLICT)
                continue
        best = max(best, score)

    if best == 0.0 and conflict == 0.0:
        # No overlapping platform: compare handles across platforms —
        # the same handle string on two platforms is meaningful for a
        # small business's cross-channel presence.
        for platform, ha in a.socials.items():
            for platform_b, hb in b.socials.items():
                if platform == platform_b:
                    continue
                if ha == hb:
                    best = W_SOCIAL_CROSS_PLATFORM
                    best_note = f"handle @{ha} on {platform} and {platform_b}"
                    break
            if best:
                break

    if best > 0.0:
        return SignalResult("social", identity=best, note=best_note)
    if conflict > 0.0:
        return SignalResult("social", conflict=conflict,
                            note="different handles on a shared platform")
    return SignalResult("social", note="no comparable social handles")


def _compare_cross_reference(a: RecordFeatures, b: RecordFeatures) -> SignalResult:
    """Does one record explicitly reference the other's identity?

    Strong same-entity evidence: the official website lists the Facebook
    page that is the other record; a directory entry links the business's
    homepage. Domain==domain agreement is excluded here (the website
    comparator owns it) so one underlying fact is never counted twice.
    Uses the per-record precomputed token sets (frozenset intersection).
    """
    social_hit = (a.outbound_set & b.self_set) | (b.outbound_set & a.self_set)
    if social_hit:
        hit = next((t for t in social_hit if t[0] == "social"), None)
        if hit is not None:
            return SignalResult("cross_reference", identity=W_XREF_SOCIAL,
                                note=f"record references {hit[1]}")

    # Domain reference: A's listed links point at B's official site while
    # A does not itself claim that site (that case is the domain signal).
    if a.website_domain and b.website_domain and a.website_domain == b.website_domain:
        return SignalResult("cross_reference", note="covered by website signal")
    a_links_b = any(
        t[0] == "domain" and t[1] == b.website_domain and t[1] != a.website_domain
        for t in (a.outbound_set & b.self_set)
    )
    b_links_a = any(
        t[0] == "domain" and t[1] == a.website_domain and t[1] != b.website_domain
        for t in (b.outbound_set & a.self_set)
    )
    if a_links_b or b_links_a:
        target = b.website_domain if a_links_b else a.website_domain
        return SignalResult("cross_reference", identity=W_XREF_DOMAIN,
                            note=f"record links to {target}")
    return SignalResult("cross_reference", note="no cross references")


def _compare_email(a: RecordFeatures, b: RecordFeatures) -> SignalResult:
    if not a.emails or not b.emails:
        return SignalResult("email", note="email unavailable on one side")
    if a.emails & b.emails:
        return SignalResult("email", identity=W_EMAIL_EXACT,
                            note=f"shared email {sorted(a.emails & b.emails)[0]}")
    if a.email_domains & b.email_domains:
        shared = sorted(a.email_domains & b.email_domains)[0]
        return SignalResult("email", org=W_EMAIL_DOMAIN,
                            note=f"shared email domain @{shared}")
    return SignalResult("email", conflict=W_EMAIL_CONFLICT,
                        note="different email domains")


def _compare_geo(a: RecordFeatures, b: RecordFeatures) -> SignalResult:
    if a.has_geo and b.has_geo:
        km = _haversine_km(a.latitude, a.longitude, b.latitude, b.longitude)
        if km < 0.2:
            return SignalResult("geo", identity=W_GEO_SAME_PLACE,
                                tags=(TAG_SAME_PLACE,),
                                note=f"coordinates {km * 1000:.0f} m apart")
        if km < 2.0:
            return SignalResult("geo", identity=W_GEO_NEIGHBOURHOOD,
                                note=f"coordinates {km:.1f} km apart")
        if km < 10.0:
            return SignalResult("geo", identity=W_GEO_CITY,
                                note=f"coordinates {km:.0f} km apart")
        if a.wilaya and b.wilaya and a.wilaya != b.wilaya:
            return SignalResult("geo", conflict=W_WILAYA_CONFLICT,
                                tags=(TAG_LOCATION_DISAGREEMENT,),
                                note=f"different wilayas ({a.wilaya} vs {b.wilaya})")
        return SignalResult("geo", note=f"coordinates {km:.0f} km apart, same wilaya")
    if a.wilaya and b.wilaya:
        if a.wilaya == b.wilaya:
            return SignalResult("geo", identity=W_WILAYA_AGREE,
                                note=f"same wilaya ({a.wilaya})")
        return SignalResult("geo", conflict=W_WILAYA_CONFLICT,
                            tags=(TAG_LOCATION_DISAGREEMENT,),
                            note=f"different wilayas ({a.wilaya} vs {b.wilaya})")
    return SignalResult("geo", note="geography unavailable")


def _compare_address(a: RecordFeatures, b: RecordFeatures) -> SignalResult:
    ta, tb = a.address_tokens, b.address_tokens
    if not ta or not tb:
        return SignalResult("address", note="address unavailable on one side")
    if not (_substantive(ta) and _substantive(tb)):
        return SignalResult("address", note="address too sparse to compare")
    jac = _token_jaccard(ta, tb)
    if jac >= 0.5:
        return SignalResult("address", identity=W_ADDRESS_MATCH * jac,
                            tags=(TAG_SAME_PLACE,),
                            note=f"address overlap {jac:.2f}")
    if jac <= 0.2:
        # Two verified, substantive, disjoint addresses is the signature
        # of two locations (chain branches) — block merging, allow linking.
        return SignalResult("address", conflict=W_ADDRESS_CONFLICT,
                            tags=(TAG_LOCATION_DISAGREEMENT,),
                            note=f"disjoint verified addresses (overlap {jac:.2f})")
    return SignalResult("address", note=f"partial address overlap {jac:.2f}")


def _compare_industry(a: RecordFeatures, b: RecordFeatures) -> SignalResult:
    if not a.industry_k or not b.industry_k:
        return SignalResult("industry", note="industry unavailable")
    ta = set(a.industry_k.split())
    tb = set(b.industry_k.split())
    if ta & tb:
        return SignalResult("industry", org=W_INDUSTRY,
                            note=f"shared category {sorted(ta & tb)[:2]}")
    return SignalResult("industry", conflict=W_INDUSTRY_CONFLICT,
                        note="different categories")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def compare_pair(
    a: RecordFeatures, b: RecordFeatures, name_sim: float
) -> list[SignalResult]:
    """All signal comparisons for one candidate pair."""
    return [
        _compare_name(a, b, name_sim),
        _compare_phone(a, b),
        _compare_domain(a, b),
        _compare_social(a, b),
        _compare_cross_reference(a, b),
        _compare_email(a, b),
        _compare_geo(a, b),
        _compare_address(a, b),
        _compare_industry(a, b),
    ]
