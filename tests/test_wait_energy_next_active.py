import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_moved_source_ready import _manual
from test_nijigasaki_inspection import _candidate, _play, _resolve
from test_nijigasaki_inspection import _state as _base_state

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, EffectInvocation, ManualModifier
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!SP-bp7-017"
EFFECT = CODE + ":1"
RULE_REFERENCE_IDS = ("4.1.4", "4.7.2", "4.7.3", "7.1.2", "7.3.3", "7.4.1", "9.7.7")


def _state(*, legacy=False):
    state = _base_state(CODE)
    if not legacy:
        state.effect_definitions[EFFECT] = EffectDefinition.model_validate(_candidate(CODE).to_registry_entry())
    else:
        raw = state.effect_definitions[EFFECT].model_dump(mode="json")
        raw.update(actions=[{"action_type": "manual_resolution"}], choice=None,
                   execution_mode="manual_resolution", simulation_support="manual_resolution", review_status="parsed_draft",
                   source_reference="Official card text; timing-only manual fallback pending structured effect modeling")
        state.effect_definitions[EFFECT] = EffectDefinition.model_validate(raw)
    for key in ["new-energy", "hidden-energy"]:
        card = state.cards["energy-0"].model_copy(deep=True)
        card.instance_id, card.face_up = key, False
        state.cards[key] = card
    state.players["player_1"].energy_deck = ["new-energy", "hidden-energy"]
    state.stage_departure_policy = "clear_departed_card_modifiers"
    state.effect_order_policy = "ap_nap_player_choice"
    return state


def _event(result):
    return next(e for e in result.events if e.event_type == "effect_wait_energy_next_active_resolved")


def test_native_onplay_places_only_new_wait_energy_and_records_next_turn():
    state = _state()
    before = match_state_hash(state)
    result = apply_action(state, _play(state))
    assert match_state_hash(state) == before
    player = result.state.players["player_1"]
    assert player.energy_area[-1] == "new-energy" and player.energy_deck == ["hidden-energy"]
    assert result.state.cards["new-energy"].orientation == "wait"
    assert _event(result).data["affected_energy_instance_ids"] == ["new-energy"]
    assert _event(result).data["target_turn"] == state.turn_number + 1
    assert not result.state.pending_effects


def _phase_action(state):
    allowed = {"advance_phase", "end_main_phase", "set_live_cards", "start_next_turn"}
    legal = next(a for a in generate_legal_actions(state) if a.action_type in allowed)
    return ActionRequest(action_type=legal.action_type, player_id=legal.player_id,
        expected_revision=state.revision, payload={"card_instance_ids": []} if legal.action_type == "set_live_cards" else {})


def _walk(state, predicate, *, repo=None):
    for _ in range(80):
        if predicate(state):
            return state
        action = _phase_action(state)
        state = (repo.apply(state.match_id, action) if repo else apply_action(state, action)).state
    raise AssertionError("phase traversal did not reach target")


def _play_owner(state):
    owner = state.cards["source-live"].owner_id
    action = _play(state)
    action.player_id = owner
    action.payload["energy_instance_ids"] = list(state.players[owner].energy_area)
    return action


def _owned_state(owner, first):
    state = _state()
    if owner == "player_2":
        state.players["player_1"], state.players["player_2"] = state.players["player_2"], state.players["player_1"]
        for key, player in state.players.items():
            player.player_id = key
        for card in state.cards.values():
            card.owner_id = "player_2" if card.owner_id == "player_1" else "player_1"
    state.first_player_id, state.second_player_id = first, "player_2" if first == "player_1" else "player_1"
    state.phase = "first_main" if owner == first else "second_main"
    state.active_player_id = owner
    return state


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("first", ["player_1", "player_2"])
def test_native_full_turns_skip_only_new_energy_once_and_sql_replay(tmp_path, owner, first):
    state = _owned_state(owner, first)
    repo = MatchRepository(tmp_path / "turns.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play_owner(state)).state
    ended = _walk(played, lambda s: s.phase == "turn_complete", repo=repo)
    assert len(ended.players[owner].manual_modifiers) == 1
    next_turn = repo.apply(state.match_id, _phase_action(ended)).state
    active = _walk(next_turn, lambda s: s.phase.endswith("_active") and s.active_player_id == owner, repo=repo)
    result = repo.apply(state.match_id, _phase_action(active))
    assert result.state.cards["new-energy"].orientation == "wait"
    assert result.state.cards["energy-0"].orientation == "active"
    assert not result.state.players[owner].manual_modifiers
    assert next(e for e in result.events if e.event_type == "cards_readied").data["skipped_instance_ids"] == ["new-energy"]
    ended = _walk(result.state, lambda s: s.phase == "turn_complete", repo=repo)
    next_turn = repo.apply(state.match_id, _phase_action(ended)).state
    active = _walk(next_turn, lambda s: s.phase.endswith("_active") and s.active_player_id == owner, repo=repo)
    final = repo.apply(state.match_id, _phase_action(active))
    assert final.state.cards["new-energy"].orientation == "active"
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


def test_control_multi_player_entry_before_owner_current_active_keeps_next_turn_block(tmp_path):
    from test_multi_player_entry import _state as multi_state
    from test_multi_player_entry import _action as multi_action
    state = multi_state()
    raw = state.effect_definitions["PL!-pb1-018:1"].model_dump(mode="json")
    raw.update(effect_id="AUDIT-before-active-entry:1", card_code="AUDIT-entry",
               label_ja="AUDIT: both-player entry before the current Active Phase")
    raw["choice"]["maximum_cost"] = 11
    control = EffectDefinition.model_validate(raw)
    state.effect_definitions[control.effect_id] = control
    state.pending_effects[0].effect_id = control.effect_id
    source = _state()
    state.effect_definitions[EFFECT] = source.effect_definitions[EFFECT]
    state.cards["opponent-target"].card = source.cards["source-live"].card.model_copy(deep=True)
    for key in ["new-energy", "hidden-energy"]:
        state.cards[key] = source.cards[key].model_copy(update={"owner_id": "player_2"}, deep=True)
    state.players["player_2"].energy_deck = ["new-energy", "hidden-energy"]
    spender = source.cards["cost"].model_copy(deep=True)
    spender.instance_id, spender.owner_id = "spend-member", "player_2"
    spender.card.cost = 1
    state.cards[spender.instance_id] = spender
    state.players["player_2"].hand.append(spender.instance_id)
    repo = MatchRepository(tmp_path / "other-main-entry.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    first = repo.apply(state.match_id, multi_action(state, "resolve_effect", invocation_id="multi-parent")).state
    second = repo.apply(state.match_id, multi_action(first, "resolve_effect_choice", selected_card_instance_id="target", slot="right")).state
    entry = repo.apply(state.match_id, multi_action(second, "resolve_effect_choice", "player_2", selected_card_instance_id="opponent-target", slot="left"))
    assert _event(entry).player_id == "player_2"
    active = _walk(entry.state, lambda s: s.phase == "second_active", repo=repo)
    current = repo.apply(state.match_id, _phase_action(active)).state
    assert current.cards["new-energy"].orientation == "active"
    assert len(current.players["player_2"].manual_modifiers) == 1
    main = _walk(current, lambda s: s.phase == "second_main", repo=repo)
    paid = repo.apply(state.match_id, ActionRequest(action_type="play_member", player_id="player_2",
        expected_revision=main.revision, payload={"card_instance_id": "spend-member", "slot": "right",
        "energy_instance_ids": ["new-energy"], "use_baton_touch": False})).state
    assert paid.cards["new-energy"].orientation == "wait"
    assert len(paid.players["player_2"].manual_modifiers) == 1
    ended = _walk(paid, lambda s: s.phase == "turn_complete", repo=repo)
    next_turn = repo.apply(state.match_id, _phase_action(ended)).state
    active = _walk(next_turn, lambda s: s.phase.endswith("_active") and s.active_player_id == "player_2", repo=repo)
    final = repo.apply(state.match_id, _phase_action(active))
    assert final.state.cards["new-energy"].orientation == "wait"
    assert not final.state.players["player_2"].manual_modifiers
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


def test_q280_ready_then_pay_does_not_remove_restriction():
    state = apply_action(_state(), _play(_state())).state
    changed = apply_action(state, _manual(state, [
        {"adjustment_type": "ready_energy", "target_card_instance_id": "new-energy"},
        {"adjustment_type": "pay_energy", "target_card_instance_id": "new-energy"},
    ])).state
    assert changed.cards["new-energy"].orientation == "wait"
    assert len(changed.players["player_1"].manual_modifiers) == 1
    changed.turn_number += 1
    changed.phase, changed.active_player_id = "first_active", "player_1"
    result = apply_action(changed, _phase_action(changed))
    assert result.state.cards["new-energy"].orientation == "wait"
    assert not result.state.players["player_1"].manual_modifiers


@pytest.mark.parametrize("zone", ["hand", "main_deck", "energy_deck", "waiting_room"])
@pytest.mark.parametrize("legacy_stage", [False, True])
def test_manual_energy_departure_and_same_id_return_do_not_inherit(zone, legacy_stage):
    state = apply_action(_state(), _play(_state())).state
    if legacy_stage:
        state.stage_departure_policy = None
    result = apply_action(state, _manual(state, [
        {"adjustment_type": "move_card", "target_card_instance_id": "new-energy", "to_zone": zone},
        {"adjustment_type": "move_card", "target_card_instance_id": "new-energy", "to_zone": "energy_area"},
    ]))
    assert not result.state.players["player_1"].manual_modifiers
    assert "new-energy" in result.state.players["player_1"].energy_area


def test_energy_area_noop_keeps_same_object_restriction():
    state = apply_action(_state(), _play(_state())).state
    result = apply_action(state, _manual(state, [{"adjustment_type": "move_card", "target_card_instance_id": "new-energy", "to_zone": "energy_area"}]))
    assert len(result.state.players["player_1"].manual_modifiers) == 1


def test_manual_attachment_and_return_create_new_object():
    state = apply_action(_state(), _play(_state())).state
    attached = apply_action(state, _manual(state, [{"adjustment_type": "attach_card_under_member",
        "target_card_instance_id": "new-energy", "target_slot": "center"}])).state
    assert not attached.players["player_1"].manual_modifiers
    returned = apply_action(attached, _manual(attached, [{"adjustment_type": "move_attached_card",
        "target_card_instance_id": "new-energy", "to_zone": "energy_area", "orientation": "wait"}]))
    assert not returned.state.players["player_1"].manual_modifiers


@pytest.mark.parametrize("operation", ["move_selected_energy_to_energy_deck", "attach_selected_under_source"])
def test_structured_energy_departure_sql_replay(tmp_path, operation):
    state = _state()
    repo = MatchRepository(tmp_path / "structured-move.sqlite3")
    played = apply_action(state, _play(state)).state
    raw = played.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id="AUDIT-energy-departure", execution_mode="prompt_then_resolve",
        actions=[{"action_type": operation}], choice={"choice_type": "card_from_zone", "zone": "energy_area",
        "card_type": "energy", "minimum": 1, "maximum": 1})
    effect = EffectDefinition.model_validate(raw)
    played.effect_definitions[effect.effect_id] = effect
    played.pending_effects = [EffectInvocation(invocation_id="departure", effect_id=effect.effect_id,
        player_id="player_1", source_card_instance_id="source-live", trigger_event="member_played")]
    repo.create_match(played, card_database_path=Path("data/loveca.sqlite3"))
    final = repo.apply(played.match_id, _resolve(played, selected_card_instance_ids=["new-energy"]))
    assert not final.state.players["player_1"].manual_modifiers
    assert "new-energy" not in final.state.players["player_1"].energy_area
    assert repo.replay(played.match_id)["metadata"]["deterministic_replay_verified"] is True


@pytest.mark.parametrize("movement", ["leave", "return", "position"])
def test_native_source_interference_still_places_energy(tmp_path, movement):
    state = _state()
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id="CONTROL", trigger="own_member_played", actions=[{"action_type": "manual_resolution"}],
        execution_mode="manual_resolution", simulation_support="manual_resolution")
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    observer = state.cards["tail"].model_copy(deep=True)
    observer.instance_id, observer.card.effect_ids = "observer", ["CONTROL"]
    state.cards[observer.instance_id] = observer
    state.players["player_1"].member_area["left"] = "observer"
    repo = MatchRepository(tmp_path / "source.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state)).state
    control = next(i for i in played.pending_effects if i.effect_id == "CONTROL")
    if movement == "position":
        adjustments = [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "right"}]
    else:
        adjustments = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"}]
        if movement == "return":
            adjustments.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_right"})
    final = repo.apply(state.match_id, _manual(played, adjustments, control))
    if final.state.pending_effects:
        final = repo.apply(state.match_id, _resolve(final.state))
    assert _event(final).data["affected_energy_instance_ids"] == ["new-energy"]
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


def test_empty_energy_deck_does_not_mark_existing_wait_energy():
    state = _state()
    state.players["player_1"].energy_deck = []
    result = apply_action(state, _play(state))
    assert not result.state.players["player_1"].manual_modifiers
    assert _event(result).data["affected_energy_instance_ids"] == []


@pytest.mark.parametrize("empty", [False, True])
def test_energy_placement_observer_runs_only_after_actual_placement(empty):
    state = _state()
    if empty:
        state.players["player_1"].energy_deck = []
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id="AUDIT-energy-observer", trigger="energy_placed_by_effect",
               actions=[{"action_type": "draw_card", "amount": 1}])
    observer_effect = EffectDefinition.model_validate(raw)
    state.effect_definitions[observer_effect.effect_id] = observer_effect
    observer = state.cards["tail"].model_copy(deep=True)
    observer.instance_id, observer.card.effect_ids = "observer", [observer_effect.effect_id]
    state.cards["observer"] = observer
    state.players["player_1"].member_area["left"] = "observer"
    result = apply_action(state, _play(state))
    triggered = [e for e in result.events if e.event_type == "effect_triggered" and e.data.get("effect_id") == observer_effect.effect_id]
    assert len(triggered) == int(not empty)
    assert ("good-member" in result.state.players["player_1"].hand) == (not empty)
    assert len(result.state.players["player_1"].manual_modifiers) == int(not empty)


@pytest.mark.parametrize("returning", [False, True])
def test_source_departure_after_grant_does_not_remove_energy_restriction(returning):
    state = apply_action(_state(), _play(_state())).state
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"}]
    if returning:
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_right"})
    result = apply_action(state, _manual(state, changes))
    assert len(result.state.players["player_1"].manual_modifiers) == 1


@pytest.mark.parametrize("legacy", [False, True])
def test_old_manual_and_new_snapshot_sql_replay(tmp_path, legacy):
    state = _state(legacy=legacy)
    repo = MatchRepository(tmp_path / "snapshot.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    final = repo.apply(state.match_id, _play(state))
    if legacy:
        assert final.state.pending_effects[0].effect_id == EFFECT
        final = repo.apply(state.match_id, _manual(final.state, [{"adjustment_type": "set_flag", "flag": "legacy-audit", "duration": "game"}], final.state.pending_effects[0]))
        assert final.state.effect_definitions[EFFECT].execution_mode == "manual_resolution"
        assert "new-energy" not in final.state.players["player_1"].energy_area
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_actual_play_hidden_energy_identity_and_input_unchanged(policy):
    state = _state()
    state.players["player_1"].hand = ["source-live"]
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision) and decision.action.action_type == "play_member"
    assert match_state_hash(state) == before
    changed = state.model_copy(deep=True)
    for key in ["opponent-secret", "new-energy", "hidden-energy", *state.players["player_1"].main_deck]:
        changed.cards[key].card.name_ja = changed.cards[key].card.card_code = "HIDDEN-CHANGED"
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}).action == decision.action
    assert _event(apply_action(state, decision.action)).data["affected_energy_instance_ids"] == ["new-energy"]


def test_dual_view_only_new_public_energy_not_hidden_remainder():
    result = apply_action(_state(), _play(_state()))
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        assert "new-energy" in payload["state"]["cards"]
        assert "hidden-energy" not in json.dumps(payload) and "AUDIT-tail" not in json.dumps(payload)
        if viewer == "player_1":
            assert "opponent-secret" not in json.dumps(payload)


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_isolated_pending_resolution(policy):
    state = _state()
    state.players["player_1"].hand.remove("source-live")
    state.players["player_1"].member_area["center"] = "source-live"
    state.pending_effects = [EffectInvocation(invocation_id="isolated", effect_id=EFFECT,
        source_card_instance_id="source-live", player_id="player_1", trigger_event="member_played")]
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision) and decision.action.action_type == "resolve_effect"
    assert match_state_hash(state) == before
    assert _event(apply_action(state, decision.action)).data["affected_energy_instance_ids"] == ["new-energy"]


def test_invalid_energy_card_type_is_atomic_before_native_cost_is_retained():
    state = _state()
    state.cards["new-energy"].card.card_type = "member"
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _play(state))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("change", [{"duration": "turn"}, {"flag": "other"}, {"modifier_type": "blade"},
    {"value": None}, {"value": {"policy": "other", "target_turn": 2}},
    {"value": {"policy": "placed_energy_next_turn_active", "target_turn": True}},
    {"target_card_instance_id": "source-live"}])
def test_unmatched_flags_do_not_block_ready(change):
    state = apply_action(_state(), _play(_state())).state
    original = state.players["player_1"].manual_modifiers[0]
    state.players["player_1"].manual_modifiers = [original.model_copy(update=change)]
    state.phase, state.active_player_id = "first_active", "player_1"
    state.turn_number += 1
    result = apply_action(state, _phase_action(state))
    assert result.state.cards["new-energy"].orientation == "active"


@pytest.mark.parametrize("target", [None, "energy-0"])
def test_legacy_skip_flags_keep_original_consumption_behavior(target):
    state = apply_action(_state(), _play(_state())).state
    state.players["player_1"].manual_modifiers.append(ManualModifier(modifier_id="old-flag", modifier_type="flag",
        flag="skip_next_active_phase_ready", duration="game", created_turn=state.turn_number,
        target_card_instance_id=target))
    state.turn_number += 1
    state.phase, state.active_player_id = "first_active", "player_1"
    result = apply_action(state, _phase_action(state))
    assert result.state.cards["new-energy"].orientation == "wait"
    assert result.state.cards["energy-0"].orientation == ("wait" if target else "active")
    assert bool(result.state.players["player_1"].manual_modifiers) == (target is None)


def test_expired_new_flag_is_not_carried_to_a_later_turn():
    state = apply_action(_state(), _play(_state())).state
    state.phase, state.active_player_id = "turn_complete", None
    state.next_first_player_id = "player_1"
    state.turn_number += 1
    result = apply_action(state, _phase_action(state))
    assert result.state.turn_number == 3
    assert not result.state.players["player_1"].manual_modifiers


def test_new_operation_cannot_be_a_cost():
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(cost=raw["actions"], actions=[{"action_type": "draw_card", "amount": 1}])
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("change", [{"amount": 2}, {"target": "opponent"}, {"orientation": "active"}, {"value": True}])
def test_bounded_operation_rejects_expansion(change):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw["actions"][0].update(change)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("change", [{"is_optional": True}, {"trigger": "live_started"}, {"duration": "live"},
    {"frequency_limit": "once_per_turn"}, {"condition": {"minimum_energy": 1}}, {"choice": {"choice_type": "choose_color"}}])
def test_bounded_definition_rejects_expansion(change):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(change)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("change", [{"card_code": "OTHER"}, {"text_revision_id": 905}, {"raw_text_hash": "other"},
    {"raw_effect_text_ja": "【登場】エネルギーカードを1枚置く。"}])
def test_exact_generator_rejects_unreviewed_variants(change):
    from loveca.simulation.effect_candidates import WAIT_ENERGY_NEXT_ACTIVE_TEXT, _onplay_wait_energy_next_active
    row = {"card_code": CODE, "text_revision_id": 904, "raw_effect_text_ja": WAIT_ENERGY_NEXT_ACTIVE_TEXT,
           "raw_text_hash": _state().effect_definitions[EFFECT].raw_text_hash}
    assert _onplay_wait_energy_next_active({**row, **change}) is None
