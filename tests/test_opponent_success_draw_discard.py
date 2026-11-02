import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_moved_source_ready import _manual
from test_nijigasaki_inspection import _candidate, _resolve
from test_nijigasaki_inspection import _state as _base_state

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!N-sd2-007"
EFFECT = CODE + ":1"
RULE_REFERENCE_IDS = ("8.3.16", "8.4.4", "8.4.5", "8.4.6", "9.6.3.1", "9.7.7", "10.2.2.1")


def _state(*, opponent_success=True, legacy=False):
    state = _base_state(CODE)
    if not legacy:
        state.effect_definitions[EFFECT] = EffectDefinition.model_validate(_candidate(CODE).to_registry_entry())
    else:
        raw = state.effect_definitions[EFFECT].model_dump(mode="json")
        raw.update(actions=[{"action_type": "manual_resolution"}], choice=None, duration="live",
                   execution_mode="manual_resolution", simulation_support="manual_resolution", review_status="parsed_draft",
                   source_reference="Official card text; timing-only manual fallback pending structured effect modeling")
        state.effect_definitions[EFFECT] = EffectDefinition.model_validate(raw)
    player = state.players["player_1"]
    player.hand = ["cost"]
    player.main_deck = ["good-member", "good-live", "wrong-work", "tail"]
    player.member_area["center"] = "source-live"
    player.live_area = ["deck-live-1"]
    other = state.cards["deck-live-2"].model_copy(deep=True)
    other.instance_id, other.owner_id = "opponent-live", "player_2"
    state.cards[other.instance_id] = other
    state.players["player_2"].live_area = [other.instance_id] if opponent_success else []
    state.phase, state.active_player_id = "live_judgment", None
    state.effect_order_policy = "ap_nap_player_choice"
    state.stage_departure_policy = "clear_departed_card_modifiers"
    return state


def _begin(state):
    return apply_action(state, ActionRequest(action_type="advance_phase", player_id=None, expected_revision=state.revision))


def _finish(state, ids):
    return apply_action(state, _resolve(state, selected_card_instance_ids=ids))


def _event(result):
    return next(e for e in result.events if e.event_type == "effect_opponent_success_draw_resolved")


def test_native_success_draws_before_owner_selects_one_to_discard():
    started = _begin(_state())
    assert started.state.live_success_player_ids == ["player_1", "player_2"]
    result = apply_action(started.state, _resolve(started.state))
    assert _event(result).data["condition_met"] is True
    assert result.state.players["player_1"].hand == ["cost", "good-member", "good-live"]
    assert result.state.players["player_1"].waiting_room == []
    final = _finish(result.state, ["good-live"])
    assert final.state.players["player_1"].hand == ["cost", "good-member"]
    assert "good-live" in final.state.players["player_1"].waiting_room
    assert not final.state.pending_effects


def test_exact_registry_contract_and_native_old_manual_blocker():
    effect = _state().effect_definitions[EFFECT]
    assert (effect.text_revision_id, effect.raw_text_hash) == (
        938, "a0652e4321925ae2826d299c309118fb251aa81c1b11b7fc62ca84091f8111fb")
    assert not effect.is_optional and not effect.cost and effect.duration is None
    assert effect.review_status == "test_validated"
    old = _begin(_state(legacy=True))
    with pytest.raises(IllegalActionError, match="manual_resolution"):
        apply_action(old.state, _resolve(old.state))


@pytest.mark.parametrize("past_count", [0, 1, 2])
def test_opponent_past_success_cards_do_not_enable_current_turn_bonus(past_count):
    state = _state(opponent_success=False)
    state.players["player_2"].success_live_area = []
    for n in range(past_count):
        key = f"past-{n}"
        card = state.cards["opponent-live"].model_copy(deep=True)
        card.instance_id = key
        state.cards[key] = card
        state.players["player_2"].success_live_area.append(key)
    # An old success cache is overwritten by the native current judgment.
    state.live_success_player_ids = ["player_1", "player_2"]
    result = _begin(state)
    assert result.state.live_success_player_ids == ["player_1"]
    result = apply_action(result.state, _resolve(result.state))
    assert _event(result).data["condition_met"] is False
    assert _event(result).data["extra_drawn_count"] == 0
    assert result.state.players["player_1"].hand == ["cost", "good-member"]
    assert not result.state.pending_effects


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("opponent_success", [False, True])
def test_owner_and_first_performer_do_not_change_condition(owner, first, opponent_success):
    state = _state(opponent_success=opponent_success)
    if owner == "player_2":
        state.players["player_1"], state.players["player_2"] = state.players["player_2"], state.players["player_1"]
        for key, player in state.players.items():
            player.player_id = key
        for card in state.cards.values():
            card.owner_id = "player_2" if card.owner_id == "player_1" else "player_1"
    state.first_player_id, state.second_player_id = first, "player_2" if first == "player_1" else "player_1"
    started = _begin(state).state
    invocation = next(i for i in started.pending_effects if i.effect_id == EFFECT)
    assert invocation.player_id == owner
    result = apply_action(started, ActionRequest(action_type="resolve_effect", player_id=owner,
        expected_revision=started.revision, payload={"invocation_id": invocation.invocation_id}))
    assert _event(result).data["condition_met"] == opponent_success
    assert len(result.state.players[owner].hand) == (3 if opponent_success else 2)
    if opponent_success:
        final = apply_action(result.state, ActionRequest(action_type="resolve_effect", player_id=owner,
            expected_revision=result.state.revision, payload={"invocation_id": invocation.invocation_id,
            "selected_card_instance_ids": ["good-live"]}))
        assert len(final.state.players[owner].hand) == 2


def test_success_is_not_winning_score_comparison():
    state = _state()
    state.cards["deck-live-1"].card.score = 0
    state.cards["opponent-live"].card.score = 99
    result = _begin(state)
    result = apply_action(result.state, _resolve(result.state))
    assert _event(result).data["condition_met"] is True
    final = _finish(result.state, ["good-live"])
    assert final.state.live_winner_ids == ["player_2"]


@pytest.mark.parametrize("draw_count", [0, 1, 2, 3])
@pytest.mark.parametrize("waiting", [False, True])
@pytest.mark.parametrize("opponent_success", [False, True])
def test_zero_short_decks_and_possible_discard(draw_count, waiting, opponent_success):
    state = _state(opponent_success=opponent_success)
    player = state.players["player_1"]
    player.hand = []
    player.main_deck = player.main_deck[:draw_count]
    player.waiting_room = ["blade-heart"] if waiting else []
    total = draw_count + int(waiting)
    result = _begin(state)
    result = apply_action(result.state, _resolve(result.state))
    drawn = min(total, 1 + int(opponent_success))
    assert len(result.state.players["player_1"].hand) == drawn
    assert _event(result).data["extra_drawn_count"] == int(opponent_success and total >= 2)
    assert bool(result.state.pending_effects) == bool(opponent_success and drawn)
    if result.state.pending_effects:
        selected = result.state.players["player_1"].hand[0]
        final = _finish(result.state, [selected])
        assert len(final.state.players["player_1"].hand) == drawn - 1
        assert not final.state.pending_effects


@pytest.mark.parametrize("movement", ["leave", "return", "position", "deck"])
@pytest.mark.parametrize("both", [False, True])
def test_native_control_interference_source_and_success_history_sql(tmp_path, movement, both):
    state = _state(opponent_success=both)
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id="CONTROL", frequency_limit="none", actions=[{"action_type": "manual_resolution"}],
               choice=None, execution_mode="manual_resolution", simulation_support="manual_resolution")
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    observer = state.cards["blade-heart"].model_copy(deep=True)
    observer.instance_id, observer.card.effect_ids = "observer", ["CONTROL"]
    state.cards[observer.instance_id] = observer
    state.players["player_1"].member_area["left"] = "observer"
    repo = MatchRepository(tmp_path / "interference.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    started = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id=None, expected_revision=state.revision)).state
    inv = next(i for i in started.pending_effects if i.effect_id == "CONTROL")
    if movement == "position":
        adjustments = [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "right"}]
    else:
        adjustments = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live",
                        "to_zone": "main_deck" if movement == "deck" else "hand"}]
        if movement == "return":
            adjustments.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_right"})
    if both:
        adjustments.append({"adjustment_type": "move_card", "target_player_id": "player_2",
                            "target_card_instance_id": "opponent-live", "to_zone": "waiting_room"})
    moved = repo.apply(state.match_id, _manual(started, adjustments, inv)).state
    result = repo.apply(state.match_id, _resolve(moved))
    assert _event(result).data["condition_met"] == both
    if movement == "deck":
        for viewer in ["player_1", "player_2"]:
            view = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
            assert "source-live" not in view["state"]["cards"]
    if both:
        result = repo.apply(state.match_id, _resolve(result.state, selected_card_instance_ids=["good-live"]))
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")


@pytest.mark.parametrize("change", ["success_cache", "live_zone", "source_leave"])
def test_condition_is_locked_after_draw_before_discard(change):
    result = _begin(_state())
    state = apply_action(result.state, _resolve(result.state)).state
    if change == "success_cache":
        state.live_success_player_ids = ["player_1"]
    elif change == "live_zone":
        state.players["player_2"].live_area = []
    else:
        state.players["player_1"].member_area["center"] = None
        state.players["player_1"].waiting_room.append("source-live")
    final = _finish(state, ["good-live"])
    assert final.state.players["player_1"].hand == ["cost", "good-member"]
    assert not any(e.event_type == "effect_opponent_success_draw_resolved" for e in final.events)


@pytest.mark.parametrize("bad", [[], ["cost", "good-live"], ["cost", "cost"], ["opponent-secret"], ["tail"]])
def test_discard_is_one_current_owner_hand_card_and_atomic(bad):
    started = _begin(_state())
    state = apply_action(started.state, _resolve(started.state)).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        _finish(state, bad)
    assert match_state_hash(state) == before


@pytest.mark.parametrize("defect", ["opponent", "decline", "early_selection", "old_turn", "missing_turn", "bool_turn", "not_queued", "not_judgment", "missing_success"])
def test_invalid_initial_resolution_does_not_draw_or_mutate(defect):
    state = _begin(_state()).state
    action = _resolve(state)
    if defect == "opponent":
        action.player_id = "player_2"
    elif defect == "decline":
        action.payload["accepted"] = False
    elif defect == "early_selection":
        action.payload["selected_card_instance_ids"] = ["cost"]
    elif defect == "old_turn":
        state.pending_effects[0].trigger_data["turn_number"] = state.turn_number - 1
    elif defect == "missing_turn":
        state.pending_effects[0].trigger_data.pop("turn_number")
    elif defect == "bool_turn":
        state.pending_effects[0].trigger_data["turn_number"] = True
    elif defect == "not_queued":
        state.live_success_effects_queued = False
    elif defect == "not_judgment":
        state.phase = "first_main"
    else:
        state.live_success_player_ids = []
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, action)
    assert match_state_hash(state) == before


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("both", [False, True])
def test_four_ai_native_sequence_and_hidden_identity_invariance(policy, both):
    state = _begin(_state(opponent_success=both)).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    for _ in range(2 if both else 1):
        before = match_state_hash(state)
        decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
        assert isinstance(decision, SimpleAIDecision) and decision.action.action_type == "resolve_effect"
        assert match_state_hash(state) == before
        changed = state.model_copy(deep=True)
        for key in ["opponent-secret", *state.players["player_1"].main_deck]:
            changed.cards[key].card.name_ja = changed.cards[key].card.card_code = "HIDDEN-CHANGED"
            changed.cards[key].card.basic_hearts = {"heart06": 99}
        assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}).action == decision.action
        state = apply_action(state, decision.action).state
    assert not state.pending_effects


def test_dual_view_drawn_hand_and_choice_remain_private_until_discard():
    started = _begin(_state())
    result = apply_action(started.state, _resolve(started.state))
    owner = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id="player_1")
    opponent = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id="player_2")
    assert {"good-member", "good-live"} <= owner["state"]["cards"].keys()
    for key in ["good-member", "good-live", "tail", "wrong-work"]:
        assert key not in json.dumps(opponent)
    assert "opponent-secret" not in json.dumps(owner)
    final = _finish(result.state, ["good-live"])
    opponent = _match_state_payload(final.state, events=final.events, legal_actions=final.legal_actions, player_id="player_2")
    assert "good-live" in opponent["state"]["cards"] and "good-member" not in json.dumps(opponent)


@pytest.mark.parametrize("legacy", [False, True])
def test_new_and_old_manual_sql_snapshots(tmp_path, legacy):
    state = _state(legacy=legacy)
    repo = MatchRepository(tmp_path / "snapshot.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id=None, expected_revision=state.revision))
    if legacy:
        result = repo.apply(state.match_id, _manual(result.state, [{"adjustment_type": "draw_card", "amount": 1}], result.state.pending_effects[0]))
    else:
        result = repo.apply(state.match_id, _resolve(result.state))
        result = repo.apply(state.match_id, _resolve(result.state, selected_card_instance_ids=["good-live"]))
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")


@pytest.mark.parametrize("change", [{"amount": 2}, {"target": "opponent"}, {"value": True}])
def test_fixed_extra_draw_operation_rejects_expansion(change):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw["actions"][1].update(change)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


def test_new_operation_cannot_be_used_as_a_cost_without_its_sequence():
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(cost=[raw["actions"][1]], actions=[{"action_type": "draw_card", "amount": 1}], choice=None)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("change", [{"is_optional": True}, {"trigger": "live_started"}, {"duration": "live"},
    {"frequency_limit": "none"}, {"condition": {"minimum_energy": 1}}, {"choice": None}])
def test_bounded_definition_rejects_expansion(change):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(change)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("change", [{"minimum": 0}, {"maximum": 2}, {"target_player": "opponent"},
    {"zone": "waiting_room"}, {"post_action_condition_key": None}, {"post_action_condition_minimum": 0}])
def test_fixed_private_discard_choice_rejects_expansion(change):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw["choice"].update(change)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("change", [{"card_code": "OTHER"}, {"text_revision_id": 939}, {"raw_text_hash": "other"},
    {"raw_effect_text_ja": "【ライブ成功時】カードを2枚引く。"}])
def test_exact_generator_rejects_unreviewed_variants(change):
    from loveca.simulation.effect_candidates import OPPONENT_SUCCESS_DRAW_DISCARD_TEXT, _live_success_opponent_draw_discard
    row = {"card_code": CODE, "text_revision_id": 938, "raw_effect_text_ja": OPPONENT_SUCCESS_DRAW_DISCARD_TEXT,
           "raw_text_hash": _state().effect_definitions[EFFECT].raw_text_hash}
    assert _live_success_opponent_draw_discard({**row, **change}) is None
