"""Tests for the storage layer (database + repositories)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from domain.enums import DataSource
from domain.models import BusinessRaw
from infrastructure.storage.database import DatabaseManager
from infrastructure.storage.repositories.raw_record_repo import RawRecordRepository


def test_database_initialises_cleanly(tmp_db: Path):
    db = DatabaseManager(db_path=tmp_db)
    assert tmp_db.exists()
    assert db.integrity_check() is True


def test_database_idempotent_init(tmp_db: Path):
    """Calling ``initialise()`` twice must not raise or duplicate tables."""
    db = DatabaseManager(db_path=tmp_db)
    db.initialise()  # second call should be a no-op
    assert db.integrity_check() is True


def test_raw_record_save_and_retrieve(tmp_db: Path):
    async def _run():
        db = DatabaseManager(db_path=tmp_db)
        repo = RawRecordRepository(db)
        biz = BusinessRaw(
            name="Test Pharmacy",
            industry="Pharmacy",
            wilaya="Algiers",
            website="https://test.dz",
            phone="+213555123456",
            email="contact@test.dz",
            source=DataSource.MOCK,
        )
        row_id = await repo.save(biz)
        assert row_id is not None
        retrieved = await repo.get_by_id(row_id)
        assert retrieved is not None
        assert retrieved.name == "Test Pharmacy"
        assert retrieved.website == "https://test.dz"

    asyncio.run(_run())


def test_raw_record_duplicate_fingerprint_upsert(tmp_db: Path):
    """Saving the same business twice should not create a duplicate row."""
    async def _run():
        db = DatabaseManager(db_path=tmp_db)
        repo = RawRecordRepository(db)
        biz = BusinessRaw(
            name="Test Pharmacy",
            industry="Pharmacy",
            wilaya="Algiers",
            website="https://test.dz",
            source=DataSource.MOCK,
        )
        first_id = await repo.save(biz)
        second_id = await repo.save(biz)
        # Same row id returned (upsert).
        assert first_id == second_id
        count = await repo.count()
        assert count == 1

    asyncio.run(_run())
