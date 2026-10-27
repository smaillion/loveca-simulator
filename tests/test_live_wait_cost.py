from contextlib import closing
from functools import lru_cache
from pathlib import Path

import pytest
from test_live_discard_color import _begin, _options, _resolve
from test_live_discard_color import _state as discard_state

from loveca.db.bootstrap import connect_database
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, MatchState
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODES = ("PL!N-sd2-006", "PL!N-bp7-012")
RULE_REFERENCE_IDS = ("5.2.1", "9.4.2", "9.7.2", "11.5.2", "9.9.2", "8.3.11")


@lru_cache
def _candidate(code):
    return next(c for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
                if c.effect_id == code + ":1")


def _state(code, *, legacy=False):
    effect = next(e for e in load_effect_registry().effects if e.effect_id == code + ":1")
    if legacy:
        raw = effect.model_dump(mode="json")
        raw.update(choice=None, cost=[], cost_choice=None, actions=[{"action_type": "manual_resolution"}],
                   execution_mode="manual_resolution", simulation_support="manual_resolution", review_status="parsed_draft")
        effect = EffectDefinition.model_validate(raw)
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        card = _load_definition(connection, code, None, {effect.effect_id: effect}, {})
    state = discard_state()
    state.effect_definitions = {effect.effect_id: effect}
    state.cards["source-live"].card = card
    for key, work, slot in [("cost-member", "nijigasaki", "left"), ("wrong-work", "aqours", "right")]:
        state.cards[key] = state.cards["hand-0"].model_copy(update={"instance_id": key, "face_up": True}, deep=True)
        state.cards[key].card.work_keys = [work]
        state.cards[key].card.effect_ids = []
        state.cards[key].card.blade = 1
        state.players["player_1"].member_area[slot] = key
    state.cards["opponent-member"] = state.cards["cost-member"].model_copy(
        update={"instance_id": "opponent-member", "owner_id": "player_2"}, deep=True)
    state.players["player_2"].member_area["center"] = "opponent-member"
    state.cards["attached-member"] = state.cards["cost-member"].model_copy(
        update={"instance_id": "attached-member"}, deep=True)
    state.players["player_1"].member_area_attachments["left"] = ["attached-member"]
    return state


def _payload(code, target="cost-member"):
    return {"selected_card_instance_ids": [target], **({"selected_color_slot": "heart06"} if code == CODES[1] else {})}


@pytest.mark.parametrize("code", CODES)
def test_actual_live_start_is_structured_not_manual(code):
    result = _begin(_state(code))
    assert _options(result)["execution_mode"] == "prompt_then_resolve"
    result = apply_action(result.state, _resolve(result.state, **_payload(code)))
    assert result.state.players["player_1"].manual_modifiers[0].target_card_instance_id == "source-live"


@pytest.mark.parametrize("code,revision,hash_value", [
    (CODES[0], 937, "1626135ef08789e583f9e8927e1640e9838f194f28d30f39ced8d1f3510f3647"),
    (CODES[1], 875, "c926270668f310d00897f094d0f60ba6de0268664a8588ee139168762e140ac5")])
def test_exact_candidate_registry_and_cost_contract(code, revision, hash_value):
    effect = _state(code).effect_definitions[code + ":1"]
    assert effect == EffectDefinition.model_validate(_candidate(code).to_registry_entry())
    assert effect.text_revision_id == revision and effect.raw_text_hash == hash_value
    assert effect.cost_choice.orientation == "active" and effect.cost_choice.work_key == "nijigasaki"
    assert not effect.cost_choice.exclude_source
    assert effect.simulation_support == "test_validated_executable" and effect.review_status == "test_validated"


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("target", ["source-live", "cost-member"])
def test_wait_cost_and_source_bonus_remain_separate_and_yell_ignores_wait_member(code, target):
    from loveca.simulation.engine import _effective_member_blade
    state = _begin(_state(code)).state
    result = apply_action(state, _resolve(state, **_payload(code, target)))
    player = result.state.players["player_1"]
    assert result.state.cards[target].orientation == "wait"
    assert result.state.players["player_1"].hand == state.players["player_1"].hand
    modifier = player.manual_modifiers[0]
    assert (modifier.modifier_type, modifier.amount, modifier.color_slot, modifier.target_card_instance_id, modifier.duration) == (
        "blade" if code == CODES[0] else "heart", 2 if code == CODES[0] else 1,
        None if code == CODES[0] else "heart06", "source-live", "live")
    expected = sum(_effective_member_blade(result.state, "player_1", item)
                   for item in player.member_area.values() if item and result.state.cards[item].orientation == "active")
    yelled = apply_action(result.state, ActionRequest(action_type="advance_phase", player_id="player_1", expected_revision=result.state.revision))
    event = next(e for e in yelled.events if e.event_type == "yell_completed")
    assert event.data["raw_blade_count"] == expected
    if code == CODES[1]:
        live_result = yelled.state.players["player_1"].live_result
        assert live_result.manual_hearts == {"heart06": 1}
        assert live_result.available_hearts["heart06"] >= 1
    if target == "source-live":
        assert expected == 2  # The two other Active Members only, not the source's gained Blade.


@pytest.mark.parametrize("color", [f"heart0{i}" for i in range(1, 7)])
def test_all_six_heart_colors_are_available(color):
    state = _begin(_state(CODES[1])).state
    result = apply_action(state, _resolve(state, selected_card_instance_ids=["cost-member"], selected_color_slot=color))
    assert result.state.players["player_1"].manual_modifiers[0].color_slot == color


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("target", [[], ["cost-member", "source-live"], ["cost-member", "cost-member"],
                                  ["wrong-work"], ["hand-0"], ["attached-member"], ["opponent-secret"], ["opponent-member"], ["missing"]])
def test_illegal_cost_target_is_atomic(code, target):
    state = _begin(_state(code)).state
    before = match_state_hash(state)
    payload = _payload(code)
    payload["selected_card_instance_ids"] = target
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, **payload))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("color", [None, "heart0", "heart07"])
def test_bad_color_does_not_wait_the_cost_member(color):
    state = _begin(_state(CODES[1])).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, selected_card_instance_ids=["cost-member"], selected_color_slot=color))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("code", CODES)
def test_waiting_cost_is_excluded_and_no_active_target_does_not_stall(code):
    state = _state(code)
    state.cards["cost-member"].orientation = "wait"
    started = _begin(state)
    assert _options(started)["candidate_card_instance_ids"] == ["source-live"]
    before = match_state_hash(started.state)
    with pytest.raises(IllegalActionError):
        apply_action(started.state, _resolve(started.state, **_payload(code)))
    assert match_state_hash(started.state) == before
    state.cards["source-live"].orientation = "wait"
    result = _begin(state)
    assert not result.state.pending_effects and not result.state.players["player_1"].manual_modifiers
    assert any(e.event_type == "effect_not_activatable" for e in result.events)


@pytest.mark.parametrize("code", CODES)
def test_decline_does_not_wait_any_member(code):
    state = _begin(_state(code)).state
    result = apply_action(state, _resolve(state, accepted=False))
    assert not result.state.players["player_1"].manual_modifiers and not result.state.pending_effects
    assert result.state.cards["cost-member"].orientation == result.state.cards["source-live"].orientation == "active"


def _with_control(code):
    state = _state(code)
    raw = state.effect_definitions[code + ":1"].model_dump(mode="json")
    raw.update(effect_id="AUDIT-control:1", card_code="AUDIT-control", cost=[], cost_choice=None, choice=None,
               actions=[{"action_type": "manual_resolution"}], execution_mode="manual_resolution",
               simulation_support="manual_resolution", review_status="parsed_draft", is_optional=False)
    control = EffectDefinition.model_validate(raw)
    state.effect_definitions[control.effect_id] = control
    state.cards["live-1"].card.effect_ids = [control.effect_id]
    return state


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("reenter", [False, True])
def test_sql_original_source_departure_does_not_grant_bonus_to_new_object(tmp_path, code, reenter):
    state = _with_control(code)
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    started = repository.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id="player_1", expected_revision=0)).state
    control = next(i for i in started.pending_effects if i.effect_id == "AUDIT-control:1")
    moved = repository.apply(state.match_id, ActionRequest(action_type="manual_adjustment", player_id="player_1",
        expected_revision=started.revision, payload={"source_invocation_id": control.invocation_id,
            "source_effect_id": control.effect_id, "source_card_instance_id": "live-1", "adjustments": [
                {"adjustment_type": "move_card", "target_player_id": "player_1", "target_card_instance_id": "source-live", "to_zone": zone}
                for zone in (["waiting_room", "member_center"] if reenter else ["waiting_room"])]})).state
    result = repository.apply(state.match_id, _resolve(moved, **_payload(code)))
    assert result.state.cards["cost-member"].orientation == "wait"
    assert not result.state.players["player_1"].manual_modifiers and not result.state.pending_effects
    assert any(e.data.get("reason") == "original_source_stage_member_departed" for e in result.events)
    replay = repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("legacy", [False, True])
def test_sql_replay_preserves_new_bonus_and_old_manual(tmp_path, code, legacy):
    state = _state(code, legacy=legacy)
    assert MatchState.model_validate_json(state.model_dump_json()) == state
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    started = repository.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id="player_1", expected_revision=0))
    if legacy:
        with pytest.raises(IllegalActionError, match="manual_resolution"):
            repository.apply(state.match_id, _resolve(started.state, **_payload(code)))
        result = started
    else:
        result = repository.apply(state.match_id, _resolve(started.state, **_payload(code)))
    replay = repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")
    for viewer, secret in [("player_1", "opponent-secret"), ("player_2", "hand-0")]:
        assert secret not in _match_state_payload(result.state, events=result.events,
            legal_actions=result.legal_actions, player_id=viewer)["state"]["cards"]


@pytest.mark.parametrize("code", CODES)
def test_live_end_clears_bonus_and_does_not_ready_paid_member(code):
    state = _begin(_state(code)).state
    state = apply_action(state, _resolve(state, **_payload(code))).state
    state.phase, state.active_player_id = "live_judgment", None
    result = apply_action(state, ActionRequest(action_type="advance_phase", expected_revision=state.revision))
    assert not result.state.players["player_1"].manual_modifiers
    assert result.state.cards["cost-member"].orientation == "wait"


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_policies_use_native_costs_and_ignore_opponent_hidden_identity(code, policy):
    state = _begin(_state(code)).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision)
    changed = state.model_copy(deep=True)
    changed.cards["opponent-secret"].card.card_code = "PRIVATE-CHANGED"
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}).action == decision.action
    assert not apply_action(state, decision.action).state.pending_effects


@pytest.mark.parametrize("defect", ["cost_target", "cost_wait", "cost_work", "amount", "trigger", "optional"])
def test_wait_source_policy_rejects_unmodeled_semantics(defect):
    raw = _state(CODES[0]).effect_definitions[CODES[0] + ":1"].model_dump(mode="json")
    if defect == "cost_target": raw["cost"][0]["target"] = "source"
    elif defect == "cost_wait": raw["cost_choice"]["orientation"] = "wait"
    elif defect == "cost_work": raw["cost_choice"]["work_key"] = "aqours"
    elif defect == "amount": raw["actions"][0]["amount"] = 3
    elif defect == "trigger": raw["trigger"] = "member_played"
    else: raw["is_optional"] = False
    with pytest.raises(ValueError, match="Wait cost source policy"):
        EffectDefinition.model_validate(raw)
