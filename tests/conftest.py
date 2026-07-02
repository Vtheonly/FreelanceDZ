"""Shared pytest fixtures."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


# Ensure the project root is on sys.path so ``import config``, ``import core``,
# etc. work from any test file.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Use a temp directory for test data so we never touch real data.
os.environ.setdefault("DATABASE_PATH", str(PROJECT_ROOT / "data" / "test.db"))
os.environ.setdefault("LLM_API_KEY", "")
os.environ.setdefault("LOG_LEVEL", "WARNING")


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Return a fresh temp database path for each test."""
    return tmp_path / "test.db"
