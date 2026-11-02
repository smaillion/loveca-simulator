import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_moved_source_ready import _manual
from test_nijigasaki_inspection import _candidate, _resolve
from test_nijigasaki_inspection import _state as _base_state

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, _member_heart_count, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, EffectInvocation
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!S-bp7-015"
EFFECT = CODE + ":1"
RULE_REFERENCE_IDS = ("4.1.4", "4.8.2", "4.8.3", "9.7.7", "10.2.2.1", "10.2.3", "8.4.11")


def _state(*, bottom_type="live", legacy=False):
    state = _base_state(CODE, legacy=legacy)
    if not legacy:
        state.effect_definitions[EFFECT] = EffectDefinition.model_validate(_candidate(CODE).to_registry_entry())
    else:
        raw = state.effect_definitions[EFFECT].model_dump(mode="json")
        raw.update(actions=[{"action_type": "manual_resolution"}], review_status="parsed_draft",
                   source_reference="Official card text; timing-only manual fallback pending structured effect modeling")
        state.effect_definitions[EFFECT] = EffectDefinition.model_validate(raw)
    player = state.players["player_1"]
    player.hand.remove("source-live")
    player.member_area["center"] = "source-live"
    player.main_deck = ["good-member", "tail", "good-live"]
    player.live_area = ["deck-live-1"]
    state.cards["good-live"].card.card_type = bottom_type
    state.phase = "performance_first"
    state.stage_departure_policy = "clear_departed_card_modifiers"
    state.effect_order_policy = "ap_nap_player_choice"
    return state


def _advance(state):
    return ActionRequest(action_type="advance_phase", player_id="player_1", expected_revision=state.revision)


def _begin(state):
    return apply_action(state, _advance(state))


def _event(result):
    return next(e for e in result.events if e.event_type == "effect_bottom_live_heart_resolved")


def test_native_live_start_moves_bottom_and_grants_only_source_heart():
    state = _state()
    before = match_state_hash(state)
    result = _begin(state)
    assert match_state_hash(state) == before
    assert _event(result).data["heart_delta"] == 1
    assert result.state.players["player_1"].waiting_room == ["good-live"]
    assert result.state.players["player_1"].main_deck == ["good-member", "tail"]
    assert _member_heart_count(result.state, "player_1", "source-live", "heart02") == 1
    assert not result.state.pending_effects and result.state.pending_choice is None


def _pending(**kwargs):
    state = _state(**kwargs)
    state.pending_effects = [EffectInvocation(
        invocation_id="isolated-live-start", effect_id=EFFECT, source_card_instance_id="source-live",
        player_id="player_1", trigger_event="live_started",
        trigger_data={"original_source_stage_object": True, "_condition_checked_at_trigger": True},
    )]
    return state


def _control_state():
    state = _state()
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id="CONTROL", frequency_limit="none", execution_mode="manual_resolution",
               simulation_support="manual_resolution", actions=[{"action_type": "manual_resolution"}])
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    observer = state.cards["wrong-work"].model_copy(deep=True)
    observer.instance_id = "observer"
    observer.card.effect_ids = ["CONTROL"]
    state.cards[observer.instance_id] = observer
    state.players["player_1"].member_area["left"] = observer.instance_id
    return state


def test_exact_binding_and_old_native_manual_reproduction():
    effect = _state().effect_definitions[EFFECT]
    assert (effect.text_revision_id, effect.raw_text_hash) == (
        860, "4de00b242755d4712ed8afbb6b6d5a27047c8f4cdbfd76101d0f1f1b7343cbf0")
    assert effect.review_status == "test_validated" and not effect.is_optional
    old = _begin(_state(legacy=True))
    assert old.state.pending_effects[0].effect_id == EFFECT
    assert old.state.effect_definitions[EFFECT].execution_mode == "manual_resolution"
    assert not any(e.event_type == "effect_cards_milled" for e in old.events)


@pytest.mark.parametrize("bottom_type,delta", [("live", 1), ("member", 0), ("energy", 0)])
@pytest.mark.parametrize("waiting", [False, True])
def test_only_actual_bottom_card_type_not_top_or_existing_waiting(bottom_type, delta, waiting):
    state = _pending(bottom_type=bottom_type)
    state.cards["good-member"].card.card_type = "live"
    state.players["player_1"].waiting_room = ["deck-live-2"] if waiting else []
    result = apply_action(state, _resolve(state))
    assert _event(result).data["heart_delta"] == delta
    player = result.state.players["player_1"]
    assert player.main_deck == ["good-member", "tail"]
    assert player.waiting_room == (["deck-live-2"] if waiting else []) + ["good-live"]
    assert len(player.manual_modifiers) == delta
    if delta:
        assert [(m.target_card_instance_id, m.color_slot, m.amount, m.duration) for m in player.manual_modifiers] == [
            ("source-live", "heart02", 1, "live")]


@pytest.mark.parametrize("bottom_type", ["live", "member"])
@pytest.mark.parametrize("waiting", [False, True])
def test_exactly_one_card_refreshes_before_condition_but_keeps_original_move(bottom_type, waiting):
    state = _pending(bottom_type=bottom_type)
    player = state.players["player_1"]
    player.main_deck = ["good-live"]
    player.waiting_room = ["tail"] if waiting else []
    result = apply_action(state, _resolve(state))
    events = [e.event_type for e in result.events]
    assert events.index("effect_cards_milled") < events.index("deck_refreshed") < events.index("effect_bottom_live_heart_resolved")
    assert _event(result).data["heart_delta"] == int(bottom_type == "live")
    player = result.state.players["player_1"]
    assert set(player.main_deck) == {"good-live", *(["tail"] if waiting else [])}
    assert player.waiting_room == [] and player.refresh_count == 1
    assert all(not result.state.cards[key].face_up for key in player.main_deck)


@pytest.mark.parametrize("waiting", [False, True])
def test_empty_deck_refreshes_normally_or_does_nothing_if_no_card(waiting):
    state = _pending()
    player = state.players["player_1"]
    player.main_deck = []
    player.waiting_room = ["good-live"] if waiting else []
    result = apply_action(state, _resolve(state))
    assert _event(result).data["milled_count"] == int(waiting)
    assert _event(result).data["heart_delta"] == int(waiting)
    assert result.state.players["player_1"].refresh_count == (2 if waiting else 0)


@pytest.mark.parametrize("movement", ["leave", "return", "position"])
@pytest.mark.parametrize("legacy_stage_policy", [False, True])
def test_native_live_start_interference_and_sql_replay(tmp_path, movement, legacy_stage_policy):
    state = _control_state()
    if legacy_stage_policy:
        state.stage_departure_policy = None
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    started = repo.apply(state.match_id, _advance(state)).state
    source = next(i for i in started.pending_effects if i.effect_id == EFFECT)
    assert source.trigger_data["original_source_stage_object"] is True
    invocation = next(i for i in started.pending_effects if i.effect_id == "CONTROL")
    if movement == "position":
        adjustments = [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "right"}]
    else:
        adjustments = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"}]
        if movement == "return":
            adjustments.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_right"})
    final = repo.apply(state.match_id, _manual(started, adjustments, invocation))
    if final.state.pending_effects:
        final = repo.apply(state.match_id, _resolve(final.state))
    assert _event(final).data["heart_delta"] == int(movement == "position")
    assert final.state.players["player_1"].waiting_room == ["good-live"]
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("legacy", [False, True])
def test_new_and_old_manual_sql_snapshots(tmp_path, legacy):
    state = _state(legacy=legacy)
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    final = repo.apply(state.match_id, _advance(state))
    if legacy:
        final = repo.apply(state.match_id, _manual(final.state, [{"adjustment_type": "move_card",
            "target_card_instance_id": "good-live", "to_zone": "waiting_room"}], final.state.pending_effects[0]))
        assert final.state.effect_definitions[EFFECT].execution_mode == "manual_resolution"
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_resolution_and_hidden_identity_invariance(policy):
    state = _pending()
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision) and match_state_hash(state) == before
    changed = state.model_copy(deep=True)
    for key in ["opponent-secret", *state.players["player_1"].main_deck]:
        changed.cards[key].card.card_code = changed.cards[key].card.name_ja = "HIDDEN-CHANGED"
        changed.cards[key].card.basic_hearts = {"heart06": 99}
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}).action == decision.action
    assert _event(apply_action(state, decision.action)).data["heart_delta"] == 1


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_actual_live_start_without_extra_confirmation(policy):
    state = _state()
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision) and decision.action.action_type == "advance_phase"
    assert match_state_hash(state) == before
    result = apply_action(state, decision.action)
    assert _event(result).data["heart_delta"] == 1 and not result.state.pending_effects


@pytest.mark.parametrize("zone", ["hand", "waiting_room", "main_deck"])
def test_live_start_does_not_trigger_source_outside_stage(zone):
    state = _state()
    state.players["player_1"].member_area["center"] = None
    getattr(state.players["player_1"], zone).append("source-live")
    result = _begin(state)
    assert not any(e.event_type == "effect_bottom_live_heart_resolved" for e in result.events)
    assert not result.state.pending_effects


def test_no_live_attempt_does_not_trigger_live_start():
    state = _state()
    state.players["player_1"].live_area = []
    assert not any(e.event_type == "effect_bottom_live_heart_resolved" for e in _begin(state).events)


@pytest.mark.parametrize("orientation", ["active", "wait"])
def test_source_orientation_does_not_cancel_trigger(orientation):
    state = _state()
    state.cards["source-live"].orientation = orientation
    assert _event(_begin(state)).data["heart_delta"] == 1


@pytest.mark.parametrize("bottom_type", ["live", "member"])
def test_second_performer_uses_own_bottom_and_source(bottom_type):
    state = _state(bottom_type=bottom_type)
    first = state.players["player_1"].model_copy(deep=True)
    second = state.players["player_2"].model_copy(deep=True)
    state.players["player_1"], state.players["player_2"] = second, first
    state.players["player_1"].player_id = "player_1"
    state.players["player_2"].player_id = "player_2"
    for card in state.cards.values():
        card.owner_id = "player_2" if card.owner_id == "player_1" else "player_1"
    state.phase, state.active_player_id = "performance_second", "player_2"
    result = apply_action(state, ActionRequest(action_type="advance_phase", player_id="player_2", expected_revision=state.revision))
    assert _event(result).player_id == "player_2"
    assert _event(result).data["heart_delta"] == int(bottom_type == "live")
    assert result.state.players["player_2"].waiting_room == ["good-live"]
    assert result.state.players["player_1"].waiting_room == second.waiting_room


def test_refreshed_card_identity_does_not_restore_hidden_current_card_map():
    state = _pending()
    state.players["player_1"].main_deck = ["good-live"]
    state.players["player_1"].waiting_room = ["tail"]
    result = apply_action(state, _resolve(state))
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        assert not {"good-live", "tail"}.intersection(payload["state"]["cards"])


def test_dual_view_public_bottom_without_hidden_top_or_opponent_hand():
    result = _begin(_state())
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        assert "good-live" in payload["state"]["cards"]
        assert "AUDIT-tail" not in json.dumps(payload) and "AUDIT-good-member" not in json.dumps(payload)
        assert "tail" not in json.dumps(payload) and "good-member" not in json.dumps(payload)
        if viewer == "player_1":
            assert "opponent-secret" not in json.dumps(payload)
        else:
            assert "AUDIT-cost" not in json.dumps(payload)


@pytest.mark.parametrize("defect", ["missing_snapshot", "opponent", "decline"])
def test_bad_resolution_is_atomic(defect):
    state = _pending()
    if defect == "missing_snapshot":
        state.pending_effects[0].trigger_data.pop("original_source_stage_object")
    action = _resolve(state, accepted=defect != "decline")
    if defect == "opponent":
        action.player_id = "player_2"
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, action)
    assert match_state_hash(state) == before


@pytest.mark.parametrize("legacy_stage_policy", [False, True])
def test_source_departure_and_native_live_end_clear_heart(legacy_stage_policy):
    initial = _state()
    if legacy_stage_policy:
        initial.stage_departure_policy = None
    state = _begin(initial).state
    control = state.effect_definitions[EFFECT].model_dump(mode="json")
    control.update(effect_id="CONTROL", actions=[{"action_type": "manual_resolution"}],
                   execution_mode="manual_resolution", simulation_support="manual_resolution")
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(control)
    state.pending_effects = [EffectInvocation(invocation_id="control", effect_id="CONTROL",
        player_id="player_1", source_card_instance_id="source-live", trigger_event="live_started")]
    left = apply_action(state, _manual(state, [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"},
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_right"}], state.pending_effects[0]))
    assert not left.state.players["player_1"].manual_modifiers
    state = _begin(_state()).state
    state.phase = "live_judgment"
    assert not apply_action(state, _advance(state)).state.players["player_1"].manual_modifiers


def test_legacy_bottom_milling_snapshot_has_no_new_source_semantics(tmp_path):
    state = _state()
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(actions=[{"action_type": "mill_bottom_cards", "amount": 1}], duration=None)
    state.effect_definitions[EFFECT] = EffectDefinition.model_validate(raw)
    assert "source_object_policy" not in state.effect_definitions[EFFECT].model_dump_json()
    repo = MatchRepository(tmp_path / "legacy-mill.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    final = repo.apply(state.match_id, _advance(state))
    assert final.state.players["player_1"].waiting_room == ["good-live"]
    assert not final.state.players["player_1"].manual_modifiers
    assert not any(e.event_type == "effect_bottom_live_heart_resolved" for e in final.events)
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True


@pytest.mark.parametrize("changes", [{"amount": 2}, {"color_slot": "heart04"}, {"target": "self"}, {"source_object_policy": None}])
def test_bounded_operation_cannot_be_widened(changes):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw["actions"][1].update(changes)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("changes", [{"is_optional": True}, {"duration": "turn"}, {"frequency_limit": "none"},
    {"condition": {"minimum_energy": 1}}, {"trigger": "member_played"}, {"actions": [{"action_type": "mill_top_cards", "amount": 1}]}])
def test_bounded_definition_cannot_be_widened(changes):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(changes)
    # Replacing all actions removes the new policy and is an unrelated legacy definition.
    if "actions" in changes:
        raw["actions"].append(_state().effect_definitions[EFFECT].actions[1].model_dump(mode="json"))
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("changes", [{"card_code": "OTHER"}, {"text_revision_id": 861}, {"raw_text_hash": "other"},
    {"raw_effect_text_ja": "【ライブ開始時】カードを1枚引く。"}])
def test_exact_generator_rejects_other_texts_and_revisions(changes):
    from loveca.simulation.effect_candidates import BOTTOM_ONE_LIVE_HEART_TEXT, _live_start_bottom_one_heart
    row = {"card_code": CODE, "text_revision_id": 860, "raw_effect_text_ja": BOTTOM_ONE_LIVE_HEART_TEXT,
           "raw_text_hash": _state().effect_definitions[EFFECT].raw_text_hash}
    assert _live_start_bottom_one_heart({**row, **changes}) is None
