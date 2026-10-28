import json
import pytest
from pydantic import ValidationError

from test_ready_source_wait_cost_probe import _state as _v1_state, PROBE as V1_PROBE, _control_checkpoint
from test_printemps_ready_history_boundary import _repo, _replay, _manual
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import apply_action, generate_legal_actions, IllegalActionError, StaleRevisionError
from loveca.simulation.models import ActionRequest
from loveca.simulation.online import match_state_hash
from loveca.simulation.ready_history import COST_KEY, SOURCE_KEY, current_effect_readied_members
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIBlocker, SimpleAIPolicy
from loveca.webapp import _match_state_payload

PROBE = "UNREGISTERED-SOURCE-WAIT-READY-V2:1"
OPERATION = "ready_member_after_source_wait_provenance_v2"


def _state(owner="player_1", *, active=False, version="v2"):
    state = _v1_state(owner, legacy=version == "legacy")
    if version == "v2":
        raw = state.effect_definitions.pop(V1_PROBE).model_dump(mode="json")
        raw.update(effect_id=PROBE, card_code="UNREGISTERED-SOURCE-WAIT-READY-V2",
            label_ja="AUDIT v2 source Wait then another Member, any orientation")
        raw["actions"][0]["action_type"] = OPERATION
        raw["choice"]["orientation"] = None
        state.effect_definitions[PROBE] = EffectDefinition.model_validate(raw)
        state.cards["source-live"].card.effect_ids = [PROBE]
    if active:
        for key in ["target", "wrong-work"]: state.cards[key].orientation = "active"
    return state


def _activate(state):
    key = PROBE if PROBE in state.effect_definitions else V1_PROBE
    return ActionRequest(action_type="activate_effect", player_id=state.active_player_id, expected_revision=state.revision,
        payload={"effect_id": key, "source_card_instance_id": "source-live", "energy_instance_ids": []})


def _resolve(state, ids=None):
    inv = next(i for i in state.pending_effects if i.effect_id in {PROBE, V1_PROBE})
    return ActionRequest(action_type="resolve_effect", player_id=inv.player_id, expected_revision=state.revision,
        payload={"invocation_id": inv.invocation_id, "selected_card_instance_ids": ["target"] if ids is None else ids})


def _paid(owner="player_1", *, active=False):
    state = _state(owner, active=active)
    return apply_action(state, _activate(state)).state


def test_native_active_target_consumes_real_wait_cost_but_no_ready_event_red():
    state = _state(active=True)
    paid = apply_action(state, _activate(state)).state
    assert paid.cards["source-live"].orientation == "wait"
    assert paid.pending_effects[0].trigger_data[COST_KEY]["paid"] is True
    result = apply_action(paid, _resolve(paid)).state
    assert not result.member_ready_history.events and not result.pending_effects
    assert len([u for u in result.effect_usage if u.effect_id == PROBE]) == 1


@pytest.mark.parametrize("invalid", ["wait", "other_owner", "not_member"])
def test_v2_never_advertises_an_unpayable_source(invalid):
    state = _state(active=True)
    if invalid == "wait":
        state.cards["source-live"].orientation = "wait"
    elif invalid == "other_owner":
        state.cards["source-live"].owner_id = "player_2"
    else:
        state.cards["source-live"].card.card_type = "live"
    before = match_state_hash(state)
    activations = [entry for action in generate_legal_actions(state) if action.action_type == "activate_effect"
                   for entry in action.options["activations"]]
    assert not any(entry["effect_id"] == PROBE for entry in activations)
    assert match_state_hash(state) == before
    with pytest.raises(IllegalActionError):
        apply_action(state, _activate(state))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("active", [False, True])
def test_native_two_step_payment_and_target_sql(tmp_path, owner, active):
    state = _state(owner, active=active); before = match_state_hash(state); repo = _repo(state, tmp_path)
    paid = repo.apply(state.match_id, _activate(state)).state
    inv = next(i for i in paid.pending_effects if i.effect_id == PROBE)
    assert inv.resolution_stage == "after_cost" and inv.trigger_data[COST_KEY]["paid"] is True
    assert paid.cards["source-live"].orientation == "wait"
    assert paid.cards["target"].orientation == ("active" if active else "wait")
    assert not paid.member_ready_history.events and match_state_hash(state) == before
    result = repo.apply(state.match_id, _resolve(paid)).state
    assert result.cards["target"].orientation == "active" and result.cards["source-live"].orientation == "wait"
    assert current_effect_readied_members(result, owner, unit_key="printemps") == ([] if active else ["target"])
    assert len(result.member_ready_history.events) == int(not active)
    assert len([u for u in result.effect_usage if u.effect_id == PROBE]) == 1
    with pytest.raises(IllegalActionError): repo.apply(state.match_id, _activate(result))
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_no_other_member_cannot_activate_or_pay_sql(tmp_path, owner):
    state = _state(owner, active=True); p = state.players[owner]
    for slot in ["center", "right"]:
        key = p.member_area[slot]
        if key is not None: p.hand.append(key)
        p.member_area[slot] = None
    repo = _repo(state, tmp_path); before = match_state_hash(state)
    assert not any(a.action_type == "activate_effect" for a in generate_legal_actions(state))
    with pytest.raises(IllegalActionError): repo.apply(state.match_id, _activate(state))
    assert match_state_hash(repo.get_state(state.match_id)) == before and state.cards["source-live"].orientation == "active"
    _replay(repo, state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("movement", ["hand", "main_deck", "return", "position"])
def test_source_lki_after_paid_legacy_order_checkpoint_sql(tmp_path, owner, active, movement):
    state = _control_checkpoint(_paid(owner, active=active), legacy_order=True); repo = _repo(state, tmp_path)
    if movement == "position": changes = [{"adjustment_type": "position_change", "from_slot": "left", "to_slot": "right"}]
    else:
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "main_deck" if movement == "main_deck" else "hand"}]
        if movement == "return": changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_left"})
    moved = repo.apply(state.match_id, _manual(state, "CONTROL", changes)).state
    result = repo.apply(state.match_id, _resolve(moved)).state
    assert len(result.member_ready_history.events) == int(not active)
    if not active:
        event = result.member_ready_history.events[0]
        assert event.source.departed is (movement != "position") and event.source.owner_id == owner
        assert event.source.unit_keys == ["printemps"]
    _replay(repo, result)


@pytest.mark.parametrize("movement", ["hand", "return", "position", "wait"])
def test_original_target_token_and_later_wait_sql(tmp_path, movement):
    paid = _paid(); state = _control_checkpoint(apply_action(paid, _resolve(paid)).state)
    if movement == "wait":
        raw = state.effect_definitions["CONTROL"].model_dump(mode="json")
        raw.update(execution_mode="prompt_then_resolve", simulation_support="test_validated_executable",
            actions=[{"action_type": "apply_wait_member", "target": "selected"}],
            choice={"choice_type": "member_from_stage", "zone": "stage", "card_type": "member", "minimum": 1, "maximum": 1})
        state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    repo = _repo(state, tmp_path)
    if movement == "wait":
        inv = next(i for i in state.pending_effects if i.effect_id == "CONTROL")
        action = ActionRequest(action_type="resolve_effect", player_id=inv.player_id, expected_revision=state.revision,
            payload={"invocation_id": inv.invocation_id, "selected_card_instance_ids": ["target"]})
    else:
        changes = [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "right"}] if movement == "position" else [
            {"adjustment_type": "move_card", "target_card_instance_id": "target", "to_zone": "hand"}]
        if movement == "return": changes.append({"adjustment_type": "move_card", "target_card_instance_id": "target", "to_zone": "member_center"})
        action = _manual(state, "CONTROL", changes)
    result = repo.apply(state.match_id, action).state
    assert current_effect_readied_members(result, "player_1", unit_key="printemps") == (["target"] if movement in {"position", "wait"} else [])
    _replay(repo, result)


@pytest.mark.parametrize("version", ["v1", "legacy"])
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_old_snapshots_are_not_upgraded_sql(tmp_path, version, owner):
    state = _state(owner, version=version); repo = _repo(state, tmp_path)
    paid = repo.apply(state.match_id, _activate(state)).state
    result = repo.apply(state.match_id, _resolve(paid)).state
    assert paid.effect_definitions[V1_PROBE].choice.orientation == "wait"
    assert (COST_KEY in paid.pending_effects[0].trigger_data) is (version == "v1")
    assert ("member_ready_history" in result.model_dump(mode="json")) is (version == "v1")
    _replay(repo, result)


@pytest.mark.parametrize("mutation", ["no_cost", "mixed", "ready_cost", "self", "wait_filter", "optional", "condition", "manual", "frequency", "followup"])
def test_v2_shape_is_fixed_and_v1_remains_wait_only(mutation):
    raw = _state().effect_definitions[PROBE].model_dump(mode="json")
    if mutation == "no_cost": raw["cost"] = []
    elif mutation == "mixed": raw["cost"].append({"action_type": "pay_energy", "amount": 1})
    elif mutation == "ready_cost": raw["cost"] = raw["actions"]
    elif mutation == "self": raw["choice"]["exclude_source"] = False
    elif mutation == "wait_filter": raw["choice"]["orientation"] = "wait"
    elif mutation == "optional": raw["is_optional"] = True
    elif mutation == "condition": raw["condition"] = {"source_is_center": True}
    elif mutation == "manual": raw["simulation_support"] = "manual_resolution"
    elif mutation == "frequency": raw["frequency_limit"] = "none"
    else: raw["follow_up_choice"] = raw["choice"]
    with pytest.raises(ValidationError): EffectDefinition.model_validate(raw)
    old = _v1_state().effect_definitions[V1_PROBE].model_dump(mode="json"); old["choice"]["orientation"] = None
    with pytest.raises(ValidationError): EffectDefinition.model_validate(old)


@pytest.mark.parametrize("field,value", [("amount", 1), ("value", {}), ("branch", "x"), ("target", "source")])
def test_operation_rejects_extra_parameters(field, value):
    raw = _state().effect_definitions[PROBE].model_dump(mode="json"); raw["actions"][0][field] = value
    with pytest.raises(ValidationError): EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("stage", ["activate", "resolve"])
@pytest.mark.parametrize("payload", [{COST_KEY: {}}, {SOURCE_KEY: {}}, {"energy_instance_ids": ["fake"]}, {"selected_branch": "fake"}, {"accepted": False}, {"accepted": 1}])
def test_client_cannot_forge_or_resupply_cost_proof(stage, payload):
    state = _state(active=True) if stage == "activate" else _paid(active=True)
    action = _activate(state) if stage == "activate" else _resolve(state)
    action.payload.update(payload); before = match_state_hash(state)
    with pytest.raises(IllegalActionError): apply_action(state, action)
    assert match_state_hash(state) == before


@pytest.mark.parametrize("field,value", [("paid", False), ("paid", 1), ("turn_number", True), ("turn_number", 100),
    ("invocation_id", "WRONG"), ("effect_id", "WRONG"), ("source_instance_id", "target"), ("player_id", "player_2")])
def test_active_noop_still_requires_genuine_paid_context(field, value):
    state = _paid(active=True); state.pending_effects[0].trigger_data[COST_KEY][field] = value
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError): apply_action(state, _resolve(state))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("active", [False, True])
def test_recording_cannot_bypass_payment_or_modern_parent_lock(active):
    from loveca.simulation.ready_history import record_member_ready
    state = _control_checkpoint(_paid(active=active)); before = match_state_hash(state)
    with pytest.raises(IllegalActionError, match="another effect must resolve first"):
        apply_action(state, _manual(state, "CONTROL", [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"}]))
    assert match_state_hash(state) == before
    inv = next(i for i in state.pending_effects if i.effect_id == PROBE); inv.trigger_data.pop(COST_KEY)
    before = match_state_hash(state)
    with pytest.raises(ValueError): record_member_ready(state, inv, "target", "active" if active else "wait")
    assert match_state_hash(state) == before


@pytest.mark.parametrize("ids", [[], ["source-live"], ["target", "target"], ["target", "wrong-work"], ["held"]])
def test_current_target_selection_is_strict_and_atomic(ids):
    state = _paid(active=True); before = match_state_hash(state)
    with pytest.raises(IllegalActionError): apply_action(state, _resolve(state, ids))
    assert match_state_hash(state) == before


def test_missing_proof_wrong_role_stage_revision_and_wait_source_are_rejected():
    for mutation in ["missing", "role", "stage", "revision", "turn"]:
        state = _paid(active=True); action = _resolve(state)
        if mutation == "missing": state.pending_effects[0].trigger_data.pop(COST_KEY)
        elif mutation == "role": action.player_id = "player_2"
        elif mutation == "stage": state.pending_effects[0].resolution_stage = "initial"
        elif mutation == "revision": action.expected_revision = 0
        else: state.turn_number = True
        before = match_state_hash(state)
        with pytest.raises(StaleRevisionError if mutation == "revision" else IllegalActionError): apply_action(state, action)
        assert match_state_hash(state) == before
    state = _state(active=True); state.cards["source-live"].orientation = "wait"; before = match_state_hash(state)
    with pytest.raises(IllegalActionError): apply_action(state, _activate(state))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_noop_usage_is_consumed_even_if_source_is_later_readied_sql(tmp_path, owner):
    paid = _paid(owner, active=True); done = apply_action(paid, _resolve(paid)).state
    state = _control_checkpoint(done)
    raw = state.effect_definitions["CONTROL"].model_dump(mode="json")
    raw.update(execution_mode="prompt_then_resolve", simulation_support="test_validated_executable",
        actions=[{"action_type": "ready_member", "target": "selected"}],
        choice={"choice_type": "member_from_stage", "zone": "stage", "card_type": "member", "minimum": 1, "maximum": 1})
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    repo = _repo(state, tmp_path); control = next(i for i in state.pending_effects if i.effect_id == "CONTROL")
    result = repo.apply(state.match_id, ActionRequest(action_type="resolve_effect", player_id=owner, expected_revision=state.revision,
        payload={"invocation_id": control.invocation_id, "selected_card_instance_ids": ["source-live"]})).state
    assert result.cards["source-live"].orientation == "active"
    assert len([u for u in result.effect_usage if u.effect_id == PROBE]) == 1
    with pytest.raises(IllegalActionError): repo.apply(state.match_id, _activate(result))
    _replay(repo, result)


@pytest.mark.parametrize("kind", ["source", "target"])
def test_attached_member_is_not_a_source_or_target_sql(tmp_path, kind):
    state = _state(active=True); p = state.players["player_1"]
    if kind == "source":
        p.member_area["left"] = None; p.member_area_attachments["center"].append("source-live")
    else:
        p.hand.remove("held"); p.member_area_attachments["center"].append("held")
        state.cards["held"].orientation = "active"
    repo = _repo(state, tmp_path)
    if kind == "source":
        before = match_state_hash(state)
        with pytest.raises(IllegalActionError): repo.apply(state.match_id, _activate(state))
        assert match_state_hash(repo.get_state(state.match_id)) == before
        result = state
    else:
        paid = repo.apply(state.match_id, _activate(state)).state; before = match_state_hash(paid)
        with pytest.raises(IllegalActionError): repo.apply(state.match_id, _resolve(paid, ["held"]))
        assert match_state_hash(repo.get_state(state.match_id)) == before
        result = repo.apply(state.match_id, _resolve(paid)).state
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_actual_support_and_hidden_source_privacy(owner, active, policy):
    initial = _state(owner, active=active); before = match_state_hash(initial)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    legal = [a for a in generate_legal_actions(initial) if a.action_type == "activate_effect"]
    decision = controller.choose_action(initial, legal, controlled_player_ids={owner})
    if isinstance(decision, SimpleAIBlocker):
        assert decision.reason == "no_safe_ai_action"
        paid = apply_action(initial, _activate(initial)).state
    else:
        assert isinstance(decision, SimpleAIDecision)
        paid = apply_action(initial, decision.action).state
    assert match_state_hash(initial) == before
    checkpoint = _control_checkpoint(paid, legacy_order=True)
    moved = apply_action(checkpoint, _manual(checkpoint, "CONTROL", [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "main_deck"}]))
    state = moved.state; before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    changed = state.model_copy(deep=True)
    for p in changed.players.values():
        for key in list(p.main_deck + (p.hand if p.player_id != owner else [])):
            item = changed.cards.pop(key); replacement = "HIDDEN-" + key; item.instance_id = replacement
            item.card.name_ja = item.card.card_code = "HIDDEN"; item.card.unit_keys, item.card.work_keys = ["bibi"], ["hasunosora"]; item.card.blade = 99
            changed.cards[replacement] = item
            p.main_deck = [replacement if i == key else i for i in p.main_deck]; p.hand = [replacement if i == key else i for i in p.hand]
            for inv in changed.pending_effects:
                if inv.source_card_instance_id == key:
                    inv.source_card_instance_id = replacement
                    inv.trigger_data[SOURCE_KEY]["instance_id"] = replacement
                    inv.trigger_data[COST_KEY]["source_instance_id"] = replacement
    changed_before = match_state_hash(changed)
    second = controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner})
    assert isinstance(second, SimpleAIDecision) and second.action == decision.action
    assert match_state_hash(state) == before and match_state_hash(changed) == changed_before
    result, other = apply_action(state, decision.action), apply_action(changed, second.action)
    assert len(result.state.member_ready_history.events) == len(other.state.member_ready_history.events) == int(not active)
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(result.state, events=[*moved.events, *result.events], legal_actions=result.legal_actions, player_id=viewer)
        text = json.dumps(payload)
        assert COST_KEY not in text and SOURCE_KEY not in text and "member_ready_history" not in payload["state"]
        for p in result.state.players.values():
            assert not any(i in payload["state"]["cards"] for i in p.main_deck)
            if p.player_id != viewer: assert not any(i in payload["state"]["cards"] for i in p.hand)
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    for builder in [build_api_play_context, build_agent_context]:
        text = json.dumps(builder(state, generate_legal_actions(state)))
        assert COST_KEY not in text and SOURCE_KEY not in text and "member_ready_history" not in text
