from __future__ import annotations

import copy
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from loveca.cards.importer import (
    CardImportConflictError,
    CardImportValidationError,
    import_normalized_cards,
    validate_normalized_cards,
)


PROJECT_ROOT = Path(__file__).parents[1]
SAMPLE_PATH = (
    PROJECT_ROOT
    / "data_samples"
    / "normalized"
    / "cards-cross-product-sample.json"
)
NORMALIZATION_PATH = (
    PROJECT_ROOT / "data_sources" / "card-entity-normalization.json"
)

EXPECTED_COUNTS = {
    "gameplay_cards": 30,
    "card_printings": 30,
    "card_sets": 6,
    "member_card_attributes": 12,
    "live_card_attributes": 12,
    "card_heart_values": 61,
    "special_blade_hearts": 11,
    "card_text_revisions": 20,
    "works": 5,
    "gameplay_card_works": 31,
    "units": 6,
    "gameplay_card_units": 14,
    "source_observations": 30,
    "printing_references": 15,
}


def test_import_cross_product_sample(tmp_path):
    database_path = tmp_path / "catalog.sqlite3"

    summary = import_normalized_cards(
        database_path,
        SAMPLE_PATH,
        NORMALIZATION_PATH,
    )

    assert summary.status == "completed"
    assert summary.records_seen == 30
    assert summary.records_imported == 30
    assert summary.review_candidates == 0
    assert _table_counts(database_path, EXPECTED_COUNTS) == EXPECTED_COUNTS

    with closing(sqlite3.connect(database_path)) as connection:
        energy_attribute_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM gameplay_cards AS card
            LEFT JOIN member_card_attributes AS member
                ON member.gameplay_card_id = card.id
            LEFT JOIN live_card_attributes AS live
                ON live.gameplay_card_id = card.id
            WHERE card.card_type = 'energy'
              AND (
                  member.gameplay_card_id IS NOT NULL
                  OR live.gameplay_card_id IS NOT NULL
              )
            """
        ).fetchone()[0]
        assert energy_attribute_count == 0


def test_reimport_is_idempotent_for_canonical_and_observation_data(tmp_path):
    database_path = tmp_path / "catalog.sqlite3"
    first = import_normalized_cards(
        database_path,
        SAMPLE_PATH,
        NORMALIZATION_PATH,
    )
    second = import_normalized_cards(
        database_path,
        SAMPLE_PATH,
        NORMALIZATION_PATH,
    )

    assert first.status == second.status == "completed"
    assert _table_counts(database_path, EXPECTED_COUNTS) == EXPECTED_COUNTS
    with closing(sqlite3.connect(database_path)) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM import_batches"
        ).fetchone()[0] == 2


def test_validate_cross_product_sample_reports_no_errors(tmp_path):
    summary = validate_normalized_cards(SAMPLE_PATH, NORMALIZATION_PATH)

    assert summary.records_seen == 30
    assert summary.records_selected == 30
    assert summary.error_count == 0
    assert summary.warning_count == 0
    assert summary.review_candidates == 0
    assert summary.per_card_set_counts == {
        "BP01": 5,
        "BP03": 5,
        "BP06": 5,
        "HSSD01": 5,
        "PLSD01": 5,
        "PR": 5,
    }


def test_incremental_import_filters_target_card_sets(tmp_path):
    database_path = tmp_path / "catalog.sqlite3"

    summary = import_normalized_cards(
        database_path,
        SAMPLE_PATH,
        NORMALIZATION_PATH,
        card_set_codes=("BP01", "PR"),
    )

    assert summary.status == "completed"
    assert summary.records_seen == 10
    assert summary.records_imported == 10
    assert summary.targeted_card_sets == ("BP01", "PR")
    with closing(sqlite3.connect(database_path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM source_observations").fetchone()[0] == 10
        assert connection.execute("SELECT COUNT(*) FROM card_sets").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM card_printings").fetchone()[0] == 10


def test_conflict_rolls_back_whole_batch_and_records_failure(tmp_path):
    database_path = tmp_path / "catalog.sqlite3"
    import_normalized_cards(database_path, SAMPLE_PATH, NORMALIZATION_PATH)
    records = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    conflicting_records = copy.deepcopy(records)
    conflicting_records[0]["name"] = "競合する名称"
    conflict_path = tmp_path / "conflict.json"
    conflict_path.write_text(
        json.dumps(conflicting_records, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(CardImportConflictError):
        import_normalized_cards(
            database_path,
            conflict_path,
            NORMALIZATION_PATH,
        )

    assert _table_counts(database_path, EXPECTED_COUNTS) == EXPECTED_COUNTS
    with closing(sqlite3.connect(database_path)) as connection:
        latest = connection.execute(
            """
            SELECT status, records_imported, error_message
            FROM import_batches
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    assert latest[0] == "failed"
    assert latest[1] == 0
    assert "canonical_name_ja conflict" in latest[2]


def test_unknown_entity_creates_review_candidate(tmp_path):
    database_path = tmp_path / "catalog.sqlite3"
    normalization = json.loads(NORMALIZATION_PATH.read_text(encoding="utf-8"))
    normalization["units"].pop("A・ZU・NA")
    incomplete_mapping = tmp_path / "normalization.json"
    incomplete_mapping.write_text(
        json.dumps(normalization, ensure_ascii=False),
        encoding="utf-8",
    )

    summary = import_normalized_cards(
        database_path,
        SAMPLE_PATH,
        incomplete_mapping,
    )

    assert summary.status == "completed_with_review"
    assert summary.review_candidates == 1
    with closing(sqlite3.connect(database_path)) as connection:
        candidate = connection.execute(
            """
            SELECT entity_type, raw_value_ja, review_status
            FROM normalization_candidates
            """
        ).fetchone()
    assert candidate == ("unit", "A・ZU・NA", "pending")


def test_duplicate_energy_card_codes_are_promoted_to_full_card_ids(tmp_path):
    database_path = tmp_path / "catalog.sqlite3"
    input_path = tmp_path / "duplicate-energy.json"
    input_path.write_text(
        json.dumps(
            [
                {
                    "card_id": "PL!SP-bp1-032-PE",
                    "card_code": "PL!SP-bp1-032",
                    "name": "ARASHI CHISATO",
                    "card_type": "エネルギー",
                    "product": "ブースターパック vol.1",
                    "product_code": "BP01",
                    "rarity": "PE",
                    "member_attributes": None,
                    "live_attributes": None,
                    "raw_effect_text": None,
                    "image_url": "https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP01/PL!SP-bp1-032-PE.png",
                    "source_url": "https://llofficial-cardgame.com/cardlist/searchresults/?title=BP01&card_kind=E&cardno=PL%21SP-bp1-032-PE",
                    "fetched_at": "2026-06-14T03:40:10+00:00",
                    "parser_version": "cardlist_spike_v0.3",
                    "parse_notes": {"import_source": "official_full_import"},
                },
                {
                    "card_id": "PL!SP-bp1-032-PE＋",
                    "card_code": "PL!SP-bp1-032",
                    "name": "ARASHI CHISATO",
                    "card_type": "エネルギー",
                    "product": "ブースターパック vol.1",
                    "product_code": "BP01",
                    "rarity": "PE+",
                    "member_attributes": None,
                    "live_attributes": None,
                    "raw_effect_text": None,
                    "image_url": "https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP01/PL!SP-bp1-032-PE2.png",
                    "source_url": "https://llofficial-cardgame.com/cardlist/searchresults/?title=BP01&card_kind=E&cardno=PL%21SP-bp1-032-PE%EF%BC%8B",
                    "fetched_at": "2026-06-14T03:40:12+00:00",
                    "parser_version": "cardlist_spike_v0.3",
                    "parse_notes": {"import_source": "official_full_import"},
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = import_normalized_cards(database_path, input_path, NORMALIZATION_PATH)

    assert summary.status == "completed"
    with closing(sqlite3.connect(database_path)) as connection:
        rows = connection.execute(
            """
            SELECT card_code
            FROM gameplay_cards
            ORDER BY card_code
            """
        ).fetchall()
        assert [row[0] for row in rows] == [
            "PL!SP-bp1-032-PE",
            "PL!SP-bp1-032-PE＋",
        ]
        assert connection.execute("SELECT COUNT(*) FROM card_printings").fetchone()[0] == 2


def test_unofficial_source_url_is_rejected_and_audited(tmp_path):
    database_path = tmp_path / "catalog.sqlite3"
    records = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    records[0]["source_url"] = "https://unofficial.example/card/1"
    input_path = tmp_path / "unofficial.json"
    input_path.write_text(
        json.dumps(records, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(CardImportValidationError):
        import_normalized_cards(
            database_path,
            input_path,
            NORMALIZATION_PATH,
        )

    with closing(sqlite3.connect(database_path)) as connection:
        latest = connection.execute(
            """
            SELECT status, records_imported, error_message
            FROM import_batches
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    assert latest[0] == "failed"
    assert latest[1] == 0
    assert "not an official HTTPS" in latest[2]


def test_only_one_current_text_revision_is_allowed(tmp_path):
    database_path = tmp_path / "catalog.sqlite3"
    import_normalized_cards(database_path, SAMPLE_PATH, NORMALIZATION_PATH)

    with closing(sqlite3.connect(database_path)) as connection:
        revision = connection.execute(
            """
            SELECT gameplay_card_id, created_from_observation_id, first_observed_at
            FROM card_text_revisions
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()
        connection.execute(
            """
            UPDATE card_text_revisions
            SET revision_status = 'current'
            WHERE gameplay_card_id = ?
            """,
            (revision[0],),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO card_text_revisions (
                    gameplay_card_id,
                    revision_number,
                    raw_effect_text_ja,
                    raw_text_hash,
                    revision_status,
                    created_from_observation_id,
                    first_observed_at,
                    last_observed_at
                )
                VALUES (?, 99, '別のテキスト', 'different-hash', 'current', ?, ?, ?)
                """,
                (revision[0], revision[1], revision[2], revision[2]),
            )


def _table_counts(
    database_path: Path,
    expected: dict[str, int],
) -> dict[str, int]:
    with closing(sqlite3.connect(database_path)) as connection:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in expected
        }
