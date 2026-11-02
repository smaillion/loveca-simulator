import json

import pytest
from pydantic import ValidationError

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.online import match_state_hash
from loveca.webapp import _match_state_payload
from test_private_named_unlimited_discard_probe import _probe as _named_probe, PROBE
from test_ll_bp2_composite_name_cost_audit import _actual, EFFECT
from test_printemps_ready_history_boundary import _advance, _manual, _repo, _replay, _resolve, _state


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("return_source", [False, True])
def test_formal_legacy_blade_after_departure_sql(tmp_path, owner, return_source):
    state = _actual(owner)
    state.effect_definitions["CONTROL"] = _state(owner=owner, control=True).effect_definitions["CONTROL"]
    state.cards["live-1"].card.effect_ids.append("CONTROL")
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"}]
    if return_source:
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_left"})
    current = repo.apply(state.match_id, _manual(current, "CONTROL", changes)).state
    result = repo.apply(state.match_id, _resolve(current, EFFECT, accepted=True, selected_card_instance_ids=["single-hand"]))
    assert "single-hand" in result.state.players[owner].waiting_room
    assert any(m.modifier_type == "blade" and m.target_card_instance_id == "source-live" and m.amount == 1
               for m in result.state.players[owner].manual_modifiers)
    _replay(repo, result.state)


def _blade_probe(owner, control=False):
    state = _named_probe(owner, control=control)
    raw = state.effect_definitions[PROBE].model_dump(mode="json")
    raw.update(duration="live", actions=[{"action_type": "gain_source_blade_for_paid_named_v1",
        "target": "cost_selected", "source_object_policy": "original_paid_named_blade_source_v1"}])
    state.effect_definitions[PROBE] = EffectDefinition.model_validate(raw)
    return state


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_paid_named_source_blade_six_sql(tmp_path, owner):
    state = _blade_probe(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    chosen = ["composite-hand", "single-hand", *(f"single-extra-{i}" for i in range(4))]
    result = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=chosen))
    assert any(m.modifier_type == "blade" and m.target_card_instance_id == "source-live" and m.amount == 6
               for m in result.state.players[owner].manual_modifiers)
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("count", [0, 1, 4, 6])
def test_paid_actual_count_controls_source_blade_sql(tmp_path, owner, count):
    state = _blade_probe(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    chosen = ["composite-hand", "single-hand", *(f"single-extra-{i}" for i in range(4))][:count]
    result = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=chosen))
    markers = [m for m in result.state.players[owner].manual_modifiers if m.value == {"policy": "paid_named_blade_v1"}]
    assert [m.amount for m in markers] == ([count] if count else [])
    assert all(i in result.state.players[owner].waiting_room for i in chosen)
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("destination", ["hand", "main_deck", "return"])
def test_departed_source_never_receives_old_blade_sql(tmp_path, owner, destination):
    state = _blade_probe(owner, control=True)
    repo = _repo(state, tmp_path)
    triggered = repo.apply(state.match_id, _advance(state))
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live",
                "to_zone": "hand" if destination == "return" else destination}]
    if destination == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_left"})
    moved = repo.apply(state.match_id, _manual(triggered.state, "CONTROL", changes))
    result = repo.apply(state.match_id, _resolve(moved.state, PROBE, accepted=True,
        selected_card_instance_ids=["single-hand"]))
    assert "single-hand" in result.state.players[owner].waiting_room
    assert not any(m.value == {"policy": "paid_named_blade_v1"} for m in result.state.players[owner].manual_modifiers)
    for viewer in ("player_1", "player_2"):
        payload = _match_state_payload(result.state, events=triggered.events + moved.events + result.events,
            legal_actions=generate_legal_actions(result.state), player_id=viewer)
        serialized = json.dumps(payload)
        assert '"paid_named_blade_source_v1":' not in serialized and '"paid_named_blade_cost_v1":' not in serialized
        if destination == "main_deck" or (destination == "hand" and viewer != owner):
            assert "source-live" not in serialized
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", [None, "clear_departed_card_modifiers"])
def test_earned_blade_is_cleared_on_departure_and_return_sql(tmp_path, owner, policy):
    state = _blade_probe(owner, control=True)
    state.stage_departure_policy = policy
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    current = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=["single-hand"])).state
    assert any(m.value == {"policy": "paid_named_blade_v1"} for m in current.players[owner].manual_modifiers)
    current = repo.apply(state.match_id, _manual(current, "CONTROL", [
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"},
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_left"},
    ])).state
    assert not any(m.value == {"policy": "paid_named_blade_v1"} for m in current.players[owner].manual_modifiers)
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_actual_live_end_expires_blade_sql(tmp_path, owner):
    state = _blade_probe(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    current = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=["single-hand"])).state
    assert any(m.value == {"policy": "paid_named_blade_v1"} for m in current.players[owner].manual_modifiers)
    for _ in range(8):
        if not any(m.value == {"policy": "paid_named_blade_v1"} for m in current.players[owner].manual_modifiers):
            break
        current = repo.apply(state.match_id, _advance(current)).state
    assert not any(m.value == {"policy": "paid_named_blade_v1"} for m in current.players[owner].manual_modifiers)
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("tampering", ["forged_cost", "source", "turn", "stage", "after_cost"])
def test_forged_proofs_and_source_are_rejected_atomically(owner, tampering):
    state = _blade_probe(owner)
    current = apply_action(state, _advance(state)).state
    invocation = next(i for i in current.pending_effects if i.effect_id == PROBE)
    if tampering == "forged_cost": invocation.trigger_data["paid_named_blade_cost_v1"] = {"paid": True}
    elif tampering == "source": invocation.trigger_data["paid_named_blade_source_v1"]["source_id"] = "other"
    elif tampering == "turn": invocation.trigger_data["paid_named_blade_source_v1"]["turn_number"] += 1
    elif tampering == "stage": invocation.trigger_data.pop("original_source_stage_object")
    else: invocation.resolution_stage = "after_cost"
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        apply_action(current, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=["single-hand"]))
    assert match_state_hash(current) == before


@pytest.mark.parametrize("field,value", [("card_code", "FORMAL"), ("is_optional", False),
    ("duration", "game"), ("trigger", "member_played"), ("condition", {"unknown": True}),
    ("cost", [{"action_type": "discard_from_hand", "amount": 1}]),
    ("actions", [{"action_type": "gain_source_blade_for_paid_named_v1", "target": "source",
                  "source_object_policy": "original_paid_named_blade_source_v1"}])])
def test_other_parent_shapes_are_rejected(field, value):
    raw = _blade_probe("player_1").effect_definitions[PROBE].model_dump(mode="json")
    raw[field] = value
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("payload", [{"selected_branch": "fake"}, {"energy_instance_ids": ["fake"]},
    {"accepted": False, "selected_card_instance_ids": ["single-hand"]},
    {"accepted": True, "selected_card_instance_ids": ["single-hand", "single-hand"]},
    {"accepted": True, "selected_card_instance_ids": ["unrelated-hand"]}])
def test_client_input_is_rejected_atomically_sql(tmp_path, owner, payload):
    state = _blade_probe(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _resolve(current, PROBE, **payload))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_decline_and_wrong_actor_do_not_pay_sql(tmp_path, owner):
    state = _blade_probe(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    before = match_state_hash(current)
    other = "player_2" if owner == "player_1" else "player_1"
    action = _resolve(current, PROBE, accepted=True, selected_card_instance_ids=["single-hand"])
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, action.model_copy(update={"player_id": other}))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    result = repo.apply(state.match_id, _resolve(current, PROBE, accepted=False)).state
    assert result.players[owner].hand == current.players[owner].hand
    assert not any(m.value == {"policy": "paid_named_blade_v1"} for m in result.players[owner].manual_modifiers)
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_stage_position_change_keeps_original_source_sql(tmp_path, owner):
    state = _blade_probe(owner, control=True)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    current = repo.apply(state.match_id, _manual(current, "CONTROL", [
        {"adjustment_type": "position_change", "from_slot": "left", "to_slot": "center"},
    ])).state
    result = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=["single-hand"])).state
    assert result.players[owner].member_area["center"] == "source-live"
    assert any(m.value == {"policy": "paid_named_blade_v1"} and m.amount == 1
               for m in result.players[owner].manual_modifiers)
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("hide_source", [False, True])
def test_ai_actual_decision_and_hidden_information(owner, policy, hide_source):
    state = _blade_probe(owner, control=hide_source)
    current = apply_action(state, _advance(state)).state
    if hide_source:
        current = apply_action(current, _manual(current, "CONTROL", [
            {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "main_deck"},
        ])).state
    before = match_state_hash(current)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    decision = controller.choose_action(current, generate_legal_actions(current), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    changed = current.model_copy(deep=True)
    opponent = "player_2" if owner == "player_1" else "player_1"
    player = changed.players[opponent]
    for key in list(player.main_deck + player.hand):
        card = changed.cards.pop(key)
        replacement = "hidden-" + key
        card.instance_id = replacement
        card.card.name_ja = card.card.card_code = "HIDDEN"
        card.card.blade = 99
        changed.cards[replacement] = card
        player.main_deck = [replacement if i == key else i for i in player.main_deck]
        player.hand = [replacement if i == key else i for i in player.hand]
    changed_before = match_state_hash(changed)
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner}) == decision
    assert match_state_hash(current) == before and match_state_hash(changed) == changed_before
    apply_action(current, decision.action)
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    for builder in (build_api_play_context, build_agent_context):
        text = json.dumps(builder(current, generate_legal_actions(current)))
        assert '"paid_named_blade_source_v1":' not in text and '"paid_named_blade_cost_v1":' not in text
        assert all(i not in text for i in current.players[opponent].main_deck + current.players[opponent].hand)
        if hide_source:
            assert "source-live" not in text
