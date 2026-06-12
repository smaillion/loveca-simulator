"""Database creation and schema-version helpers."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from loveca.db.schema import REQUIRED_TABLES, SCHEMA_SQL, SCHEMA_VERSION


class DatabaseSchemaError(RuntimeError):
    """Base error for unsupported local database layouts."""


class LegacySchemaError(DatabaseSchemaError):
    """Raised when an unversioned prototype schema is detected."""


class UnsupportedSchemaVersionError(DatabaseSchemaError):
    """Raised when a database uses an unsupported schema version."""


def connect_database(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with closing(connect_database(database_path)) as connection:
        existing = _list_tables(connection)
        if existing and "schema_metadata" not in existing:
            raise LegacySchemaError(
                "unversioned legacy schema detected; automatic migration is not supported"
            )

        if "schema_metadata" in existing:
            version = _get_schema_version(connection)
            if version != SCHEMA_VERSION:
                raise UnsupportedSchemaVersionError(
                    f"database schema version {version!r} is not supported; "
                    f"expected {SCHEMA_VERSION}"
                )

        connection.executescript(SCHEMA_SQL)


def get_schema_version(database_path: Path) -> int | None:
    if not database_path.exists():
        return None

    with closing(connect_database(database_path)) as connection:
        existing = _list_tables(connection)
        if not existing:
            return None
        if "schema_metadata" not in existing:
            raise LegacySchemaError(
                "unversioned legacy schema detected; automatic migration is not supported"
            )
        return _get_schema_version(connection)


def list_tables(database_path: Path) -> tuple[str, ...]:
    if not database_path.exists():
        return ()
    with closing(connect_database(database_path)) as connection:
        return tuple(sorted(_list_tables(connection)))


def has_required_tables(database_path: Path) -> bool:
    existing = set(list_tables(database_path))
    return set(REQUIRED_TABLES).issubset(existing)


def _list_tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        """
    ).fetchall()
    return {str(row[0]) for row in rows}


def _get_schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        raise UnsupportedSchemaVersionError("schema_metadata has no schema_version")
    try:
        return int(row[0])
    except (TypeError, ValueError) as exc:
        raise UnsupportedSchemaVersionError(
            f"invalid schema_version value: {row[0]!r}"
        ) from exc
