from contextlib import closing
from functools import lru_cache
from pathlib import Path

import pytest
from test_member_entry_area_history import _play
from test_overlap_entry_observer import _state as base_state

from loveca.db.bootstrap import connect_database
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effects import EffectDefinition, EffectOperation, load_effect_registry
from loveca.simulation.engine import (
    IllegalActionError,
    StaleRevisionError,
    apply_action,
    generate_legal_actions,
)
from loveca.simulation.models import ActionRequest, EffectUsage, MatchState
from loveca.simulation.online import match_state_hash

ACTUAL = "PL!N-pb1-012:1"
OLD_POLICY = "capture_fixed_draw_entry_observers"
POLICY = "capture_fixed_draw_and_energy_entry_observers"
RULE_REFERENCE_IDS = ("9.5.3", "9.7.2", "9.7.7", "10.4.1", "10.5.5")


@lru_cache
def _actual():
    effects = {
        e.effect_id: e for e in load_effect_registry().effects if e.card_code == "PL!N-pb1-012"
    }
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        card = _load_definition(connection, "PL!N-pb1-012", None, effects, {})
    return effects, card


def _state(*, policy=POLICY, effect=False, reserves=2, cost=11):
    state = base_state(cost=cost, effect=effect)
    effects, card = _actual()
    state.effect_definitions.update({k: e.model_copy(deep=True) for k, e in effects.items()})
    state.cards["old"].card = card.model_copy(deep=True)
    player = state.players["player_1"]
    assert not player.energy_deck
    for i in range(reserves):
        key = f"reserve-{i}"
        state.cards[key] = state.cards["energy-0"].model_copy(
            update={"instance_id": key, "face_up": False}, deep=True
        )
        player.energy_deck.append(key)
    raw = state.model_dump(mode="json")
    raw["member_overlap_policy"] = policy
    return MatchState.model_validate(raw)


def _finish_pending(state):
    all_events = []
    for _ in range(10):
        if not state.pending_effects:
            return state, all_events
        legal = next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect")
        invocation = legal.options["invocations"][0]
        result = apply_action(
            state,
            ActionRequest(
                action_type="resolve_effect",
                player_id=legal.player_id,
                expected_revision=state.revision,
                payload={"invocation_id": invocation["invocation_id"], "accepted": True},
            ),
        )
        state = result.state
        all_events.extend(result.events)
    pytest.fail("pending effects did not finish")


def test_actual_lanzhu_replacement_places_top_energy_in_wait_after_cleanup():
    state = _state()
    result = _play(state, slot="center")
    player = result.state.players["player_1"]
    assert player.energy_deck == ["reserve-1"]
    assert player.energy_area[-1] == "reserve-0"
    assert result.state.cards["reserve-0"].orientation == "wait"
    assert result.state.cards["reserve-0"].face_up
    assert "old" in player.waiting_room
    assert not result.state.pending_effects
    trigger = next(
        i
        for i, e in enumerate(result.events)
        if e.event_type == "effect_triggered" and e.data["effect_id"] == ACTUAL
    )
    cleanup = next(
        i for i, e in enumerate(result.events) if e.event_type == "duplicate_member_resolved"
    )
    energy = next(i for i, e in enumerate(result.events) if e.event_type == "energy_added")
    assert trigger < cleanup < energy
    assert result.events[energy].data["reason"] == f"effect:{ACTUAL}"


def test_returned_attachment_can_supply_energy_that_was_empty_at_entry():
    state = _state(reserves=0)
    player = state.players["player_1"]
    player.energy_area.remove("energy-0")
    player.member_area_attachments["center"] = ["energy-0"]
    # Retain enough Active Energy to pay the ordinary cost11 entry.
    state.cards["payment-extra"] = state.cards["energy-1"].model_copy(
        update={"instance_id": "payment-extra"}, deep=True
    )
    player.energy_area.append("payment-extra")
    result = _play(state, slot="center")
    assert "energy-0" in result.state.players["player_1"].energy_area
    assert result.state.cards["energy-0"].orientation == "wait"
    assert result.state.cards["energy-0"].face_up
    assert any(
        e.event_type == "energy_added" and e.data["reason"] == f"effect:{ACTUAL}"
        for e in result.events
    )


@pytest.mark.parametrize("policy", [None, OLD_POLICY, POLICY])
def test_snapshot_versions_keep_their_actual_runtime_replay_results(tmp_path, policy):
    from loveca.simulation.runtime import MatchRepository

    state = _state(policy=policy)
    initial = state.model_dump(mode="json")
    assert ("member_overlap_policy" in initial) is (policy is not None)
    assert MatchState.model_validate_json(state.model_dump_json()) == state
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repo.apply(
        state.match_id,
        ActionRequest(
            action_type="play_member",
            player_id="player_1",
            expected_revision=state.revision,
            payload={
                "card_instance_id": "entrant",
                "slot": "center",
                "use_baton_touch": False,
                "energy_instance_ids": [f"energy-{i}" for i in range(11)],
            },
        ),
    )
    replay = repo.replay(state.match_id)
    assert replay["final_state"] == result.state.model_dump(mode="json")
    assert replay["events"] == [e.model_dump(mode="json") for e in result.events]
    assert match_state_hash(MatchState.model_validate(replay["final_state"])) == match_state_hash(
        result.state
    )
    assert len(result.state.players["player_1"].energy_deck) == (1 if policy == POLICY else 2)
    assert state.model_dump(mode="json") == initial


def test_baton_removes_the_source_as_cost_before_the_new_member_enters():
    state = _state()
    result = _play(state, slot="center", baton=True)
    assert result.state.players["player_1"].energy_deck == ["reserve-0", "reserve-1"]
    assert not any(
        e.event_type == "effect_triggered" and e.data["effect_id"] == ACTUAL for e in result.events
    )


@pytest.mark.parametrize("cost", [2, 10, 12])
def test_entering_card_must_have_exact_cost11(cost):
    state = _state(cost=cost)
    result = _play(state, slot="center")
    assert result.state.players["player_1"].energy_deck == ["reserve-0", "reserve-1"]
    assert not any(
        e.event_type == "effect_triggered" and e.data["effect_id"] == ACTUAL for e in result.events
    )


def test_source_own_entry_does_not_trigger_but_another_copy_does():
    state = _state()
    state.cards["entrant"].card = _actual()[1].model_copy(deep=True)
    state.cards["old"].card.effect_ids = []
    self_entry = _play(state, slot="left")
    assert self_entry.state.players["player_1"].energy_deck == ["reserve-0", "reserve-1"]

    another = _state()
    another.cards["entrant"].card = _actual()[1].model_copy(deep=True)
    result = _play(another, slot="center")
    assert result.state.players["player_1"].energy_deck == ["reserve-1"]
    assert (
        len(
            [
                e
                for e in result.events
                if e.event_type == "effect_triggered" and e.data["effect_id"] == ACTUAL
            ]
        )
        == 1
    )


def test_once_per_turn_usage_survives_the_source_leaving_stage():
    state = _state()
    state.effect_usage.append(
        EffectUsage(
            effect_id=ACTUAL,
            source_card_instance_id="old",
            turn_number=state.turn_number,
        )
    )
    result = _play(state, slot="center")
    assert result.state.players["player_1"].energy_deck == ["reserve-0", "reserve-1"]
    assert not any(
        e.event_type == "effect_triggered" and e.data["effect_id"] == ACTUAL for e in result.events
    )


def test_empty_deck_resolves_with_an_explicit_non_error_result_without_refresh():
    state = _state(reserves=0)
    result = _play(state, slot="center")
    assert not result.state.pending_effects
    assert not any(
        e.event_type in {"energy_added", "deck_refreshed", "effect_skipped_due_to_error"}
        for e in result.events
    )
    assert any(
        e.event_type == "effect_operation_not_applied"
        and e.data["reason"] == "energy_deck_insufficient_at_resolution"
        for e in result.events
    )


def test_energy_can_be_consumed_by_the_first_chosen_effect_before_lanzhu_resolves():
    from test_attachment_promotion import _trigger

    state = _state(reserves=1)
    state.effect_order_policy = "ap_nap_player_choice"
    other = _trigger("AUDIT-energy-first:1", "member_played")
    other.actions = [
        EffectOperation(
            action_type="place_energy_from_deck", amount=1, target="self", orientation="wait"
        )
    ]
    state.effect_definitions[other.effect_id] = other
    state.cards["entrant"].card.effect_ids = [other.effect_id]
    state = _play(state, slot="center").state
    assert len(state.pending_effects) == 2
    assert state.players["player_1"].energy_deck == ["reserve-0"]
    selected = next(i for i in state.pending_effects if i.effect_id == other.effect_id)
    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            player_id="player_1",
            expected_revision=state.revision,
            payload={"invocation_id": selected.invocation_id, "accepted": True},
        ),
    )
    assert not result.state.pending_effects
    assert len([e for e in result.events if e.event_type == "energy_added"]) == 1
    assert any(
        e.event_type == "effect_operation_not_applied" and e.data["effect_id"] == ACTUAL
        for e in result.events
    )
    assert len([u for u in result.state.effect_usage if u.effect_id == ACTUAL]) == 1


@pytest.mark.parametrize("zone", ["hand", "waiting_room"])
def test_bounded_effect_entry_defers_energy_until_after_parent_and_keeps_top_order(zone):
    from test_occupied_effect_deployment import ROOT, _request

    state = _state(effect=True)
    if zone == "hand":
        player = state.players["player_1"]
        player.waiting_room.remove("target")
        player.hand.append("target")
        state.effect_definitions[ROOT].choice.zone = zone
    state.effect_order_policy = "ap_nap_player_choice"
    result = apply_action(state, _request(state))
    assert len(result.state.pending_effects) == 3
    assert not any(e.event_type == "energy_added" for e in result.events)
    assert result.state.players["player_1"].energy_deck == ["reserve-0", "reserve-1", "energy-3"]
    finished, events = _finish_pending(result.state)
    assert finished.players["player_1"].energy_deck == ["reserve-1", "energy-3"]
    assert finished.cards["reserve-0"].orientation == "wait"
    assert sum(e.event_type == "effect_cost_paid" for e in [*result.events, *events]) == 1
    assert "old" in finished.players["player_1"].waiting_room
    assert "target" in finished.players["player_1"].member_area.values()


@pytest.mark.parametrize(
    "payload",
    [
        {"energy_instance_ids": []},
        {"energy_instance_ids": ["energy-0"] * 11},
        {"slot": "missing"},
        {"card_instance_id": "old"},
        {"stale": True},
    ],
)
def test_invalid_entry_is_atomic_before_any_energy_observer_is_captured(payload):
    state = _state()
    initial = state.model_dump(mode="json")
    stale = payload.get("stale", False)
    supplied = {key: value for key, value in payload.items() if key != "stale"}
    with pytest.raises(StaleRevisionError if stale else IllegalActionError):
        apply_action(
            state,
            ActionRequest(
                action_type="play_member",
                player_id="player_1",
                expected_revision=state.revision - int(stale),
                payload={
                    "card_instance_id": "entrant",
                    "slot": "center",
                    "use_baton_touch": False,
                    "energy_instance_ids": [f"energy-{i}" for i in range(11)],
                    **supplied,
                },
            ),
        )
    assert state.model_dump(mode="json") == initial


@pytest.mark.parametrize(
    "change",
    [
        {"condition": {"source_slot": "center"}},
        {
            "actions": [
                {
                    "action_type": "place_energy_from_deck",
                    "target": "opponent",
                    "amount": 1,
                    "orientation": "wait",
                }
            ]
        },
        {
            "actions": [
                {"action_type": "place_energy_from_deck", "amount": 2, "orientation": "wait"}
            ]
        },
        {
            "actions": [
                {"action_type": "place_energy_from_deck", "amount": 1, "orientation": "active"}
            ]
        },
    ],
)
def test_complex_or_different_energy_observers_remain_guarded(change):
    from loveca.simulation.engine import _effect_deployment_slots

    state = _state(effect=True)
    state.effect_definitions[ACTUAL] = EffectDefinition.model_validate(
        {
            **state.effect_definitions[ACTUAL].model_dump(),
            **change,
        }
    )
    assert "right" not in _effect_deployment_slots(state, state.pending_effects[0], "target")


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1"])
def test_ai_uses_native_resolution_and_private_identity_does_not_change_actions(policy):
    from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
    from loveca.webapp import _match_state_payload

    state = _state(effect=True)
    state.effect_order_policy = "ap_nap_player_choice"
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    initial = controller.choose_action(
        state, generate_legal_actions(state), controlled_player_ids={"player_1"}
    )
    assert isinstance(initial, SimpleAIDecision)
    changed = state.model_copy(deep=True)
    changed.cards["opponent-private"].card.card_code = "PRIVATE-CHANGED"
    assert (
        controller.choose_action(
            changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}
        ).action
        == initial.action
    )
    all_events = []
    for _ in range(10):
        if not state.pending_effects:
            break
        decision = controller.choose_action(
            state, generate_legal_actions(state), controlled_player_ids={"player_1"}
        )
        assert (
            isinstance(decision, SimpleAIDecision)
            and decision.action.action_type == "resolve_effect"
        )
        result = apply_action(state, decision.action)
        state = result.state
        all_events.extend(result.events)
    assert not state.pending_effects and state.players["player_1"].energy_deck == [
        "reserve-1",
        "energy-3",
    ]
    assert not any(e.event_type == "effect_skipped_due_to_error" for e in all_events)
    for viewer, other in [("player_1", "player_2"), ("player_2", "player_1")]:
        visible = _match_state_payload(
            state, events=all_events, legal_actions=generate_legal_actions(state), player_id=viewer
        )
        assert not set(state.players[other].hand) & set(visible["state"]["cards"])


def test_actual_identity_text_and_support_status_are_not_modified():
    effects, card = _actual()
    actual = effects[ACTUAL]
    assert actual.text_revision_id == card.text_revision_id == 319
    assert (
        actual.raw_text_hash
        == card.raw_text_hash
        == "aa2d2e25f4d9eb9741b0f26ae21790d8db8aa87b9849686b4804d2976d5f73ca"
    )
    assert (
        actual.simulation_support == "test_validated_executable"
        and actual.review_status == "test_validated"
    )
    assert len(effects) == 2 and effects["PL!N-pb1-012:2"].trigger == "live_succeeded"


def test_second_player_replacement_uses_the_same_wait_energy_capture():
    state = _state()
    first, second = state.players["player_1"], state.players["player_2"]
    first.player_id, second.player_id = "player_2", "player_1"
    state.players = {"player_1": second, "player_2": first}
    for card in state.cards.values():
        card.owner_id = "player_2" if card.owner_id == "player_1" else "player_1"
    state.first_player_id, state.second_player_id = "player_2", "player_1"
    state.active_player_id = "player_2"
    result = apply_action(
        state,
        ActionRequest(
            action_type="play_member",
            player_id="player_2",
            expected_revision=state.revision,
            payload={
                "card_instance_id": "entrant",
                "slot": "center",
                "use_baton_touch": False,
                "energy_instance_ids": [f"energy-{i}" for i in range(11)],
            },
        ),
    )
    assert result.state.players["player_2"].energy_deck == ["reserve-1"]
    assert result.state.cards["reserve-0"].orientation == "wait"


@pytest.mark.parametrize("policy", [OLD_POLICY, POLICY])
def test_observer_remaining_on_stage_keeps_the_existing_energy_behavior(policy):
    result = _play(_state(policy=policy), slot="left")
    assert result.state.players["player_1"].member_area["center"] == "old"
    assert result.state.players["player_1"].energy_deck == ["reserve-1"]
    assert result.state.cards["reserve-0"].orientation == "wait"


def test_latest_policy_preserves_the_previous_fixed_draw_family():
    state = base_state()
    state.member_overlap_policy = POLICY
    result = _play(state, slot="center")
    assert len(result.state.players["player_1"].hand) == 3


def test_parent_cost_and_ordered_energy_followups_survive_runtime_replay(tmp_path):
    from loveca.simulation.runtime import MatchRepository
    from test_occupied_effect_deployment import _request

    state = _state(effect=True)
    state.effect_order_policy = "ap_nap_player_choice"
    repo = MatchRepository(tmp_path / "ordered-runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repo.apply(state.match_id, _request(state))
    all_events = list(result.events)
    assert not any(e.event_type == "energy_added" for e in all_events)
    for _ in range(10):
        current = result.state
        if not current.pending_effects:
            break
        legal = next(
            a for a in generate_legal_actions(current) if a.action_type == "resolve_effect"
        )
        result = repo.apply(
            current.match_id,
            ActionRequest(
                action_type="resolve_effect",
                player_id=legal.player_id,
                expected_revision=current.revision,
                payload={
                    "invocation_id": legal.options["invocations"][0]["invocation_id"],
                    "accepted": True,
                },
            ),
        )
        all_events.extend(result.events)
    assert not result.state.pending_effects
    assert result.state.players["player_1"].energy_deck == ["reserve-1", "energy-3"]
    replay = repo.replay(state.match_id)
    assert replay["final_state"] == result.state.model_dump(mode="json")
    assert replay["events"] == [e.model_dump(mode="json") for e in all_events]
    assert sum(e.event_type == "effect_cost_paid" for e in all_events) == 1
