from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from loveca.db.bootstrap import (
    LegacySchemaError,
    UnsupportedSchemaVersionError,
    get_schema_version,
    has_required_tables,
    initialize_database,
)
from loveca.db.schema import REQUIRED_TABLES, SCHEMA_VERSION


def test_required_phase_one_tables_are_named():
    assert REQUIRED_TABLES == (
        "schema_metadata",
        "import_batches",
        "card_sets",
        "gameplay_cards",
        "card_printings",
        "member_card_attributes",
        "live_card_attributes",
        "card_heart_values",
        "special_blade_hearts",
        "source_observations",
        "card_text_revisions",
        "card_text_revision_observations",
        "works",
        "units",
        "gameplay_card_works",
        "gameplay_card_units",
        "printing_references",
        "normalization_candidates",
    )


def test_initialize_database_is_versioned_and_idempotent(tmp_path):
    database_path = tmp_path / "catalog.sqlite3"

    initialize_database(database_path)
    initialize_database(database_path)

    assert get_schema_version(database_path) == SCHEMA_VERSION
    assert has_required_tables(database_path)


def test_unversioned_legacy_schema_is_rejected(tmp_path):
    database_path = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("CREATE TABLE cards (id INTEGER PRIMARY KEY)")
        connection.commit()

    with pytest.raises(LegacySchemaError):
        initialize_database(database_path)


def test_unsupported_schema_version_is_rejected(tmp_path):
    database_path = tmp_path / "future.sqlite3"
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute(
            "CREATE TABLE schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_metadata (key, value) VALUES ('schema_version', '99')"
        )
        connection.commit()

    with pytest.raises(UnsupportedSchemaVersionError):
        initialize_database(database_path)


def test_card_type_triggers_reject_invalid_attribute_ownership(tmp_path):
    database_path = tmp_path / "catalog.sqlite3"
    initialize_database(database_path)

    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        member_id = connection.execute(
            """
            INSERT INTO gameplay_cards (
                card_code,
                canonical_name_ja,
                card_type
            )
            VALUES ('MEMBER-001', 'メンバー', 'member')
            """
        ).lastrowid
        energy_id = connection.execute(
            """
            INSERT INTO gameplay_cards (
                card_code,
                canonical_name_ja,
                card_type
            )
            VALUES ('ENERGY-001', 'エネルギー', 'energy')
            """
        ).lastrowid

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO live_card_attributes (gameplay_card_id) VALUES (?)",
                (member_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO member_card_attributes (gameplay_card_id)
                VALUES (?)
                """,
                (energy_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO special_blade_hearts (
                    gameplay_card_id,
                    ordinal,
                    effect_type,
                    value,
                    source_alt,
                    source_field
                )
                VALUES (?, 0, 'score', 1, 'スコア1', '特殊ハート')
                """,
                (member_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO card_heart_values (
                    gameplay_card_id,
                    heart_role,
                    color_slot,
                    value
                )
                VALUES (?, 'basic', 'heart0', 1)
                """,
                (member_id,),
            )
