from contextlib import closing
from functools import lru_cache
from pathlib import Path

import pytest
from test_effect_execution import _minimal_effect_state

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

CODE = "PL!N-sd2-005"
EFFECT = CODE + ":1"
COLORS = [f"heart0{i}" for i in range(1, 7)]
RULE_REFERENCE_IDS = ("9.4.2", "9.5.3", "9.6.3", "9.7.2", "11.5.2", "9.9.2", "8.4.11")


@lru_cache
def _candidate():
    return next(c for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
                if c.effect_id == EFFECT)


def _state(*, hand=3, legacy=False):
    effect = next(e for e in load_effect_registry().effects if e.effect_id == EFFECT)
    if legacy:
        raw = effect.model_dump(mode="json")
        raw.update(choice=None, cost=[], cost_choice=None, actions=[{"action_type": "manual_resolution"}],
                   execution_mode="manual_resolution", simulation_support="manual_resolution", review_status="parsed_draft")
        effect = EffectDefinition.model_validate(raw)
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        card = _load_definition(connection, CODE, None, {EFFECT: effect}, {})
    state = _minimal_effect_state(effect)
    state.phase = "performance_first"
    state.pending_effects = []
    state.stage_departure_policy = "clear_departed_card_modifiers"
    state.effect_order_policy = "ap_nap_player_choice"
    state.cards["source-live"].card = card
    state.players["player_1"].member_area["center"] = "source-live"
    for i in range(hand):
        key = f"hand-{i}"
        state.cards[key] = state.cards["deck-member-1"].model_copy(update={"instance_id": key}, deep=True)
        state.players["player_1"].hand.append(key)
    state.cards["opponent-secret"] = state.cards["deck-member-1"].model_copy(
        update={"instance_id": "opponent-secret", "owner_id": "player_2"}, deep=True)
    state.players["player_2"].hand = ["opponent-secret"]
    return state


def _begin(state):
    return apply_action(state, ActionRequest(action_type="advance_phase", player_id="player_1", expected_revision=state.revision))


def _resolve(state, **payload):
    return ActionRequest(action_type="resolve_effect", player_id="player_1", expected_revision=state.revision,
        payload={"invocation_id": state.pending_effects[0].invocation_id, "accepted": True, **payload})


def _options(result):
    return next(a for a in result.legal_actions if a.action_type == "resolve_effect").options["invocations"][0]


def test_actual_live_trigger_can_pay_two_and_choose_a_color():
    started = _begin(_state())
    assert _options(started)["execution_mode"] == "prompt_then_resolve"
    result = apply_action(started.state, _resolve(started.state, selected_card_instance_ids=["hand-0", "hand-1"], selected_color_slot="heart06"))
    assert len(result.state.players["player_1"].manual_modifiers) == 1


def test_exact_candidate_and_registry_contract():
    candidate = _candidate()
    effect = next(e for e in load_effect_registry().effects if e.effect_id == EFFECT)
    assert effect == EffectDefinition.model_validate(candidate.to_registry_entry())
    assert effect.text_revision_id == 936
    assert effect.raw_text_hash == "64e8c7cad33cf244869c007c1bc7d2ff52ebfd039062a34ee1d793c7f25ee66d"
    assert effect.is_optional and effect.duration == "live" and effect.frequency_limit == "once_per_live"
    assert effect.simulation_support == "test_validated_executable" and effect.review_status == "test_validated"
    assert effect.cost_choice.minimum == effect.cost_choice.maximum == 2
    assert effect.choice.color_slots == COLORS


@pytest.mark.parametrize("color", COLORS)
def test_all_six_colors_pay_exactly_two_and_apply_two_hearts_to_source(color):
    state = _begin(_state()).state
    assert state.pending_effects[0].trigger_data["original_source_stage_object"] is True
    result = apply_action(state, _resolve(state, selected_card_instance_ids=["hand-0", "hand-1"], selected_color_slot=color))
    player = result.state.players["player_1"]
    assert player.hand == ["hand-2"] and set(player.waiting_room) == {"hand-0", "hand-1"}
    modifiers = player.manual_modifiers
    assert [(m.modifier_type, m.color_slot, m.amount, m.target_card_instance_id, m.duration) for m in modifiers] == [
        ("heart", color, 2, "source-live", "live")]
    assert not result.state.pending_effects and result.state.phase == "yell_first"
    assert sum(e.event_type == "effect_cost_paid" for e in result.events) == 1
    before = match_state_hash(result.state)
    with pytest.raises(IllegalActionError):
        action = _resolve(state, selected_card_instance_ids=["hand-0", "hand-1"], selected_color_slot=color)
        action.expected_revision = result.state.revision
        apply_action(result.state, action)
    assert match_state_hash(result.state) == before


@pytest.mark.parametrize("cards,color", [([], "heart01"), (["hand-0"], "heart01"),
    (["hand-0", "hand-0"], "heart01"), (["hand-0", "hand-1", "hand-2"], "heart01"),
    (["hand-0", "opponent-secret"], "heart01"), (["hand-0", "source-live"], "heart01"),
    (["hand-0", "deck-member-1"], "heart01"), (["hand-0", "missing"], "heart01"),
    (["hand-0", "hand-1"], None), (["hand-0", "hand-1"], "heart0"),
    (["hand-0", "hand-1"], "heart07")])
def test_invalid_payment_or_color_is_atomic(cards, color):
    state = _begin(_state()).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, selected_card_instance_ids=cards, selected_color_slot=color))
    assert match_state_hash(state) == before


def test_declining_optional_effect_pays_nothing_and_advances():
    state = _begin(_state()).state
    result = apply_action(state, _resolve(state, accepted=False))
    assert result.state.players["player_1"].hand == state.players["player_1"].hand
    assert not result.state.players["player_1"].manual_modifiers and not result.state.pending_effects
    assert any(e.event_type == "effect_declined" for e in result.events)


@pytest.mark.parametrize("hand", [0, 1])
def test_insufficient_hand_does_not_create_an_unpayable_prompt(hand):
    result = _begin(_state(hand=hand))
    assert not result.state.pending_effects and result.state.phase == "yell_first"
    assert len(result.state.players["player_1"].hand) == hand
    assert any(e.event_type == "effect_not_activatable" and e.data.get("effect_id") == EFFECT for e in result.events)


def _control_departure_state():
    state = _state()
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id="AUDIT-control:1", card_code="AUDIT-control", choice=None, cost_choice=None, cost=[],
               actions=[{"action_type": "manual_resolution"}], execution_mode="manual_resolution",
               simulation_support="manual_resolution", review_status="parsed_draft", is_optional=False)
    control = EffectDefinition.model_validate(raw)
    state.effect_definitions[control.effect_id] = control
    state.cards["live-1"].card.effect_ids = [control.effect_id]
    return _begin(state).state


@pytest.mark.parametrize("reenter", [False, True])
def test_earlier_ordered_ability_departure_does_not_buff_same_id_new_object(reenter):
    state = _control_departure_state()
    control = next(i for i in state.pending_effects if i.effect_id == "AUDIT-control:1")
    adjustments = [{"adjustment_type": "move_card", "target_player_id": "player_1",
                    "target_card_instance_id": "source-live", "to_zone": zone}
                   for zone in (["waiting_room", "member_center"] if reenter else ["waiting_room"])]
    moved = apply_action(state, ActionRequest(action_type="manual_adjustment", player_id="player_1",
        expected_revision=state.revision, payload={"source_invocation_id": control.invocation_id,
            "source_effect_id": control.effect_id, "source_card_instance_id": "live-1", "adjustments": adjustments})).state
    assert moved.pending_effects[0].trigger_data["original_source_stage_object_departed"] is True
    result = apply_action(moved, _resolve(moved, selected_card_instance_ids=["hand-0", "hand-1"], selected_color_slot="heart04"))
    assert not result.state.players["player_1"].manual_modifiers and not result.state.pending_effects
    assert len(result.state.players["player_1"].hand) == 1
    assert any(e.data.get("reason") == "original_source_stage_member_departed" for e in result.events)


def test_live_end_and_target_departure_clear_modifier_without_affecting_base_hearts():
    state = _begin(_state()).state
    state = apply_action(state, _resolve(state, selected_card_instance_ids=["hand-0", "hand-1"], selected_color_slot="heart04")).state
    base = dict(state.cards["source-live"].card.basic_hearts)
    ended = state.model_copy(deep=True)
    ended.phase, ended.active_player_id = "live_judgment", None
    ended = apply_action(ended, ActionRequest(action_type="advance_phase", expected_revision=ended.revision)).state
    assert not ended.players["player_1"].manual_modifiers
    moved = apply_action(state, ActionRequest(action_type="manual_adjustment", player_id="player_1",
        expected_revision=state.revision, payload={"adjustments": [{"adjustment_type": "move_card",
            "target_player_id": "player_1", "target_card_instance_id": "source-live", "to_zone": "waiting_room"}]})).state
    assert not moved.players["player_1"].manual_modifiers
    assert ended.cards["source-live"].card.basic_hearts == moved.cards["source-live"].card.basic_hearts == base


@pytest.mark.parametrize("legacy", [False, True])
def test_sql_replay_new_execution_and_old_manual_snapshot(tmp_path, legacy):
    state = _state(legacy=legacy)
    assert MatchState.model_validate_json(state.model_dump_json()) == state
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    started = repository.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id="player_1", expected_revision=0))
    action = _resolve(started.state, selected_card_instance_ids=["hand-0", "hand-1"], selected_color_slot="heart05")
    if legacy:
        assert "source_object_policy" not in state.effect_definitions[EFFECT].model_dump_json()
        with pytest.raises(IllegalActionError, match="manual_resolution"):
            repository.apply(state.match_id, action)
        result = started
    else:
        result = repository.apply(state.match_id, action)
    replay = repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")
    for viewer, secret in [("player_1", "opponent-secret"), ("player_2", "hand-2")]:
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        assert secret not in payload["state"]["cards"]


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_policies_choose_only_native_cost_color_or_decline_without_private_identity(policy):
    state = _begin(_state()).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision) and decision.action.action_type == "resolve_effect"
    changed = state.model_copy(deep=True)
    changed.cards["opponent-secret"].card.card_code = "PRIVATE-CHANGED"
    changed.cards["opponent-secret"].card.basic_hearts = {"heart06": 99}
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}).action == decision.action
    result = apply_action(state, decision.action)
    assert not result.state.pending_effects


@pytest.mark.parametrize("defect", ["amount", "target", "cost", "choice", "trigger", "mandatory"])
def test_source_policy_rejects_unsupported_semantics(defect):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    if defect == "amount": raw["actions"][0]["amount"] = 3
    elif defect == "target": raw["actions"][0]["target"] = "selected"
    elif defect == "cost": raw["cost_choice"]["maximum"] = 3
    elif defect == "choice": raw["choice"]["color_slots"] = ["heart0"]
    elif defect == "trigger": raw["trigger"] = "member_played"
    else: raw["is_optional"] = False
    with pytest.raises(ValueError, match="Heart source policy"):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("effect_id", ["PL!-sd1-003:2", "PL!HS-bp1-006:2", "PL!N-bp4-011:1", "PL!S-bp5-005:1"])
def test_existing_cost_and_color_effects_expose_both_controls(effect_id):
    from loveca.simulation.engine import _effect_resolution_options
    effect = next(e for e in load_effect_registry().effects if e.effect_id == effect_id)
    state = _minimal_effect_state(effect)
    options = _effect_resolution_options(state, state.pending_effects[0])
    assert options["choice_type"] == effect.cost_choice.choice_type
    assert options["requires_color_choice"] is True
    assert options["color_slots"] == effect.choice.color_slots


def test_missing_original_source_snapshot_rejects_atomically():
    state = _begin(_state()).state
    state.pending_effects[0].trigger_data.pop("original_source_stage_object")
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError, match="snapshot is missing"):
        apply_action(state, _resolve(state, selected_card_instance_ids=["hand-0", "hand-1"], selected_color_slot="heart06"))
    assert match_state_hash(state) == before


def test_old_structured_snapshot_without_policy_keeps_shape_and_action_behavior():
    state = _state()
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw["actions"][0].pop("source_object_policy")
    state.effect_definitions[EFFECT] = EffectDefinition.model_validate(raw)
    restored = MatchState.model_validate_json(state.model_dump_json())
    assert match_state_hash(restored) == match_state_hash(state)
    started = _begin(restored).state
    assert "original_source_stage_object" not in started.pending_effects[0].trigger_data
    result = apply_action(started, _resolve(started, selected_card_instance_ids=["hand-0", "hand-1"], selected_color_slot="heart02"))
    assert result.state.players["player_1"].manual_modifiers[0].amount == 2


@pytest.mark.parametrize("reenter", [False, True])
def test_sql_replay_preserves_source_departure_identity(tmp_path, reenter):
    state = _control_departure_state()
    control = next(i for i in state.pending_effects if i.effect_id == "AUDIT-control:1")
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    moved = repository.apply(state.match_id, ActionRequest(action_type="manual_adjustment", player_id="player_1",
        expected_revision=state.revision, payload={"source_invocation_id": control.invocation_id,
            "source_effect_id": control.effect_id, "source_card_instance_id": "live-1",
            "adjustments": [{"adjustment_type": "move_card", "target_player_id": "player_1",
                "target_card_instance_id": "source-live", "to_zone": zone}
                for zone in (["waiting_room", "member_center"] if reenter else ["waiting_room"])]})).state
    result = repository.apply(state.match_id, _resolve(moved, selected_card_instance_ids=["hand-0", "hand-1"], selected_color_slot="heart06"))
    assert not result.state.players["player_1"].manual_modifiers
    replay = repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")


@pytest.mark.parametrize("zone", ["hand", "waiting_room", "success_live_area"])
def test_live_start_does_not_trigger_member_outside_stage(zone):
    state = _state()
    state.players["player_1"].member_area["center"] = None
    getattr(state.players["player_1"], zone).append("source-live")
    result = _begin(state)
    assert not result.state.pending_effects
    assert not any(e.data.get("effect_id") == EFFECT for e in result.events)
