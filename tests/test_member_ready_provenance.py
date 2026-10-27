from pathlib import Path

import pytest
from test_printemps_ready_history_boundary import _state as _boundary_state, _advance, _manual, _repo, _replay
from test_mirakura_front_position_boundary import _swap_roles

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, MatchState
from loveca.simulation.online import match_state_hash
from loveca.simulation.ready_history import OPERATION, SOURCE_KEY, current_effect_readied_members
from loveca.webapp import _match_state_payload

PROBE = "UNREGISTERED-READY:1"


def _state(*, owner="player_1", waits=3, legacy=False, selected=False, repeat=False):
    state = _boundary_state(waits=waits, control=True, ready=True)
    raw = state.effect_definitions["PL!-pb1-028:1"].model_dump(mode="json")
    raw.update(effect_id=PROBE, card_code="UNREGISTERED-READY", label_ja="AUDIT provenance probe, not a registered ability",
               frequency_limit="none", execution_mode="prompt_then_resolve", cost=[], cost_choice=None,
               follow_up_choice=None, duration=None, condition={}, is_optional=False,
               actions=[{"action_type": "ready_member" if legacy else OPERATION, "target": "selected" if selected else "self_stage_all"}],
               choice={"choice_type": "member_from_stage", "zone": "stage", "card_type": "member", "minimum": 1, "maximum": 1} if selected else None)
    if repeat:
        raw["actions"] += [{"action_type": "apply_wait_member", "target": "selected"},
                           {"action_type": OPERATION, "target": "selected"}]
    state.effect_definitions[PROBE] = EffectDefinition.model_validate(raw)
    state.cards["live-1"].card.effect_ids = [PROBE, "CONTROL"]
    if owner == "player_2":
        state = _swap_roles(state)
        state.phase, state.active_player_id = "performance_second", owner
    return state


def _resolve(state, ids=None):
    inv = next(i for i in state.pending_effects if i.effect_id == PROBE)
    return ActionRequest(action_type="resolve_effect", player_id=inv.player_id, expected_revision=state.revision,
        payload={"invocation_id": inv.invocation_id, **({"selected_card_instance_ids": ids} if ids is not None else {})})


def _members(state, owner="player_1", unit="printemps"):
    return current_effect_readied_members(state, owner, unit_key=unit)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("waits", [0, 1, 3])
def test_actual_changes_and_immutable_provenance_sql(tmp_path, owner, waits):
    state = _state(owner=owner, waits=waits)
    before = match_state_hash(state)
    repo = _repo(state, tmp_path)
    begun = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _resolve(begun))
    assert match_state_hash(state) == before
    assert len(_members(result.state, owner)) == waits
    history = result.state.member_ready_history
    assert len(history.events) == waits and history.coverage_complete
    for event in history.events:
        assert event.source.effect_id == PROBE
        assert event.source.effect_player_id == event.source.owner_id == owner
        assert event.source.unit_keys == ["printemps"] and event.source.work_keys == ["love_live"]
        assert event.source.turn_number == result.state.turn_number
    assert result.state.players[owner].effect_ready_flags_this_turn == (["love_live:member"] if waits else [])
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("movement", ["hand", "main_deck", "return", "same_area"])
def test_pending_source_departure_and_return_use_last_information_sql(tmp_path, owner, movement):
    state = _state(owner=owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "live-1",
                "to_zone": "live_area" if movement == "same_area" else "main_deck" if movement == "main_deck" else "hand"}]
    if movement == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "live-1", "to_zone": "live_area"})
    moved = repo.apply(state.match_id, _manual(current, "CONTROL", changes)).state
    result = repo.apply(state.match_id, _resolve(moved))
    assert len(_members(result.state, owner)) == 3
    assert all(e.source.departed is (movement != "same_area") for e in result.state.member_ready_history.events)
    for viewer in ["player_1", "player_2"]:
        before = match_state_hash(result.state)
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        assert "member_ready_history" not in payload["state"]
        assert all(SOURCE_KEY not in i["trigger_data"] for i in payload["state"]["pending_effects"])
        for p in result.state.players.values():
            assert not any(i in payload["state"]["cards"] for i in p.main_deck)
            if p.player_id != viewer:
                assert not any(i in payload["state"]["cards"] for i in p.hand)
        assert match_state_hash(result.state) == before
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("movement", ["hand", "main_deck", "return", "position", "formation"])
def test_original_target_object_expires_on_departure_not_stage_movement_sql(tmp_path, owner, movement):
    state = _state(owner=owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    current = repo.apply(state.match_id, _resolve(current)).state
    old_token = current.member_ready_history.object_ids["target"]
    if movement == "position":
        changes = [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "right"}]
    elif movement == "formation":
        changes = [{"adjustment_type": "formation_change", "slot_assignments": {"left": "target", "center": "wrong-work", "right": "source-live"}}]
    else:
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": "target", "to_zone": "main_deck" if movement == "main_deck" else "hand"}]
        if movement == "return":
            changes.append({"adjustment_type": "move_card", "target_card_instance_id": "target", "to_zone": "member_center"})
    result = repo.apply(state.match_id, _manual(current, "CONTROL", changes))
    retained = movement in {"position", "formation"}
    assert ("target" in _members(result.state, owner)) is retained
    assert (result.state.member_ready_history.object_ids.get("target") == old_token) is retained
    _replay(repo, result.state)


@pytest.mark.parametrize("legacy", [False, True])
def test_legacy_snapshot_has_no_new_json_keys_and_replays_sql(tmp_path, legacy):
    state = _state(legacy=legacy)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _resolve(current))
    assert ("member_ready_history" not in result.state.model_dump(mode="json")) is legacy
    if legacy:
        assert _members(result.state) is None
        assert all(SOURCE_KEY not in i.trigger_data for i in current.pending_effects)
    _replay(repo, result.state)


def test_repeat_ready_operations_count_the_original_member_once_sql(tmp_path):
    state = _state(selected=True, repeat=True)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _resolve(current, ["target"]))
    assert _members(result.state) == ["target"]
    assert len(result.state.member_ready_history.events) == 1
    assert result.state.cards["target"].orientation == "active"
    _replay(repo, result.state)


def test_actual_active_phase_is_not_a_card_effect_sql(tmp_path):
    state = _state()
    state.phase, state.active_player_id = "first_active", "player_1"
    repo = _repo(state, tmp_path)
    result = repo.apply(state.match_id, _advance(state))
    assert all(result.state.cards[i].orientation == "active" for i in result.state.players["player_1"].member_area.values())
    assert _members(result.state) == []
    assert not result.state.member_ready_history.events
    _replay(repo, result.state)


def test_native_next_turn_clears_history_not_old_snapshot_shape_sql(tmp_path):
    state = _state()
    begun = apply_action(state, _advance(state)).state
    current = apply_action(begun, _resolve(begun)).state
    current.pending_effects = []
    current.phase, current.next_first_player_id = "turn_complete", "player_1"
    repo = _repo(current, tmp_path)
    result = repo.apply(current.match_id, ActionRequest(action_type="start_next_turn", expected_revision=current.revision))
    assert result.state.member_ready_history.turn_number == current.turn_number + 1
    assert not result.state.member_ready_history.events and _members(result.state) == []
    _replay(repo, result.state)


def test_source_last_info_is_not_returned_new_card_info():
    state = _state()
    begun = apply_action(state, _advance(state)).state
    begun.cards["live-1"].card.unit_keys = ["lily_white"]
    moved = apply_action(begun, _manual(begun, "CONTROL", [
        {"adjustment_type": "move_card", "target_card_instance_id": "live-1", "to_zone": "hand"},
        {"adjustment_type": "move_card", "target_card_instance_id": "live-1", "to_zone": "live_area"},
    ])).state
    moved.cards["live-1"].card.unit_keys = ["printemps"]
    moved.cards["live-1"].card.work_keys = ["hasunosora"]
    result = apply_action(moved, _resolve(moved)).state
    assert _members(result) == []
    assert len(_members(result, unit="lily_white")) == 3
    assert result.players["player_1"].effect_ready_flags_this_turn == ["love_live:member"]


def test_legacy_producer_in_new_snapshot_makes_coverage_unknown():
    state = _state()
    raw = state.effect_definitions[PROBE].model_dump(mode="json")
    raw.update(effect_id="LEGACY-READY", actions=[{"action_type": "ready_member", "target": "self_stage_all"}])
    state.effect_definitions["LEGACY-READY"] = EffectDefinition.model_validate(raw)
    state.cards["live-1"].card.effect_ids.append("LEGACY-READY")
    current = apply_action(state, _advance(state)).state
    inv = next(i for i in current.pending_effects if i.effect_id == "LEGACY-READY")
    result = apply_action(current, ActionRequest(action_type="resolve_effect", player_id="player_1", expected_revision=current.revision,
        payload={"invocation_id": inv.invocation_id})).state
    assert not result.member_ready_history.coverage_complete and _members(result) is None


def test_late_snapshot_cannot_claim_complete_prior_turn_history():
    state = _state()
    state.revision = 5
    current = apply_action(state, _advance(state)).state
    result = apply_action(current, _resolve(current)).state
    assert not result.member_ready_history.coverage_complete and _members(result) is None


def test_source_unit_not_target_unit_controls_qualification():
    state = _state()
    state.cards["target"].card.unit_keys = ["bibi"]
    current = apply_action(state, _advance(state)).state
    result = apply_action(current, _resolve(current)).state
    assert "target" in _members(result)
    assert _members(result, unit="bibi") == []
    assert current_effect_readied_members(result, "player_1", work_key="nijigasaki") == []
    assert current_effect_readied_members(result, "player_2", unit_key="printemps") == []


@pytest.mark.parametrize("movement", ["hand", "return"])
def test_stage_source_lki_after_native_pending_movement_sql(tmp_path, movement):
    state = _state()
    state.cards["source-live"].card.effect_ids = [PROBE]
    state.cards["live-1"].card.effect_ids = ["CONTROL"]
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"}]
    if movement == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_left"})
    moved = repo.apply(state.match_id, _manual(current, "CONTROL", changes))
    result = (repo.apply(state.match_id, _resolve(moved.state))
              if any(i.effect_id == PROBE for i in moved.state.pending_effects) else moved)
    assert len(_members(result.state)) == 2 + int(movement == "return")
    assert all(e.source.zone == "stage" and e.source.departed for e in result.state.member_ready_history.events)
    _replay(repo, result.state)


def test_attached_member_is_not_a_ready_target():
    state = _state(selected=True)
    state.players["player_1"].hand.remove("held")
    state.players["player_1"].member_area_attachments["center"] = ["held"]
    state.cards["held"].orientation = "wait"
    current = apply_action(state, _advance(state)).state
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        apply_action(current, _resolve(current, ["held"]))
    assert match_state_hash(current) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_no_cost_native_activation_captures_its_actual_source_sql(tmp_path, owner):
    state = _state(selected=True)
    raw = state.effect_definitions[PROBE].model_dump(mode="json")
    raw.update(effect_type="activated", timing="activated_main", trigger="player_activation")
    state.effect_definitions[PROBE] = EffectDefinition.model_validate(raw)
    state.cards["source-live"].card.effect_ids = [PROBE]
    state.cards["live-1"].card.effect_ids = []
    state.phase, state.active_player_id = "first_main", "player_1"
    if owner == "player_2":
        state = _swap_roles(state)
    repo = _repo(state, tmp_path)
    result = repo.apply(state.match_id, ActionRequest(action_type="activate_effect", player_id=owner,
        expected_revision=state.revision, payload={"effect_id": PROBE, "source_card_instance_id": "source-live",
                                                 "energy_instance_ids": []}))
    if result.state.pending_effects:
        result = repo.apply(state.match_id, _resolve(result.state, ["target"]))
    assert _members(result.state, owner) == ["target"]
    assert result.state.member_ready_history.events[0].source.instance_id == "source-live"
    _replay(repo, result.state)


@pytest.mark.parametrize("payload", [{SOURCE_KEY: {}}, {"member_ready_history": {}}, {"energy_instance_ids": ["fake"]}, {"accepted": 1}])
def test_client_cannot_supply_provenance_or_pay_unmodeled_cost(payload):
    state = apply_action(_state(), _advance(_state())).state
    action = _resolve(state)
    action.payload.update(payload)
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, action)
    assert match_state_hash(state) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_pending_source_metadata_is_private_in_all_player_and_provider_views(owner):
    import json
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    state = _state(owner=owner)
    current = apply_action(state, _advance(state)).state
    moved = apply_action(current, _manual(current, "CONTROL", [
        {"adjustment_type": "move_card", "target_card_instance_id": "live-1", "to_zone": "main_deck"}
    ])).state
    before = match_state_hash(moved)
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(moved, events=[], legal_actions=generate_legal_actions(moved), player_id=viewer)
        assert SOURCE_KEY not in json.dumps(payload) and "member_ready_history" not in payload["state"]
    for builder in [build_api_play_context, build_agent_context]:
        payload = builder(moved, generate_legal_actions(moved))
        assert SOURCE_KEY not in json.dumps(payload)
        assert "member_ready_history" not in json.dumps(payload)
    assert match_state_hash(moved) == before


def test_returned_member_requires_a_new_ready_object_token_sql(tmp_path):
    state = _state(selected=True)
    raw = state.effect_definitions[PROBE].model_dump(mode="json")
    raw.update(effect_id="SECOND-PROBE", actions=[{"action_type": "apply_wait_member", "target": "selected"},
        {"action_type": OPERATION, "target": "selected"}])
    state.effect_definitions["SECOND-PROBE"] = EffectDefinition.model_validate(raw)
    state.cards["live-1"].card.effect_ids.append("SECOND-PROBE")
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    current = repo.apply(state.match_id, _resolve(current, ["target"])).state
    old_token = current.member_ready_history.object_ids["target"]
    current = repo.apply(state.match_id, _manual(current, "CONTROL", [
        {"adjustment_type": "move_card", "target_card_instance_id": "target", "to_zone": "hand"},
        {"adjustment_type": "move_card", "target_card_instance_id": "target", "to_zone": "member_center"}
    ])).state
    inv = next(i for i in current.pending_effects if i.effect_id == "SECOND-PROBE")
    result = repo.apply(state.match_id, ActionRequest(action_type="resolve_effect", player_id="player_1", expected_revision=current.revision,
        payload={"invocation_id": inv.invocation_id, "selected_card_instance_ids": ["target"]}))
    assert result.state.member_ready_history.object_ids["target"] != old_token
    assert len(result.state.member_ready_history.events) == 2 and _members(result.state) == ["target"]
    _replay(repo, result.state)


def test_prototype_cannot_be_used_as_payment_or_with_unmodeled_costs():
    from pydantic import ValidationError
    raw = _state().effect_definitions[PROBE].model_dump(mode="json")
    for cost in [[{"action_type": OPERATION, "target": "source"}], [{"action_type": "apply_wait", "target": "source"}]]:
        bad = dict(raw, cost=cost)
        with pytest.raises(ValidationError):
            EffectDefinition.model_validate(bad)


def test_legacy_namespace_does_not_require_opt_in_history():
    from types import SimpleNamespace
    from loveca.simulation.ready_history import mark_ready_departure
    from loveca.simulation.engine import _record_effect_ready_flag
    state = _state()
    legacy = SimpleNamespace(cards=state.cards)
    mark_ready_departure(legacy, ["target"], "stage")
    assert current_effect_readied_members(legacy, "player_1") is None
    _record_effect_ready_flag(legacy, state.players["player_1"], SimpleNamespace(source_card_instance_id="live-1"),
                             ready_type="member", previous_orientation="wait")
    assert state.players["player_1"].effect_ready_flags_this_turn == ["love_live:member"]


@pytest.mark.parametrize("field,value", [("turn_number", True), ("policy", "old"), ("coverage_complete", 1)])
def test_strict_versioned_history_rejects_malformed_snapshot(field, value):
    from pydantic import ValidationError
    raw = apply_action(_state(), _advance(_state())).state.model_dump(mode="json")
    raw["member_ready_history"][field] = value
    with pytest.raises(ValidationError):
        MatchState.model_validate(raw)


@pytest.mark.parametrize("field,value", [("turn_number", True), ("effect_id", "WRONG"), ("invocation_id", "WRONG"), ("departed", 1)])
def test_missing_or_forged_source_context_rejected_atomically(field, value):
    state = apply_action(_state(), _advance(_state())).state
    inv = next(i for i in state.pending_effects if i.effect_id == PROBE)
    inv.trigger_data[SOURCE_KEY][field] = value
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_actual_probe_choice_and_hidden_invariance(owner, policy):
    initial = _state(owner=owner, selected=True)
    initial.cards["source-live"].card.effect_ids = []
    initial.cards["live-1"].card.effect_ids = [PROBE]
    state = apply_action(initial, _advance(initial)).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    changed = state.model_copy(deep=True)
    for p in changed.players.values():
        for key in list(p.main_deck + (p.hand if p.player_id != owner else [])):
            item = changed.cards.pop(key)
            name = "HIDDEN-" + key
            item.instance_id = name
            item.card.name_ja = item.card.card_code = "HIDDEN"
            changed.cards[name] = item
            p.main_deck = [name if i == key else i for i in p.main_deck]
            p.hand = [name if i == key else i for i in p.hand]
    changed_before = match_state_hash(changed)
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner}).action == decision.action
    assert match_state_hash(state) == before and match_state_hash(changed) == changed_before
    result = apply_action(state, decision.action).state
    assert _members(result, owner) == decision.action.payload["selected_card_instance_ids"]
