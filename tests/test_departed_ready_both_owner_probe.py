import json
import pytest

from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.models import ActionRequest, CardDefinition, CardInstance
from loveca.simulation.online import match_state_hash
from loveca.simulation.ready_history import current_qualified_effect_readied_members
from loveca.webapp import _match_state_payload
from test_bottom_one_aqours_requirement import _exclusive
from test_printemps_ready_history_boundary import _manual, _repo, _replay
from test_ready_departed_source_probe import PROBE, _play, _state as _base_state

OPERATION = "ready_member_from_departed_both_provenance_v2"
POLICY = "public_departed_ready_both_one"


def _state(owner="player_1", control=False):
    state = _base_state(owner=owner, control=control)
    raw = state.effect_definitions[PROBE].model_dump(mode="json")
    raw["actions"] = [{"action_type": OPERATION, "target": "selected"}]
    raw["choice"]["selection_policy"] = POLICY
    raw["choice"]["orientation"] = None
    state.effect_definitions[PROBE] = EffectDefinition.model_validate(raw)
    other = "player_2" if owner == "player_1" else "player_1"
    for orientation, slot in [("wait", "center"), ("active", "right")]:
        key = "audit-opponent-" + orientation
        existing = state.players[other].member_area[slot]
        if existing:
            state.players[other].hand.append(existing)
        state.cards[key] = CardInstance(instance_id=key, owner_id=other, orientation=orientation,
            card=CardDefinition(card_code=key, card_id=key, name_ja=key, card_type="member", cost=4, blade=1))
        state.players[other].member_area[slot] = key
    _exclusive(state)
    return state


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("selection", ["wrong-target", "own-active", "audit-opponent-wait", "audit-opponent-active", "none", "decline"])
def test_departed_both_top_targets_sql(tmp_path, owner, selection):
    state = _state(owner)
    if selection == "own-active":
        state.cards["wrong-target"].orientation = "active"
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play(state)).state
    invocation = next(i for i in current.pending_effects if i.effect_id == PROBE)
    choices = next(a.options for a in generate_legal_actions(current) if a.action_type == "resolve_effect")
    candidates = next(i["candidate_card_instance_ids"] for i in choices["invocations"] if i["effect_id"] == PROBE)
    assert {"wrong-target", "audit-opponent-wait", "audit-opponent-active"} <= set(candidates)
    ids = [] if selection in {"none", "decline"} else ["wrong-target" if selection == "own-active" else selection]
    payload = {"invocation_id": invocation.invocation_id, "accepted": selection != "decline", "selected_card_instance_ids": ids}
    result = repo.apply(state.match_id, ActionRequest(action_type="resolve_effect", player_id=owner,
        expected_revision=current.revision, payload=payload)).state
    assert len(result.member_ready_history.events) == int(selection in {"wrong-target", "audit-opponent-wait"})
    if selection in {"wrong-target", "audit-opponent-wait"}:
        event = result.member_ready_history.events[0]
        assert event.target_owner_id == state.cards[selection].owner_id
        assert event.source.owner_id == event.source.effect_player_id == owner and event.source.departed
    _exclusive(result)
    _replay(repo, result)


def test_v2_is_not_registered_on_formal_cards():
    from loveca.simulation.effects import load_effect_registry
    assert not [e.effect_id for e in load_effect_registry().effects if any(a.action_type == OPERATION for a in e.actions)]


@pytest.mark.parametrize("field,value", [("target_player", "opponent"), ("orientation", "wait"), ("maximum", 2)])
def test_static_shape_rejects_unrelated_scope(field, value):
    raw = _state().effect_definitions[PROBE].model_dump(mode="json")
    raw["choice"][field] = value
    with pytest.raises(ValueError, match="fixed optional public choice"):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("field", ["cost_choice", "follow_up_choice"])
def test_policy_is_not_accepted_in_cost_or_follow_up(field):
    raw = _state().effect_definitions[PROBE].model_dump(mode="json")
    raw[field] = dict(raw["choice"])
    with pytest.raises(ValueError, match="cannot be used for costs or follow-up choices"):
        EffectDefinition.model_validate(raw)


def test_policy_is_not_accepted_with_legacy_operation():
    raw = _state().effect_definitions[PROBE].model_dump(mode="json")
    raw["actions"] = [{"action_type": "ready_member", "target": "selected"}]
    with pytest.raises(ValueError, match="requires its bounded operation"):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("movement", ["hand", "main_deck", "return"])
def test_original_departed_source_lki_after_move_sql(tmp_path, owner, movement):
    state = _state(owner, control=True)
    repo = _repo(state, tmp_path)
    departed = repo.apply(state.match_id, _play(state)).state
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "good-target",
                "to_zone": "hand" if movement == "return" else movement}]
    if movement == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "good-target", "to_zone": "member_center"})
    moved = repo.apply(state.match_id, _manual(departed, "CONTROL", changes)).state
    inv = next(i for i in moved.pending_effects if i.effect_id == PROBE)
    result = repo.apply(state.match_id, ActionRequest(action_type="resolve_effect", player_id=owner,
        expected_revision=moved.revision, payload={"invocation_id": inv.invocation_id, "accepted": True,
                                                  "selected_card_instance_ids": ["audit-opponent-wait"]})).state
    source = result.member_ready_history.events[0].source
    assert source.departed and source.owner_id == owner and source.unit_keys == ["printemps"]
    assert result.member_ready_history.events[0].target_owner_id != owner
    _exclusive(result)
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("target", ["wrong-target", "audit-opponent-wait"])
def test_illegal_payloads_are_atomic(owner, target):
    state = _state(owner)
    current = apply_action(state, _play(state)).state
    inv = next(i for i in current.pending_effects if i.effect_id == PROBE)
    before = match_state_hash(current)
    for payload in [
        {"invocation_id": inv.invocation_id, "selected_card_instance_ids": [target, target]},
        {"invocation_id": inv.invocation_id, "selected_card_instance_ids": ["missing"]},
        {"invocation_id": inv.invocation_id, "selected_card_instance_ids": [target], "energy_instance_ids": ["fake"]},
        {"invocation_id": inv.invocation_id, "selected_card_instance_ids": [target], "accepted": 1},
    ]:
        with pytest.raises(IllegalActionError):
            apply_action(current, ActionRequest(action_type="resolve_effect", player_id=owner,
                                               expected_revision=current.revision, payload=payload))
        assert match_state_hash(current) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("target", ["wrong-target", "audit-opponent-wait"])
@pytest.mark.parametrize("movement", ["hand", "return"])
def test_actual_target_departure_does_not_restore_original_token_sql(tmp_path, owner, target, movement):
    state = _state(owner, control=True)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play(state)).state
    invocation = next(i for i in current.pending_effects if i.effect_id == PROBE)
    current = repo.apply(state.match_id, ActionRequest(action_type="resolve_effect", player_id=owner,
        expected_revision=current.revision, payload={"invocation_id": invocation.invocation_id,
            "accepted": True, "selected_card_instance_ids": [target]})).state
    token = current.member_ready_history.object_ids[target]
    target_owner = current.cards[target].owner_id
    slot = next(key for key, value in current.players[target_owner].member_area.items() if value == target)
    changes = [{"target_player_id": target_owner, "adjustment_type": "move_card",
                "target_card_instance_id": target, "to_zone": "hand"}]
    if movement == "return":
        changes.append({"target_player_id": target_owner, "adjustment_type": "move_card",
                        "target_card_instance_id": target, "to_zone": "member_" + slot})
    result = repo.apply(state.match_id, _manual(current, "CONTROL", changes)).state
    assert result.member_ready_history.events[0].target_object_id == token
    assert result.member_ready_history.object_ids.get(target) != token
    _exclusive(result)
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_opponent_stage_position_move_keeps_original_token_sql(tmp_path, owner):
    state = _state(owner, control=True)
    other = "player_2" if owner == "player_1" else "player_1"
    existing = state.players[other].member_area["left"]
    if existing:
        state.players[other].hand.append(existing)
        state.players[other].member_area["left"] = None
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play(state)).state
    invocation = next(i for i in current.pending_effects if i.effect_id == PROBE)
    current = repo.apply(state.match_id, ActionRequest(action_type="resolve_effect", player_id=owner,
        expected_revision=current.revision, payload={"invocation_id": invocation.invocation_id,
            "accepted": True, "selected_card_instance_ids": ["audit-opponent-wait"]})).state
    token = current.member_ready_history.object_ids["audit-opponent-wait"]
    result = repo.apply(state.match_id, _manual(current, "CONTROL", [{"target_player_id": other,
        "adjustment_type": "position_change", "from_slot": "center", "to_slot": "left"}])).state
    assert result.member_ready_history.object_ids["audit-opponent-wait"] == token
    _exclusive(result)
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_choices_do_not_depend_on_hidden_cards(owner, policy):
    state = _state(owner, control=True)
    entered = apply_action(state, _play(state)).state
    current = apply_action(entered, _manual(entered, "CONTROL", [{"adjustment_type": "move_card",
        "target_card_instance_id": "good-target", "to_zone": "main_deck"}])).state
    before = match_state_hash(current)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    decision = controller.choose_action(current, generate_legal_actions(current), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    changed = current.model_copy(deep=True)
    for player in changed.players.values():
        for key in list(player.main_deck + (player.hand if player.player_id != owner else [])):
            item = changed.cards.pop(key)
            name = "HIDDEN-" + key
            item.instance_id = name
            item.card.name_ja = item.card.card_code = "HIDDEN"
            item.card.unit_keys = ["lily_white"]
            item.card.work_keys = ["hasunosora"]
            item.card.blade = 99
            changed.cards[name] = item
            player.main_deck = [name if i == key else i for i in player.main_deck]
            player.hand = [name if i == key else i for i in player.hand]
            for invocation in changed.pending_effects:
                if invocation.source_card_instance_id == key:
                    invocation.source_card_instance_id = name
                    invocation.trigger_data["ready_departed_source_v1"]["instance_id"] = name
                    invocation.trigger_data["ready_source_lki_v1"]["instance_id"] = name
    changed_before = match_state_hash(changed)
    changed_decision = controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner})
    assert isinstance(changed_decision, SimpleAIDecision) and changed_decision.action == decision.action
    assert match_state_hash(current) == before and match_state_hash(changed) == changed_before
    apply_action(current, decision.action)
    apply_action(changed, changed_decision.action)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_player_and_provider_views_hide_internal_departure_evidence(owner):
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    initial = _state(owner, control=True)
    entered = apply_action(initial, _play(initial))
    moved = apply_action(entered.state, _manual(entered.state, "CONTROL", [{"adjustment_type": "move_card",
        "target_card_instance_id": "good-target", "to_zone": "main_deck"}]))
    state = moved.state
    before = match_state_hash(state)
    legal = generate_legal_actions(state)
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(state, events=[*entered.events, *moved.events], legal_actions=legal, player_id=viewer)
        rendered = json.dumps(payload)
        assert "ready_departed_source_v1" not in rendered and "ready_source_lki_v1" not in rendered
        assert "member_ready_history" not in payload["state"] and "good-target" not in payload["state"]["cards"]
        for player in state.players.values():
            assert not any(i in payload["state"]["cards"] for i in player.main_deck)
            if player.player_id != viewer:
                assert not any(i in payload["state"]["cards"] for i in player.hand)
    for builder in [build_api_play_context, build_agent_context]:
        rendered = json.dumps(builder(state, legal))
        assert "ready_departed_source_v1" not in rendered and "ready_source_lki_v1" not in rendered
        assert "member_ready_history" not in rendered
    assert match_state_hash(state) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_qualified_query_separates_source_and_opponent_target_sql(tmp_path, owner):
    state = _state(owner)
    state.member_ready_coverage_policy = "qualified_source_v1"
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play(state)).state
    inv = next(i for i in current.pending_effects if i.effect_id == PROBE)
    result = repo.apply(state.match_id, ActionRequest(action_type="resolve_effect", player_id=owner,
        expected_revision=current.revision, payload={"invocation_id": inv.invocation_id, "accepted": True,
            "selected_card_instance_ids": ["audit-opponent-wait"]})).state
    other = "player_2" if owner == "player_1" else "player_1"
    found = current_qualified_effect_readied_members(result, other, source_owner_id=owner,
        effect_player_id=owner, unit_key="printemps", work_key="love_live")
    assert found == ["audit-opponent-wait"]
    assert current_qualified_effect_readied_members(result, owner, source_owner_id=owner,
        effect_player_id=owner, unit_key="printemps", work_key="love_live") == []
    _replay(repo, result)
