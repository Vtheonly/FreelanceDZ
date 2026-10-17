"""Feature extraction & normalization for entity resolution.

Every comparison in the pipeline works on ``RecordFeatures`` rather than
raw ``Lead`` values so that normalization is computed once per record
(work elimination) and the comparators stay pure and testable.

Normalization decisions (deterministic, locale-aware for Algeria):

- Names: NFKD fold + combining-mark strip (é->e, so "Café Atlas" and
  "Cafe Atlas" compare equal), lowercase, alphanumeric key, token set
  with Algerian legal-form suffixes stripped (SARL/EURL/ETS/SPA/...).
  Light Arabic normalization (tatweel, diacritics, alef/ya/ta-marbuta
  folding) so Arabic-script variants of the same name compare equal;
  cross-script matching deliberately relies on other signals.
- Phones: E.164 digit sets from structured details first, raw string
  fallback — "+213(0)550-12-34-56" and "0550123456" normalize to the
  same key when the details carry the E.164 form.
- Websites: registrable-domain extraction (path/query/``www.`` stripped).
  A social-platform URL in the ``website`` field is routed to the social
  identity (platform + handle) instead — "facebook.com/x" vs
  "facebook.com/y" is a *social* comparison, not a website match.
- Social identity: (platform, handle) pairs harvested from social_links
  and from source_url when the record itself IS a social profile.
- Addresses: token set minus French/Arabic street stopwords; wilaya is
  normalized through the wilaya registry (case/diacritics-insensitive).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

from config.wilayas import WILAYAS
from domain.models import Lead

# ---------------------------------------------------------------------------
# Normalization tables
# ---------------------------------------------------------------------------

# Algerian / French legal forms and trading styles that carry no identity.
_LEGAL_SUFFIXES = {
    "sarl", "eurl", "ets", "etablissement", "ste", "societe", "société",
    "spa", "snc", "sa", "eid", "epic", "fondation", "association",
    "co", "ltd", "llc", "inc", "gmbh", "bv", "cie", "compagnie",
}

# Words that describe what a business is, not which one it is. They stay
# in the name key (they do distinguish e.g. "Café Atlas" the venue from a
# hypothetical "Atlas" shipping company) but are dropped from the
# *blocking* prefix so "Café Atlas" and "Café Atlas Restaurant" land in
# the same prefix block.
_TYPE_WORDS = {
    "restaurant", "cafe", "café", "coffee", "hotel", "pharmacie",
    "boulangerie", "patisserie", "pâtisserie", "bureau", "clinique",
    "cabinet", "garage", "boutique", "market", "supermarche", "pizzeria",
    "fast", "food", "agence", "institut", "ecole", "école", "salon",
}

# Social platforms whose URLs are identities, not websites.
_SOCIAL_PLATFORMS = {
    "facebook.com": "facebook",
    "fb.com": "facebook",
    "m.facebook.com": "facebook",
    "instagram.com": "instagram",
    "linkedin.com": "linkedin",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "tiktok.com": "tiktok",
    "youtube.com": "youtube",
    "pinterest.com": "pinterest",
    "snapchat.com": "snapchat",
    "business.facebook.com": "facebook",
}

# Public registrable domains that must never count as a business website.
_PROVIDER_DOMAINS = {
    "facebook.com", "fb.com", "instagram.com", "linkedin.com", "twitter.com",
    "x.com", "tiktok.com", "youtube.com", "pinterest.com", "snapchat.com",
    "google.com", "google.dz", "bing.com", "search.marcia.fr", "duckduckgo.com",
    "yelp.com", "tripadvisor.com", "pagesjaunes.dz", "menusdz.com",
    "blogspot.com", "wordpress.com", "wixsite.com", "godaddysites.com",
    "mail.ru", "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "live.com", "protonmail.com",
}

# Private-suffix style second-level domains where the registrable unit is
# the third label (co.uk pattern — plus DZ hosting patterns we may see).
_MULTI_PART_TLDS = {"com.dz", "net.dz", "org.dz", "edu.dz", "gov.dz", "asso.dz", "co.uk", "com.fr"}

_ADDRESS_STOPWORDS = {
    "rue", "avenue", "av", "bd", "boulevard", "chemin", "place", "pl",
    "route", "lotissement", "lot", "cite", "cité", "villa", "immeuble",
    "imm", "bloc", "etage", "étage", "bp", "boite", "box", "n", "no",
    "nr", "num", "numero", "numéro", "de", "du", "la", "le", "les", "el",
    "al", "derriere", "devant", "pres", "zone", "industrielle", "zi",
    "quartier", "hai", "mahalla", "شارع", "حي", "رقم", "طريق",
}

_ARABIC_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670\u0640]")
_NON_ALNUM = re.compile(r"[^a-z0-9\u0600-\u06FF]+")
_URL_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


def fold_text(text: str) -> str:
    """NFKD fold, strip combining marks, lowercase, drop tatweel/diacritics."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.lower()


def _fold_arabic(text: str) -> str:
    """Normalize Arabic-script variance: alef forms, ya/alef-maqsura,
    ta-marbuta, tatweel, diacritics."""
    text = _ARABIC_DIACRITICS.sub("", text)
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ئ", "ي")
    text = text.replace("ة", "ه")
    return text


def name_key(name: str) -> str:
    """Alphanumeric comparison key over legal-suffix-stripped tokens:
    'Café Atlas' / 'cafe atlas' -> 'cafeatlas', and 'Boulangerie ETS
    Benali' / 'boulangerie benali' -> 'boulangeriebenali' (the legal form
    is styling, not identity)."""
    if not name:
        return ""
    return "".join(name_tokens(name))


def name_tokens(name: str) -> list[str]:
    """Order-insensitive token view with legal suffixes stripped."""
    folded = _fold_arabic(fold_text(name))
    raw = [t for t in re.split(r"[^a-z0-9\u0600-\u06FF]+", folded) if t]
    return [t for t in raw if t not in _LEGAL_SUFFIXES]


def blocking_prefix(name: str, limit: int = 8) -> str:
    """Type-word-stripped name prefix used as an extra blocking key."""
    tokens = [t for t in name_tokens(name) if t not in _TYPE_WORDS]
    key = name_key(" ".join(tokens))
    return key[:limit]


def _normalise_digit_phone(digits: str) -> str:
    """Canonical digit form for Algerian numbers.

    '0555112233' (national), '213555112233' (E.164 without +) and
    '2130555112233' (+213(0) form with the national-prefix zero kept)
    all reduce to '213555112233', so a Google profile listing the
    national format and a website listing +213 compare equal.
    """
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 10 and digits.startswith("0"):
        digits = "213" + digits[1:]
    if len(digits) == 13 and digits.startswith("2130"):
        digits = "213" + digits[4:]
    return digits


def phone_digits(lead: Lead) -> set[str]:
    """Normalized E.164 digit sets — structured details first, raw string
    fallback — so '+213(0)550-12-34-56', '0550123456' and '+213550123456'
    all produce the same key."""
    numbers: set[str] = set()
    for p in lead.phone_details:
        if p.e164:
            digits = "".join(ch for ch in p.e164 if ch.isdigit())
            if digits:
                numbers.add(_normalise_digit_phone(digits))
    if not numbers and lead.phone:
        digits = "".join(ch for ch in lead.phone if ch.isdigit())
        if digits:
            numbers.add(_normalise_digit_phone(digits))
    return numbers


def registrable_domain(url: Optional[str]) -> str:
    """Last two labels (three under multi-part TLDs), '' when absent.

    Social platforms and generic providers return '' — they are routed to
    social-identity comparison instead of website comparison, so that
    'facebook.com/x' vs 'facebook.com/y' is never scored as a website
    agreement (the v3.0 composite scorer's blind spot).
    """
    if not url:
        return ""
    raw = url.strip().lower()
    if not _URL_SCHEME.match(raw):
        raw = "http://" + raw
    try:
        host = (urlparse(raw).hostname or "").rstrip(".")
    except ValueError:
        return ""
    if not host:
        return ""
    if host in _SOCIAL_PLATFORMS or host in _PROVIDER_DOMAINS:
        return ""
    labels = host.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in _MULTI_PART_TLDS:
        domain = ".".join(labels[-3:])
    elif len(labels) >= 2:
        domain = ".".join(labels[-2:])
    else:
        domain = host
    if domain in _PROVIDER_DOMAINS:
        return ""
    return domain


def social_handle_from_url(url: Optional[str]) -> Optional[tuple[str, str]]:
    """(platform, handle) when the URL is a social profile, else None."""
    if not url:
        return None
    raw = url.strip().lower()
    if not _URL_SCHEME.match(raw):
        raw = "http://" + raw
    try:
        host = (urlparse(raw).hostname or "").rstrip(".")
        path = (urlparse(raw).path or "").strip("/")
    except ValueError:
        return None
    platform = _SOCIAL_PLATFORMS.get(host)
    if not platform or not path:
        return None
    handle = path.split("/")[0]
    if not handle or handle in {"pages", "p", "people", "profile", "company", "public"}:
        return None
    return platform, handle


def email_domain(email: str) -> str:
    """Registrable domain of the mail host (explicit '@' split — an email
    is never fed to the URL parser, even though urlparse happens to
    tolerate it via userinfo parsing)."""
    if not email or "@" not in email:
        return ""
    return registrable_domain(email.rsplit("@", 1)[1])


def _social_identities(lead: Lead) -> dict[str, str]:
    """platform -> handle, from social_links and (when the record itself is
    a social profile) from source_url. Later entries win; conflicts between
    a record's own profile URL and a listed link are rare and the handle
    comparison tolerates near-misses."""
    identities: dict[str, str] = {}
    for url in lead.social_links:
        parsed = social_handle_from_url(url)
        if parsed:
            identities[parsed[0]] = parsed[1]
    own = social_handle_from_url(lead.source_url)
    if own:
        identities[own[0]] = own[1]
    return identities


def _norm_wilaya(wilaya: str) -> str:
    """Registry-normalized wilaya name (diacritic-folded, en/fr/ar accepted).

    Falls back to the folded input when the registry has no match, so an
    unregistered place name still compares consistently (folded) instead
    of silently becoming empty and dropping the wilaya signal.
    """
    folded = fold_text(wilaya or "").strip()
    if not folded:
        return ""
    for w in WILAYAS:
        if folded in {
            fold_text(str(w["name_en"])),
            fold_text(str(w["name_fr"])),
            str(w["name_ar"]),
        }:
            return fold_text(str(w["name_en"]))
    return folded


def _address_tokens(address: Optional[str]) -> set[str]:
    if not address:
        return set()
    folded = _fold_arabic(fold_text(address))
    raw = {t for t in re.split(r"[^a-z0-9\u0600-\u06FF]+", folded) if t}
    return {t for t in raw if t not in _ADDRESS_STOPWORDS and not t.isdigit()}


# ---------------------------------------------------------------------------
# The feature record
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class RecordFeatures:
    """Comparable view of one Lead — computed once, compared N times."""

    index: int                       # position in the resolve batch
    lead_id: Optional[int]
    lead: Lead

    name: str = ""                   # raw display name
    name_k: str = ""                 # name_key (folded alnum)
    tokens: list[str] = field(default_factory=list)
    prefix: str = ""                 # blocking prefix (type words stripped)

    phones: set[str] = field(default_factory=set)          # E.164 digits
    emails: set[str] = field(default_factory=set)          # lowercased
    email_domains: set[str] = field(default_factory=set)   # registrable

    website_domain: str = ""         # registrable domain (socials excluded)
    link_domains: set[str] = field(default_factory=set)  # domains referenced by social_links
    socials: dict[str, str] = field(default_factory=dict)  # platform -> handle

    # Precomputed identity-token sets (work elimination: built once per
    # record instead of twice per candidate pair — the profiler showed
    # per-pair rebuilding dominating at 100k+ pairs).
    outbound_set: frozenset[tuple[str, str]] = frozenset()
    self_set: frozenset[tuple[str, str]] = frozenset()

    wilaya: str = ""                 # normalized
    address_tokens: set[str] = field(default_factory=set)
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    industry_k: str = ""             # folded industry string

    # ---- derived helpers used by comparators ---------------------------
    @property
    def has_geo(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def outbound_tokens(self) -> set[tuple[str, str]]:
        """Identity tokens this record *points at*: social profiles it
        lists, its own website domain, and any business domains its
        social_links reference. Used for cross-reference detection —
        record A referencing record B's identity is strong same-entity
        evidence (a Facebook page listed on the official website, a
        directory linking the business homepage)."""
        return set(self.outbound_set)

    def self_tokens(self) -> set[tuple[str, str]]:
        """Identity tokens this record *is*: its own social profile (from
        source_url) and its website domain."""
        return set(self.self_set)


def extract_features(index: int, lead: Lead) -> RecordFeatures:
    """Normalize one lead into its comparable feature view."""
    emails = {(e or "").strip().lower() for e in [lead.email] if e}
    email_domains = {email_domain(e) for e in emails} - {""}
    link_domains: set[str] = set()
    for url in lead.social_links:
        d = registrable_domain(url)
        if d:
            link_domains.add(d)

    socials = _social_identities(lead)
    website_domain = registrable_domain(lead.website)
    own_social = social_handle_from_url(lead.source_url)

    outbound: set[tuple[str, str]] = {
        ("social", f"{p}:{h}") for p, h in socials.items()
    }
    if website_domain:
        outbound.add(("domain", website_domain))
    for d in link_domains:
        outbound.add(("domain", d))

    self_tokens: set[tuple[str, str]] = set()
    if own_social:
        self_tokens.add(("social", f"{own_social[0]}:{own_social[1]}"))
    if website_domain:
        self_tokens.add(("domain", website_domain))

    return RecordFeatures(
        index=index,
        lead_id=lead.id,
        lead=lead,
        name=(lead.name or "").strip(),
        name_k=name_key(lead.name or ""),
        tokens=name_tokens(lead.name or ""),
        prefix=blocking_prefix(lead.name or ""),
        phones=phone_digits(lead),
        emails=emails,
        email_domains=email_domains,
        website_domain=website_domain,
        link_domains=link_domains,
        socials=socials,
        outbound_set=frozenset(outbound),
        self_set=frozenset(self_tokens),
        wilaya=_norm_wilaya(lead.wilaya),
        address_tokens=_address_tokens(lead.address),
        latitude=lead.latitude,
        longitude=lead.longitude,
        industry_k=fold_text(lead.industry or "").strip(),
    )
