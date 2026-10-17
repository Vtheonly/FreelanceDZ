"""ctypes bridge to the native C++20 SIMD engine core.

Every native symbol has a pure-Python fallback with identical semantics
(verified by tests/test_native_parity.py), so the engine runs correctly even
when the shared library is absent — only slower on the hot paths.

Native hot paths and why they exist:
    - names_match_pairs : entity-resolution candidate pairs (bitset prefilter
      + Myers Levenshtein verification) in one batched C call.
    - extract_html      : zero-copy structural HTML scan (no DOM allocation).
    - bloom_*           : cache-line-blocked URL dedup for the crawl frontier.
    - score_batch       : SoA channel-flag scoring for lead batches.

The library is loaded once per process. Locate via:
    1. FDZ_NATIVE_LIB env var (explicit path)
    2. <project_root>/engine_native/libfdz_engine.so
    3. <project_root>/libfdz_engine.so
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("engine.native")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# ctypes mirrors of the C structs (keep in sync with engine_types.h)
# ---------------------------------------------------------------------------

_MAX_LINKS = 128
_MAX_PHONES = 16
_JSONLD_CAP = 8192


class _FdzLink(ctypes.Structure):
    _fields_ = [("url", ctypes.c_char * 256)]


class _FdzPhone(ctypes.Structure):
    _fields_ = [("raw", ctypes.c_char * 32)]


class _FdzExtraction(ctypes.Structure):
    _fields_ = [
        ("title", ctypes.c_char * 192),
        ("meta_description", ctypes.c_char * 256),
        ("canonical_url", ctypes.c_char * 256),
        ("og_title", ctypes.c_char * 192),
        ("og_description", ctypes.c_char * 256),
        ("email", ctypes.c_char * 96),
        ("lang", ctypes.c_char * 16),
        ("json_ld", ctypes.c_char * _JSONLD_CAP),
        ("json_ld_len", ctypes.c_uint32),
        ("link_count", ctypes.c_uint32),
        ("phone_count", ctypes.c_uint32),
        ("links", _FdzLink * _MAX_LINKS),
        ("phones", _FdzPhone * _MAX_PHONES),
    ]


@dataclass
class ExtractionResult:
    """Friendly view over a native/fallback HTML extraction."""
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


# Channel flag bit positions (mirror FDZ_FLAG_* in engine_types.h).
FLAG_WEBSITE = 1 << 0
FLAG_SSL = 1 << 1
FLAG_PHONE = 1 << 2
FLAG_MOBILE = 1 << 3
FLAG_WHATSAPP = 1 << 4
FLAG_EMAIL = 1 << 5
FLAG_SOCIAL = 1 << 6
FLAG_ADDRESS = 1 << 7
FLAG_GEO = 1 << 8

ISA_SCALAR, ISA_SSE42, ISA_AVX2, ISA_AVX512 = 0, 1, 2, 3
_ISA_NAMES = {ISA_SCALAR: "scalar", ISA_SSE42: "sse4.2", ISA_AVX2: "avx2", ISA_AVX512: "avx-512"}


def _locate_library() -> Path | None:
    env = os.environ.get("FDZ_NATIVE_LIB")
    if env:
        p = Path(env)
        if p.exists():
            return p
    for candidate in (
        PROJECT_ROOT / "engine_native" / "libfdz_engine.so",
        PROJECT_ROOT / "libfdz_engine.so",
    ):
        if candidate.exists():
            return candidate
    return None


class NativeEngine:
    """Process-wide accessor for the native core with graceful degradation."""

    _instance: "NativeEngine | None" = None

    def __init__(self) -> None:
        self._lib: ctypes.CDLL | None = None
        self._isa_level = ISA_SCALAR
        path = _locate_library()
        if path is not None:
            try:
                lib = ctypes.CDLL(str(path))
                self._bind(lib)
                self._lib = lib
                self._isa_level = int(lib.engine_isa_level())
                logger.info(
                    "Native engine core loaded (%s, ISA=%s)",
                    path.name,
                    _ISA_NAMES.get(self._isa_level, "unknown"),
                )
            except OSError as exc:  # pragma: no cover - environment dependent
                logger.warning("Native core found but failed to load (%s); using Python fallbacks", exc)
        else:
            logger.info("Native core not found; using pure-Python fallbacks")

    # -- singleton ---------------------------------------------------------
    @classmethod
    def get(cls) -> "NativeEngine":
        if cls._instance is None:
            cls._instance = NativeEngine()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Test hook: force re-discovery on next get()."""
        cls._instance = None

    # -- binding -----------------------------------------------------------
    def _bind(self, lib: ctypes.CDLL) -> None:
        u32 = ctypes.c_uint32
        u64 = ctypes.c_uint64
        f32 = ctypes.c_float
        i32 = ctypes.c_int32

        lib.engine_isa_level.argtypes = []
        lib.engine_isa_level.restype = u32

        lib.engine_score_batch.argtypes = [
            ctypes.POINTER(u64), ctypes.POINTER(u8 := ctypes.c_uint8),
            ctypes.POINTER(u8), u32, ctypes.POINTER(f32), ctypes.POINTER(u8),
        ]
        lib.engine_score_batch.restype = None

        lib.engine_names_reset.argtypes = [u32]
        lib.engine_names_reset.restype = i32

        lib.engine_names_add.argtypes = [ctypes.c_char_p, u32]
        lib.engine_names_add.restype = i32

        lib.engine_names_add_many.argtypes = [ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(u32), u32]
        lib.engine_names_add_many.restype = i32

        lib.engine_names_match_pairs.argtypes = [
            ctypes.POINTER(u32), ctypes.POINTER(u32), u32, f32, f32, ctypes.POINTER(f32),
        ]
        lib.engine_names_match_pairs.restype = i32

        lib.engine_levenshtein.argtypes = [ctypes.c_char_p, u32, ctypes.c_char_p, u32]
        lib.engine_levenshtein.restype = u32

        lib.engine_trigram_jaccard.argtypes = [ctypes.c_char_p, u32, ctypes.c_char_p, u32]
        lib.engine_trigram_jaccard.restype = f32

        lib.engine_bloom_init.argtypes = [u64, ctypes.c_double]
        lib.engine_bloom_init.restype = u32
        lib.engine_bloom_test_and_add.argtypes = [ctypes.c_char_p, u32]
        lib.engine_bloom_test_and_add.restype = u32
        lib.engine_bloom_test.argtypes = [ctypes.c_char_p, u32]
        lib.engine_bloom_test.restype = u32
        lib.engine_bloom_clear.argtypes = []
        lib.engine_bloom_clear.restype = None
        lib.engine_bloom_size.argtypes = []
        lib.engine_bloom_size.restype = u64

        lib.engine_extract_html.argtypes = [ctypes.c_char_p, u32, ctypes.POINTER(_FdzExtraction)]
        lib.engine_extract_html.restype = None

    # -- properties ----------------------------------------------------------
    @property
    def is_native(self) -> bool:
        return self._lib is not None

    @property
    def isa_level(self) -> int:
        return self._isa_level

    @property
    def isa_name(self) -> str:
        return _ISA_NAMES.get(self._isa_level, "unknown")

    # ------------------------------------------------------------------
    # Levenshtein
    # ------------------------------------------------------------------
    def levenshtein(self, a: str, b: str) -> int:
        if self._lib is not None:
            ab, bb = a.encode("utf-8"), b.encode("utf-8")
            if not ab or not bb:
                return len(ab) + len(bb)
            return int(self._lib.engine_levenshtein(ab, len(ab), bb, len(bb)))
        return self._levenshtein_py(a, b)

    @staticmethod
    def _levenshtein_py(a: str, b: str) -> int:
        """Byte-level Levenshtein (matches native, which scans UTF-8 bytes)."""
        ab = a.encode("utf-8") if isinstance(a, str) else a
        bb = b.encode("utf-8") if isinstance(b, str) else b
        try:
            from rapidfuzz.distance import Levenshtein
            return int(Levenshtein.distance(ab, bb))
        except ImportError:  # pragma: no cover
            if not ab:
                return len(bb)
            if not bb:
                return len(ab)
            prev = list(range(len(bb) + 1))
            for i, ca in enumerate(ab, 1):
                cur = [i]
                for j, cb in enumerate(bb, 1):
                    cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
                prev = cur
            return prev[-1]

    # ------------------------------------------------------------------
    # Trigram Jaccard
    # ------------------------------------------------------------------
    def trigram_jaccard(self, a: str, b: str) -> float:
        if self._lib is not None:
            ab, bb = a.encode("utf-8"), b.encode("utf-8")
            if not ab or not bb:
                return 0.0
            return float(self._lib.engine_trigram_jaccard(ab, len(ab), bb, len(bb)))
        return self._trigram_jaccard_py(a, b)

    @staticmethod
    def _trigram_bitset_py(text: str) -> set[int]:
        """256-bucket trigram presence over UTF-8 bytes (native-identical)."""
        b = text.encode("utf-8")
        return {
            ((b[i] * 961) ^ (b[i + 1] * 31) ^ b[i + 2]) & 255
            for i in range(max(0, len(b) - 2))
        }

    @classmethod
    def _trigram_jaccard_py(cls, a: str, b: str) -> float:
        sa = cls._trigram_bitset_py(a)
        sb = cls._trigram_bitset_py(b)
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)

    # ------------------------------------------------------------------
    # Batch scoring (SoA)
    # ------------------------------------------------------------------
    def score_batch(
        self,
        flags: list[int],
        social_counts: list[int] | None = None,
        freshness_buckets: list[int] | None = None,
    ) -> tuple[list[float], list[int]]:
        n = len(flags)
        if n == 0:
            return [], []
        socials = social_counts if social_counts is not None else [0] * n
        fresh = freshness_buckets if freshness_buckets is not None else [4] * n

        if self._lib is not None:
            from array import array
            arr_flags = array("Q", flags)
            arr_socials = array("B", socials)
            arr_fresh = array("B", fresh)
            out_p = (ctypes.c_float * n)()
            out_d = (ctypes.c_uint8 * n)()
            self._lib.engine_score_batch(
                (ctypes.c_uint64 * n).from_buffer(arr_flags),
                (ctypes.c_uint8 * n).from_buffer(arr_socials),
                (ctypes.c_uint8 * n).from_buffer(arr_fresh),
                n, out_p, out_d,
            )
            return list(out_p), list(out_d)
        return self._score_batch_py(flags, socials, fresh)

    @staticmethod
    def _score_batch_py(
        flags: list[int], socials: list[int], fresh: list[int]
    ) -> tuple[list[float], list[int]]:
        fresh_pts = (15.0, 10.0, 7.0, 4.0, 2.0)
        priorities: list[float] = []
        digitals: list[int] = []
        for f, soc, fb in zip(flags, socials, fresh):
            health = 10
            if f & FLAG_WEBSITE:
                health += 35
                if f & FLAG_SSL:
                    health += 10
            if f & FLAG_PHONE:
                health += 15
            if f & FLAG_EMAIL:
                health += 10
            if f & FLAG_SOCIAL:
                health += 10 + min(soc, 2) * 5
            if f & FLAG_ADDRESS:
                health += 5
            health = min(100, health)

            reach = 0.0
            if f & FLAG_PHONE:
                reach += 15.0
            if f & FLAG_MOBILE:
                reach += 10.0
            if f & FLAG_WHATSAPP:
                reach += 5.0
            if f & FLAG_EMAIL:
                reach += 5.0

            substance = 0.0
            if f & FLAG_WEBSITE:
                substance += 10.0
            if f & FLAG_SOCIAL:
                substance += 5.0
            if f & FLAG_ADDRESS:
                substance += 5.0
            if f & FLAG_GEO:
                substance += 5.0

            deficit = (100.0 - health) * 0.25
            fb_idx = fb if 0 <= fb < 5 else 4
            total = reach + substance + deficit + fresh_pts[fb_idx]
            priorities.append(min(100.0, total))
            digitals.append(health)
        return priorities, digitals

    # ------------------------------------------------------------------
    # Name-matching session (entity resolution)
    # ------------------------------------------------------------------
    def names_reset(self, expected_count: int = 4096) -> None:
        if self._lib is not None:
            self._lib.engine_names_reset(expected_count)
        self._py_names.clear()

    _py_names: list[str] = []

    def names_add(self, name: str) -> int:
        if not name:
            return -1
        if self._lib is not None:
            b = name.encode("utf-8")
            return int(self._lib.engine_names_add(b, len(b)))
        self._py_names.append(name)
        return len(self._py_names) - 1

    def names_add_many(self, names: list[str]) -> int:
        """Register a batch in one FFI call. Returns the first index (or -1)."""
        names = [n for n in names if n]
        if not names:
            return -1
        if self._lib is not None:
            encoded = [n.encode("utf-8") for n in names]
            ptrs = (ctypes.c_char_p * len(encoded))(*encoded)
            lens = (ctypes.c_uint32 * len(encoded))(*(len(e) for e in encoded))
            return int(self._lib.engine_names_add_many(ptrs, lens, len(encoded)))
        first = len(self._py_names)
        self._py_names.extend(names)
        return first

    def names_match_pairs(
        self,
        pairs: list[tuple[int, int]],
        jaccard_prefilter: float = 0.4,
        name_threshold: float = 0.78,
    ) -> list[float]:
        if not pairs:
            return []
        count = len(pairs)

        if self._lib is not None:
            from array import array
            flat_a = array("I", (p[0] for p in pairs))
            flat_b = array("I", (p[1] for p in pairs))
            out = (ctypes.c_float * count)()
            self._lib.engine_names_match_pairs(
                (ctypes.c_uint32 * count).from_buffer(flat_a),
                (ctypes.c_uint32 * count).from_buffer(flat_b),
                count, jaccard_prefilter, name_threshold, out,
            )
            return list(out)

        # Pure fallback: identical cascade (bitset prefilter, then Levenshtein).
        bitsets = [self._trigram_bitset_py(n) for n in self._py_names]
        results: list[float] = []
        for ia, ib in pairs:
            if ia >= len(bitsets) or ib >= len(bitsets):
                results.append(0.0)
                continue
            sa, sb = bitsets[ia], bitsets[ib]
            jac = (len(sa & sb) / len(sa | sb)) if (sa and sb) else 0.0
            if jac < jaccard_prefilter:
                results.append(0.0)
                continue
            a, b = self._py_names[ia], self._py_names[ib]
            if not a or not b:
                results.append(0.0)
                continue
            dist = self._levenshtein_py(a, b)
            la, lb = len(a.encode("utf-8")), len(b.encode("utf-8"))
            sim = 1.0 - dist / max(la, lb)
            results.append(sim if sim >= name_threshold else 0.0)
        return results

    # ------------------------------------------------------------------
    # Bloom filter
    # ------------------------------------------------------------------
    def bloom_init(self, expected_items: int = 2_000_000, fpr: float = 0.01) -> None:
        if self._lib is not None:
            self._lib.engine_bloom_init(expected_items, fpr)
        else:
            self._py_bloom.clear()

    _py_bloom: set[str] = set()

    def bloom_test_and_add(self, url: str) -> bool:
        """True = already seen before (probable duplicate)."""
        if self._lib is not None:
            b = url.encode("utf-8")
            return bool(self._lib.engine_bloom_test_and_add(b, len(b)))
        seen = url in self._py_bloom
        self._py_bloom.add(url)
        return seen

    def bloom_test(self, url: str) -> bool:
        if self._lib is not None:
            b = url.encode("utf-8")
            return bool(self._lib.engine_bloom_test(b, len(b)))
        return url in self._py_bloom

    def bloom_clear(self) -> None:
        if self._lib is not None:
            self._lib.engine_bloom_clear()
        else:
            self._py_bloom.clear()

    def bloom_size(self) -> int:
        if self._lib is not None:
            return int(self._lib.engine_bloom_size())
        return len(self._py_bloom)

    # ------------------------------------------------------------------
    # HTML extraction
    # ------------------------------------------------------------------
    def extract_html(self, html: bytes | str) -> ExtractionResult:
        raw = html.encode("utf-8", errors="ignore") if isinstance(html, str) else html
        if self._lib is not None and raw:
            cres = _FdzExtraction()
            self._lib.engine_extract_html(raw, len(raw), ctypes.byref(cres))
            result = ExtractionResult(
                title=cres.title.decode("utf-8", errors="replace"),
                meta_description=cres.meta_description.decode("utf-8", errors="replace"),
                canonical_url=cres.canonical_url.decode("utf-8", errors="replace"),
                og_title=cres.og_title.decode("utf-8", errors="replace"),
                og_description=cres.og_description.decode("utf-8", errors="replace"),
                email=cres.email.decode("utf-8", errors="replace"),
                lang=cres.lang.decode("utf-8", errors="replace"),
                json_ld=cres.json_ld[: cres.json_ld_len].decode("utf-8", errors="replace"),
                links=[cres.links[i].url.decode("utf-8", errors="replace")
                       for i in range(min(cres.link_count, _MAX_LINKS))],
                phones=[cres.phones[i].raw.decode("utf-8", errors="replace")
                        for i in range(min(cres.phone_count, _MAX_PHONES))],
            )
            return result
        return self._extract_html_py(raw)

    _PHONE_SCAN_RE = re.compile(
        r"(?<!\d)(?:\+213|00213|0[567])[\d\s\-.]{7,18}[\d]"
    )
    _MAILTO_RE = re.compile(r"mailto:([^\"'>\s?&]+)", re.IGNORECASE)

    @classmethod
    def _extract_html_py(cls, raw: bytes) -> ExtractionResult:
        """BeautifulSoup-based fallback producing the same signal set."""
        result = ExtractionResult()
        if not raw:
            return result
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw, "lxml")
        except Exception:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw, "html.parser")

        if soup.title and soup.title.string:
            result.title = soup.title.get_text(strip=True)

        meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
        if meta and meta.get("content"):
            result.meta_description = meta["content"].strip()

        for m in soup.find_all("meta", attrs={"property": True}):
            prop = (m["property"] or "").lower()
            content = (m.get("content") or "").strip()
            if not content:
                continue
            if prop == "og:title" and not result.og_title:
                result.og_title = content
            elif prop == "og:description" and not result.og_description:
                result.og_description = content

        if soup.html and soup.html.get("lang"):
            result.lang = soup.html["lang"]

        canonical = soup.find("link", rel=re.compile("^canonical$", re.I))
        if canonical and canonical.get("href"):
            result.canonical_url = canonical["href"].strip()

        for script in soup.find_all("script"):
            if (script.get("type") or "").strip().lower() == "application/ld+json":
                payload = script.string or script.get_text()
                if payload and payload.strip():
                    result.json_ld = payload.strip()[:_JSONLD_CAP - 1]
                    break

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href:
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
                if len(result.links) < _MAX_LINKS:
                    result.links.append(href)

        text = soup.get_text(" ")
        for match in cls._PHONE_SCAN_RE.finditer(text):
            if len(result.phones) >= _MAX_PHONES:
                break
            num = match.group(0).rstrip(" -.")
            digits = sum(c.isdigit() for c in num)
            if digits >= 9:
                result.phones.append(num)
        return result
