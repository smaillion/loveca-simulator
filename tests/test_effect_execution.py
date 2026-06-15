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
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.engine import apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, EffectInvocation, PendingChoice
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
            and operation.orientation == "wait"
            for operation in effect.actions
        )
        and effect.trigger == "member_played"
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
    live_start = {
        effect.card_code: effect
        for effect in registry.effects
        if any(
            operation.action_type == "place_energy_from_deck"
            and operation.orientation == "wait"
            for operation in effect.actions
        )
        and effect.trigger == "live_started"
    }
    assert set(live_start) == {"PL!SP-bp5-222", "PL!SP-pb1-004"}
    assert live_start["PL!SP-bp5-222"].condition == {
        "minimum_active_energy": 1,
        "minimum_energy_deck_cards": 1,
    }
    assert live_start["PL!SP-pb1-004"].condition == {
        "minimum_active_energy": 2,
        "minimum_energy_deck_cards": 1,
    }


def test_registry_contains_expanded_exact_text_reorder_effects():
    registry = EffectRegistry.model_validate_json(REGISTRY.read_text(encoding="utf-8"))
    expected = {
        "PL!-bp3-014",
        "PL!-bp3-017",
        "PL!-bp3-018",
        "PL!N-bp3-022",
        "PL!N-bp4-016",
        "PL!S-bp6-018",
        "PL!HS-bp2-016",
        "PL!HS-pb1-024",
        "PL!-bp6-016",
        "PL!-sd1-019",
        "PL!N-bp1-002",
        "PL!S-PR-028",
        "PL!S-PR-032",
        "PL!S-PR-033",
    }
    registered = {
        effect.card_code: effect
        for effect in registry.effects
        if any(
            operation.action_type == "reorder_deck_top"
            for operation in effect.actions
        )
    }

    assert expected <= set(registered)
    assert registered["PL!-bp3-017"].choice is not None
    assert registered["PL!-bp3-017"].choice.amount == 2
    assert registered["PL!-bp3-017"].cost[0].action_type == "apply_wait"
    assert registered["PL!HS-bp2-016"].cost == []
    assert registered["PL!-bp6-016"].trigger == "live_succeeded"
    assert registered["PL!-bp6-016"].choice.minimum == 3
    assert registered["PL!S-PR-028"].trigger == "member_played"
    assert registered["PL!S-PR-028"].simulation_support == "test_validated_executable"
    assert registered["PL!S-PR-028"].choice.amount == 3
    assert registered["PL!N-bp1-002"].choice.maximum == 3


def test_effect_candidate_discovery_is_review_only_after_registry_update():
    remaining = discover_effect_candidates(PROJECT_ROOT / "data" / "loveca.sqlite3")
    all_candidates = discover_effect_candidates(
        PROJECT_ROOT / "data" / "loveca.sqlite3",
        include_registered=True,
    )

    assert remaining == []
    assert len(all_candidates) >= 425
    assert len({candidate.card_code for candidate in all_candidates}) >= 417
    assert all(candidate.already_registered for candidate in all_candidates)
    assert {candidate.pattern_id for candidate in all_candidates} >= {
        "onplay_wait_inspect2_reorder_rest_wr",
        "onplay_inspect2_reorder_rest_wr",
        "onplay_inspect3_reorder_rest_wr",
        "live_success_inspect3_reorder_all_top",
        "live_success_inspect3_reorder_rest_wr",
        "activated_wait_ready_other_member",
        "onplay_choose_draw_discard_or_wait_opponent_cost2",
        "onplay_mill5",
        "onplay_reveal3_opponent_hand_draw_if_no_live",
        "onplay_both_deploy_cost2_waiting_member",
        "onplay_baton_lower_both_discard_to3_draw3",
        "manual_timing_fallback",
    }


def test_effect_registry_timing_prompt_coverage_exceeds_target():
    registry = EffectRegistry.model_validate_json(REGISTRY.read_text(encoding="utf-8"))
    registered_card_codes = {effect.card_code for effect in registry.effects}

    import sqlite3

    connection = sqlite3.connect(PROJECT_ROOT / "data" / "loveca.sqlite3")
    try:
        cards_with_text = connection.execute(
            """
            SELECT COUNT(DISTINCT gameplay_card_id)
            FROM card_text_revisions
            WHERE raw_effect_text_ja IS NOT NULL
              AND TRIM(raw_effect_text_ja) <> ''
            """
        ).fetchone()[0]
    finally:
        connection.close()

    assert cards_with_text
    assert len(registered_card_codes) / cards_with_text >= 0.30


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
    target = next(effect for effect in broken.effects if effect.effect_id == "LL-bp1-001:1")
    target.raw_text_hash = "0" * 64

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
    service, match_id = _create_match(tmp_path, seed=223)
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

    state = _apply_direct(
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
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": [discard],
        },
    )
    assert discard in state.players["player_1"].waiting_room
    from loveca.simulation.engine import generate_legal_actions

    assert not any(
        action.action_type == "activate_effect"
        for action in generate_legal_actions(state)
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
    state = _apply_direct(
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


def test_live_start_color_choice_grants_temporary_heart(tmp_path):
    service, match_id = _create_match(tmp_path, seed=52)
    state = _reach_first_main(service, match_id)
    source = _instance(state, "player_1", "PL!N-bp1-001", zone="main_deck")
    live = next(
        instance_id
        for instance_id in state.players["player_1"].main_deck
        if state.cards[instance_id].card.card_type == "live"
    )
    state = _manual_move(service, match_id, state, source, "member_center")
    state = _manual_move(service, match_id, state, live, "hand")
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-color-heart:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "1" * 64,
            "effect_index": 1,
            "label_ja": (
                "【ライブ開始時】好きなハートの色を1つ指定する。"
                "ライブ終了時まで、そのハートを1つ得る。"
            ),
            "effect_type": "triggered",
            "timing": "live_start",
            "trigger": "live_started",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "once_per_live",
            "is_optional": False,
            "condition": {},
            "cost": [],
            "choice": {
                "choice_type": "choose_color",
                "color_slots": ["heart01", "heart02", "heart03", "heart04", "heart05", "heart06"],
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "gain_heart", "amount": 1}],
            "duration": "live",
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions[effect.effect_id] = effect
    state.cards[source].card.effect_ids = [effect.effect_id]
    state = _advance_to_live_start_direct(state, live)

    invocation = next(
        item for item in state.pending_effects if item.effect_id == effect.effect_id
    )
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": invocation.invocation_id,
            "selected_color_slot": "heart03",
        },
    )

    assert any(
        modifier.modifier_type == "heart"
        and modifier.color_slot == "heart03"
        and modifier.amount == 1
        and modifier.duration == "live"
        for modifier in state.players["player_1"].manual_modifiers
    )


def test_energy_choice_can_apply_wait_and_ready_energy(tmp_path):
    state, source = _state_with_wait_energy_effect(tmp_path)
    active_energy = state.players["player_1"].energy_area[0]
    wait_energy = state.players["player_1"].energy_area[1]
    state.cards[wait_energy].orientation = "wait"
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-energy-state:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "2" * 64,
            "effect_index": 1,
            "label_ja": "【登場】エネルギーを1枚ウェイトにし、エネルギーを1枚アクティブにする。",
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {},
            "cost": [],
            "choice": {
                "choice_type": "energy_from_area",
                "orientation": "active",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "apply_wait_energy", "amount": 1}],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    state.cards[source].card.effect_ids = [effect.effect_id]

    state = _play_wait_energy_source(state, source)
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": [active_energy],
        },
    )
    assert state.cards[active_energy].orientation == "wait"

    ready_effect = effect.model_copy(deep=True)
    ready_effect.effect_id = "test-energy-state:2"
    ready_effect.choice.orientation = "wait"
    ready_effect.actions = [
        ready_effect.actions[0].model_copy(
            update={"action_type": "ready_energy", "amount": 1}
        )
    ]
    state.pending_effects.clear()
    state.effect_definitions = {ready_effect.effect_id: ready_effect}
    state.cards[source].card.effect_ids = [ready_effect.effect_id]
    state.cards[source].orientation = "active"
    state.pending_effects.append(
        _effect_invocation_for_test(state, ready_effect.effect_id, source)
    )

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": [wait_energy],
        },
    )
    assert state.cards[wait_energy].orientation == "active"


def test_activated_wait_can_ready_another_member(tmp_path):
    service, match_id = _create_match(tmp_path, seed=57)
    state = _reach_first_main(service, match_id)
    candidates = [
        instance_id
        for instance_id in state.players["player_1"].main_deck
        if state.cards[instance_id].card.card_code == "PL!-bp3-001"
    ]
    assert len(candidates) >= 2
    source, target = candidates[:2]
    state = _manual_move(service, match_id, state, source, "member_center")
    state = _manual_move(service, match_id, state, target, "member_left")
    state.cards[target].orientation = "wait"
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-ready-other:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "4" * 64,
            "effect_index": 1,
            "label_ja": (
                "【起動】【ターン1回】このメンバーをウェイトにする："
                "自分のステージにいるほかのメンバー1人をアクティブにする。"
            ),
            "effect_type": "activated",
            "timing": "activated_main",
            "trigger": "player_activation",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "once_per_turn",
            "is_optional": False,
            "condition": {"source_zone": "stage", "source_orientation": "active"},
            "cost": [{"action_type": "apply_wait", "target": "source"}],
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "orientation": "wait",
                "exclude_source": True,
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "ready_member"}],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    state.cards[source].card.effect_ids = [effect.effect_id]

    legal = generate_legal_actions(state)
    activation = next(
        entry
        for action in legal
        if action.action_type == "activate_effect"
        for entry in action.options["activations"]
        if entry["effect_id"] == effect.effect_id
    )
    assert activation["source_card_instance_id"] == source

    state = _apply_direct(
        state,
        "activate_effect",
        player_id="player_1",
        payload={
            "effect_id": effect.effect_id,
            "source_card_instance_id": source,
        },
    )
    assert state.cards[source].orientation == "wait"
    assert state.cards[target].orientation == "wait"
    invocation = state.pending_effects[0]
    legal = generate_legal_actions(state)
    options = legal[0].options["invocations"][0]
    assert source not in options["candidate_card_instance_ids"]
    assert target in options["candidate_card_instance_ids"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": invocation.invocation_id,
            "selected_card_instance_ids": [target],
        },
    )

    assert state.cards[source].orientation == "wait"
    assert state.cards[target].orientation == "active"
    assert not state.pending_effects


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


def test_live_success_trigger_auto_resolves_before_turn_completion(tmp_path):
    service, match_id = _create_match(tmp_path, seed=69)
    state = _reach_first_main(service, match_id)
    live = next(
        instance_id
        for instance_id in state.players["player_1"].main_deck
        if state.cards[instance_id].card.card_type == "live"
    )
    state.players["player_1"].main_deck.remove(live)
    state.players["player_1"].live_area.append(live)
    state.cards[live].face_up = True
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-live-success:1",
            "card_code": state.cards[live].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "3" * 64,
            "effect_index": 1,
            "label_ja": "【ライブ成功時】カードを1枚引く。",
            "effect_type": "triggered",
            "timing": "live_success",
            "trigger": "live_succeeded",
            "execution_mode": "auto_resolve",
            "frequency_limit": "once_per_live",
            "is_optional": False,
            "condition": {},
            "cost": [],
            "choice": None,
            "actions": [{"action_type": "draw_card", "amount": 1}],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions[effect.effect_id] = effect
    state.cards[live].card.effect_ids = [effect.effect_id]
    state.phase = "live_judgment"
    state.active_player_id = None
    state.players["player_1"].live_result.requirements_satisfied = True
    state.players["player_1"].live_result.total_score = 1
    state.players["player_2"].live_result.requirements_satisfied = False
    hand_count = len(state.players["player_1"].hand)

    result = apply_action(
        state,
        ActionRequest(
            action_type="advance_phase",
            expected_revision=state.revision,
            player_id=None,
            payload={},
        ),
    )

    assert result.state.phase == "turn_complete"
    assert live in result.state.players["player_1"].success_live_area
    assert len(result.state.players["player_1"].hand) == hand_count + 1
    assert any(event.event_type == "effect_auto_resolved" for event in result.events)
    assert result.state.success_live_moved_instance_ids == {"player_1": [live]}


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


def test_onplay_branch_choice_can_draw_discard_or_wait_opponent_cost2(tmp_path):
    service, match_id = _create_match(tmp_path, seed=221)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    state = _manual_move(service, match_id, state, source, "hand")
    state.cards[source].card.cost = 0
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-branch:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "b" * 64,
            "effect_index": 1,
            "label_ja": (
                "【登場】以下から1つを選ぶ。 "
                "・カードを1枚引き、手札を1枚控え室に置く。 "
                "・相手のステージにいるすべてのコスト2以下のメンバーをウェイトにする。"
            ),
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {},
            "cost": [],
            "choice": {
                "choice_type": "choose_effect_branch",
                "zone": "hand",
                "branch_ids": ["draw_discard", "wait_opponent_cost2"],
                "branch_selection_minimum": {"draw_discard": 1},
                "branch_selection_maximum": {"draw_discard": 1},
            },
            "actions": [
                {"action_type": "draw_card", "amount": 1, "branch": "draw_discard"},
                {"action_type": "discard_from_hand", "branch": "draw_discard"},
                {
                    "action_type": "apply_wait_member",
                    "target": "opponent_stage_cost2_all",
                    "branch": "wait_opponent_cost2",
                },
            ],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    state.cards[source].card.effect_ids = [effect.effect_id]

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
    first_hand_count = len(state.players["player_1"].hand)
    invocation = state.pending_effects[0]
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": invocation.invocation_id,
            "selected_branch": "draw_discard",
        },
    )
    assert state.pending_effects[0].trigger_data["selected_branch"] == "draw_discard"
    assert len(state.players["player_1"].hand) == first_hand_count + 1
    discard = state.players["player_1"].hand[0]
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": [discard],
        },
    )
    assert discard in state.players["player_1"].waiting_room
    assert not state.pending_effects

    service, match_id = _create_match(tmp_path, seed=223)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    state = _manual_move(service, match_id, state, source, "hand")
    state.cards[source].card.cost = 0
    state.effect_definitions = {effect.effect_id: effect}
    state.cards[source].card.effect_ids = [effect.effect_id]
    opponent_members = [
        item
        for item in state.players["player_2"].main_deck
        if state.cards[item].card.card_type == "member"
    ][:2]
    low_cost, high_cost = opponent_members
    for instance_id in opponent_members:
        state.players["player_2"].main_deck.remove(instance_id)
    state.players["player_2"].member_area["left"] = low_cost
    state.players["player_2"].member_area["center"] = high_cost
    state.cards[low_cost].card.cost = 2
    state.cards[high_cost].card.cost = 3
    state.cards[low_cost].orientation = "active"
    state.cards[high_cost].orientation = "active"

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
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_branch": "wait_opponent_cost2",
        },
    )
    assert state.cards[low_cost].orientation == "wait"
    assert state.cards[high_cost].orientation == "active"


def test_onplay_reveals_opponent_hand_and_draws_if_no_live(tmp_path):
    service, match_id = _create_match(tmp_path, seed=224)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    state = _manual_move(service, match_id, state, source, "hand")
    state.cards[source].card.cost = 0
    selected = state.players["player_2"].hand[:3]
    for instance_id in selected:
        state.cards[instance_id].card.card_type = "member"
        state.cards[instance_id].face_up = False
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-opponent-hand-reveal:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "d" * 64,
            "effect_index": 1,
            "label_ja": (
                "【登場】相手の手札を、自分は見ないで3枚選び公開する。"
                "これにより公開されたカードの中にライブカードがない場合、カードを1枚引く。"
            ),
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {},
            "cost": [],
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "target_player": "opponent",
                "minimum": 3,
                "maximum": 3,
            },
            "actions": [
                {"action_type": "reveal_selected_cards"},
                {
                    "action_type": "draw_if_selected_none_card_type",
                    "card_type": "live",
                    "amount": 1,
                },
            ],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    state.cards[source].card.effect_ids = [effect.effect_id]

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
    hand_count = len(state.players["player_1"].hand)
    invocation = state.pending_effects[0]
    legal = generate_legal_actions(state)
    options = next(
        action.options["invocations"][0]
        for action in legal
        if action.action_type == "resolve_effect"
    )
    assert options["candidate_card_instance_ids"] == state.players["player_2"].hand

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": invocation.invocation_id,
            "selected_card_instance_ids": selected,
        },
    )

    assert all(instance_id in state.players["player_2"].hand for instance_id in selected)
    assert all(state.cards[instance_id].face_up for instance_id in selected)
    assert len(state.players["player_1"].hand) == hand_count + 1


def test_multi_player_effect_deploys_waiting_room_members_for_both_players(tmp_path):
    service, match_id = _create_match(tmp_path, seed=225)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    state = _manual_move(service, match_id, state, source, "hand")
    state.cards[source].card.cost = 0
    own_target = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member" and item != source
    )
    opponent_target = next(
        item
        for item in state.players["player_2"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    for player_id, instance_id in (
        ("player_1", own_target),
        ("player_2", opponent_target),
    ):
        state.players[player_id].main_deck.remove(instance_id)
        state.players[player_id].waiting_room.append(instance_id)
        state.cards[instance_id].card.cost = 2
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-multi-deploy:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "e" * 64,
            "effect_index": 1,
            "label_ja": (
                "【登場】自分と相手はそれぞれ、自身の控え室からコスト2以下の"
                "メンバーカードを1枚、メンバーのいないエリアにウェイト状態で"
                "登場させる。（この効果で登場したメンバーのいるエリアには、"
                "このターンにメンバーは登場できない。）"
            ),
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {},
            "cost": [],
            "choice": {
                "choice_type": "multi_player_deploy_waiting_member",
                "zone": "waiting_room",
                "card_type": "member",
                "maximum_cost": 2,
                "minimum": 0,
                "maximum": 1,
            },
            "actions": [],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    state.cards[source].card.effect_ids = [effect.effect_id]

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
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": state.pending_effects[0].invocation_id},
    )
    assert state.pending_choice is not None
    assert state.pending_choice.choice_type == "multi_player_effect_selection"
    assert state.pending_choice.player_id == "player_1"
    assert own_target in state.pending_choice.options["candidate_card_instance_ids"]

    state = _apply_direct(
        state,
        "resolve_effect_choice",
        player_id="player_1",
        payload={"selected_card_instance_id": own_target, "slot": "left"},
    )
    assert state.players["player_1"].member_area["left"] == own_target
    assert state.cards[own_target].orientation == "wait"
    assert state.pending_choice.player_id == "player_2"

    state = _apply_direct(
        state,
        "resolve_effect_choice",
        player_id="player_2",
        payload={"selected_card_instance_id": opponent_target, "slot": "center"},
    )
    assert state.players["player_2"].member_area["center"] == opponent_target
    assert state.cards[opponent_target].orientation == "wait"
    assert "left" in state.players["player_1"].member_areas_entered_this_turn
    assert "center" in state.players["player_2"].member_areas_entered_this_turn
    assert state.pending_choice is None
    assert not state.pending_effects


def test_multi_player_effect_discards_to_three_then_draws_three(tmp_path):
    service, match_id = _create_match(tmp_path, seed=226)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    replacement = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member" and item != source
    )
    state.cards[source].card.cost = 4
    state.cards[replacement].card.cost = 1
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-hand-reset:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "f" * 64,
            "effect_index": 1,
            "label_ja": (
                "【登場】このメンバーよりコストが低いメンバーからバトンタッチして"
                "登場した場合、自分と相手はそれぞれ自身の手札の枚数が3枚になるまで"
                "手札を控え室に置き、その後、自分と相手はそれぞれカードを3枚引く。"
            ),
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {"replacement_member_cost_less_than_source": True},
            "cost": [],
            "choice": {
                "choice_type": "multi_player_discard_to_hand_size_then_draw",
                "zone": "hand",
                "target_hand_size": 3,
                "amount": 3,
            },
            "actions": [],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    state.cards[source].card.effect_ids = [effect.effect_id]
    state.pending_effects.append(
        _effect_invocation_for_test(state, effect.effect_id, source)
    )
    state.pending_effects[0].trigger_data["replacement_card_instance_id"] = replacement
    player_1_discards = state.players["player_1"].hand[
        : len(state.players["player_1"].hand) - 3
    ]
    player_2_discards = state.players["player_2"].hand[
        : len(state.players["player_2"].hand) - 3
    ]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": state.pending_effects[0].invocation_id},
    )
    assert state.pending_choice is not None
    assert state.pending_choice.options["minimum"] == len(player_1_discards)

    state = _apply_direct(
        state,
        "resolve_effect_choice",
        player_id="player_1",
        payload={"selected_card_instance_ids": player_1_discards},
    )
    assert state.pending_choice.player_id == "player_2"
    assert state.pending_choice.options["minimum"] == len(player_2_discards)

    state = _apply_direct(
        state,
        "resolve_effect_choice",
        player_id="player_2",
        payload={"selected_card_instance_ids": player_2_discards},
    )
    assert all(item in state.players["player_1"].waiting_room for item in player_1_discards)
    assert all(item in state.players["player_2"].waiting_room for item in player_2_discards)
    assert len(state.players["player_1"].hand) == 6
    assert len(state.players["player_2"].hand) == 6
    assert state.pending_choice is None
    assert not state.pending_effects


def test_pending_effect_can_be_skipped_with_a_debug_event(tmp_path):
    service, match_id = _create_match(tmp_path, seed=227)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-manual-skip:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "1" * 64,
            "effect_index": 1,
            "label_ja": "【登場】未対応の能力。",
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "manual_resolution",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {},
            "cost": [],
            "actions": [],
            "duration": None,
            "simulation_support": "manual_resolution",
            "review_status": "provisional",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    invocation = _effect_invocation_for_test(state, effect.effect_id, source)
    state.pending_effects.append(invocation)

    legal = generate_legal_actions(state)
    assert any(action.action_type == "skip_effect" for action in legal)

    result = apply_action(
        state,
        ActionRequest(
            action_type="skip_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "invocation_id": invocation.invocation_id,
                "reason": "test skip",
                "error_message": "fixture unsupported",
            },
        ),
    )

    assert not result.state.pending_effects
    assert result.events[-1].event_type == "effect_skipped_due_to_error"
    assert result.events[-1].source == "manual"
    assert result.events[-1].data["effect_id"] == effect.effect_id
    assert result.events[-1].data["error_message"] == "fixture unsupported"


def test_skipping_effect_choice_cleans_inspected_cards_for_debug_continuation(tmp_path):
    service, match_id = _create_match(tmp_path, seed=228)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    inspected = state.players["player_1"].main_deck[:2]
    for instance_id in inspected:
        state.players["player_1"].main_deck.remove(instance_id)
        state.players["player_1"].resolution_area.append(instance_id)
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-inspection-skip:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "2" * 64,
            "effect_index": 1,
            "label_ja": "【登場】デッキの上からカードを2枚見る。",
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {},
            "cost": [],
            "choice": {
                "choice_type": "inspect_top_select",
                "amount": 2,
                "minimum": 0,
                "maximum": 2,
                "requires_order": True,
                "selected_destination": "main_deck_top_ordered",
                "unselected_destination": "waiting_room",
            },
            "actions": [],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    invocation = _effect_invocation_for_test(state, effect.effect_id, source)
    state.pending_effects.append(invocation)
    state.pending_choice = PendingChoice(
        choice_type="effect_inspection_selection",
        player_id="player_1",
        message_ja="確認したカードの処理を選んでください。",
        message_zh="请选择检查后的卡牌处理结果。",
        options={
            "invocation_id": invocation.invocation_id,
            "effect_id": effect.effect_id,
            "source_card_instance_id": source,
            "inspected_card_instance_ids": list(inspected),
            "candidate_card_instance_ids": list(inspected),
            "minimum": 0,
            "maximum": 2,
            "requires_order": True,
            "selected_destination": "main_deck_top_ordered",
            "unselected_destination": "waiting_room",
        },
    )

    result = apply_action(
        state,
        ActionRequest(
            action_type="skip_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "invocation_id": invocation.invocation_id,
                "reason": "choice UI failed",
                "error_message": "cannot submit choice",
            },
        ),
    )

    assert result.state.pending_choice is None
    assert not result.state.pending_effects
    assert all(
        item not in result.state.players["player_1"].resolution_area
        for item in inspected
    )
    assert all(item in result.state.players["player_1"].waiting_room for item in inspected)
    event = result.events[-1]
    assert event.event_type == "effect_skipped_due_to_error"
    assert event.data["pending_choice_type"] == "effect_inspection_selection"
    assert event.data["cleaned_resolution_area_instance_ids"] == inspected


def test_onplay_mill5_auto_moves_top_cards_to_waiting_room(tmp_path):
    service, match_id = _create_match(tmp_path, seed=222)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    state = _manual_move(service, match_id, state, source, "hand")
    state.cards[source].card.cost = 0
    expected = state.players["player_1"].main_deck[:5]
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-mill5:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "c" * 64,
            "effect_index": 1,
            "label_ja": "【登場】デッキの上からカードを5枚控え室に置く。",
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "auto_resolve",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {},
            "cost": [],
            "choice": None,
            "actions": [{"action_type": "mill_top_cards", "amount": 5}],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    state.cards[source].card.effect_ids = [effect.effect_id]

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

    assert all(item in state.players["player_1"].waiting_room for item in expected)
    assert not state.pending_effects


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


def test_optional_discard_cost_enters_structured_inspection_choice(tmp_path):
    service, match_id = _create_match(tmp_path, seed=501)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    state = _manual_move(service, match_id, state, source, "hand")
    state.cards[source].card.cost = 0
    discard = next(item for item in state.players["player_1"].hand if item != source)
    inspected = state.players["player_1"].main_deck[:3]
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-discard-inspect3:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "8" * 64,
            "effect_index": 1,
            "label_ja": (
                "【登場】手札を1枚控え室に置いてもよい："
                "自分のデッキの上からカードを3枚見る。"
                "その中から1枚を手札に加え、残りを控え室に置く。"
            ),
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "none",
            "is_optional": True,
            "condition": {},
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "choice": {
                "choice_type": "inspect_top_select",
                "amount": 3,
                "minimum": 1,
                "maximum": 1,
                "selected_destination": "hand",
                "unselected_destination": "waiting_room",
            },
            "actions": [
                {"action_type": "inspect_top_cards", "amount": 3},
                {"action_type": "select_to_hand_from_inspected"},
                {"action_type": "move_remaining_cards"},
            ],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    state.cards[source].card.effect_ids = [effect.effect_id]

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
    legal = generate_legal_actions(state)
    options = legal[0].options["invocations"][0]
    assert options["choice_type"] == "card_from_zone"
    assert options["cost_choice"]["zone"] == "hand"
    assert discard in options["candidate_card_instance_ids"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "accepted": True,
            "selected_card_instance_ids": [discard],
        },
    )
    assert discard in state.players["player_1"].waiting_room
    assert state.pending_choice is not None
    assert state.pending_choice.choice_type == "effect_inspection_selection"
    assert state.pending_choice.options["inspected_card_instance_ids"] == inspected

    selected = inspected[1]
    state = _apply_direct(
        state,
        "resolve_effect_choice",
        player_id="player_1",
        payload={"selected_card_instance_ids": [selected]},
    )
    assert selected in state.players["player_1"].hand
    assert all(
        item in state.players["player_1"].waiting_room
        for item in inspected
        if item != selected
    )
    assert not state.pending_effects


def test_source_to_waiting_cost_allows_post_cost_waiting_room_choice(tmp_path):
    service, match_id = _create_match(tmp_path, seed=502)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    target = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "live"
    )
    state = _manual_move(service, match_id, state, source, "member_center")
    state = _manual_move(service, match_id, state, target, "waiting_room")
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-source-to-wr-return-live:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "9" * 64,
            "effect_index": 1,
            "label_ja": (
                "【起動】このメンバーをステージから控え室に置く："
                "自分の控え室からライブカードを1枚手札に加える。"
            ),
            "effect_type": "activated",
            "timing": "activated_main",
            "trigger": "player_activation",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {"source_zone": "stage"},
            "cost": [{"action_type": "source_to_waiting_room"}],
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "waiting_room",
                "card_type": "live",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "return_from_waiting_room"}],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    state.cards[source].card.effect_ids = [effect.effect_id]
    state.pending_effects.append(_effect_invocation_for_test(state, effect.effect_id, source))

    legal = generate_legal_actions(state)
    initial_options = legal[0].options["invocations"][0]
    assert initial_options["candidate_card_instance_ids"] == []

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": state.pending_effects[0].invocation_id},
    )
    assert source in state.players["player_1"].waiting_room
    assert state.pending_effects[0].resolution_stage == "after_cost"
    legal = generate_legal_actions(state)
    options = legal[0].options["invocations"][0]
    assert target in options["candidate_card_instance_ids"]

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
    assert not state.pending_effects


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


def _advance_to_live_start_direct(state, live_instance_id: str):
    state = _apply_direct(state, "end_main_phase", player_id="player_1")
    for _ in range(3):
        state = _apply_direct(state, "advance_phase", player_id="player_2")
    state = _apply_direct(state, "end_main_phase", player_id="player_2")
    state = _apply_direct(
        state,
        "set_live_cards",
        player_id="player_1",
        payload={"card_instance_ids": [live_instance_id]},
    )
    state = _apply_direct(
        state,
        "set_live_cards",
        player_id="player_2",
        payload={"card_instance_ids": []},
    )
    return _apply_direct(state, "advance_phase", player_id="player_1")


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


def _effect_invocation_for_test(
    state,
    effect_id: str,
    source_instance_id: str,
) -> EffectInvocation:
    return EffectInvocation(
        invocation_id=f"test:{effect_id}",
        effect_id=effect_id,
        source_card_instance_id=source_instance_id,
        player_id=state.cards[source_instance_id].owner_id,
        trigger_event=state.effect_definitions[effect_id].trigger,
    )
