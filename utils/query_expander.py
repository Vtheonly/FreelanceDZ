"""Algerian-localised query expander.

v3: the LLM expansion layer is removed (the LLM stack is gone; the offline
dialect matrix plus modifier fallbacks cover the same space deterministically
and instantly). Input sanitisation is unchanged — it is the security boundary
for everything downstream of the API.

Two-layer strategy:
  1. **Offline** — look up the query in ``ALGERIAN_DIALECT_MATRIX`` and
     return the curated FR / MSA / Darja variants. Always succeeds for
     known industries, no network.
  2. **Fallback** — simple modifiers ("query Algérie", "query DZ").
"""

from __future__ import annotations

import logging
import re
import unicodedata

from config.dialect_matrix import lookup_dialect_variants

_logger = logging.getLogger("utils.query_expander")

# Characters safe to pass to a search-engine query string.
_ALLOWED_QUERY_RE = re.compile(r"[^\w\sÀ-ÿ\u0600-\u06FF\u0750-\u077F\-']")

# Template-injection / prompt-injection patterns — reject the whole query.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\{\{.*\}\}", re.DOTALL),  # Jinja2
    re.compile(r"\{%.*%\}", re.DOTALL),    # Jinja2 statements
    re.compile(r"\$\{.*\}", re.DOTALL),    # shell/EL expressions
    re.compile(r"--", re.DOTALL),          # SQL comment
    re.compile(r";\s*drop\b", re.IGNORECASE),
    re.compile(r"<script", re.IGNORECASE),
)

MAX_QUERY_LENGTH = 200


def sanitise_query(query: str) -> str:
    """Strip dangerous characters and normalise whitespace in a query string.

    Raises ``ValueError`` if the sanitised result is empty or matches a
    known injection pattern — callers should reject the request with 400.
    """
    if not query:
        raise ValueError("Query cannot be empty.")
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(query):
            raise ValueError(f"Query contains a forbidden pattern: {pattern.pattern!r}")
    decomposed = unicodedata.normalize("NFKC", query)
    cleaned = _ALLOWED_QUERY_RE.sub(" ", decomposed)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        raise ValueError("Query is empty after sanitisation.")
    if len(cleaned) > MAX_QUERY_LENGTH:
        cleaned = cleaned[:MAX_QUERY_LENGTH].rsplit(" ", 1)[0]
    return cleaned


class AlgerianQueryExpander:
    """Expand a base query into FR / MSA / Darja search variants."""

    async def expand(self, base_query: str) -> list[str]:
        """De-duplicated variant list; the original query always comes first.

        Raises ``ValueError`` if ``base_query`` fails sanitation.
        """
        if not base_query or not base_query.strip():
            return []
        base_query = sanitise_query(base_query)

        variants = self._expand_offline(base_query)
        if variants:
            return self._sanitise_all(variants)
        return self._sanitise_all(self._fallback_variants(base_query))

    @staticmethod
    def _sanitise_all(variants: list[str]) -> list[str]:
        cleaned: list[str] = []
        for v in variants:
            try:
                cleaned.append(sanitise_query(v))
            except ValueError:
                _logger.debug("Dropped invalid query variant %r", v)
        return _dedupe_preserve_order(cleaned)

    @staticmethod
    def _expand_offline(base_query: str) -> list[str]:
        lang_map = lookup_dialect_variants(base_query)
        if lang_map is None:
            return []
        flat: list[str] = [base_query]
        for variants in lang_map.values():
            flat.extend(variants)
        return _dedupe_preserve_order(flat)

    @staticmethod
    def _fallback_variants(base_query: str) -> list[str]:
        return _dedupe_preserve_order([
            base_query,
            f"{base_query} Algérie",
            f"{base_query} DZ",
            f"{base_query} Algeria",
        ])


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out
