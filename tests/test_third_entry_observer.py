from contextlib import closing
from functools import lru_cache
from pathlib import Path

import pytest
from test_member_entry_area_history import _play
from test_member_entry_area_history import _state as base_state

from loveca.db.bootstrap import connect_database
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effects import EffectDefinition, EffectOperation, load_effect_registry
from loveca.simulation.engine import (
    IllegalActionError,
    StaleRevisionError,
    apply_action,
    generate_legal_actions,
)
from loveca.simulation.models import ActionRequest, EffectInvocation, MatchState
from loveca.simulation.online import match_state_hash

ACTUAL = "PL!N-bp3-005:1"
RULE_REFERENCE_IDS = ("9.7.2", "9.7.7", "10.4.1", "11.4.2")


@lru_cache
def _actual():
    effects = {
        e.effect_id: e for e in load_effect_registry().effects if e.card_code == "PL!N-bp3-005"
    }
    effect = effects[ACTUAL]
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        card = _load_definition(connection, effect.card_code, None, effects, {})
    return effect, card, effects


def _state(entry=3):
    state = base_state()
    effect, card, effects = _actual()
    state.effect_definitions.update(
        {key: item.model_copy(deep=True) for key, item in effects.items()}
    )
    state.cards["old"].card = card.model_copy(deep=True)
    state.member_overlap_policy = "capture_fixed_draw_and_energy_entry_observers"
    state.effect_order_policy = "ap_nap_player_choice"
    player = state.players["player_1"]
    player.member_entered_count_this_turn = entry - 1
    player.hand = ["entrant", "next"]
    for i in range(10):
        key = f"extra-deck-{i}"
        state.cards[key] = state.cards["deck-member-1"].model_copy(
            update={"instance_id": key}, deep=True
        )
        player.main_deck.append(key)
    return state


@pytest.mark.parametrize("entry", [1, 2, 3, 4, 5])
def test_only_the_actual_third_entry_draws_to_five(entry):
    result = _play(_state(entry), slot="left")
    assert len(result.state.players["player_1"].hand) == (5 if entry == 3 else 1)
    assert sum(
        e.event_type == "effect_triggered" and e.data["effect_id"] == ACTUAL for e in result.events
    ) == int(entry == 3)


def test_third_entry_observer_is_preserved_when_normally_replaced():
    result = _play(_state(), slot="center")
    assert "old" in result.state.players["player_1"].waiting_room
    assert len(result.state.players["player_1"].hand) == 5


def _resolve(state, effect_id, **payload):
    inv = next(i for i in state.pending_effects if i.effect_id == effect_id)
    return ActionRequest(
        action_type="resolve_effect",
        player_id=inv.player_id,
        expected_revision=state.revision,
        payload={"invocation_id": inv.invocation_id, "accepted": True, **payload},
    )


@pytest.mark.parametrize("entry", [3, 4])
def test_the_source_entering_at_third_but_not_later_triggers_itself(entry):
    state = _state(entry)
    state.cards["entrant"].card = _actual()[1].model_copy(deep=True)
    state.cards["old"].card.effect_ids = []
    for i in range(6, 15):
        key = f"energy-{i}"
        state.cards[key] = state.cards["energy-0"].model_copy(
            update={"instance_id": key}, deep=True
        )
        state.players["player_1"].energy_area.append(key)
    result = _play(state, slot="left")
    assert len(result.state.players["player_1"].hand) == (5 if entry == 3 else 1)


def test_baton_source_leaves_before_the_third_entry_and_does_not_observe_it():
    result = _play(_state(), slot="center", baton=True)
    assert len(result.state.players["player_1"].hand) == 1
    assert not any(
        e.event_type == "effect_triggered" and e.data["effect_id"] == ACTUAL for e in result.events
    )


@pytest.mark.parametrize("hand_size", [5, 7])
def test_draw_to_five_does_not_discard_or_draw_if_already_full(hand_size):
    state = _state()
    for _i in range(hand_size - 1):
        key = state.players["player_1"].main_deck.pop(0)
        state.players["player_1"].hand.append(key)
    result = _play(state, slot="center")
    assert len(result.state.players["player_1"].hand) == hand_size
    assert any(
        e.event_type == "effect_auto_resolved" and e.data["effect_id"] == ACTUAL
        for e in result.events
    )
    assert not any(e.event_type == "cards_drawn" for e in result.events)


def _with_extra_entry_effect(state, *, leave=False):
    from test_attachment_promotion import _trigger

    effect = _trigger("AUDIT-first:1", "own_member_played")
    effect.actions = [
        EffectOperation(
            action_type="source_to_waiting_room" if leave else "draw_card",
            amount=None if leave else 2,
        )
    ]
    state.effect_definitions[effect.effect_id] = effect
    state.cards["old"].card.effect_ids.append(effect.effect_id)
    return effect.effect_id


@pytest.mark.parametrize("leave", [False, True])
def test_pending_trigger_survives_source_departure_and_draws_only_current_deficit(leave):
    state = _state()
    first = _with_extra_entry_effect(state, leave=leave)
    state = _play(state, slot="left").state
    assert len(state.pending_effects) == 2
    inv = next(i for i in state.pending_effects if i.effect_id == ACTUAL)
    assert inv.trigger_data["member_entry_count_at_trigger"] == 3
    assert inv.trigger_data["source_stage_at_trigger"] is True
    result = apply_action(state, _resolve(state, first))
    assert not result.state.pending_effects
    assert len(result.state.players["player_1"].hand) == 5
    if leave:
        assert "old" in result.state.players["player_1"].waiting_room
    draws = [e for e in result.events if e.event_type == "cards_drawn"]
    assert sum(len(e.data["instance_ids"]) for e in draws) == 4


def _nested_deployment_state():
    from test_occupied_effect_deployment import ROOT
    from test_occupied_effect_deployment import _state as deployment_state

    state = _state()
    raw = deployment_state().effect_definitions[ROOT].model_dump()
    raw["cost"] = []
    effect = EffectDefinition.model_validate(raw)
    state.effect_definitions[ROOT] = effect
    state.cards["entrant"].card.effect_ids = [ROOT]
    state.cards["target"] = state.cards["next"].model_copy(
        update={"instance_id": "target"}, deep=True
    )
    state.players["player_1"].waiting_room.append("target")
    return state, ROOT


def test_fourth_entry_before_resolution_does_not_cancel_or_duplicate_the_third_trigger():
    state, parent = _nested_deployment_state()
    state = _play(state, slot="left").state
    assert len(state.pending_effects) == 2
    result = apply_action(
        state,
        _resolve(
            state,
            parent,
            selected_card_instance_ids=["target"],
            to_slot="right",
            energy_instance_ids=[],
        ),
    )
    assert result.state.players["player_1"].member_entered_count_this_turn == 4
    assert len(result.state.players["player_1"].hand) == 5
    assert (
        sum(
            e.event_type == "effect_auto_resolved" and e.data["effect_id"] == ACTUAL
            for e in result.events
        )
        == 1
    )
    assert not any(
        e.event_type == "effect_triggered" and e.data["effect_id"] == ACTUAL for e in result.events
    )
    assert not result.state.pending_effects


@pytest.mark.parametrize("occupied", [False, True])
def test_bounded_effect_entry_uses_actual_counter_and_full_source_definition(occupied):
    from test_occupied_effect_deployment import _request
    from test_occupied_effect_deployment import _state as deployment_state
    from test_overlap_energy_observer import _finish_pending

    state = deployment_state()
    effect, card, effects = _actual()
    state.effect_definitions.update({k: e.model_copy(deep=True) for k, e in effects.items()})
    state.cards["old"].card = card.model_copy(deep=True)
    state.member_overlap_policy = "capture_fixed_draw_and_energy_entry_observers"
    state.effect_order_policy = "ap_nap_player_choice"
    state.players["player_1"].member_entered_count_this_turn = 2
    if not occupied:
        player = state.players["player_1"]
        player.waiting_room.append("left-old")
        player.member_area.update(right=None, left="old")
        player.member_area_attachments["left"] = player.member_area_attachments["right"]
        player.member_area_attachments["right"] = []
    legal = next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect")
    assert (
        "right" in legal.options["invocations"][0]["position_change_slots_by_candidate"]["target"]
    )
    result = apply_action(state, _request(state))
    state = result.state
    followups = []
    while len(state.pending_effects) > 1:
        other = next(i for i in state.pending_effects if i.effect_id != ACTUAL)
        resolved = apply_action(state, _resolve(state, other.effect_id))
        state = resolved.state
        followups.extend(resolved.events)
    final, rest = _finish_pending(state)
    followups.extend(rest)
    assert len(final.players["player_1"].hand) == 5
    assert any(
        e.event_type == "effect_triggered" and e.data["effect_id"] == ACTUAL for e in result.events
    )
    assert not any(e.event_type == "effect_skipped_due_to_error" for e in followups)


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("entry", [3, 4])
@pytest.mark.parametrize("slot", ["left", "center"])
def test_actual_sql_replay_keeps_legacy_snapshot_behavior(tmp_path, legacy, entry, slot):
    from loveca.simulation.runtime import MatchRepository

    state = _state(entry)
    if legacy:
        raw = state.effect_definitions[ACTUAL].model_dump()
        raw["condition"] = {
            "source_zone": "stage",
            "own_member_entered_count_this_turn_at_least": 3,
        }
        state.effect_definitions[ACTUAL] = EffectDefinition.model_validate(raw)
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
                "slot": slot,
                "use_baton_touch": False,
                "energy_instance_ids": ["energy-0", "energy-1"],
            },
        ),
    )
    should_draw = slot == "left" if legacy else entry == 3
    assert len(result.state.players["player_1"].hand) == (5 if should_draw else 1)
    replay = repo.replay(state.match_id)
    assert replay["events"] == [e.model_dump(mode="json") for e in result.events]
    assert replay["final_state"] == result.state.model_dump(mode="json")
    assert match_state_hash(MatchState.model_validate(replay["final_state"])) == match_state_hash(
        result.state
    )


@pytest.mark.parametrize(
    "change", [{}, {"member_entry_count_at_trigger": 4, "source_stage_at_trigger": True}]
)
def test_missing_or_wrong_trigger_snapshot_is_rejected_atomically(change):
    state = _state()
    state.pending_effects = [
        EffectInvocation(
            invocation_id="wrong",
            effect_id=ACTUAL,
            source_card_instance_id="old",
            player_id="player_1",
            trigger_event="own_member_played",
            trigger_data=change,
        )
    ]
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalActionError, match="member_entry_trigger"):
        apply_action(state, _resolve(state, ACTUAL))
    assert state.model_dump(mode="json") == before


@pytest.mark.parametrize("bad", ["energy", "slot", "stale"])
def test_invalid_entry_never_records_a_counter_snapshot(bad):
    state = _state()
    before = state.model_dump(mode="json")
    with pytest.raises(StaleRevisionError if bad == "stale" else IllegalActionError):
        apply_action(
            state,
            ActionRequest(
                action_type="play_member",
                player_id="player_1",
                expected_revision=state.revision - int(bad == "stale"),
                payload={
                    "card_instance_id": "entrant",
                    "slot": "bad" if bad == "slot" else "center",
                    "use_baton_touch": False,
                    "energy_instance_ids": ["energy-0"] * 2
                    if bad == "energy"
                    else ["energy-0", "energy-1"],
                },
            ),
        )
    assert state.model_dump(mode="json") == before


def test_exact_candidate_keeps_text_identity_and_matches_executable_contract():
    from loveca.simulation.effect_candidates import discover_effect_candidates

    candidate = next(
        c
        for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
        if c.effect_id == ACTUAL
    )
    effect = _actual()[0]
    assert (
        candidate.condition
        == effect.condition
        == {"trigger_source_zone": "stage", "trigger_member_entry_count_exact": 3}
    )
    assert candidate.frequency_limit == effect.frequency_limit == "none"
    assert (
        candidate.raw_text_hash
        == effect.raw_text_hash
        == "703ce2e0b25a3031dc85ad756ffef21273d48f1d872d20c70cbe5037a1cb9e23"
    )
    assert candidate.text_revision_id == effect.text_revision_id == 477
    assert effect.label_ja in _actual()[1].raw_effect_text_ja


@pytest.mark.parametrize(
    "change",
    [
        {"trigger": "live_started"},
        {"is_optional": True},
        {"frequency_limit": "once_per_turn"},
        {"condition": {"trigger_source_zone": "stage", "trigger_member_entry_count_exact": True}},
        {"condition": {"trigger_source_zone": "hand", "trigger_member_entry_count_exact": 3}},
        {"condition": {"trigger_member_entry_count_exact": 3}},
        {"actions": [{"action_type": "gain_blade", "amount": 1}]},
    ],
)
def test_snapshot_contract_rejects_unreviewed_semantic_variants(change):
    with pytest.raises(ValueError):
        EffectDefinition.model_validate({**_actual()[0].model_dump(), **change})


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1"])
def test_native_ai_finishes_actual_pending_counter_without_private_information(policy):
    from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
    from loveca.webapp import _match_state_payload

    state = _state()
    _with_extra_entry_effect(state)
    state.cards["secret"] = state.cards["next"].model_copy(
        update={"instance_id": "secret", "owner_id": "player_2"}, deep=True
    )
    state.players["player_2"].hand = ["secret"]
    state = _play(state, slot="left").state
    assert len(state.pending_effects) == 2
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    events = []
    for _ in range(3):
        if not state.pending_effects:
            break
        legal = generate_legal_actions(state)
        decision = controller.choose_action(state, legal, controlled_player_ids={"player_1"})
        assert isinstance(decision, SimpleAIDecision)
        assert decision.action.action_type == "resolve_effect"
        changed = state.model_copy(deep=True)
        changed.cards["secret"].card.name_ja = "非公開変更"
        assert (
            controller.choose_action(
                changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}
            ).action
            == decision.action
        )
        result = apply_action(state, decision.action)
        state = result.state
        events.extend(result.events)
    assert not state.pending_effects
    assert len(state.players["player_1"].hand) in {5, 7}
    assert not any(e.event_type == "effect_skipped_due_to_error" for e in events)
    assert any(
        e.event_type in {"effect_auto_resolved", "effect_resolved"}
        and e.data["effect_id"] == ACTUAL
        for e in events
    )
    for viewer, other in [("player_1", "player_2"), ("player_2", "player_1")]:
        visible = _match_state_payload(
            state, events=events, legal_actions=generate_legal_actions(state), player_id=viewer
        )
        assert not set(state.players[other].hand) & set(visible["state"]["cards"])


def test_two_copies_share_the_third_event_but_do_not_overdraw():
    state = _state()
    state.cards["other-copy"] = state.cards["old"].model_copy(
        update={"instance_id": "other-copy"}, deep=True
    )
    state.players["player_1"].member_area["left"] = "other-copy"
    state = _play(state, slot="right").state
    assert len(state.pending_effects) == 2
    result = apply_action(state, _resolve(state, ACTUAL))
    assert not result.state.pending_effects
    assert len(result.state.players["player_1"].hand) == 5
    assert (
        sum(
            e.event_type in {"effect_auto_resolved", "effect_resolved"}
            and e.data["effect_id"] == ACTUAL
            for e in result.events
        )
        == 2
    )


def test_sql_replay_retains_third_trigger_snapshot_across_nested_fourth_entry(tmp_path):
    from loveca.simulation.runtime import MatchRepository

    state, parent = _nested_deployment_state()
    repo = MatchRepository(tmp_path / "nested.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    first = repo.apply(
        state.match_id,
        ActionRequest(
            action_type="play_member",
            player_id="player_1",
            expected_revision=state.revision,
            payload={
                "card_instance_id": "entrant",
                "slot": "left",
                "use_baton_touch": False,
                "energy_instance_ids": ["energy-0", "energy-1"],
            },
        ),
    )
    assert (
        next(i for i in first.state.pending_effects if i.effect_id == ACTUAL).trigger_data[
            "member_entry_count_at_trigger"
        ]
        == 3
    )
    second = repo.apply(
        state.match_id,
        _resolve(
            first.state,
            parent,
            selected_card_instance_ids=["target"],
            to_slot="right",
            energy_instance_ids=[],
        ),
    )
    assert second.state.players["player_1"].member_entered_count_this_turn == 4
    assert len(second.state.players["player_1"].hand) == 5
    replay = repo.replay(state.match_id)
    assert replay["events"] == [e.model_dump(mode="json") for e in [*first.events, *second.events]]
    assert replay["final_state"] == second.state.model_dump(mode="json")


@pytest.mark.parametrize("entries", [1, 2, 3, 4])
def test_separate_live_start_segment_still_means_at_least_two_entries(entries):
    state = _state()
    state.players["player_1"].member_entered_count_this_turn = entries
    effect_id = "PL!N-bp3-005:2"
    assert state.effect_definitions[effect_id].condition == {
        "own_member_entered_count_this_turn_at_least": 2
    }
    state.pending_effects = [
        EffectInvocation(
            invocation_id="live-start",
            effect_id=effect_id,
            source_card_instance_id="old",
            player_id="player_1",
            trigger_event="live_started",
        )
    ]
    if entries == 1:
        with pytest.raises(IllegalActionError, match="member_entered_count_this_turn_too_low"):
            apply_action(state, _resolve(state, effect_id))
    else:
        result = apply_action(state, _resolve(state, effect_id))
        assert (
            sum(
                m.amount or 0
                for m in result.state.players["player_1"].manual_modifiers
                if m.modifier_type == "score"
            )
            == 1
        )
