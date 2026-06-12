from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from loveca.cards.importer import import_normalized_cards
from loveca.decks.analyzer import load_deck
from loveca.simulation.effects import (
    EffectRegistry,
    validate_registry_for_cards,
)
from loveca.simulation.engine import apply_action
from loveca.simulation.models import ActionRequest
from loveca.simulation.service import MatchService


PROJECT_ROOT = Path(__file__).parents[1]
SAMPLE_CARDS = (
    PROJECT_ROOT / "data_samples" / "normalized" / "cards-cross-product-sample.json"
)
NORMALIZATION = PROJECT_ROOT / "data_sources" / "card-entity-normalization.json"
SAMPLE_DECK = PROJECT_ROOT / "examples" / "decks" / "sample-deck.json"
REGISTRY = PROJECT_ROOT / "data_sources" / "effect-registry.v0.json"


def test_registry_rejects_duplicate_effect_ids():
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    payload["effects"].append(payload["effects"][0])

    with pytest.raises(ValidationError, match="duplicate effect_id"):
        EffectRegistry.model_validate(payload)


def test_registry_rejects_unknown_operations():
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    payload["effects"][0]["actions"][0]["action_type"] = "invented_operation"

    with pytest.raises(ValidationError, match="unsupported effect operations"):
        EffectRegistry.model_validate(payload)


def test_registry_hash_mismatch_is_explicit(tmp_path):
    service, _ = _create_match(tmp_path)
    registry = EffectRegistry.model_validate_json(REGISTRY.read_text(encoding="utf-8"))
    broken = registry.model_copy(deep=True)
    broken.effects[0].raw_text_hash = "0" * 64

    from loveca.db.bootstrap import connect_database

    connection = connect_database(service.card_database_path)
    try:
        valid, errors = validate_registry_for_cards(
            connection, broken, {"LL-bp1-001"}
        )
    finally:
        connection.close()

    assert "LL-bp1-001:1" not in valid
    assert errors["LL-bp1-001"] == [
        "LL-bp1-001:1: raw effect text hash mismatch"
    ]


def test_on_play_returns_selected_member_from_waiting_room(tmp_path):
    service, match_id = _create_match(tmp_path, seed=31)
    state = _reach_first_main(service, match_id)
    source = _instance(state, "player_1", "LL-bp1-001", zone="main_deck")
    target = _instance(state, "player_1", "PL!-bp3-002", zone="main_deck")
    state = _manual_move(service, match_id, state, source, "hand")
    state = _manual_move(service, match_id, state, target, "waiting_room")
    state.cards[source].card.cost = 0

    state = _apply_direct(
        state,
        "play_member",
        player_id="player_1",
        payload={
            "card_instance_id": source,
            "slot": "center",
            "energy_instance_ids": [],
            "use_baton_touch": False,
        },
    )

    assert state.pending_effects[0].effect_id == "LL-bp1-001:1"
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": [target],
        },
    )
    assert target in state.players["player_1"].hand
    assert target not in state.players["player_1"].waiting_room


def test_activated_draw_discard_is_once_per_turn(tmp_path):
    service, match_id = _create_match(tmp_path, seed=44)
    state = _reach_first_main(service, match_id)
    source = _instance(state, "player_1", "PL!-bp3-001", zone="main_deck")
    state = _manual_move(service, match_id, state, source, "member_center")
    initial_hand = len(state.players["player_1"].hand)

    state = _apply(
        service,
        match_id,
        state,
        "activate_effect",
        player_id="player_1",
        payload={
            "effect_id": "PL!-bp3-001:1",
            "source_card_instance_id": source,
        },
    )
    assert state.cards[source].orientation == "wait"
    assert len(state.players["player_1"].hand) == initial_hand + 1
    discard = state.players["player_1"].hand[0]
    state = _apply(
        service,
        match_id,
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": [discard],
        },
    )
    assert discard in state.players["player_1"].waiting_room
    legal = service.repository.get_state(match_id)
    from loveca.simulation.engine import generate_legal_actions

    assert not any(
        action.action_type == "activate_effect"
        for action in generate_legal_actions(legal)
    )


def test_live_start_optional_blade_pays_energy_and_expires(tmp_path):
    service, match_id = _create_match(tmp_path, seed=51)
    state = _reach_first_main(service, match_id)
    source = _instance(state, "player_1", "PL!N-bp1-001", zone="main_deck")
    live = next(
        instance_id
        for instance_id in state.players["player_1"].main_deck
        if state.cards[instance_id].card.card_type == "live"
    )
    state = _manual_move(service, match_id, state, source, "member_center")
    state = _manual_move(service, match_id, state, live, "hand")
    state = _advance_to_live_start(service, match_id, state, live)

    invocation = next(
        item for item in state.pending_effects if item.effect_id == "PL!N-bp1-001:1"
    )
    energy = next(
        item
        for item in state.players["player_1"].energy_area
        if state.cards[item].orientation == "active"
    )
    state = _apply(
        service,
        match_id,
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": invocation.invocation_id,
            "accepted": True,
            "energy_instance_ids": [energy],
        },
    )
    assert state.cards[energy].orientation == "wait"
    assert any(
        modifier.modifier_type == "blade" and modifier.duration == "live"
        for modifier in state.players["player_1"].manual_modifiers
    )


def test_baton_touch_auto_readies_two_energy(tmp_path):
    service, match_id = _create_match(tmp_path, seed=67)
    state = _reach_first_main(service, match_id)
    old = _instance(state, "player_1", "PL!HS-sd1-001", zone="main_deck")
    new = _instance(state, "player_1", "PL!HS-sd1-002", zone="main_deck")
    state = _manual_move(service, match_id, state, old, "member_center")
    state = _manual_move(service, match_id, state, new, "hand")
    state.players["player_1"].member_areas_entered_this_turn.clear()
    old_cost = state.cards[old].card.cost or 0
    new_cost = state.cards[new].card.cost or 0
    payment = max(0, new_cost - old_cost)
    active_energy = [
        item
        for item in state.players["player_1"].energy_area
        if state.cards[item].orientation == "active"
    ][:payment]
    state = _apply_direct(
        state,
        "play_member",
        player_id="player_1",
        payload={
            "card_instance_id": new,
            "slot": "center",
            "energy_instance_ids": active_energy,
            "use_baton_touch": True,
        },
    )
    assert sum(
        state.cards[item].orientation == "active"
        for item in state.players["player_1"].energy_area
    ) >= 2
    assert not state.pending_effects


def test_replay_uses_match_effect_snapshot_after_registry_changes(tmp_path):
    registry_copy = tmp_path / "effect-registry.json"
    registry_copy.write_text(REGISTRY.read_text(encoding="utf-8"), encoding="utf-8")
    card_database = tmp_path / "cards.sqlite3"
    import_normalized_cards(card_database, SAMPLE_CARDS, NORMALIZATION)
    service = MatchService(
        card_database,
        tmp_path / "matches.sqlite3",
        registry_copy,
    )
    created = service.create_match(
        first_name="A",
        first_deck=load_deck(SAMPLE_DECK),
        second_name="B",
        second_deck=load_deck(SAMPLE_DECK),
        seed=99,
    )
    match_id = created.state.match_id
    state = _apply(
        service,
        match_id,
        created.state,
        "choose_first_player",
        payload={"first_player_id": "player_1"},
    )
    registry_copy.write_text("{not valid json", encoding="utf-8")

    replay = service.repository.replay(match_id)

    assert replay["final_state"]["revision"] == state.revision
    assert replay["final_state"]["effect_registry_version"] == "effect-registry.v0"
    assert "PL!-bp3-001:1" in replay["final_state"]["effect_definitions"]


def test_manual_top_deck_inspection_selects_revealed_card_and_discards_rest(
    tmp_path,
):
    service, match_id = _create_match(tmp_path, seed=123)
    state = _reach_first_main(service, match_id)
    expected = state.players["player_1"].main_deck[:3]

    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "manual search effect",
            "requires_confirmation": True,
            "confirmed_by": "tester",
            "adjustments": [
                {
                    "adjustment_type": "inspect_top_cards",
                    "target_player_id": "player_1",
                    "amount": 3,
                    "minimum": 0,
                    "maximum": 1,
                    "reveal_selected_to_opponent": True,
                }
            ],
        },
    )

    assert state.pending_choice is not None
    assert state.pending_choice.choice_type == "manual_card_selection"
    assert state.pending_choice.options["inspected_card_instance_ids"] == expected
    assert all(item in state.players["player_1"].resolution_area for item in expected)

    selected = expected[0]
    state = _apply(
        service,
        match_id,
        state,
        "resolve_manual_inspection",
        player_id="player_1",
        payload={"selected_card_instance_ids": [selected]},
    )

    assert state.pending_choice is None
    assert selected in state.players["player_1"].hand
    assert all(
        item in state.players["player_1"].waiting_room for item in expected[1:]
    )
    replay = service.repository.replay(match_id)
    event = next(
        item
        for item in replay["events"]
        if item["event_type"] == "manual_card_inspection_resolved"
    )
    assert event["data"]["reveal_selected_to_opponent"] is True
    assert event["data"]["selected_card_instance_ids"] == [selected]


def _create_match(tmp_path: Path, seed: int = 7):
    card_database = tmp_path / "cards.sqlite3"
    import_normalized_cards(card_database, SAMPLE_CARDS, NORMALIZATION)
    service = MatchService(card_database, tmp_path / "matches.sqlite3", REGISTRY)
    result = service.create_match(
        first_name="A",
        first_deck=load_deck(SAMPLE_DECK),
        second_name="B",
        second_deck=load_deck(SAMPLE_DECK),
        seed=seed,
    )
    return service, result.state.match_id


def _apply(
    service: MatchService,
    match_id: str,
    state,
    action_type: str,
    *,
    player_id: str | None = None,
    payload: dict | None = None,
):
    return service.apply(
        match_id,
        ActionRequest(
            action_type=action_type,
            expected_revision=state.revision,
            player_id=player_id,
            payload=payload or {},
        ),
    ).state


def _apply_direct(
    state,
    action_type: str,
    *,
    player_id: str | None = None,
    payload: dict | None = None,
):
    return apply_action(
        state,
        ActionRequest(
            action_type=action_type,
            expected_revision=state.revision,
            player_id=player_id,
            payload=payload or {},
        ),
    ).state


def _reach_first_main(service: MatchService, match_id: str):
    state = service.repository.get_state(match_id)
    state = _apply(
        service,
        match_id,
        state,
        "choose_first_player",
        payload={"first_player_id": "player_1"},
    )
    state = _apply(
        service, match_id, state, "submit_mulligan", player_id="player_1",
        payload={"card_instance_ids": []},
    )
    state = _apply(
        service, match_id, state, "submit_mulligan", player_id="player_2",
        payload={"card_instance_ids": []},
    )
    for _ in range(3):
        state = _apply(
            service, match_id, state, "advance_phase", player_id="player_1"
        )
    return state


def _advance_to_live_start(
    service: MatchService,
    match_id: str,
    state,
    live_instance_id: str,
):
    state = _apply(
        service, match_id, state, "end_main_phase", player_id="player_1"
    )
    for _ in range(3):
        state = _apply(
            service, match_id, state, "advance_phase", player_id="player_2"
        )
    state = _apply(
        service, match_id, state, "end_main_phase", player_id="player_2"
    )
    state = _apply(
        service, match_id, state, "set_live_cards", player_id="player_1",
        payload={"card_instance_ids": [live_instance_id]},
    )
    state = _apply(
        service, match_id, state, "set_live_cards", player_id="player_2",
        payload={"card_instance_ids": []},
    )
    return _apply(
        service, match_id, state, "advance_phase", player_id="player_1"
    )


def _instance(state, player_id: str, card_code: str, *, zone: str) -> str:
    player = state.players[player_id]
    ids = getattr(player, zone)
    return next(
        instance_id
        for instance_id in ids
        if state.cards[instance_id].card.card_code == card_code
    )


def _manual_move(
    service: MatchService,
    match_id: str,
    state,
    instance_id: str,
    zone: str,
):
    return _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "effect test setup",
            "requires_confirmation": True,
            "confirmed_by": "test",
            "adjustments": [
                {
                    "adjustment_type": "move_card",
                    "target_player_id": "player_1",
                    "target_card_instance_id": instance_id,
                    "to_zone": zone,
                }
            ],
        },
    )
