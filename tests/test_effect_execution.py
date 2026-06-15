from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from loveca.cards.importer import import_normalized_cards
from loveca.decks.analyzer import load_deck
from loveca.simulation.effects import (
    EffectDefinition,
    EffectRegistry,
    validate_registry_for_cards,
)
from loveca.simulation.engine import apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest
from loveca.simulation.service import MatchService

PROJECT_ROOT = Path(__file__).parents[1]
SAMPLE_CARDS = (
    PROJECT_ROOT / "data_samples" / "normalized" / "cards-cross-product-sample.json"
)
NORMALIZATION = PROJECT_ROOT / "data_sources" / "card-entity-normalization.json"
SAMPLE_DECK = PROJECT_ROOT / "tests" / "fixtures" / "legal-deck.json"
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


def test_registry_contains_all_matching_wait_energy_effects():
    registry = EffectRegistry.model_validate_json(REGISTRY.read_text(encoding="utf-8"))
    expected = {
        "PL!SP-PR-004": 764,
        "PL!SP-PR-006": 765,
        "PL!SP-PR-013": 771,
        "PL!SP-bp1-021": 652,
        "PL!SP-sd1-014": 705,
        "PL!SP-sd1-016": 706,
    }
    matching = {
        effect.card_code: effect
        for effect in registry.effects
        if any(
            operation.action_type == "place_energy_from_deck"
            for operation in effect.actions
        )
    }

    assert set(matching) == set(expected)
    for card_code, revision_id in expected.items():
        effect = matching[card_code]
        assert effect.text_revision_id == revision_id
        assert effect.raw_text_hash == (
            "e265aa3650daa72a3459f55faf73e40226d3132d5a51e6efa97e0b63d13adb69"
        )
        assert effect.condition == {"minimum_energy_deck_cards": 1}
        assert effect.choice is not None
        assert effect.choice.zone == "hand"
        assert effect.choice.minimum == effect.choice.maximum == 1
        assert effect.actions[0].orientation == "wait"


def test_place_energy_from_deck_requires_orientation():
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    effect = next(
        item
        for item in payload["effects"]
        if item["card_code"] == "PL!SP-bp1-021"
    )
    del effect["actions"][0]["orientation"]

    with pytest.raises(ValidationError, match="requires an orientation"):
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


def test_on_play_discard_adds_top_energy_in_wait_state(tmp_path):
    state, source = _state_with_wait_energy_effect(tmp_path)
    discard = next(
        item for item in state.players["player_1"].hand if item != source
    )
    top_energy = state.players["player_1"].energy_deck[0]

    play_result = apply_action(
        state,
        ActionRequest(
            action_type="play_member",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "card_instance_id": source,
                "slot": "center",
                "energy_instance_ids": [],
                "use_baton_touch": False,
            },
        ),
    )
    state = play_result.state
    assert state.pending_effects[0].effect_id == "test-wait-energy:1"
    legal = generate_legal_actions(state)
    invocation = legal[0].options["invocations"][0]
    assert invocation["candidate_card_instance_ids"] == state.players["player_1"].hand
    assert invocation["card_selection_minimum"] == 1
    assert invocation["card_selection_maximum"] == 1

    before_resolution = state.model_copy(deep=True)
    action = ActionRequest(
        action_type="resolve_effect",
        expected_revision=state.revision,
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "accepted": True,
            "selected_card_instance_ids": [discard],
        },
    )
    result = apply_action(state, action)
    replay_result = apply_action(before_resolution, action)
    state = result.state

    assert discard in state.players["player_1"].waiting_room
    assert top_energy not in state.players["player_1"].energy_deck
    assert top_energy in state.players["player_1"].energy_area
    assert state.cards[top_energy].orientation == "wait"
    assert state.cards[top_energy].face_up is True
    assert state.model_dump(mode="json") == replay_result.state.model_dump(mode="json")
    assert [event.event_type for event in result.events] == [
        "effect_cost_paid",
        "energy_added",
        "effect_resolved",
    ]
    assert result.events[0].data["selected_card_instance_ids"] == [discard]
    assert result.events[1].data["instance_ids"] == [top_energy]
    assert result.events[1].data["orientation"] == "wait"
    assert result.events[1].data["reason"] == "effect:test-wait-energy:1"


def test_optional_wait_energy_effect_may_be_declined(tmp_path):
    state, source = _state_with_wait_energy_effect(tmp_path)
    state = _play_wait_energy_source(state, source)
    before = state.model_copy(deep=True)

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "invocation_id": state.pending_effects[0].invocation_id,
                "accepted": False,
            },
        ),
    )

    player = result.state.players["player_1"]
    assert player.hand == before.players["player_1"].hand
    assert player.waiting_room == before.players["player_1"].waiting_room
    assert player.energy_deck == before.players["player_1"].energy_deck
    assert player.energy_area == before.players["player_1"].energy_area
    assert not result.state.pending_effects
    assert result.events[0].event_type == "effect_declined"


@pytest.mark.parametrize("missing_zone", ["hand", "energy_deck"])
def test_wait_energy_effect_is_not_offered_without_required_resources(
    tmp_path, missing_zone
):
    state, source = _state_with_wait_energy_effect(tmp_path)
    if missing_zone == "hand":
        state.players["player_1"].hand = [source]
    else:
        state.players["player_1"].energy_deck = []

    result = apply_action(
        state,
        ActionRequest(
            action_type="play_member",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "card_instance_id": source,
                "slot": "center",
                "energy_instance_ids": [],
                "use_baton_touch": False,
            },
        ),
    )

    assert not result.state.pending_effects
    unavailable = next(
        event for event in result.events if event.event_type == "effect_not_activatable"
    )
    expected_reason = (
        "choice_candidates_unavailable"
        if missing_zone == "hand"
        else "energy_deck_empty"
    )
    assert unavailable.data["reason"] == expected_reason


def test_wait_energy_effect_resolution_is_atomic_if_energy_deck_changes(tmp_path):
    state, source = _state_with_wait_energy_effect(tmp_path)
    state = _play_wait_energy_source(state, source)
    discard = state.players["player_1"].hand[0]
    state.players["player_1"].energy_deck = []
    before = state.model_dump(mode="json")

    with pytest.raises(Exception, match="energy_deck_empty"):
        apply_action(
            state,
            ActionRequest(
                action_type="resolve_effect",
                expected_revision=state.revision,
                player_id="player_1",
                payload={
                    "invocation_id": state.pending_effects[0].invocation_id,
                    "accepted": True,
                    "selected_card_instance_ids": [discard],
                },
            ),
        )

    assert state.model_dump(mode="json") == before


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


def test_same_player_may_choose_pending_effect_resolution_order(tmp_path):
    service, match_id = _create_match(tmp_path, seed=58)
    state = _reach_first_main(service, match_id)
    readied = _instance(state, "player_1", "PL!-bp3-001", zone="main_deck")
    blade = _instance(state, "player_1", "PL!N-bp1-001", zone="main_deck")
    live = next(
        instance_id
        for instance_id in state.players["player_1"].main_deck
        if state.cards[instance_id].card.card_type == "live"
    )
    state = _manual_move(service, match_id, state, readied, "member_left")
    state = _manual_move(service, match_id, state, blade, "member_center")
    discard = state.players["player_1"].hand[0]
    state = _apply(
        service,
        match_id,
        state,
        "activate_effect",
        player_id="player_1",
        payload={
            "effect_id": "PL!-bp3-001:1",
            "source_card_instance_id": readied,
        },
    )
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
    state = _manual_move(service, match_id, state, live, "hand")
    state = _advance_to_live_start(service, match_id, state, live)

    invocation_ids = [item.effect_id for item in state.pending_effects]
    assert "PL!-bp3-001:2" in invocation_ids
    assert "PL!N-bp1-001:1" in invocation_ids

    optional_invocation = next(
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
            "invocation_id": optional_invocation.invocation_id,
            "accepted": True,
            "energy_instance_ids": [energy],
        },
    )
    assert any(
        modifier.modifier_type == "blade"
        for modifier in state.players["player_1"].manual_modifiers
    )
    assert any(item.effect_id == "PL!-bp3-001:2" for item in state.pending_effects)


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


def test_manual_resolution_requires_pending_invocation_binding(tmp_path):
    service, match_id = _create_match(tmp_path, seed=71)
    state = _reach_first_main(service, match_id)
    source = _instance(state, "player_1", "LL-bp1-001", zone="main_deck")
    live = next(
        instance_id
        for instance_id in state.players["player_1"].main_deck
        if state.cards[instance_id].card.card_type == "live"
    )
    state = _manual_move(service, match_id, state, source, "member_center")
    state = _manual_move(service, match_id, state, live, "hand")
    state = _advance_to_live_start(service, match_id, state, live)
    manual_invocation = next(
        item for item in state.pending_effects if item.effect_id == "LL-bp1-001:2"
    )

    with pytest.raises(Exception, match="source_invocation_id"):
        _apply(
            service,
            match_id,
            state,
            "manual_adjustment",
            player_id="player_1",
            payload={
                "reason": "manual live-start effect",
                "requires_confirmation": True,
                "confirmed_by": "tester",
                "adjustments": [
                    {
                        "adjustment_type": "modify_score",
                        "target_player_id": "player_1",
                        "amount": 3,
                        "duration": "live",
                    }
                ],
            },
        )

    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "manual live-start effect",
            "requires_confirmation": True,
            "confirmed_by": "tester",
            "source_invocation_id": manual_invocation.invocation_id,
            "source_effect_id": manual_invocation.effect_id,
            "source_card_instance_id": manual_invocation.source_card_instance_id,
            "adjustments": [
                {
                    "adjustment_type": "modify_score",
                    "target_player_id": "player_1",
                    "amount": 3,
                    "duration": "live",
                }
            ],
        },
    )
    assert not any(item.effect_id == "LL-bp1-001:2" for item in state.pending_effects)


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


def test_on_play_inspection_reorders_kept_cards_and_records_replay(tmp_path):
    service, match_id = _create_match(tmp_path, seed=141)
    state = _reach_first_main(service, match_id)
    source = _instance(state, "player_1", "PL!-bp3-014", zone="main_deck")
    state = _manual_move(service, match_id, state, source, "hand")
    extra_energy = state.players["player_1"].energy_deck[0]
    state = _manual_move(service, match_id, state, extra_energy, "energy_area")
    expected = state.players["player_1"].main_deck[:2]

    state = _apply(
        service,
        match_id,
        state,
        "play_member",
        player_id="player_1",
        payload={
            "card_instance_id": source,
            "slot": "center",
            "energy_instance_ids": state.players["player_1"].energy_area[:4],
            "use_baton_touch": False,
        },
    )

    assert state.pending_effects[0].effect_id == "PL!-bp3-014:1"
    state = _apply(
        service,
        match_id,
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "accepted": True,
        },
    )

    assert state.pending_choice is not None
    assert state.pending_choice.choice_type == "effect_inspection_selection"
    assert state.cards[source].orientation == "wait"
    state = _apply(
        service,
        match_id,
        state,
        "resolve_effect_choice",
        player_id="player_1",
        payload={
            "selected_card_instance_ids": [expected[1], expected[0]],
            "ordered_card_instance_ids": [expected[1], expected[0]],
        },
    )

    assert state.players["player_1"].main_deck[:2] == [expected[1], expected[0]]
    assert not state.players["player_1"].resolution_area
    replay = service.repository.replay(match_id)
    event = next(
        item
        for item in replay["events"]
        if item["event_type"] == "effect_resolved"
        and item["data"]["effect_id"] == "PL!-bp3-014:1"
    )
    assert event["data"]["ordered_card_instance_ids"] == [expected[1], expected[0]]


def test_on_play_inspection_filter_only_accepts_matching_candidate(tmp_path):
    service, match_id = _create_match(tmp_path, seed=177)
    state = _reach_first_main(service, match_id)
    source = _instance(state, "player_1", "PL!-bp6-002", zone="main_deck")
    state.players["player_1"].main_deck.remove(source)
    state.players["player_1"].hand.append(source)
    state.cards[source].face_up = True
    state.cards[source].card.cost = 0
    valid = state.players["player_1"].main_deck[0]
    invalid = state.players["player_1"].main_deck[1]
    state.cards[valid].card.work_keys = ["muse"]
    state.cards[valid].card.ability_bucket = "static_only"
    state.cards[invalid].card.work_keys = ["hasunosora"]
    state.cards[invalid].card.ability_bucket = "other"
    _stack_main_deck_top(state, "player_1", [valid, invalid])

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
    invocation = state.pending_effects[0]
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": invocation.invocation_id},
    )

    assert state.pending_choice is not None
    assert state.pending_choice.options["candidate_card_instance_ids"] == [valid]

    with pytest.raises(Exception, match="selection is not legal"):
        _apply_direct(
            state,
            "resolve_effect_choice",
            player_id="player_1",
            payload={"selected_card_instance_ids": [invalid]},
        )

    state = _apply_direct(
        state,
        "resolve_effect_choice",
        player_id="player_1",
        payload={"selected_card_instance_ids": [valid]},
    )
    assert valid in state.players["player_1"].hand
    assert invalid in state.players["player_1"].waiting_room


def test_effect_inspection_pending_choice_blocks_manual_adjustment(tmp_path):
    service, match_id = _create_match(tmp_path, seed=211)
    state = _reach_first_main(service, match_id)
    source = _instance(state, "player_1", "PL!-bp6-002", zone="main_deck")
    state.players["player_1"].main_deck.remove(source)
    state.players["player_1"].hand.append(source)
    state.cards[source].face_up = True
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
    invocation = state.pending_effects[0]
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": invocation.invocation_id},
    )

    with pytest.raises(Exception, match="structured effect inspection"):
        _apply_direct(
            state,
            "manual_adjustment",
            player_id="player_1",
            payload={
                "reason": "incorrect fallback",
                "requires_confirmation": True,
                "confirmed_by": "tester",
                "source_invocation_id": invocation.invocation_id,
                "source_effect_id": invocation.effect_id,
                "source_card_instance_id": invocation.source_card_instance_id,
                "adjustments": [
                    {
                        "adjustment_type": "draw_card",
                        "target_player_id": "player_1",
                        "amount": 1,
                    }
                ],
            },
        )


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


def _state_with_wait_energy_effect(tmp_path: Path):
    service, match_id = _create_match(tmp_path, seed=313)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    state = _manual_move(service, match_id, state, source, "hand")
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-wait-energy:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "0" * 64,
            "effect_index": 1,
            "label_ja": (
                "【登場】手札を1枚控え室に置いてもよい："
                "自分のエネルギーデッキから、"
                "エネルギーカードを1枚ウェイト状態で置く。"
            ),
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "none",
            "is_optional": True,
            "condition": {"minimum_energy_deck_cards": 1},
            "cost": [{"action_type": "discard_from_hand"}],
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {
                    "action_type": "place_energy_from_deck",
                    "target": "self",
                    "amount": 1,
                    "orientation": "wait",
                }
            ],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions[effect.effect_id] = effect
    state.cards[source].card.effect_ids = [effect.effect_id]
    state.cards[source].card.cost = 0
    return state, source


def _play_wait_energy_source(state, source: str):
    return _apply_direct(
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


def _stack_main_deck_top(state, player_id: str, ordered_ids: list[str]):
    deck = state.players[player_id].main_deck
    for instance_id in reversed(ordered_ids):
        deck.remove(instance_id)
        deck.insert(0, instance_id)
