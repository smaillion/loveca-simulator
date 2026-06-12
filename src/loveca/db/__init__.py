"""SQLite database schema, connection, and import helpers."""

from loveca.db.bootstrap import (
    DatabaseSchemaError,
    LegacySchemaError,
    UnsupportedSchemaVersionError,
    get_schema_version,
    initialize_database,
)

__all__ = [
    "DatabaseSchemaError",
    "LegacySchemaError",
    "UnsupportedSchemaVersionError",
    "get_schema_version",
    "initialize_database",
]
