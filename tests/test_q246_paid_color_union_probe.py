from collections import Counter
import json

import pytest
from pydantic import ValidationError

from loveca.simulation.effects import EffectDefinition
from loveca.simulation.ai import SimpleAIBlocker, SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.online import match_state_hash
from loveca.webapp import _match_state_payload
from test_q246_named_cost_union_boundary import PROBE, _probe as _old_probe
from test_printemps_ready_history_boundary import _advance, _manual, _repo, _replay, _resolve, _state

OPERATION = "gain_source_heart_from_paid_basic_color_union_v1"


def _probe(owner, control=False):
    state = _old_probe(owner)
    raw = state.effect_definitions[PROBE].model_dump(mode="json")
    raw["actions"] = [{"action_type": OPERATION, "target": "cost_selected",
                       "source_object_policy": "original_paid_basic_color_union_source_v1"}]
    state.effect_definitions[PROBE] = EffectDefinition.model_validate(raw)
    if control:
        state.effect_definitions["CONTROL"] = _state(owner=owner, control=True).effect_definitions["CONTROL"]
        state.cards["live-1"].card.effect_ids.append("CONTROL")
    return state


@pytest.mark.parametrize("field,value", [("card_code", "FORMAL"), ("is_optional", False),
    ("duration", "game"), ("trigger", "member_played"), ("condition", {"unknown": True})])
def test_probe_rejects_non_bounded_parent_shape(field, value):
    raw = _probe("player_1").effect_definitions[PROBE].model_dump(mode="json")
    raw[field] = value
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


def test_union_cannot_be_used_as_a_cost():
    raw = _probe("player_1").effect_definitions[PROBE].model_dump(mode="json")
    raw["cost"] = raw["actions"]
    raw["actions"] = [{"action_type": "draw_card", "amount": 1}]
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("count", [0, 1, 2, 3, 4])
def test_paid_basic_colors_are_a_union_sql(tmp_path, owner, count):
    state = _probe(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    chosen = [f"audit-hand-{i}" for i in range(count)]
    result = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=chosen))
    colors = Counter(m.color_slot for m in result.state.players[owner].manual_modifiers
                     if m.value == {"policy": "paid_basic_color_union_v1"})
    expected = set().union(*(set(state.cards[i].card.basic_hearts) for i in chosen))
    assert colors == {color: 1 for color in expected}
    assert all(i in result.state.players[owner].waiting_room for i in chosen)
    paid = [e for e in result.events if e.event_type == "effect_cost_paid"]
    assert len(paid) == 1 and paid[0].data["selected_card_instance_ids"] == chosen
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("selection", [["audit-hand-0", "audit-hand-0"], ["wrong-work"]])
def test_illegal_paid_cost_is_atomic_sql(tmp_path, owner, selection):
    state = _probe(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=selection))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_unknown_basic_color_rejects_before_payment_sql(tmp_path, owner):
    state = _probe(owner)
    state.cards["audit-hand-0"].card.basic_hearts = {"heart0": 1}
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=["audit-hand-0"]))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("return_source", [False, True])
def test_departed_original_source_never_gains_paid_union_sql(tmp_path, owner, return_source):
    state = _probe(owner, control=True)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"}]
    if return_source:
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_left"})
    current = repo.apply(state.match_id, _manual(current, "CONTROL", changes)).state
    result = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=["audit-hand-0"]))
    assert "audit-hand-0" in result.state.players[owner].waiting_room
    assert not any(m.value == {"policy": "paid_basic_color_union_v1"} for m in result.state.players[owner].manual_modifiers)
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", [None, "clear_departed_card_modifiers"])
def test_earned_union_is_removed_when_source_leaves_sql(tmp_path, owner, policy):
    state = _probe(owner, control=True)
    state.stage_departure_policy = policy
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    current = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True,
        selected_card_instance_ids=["audit-hand-0"])).state
    assert any(m.value == {"policy": "paid_basic_color_union_v1"} for m in current.players[owner].manual_modifiers)
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"},
               {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_left"}]
    result = repo.apply(state.match_id, _manual(current, "CONTROL", changes)).state
    assert not any(m.value == {"policy": "paid_basic_color_union_v1"} for m in result.players[owner].manual_modifiers)
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("tampering", ["forged_proof", "after_cost", "source_snapshot", "source_turn"])
def test_untrusted_payment_and_source_state_is_rejected_atomically(owner, tampering):
    state = _probe(owner)
    current = apply_action(state, _advance(state)).state
    invocation = next(i for i in current.pending_effects if i.effect_id == PROBE)
    if tampering == "forged_proof":
        invocation.trigger_data["paid_basic_color_union_v1"] = {"paid": True}
    elif tampering == "after_cost":
        invocation.resolution_stage = "after_cost"
    elif tampering == "source_snapshot":
        invocation.trigger_data.pop("original_source_stage_object")
    else:
        invocation.trigger_data["paid_basic_color_source_v1"]["turn_number"] += 1
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        apply_action(current, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=["audit-hand-0"]))
    assert match_state_hash(current) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_opponent_hidden_card_color_does_not_change_invalid_selection_error(owner):
    state = _probe(owner)
    current = apply_action(state, _advance(state)).state
    opponent = "player_2" if owner == "player_1" else "player_1"
    hidden = current.players[opponent].hand[0]
    changed = current.model_copy(deep=True)
    changed.cards[hidden].card.basic_hearts = {"heart0": 1}
    errors = []
    for item in (current, changed):
        before = match_state_hash(item)
        with pytest.raises(IllegalActionError) as error:
            apply_action(item, _resolve(item, PROBE, accepted=True, selected_card_instance_ids=[hidden]))
        errors.append(str(error.value))
        assert match_state_hash(item) == before
    assert errors[0] == errors[1]


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_actual_live_end_expires_union_sql(tmp_path, owner):
    state = _probe(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    current = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True,
        selected_card_instance_ids=["audit-hand-0"])).state
    assert any(m.value == {"policy": "paid_basic_color_union_v1"} for m in current.players[owner].manual_modifiers)
    for _ in range(8):
        if not any(m.value == {"policy": "paid_basic_color_union_v1"} for m in current.players[owner].manual_modifiers):
            break
        current = repo.apply(state.match_id, _advance(current)).state
    assert not any(m.value == {"policy": "paid_basic_color_union_v1"} for m in current.players[owner].manual_modifiers)
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_hidden_departed_source_never_leaks_in_player_or_provider_context(owner):
    state = _probe(owner, control=True)
    current = apply_action(state, _advance(state)).state
    current = apply_action(current, _manual(current, "CONTROL", [
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "main_deck"},
    ])).state
    for viewer in ("player_1", "player_2"):
        payload = _match_state_payload(current, events=[], legal_actions=generate_legal_actions(current), player_id=viewer)
        assert "source-live" not in payload["state"]["cards"]
        assert '"paid_basic_color_source_v1":' not in json.dumps(payload)
        assert '"paid_basic_color_union_v1":' not in json.dumps(payload)
    result = apply_action(current, _resolve(current, PROBE, accepted=True,
        selected_card_instance_ids=["audit-hand-0"])).state
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    for builder in (build_api_play_context, build_agent_context):
        context = json.dumps(builder(result, generate_legal_actions(result)))
        assert "source-live" not in context
        assert '"paid_basic_color_source_v1":' not in context
        assert '"paid_basic_color_union_v1":' not in context


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("hide_source", [False, True])
def test_real_recent_events_respect_hidden_source_and_private_hand(owner, hide_source):
    state = _probe(owner, control=hide_source)
    triggered = apply_action(state, _advance(state))
    assert any(e.event_type == "effect_triggered" and e.data.get("effect_id") == PROBE for e in triggered.events)
    current = triggered.state
    recent = list(triggered.events)
    if hide_source:
        moved = apply_action(current, _manual(current, "CONTROL", [
            {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "main_deck"},
        ]))
        current = moved.state
        recent.extend(moved.events)
    for viewer in ("player_1", "player_2"):
        payload = _match_state_payload(current, events=recent, legal_actions=generate_legal_actions(current), player_id=viewer)
        serialized = json.dumps(payload, ensure_ascii=False)
        assert '"paid_basic_color_source_v1":' not in serialized
        assert '"paid_basic_color_union_v1":' not in serialized
        if hide_source:
            assert "source-live" not in serialized
        if viewer != owner:
            assert all(i not in serialized for i in current.players[owner].hand)
    resolved = apply_action(current, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=["audit-hand-0"]))
    assert any(e.event_type == "effect_cost_paid" and e.data.get("selected_card_instance_ids") == ["audit-hand-0"]
               for e in resolved.events)
    for viewer in ("player_1", "player_2"):
        payload = _match_state_payload(resolved.state, events=recent + resolved.events,
            legal_actions=generate_legal_actions(resolved.state), player_id=viewer)
        serialized = json.dumps(payload, ensure_ascii=False)
        assert '"paid_basic_color_source_v1":' not in serialized
        assert '"paid_basic_color_union_v1":' not in serialized
        assert any(e["event_type"] == "effect_cost_paid" for e in payload["events"])
        assert "audit-hand-0" in payload["state"]["cards"]
        if hide_source:
            assert "source-live" not in serialized
        if viewer != owner:
            assert all(i not in serialized for i in resolved.state.players[owner].hand)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("tampering", ["wrong_player", "fake_source", "fake_paid", "extra_branch", "energy", "decline_with_card"])
def test_wrong_player_and_extra_client_fields_are_atomic(owner, tampering):
    state = _probe(owner)
    current = apply_action(state, _advance(state)).state
    action = _resolve(current, PROBE, accepted=True, selected_card_instance_ids=["audit-hand-0"])
    if tampering == "wrong_player":
        action.player_id = "player_2" if owner == "player_1" else "player_1"
    elif tampering == "fake_source":
        action.payload["paid_basic_color_source_v1"] = {"stage_member": True}
    elif tampering == "fake_paid":
        action.payload["paid_basic_color_union_v1"] = {"paid": True}
    elif tampering == "extra_branch":
        action.payload["selected_branch"] = "fake"
    elif tampering == "energy":
        action.payload["energy_instance_ids"] = ["fake-energy"]
    else:
        action.payload["accepted"] = False
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        apply_action(current, action)
    assert match_state_hash(current) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_and_private_contexts_for_unregistered_probe(owner, policy):
    state = _probe(owner)
    current = apply_action(state, _advance(state)).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(current)
    decision = controller.choose_action(current, generate_legal_actions(current), controlled_player_ids={owner})
    changed = current.model_copy(deep=True)
    opponent = "player_2" if owner == "player_1" else "player_1"
    player = changed.players[opponent]
    for key in list(player.main_deck + player.hand):
        item = changed.cards.pop(key)
        replacement = "hidden-" + key
        item.instance_id = replacement
        item.card.name_ja = item.card.card_code = "HIDDEN"
        item.card.blade = 99
        changed.cards[replacement] = item
        player.main_deck = [replacement if i == key else i for i in player.main_deck]
        player.hand = [replacement if i == key else i for i in player.hand]
    changed_before = match_state_hash(changed)
    other = controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner})
    assert decision == other
    if isinstance(decision, SimpleAIDecision):
        apply_action(current, decision.action)
        apply_action(changed, other.action)
    else:
        assert isinstance(decision, SimpleAIBlocker) and decision.reason == "no_safe_ai_action"
    for viewer in ("player_1", "player_2"):
        payload = _match_state_payload(current, events=[], legal_actions=generate_legal_actions(current), player_id=viewer)
        for player in current.players.values():
            assert all(i not in payload["state"]["cards"] for i in player.main_deck)
            if player.player_id != viewer:
                assert all(i not in payload["state"]["cards"] for i in player.hand)
        assert '"paid_basic_color_union_v1":' not in json.dumps(payload)
        assert '"paid_basic_color_source_v1":' not in json.dumps(payload)
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    for builder in (build_api_play_context, build_agent_context):
        assert '"paid_basic_color_union_v1":' not in json.dumps(builder(current, generate_legal_actions(current)))
        assert '"paid_basic_color_source_v1":' not in json.dumps(builder(current, generate_legal_actions(current)))
    assert match_state_hash(current) == before and match_state_hash(changed) == changed_before
