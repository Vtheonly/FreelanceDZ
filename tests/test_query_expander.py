"""Tests for the query expander."""

from __future__ import annotations

import pytest

from utils.query_expander import AlgerianQueryExpander


@pytest.mark.asyncio
async def test_offline_matrix_hit():
    expander = AlgerianQueryExpander(llm=None)
    variants = await expander.expand("pharmacie")
    assert len(variants) >= 4  # original + fr + ar + darja
    assert variants[0] == "pharmacie"
    assert any("صيدلية" in v for v in variants)


@pytest.mark.asyncio
async def test_offline_matrix_miss_falls_back():
    expander = AlgerianQueryExpander(llm=None)
    variants = await expander.expand("quantum_computing")
    assert variants[0] == "quantum_computing"
    assert any("Algérie" in v for v in variants)


@pytest.mark.asyncio
async def test_empty_query_returns_empty():
    expander = AlgerianQueryExpander(llm=None)
    assert await expander.expand("") == []
    assert await expander.expand("   ") == []
