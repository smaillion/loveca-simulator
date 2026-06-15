from __future__ import annotations

import json
from pathlib import Path

from loveca.decks.library import (
    delete_saved_deck,
    import_deck_directory,
    list_saved_decks,
    load_saved_deck,
    rename_saved_deck,
    save_deck_file,
)

PROJECT_ROOT = Path(__file__).parents[1]
SAMPLE_DECK = PROJECT_ROOT / "tests" / "fixtures" / "legal-deck.json"


def test_deck_library_crud_round_trip(tmp_path: Path):
    library_root = tmp_path / "decks"

    saved = save_deck_file(SAMPLE_DECK, library_root)
    assert saved.exists()

    decks = list_saved_decks(library_root)
    assert len(decks) == 1
    assert decks[0].name == "Legal Test Deck"
    assert decks[0].main_card_count == 60
    assert decks[0].energy_card_count == 12

    loaded = load_saved_deck(library_root, saved.stem)
    assert loaded.name == "Legal Test Deck"
    assert loaded.version == "decklist.v0"

    renamed = rename_saved_deck(library_root, saved.stem, "Renamed Deck")
    assert renamed.exists()
    renamed_payload = json.loads(renamed.read_text(encoding="utf-8"))
    assert renamed_payload["name"] == "Renamed Deck"
    assert not saved.exists()

    delete_saved_deck(library_root, renamed.stem)
    assert list_saved_decks(library_root) == []


def test_import_deck_directory_promotes_sandbox_artifacts(tmp_path: Path):
    source_root = tmp_path / "sandbox-decks"
    library_root = tmp_path / "library"
    source_root.mkdir()
    payload = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))
    for index in range(2):
        copied = dict(payload)
        copied["name"] = f"Sandbox Deck {index + 1:02d}"
        (source_root / f"Sandbox Deck {index + 1:02d}.json").write_text(
            json.dumps(copied, ensure_ascii=False),
            encoding="utf-8",
        )

    imported = import_deck_directory(
        source_root,
        library_root,
        name_prefix="Imported",
    )

    assert [item.name for item in imported] == [
        "Imported Sandbox Deck 01",
        "Imported Sandbox Deck 02",
    ]
    saved = list_saved_decks(library_root)
    assert [deck.name for deck in saved] == [
        "Imported Sandbox Deck 01",
        "Imported Sandbox Deck 02",
    ]
    assert all(deck.main_card_count == 60 for deck in saved)
    assert all(deck.energy_card_count == 12 for deck in saved)


def test_import_deck_directory_does_not_duplicate_existing_prefix(tmp_path: Path):
    source_root = tmp_path / "sandbox-decks"
    library_root = tmp_path / "library"
    source_root.mkdir()
    payload = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))
    payload["name"] = "Sandbox Deck 01"
    (source_root / "Sandbox Deck 01.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    imported = import_deck_directory(
        source_root,
        library_root,
        name_prefix="Sandbox",
    )

    assert imported[0].name == "Sandbox Deck 01"
    assert imported[0].destination.name == "sandbox-deck-01.json"
