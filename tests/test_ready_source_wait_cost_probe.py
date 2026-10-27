import json
import pytest
from pydantic import ValidationError

from test_member_ready_provenance import _state as _base_state, PROBE as OLD_PROBE
from test_mirakura_front_position_boundary import _swap_roles
from test_printemps_ready_history_boundary import _repo, _replay, _manual
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import apply_action, IllegalActionError, StaleRevisionError, generate_legal_actions
from loveca.simulation.models import ActionRequest, EffectInvocation
from loveca.simulation.online import match_state_hash
from loveca.simulation.ready_history import current_effect_readied_members
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIBlocker, SimpleAIPolicy
from loveca.webapp import _match_state_payload

PROBE = "UNREGISTERED-SOURCE-WAIT-READY:1"
OPERATION = "ready_member_after_source_wait_provenance_v1"
COST_KEY = "ready_source_wait_cost_v1"


def _state(owner="player_1", legacy=False):
    state = _base_state(selected=True)
    raw = state.effect_definitions.pop(OLD_PROBE).model_dump(mode="json")
    raw.update(effect_id=PROBE, card_code="UNREGISTERED-SOURCE-WAIT-READY",
        label_ja="AUDIT unregistered source-Wait cost then other Member ready",
        effect_type="activated", timing="activated_main", trigger="player_activation", frequency_limit="once_per_turn",
        actions=[{"action_type": "ready_member" if legacy else OPERATION, "target": "selected"}],
        cost=[{"action_type": "apply_wait", "target": "source"}],
        choice={"choice_type": "member_from_stage", "zone": "stage", "card_type": "member", "target_player": "self",
                "orientation": "wait", "exclude_source": True, "minimum": 1, "maximum": 1})
    state.effect_definitions[PROBE] = EffectDefinition.model_validate(raw)
    state.cards["source-live"].card.effect_ids = [PROBE]
    state.cards["source-live"].orientation = "active"
    state.cards["live-1"].card.effect_ids = []
    state.cards["target"].card.unit_keys = ["bibi"]
    state.phase, state.active_player_id = "first_main", "player_1"
    if owner == "player_2":
        state = _swap_roles(state)
    return state


def _activate(state):
    return ActionRequest(action_type="activate_effect", player_id=state.active_player_id, expected_revision=state.revision,
        payload={"effect_id": PROBE, "source_card_instance_id": "source-live", "energy_instance_ids": []})


def _resolve(state, ids=None):
    inv = next(i for i in state.pending_effects if i.effect_id == PROBE)
    return ActionRequest(action_type="resolve_effect", player_id=inv.player_id, expected_revision=state.revision,
        payload={"invocation_id": inv.invocation_id, "selected_card_instance_ids": ["target"] if ids is None else ids})


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_native_cost_then_ready_has_server_payment_provenance_sql(tmp_path, owner):
    state = _state(owner)
    repo = _repo(state, tmp_path)
    paid = repo.apply(state.match_id, _activate(state)).state
    assert paid.cards["source-live"].orientation == "wait"
    assert paid.cards["target"].orientation == "wait"
    inv = next(i for i in paid.pending_effects if i.effect_id == PROBE)
    assert inv.trigger_data[COST_KEY]["paid"] is True
    result = repo.apply(state.match_id, _resolve(paid)).state
    assert result.cards["target"].orientation == "active"
    assert result.cards["source-live"].orientation == "wait"
    assert len(result.member_ready_history.events) == 1
    event = result.member_ready_history.events[0]
    assert event.source.effect_id == PROBE and event.source.owner_id == event.source.effect_player_id == owner
    assert event.source.unit_keys == ["printemps"] and event.target_instance_id == "target"
    assert current_effect_readied_members(result, owner, unit_key="printemps") == ["target"]
    _replay(repo, result)


def _paid(owner="player_1"):
    state = _state(owner)
    return apply_action(state, _activate(state)).state


def _control_checkpoint(state, *, legacy_order=False):
    if legacy_order:
        state.effect_order_policy = None
    state.pending_effects.insert(0, EffectInvocation(invocation_id="AUDIT-CONTROL", effect_id="CONTROL",
        source_card_instance_id="live-1", player_id=state.active_player_id, trigger_event="audit_checkpoint"))
    return state


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("movement", ["hand", "main_deck", "return", "position"])
def test_paid_source_interference_checkpoint_sql(tmp_path, owner, movement):
    state = _control_checkpoint(_paid(owner), legacy_order=True)
    repo = _repo(state, tmp_path)
    if movement == "position":
        changes = [{"adjustment_type": "position_change", "from_slot": "left", "to_slot": "right"}]
    else:
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "main_deck" if movement == "main_deck" else "hand"}]
        if movement == "return":
            changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_left"})
    moved = repo.apply(state.match_id, _manual(state, "CONTROL", changes)).state
    result = repo.apply(state.match_id, _resolve(moved)).state
    assert current_effect_readied_members(result, owner, unit_key="printemps") == ["target"]
    assert result.member_ready_history.events[0].source.departed is (movement != "position")
    assert result.member_ready_history.events[0].source.owner_id == owner
    _replay(repo, result)


@pytest.mark.parametrize("movement", ["hand", "return", "position", "wait"])
def test_original_target_history_after_effect_checkpoint_sql(tmp_path, movement):
    paid = _paid()
    state = _control_checkpoint(apply_action(paid, _resolve(paid)).state)
    if movement == "wait":
        raw = state.effect_definitions["CONTROL"].model_dump(mode="json")
        raw.update(execution_mode="prompt_then_resolve", simulation_support="test_validated_executable",
            choice={"choice_type": "member_from_stage", "zone": "stage", "card_type": "member", "minimum": 1, "maximum": 1},
            actions=[{"action_type": "apply_wait_member", "target": "selected"}])
        state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    repo = _repo(state, tmp_path)
    if movement == "position":
        changes = [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "right"}]
    elif movement == "wait":
        changes = []
    else:
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": "target", "to_zone": "hand"}]
        if movement == "return":
            changes.append({"adjustment_type": "move_card", "target_card_instance_id": "target", "to_zone": "member_center"})
    if movement == "wait":
        control = next(i for i in state.pending_effects if i.effect_id == "CONTROL")
        action = ActionRequest(action_type="resolve_effect", player_id=control.player_id, expected_revision=state.revision,
            payload={"invocation_id": control.invocation_id, "selected_card_instance_ids": ["target"]})
    else:
        action = _manual(state, "CONTROL", changes)
    result = repo.apply(state.match_id, action).state
    assert current_effect_readied_members(result, "player_1", unit_key="printemps") == (["target"] if movement in {"position", "wait"} else [])
    _replay(repo, result)


@pytest.mark.parametrize("legacy", [False, True])
def test_old_snapshot_has_no_new_payment_or_history_json_sql(tmp_path, legacy):
    state = _state(legacy=legacy)
    repo = _repo(state, tmp_path)
    paid = repo.apply(state.match_id, _activate(state)).state
    result = repo.apply(state.match_id, _resolve(paid)).state
    assert (COST_KEY in paid.pending_effects[0].trigger_data) is (not legacy)
    assert ("member_ready_history" in result.model_dump(mode="json")) is (not legacy)
    _replay(repo, result)


@pytest.mark.parametrize("payload", [{COST_KEY: {}}, {"energy_instance_ids": ["fake"]},
    {"selected_card_instance_ids": ["target"]}, {"accepted": False}, {"selected_branch": "other"}])
def test_activation_cannot_supply_cost_evidence_or_inline_target(payload):
    state = _state(); before = match_state_hash(state)
    action = _activate(state); action.payload.update(payload)
    with pytest.raises(IllegalActionError):
        apply_action(state, action)
    assert match_state_hash(state) == before


@pytest.mark.parametrize("payload", [{COST_KEY: {}}, {"energy_instance_ids": ["fake"]}, {"accepted": False},
    {"accepted": 1}, {"selected_color_slot": "heart01"}, {"selected_card_instance_ids": ["source-live"]},
    {"selected_card_instance_ids": ["target", "target"]}, {"selected_card_instance_ids": ["held"]},
    {"selected_card_instance_ids": []}])
def test_resolution_rejects_extra_cost_forgery_and_bad_target_atomically(payload):
    state = _paid(); before = match_state_hash(state)
    action = _resolve(state); action.payload.update(payload)
    with pytest.raises(IllegalActionError):
        apply_action(state, action)
    assert match_state_hash(state) == before


@pytest.mark.parametrize("field,value", [("paid", False), ("paid", 1), ("turn_number", True), ("turn_number", 100),
    ("effect_id", "WRONG"), ("invocation_id", "WRONG"), ("source_instance_id", "target"), ("player_id", "player_2"),
    ("policy", "old")])
def test_corrupt_payment_context_is_rejected_atomically(field, value):
    state = _paid(); state.pending_effects[0].trigger_data[COST_KEY][field] = value
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state))
    assert match_state_hash(state) == before


def test_missing_payment_wrong_stage_owner_and_revision_are_rejected():
    for mutation in ["missing", "stage", "owner", "revision"]:
        state = _paid(); action = _resolve(state)
        if mutation == "missing": state.pending_effects[0].trigger_data.pop(COST_KEY)
        elif mutation == "stage": state.pending_effects[0].resolution_stage = "initial"
        elif mutation == "owner": action.player_id = "player_2"
        else: action.expected_revision = 0
        before = match_state_hash(state)
        with pytest.raises(StaleRevisionError if mutation == "revision" else IllegalActionError): apply_action(state, action)
        assert match_state_hash(state) == before


def test_already_wait_source_cannot_pay_and_paid_effect_cannot_be_repeated():
    initial = _state(); initial.cards["source-live"].orientation = "wait"
    before = match_state_hash(initial)
    with pytest.raises(IllegalActionError): apply_action(initial, _activate(initial))
    assert match_state_hash(initial) == before
    paid = _paid(); action = _resolve(paid); done = apply_action(paid, action).state
    before = match_state_hash(done)
    with pytest.raises(IllegalActionError): apply_action(done, _activate(done))
    action.expected_revision = done.revision
    with pytest.raises(IllegalActionError): apply_action(done, action)
    assert match_state_hash(done) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_actual_activation_and_followup_hidden_invariance(owner, policy):
    initial = _state(owner)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    legal = [a for a in generate_legal_actions(initial) if a.action_type == "activate_effect"]
    before = match_state_hash(initial)
    decision = controller.choose_action(initial, legal, controlled_player_ids={owner})
    if policy == "simple_ai_v0":
        assert isinstance(decision, SimpleAIBlocker) and decision.reason == "no_safe_ai_action"
        state = apply_action(initial, _activate(initial)).state
    else:
        assert isinstance(decision, SimpleAIDecision)
        state = apply_action(initial, decision.action).state
    assert match_state_hash(initial) == before
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    changed = state.model_copy(deep=True)
    for p in changed.players.values():
        for key in list(p.main_deck + (p.hand if p.player_id != owner else [])):
            item = changed.cards.pop(key); name = "HIDDEN-" + key
            item.instance_id = name; item.card.name_ja = item.card.card_code = "HIDDEN"
            changed.cards[name] = item
            p.main_deck = [name if i == key else i for i in p.main_deck]
            p.hand = [name if i == key else i for i in p.hand]
    changed_before = match_state_hash(changed)
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner}).action == decision.action
    assert match_state_hash(changed) == changed_before and match_state_hash(state) == before
    result = apply_action(state, decision.action).state
    assert len(result.member_ready_history.events) == 1


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_payment_and_history_are_private_in_complete_player_and_provider_views(owner):
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    state = _control_checkpoint(_paid(owner), legacy_order=True)
    state = apply_action(state, _manual(state, "CONTROL", [
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "main_deck"}])).state
    before = match_state_hash(state)
    legal = generate_legal_actions(state)
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(state, events=[], legal_actions=legal, player_id=viewer)
        text = json.dumps(payload)
        assert COST_KEY not in text and "ready_source_lki_v1" not in text and "member_ready_history" not in payload["state"]
        assert "source-live" not in payload["state"]["cards"]
        for p in state.players.values():
            assert not any(i in payload["state"]["cards"] for i in p.main_deck)
            if p.player_id != viewer: assert not any(i in payload["state"]["cards"] for i in p.hand)
    for builder in [build_api_play_context, build_agent_context]:
        text = json.dumps(builder(state, legal))
        assert COST_KEY not in text and "ready_source_lki_v1" not in text and "member_ready_history" not in text
    assert match_state_hash(state) == before


@pytest.mark.parametrize("mutation", ["no_cost", "mixed_cost", "ready_cost", "wrong_target", "wrong_choice", "optional", "condition", "manual", "no_frequency", "followup"])
def test_snapshot_is_fixed_and_does_not_relax_old_v1(mutation):
    raw = _state().effect_definitions[PROBE].model_dump(mode="json")
    if mutation == "no_cost": raw["cost"] = []
    elif mutation == "mixed_cost": raw["cost"].append({"action_type": "pay_energy", "amount": 1})
    elif mutation == "ready_cost": raw["cost"] = raw["actions"]
    elif mutation == "wrong_target": raw["actions"][0]["target"] = "source"
    elif mutation == "wrong_choice": raw["choice"]["exclude_source"] = False
    elif mutation == "optional": raw["is_optional"] = True
    elif mutation == "condition": raw["condition"] = {"source_is_center": True}
    elif mutation == "manual": raw["simulation_support"] = "manual_resolution"
    elif mutation == "no_frequency": raw["frequency_limit"] = "none"
    else: raw["follow_up_choice"] = raw["choice"]
    with pytest.raises(ValidationError): EffectDefinition.model_validate(raw)
    old = _state().effect_definitions[PROBE].model_dump(mode="json")
    old["actions"][0]["action_type"] = "ready_member_with_provenance_v1"
    with pytest.raises(ValidationError): EffectDefinition.model_validate(old)


def test_current_order_locks_paid_parent_against_manual_interruption():
    state = _control_checkpoint(_paid())
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError, match="another effect must resolve first"):
        apply_action(state, _manual(state, "CONTROL", [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"}]))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_no_wait_target_does_not_fabricate_a_ready_event_sql(tmp_path, owner):
    state = _state(owner)
    for key in ["target", "wrong-work"]: state.cards[key].orientation = "active"
    repo = _repo(state, tmp_path)
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError): repo.apply(state.match_id, _activate(state))
    assert match_state_hash(state) == before and state.cards["source-live"].orientation == "active"
    assert state.member_ready_history is None
    _replay(repo, state)


@pytest.mark.parametrize("field,value", [("amount", 1), ("branch", "fake"), ("value", {"unit_key": "printemps"})])
def test_operation_rejects_unmodeled_parameters(field, value):
    raw = _state().effect_definitions[PROBE].model_dump(mode="json")
    raw["actions"][0][field] = value
    with pytest.raises(ValidationError): EffectDefinition.model_validate(raw)


def test_boolean_current_turn_is_not_an_authoritative_payment_turn():
    state = _paid(); state.turn_number = True
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError): apply_action(state, _resolve(state))
    assert match_state_hash(state) == before


def test_executor_cannot_record_unpaid_ready_even_outside_resolver():
    from loveca.simulation.ready_history import record_member_ready
    state = _paid(); inv = state.pending_effects[0]
    inv.trigger_data.pop(COST_KEY)
    before = match_state_hash(state)
    with pytest.raises(ValueError): record_member_ready(state, inv, "target", "wait")
    assert match_state_hash(state) == before


@pytest.mark.parametrize("kind", ["source", "target"])
def test_attached_member_is_not_a_source_or_target_sql(tmp_path, kind):
    state = _state()
    p = state.players["player_1"]
    if kind == "source":
        p.member_area["left"] = None
        p.member_area_attachments["center"].append("source-live")
    else:
        p.hand.remove("held")
        p.member_area_attachments["center"].append("held")
        state.cards["held"].orientation = "wait"
    repo = _repo(state, tmp_path)
    before = match_state_hash(state)
    if kind == "source":
        with pytest.raises(IllegalActionError): repo.apply(state.match_id, _activate(state))
        assert match_state_hash(state) == before
        final = state
    else:
        paid = repo.apply(state.match_id, _activate(state)).state
        before = match_state_hash(paid)
        with pytest.raises(IllegalActionError): repo.apply(state.match_id, _resolve(paid, ["held"]))
        assert match_state_hash(paid) == before
        final = repo.apply(state.match_id, _resolve(paid)).state
    _replay(repo, final)
