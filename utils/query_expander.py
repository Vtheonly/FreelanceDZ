"""Algerian-localised query expander.

Two-layer strategy:
  1. **Offline** — look up the query in ``ALGERIAN_DIALECT_MATRIX`` and
     return the curated FR / MSA / Darja variants. This always succeeds
     for known industries and needs no network.
  2. **Online** — if the offline lookup misses, ask the LLM to generate
     variants. The LLM call is optional; if it fails, we fall back to
     simple query modifiers ("query Algérie", "query DZ").

The expander is async because the LLM call is async. The offline path
returns immediately without yielding to the event loop when no LLM is
configured.

Input sanitation
----------------
Every query is run through ``sanitise_query()`` before it touches the
search engine. This strips shell metacharacters, control bytes, and
template-injection patterns (``{{``, ``%}``, SQL comment sequences) so a
malicious or malformed input cannot break the downstream URL builder or
the LLM prompt template.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Optional

from config.dialect_matrix import lookup_dialect_variants
from core.interfaces import ILLMClient


_logger = logging.getLogger("utils.query_expander")


# Characters that are safe to pass to a search-engine query string.
# Everything else is stripped or replaced.
_ALLOWED_QUERY_RE = re.compile(r"[^\w\sÀ-ÿ\u0600-\u06FF\u0750-\u077F\-']")

# Substrings that signal a template-injection / prompt-injection attempt.
# We drop the whole query if any of these appear — better safe than sorry.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\{\{.*\}\}", re.DOTALL),  # Jinja2
    re.compile(r"\{%.*%\}", re.DOTALL),    # Jinja2 statements
    re.compile(r"\$\{.*\}", re.DOTALL),    # shell/EL expressions
    re.compile(r"--", re.DOTALL),          # SQL comment
    re.compile(r";\s*drop\b", re.IGNORECASE),
    re.compile(r"<script", re.IGNORECASE),
)

# Maximum query length — protects against denial-of-service via huge inputs.
MAX_QUERY_LENGTH = 200


def sanitise_query(query: str) -> str:
    """Strip dangerous characters and normalise whitespace in a query string.

    * Decomposes Unicode accents (NFKD) so identical-looking queries from
      different sources normalise to the same key.
    * Drops control bytes, shell metacharacters, and template syntax.
    * Collapses internal whitespace to single spaces.
    * Truncates to ``MAX_QUERY_LENGTH`` characters.

    Raises ``ValueError`` if the sanitised result is empty or matches a
    known injection pattern — callers should catch this and reject the
    request with a 400.
    """
    if not query:
        raise ValueError("Query cannot be empty.")
    # Reject template-injection patterns up front.
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(query):
            raise ValueError(f"Query contains a forbidden pattern: {pattern.pattern!r}")
    # Decompose accents then drop combining marks for the *comparison* key,
    # but keep the original accented form for the actual search (Algerian
    # businesses are indexed with accents).
    decomposed = unicodedata.normalize("NFKC", query)
    # Strip disallowed characters (keep alphanumerics, whitespace, accented
    # Latin, Arabic, hyphens, apostrophes).
    cleaned = _ALLOWED_QUERY_RE.sub(" ", decomposed)
    # Collapse whitespace.
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        raise ValueError("Query is empty after sanitisation.")
    if len(cleaned) > MAX_QUERY_LENGTH:
        cleaned = cleaned[:MAX_QUERY_LENGTH].rsplit(" ", 1)[0]
    return cleaned


class AlgerianQueryExpander:
    """Expand a base query into FR / MSA / Darja search variants.

    Parameters
    ----------
    llm:
        Optional LLM client. When ``None``, only the offline matrix is
        used. When provided, the LLM is called *only* if the offline
        lookup misses.
    """

    def __init__(self, llm: Optional[ILLMClient] = None) -> None:
        self._llm = llm

    async def expand(self, base_query: str) -> list[str]:
        """Return a de-duplicated list of query variants.

        The original query is always first in the list so callers can
        prioritise it.

        Raises ``ValueError`` if ``base_query`` fails sanitation (empty
        after cleaning or contains an injection pattern).
        """
        if not base_query or not base_query.strip():
            return []
        # Sanitise the input up front — this is the security boundary.
        base_query = sanitise_query(base_query)

        # 1. Offline matrix.
        variants = self._expand_offline(base_query)
        if variants:
            return self._sanitise_all(variants)

        # 2. Online LLM expansion.
        if self._llm is not None:
            llm_variants = await self._expand_via_llm(base_query)
            if llm_variants:
                return self._sanitise_all(llm_variants)

        # 3. Final fallback: simple modifiers.
        return self._sanitise_all(self._fallback_variants(base_query))

    @staticmethod
    def _sanitise_all(variants: list[str]) -> list[str]:
        """Run every variant through ``sanitise_query``, dropping invalid ones.

        LLM-generated variants in particular can contain quotes or
        template syntax that would break the URL builder — we filter
        them here rather than trusting the model's output.
        """
        cleaned: list[str] = []
        for v in variants:
            try:
                cleaned.append(sanitise_query(v))
            except ValueError:
                _logger.debug("Dropped invalid query variant %r", v)
        return _dedupe_preserve_order(cleaned)

    # ------------------------------------------------------------------
    #  Strategies
    # ------------------------------------------------------------------

    def _expand_offline(self, base_query: str) -> list[str]:
        lang_map = lookup_dialect_variants(base_query)
        if lang_map is None:
            return []
        flat: list[str] = [base_query]
        for variants in lang_map.values():
            flat.extend(variants)
        # Preserve order while de-duplicating case-insensitively.
        return _dedupe_preserve_order(flat)

    async def _expand_via_llm(self, base_query: str) -> list[str]:
        try:
            raw_variants = await self._llm.expand_query(base_query)
        except Exception as exc:
            _logger.warning("LLM query expansion failed: %s. Falling back.", exc)
            return []
        if not raw_variants:
            return []
        combined = [base_query] + [str(v).strip() for v in raw_variants if str(v).strip()]
        return _dedupe_preserve_order(combined)

    def _fallback_variants(self, base_query: str) -> list[str]:
        return _dedupe_preserve_order([
            base_query,
            f"{base_query} Algérie",
            f"{base_query} DZ",
            f"{base_query} Algeria",
        ])


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    """Remove duplicates case-insensitively while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out
