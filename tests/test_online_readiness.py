from __future__ import annotations

import json
from pathlib import Path

from loveca.cards.importer import import_normalized_cards
from loveca.decks.analyzer import load_deck
from loveca.simulation.models import ActionRequest
from loveca.simulation.online import (
    ActionEnvelope,
    build_compatibility_fingerprint,
    compatibility_report,
    decklist_hash,
    effect_registry_hash,
    match_state_hash,
)
from loveca.simulation.service import MatchService

PROJECT_ROOT = Path(__file__).parents[1]
SAMPLE_CARDS = (
    PROJECT_ROOT / "data_samples" / "normalized" / "cards-cross-product-sample.json"
)
NORMALIZATION = PROJECT_ROOT / "data_sources" / "card-entity-normalization.json"
SAMPLE_DECK = PROJECT_ROOT / "tests" / "fixtures" / "legal-deck.json"
REGISTRY = PROJECT_ROOT / "data_sources" / "effect-registry.v0.json"


def test_match_state_hash_is_deterministic(tmp_path):
    service, match_id = _create_match(tmp_path)
    state = service.repository.get_state(match_id)

    assert match_state_hash(state) == match_state_hash(state.model_copy(deep=True))

    result = service.apply(
        match_id,
        ActionRequest(
            action_type="submit_mulligan",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"card_instance_ids": []},
        ),
    )

    assert match_state_hash(result.state) != match_state_hash(state)


def test_deck_and_registry_hashes_are_content_based():
    deck = load_deck(SAMPLE_DECK)

    assert decklist_hash(deck) == decklist_hash(load_deck(SAMPLE_DECK))
    assert effect_registry_hash(REGISTRY) == effect_registry_hash(REGISTRY)


def test_action_envelope_round_trip(tmp_path):
    service, match_id = _create_match(tmp_path)
    state = service.repository.get_state(match_id)
    action = ActionRequest(
        action_type="choose_first_player",
        expected_revision=state.revision,
        payload={"first_player_id": "player_1"},
    )
    envelope = ActionEnvelope(
        message_id="msg-1",
        match_id=match_id,
        sender_player_id="player_1",
        expected_revision=state.revision,
        base_state_hash=match_state_hash(state),
        action=action,
    )

    restored = ActionEnvelope.model_validate_json(envelope.model_dump_json())

    assert restored == envelope
    assert json.loads(restored.model_dump_json())["action"]["action_type"] == (
        "choose_first_player"
    )


def test_compatibility_fingerprint_and_replay_metadata(tmp_path):
    service, match_id = _create_match(tmp_path)
    deck = load_deck(SAMPLE_DECK)
    fingerprint = build_compatibility_fingerprint(
        card_database_path=service.card_database_path,
        effect_registry_path=REGISTRY,
        decks={"player_1": deck, "player_2": deck},
    )

    assert fingerprint.card_database_fingerprint
    assert fingerprint.effect_registry_hash
    assert set(fingerprint.decklist_hashes) == {"player_1", "player_2"}
    assert compatibility_report(fingerprint, fingerprint)["is_compatible"]

    replay = service.repository.replay(match_id)
    assert replay["metadata"]["protocol_version"] == "loveca-online.v0"
    assert replay["metadata"]["card_database_fingerprint"]
    assert replay["metadata"]["final_state_hash"] == match_state_hash(
        service.repository.get_state(match_id)
    )
    assert (
        replay["metadata"]["initial_state_hash"]
        != replay["metadata"]["final_state_hash"]
    )


def _create_match(tmp_path):
    card_database = tmp_path / "cards.sqlite3"
    import_normalized_cards(card_database, SAMPLE_CARDS, NORMALIZATION)
    service = MatchService(card_database, tmp_path / "matches.sqlite3", REGISTRY)
    created = service.create_match(
        first_name="A",
        first_deck=load_deck(SAMPLE_DECK),
        second_name="B",
        second_deck=load_deck(SAMPLE_DECK),
        seed=42,
        first_player_id="player_1",
    )
    return service, created.state.match_id
