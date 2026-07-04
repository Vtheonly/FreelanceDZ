"""Database manager — connection pooling, schema bootstrap, and migrations.

This module replaces the broken "init_schema" hack from the original
codebase (which ran "ALTER TABLE" on every startup and polluted the
logs with fake errors). The new design:

* Schema is defined in a single, authoritative SQL file
  ("schema_v1.sql") with no duplicate "CREATE TABLE" blocks.
* Migrations are tracked in a "schema_migrations" table so we know
  exactly which version the database is on.
* Migrations are *idempotent* — running them twice is a no-op.
* All errors are caught and logged at the appropriate level; the
  "duplicate column" log spam is gone because we check
  "PRAGMA table_info" before adding columns.

The connection pool uses "sqlite3" directly (with "check_same_thread=False")
because SQLite's WAL mode handles concurrent readers and a single writer
efficiently. Each repository gets its own short-lived connection per
operation, which is the recommended pattern for SQLite.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from config.settings import AppSettings, get_settings
from core.exceptions import StorageError


_logger = logging.getLogger("storage.database")


_SCHEMA_DIR = Path(__file__).resolve().parent
_INITIAL_SCHEMA = _SCHEMA_DIR / "schema_v1.sql"


class DatabaseManager:
    """Owns the SQLite file and runs idempotent migrations.

    A single instance is shared across the application (created by
    "api.dependencies"). Every repository receives the same
    "DatabaseManager" and asks it for short-lived connections via the
    "connection()" context manager.

    Thread-safety
    -------------
    SQLite connections are not safe to share across threads, so we
    create a *new* connection per operation. The "WAL" journal mode
    allows concurrent readers while a write is in progress, so this
    pattern is both safe and fast.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        settings: Optional[AppSettings] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._db_path = db_path or self._settings.resolved_db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._verify_writable()
        self._lock = threading.Lock()
        self._initialised = False
        self.initialise()

    def _verify_writable(self) -> None:
        """Verify the host directory is writable before opening a connection.

        Creates a probe file, writes a byte, and removes it. Raises
        "StorageError" with a clear message if the directory is on a
        read-only mount (common in mis-configured Docker volumes).
        """
        import os
        probe = self._db_path.parent / f".deephuntr-write-probe-{os.getpid()}"
        try:
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError as exc:
            raise StorageError(
                f"Database directory {self._db_path.parent} is not writable: {exc}. "
                "Check Docker volume permissions or host filesystem mount options."
            ) from exc

    # ------------------------------------------------------------------
    #  Connection management
    # ------------------------------------------------------------------

    @property
    def db_path(self) -> Path:
        return self._db_path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a short-lived connection with WAL and FK enabled.

        Commits on clean exit, rolls back on exception. The connection
        is always closed in the "finally" block so we never leak
        file descriptors.

        Note: we use the default "isolation_level=''" (deferred) so that
        Python's sqlite3 module manages BEGIN/COMMIT automatically. This
        avoids the "cannot commit - no transaction is active" error that
        occurs when "executescript()" implicitly commits inside a
        manually-managed transaction.
        """
        conn = sqlite3.connect(
            str(self._db_path),
            timeout=30.0,
            isolation_level="",  # Deferred — Python manages BEGIN/COMMIT.
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            yield conn
            conn.commit()
        except sqlite3.Error as exc:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            _logger.error("SQLite error: %s", exc)
            raise StorageError(str(exc)) from exc
        finally:
            conn.close()

    # ------------------------------------------------------------------
    #  Schema bootstrap & migrations
    # ------------------------------------------------------------------

    def initialise(self) -> None:
        """Create the schema if missing and run any pending migrations.

        Idempotent: safe to call on every startup. The first call does
        the work; subsequent calls are no-ops.
        """
        with self._lock:
            if self._initialised:
                return
            self._create_schema()
            self._run_migrations()
            self._initialised = True
            _logger.info("Database initialised at %s", self._db_path)

    def _create_schema(self) -> None:
        """Apply the initial schema file ("schema_v1.sql")."""
        if not _INITIAL_SCHEMA.exists():
            raise StorageError(f"Schema file not found: {_INITIAL_SCHEMA}")
        schema_sql = _INITIAL_SCHEMA.read_text(encoding="utf-8")
        with self.connection() as conn:
            conn.executescript(schema_sql)

    def _run_migrations(self) -> None:
        """Run pending migrations tracked in "schema_migrations".

        Each migration is a function decorated with "@migration". The
        decorator registers the migration and its version number; this
        method runs every registered migration whose version is greater
        than the current database version, in order.
        """
        with self.connection() as conn:
            current = self._current_version(conn)
            for migration in _MIGRATIONS:
                if migration.version <= current:
                    continue
                _logger.info("Running migration %d: %s", migration.version, migration.description)
                migration.run(conn)
                conn.execute(
                    "INSERT INTO schema_migrations (version, description, applied_at) VALUES (?, ?, ?);",
                    (migration.version, migration.description, _now_iso()),
                )
            if _MIGRATIONS:
                _logger.info(
                    "Database at migration version %d (was %d)",
                    max((m.version for m in _MIGRATIONS), default=0),
                    current,
                )

    def _current_version(self, conn: sqlite3.Connection) -> int:
        """Return the highest applied migration version (0 if none)."""
        row = conn.execute(
            "SELECT MAX(version) AS v FROM schema_migrations"
        ).fetchone()
        if row is None or row["v"] is None:
            return 0
        return int(row["v"])

    # ------------------------------------------------------------------
    #  Maintenance
    # ------------------------------------------------------------------

    def vacuum(self) -> None:
        """Reclaim free space. Run periodically (e.g. once a week)."""
        with self.connection() as conn:
            conn.execute("VACUUM;")
        _logger.info("Database vacuumed.")

    def integrity_check(self) -> bool:
        """Run "PRAGMA integrity_check" and return True if healthy."""
        with self.connection() as conn:
            row = conn.execute("PRAGMA integrity_check;").fetchone()
            return bool(row and row[0] == "ok")


# ============================================================
#  Migration registry
# ============================================================

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class _Migration:
    """A single migration step."""

    __slots__ = ("version", "description", "fn")

    def __init__(self, version: int, description: str, fn) -> None:
        self.version = version
        self.description = description
        self.fn = fn

    def run(self, conn: sqlite3.Connection) -> None:
        self.fn(conn)


_MIGRATIONS: list[_Migration] = []


def migration(version: int, description: str):
    """Decorator that registers a function as a schema migration.

    Example
    -------
    .. code-block:: python

        @migration(2, "Add index on raw_records.source_url")
        def _add_index(conn):
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_raw_source_url "
                "ON raw_records (source_url);"
            )
    """
    def decorator(fn):
        _MIGRATIONS.append(_Migration(version, description, fn))
        _MIGRATIONS.sort(key=lambda m: m.version)
        return fn
    return decorator


# ============================================================
#  Migrations (each one is idempotent — uses IF NOT EXISTS / IF EXISTS)
# ============================================================

@migration(1, "Initial schema (raw_records, resolved_entities, crawl_queue, analyses, lead_scores, schema_migrations)")
def _migration_1_initial(conn: sqlite3.Connection) -> None:
    """The initial schema is applied by "_create_schema" before migrations
    run, so this migration is a no-op. It exists only to record version 1
    so that future migrations have a baseline to compare against."""
    pass


@migration(2, "Add indexes for freshness filtering")
def _migration_2_freshness_indexes(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_raw_records_age_class "
        "ON raw_records (calculated_age_class);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_raw_records_discovered_at "
        "ON raw_records (discovered_at DESC);"
    )


@migration(3, "Add indexes for entity-resolution performance")
def _migration_3_resolution_indexes(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_resolved_entities_confidence "
        "ON resolved_entities (confidence DESC);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_resolved_entities_wilaya "
        "ON resolved_entities (wilaya);"
    )


@migration(4, "Add full-text search virtual table for leads")
def _migration_4_fts(conn: sqlite3.Connection) -> None:
    """Create an FTS5 mirror of "raw_records" for fast text search.

    We use an *external-content* FTS5 table so the original rows are the
    source of truth and the FTS index is just a fast lookup. A trigger
    keeps the index in sync on insert/update/delete.
    """
    conn.executescript(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS raw_records_fts USING fts5(
            name, industry, wilaya, address, email,
            content='raw_records',
            content_rowid='id',
            tokenize='unicode61 remove_diacritics 2'
        );

        CREATE TRIGGER IF NOT EXISTS raw_records_ai AFTER INSERT ON raw_records BEGIN
            INSERT INTO raw_records_fts(rowid, name, industry, wilaya, address, email)
            VALUES (new.id, new.name, new.industry, new.wilaya, new.address, new.email);
        END;

        CREATE TRIGGER IF NOT EXISTS raw_records_ad AFTER DELETE ON raw_records BEGIN
            INSERT INTO raw_records_fts(raw_records_fts, rowid, name, industry, wilaya, address, email)
            VALUES ('delete', old.id, old.name, old.industry, old.wilaya, old.address, old.email);
        END;

        CREATE TRIGGER IF NOT EXISTS raw_records_au AFTER UPDATE ON raw_records BEGIN
            INSERT INTO raw_records_fts(raw_records_fts, rowid, name, industry, wilaya, address, email)
            VALUES ('delete', old.id, old.name, old.industry, old.wilaya, old.address, old.email);
            INSERT INTO raw_records_fts(rowid, name, industry, wilaya, address, email)
            VALUES (new.id, new.name, new.industry, new.wilaya, new.address, new.email);
        END;
        """
    )


@migration(5, "Add discovery_campaigns table for tracking background sourcing tasks")
def _migration_5_campaigns(conn: sqlite3.Connection) -> None:
    """Create a persistent queue table to monitor progress of discovery campaigns in the UI."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS discovery_campaigns (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            query          TEXT NOT NULL,
            wilaya         TEXT,
            limit_num      INTEGER NOT NULL,
            status         TEXT NOT NULL, -- pending|processing|completed|failed
            discovered_qty INTEGER DEFAULT 0,
            saved_qty      INTEGER DEFAULT 0,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL
        );
        """
    )


@migration(6, "Add is_contact column to lead_scores for Contacts feature")
def _migration_6_contacts(conn: sqlite3.Connection) -> None:
    # Check if column is_contact already exists
    cursor = conn.execute("PRAGMA table_info(lead_scores);")
    columns = [row["name"] for row in cursor.fetchall()]
    if "is_contact" not in columns:
        conn.execute("ALTER TABLE lead_scores ADD COLUMN is_contact INTEGER DEFAULT 0;")