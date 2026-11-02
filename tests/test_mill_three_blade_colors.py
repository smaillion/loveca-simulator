import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_moved_source_ready import _manual
from test_nijigasaki_inspection import _candidate, _play, _resolve
from test_nijigasaki_inspection import _state as _base_state

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effect_candidates import MILL_THREE_BLADE_COLORS_TEXT, _onplay_mill_three_blade_colors
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, _member_heart_count, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, EffectInvocation, SpecialBladeHeart
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!N-bp7-020"
EFFECT = CODE + ":1"
RULE_REFERENCE_IDS = ("2.1.1", "2.1.3", "2.2.2.2", "2.7", "4.1.4", "9.7.7", "10.2.2.1", "8.4.11")


def _state(colors=("heart01", "heart04", None), *, legacy=False):
    state = _base_state(CODE, legacy=legacy)
    if legacy:
        raw = state.effect_definitions[EFFECT].model_dump(mode="json")
        raw.update(actions=[{"action_type": "manual_resolution"}], review_status="parsed_draft",
                   source_reference="Official card text; timing-only manual fallback pending structured effect modeling")
        state.effect_definitions[EFFECT] = EffectDefinition.model_validate(raw)
    state.stage_departure_policy = "clear_departed_card_modifiers"
    player = state.players["player_1"]
    player.main_deck = ["good-member", "wrong-work", "blade-heart", "tail", "good-live"]
    for item, color in zip(player.main_deck, colors):
        state.cards[item].card.card_type = "member"
        state.cards[item].card.blade_heart_color_slot = color
        state.cards[item].card.special_blade_hearts = []
        state.cards[item].card.basic_hearts = {"heart02": 3, "heart05": 2}
    return state


def _pending(colors=("heart01", "heart04", None)):
    state = _state(colors)
    player = state.players["player_1"]
    player.hand.remove("source-live")
    player.member_area["center"] = "source-live"
    state.pending_effects = [EffectInvocation(
        invocation_id="isolated-onplay", effect_id=EFFECT, source_card_instance_id="source-live",
        player_id="player_1", trigger_event="member_played",
        trigger_data={"original_source_stage_object": True, "_condition_checked_at_trigger": True},
    )]
    return state


def _resolved(colors=("heart01", "heart04", None)):
    state = _state(colors)
    return apply_action(state, _play(state))


def _result_event(result):
    return next(e for e in result.events if e.event_type == "effect_milled_blade_colors_resolved")


def _control(state):
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id="AUDIT-control", execution_mode="manual_resolution",
               simulation_support="manual_resolution", actions=[{"action_type": "manual_resolution"}])
    effect = EffectDefinition.model_validate(raw)
    state.effect_definitions[effect.effect_id] = effect
    invocation = state.pending_effects[0].model_copy(update={"invocation_id": "control", "effect_id": effect.effect_id})
    state.pending_effects.insert(0, invocation)
    return invocation


def _native_control_state():
    state = _state()
    state.effect_order_policy = "ap_nap_player_choice"
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id="CONTROL", trigger="own_member_played", execution_mode="manual_resolution",
               simulation_support="manual_resolution", actions=[{"action_type": "manual_resolution"}])
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    observer = state.cards["tail"].model_copy(deep=True)
    observer.instance_id = "observer"
    observer.card.effect_ids = ["CONTROL"]
    state.cards[observer.instance_id] = observer
    state.players["player_1"].member_area["left"] = observer.instance_id
    return state


def test_exact_identity_and_native_mandatory_onplay():
    state = _state()
    effect = state.effect_definitions[EFFECT]
    assert effect == EffectDefinition.model_validate(_candidate(CODE).to_registry_entry())
    assert (effect.text_revision_id, effect.raw_text_hash) == (
        883, "1fd519f551bd331e61e6a8fa1d9cfada8390c609ae73319768e4e7d30701ea04")
    assert effect.label_ja == MILL_THREE_BLADE_COLORS_TEXT
    assert effect.review_status == "test_validated" and not effect.is_optional
    assert not effect.cost and effect.choice is None
    played = apply_action(state, _play(state))
    assert not played.state.pending_effects
    assert _result_event(played).data["source_available"] is True
    assert played.state.players["player_1"].waiting_room == ["good-member", "wrong-work", "blade-heart"]


@pytest.mark.parametrize("colors,expected", [
    ((None, None, None), []), (("heart01", None, None), ["heart01"]),
    (("heart04", "heart04", "heart04"), ["heart04"]),
    (("heart0", "heart04", None), ["heart04"]),
    (("heart01", "heart04", None), ["heart01", "heart04"]),
    (("heart06", "heart03", "heart02"), ["heart02", "heart03", "heart06"]),
])
def test_only_distinct_colored_member_blade_hearts_grant_one_source_heart(colors, expected):
    result = _resolved(colors)
    event = _result_event(result)
    delta = int(len(expected) >= 2)
    assert event.data["blade_heart_color_slots"] == expected and event.data["heart_delta"] == delta
    assert event.data["condition_met"] == bool(delta)
    player = result.state.players["player_1"]
    assert player.waiting_room == ["good-member", "wrong-work", "blade-heart"]
    assert player.main_deck == ["tail", "good-live"] and player.hand == ["cost"]
    modifiers = player.manual_modifiers
    assert len(modifiers) == delta
    if delta:
        assert modifiers[0].target_card_instance_id == "source-live"
        assert (modifiers[0].color_slot, modifiers[0].amount, modifiers[0].duration) == ("heart04", 1, "live")
        assert _member_heart_count(result.state, "player_1", "source-live", "heart04") == 1
    assert not result.state.pending_effects and result.state.pending_choice is None


@pytest.mark.parametrize("color", ["heart01", "heart02", "heart03", "heart04", "heart05", "heart06"])
def test_all_six_printed_colors_count_but_ordinary_heart_colors_do_not(color):
    result = _resolved((color, None, None))
    assert _result_event(result).data["blade_heart_color_slots"] == [color]
    assert not result.state.players["player_1"].manual_modifiers


@pytest.mark.parametrize("special", ["all_color", "draw", "score", "unknown"])
def test_official_q270_all_plus_green_is_not_two_colors(special):
    state = _pending((None, "heart04", None))
    state.cards["good-member"].card.special_blade_hearts = [SpecialBladeHeart(effect_type=special, source_alt="AUDIT", value=3)]
    result = apply_action(state, _resolve(state))
    assert _result_event(result).data["blade_heart_color_slots"] == ["heart04"]
    assert _result_event(result).data["heart_delta"] == 0


@pytest.mark.parametrize("index", [0, 1])
def test_live_blade_color_does_not_complete_member_condition(index):
    state = _pending()
    state.cards[state.players["player_1"].main_deck[index]].card.card_type = "live"
    result = apply_action(state, _resolve(state))
    assert _result_event(result).data["heart_delta"] == 0


@pytest.mark.parametrize("count", [0, 1, 2, 3])
@pytest.mark.parametrize("waiting", [False, True])
def test_short_deck_sequential_mill_and_refresh(count, waiting):
    state = _pending()
    player = state.players["player_1"]
    deck = player.main_deck[:count]
    player.main_deck = deck
    player.waiting_room = ["good-live", "tail"] if waiting else []
    result = apply_action(state, _resolve(state))
    event = next(e for e in result.events if e.event_type == "effect_cards_milled")
    ids = event.data["milled_card_instance_ids"]
    assert ids[:count] == deck
    assert len(ids) == (3 if count or waiting else 0)
    assert result.state.players["player_1"].refresh_count >= int(count < 3 and (waiting or count > 0))
    assert not result.state.pending_effects and result.state.pending_choice is None
    assert len(set(result.state.players["player_1"].main_deck + result.state.players["player_1"].waiting_room)) == count + (2 if waiting else 0)


@pytest.mark.parametrize("returning", [False, True])
def test_source_departure_before_resolution_still_mills_without_inheriting_heart(returning):
    state = _pending()
    control = _control(state)
    adjustments = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"}]
    if returning:
        adjustments.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_right"})
    result = apply_action(state, _manual(state, adjustments, control))
    assert result.state.players["player_1"].waiting_room == ["good-member", "wrong-work", "blade-heart"]
    assert _result_event(result).data["source_available"] is False
    assert not result.state.players["player_1"].manual_modifiers


def test_source_stage_position_change_keeps_original_object():
    state = _pending()
    control = _control(state)
    result = apply_action(state, _manual(state, [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "right"}], control))
    assert _result_event(result).data["heart_delta"] == 1


@pytest.mark.parametrize("movement", ["leave", "return", "position"])
def test_native_onplay_order_interference_and_sql_replay(tmp_path, movement):
    state = _native_control_state()
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state)).state
    invocation = next(i for i in played.pending_effects if i.effect_id == "CONTROL")
    source = next(i for i in played.pending_effects if i.effect_id == EFFECT)
    assert source.trigger_data["original_source_stage_object"] is True
    if movement == "position":
        adjustments = [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "right"}]
    else:
        adjustments = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"}]
        if movement == "return":
            adjustments.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_right"})
    moved = repo.apply(state.match_id, _manual(played, adjustments, invocation))
    if moved.state.pending_effects:
        final = repo.apply(state.match_id, _resolve(moved.state))
    else:
        final = moved
    assert _result_event(final).data["heart_delta"] == int(movement == "position")
    assert final.state.players["player_1"].waiting_room == ["good-member", "wrong-work", "blade-heart"]
    if movement == "leave":
        public = _match_state_payload(final.state, events=final.events, legal_actions=final.legal_actions, player_id="player_2")
        assert "source-live" not in public["state"]["cards"]
        assert "opponent-secret" not in _match_state_payload(final.state, events=[], legal_actions=[], player_id="player_1")["state"]["cards"]
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


def test_source_leaving_after_grant_clears_targeted_modifier():
    state = _resolved().state
    result = apply_action(state, _manual(state, [
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"},
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_right"},
    ]))
    assert not result.state.players["player_1"].manual_modifiers


def test_native_live_end_expires_heart():
    state = _resolved().state
    state.phase = "live_judgment"
    result = apply_action(state, ActionRequest(action_type="advance_phase", player_id="player_1", expected_revision=state.revision))
    assert not result.state.players["player_1"].manual_modifiers


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_native_resolution_and_hidden_identity_invariance(policy):
    state = _pending()
    ai = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    decision = ai.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision) and match_state_hash(state) == before
    changed = state.model_copy(deep=True)
    for key in ["opponent-secret", "good-member", "wrong-work", "blade-heart", "tail"]:
        changed.cards[key].card.name_ja = changed.cards[key].card.card_code = "HIDDEN-CHANGED"
    assert ai.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}).action == decision.action
    assert not apply_action(state, decision.action).state.pending_effects


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_actual_member_play_resolves_auto_mill(policy):
    state = _state()
    state.players["player_1"].hand = ["source-live"]
    ai = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    decision = ai.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision) and decision.action.action_type == "play_member"
    assert match_state_hash(state) == before
    result = apply_action(state, decision.action)
    assert _result_event(result).data["heart_delta"] == 1 and not result.state.pending_effects


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


def test_dual_view_milled_public_cards_without_hidden_tail_or_opponent_hand():
    result = _resolved()
    for viewer in ("player_1", "player_2"):
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        assert {"good-member", "wrong-work", "blade-heart"} <= payload["state"]["cards"].keys()
        assert "tail" not in json.dumps(payload) and "AUDIT-tail" not in json.dumps(payload)
        if viewer == "player_1":
            assert "opponent-secret" not in json.dumps(payload)
        else:
            assert "AUDIT-cost" not in json.dumps(payload)


@pytest.mark.parametrize("legacy", [False, True])
def test_sql_replay_preserves_new_source_policy_and_old_manual(tmp_path, legacy):
    state = _state(legacy=legacy)
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played_result = repo.apply(state.match_id, _play(state))
    played = played_result.state
    if legacy:
        final = repo.apply(state.match_id, _manual(played, [{"adjustment_type": "move_card", "target_card_instance_id": "good-member", "to_zone": "waiting_room"}], played.pending_effects[0]))
        assert final.state.effect_definitions[EFFECT].actions[0].action_type == "manual_resolution"
        assert final.state.effect_definitions[EFFECT].actions[0].amount is None
        assert final.state.effect_definitions[EFFECT].review_status == "parsed_draft"
    else:
        final = played_result
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("changes", [{"amount": 2}, {"color_slot": "heart01"}, {"target": "self"}, {"source_object_policy": None}])
def test_bounded_operation_cannot_be_widened(changes):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw["actions"][1].update(changes)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("changes", [{"is_optional": True}, {"duration": "turn"}, {"condition": {"minimum_energy": 1}}, {"trigger": "live_started"}])
def test_bounded_definition_cannot_be_widened(changes):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(changes)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("changes", [{"card_code": "OTHER"}, {"text_revision_id": 884}, {"raw_text_hash": "other"},
    {"raw_effect_text_ja": MILL_THREE_BLADE_COLORS_TEXT + "カードを1枚引く。"}])
def test_exact_generator_rejects_unreviewed_variants(changes):
    row = {"card_code": CODE, "text_revision_id": 883, "raw_effect_text_ja": MILL_THREE_BLADE_COLORS_TEXT,
           "raw_text_hash": _state().effect_definitions[EFFECT].raw_text_hash}
    assert _onplay_mill_three_blade_colors({**row, **changes}) is None
