from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from loveca.cards.importer import import_normalized_cards
from loveca.decks.analyzer import (
    DeckFileError,
    analyze_deck_file,
    load_deck,
    parse_deck,
    render_analysis_json,
    render_analysis_text,
)

PROJECT_ROOT = Path(__file__).parents[1]
SAMPLE_CARDS_PATH = (
    PROJECT_ROOT
    / "data_samples"
    / "normalized"
    / "cards-cross-product-sample.json"
)
NORMALIZATION_PATH = PROJECT_ROOT / "data_sources" / "card-entity-normalization.json"
SAMPLE_DECK_PATH = PROJECT_ROOT / "tests" / "fixtures" / "legal-deck.json"


def test_sample_deck_is_legal_and_reports_core_statistics(tmp_path):
    database_path = _import_sample_database(tmp_path)

    analysis = analyze_deck_file(database_path, SAMPLE_DECK_PATH)

    assert analysis.is_legal is True
    assert analysis.issues == ()
    assert analysis.card_type_counts["main_deck"]["member"] == 48
    assert analysis.card_type_counts["main_deck"]["live"] == 12
    assert analysis.card_type_counts["energy_deck"]["energy"] == 12
    assert analysis.member_blade_summary["counted_cards"] == 44
    assert analysis.member_blade_summary["missing_cards"] == 4
    assert analysis.member_basic_heart_distribution
    assert analysis.live_required_heart_distribution
    assert analysis.special_blade_heart_summary["ALL1"] == 9
    assert analysis.special_blade_heart_summary["スコア1"] == 2


def test_renderers_produce_text_and_stable_json(tmp_path):
    database_path = _import_sample_database(tmp_path)
    analysis = analyze_deck_file(database_path, SAMPLE_DECK_PATH)

    text = render_analysis_text(analysis)
    payload = json.loads(render_analysis_json(analysis))

    assert "Status: legal" in text
    assert "Card Type Counts" in text
    assert payload["is_legal"] is True
    assert payload["card_type_counts"]["total"]["energy"] == 12


def test_unknown_card_and_copy_limit_are_reported(tmp_path):
    database_path = _import_sample_database(tmp_path)
    deck = _sample_deck_payload()
    deck["main_deck"][0]["quantity"] = 5
    deck["main_deck"].append({"card_code": "UNKNOWN-CARD", "quantity": 1})
    deck_path = _write_deck(tmp_path, deck)

    analysis = analyze_deck_file(database_path, deck_path)
    issue_codes = {issue.code for issue in analysis.issues}

    assert analysis.is_legal is False
    assert "unknown_card" in issue_codes
    assert "copy_limit_exceeded" in issue_codes
    assert "deck_count_mismatch" in issue_codes


def test_energy_cards_are_not_limited_to_four_copies(tmp_path):
    database_path = _import_sample_database(tmp_path)
    deck = _sample_deck_payload()
    deck["energy_deck"] = [
        {
            "card_code": deck["energy_deck"][0]["card_code"],
            "quantity": 12,
        }
    ]
    deck_path = _write_deck(tmp_path, deck)

    analysis = analyze_deck_file(database_path, deck_path)

    assert analysis.is_legal is True
    assert all(issue.code != "copy_limit_exceeded" for issue in analysis.issues)


def test_wrong_deck_section_is_reported(tmp_path):
    database_path = _import_sample_database(tmp_path)
    deck = _sample_deck_payload()
    deck["energy_deck"][0] = {"card_code": "LL-bp1-001", "quantity": 2}
    deck_path = _write_deck(tmp_path, deck)

    analysis = analyze_deck_file(database_path, deck_path)

    assert analysis.is_legal is False
    assert any(issue.code == "wrong_deck_section" for issue in analysis.issues)


def test_preferred_printing_must_match_card_code(tmp_path):
    database_path = _import_sample_database(tmp_path)
    deck = _sample_deck_payload()
    deck["main_deck"][0]["preferred_printing_id"] = "PL!N-bp1-001-R"
    deck_path = _write_deck(tmp_path, deck)

    analysis = analyze_deck_file(database_path, deck_path)

    assert analysis.is_legal is False
    assert any(
        issue.code == "preferred_printing_mismatch" for issue in analysis.issues
    )


def test_plus_card_identifiers_are_normalized_to_ascii():
    deck = _sample_deck_payload()
    deck["main_deck"][0]["card_code"] = "PL!SP-bp1-003-P＋"
    deck["main_deck"][0]["preferred_printing_id"] = "PL!SP-bp1-003-P＋"

    parsed = parse_deck(deck)

    assert parsed.main_deck[0].card_code == "PL!SP-bp1-003-P+"
    assert parsed.main_deck[0].preferred_printing_id == "PL!SP-bp1-003-P+"


def test_deck_file_contract_is_validated(tmp_path):
    deck_path = tmp_path / "bad-deck.json"
    deck_path.write_text(
        json.dumps(
            {
                "version": "decklist.v1",
                "main_deck": [],
                "energy_deck": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DeckFileError):
        load_deck(deck_path)


def _import_sample_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "catalog.sqlite3"
    import_normalized_cards(database_path, SAMPLE_CARDS_PATH, NORMALIZATION_PATH)
    return database_path


def _sample_deck_payload() -> dict:
    return copy.deepcopy(json.loads(SAMPLE_DECK_PATH.read_text(encoding="utf-8")))


def _write_deck(tmp_path: Path, payload: dict) -> Path:
    deck_path = tmp_path / "deck.json"
    deck_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return deck_path
