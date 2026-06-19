from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from loveca.cards.importer import import_normalized_cards
from loveca.decks.analyzer import load_deck, parse_deck
from loveca.simulation.engine import (
    IllegalActionError,
    StaleRevisionError,
    apply_action,
    generate_legal_actions,
)
from loveca.simulation.models import ActionRequest, MatchState
from loveca.simulation.runtime import (
    MatchRepository,
    RuntimeSchemaError,
    initialize_runtime_database,
)
from loveca.simulation.service import MatchService

# Official comprehensive rules ver. 1.06:
# 6.2.1.5 opening hand 6; 6.2.1.6 mulligan; 6.2.1.7 initial Energy 3;
# 7.1.2 and 7.3.3 phase order; 8.2.2/8.2.4 set up to 3 cards and draw
# the same count; 8.3 performance;
# 8.3.10-8.3.15 Blade total, Yell, Live owned Hearts, and requirements;
# 8.4.2-8.4.7 score calculation and Live judgment; 8.4.13 next first player;
# 10.2 deck refresh; 1.2.1.1-1.2.1.2 victory and simultaneous draw.
PROJECT_ROOT = Path(__file__).parents[1]
SAMPLE_CARDS = (
    PROJECT_ROOT
    / "data_samples"
    / "normalized"
    / "cards-cross-product-sample.json"
)
NORMALIZATION = PROJECT_ROOT / "data_sources" / "card-entity-normalization.json"
SAMPLE_DECK = PROJECT_ROOT / "tests" / "fixtures" / "legal-deck.json"


def test_unavailable_preferred_printing_falls_back_for_match_setup(tmp_path):
    card_database = tmp_path / "cards.sqlite3"
    import_normalized_cards(card_database, SAMPLE_CARDS, NORMALIZATION)
    service = MatchService(card_database, tmp_path / "matches.sqlite3")
    payload = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))
    payload["main_deck"][0]["preferred_printing_id"] = "LL-bp1-001-MISSING"
    deck = parse_deck(payload)

    result = service.create_match(
        first_name="A",
        first_deck=deck,
        second_name="B",
        second_deck=deck,
        seed=1,
    )

    assert result.state.match_id
    assert result.state.cards[result.state.players["player_1"].main_deck[0]].card.card_code


def test_initial_main_deck_shuffle_is_seeded_and_observable(tmp_path):
    first_service, first_match_id = _create_match(
        tmp_path / "first",
        seed=4242,
    )
    repeated_service, repeated_match_id = _create_match(
        tmp_path / "repeated",
        seed=4242,
    )
    different_service, different_match_id = _create_match(
        tmp_path / "different",
        seed=4243,
    )

    first = first_service.repository.get_state(first_match_id)
    repeated = repeated_service.repository.get_state(repeated_match_id)
    different = different_service.repository.get_state(different_match_id)

    assert first.players["player_1"].hand == repeated.players["player_1"].hand
    assert first.players["player_1"].main_deck == repeated.players["player_1"].main_deck
    assert first.players["player_1"].hand != different.players["player_1"].hand
    first_replay = first_service.repository.replay(first_match_id)
    shuffle_events = [
        event
        for event in first_replay["events"]
        if event["event_type"] == "deck_shuffled"
    ]
    assert {event["player_id"] for event in shuffle_events} == {
        "player_1",
        "player_2",
    }
    assert all(event["data"]["card_count"] == 60 for event in shuffle_events)


def test_setup_phase_order_and_next_turn_start(tmp_path):
    service, match_id = _create_match(tmp_path, seed=260428)

    state = service.repository.get_state(match_id)
    assert state.phase == "setup_mulligan_first"
    assert state.first_player_id == "player_1"
    assert len(state.players["player_1"].main_deck) == 54
    assert len(state.players["player_1"].hand) == 6
    assert len(state.players["player_2"].hand) == 6

    state = _apply(
        service,
        match_id,
        state,
        "submit_mulligan",
        player_id="player_1",
        payload={"card_instance_ids": state.players["player_1"].hand[:2]},
    )
    assert len(state.players["player_1"].hand) == 6
    state = _apply(
        service,
        match_id,
        state,
        "submit_mulligan",
        player_id="player_2",
        payload={"card_instance_ids": []},
    )
    assert state.phase == "first_active"
    assert len(state.players["player_1"].energy_area) == 3
    assert len(state.players["player_2"].energy_area) == 3

    expected_phases = [
        "first_energy",
        "first_draw",
        "first_main",
        "second_active",
        "second_energy",
        "second_draw",
        "second_main",
        "live_set_first",
        "live_set_second",
        "performance_first",
        "yell_first",
        "performance_second",
        "yell_second",
        "live_judgment",
        "turn_complete",
    ]
    for expected in expected_phases:
        if state.phase.endswith(("_active", "_energy", "_draw")):
            action_type = "advance_phase"
        elif state.phase.endswith("_main"):
            action_type = "end_main_phase"
        elif state.phase.startswith("live_set"):
            action_type = "set_live_cards"
        else:
            action_type = "advance_phase"
        state = _apply(
            service,
            match_id,
            state,
            action_type,
            player_id=state.active_player_id,
            payload={"card_instance_ids": []} if action_type == "set_live_cards" else {},
        )
        assert state.phase == expected
    assert state.completed_reason is None
    assert state.live_judgment_summary is not None
    assert state.live_judgment_summary["basis"] == "no_successful_live"
    assert state.next_first_player_id == "player_1"
    assert _match_status(service, match_id) == "active"

    state = _apply(service, match_id, state, "start_next_turn")
    assert state.phase == "first_active"
    assert state.turn_number == 2
    assert state.first_player_id == "player_1"
    assert state.live_judgment_summary is None


def test_yell_and_live_requirement_details_are_preserved(tmp_path):
    service, match_id = _create_match(tmp_path, seed=106)
    state = _reach_first_main(service, match_id)
    live_id = next(
        instance_id
        for instance_id in state.players["player_1"].main_deck
        if state.cards[instance_id].card.card_type == "live"
        and state.cards[instance_id].card.required_hearts
    )
    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "prepare Live requirement review",
            "requires_confirmation": True,
            "confirmed_by": "tester",
            "adjustments": [
                {
                    "adjustment_type": "move_card",
                    "target_player_id": "player_1",
                    "target_card_instance_id": live_id,
                    "to_zone": "hand",
                }
            ],
        },
    )
    state = _apply(
        service,
        match_id,
        state,
        "end_main_phase",
        player_id="player_1",
    )
    for _ in range(3):
        state = _apply(
            service,
            match_id,
            state,
            "advance_phase",
            player_id="player_2",
        )
    state = _apply(
        service,
        match_id,
        state,
        "end_main_phase",
        player_id="player_2",
    )
    state = _apply(
        service,
        match_id,
        state,
        "set_live_cards",
        player_id="player_1",
        payload={"card_instance_ids": [live_id]},
    )
    state = _apply(
        service,
        match_id,
        state,
        "set_live_cards",
        player_id="player_2",
        payload={"card_instance_ids": []},
    )
    assert state.phase == "performance_first"

    state = _apply(
        service,
        match_id,
        state,
        "advance_phase",
        player_id="player_1",
    )
    assert state.phase == "yell_first"
    assert state.cards[live_id].face_up
    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "exercise Yell output",
            "requires_confirmation": True,
            "confirmed_by": "tester",
            "adjustments": [
                    {
                        "adjustment_type": "modify_blade",
                        "target_player_id": "player_1",
                        "amount": 2,
                        "duration": "live",
                    }
            ],
        },
    )
    state = _apply(
        service,
        match_id,
        state,
        "advance_phase",
        player_id="player_1",
    )
    if state.pending_choice is not None:
        state = _apply(
            service,
            match_id,
            state,
            "resolve_live_requirements",
            player_id="player_1",
            payload={"live_instance_ids": [live_id]},
        )

    result = state.players["player_1"].live_result
    assert state.phase == "performance_second"
    assert result.blade_count == 2
    assert len(result.revealed_instance_ids) == 2
    assert result.live_allocations[0]["live_instance_id"] == live_id
    assert result.live_allocations[0]["required_hearts"]
    assert "consumed_hearts" in result.live_allocations[0]
    assert "missing_hearts" in result.live_allocations[0]


def test_two_successful_live_cards_use_combined_score_but_move_only_one(tmp_path):
    service, match_id = _create_match(tmp_path, seed=20842)
    state = _reach_first_main(service, match_id)
    player_id = state.first_player_id or ""
    live_ids = _flow_test_live_cards(state, player_id, count=2)
    colors = {
        color
        for instance_id in live_ids
        for color in state.cards[instance_id].card.required_hearts
    }
    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id=player_id,
        payload={
            "reason": "prepare two-Live total score rule test",
            "adjustments": [
                *[
                    {
                        "adjustment_type": "move_card",
                        "target_player_id": player_id,
                        "target_card_instance_id": instance_id,
                        "to_zone": "hand",
                    }
                    for instance_id in live_ids
                ],
                *[
                    {
                        "adjustment_type": "modify_heart",
                        "target_player_id": player_id,
                        "color_slot": color,
                        "amount": 20,
                        "duration": "live",
                    }
                    for color in colors
                ],
            ],
        },
    )
    state = _reach_live_set_from_first_main(service, match_id, state)
    state = _apply(
        service,
        match_id,
        state,
        "set_live_cards",
        player_id=player_id,
        payload={"card_instance_ids": live_ids},
    )
    state = _apply(
        service,
        match_id,
        state,
        "set_live_cards",
        player_id=state.second_player_id,
        payload={"card_instance_ids": []},
    )
    state = _apply(
        service,
        match_id,
        state,
        "advance_phase",
        player_id=player_id,
    )
    state = _apply(
        service,
        match_id,
        state,
        "advance_phase",
        player_id=player_id,
    )
    assert state.pending_choice is not None
    state = _apply(
        service,
        match_id,
        state,
        "resolve_live_requirements",
        player_id=player_id,
        payload={"live_instance_ids": live_ids},
    )
    for _ in range(2):
        state = _apply(
            service,
            match_id,
            state,
            "advance_phase",
            player_id=state.second_player_id,
        )

    expected_score = sum(state.cards[item].card.score or 0 for item in live_ids)
    assert state.players[player_id].live_result.base_score == expected_score
    assert state.players[player_id].live_result.total_score == expected_score

    state = _apply(service, match_id, state, "advance_phase")
    assert state.pending_choice is not None
    assert state.pending_choice.choice_type == "success_live"
    state = _apply(
        service,
        match_id,
        state,
        "resolve_live_requirements",
        player_id=player_id,
        payload={"success_live_instance_id": live_ids[0]},
    )
    assert state.phase == "turn_complete"
    assert state.players[player_id].success_live_area == [live_ids[0]]
    assert live_ids[1] in state.players[player_id].waiting_room


def test_manual_adjustment_and_member_play_are_action_only(tmp_path):
    service, match_id = _create_match(tmp_path, seed=11)
    state = _reach_first_main(service, match_id)
    player = state.players["player_1"]
    member_id = next(
        instance_id
        for instance_id in player.main_deck
        if state.cards[instance_id].card.card_type == "member"
        and state.cards[instance_id].card.cost is not None
        and state.cards[instance_id].card.cost <= len(player.energy_area)
    )
    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "rule test setup",
            "requires_confirmation": True,
            "confirmed_by": "tester",
            "adjustments": [
                {
                    "adjustment_type": "move_card",
                    "target_player_id": "player_1",
                    "target_card_instance_id": member_id,
                    "to_zone": "hand",
                }
            ],
        },
    )
    cost = state.cards[member_id].card.cost or 0
    energy_ids = state.players["player_1"].energy_area[:cost]
    state = _apply(
        service,
        match_id,
        state,
        "play_member",
        player_id="player_1",
        payload={
            "card_instance_id": member_id,
            "slot": "center",
            "energy_instance_ids": energy_ids,
        },
    )
    assert state.players["player_1"].member_area["center"] == member_id
    assert all(state.cards[item].orientation == "wait" for item in energy_ids)
    assert state.players["player_1"].member_areas_entered_this_turn == ["center"]


def test_manual_return_from_waiting_room_moves_card_to_hand(tmp_path):
    service, match_id = _create_match(tmp_path, seed=17)
    state = _reach_first_main(service, match_id)
    manual_options = next(
        action.options
        for action in generate_legal_actions(state)
        if action.action_type == "manual_adjustment"
    )
    assert "return_from_waiting_room" in manual_options["adjustment_types"]
    card_id = state.players["player_1"].hand[0]

    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "prepare waiting-room return",
            "requires_confirmation": True,
            "confirmed_by": "tester",
            "adjustments": [
                {
                    "adjustment_type": "discard_card",
                    "target_player_id": "player_1",
                    "target_card_instance_id": card_id,
                }
            ],
        },
    )
    assert card_id in state.players["player_1"].waiting_room
    assert card_id not in state.players["player_1"].hand

    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "return from waiting room",
            "requires_confirmation": True,
            "confirmed_by": "tester",
            "adjustments": [
                {
                    "adjustment_type": "return_from_waiting_room",
                    "target_player_id": "player_1",
                    "target_card_instance_id": card_id,
                }
            ],
        },
    )
    assert card_id in state.players["player_1"].hand
    assert card_id not in state.players["player_1"].waiting_room

    deck_card = state.players["player_1"].main_deck[0]
    with pytest.raises(IllegalActionError, match="waiting room"):

        _apply(
            service,
            match_id,
            state,
            "manual_adjustment",
            player_id="player_1",
            payload={
                "reason": "reject non-waiting-room target",
                "requires_confirmation": True,
                "confirmed_by": "tester",
                "adjustments": [
                    {
                        "adjustment_type": "return_from_waiting_room",
                        "target_player_id": "player_1",
                        "target_card_instance_id": deck_card,
                    }
                ],
            },
        )


def test_manual_discard_card_rejects_non_hand_target(tmp_path):
    service, match_id = _create_match(tmp_path, seed=715)
    state = _reach_first_main(service, match_id)
    deck_card = state.players["player_1"].main_deck[0]

    with pytest.raises(IllegalActionError, match="target must be in hand"):
        _apply(
            service,
            match_id,
            state,
            "manual_adjustment",
            player_id="player_1",
            payload={
                "reason": "manual discard should only target hand",
                "requires_confirmation": True,
                "confirmed_by": "tester",
                "adjustments": [
                    {
                        "adjustment_type": "discard_card",
                        "target_player_id": "player_1",
                        "target_card_instance_id": deck_card,
                    }
                ],
            },
        )


def test_manual_energy_adjustment_supports_multiple_targets(tmp_path):
    service, match_id = _create_match(tmp_path, seed=19)
    state = _reach_first_main(service, match_id)
    energy_ids = state.players["player_1"].energy_area[:2]

    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
          "reason": "set multiple Energy to Wait",
          "adjustments": [
              {
                  "adjustment_type": "pay_energy",
                  "target_player_id": "player_1",
                  "target_card_instance_ids": energy_ids,
              }
          ],
        },
    )
    assert all(state.cards[item].orientation == "wait" for item in energy_ids)

    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
          "reason": "ready multiple Energy",
          "adjustments": [
              {
                  "adjustment_type": "ready_energy",
                  "target_player_id": "player_1",
                  "target_card_instance_ids": energy_ids,
              }
          ],
        },
    )
    assert all(state.cards[item].orientation == "active" for item in energy_ids)


def test_baton_touch_replaces_member_and_pays_only_cost_difference(tmp_path):
    service, match_id = _create_match(tmp_path, seed=121)
    state = _reach_first_main(service, match_id)
    player = state.players["player_1"]
    members = sorted(
        (
            instance_id
            for instance_id in player.main_deck
            if state.cards[instance_id].card.card_type == "member"
        ),
        key=lambda instance_id: state.cards[instance_id].card.cost or 0,
    )
    old_id, new_id = next(
        (old_id, new_id)
        for old_id in members
        for new_id in reversed(members)
        if (state.cards[old_id].card.cost or 0) <= len(player.energy_area)
        and (state.cards[new_id].card.cost or 0)
        > (state.cards[old_id].card.cost or 0)
        and (state.cards[new_id].card.cost or 0)
        - (state.cards[old_id].card.cost or 0)
        <= len(player.energy_area) + 1
    )
    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "prepare Baton Touch rule test",
            "adjustments": [
                {
                    "adjustment_type": "move_card",
                    "target_player_id": "player_1",
                    "target_card_instance_id": instance_id,
                    "to_zone": "hand",
                }
                for instance_id in (old_id, new_id)
            ],
        },
    )
    old_cost = state.cards[old_id].card.cost or 0
    state = _apply(
        service,
        match_id,
        state,
        "play_member",
        player_id="player_1",
        payload={
            "card_instance_id": old_id,
            "slot": "center",
            "use_baton_touch": False,
            "energy_instance_ids": state.players["player_1"].energy_area[:old_cost],
        },
    )
    with pytest.raises(IllegalActionError, match="outside the Stage this turn"):
        service.apply(
            match_id,
            ActionRequest(
                action_type="play_member",
                expected_revision=state.revision,
                player_id="player_1",
                payload={
                    "card_instance_id": new_id,
                    "slot": "center",
                    "use_baton_touch": True,
                    "energy_instance_ids": [],
                },
            ),
        )

    attached_member_id = next(
        instance_id
        for instance_id in state.players["player_1"].main_deck
        if state.cards[instance_id].card.card_type == "member"
        and instance_id not in {old_id, new_id}
    )
    attached_energy_id = state.players["player_1"].energy_area[0]
    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "prepare Baton Touch attachment cleanup",
            "adjustments": [
                {
                    "adjustment_type": "move_card",
                    "target_player_id": "player_1",
                    "target_card_instance_id": attached_member_id,
                    "to_zone": "hand",
                },
                {
                    "adjustment_type": "attach_card_under_member",
                    "target_player_id": "player_1",
                    "target_card_instance_id": attached_member_id,
                    "target_slot": "center",
                },
                {
                    "adjustment_type": "attach_card_under_member",
                    "target_player_id": "player_1",
                    "target_card_instance_id": attached_energy_id,
                    "target_slot": "center",
                },
            ],
        },
    )
    state = _complete_turn(service, match_id, state, set())
    state = _apply(service, match_id, state, "start_next_turn")
    for _ in range(3):
        state = _apply(
            service,
            match_id,
            state,
            "advance_phase",
            player_id="player_1",
        )
    assert state.phase == "first_main"
    assert state.players["player_1"].member_areas_entered_this_turn == []

    play_action = next(
        action
        for action in generate_legal_actions(state)
        if action.action_type == "play_member"
    )
    placement = next(
        item
        for item in play_action.options["placements"]
        if item["card_instance_id"] == new_id
        and item["slot"] == "center"
        and item["use_baton_touch"]
    )
    new_cost = state.cards[new_id].card.cost or 0
    assert placement["payment_cost"] == max(0, new_cost - old_cost)

    result = service.apply(
        match_id,
        ActionRequest(
            action_type="play_member",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "card_instance_id": new_id,
                "slot": "center",
                "use_baton_touch": True,
                "energy_instance_ids": state.players["player_1"].energy_area[
                    : placement["payment_cost"]
                ],
            },
        ),
    )
    state = result.state
    assert state.players["player_1"].member_area["center"] == new_id
    assert state.players["player_1"].member_area_attachments["center"] == []
    assert old_id in state.players["player_1"].waiting_room
    assert attached_member_id in state.players["player_1"].waiting_room
    assert attached_energy_id in state.players["player_1"].energy_deck
    assert sum(
        state.cards[instance_id].orientation == "wait"
        for instance_id in state.players["player_1"].energy_area
    ) == placement["payment_cost"]
    baton_event = next(
        event for event in result.events if event.event_type == "baton_touch_performed"
    )
    assert baton_event.data["replaced_card_instance_id"] == old_id
    assert baton_event.data["payment_cost"] == placement["payment_cost"]
    assert any(
        event.event_type == "stage_attachments_cleaned"
        for event in result.events
    )


def test_stage_attachments_support_member_and_energy_cards(tmp_path):
    service, match_id = _create_match(tmp_path, seed=122)
    state = _reach_first_main(service, match_id)
    player = state.players["player_1"]
    member_ids = [
        instance_id
        for instance_id in player.main_deck
        if state.cards[instance_id].card.card_type == "member"
    ][:2]
    top_id, attached_member_id = member_ids
    energy_id = player.energy_area[0]

    result = service.apply(
        match_id,
        ActionRequest(
            action_type="manual_adjustment",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "reason": "stage attachment rule test",
                "adjustments": [
                    {
                        "adjustment_type": "move_card",
                        "target_player_id": "player_1",
                        "target_card_instance_id": top_id,
                        "to_zone": "member_center",
                    },
                    {
                        "adjustment_type": "move_card",
                        "target_player_id": "player_1",
                        "target_card_instance_id": attached_member_id,
                        "to_zone": "hand",
                    },
                    {
                        "adjustment_type": "attach_card_under_member",
                        "target_player_id": "player_1",
                        "target_card_instance_id": attached_member_id,
                        "target_slot": "center",
                    },
                    {
                        "adjustment_type": "attach_card_under_member",
                        "target_player_id": "player_1",
                        "target_card_instance_id": energy_id,
                        "target_slot": "center",
                    },
                ],
            },
        ),
    )

    state = result.state
    assert state.players["player_1"].member_area["center"] == top_id
    assert state.players["player_1"].member_area_attachments["center"] == [
        attached_member_id,
        energy_id,
    ]
    assert energy_id not in state.players["player_1"].energy_area
    assert attached_member_id not in state.players["player_1"].hand
    assert sum(
        event.event_type == "card_attached_under_member"
        for event in result.events
    ) == 2
    assert service.repository.replay(match_id)["final_state"] == state.model_dump()


def test_attached_cards_move_out_with_type_specific_validation(tmp_path):
    service, match_id = _create_match(tmp_path, seed=123)
    state = _reach_first_main(service, match_id)
    player = state.players["player_1"]
    top_id, attached_member_id = [
        instance_id
        for instance_id in player.main_deck
        if state.cards[instance_id].card.card_type == "member"
    ][:2]
    energy_id = player.energy_area[0]
    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "prepare attached card movement",
            "adjustments": [
                {
                    "adjustment_type": "move_card",
                    "target_player_id": "player_1",
                    "target_card_instance_id": top_id,
                    "to_zone": "member_center",
                },
                {
                    "adjustment_type": "move_card",
                    "target_player_id": "player_1",
                    "target_card_instance_id": attached_member_id,
                    "to_zone": "hand",
                },
                {
                    "adjustment_type": "attach_card_under_member",
                    "target_player_id": "player_1",
                    "target_card_instance_id": attached_member_id,
                    "target_slot": "center",
                },
                {
                    "adjustment_type": "attach_card_under_member",
                    "target_player_id": "player_1",
                    "target_card_instance_id": energy_id,
                    "target_slot": "center",
                },
            ],
        },
    )

    with pytest.raises(IllegalActionError, match="requires orientation"):
        _apply(
            service,
            match_id,
            state,
            "manual_adjustment",
            player_id="player_1",
            payload={
                "reason": "invalid attached Energy movement",
                "adjustments": [
                    {
                        "adjustment_type": "move_attached_card",
                        "target_player_id": "player_1",
                        "target_card_instance_id": energy_id,
                        "to_zone": "energy_area",
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
            "reason": "move attached cards",
            "adjustments": [
                {
                    "adjustment_type": "move_attached_card",
                    "target_player_id": "player_1",
                    "target_card_instance_id": attached_member_id,
                    "to_zone": "member_left",
                },
                {
                    "adjustment_type": "move_attached_card",
                    "target_player_id": "player_1",
                    "target_card_instance_id": energy_id,
                    "to_zone": "energy_area",
                    "orientation": "wait",
                },
            ],
        },
    )

    assert state.players["player_1"].member_area["left"] == attached_member_id
    assert state.players["player_1"].member_area_attachments["center"] == []
    assert energy_id in state.players["player_1"].energy_area
    assert state.cards[energy_id].orientation == "wait"


def test_position_and_formation_change_move_complete_member_groups(tmp_path):
    service, match_id = _create_match(tmp_path, seed=124)
    state = _reach_first_main(service, match_id)
    player = state.players["player_1"]
    members = [
        instance_id
        for instance_id in player.main_deck
        if state.cards[instance_id].card.card_type == "member"
    ][:4]
    left_id, center_id, right_id, attached_id = members
    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "prepare Stage groups",
            "adjustments": [
                *[
                    {
                        "adjustment_type": "move_card",
                        "target_player_id": "player_1",
                        "target_card_instance_id": instance_id,
                        "to_zone": f"member_{slot}",
                    }
                    for slot, instance_id in (
                        ("left", left_id),
                        ("center", center_id),
                        ("right", right_id),
                    )
                ],
                {
                    "adjustment_type": "move_card",
                    "target_player_id": "player_1",
                    "target_card_instance_id": attached_id,
                    "to_zone": "hand",
                },
                {
                    "adjustment_type": "attach_card_under_member",
                    "target_player_id": "player_1",
                    "target_card_instance_id": attached_id,
                    "target_slot": "left",
                },
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
            "reason": "position change",
            "adjustments": [
                {
                    "adjustment_type": "position_change",
                    "target_player_id": "player_1",
                    "from_slot": "left",
                    "to_slot": "center",
                }
            ],
        },
    )
    assert state.players["player_1"].member_area["center"] == left_id
    assert state.players["player_1"].member_area["left"] == center_id
    assert state.players["player_1"].member_area_attachments["center"] == [
        attached_id
    ]
    assert state.players["player_1"].member_areas_moved_this_turn == [
        "center",
        "left",
    ]

    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "formation change",
            "adjustments": [
                {
                    "adjustment_type": "formation_change",
                    "target_player_id": "player_1",
                    "slot_assignments": {
                        "left": right_id,
                        "center": center_id,
                        "right": left_id,
                    },
                }
            ],
        },
    )
    assert state.players["player_1"].member_area == {
        "left": right_id,
        "center": center_id,
        "right": left_id,
    }
    assert state.players["player_1"].member_area_attachments["right"] == [
        attached_id
    ]
    assert state.players["player_1"].member_areas_moved_this_turn == [
        "center",
        "left",
        "right",
    ]


def test_move_member_accepts_only_top_stage_member_and_derives_source_slot(tmp_path):
    service, match_id = _create_match(tmp_path, seed=126)
    state = _reach_first_main(service, match_id)
    player = state.players["player_1"]
    stage_id, hand_id = [
        instance_id
        for instance_id in player.main_deck
        if state.cards[instance_id].card.card_type == "member"
    ][:2]
    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "prepare move_member",
            "adjustments": [
                {
                    "adjustment_type": "move_card",
                    "target_player_id": "player_1",
                    "target_card_instance_id": stage_id,
                    "to_zone": "member_left",
                },
                {
                    "adjustment_type": "move_card",
                    "target_player_id": "player_1",
                    "target_card_instance_id": hand_id,
                    "to_zone": "hand",
                },
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
            "reason": "move top Member",
            "adjustments": [
                {
                    "adjustment_type": "move_member",
                    "target_player_id": "player_1",
                    "target_card_instance_id": stage_id,
                    "to_slot": "right",
                }
            ],
        },
    )
    assert state.players["player_1"].member_area["left"] is None
    assert state.players["player_1"].member_area["right"] == stage_id
    assert state.players["player_1"].member_areas_moved_this_turn == ["right"]

    with pytest.raises(
        IllegalActionError,
        match="top Member currently on Stage",
    ):
        _apply(
            service,
            match_id,
            state,
            "manual_adjustment",
            player_id="player_1",
            payload={
                "reason": "reject hand Member",
                "adjustments": [
                    {
                        "adjustment_type": "move_member",
                        "target_player_id": "player_1",
                        "target_card_instance_id": hand_id,
                        "to_slot": "center",
                    }
                ],
            },
        )


def test_area_move_does_not_mark_member_area_as_entered_for_turn(tmp_path):
    service, match_id = _create_match(tmp_path, seed=127)
    state = _reach_first_main(service, match_id)
    player = state.players["player_1"]
    stage_id, hand_id = [
        instance_id
        for instance_id in player.main_deck
        if state.cards[instance_id].card.card_type == "member"
    ][:2]
    state = apply_action(
        state,
        ActionRequest(
            action_type="manual_adjustment",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "reason": "prepare existing Stage Member",
                "adjustments": [
                    {
                        "adjustment_type": "move_card",
                        "target_player_id": "player_1",
                        "target_card_instance_id": stage_id,
                        "to_zone": "member_left",
                    },
                    {
                        "adjustment_type": "move_card",
                        "target_player_id": "player_1",
                        "target_card_instance_id": hand_id,
                        "to_zone": "hand",
                    },
                ],
            },
        ),
    ).state
    state.players["player_1"].member_areas_entered_this_turn.clear()

    state = apply_action(
        state,
        ActionRequest(
            action_type="manual_adjustment",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "reason": "area move",
                "adjustments": [
                    {
                        "adjustment_type": "move_member",
                        "target_player_id": "player_1",
                        "target_card_instance_id": stage_id,
                        "to_slot": "right",
                    }
                ],
            },
        ),
    ).state

    assert state.players["player_1"].member_area["left"] is None
    assert state.players["player_1"].member_area["right"] == stage_id
    assert state.players["player_1"].member_areas_entered_this_turn == []
    assert state.players["player_1"].member_areas_moved_this_turn == ["right"]

    play_action = next(
        action
        for action in generate_legal_actions(state)
        if action.action_type == "play_member"
    )
    assert any(
        placement["card_instance_id"] == hand_id and placement["slot"] == "left"
        for placement in play_action.options["placements"]
    )


def test_top_member_departure_cleans_attached_member_and_energy(tmp_path):
    service, match_id = _create_match(tmp_path, seed=125)
    state = _reach_first_main(service, match_id)
    player = state.players["player_1"]
    top_id, attached_member_id = [
        instance_id
        for instance_id in player.main_deck
        if state.cards[instance_id].card.card_type == "member"
    ][:2]
    energy_id = player.energy_area[0]
    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "prepare Stage departure",
            "adjustments": [
                {
                    "adjustment_type": "move_card",
                    "target_player_id": "player_1",
                    "target_card_instance_id": top_id,
                    "to_zone": "member_center",
                },
                {
                    "adjustment_type": "move_card",
                    "target_player_id": "player_1",
                    "target_card_instance_id": attached_member_id,
                    "to_zone": "hand",
                },
                {
                    "adjustment_type": "attach_card_under_member",
                    "target_player_id": "player_1",
                    "target_card_instance_id": attached_member_id,
                    "target_slot": "center",
                },
                {
                    "adjustment_type": "attach_card_under_member",
                    "target_player_id": "player_1",
                    "target_card_instance_id": energy_id,
                    "target_slot": "center",
                },
            ],
        },
    )
    result = service.apply(
        match_id,
        ActionRequest(
            action_type="manual_adjustment",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "reason": "top Member leaves Stage",
                "adjustments": [
                    {
                        "adjustment_type": "move_card",
                        "target_player_id": "player_1",
                        "target_card_instance_id": top_id,
                        "to_zone": "waiting_room",
                    }
                ],
            },
        ),
    )
    state = result.state
    assert state.players["player_1"].member_area["center"] is None
    assert state.players["player_1"].member_area_attachments["center"] == []
    assert top_id in state.players["player_1"].waiting_room
    assert attached_member_id in state.players["player_1"].waiting_room
    assert energy_id in state.players["player_1"].energy_deck
    cleanup = next(
        event
        for event in result.events
        if event.event_type == "stage_attachments_cleaned"
    )
    assert cleanup.data["member_to_waiting_room_instance_ids"] == [
        attached_member_id
    ]
    assert cleanup.data["energy_to_energy_deck_instance_ids"] == [energy_id]


def test_stale_or_illegal_action_does_not_persist(tmp_path):
    service, match_id = _create_match(tmp_path, seed=5)
    before = service.repository.get_state(match_id)
    with closing(sqlite3.connect(service.repository.path)) as connection:
        before_action_count = connection.execute(
            "SELECT COUNT(*) FROM match_actions"
        ).fetchone()[0]
    with pytest.raises(StaleRevisionError):
        service.apply(
            match_id,
            ActionRequest(
                action_type="submit_mulligan",
                expected_revision=99,
                player_id="player_1",
                payload={"card_instance_ids": []},
            ),
        )
    with pytest.raises(IllegalActionError):
        service.apply(
            match_id,
            ActionRequest(
                action_type="advance_phase",
                expected_revision=before.revision,
            ),
        )
    after = service.repository.get_state(match_id)
    assert after == before
    with closing(sqlite3.connect(service.repository.path)) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM match_actions").fetchone()[0]
            == before_action_count
        )


def test_replay_reconstructs_current_state(tmp_path):
    service, match_id = _create_match(tmp_path, seed=77)
    state = service.repository.get_state(match_id)
    state = _apply(
        service,
        match_id,
        state,
        "submit_mulligan",
        player_id="player_1",
        payload={"card_instance_ids": []},
    )
    state = _apply(
        service,
        match_id,
        state,
        "submit_mulligan",
        player_id="player_2",
        payload={"card_instance_ids": []},
    )

    replay = service.repository.replay(match_id)

    assert replay["final_state"] == state.model_dump()
    assert len(replay["actions"]) == 3


def test_runtime_v2_snapshot_without_stage_attachments_uses_empty_defaults(tmp_path):
    service, match_id = _create_match(tmp_path, seed=78)
    state_data = service.repository.get_state(match_id).model_dump()
    for player in state_data["players"].values():
        player.pop("member_area_attachments")

    restored = MatchState.model_validate(state_data)

    assert restored.players["player_1"].member_area_attachments == {
        "left": [],
        "center": [],
        "right": [],
    }
    assert restored.players["player_2"].member_area_attachments == {
        "left": [],
        "center": [],
        "right": [],
    }


def test_live_set_draws_exactly_the_number_of_set_cards(tmp_path):
    service, match_id = _create_match(tmp_path, seed=808)
    state = _reach_live_set(service, match_id)
    player = state.players[state.first_player_id or ""]
    selected = player.hand[:3]
    before_hand = len(player.hand)

    result = service.apply(
        match_id,
        ActionRequest(
            action_type="set_live_cards",
            expected_revision=state.revision,
            player_id=player.player_id,
            payload={"card_instance_ids": selected},
        ),
    )

    assert len(result.state.players[player.player_id].hand) == before_hand
    drawn = next(event for event in result.events if event.event_type == "cards_drawn")
    assert drawn.data["reason"] == "live_set_replacement"
    assert len(drawn.data["instance_ids"]) == 3


def test_draw_refreshes_main_deck_deterministically_and_replays(tmp_path):
    service, match_id = _create_match(tmp_path, seed=909)
    state = _reach_first_main(service, match_id)
    player = state.players["player_1"]
    move_to_waiting = [
        {
            "adjustment_type": "move_card",
            "target_player_id": "player_1",
            "target_card_instance_id": instance_id,
            "to_zone": "waiting_room",
        }
        for instance_id in player.main_deck[1:]
    ]
    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "prepare deterministic refresh",
            "adjustments": move_to_waiting,
        },
    )
    result = service.apply(
        match_id,
        ActionRequest(
            action_type="manual_adjustment",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "reason": "draw across deck boundary",
                "adjustments": [
                    {
                        "adjustment_type": "draw_card",
                        "target_player_id": "player_1",
                        "amount": 2,
                    }
                ],
            },
        ),
    )

    refreshed = [
        event for event in result.events if event.event_type == "deck_refreshed"
    ]
    assert len(refreshed) == 1
    assert result.state.players["player_1"].refresh_count == 1
    assert all(
        not result.state.cards[instance_id].face_up
        for instance_id in result.state.players["player_1"].main_deck
    )
    assert service.repository.replay(match_id)["final_state"] == result.state.model_dump()


@pytest.mark.parametrize(
    ("successful_roles", "expected_role"),
    [
        (set(), "first"),
        ({"first"}, "first"),
        ({"second"}, "second"),
        ({"first", "second"}, "first"),
    ],
)
def test_next_first_player_rule(tmp_path, successful_roles, expected_role):
    service, match_id = _create_match(
        tmp_path,
        seed=1200 + len(successful_roles) * 10 + (1 if "second" in successful_roles else 0),
    )
    state = _reach_first_main(service, match_id)
    original_first = state.first_player_id
    original_second = state.second_player_id
    successful_players = {
        original_first if role == "first" else original_second
        for role in successful_roles
    }
    state = _complete_turn(service, match_id, state, successful_players)

    assert state.phase == "turn_complete"
    expected = original_first if expected_role == "first" else original_second
    assert state.next_first_player_id == expected


def test_third_success_live_wins_and_match_rejects_further_actions(tmp_path):
    service, match_id = _create_match(tmp_path, seed=1337)
    state = _reach_first_main(service, match_id)
    winner_id = state.first_player_id or ""
    state = _preload_success_lives(service, match_id, state, [winner_id], count=2)
    state = _complete_turn(service, match_id, state, {winner_id})

    assert state.phase == "complete"
    assert state.game_result is not None
    assert state.game_result.outcome == "win"
    assert state.game_result.winner_player_ids == [winner_id]
    assert _match_status(service, match_id) == "complete"
    with pytest.raises(IllegalActionError):
        _apply(service, match_id, state, "start_next_turn")


def test_simultaneous_third_success_live_is_a_draw(tmp_path):
    service, match_id = _create_match(tmp_path, seed=1441)
    state = _reach_first_main(service, match_id)
    players = {state.first_player_id or "", state.second_player_id or ""}
    state = _preload_success_lives(
        service,
        match_id,
        state,
        list(players),
        count=2,
    )
    state = _complete_turn(service, match_id, state, players)

    assert state.phase == "complete"
    assert state.game_result is not None
    assert state.game_result.outcome == "draw"
    assert state.game_result.winner_player_ids == []


def test_manual_modifier_durations_expire_at_live_turn_and_game_boundaries(tmp_path):
    service, match_id = _create_match(tmp_path, seed=1551)
    state = _reach_first_main(service, match_id)
    adjustments = []
    for duration in ("live", "turn", "game"):
        adjustments.append(
            {
                "adjustment_type": "modify_blade",
                "target_player_id": "player_1",
                "amount": 1,
                "duration": duration,
            }
        )
        adjustments.append(
            {
                "adjustment_type": "set_flag",
                "target_player_id": "player_1",
                "flag": f"{duration}_flag",
                "value": True,
                "duration": duration,
            }
        )
    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={"reason": "duration test", "adjustments": adjustments},
    )
    assert len(state.players["player_1"].manual_modifiers) == 6

    state = _complete_turn(service, match_id, state, set())
    remaining = state.players["player_1"].manual_modifiers
    assert {modifier.duration for modifier in remaining} == {"turn", "game"}

    state = _apply(service, match_id, state, "start_next_turn")
    remaining = state.players["player_1"].manual_modifiers
    assert {modifier.duration for modifier in remaining} == {"game"}


def test_runtime_v1_is_rejected_and_v2_initialization_is_idempotent(tmp_path):
    runtime_path = tmp_path / "runtime-v1.sqlite3"
    with closing(sqlite3.connect(runtime_path)) as connection:
        connection.execute(
            "CREATE TABLE runtime_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO runtime_metadata (key, value) VALUES ('schema_version', '1')"
        )
        connection.commit()
    with pytest.raises(RuntimeSchemaError, match="expected 2"):
        initialize_runtime_database(runtime_path)

    v2_path = tmp_path / "runtime-v2.sqlite3"
    initialize_runtime_database(v2_path)
    initialize_runtime_database(v2_path)
    with closing(sqlite3.connect(v2_path)) as connection:
        version = connection.execute(
            "SELECT value FROM runtime_metadata WHERE key = 'schema_version'"
        ).fetchone()[0]
    assert version == "2"


def test_runtime_prunes_old_completed_matches_with_cascading_records(tmp_path):
    runtime_path = tmp_path / "runtime-prune.sqlite3"
    initialize_runtime_database(runtime_path)
    with closing(sqlite3.connect(runtime_path)) as connection:
        for index in range(30):
            match_id = f"match-{index:02d}"
            timestamp = f"2026-06-15T00:{index:02d}:00+00:00"
            connection.execute(
                """
                INSERT INTO matches (
                    match_id,
                    card_database_path,
                    rule_version,
                    seed,
                    status,
                    revision,
                    initial_state_json,
                    current_state_json,
                    created_at,
                    updated_at
                )
                VALUES (?, 'cards.sqlite3', 'test', ?, 'complete', 0, '{}', '{}', ?, ?)
                """,
                (match_id, index, timestamp, timestamp),
            )
            connection.execute(
                """
                INSERT INTO match_actions (
                    match_id,
                    sequence,
                    action_id,
                    action_type,
                    payload_json,
                    expected_revision,
                    result_revision,
                    created_at
                )
                VALUES (?, 1, ?, 'test_action', '{}', 0, 1, ?)
                """,
                (match_id, f"action-{index:02d}", timestamp),
            )
            connection.execute(
                """
                INSERT INTO match_events (
                    match_id,
                    action_sequence,
                    event_index,
                    event_type,
                    event_json
                )
                VALUES (?, 1, 0, 'test_event', '{}')
                """,
                (match_id,),
            )
            connection.execute(
                """
                INSERT INTO match_snapshots (
                    match_id,
                    revision,
                    action_sequence,
                    state_json,
                    created_at
                )
                VALUES (?, 0, 0, '{}', ?)
                """,
                (match_id, timestamp),
            )
        connection.commit()

    repository = MatchRepository(runtime_path, active_match_ttl_hours=24 * 365 * 10)
    assert repository.prune_old_matches(max_matches=25) == 5
    assert [row["match_id"] for row in repository.list_matches()["items"]][0] == "match-29"

    with closing(sqlite3.connect(runtime_path)) as connection:
        for table in ("matches", "match_actions", "match_events", "match_snapshots"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 25
        oldest_remaining = connection.execute(
            "SELECT match_id FROM matches ORDER BY updated_at ASC LIMIT 1"
        ).fetchone()[0]
    assert oldest_remaining == "match-05"


def test_runtime_prune_keeps_active_and_hosted_room_matches(tmp_path):
    runtime_path = tmp_path / "runtime-prune-hosted.sqlite3"
    initialize_runtime_database(runtime_path)
    with closing(sqlite3.connect(runtime_path)) as connection:
        connection.executescript(
            """
            CREATE TABLE hosted_rooms (
                room_code TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                match_id TEXT
            );
            """
        )
        for index in range(32):
            match_id = f"match-{index:02d}"
            status = "active" if index == 0 else "complete"
            timestamp = f"2026-06-15T00:{index:02d}:00+00:00"
            connection.execute(
                """
                INSERT INTO matches (
                    match_id,
                    card_database_path,
                    rule_version,
                    seed,
                    status,
                    revision,
                    initial_state_json,
                    current_state_json,
                    created_at,
                    updated_at
                )
                VALUES (?, 'cards.sqlite3', 'test', ?, ?, 0, '{}', '{}', ?, ?)
                """,
                (match_id, index, status, timestamp, timestamp),
            )
        connection.execute(
            """
            INSERT INTO hosted_rooms (room_code, status, match_id)
            VALUES ('ABC123', 'active', 'match-01')
            """
        )
        connection.commit()

    repository = MatchRepository(runtime_path, active_match_ttl_hours=24 * 365 * 10)
    assert repository.prune_old_matches(max_matches=25) == 5

    with closing(sqlite3.connect(runtime_path)) as connection:
        remaining = {
            row[0]
            for row in connection.execute("SELECT match_id FROM matches").fetchall()
        }
    assert "match-00" in remaining
    assert "match-01" in remaining


def test_runtime_prune_removes_stale_unprotected_active_matches(tmp_path):
    runtime_path = tmp_path / "runtime-prune-stale-active.sqlite3"
    initialize_runtime_database(runtime_path)
    with closing(sqlite3.connect(runtime_path)) as connection:
        connection.executescript(
            """
            CREATE TABLE hosted_rooms (
                room_code TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                match_id TEXT
            );
            """
        )
        rows = [
            ("stale-open", "active", "2000-01-01T00:00:00+00:00"),
            ("recent-open", "active", "2099-01-01T00:00:00+00:00"),
            ("protected-open", "active", "2000-01-01T00:00:00+00:00"),
        ]
        for index, (match_id, status, timestamp) in enumerate(rows):
            connection.execute(
                """
                INSERT INTO matches (
                    match_id,
                    card_database_path,
                    rule_version,
                    seed,
                    status,
                    revision,
                    initial_state_json,
                    current_state_json,
                    created_at,
                    updated_at
                )
                VALUES (?, 'cards.sqlite3', 'test', ?, ?, 0, '{}', '{}', ?, ?)
                """,
                (match_id, index, status, timestamp, timestamp),
            )
        connection.execute(
            """
            INSERT INTO hosted_rooms (room_code, status, match_id)
            VALUES ('ABC123', 'active', 'protected-open')
            """
        )
        connection.commit()

    repository = MatchRepository(runtime_path)
    assert repository.prune_old_matches(max_matches=25) == 1

    with closing(sqlite3.connect(runtime_path)) as connection:
        remaining = {
            row[0]
            for row in connection.execute("SELECT match_id FROM matches").fetchall()
        }
    assert "stale-open" not in remaining
    assert "recent-open" in remaining
    assert "protected-open" in remaining


def test_runtime_prunes_snapshots_to_recent_revisions(tmp_path):
    runtime_path = tmp_path / "runtime-prune-snapshots.sqlite3"
    initialize_runtime_database(runtime_path)
    with closing(sqlite3.connect(runtime_path)) as connection:
        connection.execute(
            """
            INSERT INTO matches (
                match_id,
                card_database_path,
                rule_version,
                seed,
                status,
                revision,
                initial_state_json,
                current_state_json,
                created_at,
                updated_at
            )
            VALUES ('match-1', 'cards.sqlite3', 'test', 1, 'active', 5, '{}', '{}',
                    '2026-06-15T00:00:00+00:00', '2026-06-15T00:05:00+00:00')
            """
        )
        for revision in range(6):
            connection.execute(
                """
                INSERT INTO match_snapshots (
                    match_id,
                    revision,
                    action_sequence,
                    state_json,
                    created_at
                )
                VALUES ('match-1', ?, ?, '{}', '2026-06-15T00:00:00+00:00')
                """,
                (revision, revision),
            )
        connection.commit()

    repository = MatchRepository(runtime_path)
    assert repository.prune_snapshots(max_snapshots_per_match=3) == 3

    with closing(sqlite3.connect(runtime_path)) as connection:
        remaining = [
            row[0]
            for row in connection.execute(
                "SELECT revision FROM match_snapshots ORDER BY revision"
            ).fetchall()
        ]
    assert remaining == [3, 4, 5]


def test_runtime_keeps_only_recent_snapshots_after_actions(tmp_path):
    service, match_id = _create_match(tmp_path, seed=991)
    state = service.repository.get_state(match_id)
    for player_id in ("player_1", "player_2"):
        state = _apply(
            service,
            match_id,
            state,
            "submit_mulligan",
            player_id=player_id,
            payload={"card_instance_ids": []},
        )
    for _ in range(3):
        state = _apply(
            service,
            match_id,
            state,
            "advance_phase",
            player_id="player_1",
        )

    with closing(sqlite3.connect(tmp_path / "matches.sqlite3")) as connection:
        revisions = [
            row[0]
            for row in connection.execute(
                """
                SELECT revision
                FROM match_snapshots
                WHERE match_id = ?
                ORDER BY revision
                """,
                (match_id,),
            ).fetchall()
        ]
    assert len(revisions) == 3
    assert revisions == sorted(revisions)
    assert revisions[-1] == state.revision


def _create_match(tmp_path: Path, *, seed: int) -> tuple[MatchService, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    card_database = tmp_path / "cards.sqlite3"
    import_normalized_cards(card_database, SAMPLE_CARDS, NORMALIZATION)
    service = MatchService(card_database, tmp_path / "matches.sqlite3")
    result = service.create_match(
        first_name="先攻候補",
        first_deck=load_deck(SAMPLE_DECK),
        second_name="後攻候補",
        second_deck=load_deck(SAMPLE_DECK),
        seed=seed,
        match_id=f"match-{seed}",
        first_player_id="player_1",
    )
    return service, result.state.match_id


def _reach_first_main(service: MatchService, match_id: str):
    state = service.repository.get_state(match_id)
    for player_id in ("player_1", "player_2"):
        state = _apply(
            service,
            match_id,
            state,
            "submit_mulligan",
            player_id=player_id,
            payload={"card_instance_ids": []},
        )
    for _ in range(3):
        state = _apply(
            service,
            match_id,
            state,
            "advance_phase",
            player_id="player_1",
        )
    return state


def _reach_live_set(service: MatchService, match_id: str):
    state = _reach_first_main(service, match_id)
    state = _apply(
        service,
        match_id,
        state,
        "end_main_phase",
        player_id=state.first_player_id,
    )
    for _ in range(3):
        state = _apply(
            service,
            match_id,
            state,
            "advance_phase",
            player_id=state.second_player_id,
        )
    return _apply(
        service,
        match_id,
        state,
        "end_main_phase",
        player_id=state.second_player_id,
    )


def _flow_test_live_cards(
    state,
    player_id: str,
    *,
    count: int,
    require_hearts: bool = True,
) -> list[str]:
    live_ids = [
        instance_id
        for instance_id in state.players[player_id].main_deck
        if state.cards[instance_id].card.card_type == "live"
        and (not require_hearts or state.cards[instance_id].card.required_hearts)
        and not state.cards[instance_id].card.effect_ids
    ]
    assert len(live_ids) >= count
    return live_ids[:count]


def _preload_success_lives(
    service: MatchService,
    match_id: str,
    state,
    player_ids: list[str],
    *,
    count: int,
):
    adjustments = []
    for player_id in player_ids:
        live_ids = _flow_test_live_cards(
            state,
            player_id,
            count=count,
            require_hearts=False,
        )
        adjustments.extend(
            {
                "adjustment_type": "move_card",
                "target_player_id": player_id,
                "target_card_instance_id": instance_id,
                "to_zone": "success_live_area",
            }
            for instance_id in live_ids
        )
    return _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id=state.active_player_id,
        payload={"reason": "prepare success threshold", "adjustments": adjustments},
    )


def _complete_turn(
    service: MatchService,
    match_id: str,
    state,
    successful_player_ids: set[str],
):
    live_by_player: dict[str, str] = {}
    adjustments = []
    for player_id in successful_player_ids:
        live_id = _flow_test_live_cards(state, player_id, count=1)[0]
        live_by_player[player_id] = live_id
        adjustments.append(
            {
                "adjustment_type": "move_card",
                "target_player_id": player_id,
                "target_card_instance_id": live_id,
                "to_zone": "hand",
            }
        )
        for color in state.cards[live_id].card.required_hearts:
            adjustments.append(
                {
                    "adjustment_type": "modify_heart",
                    "target_player_id": player_id,
                    "color_slot": color,
                    "amount": 20,
                    "duration": "live",
                }
            )
    if len(live_by_player) == 2:
        target_score = max(
            state.cards[live_id].card.score or 0
            for live_id in live_by_player.values()
        )
        for player_id, live_id in live_by_player.items():
            score_delta = target_score - (state.cards[live_id].card.score or 0)
            if score_delta:
                adjustments.append(
                    {
                        "adjustment_type": "modify_score",
                        "target_player_id": player_id,
                        "amount": score_delta,
                        "duration": "live",
                    }
                )
    if adjustments:
        state = _apply(
            service,
            match_id,
            state,
            "manual_adjustment",
            player_id=state.active_player_id,
            payload={"reason": "prepare successful Live", "adjustments": adjustments},
        )

    state = _reach_live_set_from_first_main(service, match_id, state)
    for player_id in (state.first_player_id, state.second_player_id):
        selected = [live_by_player[player_id]] if player_id in live_by_player else []
        state = _apply(
            service,
            match_id,
            state,
            "set_live_cards",
            player_id=player_id,
            payload={"card_instance_ids": selected},
        )
    for player_id in (state.first_player_id, state.second_player_id):
        state = _apply(
            service,
            match_id,
            state,
            "advance_phase",
            player_id=player_id,
        )
        state = _apply(
            service,
            match_id,
            state,
            "advance_phase",
            player_id=player_id,
        )
        if state.pending_choice is not None:
            state = _apply(
                service,
                match_id,
                state,
                "resolve_live_requirements",
                player_id=player_id,
                payload={
                    "live_instance_ids": list(
                        state.pending_choice.options["live_instance_ids"]
                    )
                },
            )
    assert state.phase == "live_judgment"
    return _apply(
        service,
        match_id,
        state,
        "advance_phase",
    )


def _reach_live_set_from_first_main(service: MatchService, match_id: str, state):
    state = _apply(
        service,
        match_id,
        state,
        "end_main_phase",
        player_id=state.first_player_id,
    )
    for _ in range(3):
        state = _apply(
            service,
            match_id,
            state,
            "advance_phase",
            player_id=state.second_player_id,
        )
    return _apply(
        service,
        match_id,
        state,
        "end_main_phase",
        player_id=state.second_player_id,
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


def _match_status(service: MatchService, match_id: str) -> str:
    with closing(sqlite3.connect(service.repository.path)) as connection:
        return connection.execute(
            "SELECT status FROM matches WHERE match_id = ?",
            (match_id,),
        ).fetchone()[0]
