"""Tests for the query sanitiser (Task 43)."""

from __future__ import annotations

import pytest

from utils.query_expander import sanitise_query


def test_strips_shell_metacharacters():
    assert sanitise_query("pharmacie; rm -rf /") == "pharmacie rm -rf"


def test_rejects_jinja_template():
    with pytest.raises(ValueError):
        sanitise_query("{{ config.SECRET_KEY }}")


def test_rejects_sql_comment():
    with pytest.raises(ValueError):
        sanitise_query("pharmacie -- DROP TABLE users")


def test_rejects_sql_drop():
    with pytest.raises(ValueError):
        sanitise_query("pharmacie; DROP TABLE users")


def test_rejects_script_tag():
    with pytest.raises(ValueError):
        sanitise_query("<script>alert(1)</script>")


def test_preserves_arabic_text():
    assert sanitise_query("صيدلية") == "صيدلية"


def test_preserves_accents():
    assert sanitise_query("pharmacie Algérie") == "pharmacie Algérie"


def test_collapses_whitespace():
    assert sanitise_query("pharmacie    oran    algérie") == "pharmacie oran algérie"


def test_truncates_long_input():
    long = "a" * 500
    result = sanitise_query(long)
    assert len(result) <= 200


def test_rejects_empty():
    with pytest.raises(ValueError):
        sanitise_query("")


def test_rejects_only_special_chars():
    with pytest.raises(ValueError):
        sanitise_query("!!!@@@###")


def test_preserves_hyphens_and_apostrophes():
    assert sanitise_query("l'atelier de menuiserie") == "l'atelier de menuiserie"
    assert sanitise_query("fast-food") == "fast-food"
