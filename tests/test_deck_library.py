from __future__ import annotations

import json
from pathlib import Path

from loveca.decks.library import (
    delete_saved_deck,
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
