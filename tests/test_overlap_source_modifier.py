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

ACTUAL = "PL!HS-pb1-009:1"
FIELD = "overlap_source_policy"
POLICY = "original_stage_member"
RULE_REFERENCE_IDS = ("4.1.4", "9.7.4.1.2", "9.7.7", "10.4.1", "11.7.3")


@lru_cache
def _actual():
    effects = {
        e.effect_id: e for e in load_effect_registry().effects if e.card_code == "PL!HS-pb1-009"
    }
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        card = _load_definition(connection, "PL!HS-pb1-009", None, effects, {})
    return effects, card


def _state(*, legacy=False):
    state = base_state()
    effects, card = _actual()
    state.effect_definitions.update({k: e.model_copy(deep=True) for k, e in effects.items()})
    state.cards["old"].card = card.model_copy(deep=True)
    state.cards["entrant"].card.work_keys = ["hasunosora"]
    state.member_overlap_policy = "capture_fixed_draw_and_energy_entry_observers"
    state.effect_order_policy = "ap_nap_player_choice"
    if legacy:
        raw = state.effect_definitions[ACTUAL].model_dump()
        raw["actions"][0].pop(FIELD, None)
        state.effect_definitions[ACTUAL] = EffectDefinition.model_validate(raw)
    return state


def test_center_observer_triggers_before_replacement_but_does_not_buff_departed_source():
    result = _play(_state(), slot="center")
    assert any(
        e.event_type == "effect_triggered" and e.data["effect_id"] == ACTUAL for e in result.events
    )
    assert any(
        e.event_type == "effect_operation_not_applied"
        and e.data["reason"] == "overlap_source_member_departed"
        for e in result.events
    )
    assert not any(
        m.target_card_instance_id == "old"
        for m in result.state.players["player_1"].manual_modifiers
    )
    assert len([u for u in result.state.effect_usage if u.effect_id == ACTUAL]) == 1
    assert not result.state.pending_effects


def test_center_observer_that_stays_on_stage_still_gains_two_blade():
    result = _play(_state(), slot="left")
    assert (
        sum(
            m.amount or 0
            for m in result.state.players["player_1"].manual_modifiers
            if m.target_card_instance_id == "old" and m.modifier_type == "blade"
        )
        == 2
    )


def _resolve(state, effect_id, **payload):
    inv = next(i for i in state.pending_effects if i.effect_id == effect_id)
    return ActionRequest(
        action_type="resolve_effect",
        player_id=inv.player_id,
        expected_revision=state.revision,
        payload={"invocation_id": inv.invocation_id, "accepted": True, **payload},
    )


def test_original_center_object_does_not_regain_the_bonus_after_same_id_returns():
    from test_occupied_effect_deployment import ROOT
    from test_occupied_effect_deployment import _state as deployment_state

    state = _state()
    raw = deployment_state().effect_definitions[ROOT].model_dump()
    raw.update(effect_id="AUDIT-return-source:1", cost=[], execution_mode="prompt_then_resolve")
    raw["choice"]["maximum_cost"] = 30
    returning = EffectDefinition.model_validate(raw)
    state.effect_definitions[returning.effect_id] = returning
    state.cards["entrant"].card.effect_ids = [returning.effect_id]
    state = _play(state, slot="center").state
    assert len(state.pending_effects) == 2
    captured = next(i for i in state.pending_effects if i.effect_id == ACTUAL)
    assert captured.trigger_data["overlap_source_slot_at_trigger"] == "center"
    result = apply_action(
        state,
        _resolve(
            state,
            returning.effect_id,
            selected_card_instance_ids=["old"],
            to_slot="left",
            energy_instance_ids=[],
        ),
    )
    assert result.state.players["player_1"].member_area["left"] == "old"
    assert not result.state.pending_effects
    assert not any(
        m.target_card_instance_id == "old"
        for m in result.state.players["player_1"].manual_modifiers
    )
    assert any(
        e.event_type == "effect_operation_not_applied" and e.data.get("effect_id") == ACTUAL
        for e in result.events
    )


def test_its_own_center_entry_gains_blade_without_being_treated_as_outgoing():
    state = _state()
    state.cards["entrant"].card = _actual()[1].model_copy(deep=True)
    state.cards["old"].card.effect_ids = []
    for i in range(10, state.cards["entrant"].card.cost):
        key = f"energy-{i}"
        state.cards[key] = state.cards["energy-0"].model_copy(
            update={"instance_id": key}, deep=True
        )
        state.players["player_1"].energy_area.append(key)
    result = _play(state, slot="center")
    assert (
        sum(
            m.amount or 0
            for m in result.state.players["player_1"].manual_modifiers
            if m.target_card_instance_id == "entrant" and m.modifier_type == "blade"
        )
        == 2
    )
    assert not any(e.data.get("reason") == "overlap_source_member_departed" for e in result.events)


@pytest.mark.parametrize("slot", ["left", "right"])
def test_side_source_is_not_a_center_observer(slot):
    state = _state()
    state.players["player_1"].member_area.update(center=None)
    state.players["player_1"].member_area[slot] = "old"
    result = _play(state, slot="center")
    assert not any(
        e.event_type == "effect_triggered" and e.data["effect_id"] == ACTUAL for e in result.events
    )
    assert not result.state.players["player_1"].manual_modifiers


def test_non_hasunosora_entry_and_baton_do_not_trigger_the_departed_observer():
    state = _state()
    state.cards["entrant"].card.work_keys = ["nijigasaki"]
    for initial, baton in [(state, False), (_state(), True)]:
        result = _play(initial, slot="center", baton=baton)
        assert not any(
            e.event_type == "effect_triggered" and e.data["effect_id"] == ACTUAL
            for e in result.events
        )


@pytest.mark.parametrize("used", [0, 1, 2])
def test_twice_per_turn_limit_is_consumed_even_when_the_old_target_is_gone(used):
    state = _state()
    state.effect_usage.extend(
        EffectUsage(effect_id=ACTUAL, source_card_instance_id="old", turn_number=state.turn_number)
        for _ in range(used)
    )
    result = _play(state, slot="center")
    actual_usage = [u for u in result.state.effect_usage if u.effect_id == ACTUAL]
    assert len(actual_usage) == min(used + 1, 2)
    assert not any(
        m.target_card_instance_id == "old"
        for m in result.state.players["player_1"].manual_modifiers
    )


@pytest.mark.parametrize("legacy", [False, True])
def test_actual_sql_replay_preserves_new_and_legacy_effect_snapshot_shapes(tmp_path, legacy):
    from loveca.simulation.runtime import MatchRepository

    state = _state(legacy=legacy)
    raw = state.model_dump(mode="json")
    assert (FIELD in raw["effect_definitions"][ACTUAL]["actions"][0]) is not legacy
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
                "energy_instance_ids": [f"energy-{i}" for i in range(10)],
            },
        ),
    )
    replay = repo.replay(state.match_id)
    assert replay["final_state"] == result.state.model_dump(mode="json")
    assert replay["events"] == [e.model_dump(mode="json") for e in result.events]
    assert match_state_hash(MatchState.model_validate(replay["final_state"])) == match_state_hash(
        result.state
    )
    assert (
        any(e.data.get("reason") == "overlap_source_member_departed" for e in result.events)
        is not legacy
    )
    assert state.model_dump(mode="json") == raw


@pytest.mark.parametrize(
    "payload,stale",
    [
        ({"energy_instance_ids": []}, False),
        ({"energy_instance_ids": ["energy-0"] * 10}, False),
        ({"slot": "missing"}, False),
        ({}, True),
    ],
)
def test_invalid_entry_is_atomic_before_source_slot_capture(payload, stale):
    state = _state()
    before = state.model_dump(mode="json")
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
                    "energy_instance_ids": [f"energy-{i}" for i in range(10)],
                    **payload,
                },
            ),
        )
    assert state.model_dump(mode="json") == before


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1"])
def test_ai_finishes_captured_modifier_and_keeps_opponent_hand_private(policy):
    from test_attachment_promotion import _trigger

    from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
    from loveca.webapp import _match_state_payload

    state = _state()
    draw = _trigger("AUDIT-entry-draw:1", "member_played")
    state.effect_definitions[draw.effect_id] = draw
    state.cards["entrant"].card.effect_ids = [draw.effect_id]
    state.cards["private"] = state.cards["entrant"].model_copy(
        update={"instance_id": "private", "owner_id": "player_2"}, deep=True
    )
    state.players["player_2"].hand = ["private"]
    state = _play(state, slot="center").state
    assert len(state.pending_effects) == 2
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    decision = controller.choose_action(
        state, generate_legal_actions(state), controlled_player_ids={"player_1"}
    )
    assert (
        isinstance(decision, SimpleAIDecision) and decision.action.action_type == "resolve_effect"
    )
    changed = state.model_copy(deep=True)
    changed.cards["private"].card.name_ja = "非公開変更"
    assert (
        controller.choose_action(
            changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}
        ).action
        == decision.action
    )
    result = apply_action(state, decision.action)
    assert not result.state.pending_effects
    assert not any(
        m.target_card_instance_id == "old"
        for m in result.state.players["player_1"].manual_modifiers
    )
    assert not any(e.event_type == "effect_skipped_due_to_error" for e in result.events)
    for viewer, other in [("player_1", "player_2"), ("player_2", "player_1")]:
        visible = _match_state_payload(
            result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer
        )
        assert not set(result.state.players[other].hand) & set(visible["state"]["cards"])


@pytest.mark.parametrize(
    "change",
    [
        {"action_type": "draw_card"},
        {"target": "selected"},
        {"amount": 0},
        {"amount_source": "own_stage_member_count"},
        {"branch": "other"},
    ],
)
def test_operation_policy_is_not_a_generic_target_identity_override(change):
    with pytest.raises(ValueError):
        EffectOperation.model_validate(
            {"action_type": "gain_blade", "amount": 2, FIELD: POLICY, **change}
        )


@pytest.mark.parametrize(
    "change",
    [
        {"duration": "turn"},
        {"trigger": "live_started"},
        {"condition": {"source_slot": {}}},
        {"condition": {"source_slot": "center", "own_stage_member_count": 3}},
    ],
)
def test_effect_policy_rejects_other_timing_duration_and_conditions(change):
    with pytest.raises(ValueError):
        EffectDefinition.model_validate({**_actual()[0][ACTUAL].model_dump(), **change})


def test_exact_candidate_and_registry_share_identity_and_snapshot_policy():
    from loveca.simulation.effect_candidates import discover_effect_candidates

    registered = _actual()[0][ACTUAL]
    candidate = next(
        c
        for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
        if c.effect_id == ACTUAL
    )
    assert (
        candidate.raw_text_hash
        == registered.raw_text_hash
        == "38e3fc157108b2f0049174a08fa2cbf15180ac5809f99365e76087ef4a228613"
    )
    assert candidate.text_revision_id == registered.text_revision_id == 125
    assert candidate.actions[0][FIELD] == registered.actions[0].overlap_source_policy == POLICY
    assert (
        registered.simulation_support == "test_validated_executable"
        and registered.review_status == "test_validated"
    )
    assert FIELD not in EffectOperation(action_type="draw_card", amount=1).model_dump()


def test_effect_replacement_uses_original_center_position_after_parent_finishes():
    from test_occupied_effect_deployment import _request
    from test_overlap_energy_observer import _finish_pending

    state = base_state(effect=True)
    effects, card = _actual()
    state.effect_definitions.update({k: e.model_copy(deep=True) for k, e in effects.items()})
    state.cards["old"].card = card.model_copy(deep=True)
    state.cards["target"].card.work_keys = ["hasunosora"]
    player = state.players["player_1"]
    # The AUDIT parent was already triggered; move it out of the test area first.
    player.member_area.update(center="old", right=None)
    player.waiting_room.append("source-live")
    player.member_area_attachments["center"] = player.member_area_attachments["right"]
    player.member_area_attachments["right"] = []
    state.member_overlap_policy = "capture_fixed_draw_and_energy_entry_observers"
    state.effect_order_policy = "ap_nap_player_choice"
    result = apply_action(state, _request(state, to_slot="center"))
    assert result.state.pending_effects
    assert not any(e.data.get("reason") == "overlap_source_member_departed" for e in result.events)
    finished, followups = _finish_pending(result.state)
    assert any(e.data.get("reason") == "overlap_source_member_departed" for e in followups)
    assert not any(
        m.target_card_instance_id == "old" for m in finished.players["player_1"].manual_modifiers
    )


def test_source_policy_cannot_be_put_into_an_effect_cost():
    raw = _actual()[0][ACTUAL].model_dump()
    raw["cost"] = raw["actions"]
    raw["actions"] = [{"action_type": "draw_card", "amount": 1}]
    with pytest.raises(ValueError, match="cost"):
        EffectDefinition.model_validate(raw)


def test_old_unrelated_live_start_snapshot_keeps_its_original_overlap_guard():
    from loveca.simulation.engine import _occupied_deployment_gaps
    from loveca.simulation.models import EffectInvocation

    state = _state()
    state.cards["old"].card.effect_ids = ["PL!HS-pb1-009:2"]
    invocation = EffectInvocation(
        invocation_id="AUDIT",
        effect_id=ACTUAL,
        source_card_instance_id="old",
        player_id="player_1",
        trigger_event="member_played",
    )
    assert _occupied_deployment_gaps(state, invocation, "entrant")["center"] == (
        "outgoing_effect_requires_overlap_timing_review"
    )
    state.cards["old"].card.effect_ids.insert(0, ACTUAL)
    assert "center" not in _occupied_deployment_gaps(state, invocation, "entrant")
