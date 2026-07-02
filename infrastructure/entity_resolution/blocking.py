"""Trigram blocking — groups records that share at least one character trigram.

Blocking is the *canopy* step that prevents the O(N²) pairwise
comparison blow-up. Only records in the same block are compared by the
expensive graph matcher.

The algorithm:
1. Normalise each record's name (lowercase, alnum only).
2. Split into 3-character shingles (trigrams).
3. Index records by trigram — any two records sharing a trigram land in
   the same candidate block.

Blocks that are too large (> ``max_block_size``) are skipped because
they almost always correspond to generic trigrams (e.g. "pha" matches
every pharmacy) and would produce noisy candidate pairs.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any


_logger = logging.getLogger("entity_resolution.blocking")


class TrigramBlocker:
    """Group records by shared character trigrams."""

    def __init__(self, max_block_size: int = 100) -> None:
        self._max_block_size = max_block_size

    def generate_blocks(self, records: list[dict[str, Any]]) -> dict[str, list[int]]:
        """Return a mapping of trigram → list of record indices."""
        blocks: dict[str, list[int]] = defaultdict(list)
        for idx, rec in enumerate(records):
            name = str(rec.get("name", "")).lower()
            clean = re.sub(r"[^a-z0-9]", "", name)
            if len(clean) < 3:
                # Single hash bucket for very short names.
                blocks.setdefault("__short__", []).append(idx)
                continue
            trigrams = {clean[i : i + 3] for i in range(len(clean) - 2)}
            for tg in trigrams:
                blocks[tg].append(idx)
        return blocks

    def candidate_pairs(self, records: list[dict[str, Any]]) -> set[tuple[int, int]]:
        """Return a set of ``(i, j)`` index pairs to compare, i < j."""
        blocks = self.generate_blocks(records)
        pairs: set[tuple[int, int]] = set()
        for trigram, members in blocks.items():
            if len(members) < 2 or len(members) > self._max_block_size:
                continue
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    a, b = members[i], members[j]
                    pairs.add((min(a, b), max(a, b)))
        _logger.debug(
            "Trigram blocking: %d records → %d blocks → %d candidate pairs",
            len(records), len(blocks), len(pairs),
        )
        return pairs
