import hashlib
import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from test_printemps_producer_coverage import _state as _audit_state, _play_for, _resolve, CODE, EFFECT
from test_printemps_ready_history_boundary import _repo, _replay, _manual
from loveca.simulation.effects import load_effect_registry, EffectDefinition
from loveca.simulation.engine import apply_action, generate_legal_actions, IllegalActionError, StaleRevisionError
from loveca.simulation.models import ActionRequest
from loveca.simulation.online import match_state_hash
from loveca.simulation.ready_history import OPERATION, SOURCE_KEY, current_effect_readied_members
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.webapp import _match_state_payload


def _state(*, legacy=False, **kwargs):
    state = _audit_state(**kwargs)
    if not legacy:
        state.effect_definitions[EFFECT] = next(e for e in load_effect_registry().effects if e.effect_id == EFFECT)
    return state


def _members(state, owner="player_1"):
    return current_effect_readied_members(state, owner, unit_key="printemps", work_key="love_live")


def test_native_kotori_records_its_actual_wait_to_active_source_red():
    initial = _state()
    played = apply_action(initial, _play_for(initial)).state
    result = apply_action(played, _resolve(played, ["good-target"])).state
    assert result.member_ready_history is not None
    assert len(result.member_ready_history.events) == 1
    assert result.member_ready_history.events[0].source.effect_id == EFFECT


def test_generator_uses_exact_provenance_snapshot_red():
    from loveca.simulation.effect_candidates import _onplay_ready_printemps_member_up_to1
    card = _state().cards["source-live"].card
    candidate = _onplay_ready_printemps_member_up_to1({"card_code": CODE, "text_revision_id": card.text_revision_id,
        "raw_text_hash": card.raw_text_hash, "raw_effect_text_ja": card.raw_effect_text_ja})
    assert candidate.pattern_id == "onplay_ready_printemps_member_up_to1_provenance_v3"
    assert candidate.actions == [{"action_type": "ready_member_with_provenance_v1"}]


def test_formal_provenance_operation_retains_ready_member_ai_value():
    from loveca.simulation.ai import _operation_value_without_observation
    from loveca.simulation.effects import EffectOperation
    operation = _state().effect_definitions[EFFECT].actions[0]
    assert _operation_value_without_observation(operation, is_cost=False) == _operation_value_without_observation(EffectOperation(action_type="ready_member"), is_cost=False) == 6


@pytest.mark.parametrize("field,value", [("raw_text_hash", "OTHER"), ("text_revision_id", 428),
    ("raw_effect_text_ja", " 【登場】自分のステージにいる『Printemps』のメンバーを1人までアクティブにする。"),
    ("raw_effect_text_ja", "【登場】自分のステージにいる『Printemps』のメンバーを1人までアクティブにする。 ")])
def test_changed_identity_cannot_fall_back_to_another_structured_pattern(field, value):
    from loveca.db.bootstrap import connect_database
    from loveca.simulation.effect_candidates import _effect_text_rows, _PATTERNS
    with connect_database(Path("data/loveca.sqlite3")) as db:
        row = next(dict(r) for r in _effect_text_rows(db) if r["card_code"] == CODE)
    row[field] = value
    assert not any(pattern(row) is not None for pattern in _PATTERNS)


def test_identity_and_only_one_formal_history_producer():
    state = _state(); card = state.cards["source-live"].card
    assert (card.name_ja, card.cost, card.blade) == ("南ことり", 2, 1)
    assert card.text_revision_id == 427
    assert card.raw_effect_text_ja == "【登場】自分のステージにいる『Printemps』のメンバーを1人までアクティブにする。"
    assert hashlib.sha256(card.raw_effect_text_ja.encode()).hexdigest() == card.raw_text_hash == "b9330edc34a6956d65e6eb4f353a012df515635f142ff3312f42c9bd9d8b182c"
    assert card.unit_keys == ["printemps"] and card.work_keys == ["love_live"]
    definitions = load_effect_registry().effects
    assert {e.effect_id for e in definitions if any(a.action_type == OPERATION for a in e.actions)} == {EFFECT, "PL!-bp3-001:2"}
    consumer = next(e for e in definitions if e.effect_id == "PL!-pb2-010:1")
    assert consumer.simulation_support == "manual_resolution"
    assert state.member_ready_coverage_policy is None


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("targets,ids", [("none", []), ("wrong", []), ("good", []), ("good", ["good-target"]),
    ("both", []), ("both", ["good-target"]), ("two-good", ["wrong-target"])])
def test_native_zero_or_one_actual_member_history_sql(tmp_path, owner, targets, ids):
    state = _state(owner=owner, targets=targets); before = match_state_hash(state)
    repo = _repo(state, tmp_path)
    played = repo.apply(state.match_id, _play_for(state)).state
    if any(i.effect_id == EFFECT for i in played.pending_effects):
        result = repo.apply(state.match_id, _resolve(played, ids)).state
    else:
        assert ids == []
        result = played
    assert match_state_hash(state) == before
    assert _members(result, owner) == ids
    assert len(result.member_ready_history.events) == len(ids)
    for event in result.member_ready_history.events:
        assert event.source.effect_id == EFFECT and event.source.instance_id == "source-live"
        assert event.source.owner_id == event.source.effect_player_id == owner
        assert event.source.unit_keys == ["printemps"] and event.source.work_keys == ["love_live"]
        assert event.source.turn_number == result.turn_number and not event.source.departed
    assert result.member_ready_coverage_policy is None and result.member_ready_qualified_coverage is None
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("kind", ["active", "attached"])
def test_active_and_attached_members_do_not_create_ready_fact_sql(tmp_path, owner, kind):
    state = _state(owner=owner)
    if kind == "active": state.cards["good-target"].orientation = "active"
    else:
        state.players[owner].member_area["left"] = None
        state.players[owner].member_area_attachments["right"].append("good-target")
    repo = _repo(state, tmp_path)
    played = repo.apply(state.match_id, _play_for(state)).state
    result = repo.apply(state.match_id, _resolve(played, ["good-target"] if kind == "active" else [])).state if any(i.effect_id == EFFECT for i in played.pending_effects) else played
    assert _members(result, owner) == [] and not result.member_ready_history.events
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("movement", ["hand", "main_deck", "waiting_room", "return", "position", "formation"])
def test_native_source_interference_keeps_original_information_sql(tmp_path, owner, movement):
    state = _state(owner=owner, control=True)
    repo = _repo(state, tmp_path)
    played = repo.apply(state.match_id, _play_for(state)).state
    if movement == "position": changes = [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "right"}]
    elif movement == "formation": changes = [{"adjustment_type": "formation_change", "slot_assignments": {"left": "source-live", "center": "wrong-target", "right": "good-target"}}]
    else:
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand" if movement == "return" else movement}]
        if movement == "return": changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_center"})
    moved = repo.apply(state.match_id, _manual(played, "CONTROL", changes)).state
    result = repo.apply(state.match_id, _resolve(moved, ["good-target"])).state
    event = result.member_ready_history.events[0]
    assert event.source.departed is (movement not in {"position", "formation"})
    assert event.source.unit_keys == ["printemps"] and event.source.work_keys == ["love_live"]
    assert _members(result, owner) == ["good-target"]
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("movement", ["hand", "main_deck", "return", "position", "formation", "attached_return"])
def test_original_target_objects_not_bare_instance_ids_sql(tmp_path, owner, movement):
    state = _state(owner=owner, control=True)
    repo = _repo(state, tmp_path)
    played = repo.apply(state.match_id, _play_for(state)).state
    ready = repo.apply(state.match_id, _resolve(played, ["good-target"])).state
    token = ready.member_ready_history.object_ids["good-target"]
    if movement == "position": changes = [{"adjustment_type": "position_change", "from_slot": "left", "to_slot": "right"}]
    elif movement == "formation": changes = [{"adjustment_type": "formation_change", "slot_assignments": {"left": "source-live", "center": "wrong-target", "right": "good-target"}}]
    else:
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": "good-target", "to_zone": "main_deck" if movement == "main_deck" else "hand"}]
        if movement == "return": changes.append({"adjustment_type": "move_card", "target_card_instance_id": "good-target", "to_zone": "member_left"})
        elif movement == "attached_return":
            changes += [{"adjustment_type": "attach_card_under_member", "target_card_instance_id": "good-target", "target_slot": "center"},
                        {"adjustment_type": "move_attached_card", "target_card_instance_id": "good-target", "to_zone": "member_left"}]
    result = repo.apply(state.match_id, _manual(ready, "CONTROL", changes)).state
    retained = movement in {"position", "formation"}
    assert _members(result, owner) == (["good-target"] if retained else [])
    assert (result.member_ready_history.object_ids.get("good-target") == token) is retained
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("mode", ["source_wait", "target_wait", "old_ready"])
def test_control_wait_and_legacy_ready_do_not_rewrite_facts_sql(tmp_path, owner, mode):
    state = _state(owner=owner, control=True)
    raw = state.effect_definitions["CONTROL"].model_dump(mode="json")
    raw.update(execution_mode="prompt_then_resolve", simulation_support="test_validated_executable",
        actions=[{"action_type": "ready_member" if mode == "old_ready" else "apply_wait_member", "target": "source" if mode == "source_wait" else "selected"}],
        choice=None if mode == "source_wait" else {"choice_type": "member_from_stage", "zone": "stage", "card_type": "member", "minimum": 1, "maximum": 1})
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    repo = _repo(state, tmp_path)
    played = repo.apply(state.match_id, _play_for(state)).state
    if mode != "source_wait": played = repo.apply(state.match_id, _resolve(played, ["good-target"])).state
    inv = next(i for i in played.pending_effects if i.effect_id == "CONTROL")
    current = repo.apply(state.match_id, ActionRequest(action_type="resolve_effect", player_id=owner, expected_revision=played.revision,
        payload={"invocation_id": inv.invocation_id, **({} if mode == "source_wait" else {"selected_card_instance_ids": ["wrong-target" if mode == "old_ready" else "good-target"]})})).state
    if mode == "source_wait":
        current = repo.apply(state.match_id, _resolve(current, ["source-live"])).state
        assert _members(current, owner) == ["source-live"]
    elif mode == "target_wait": assert _members(current, owner) == ["good-target"] and current.cards["good-target"].orientation == "wait"
    else:
        assert _members(current, owner) is None
        assert len(current.member_ready_history.events) == 1
    assert current.member_ready_coverage_policy is None
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("legacy", [False, True])
def test_precise_old_v2_snapshot_keeps_legacy_json_and_replay_sql(tmp_path, owner, legacy):
    state = _state(owner=owner, legacy=legacy)
    repo = _repo(state, tmp_path)
    played = repo.apply(state.match_id, _play_for(state)).state
    result = repo.apply(state.match_id, _resolve(played, ["good-target"])).state
    assert (SOURCE_KEY in played.pending_effects[0].trigger_data) is (not legacy)
    assert ("member_ready_history" in result.model_dump(mode="json")) is (not legacy)
    assert result.cards["good-target"].orientation == "active"
    _replay(repo, result)


@pytest.mark.parametrize("payload", [{"selected_card_instance_ids": ["wrong-target"]}, {"selected_card_instance_ids": ["good-target", "good-target"]},
    {"selected_card_instance_ids": ["opponent-secret"]}, {"selected_card_instance_ids": ["missing"]}, {"energy_instance_ids": ["fake"]},
    {"source_card_instance_id": "wrong-target"}, {SOURCE_KEY: {}}, {"selected_color_slot": "heart01"}, {"accepted": False}])
def test_illegal_formal_submissions_are_atomic(payload):
    state = _state(); played = apply_action(state, _play_for(state)).state
    action = _resolve(played, ["good-target"]); action.payload.update(payload)
    before = match_state_hash(played)
    with pytest.raises(IllegalActionError): apply_action(played, action)
    assert match_state_hash(played) == before


def test_wrong_role_stale_and_repeated_submission_are_rejected():
    state = _state(); played = apply_action(state, _play_for(state)).state
    action = _resolve(played, ["good-target"]); action.player_id = "player_2"
    before = match_state_hash(played)
    with pytest.raises(IllegalActionError): apply_action(played, action)
    action = _resolve(played, ["good-target"]); action.expected_revision -= 1
    with pytest.raises(StaleRevisionError): apply_action(played, action)
    assert match_state_hash(played) == before
    action = _resolve(played, ["good-target"]); resolved = apply_action(played, action).state
    action.expected_revision = resolved.revision
    with pytest.raises(IllegalActionError): apply_action(resolved, action)


def test_returned_new_source_card_does_not_replace_original_lki_sql(tmp_path):
    state = _state(control=True)
    played = apply_action(state, _play_for(state)).state
    returned = apply_action(played, _manual(played, "CONTROL", [
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"},
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_center"}])).state
    returned.cards["source-live"].card.unit_keys = ["bibi"]
    returned.cards["source-live"].card.work_keys = ["hasunosora"]
    repo = _repo(returned, tmp_path)
    result = repo.apply(returned.match_id, _resolve(returned, ["good-target"])).state
    assert _members(result) == ["good-target"]
    assert result.member_ready_history.events[0].source.unit_keys == ["printemps"]
    assert result.member_ready_history.events[0].source.work_keys == ["love_live"]
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_two_real_copies_in_one_turn_count_current_member_once_sql(tmp_path, owner):
    from loveca.simulation.models import CardInstance, CardDefinition
    state = _state(owner=owner, control=True)
    state.cards["second-kotori"] = state.cards["source-live"].model_copy(deep=True)
    state.cards["second-kotori"].instance_id = "second-kotori"
    state.cards["second-kotori"].card.effect_ids = [EFFECT]
    state.players[owner].hand.append("second-kotori")
    raw = state.effect_definitions["CONTROL"].model_dump(mode="json")
    raw.update(execution_mode="prompt_then_resolve", simulation_support="test_validated_executable",
        actions=[{"action_type": "apply_wait_member", "target": "selected"}],
        choice={"choice_type": "member_from_stage", "zone": "stage", "card_type": "member", "minimum": 1, "maximum": 1})
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    for i in range(2):
        key = f"second-energy-{i}"
        state.cards[key] = CardInstance(instance_id=key, owner_id=owner,
            card=CardDefinition(card_code="AUDIT-ENERGY", card_id=key, name_ja="AUDIT", card_type="energy"))
        state.players[owner].energy_area.append(key)
    repo = _repo(state, tmp_path)
    action = _play_for(state); action.payload["energy_instance_ids"] = state.players[owner].energy_area[:2]
    played = repo.apply(state.match_id, action).state
    first = repo.apply(state.match_id, _resolve(played, ["good-target"])).state
    inv = next(i for i in first.pending_effects if i.effect_id == "CONTROL")
    waited = repo.apply(state.match_id, ActionRequest(action_type="resolve_effect", player_id=owner, expected_revision=first.revision,
        payload={"invocation_id": inv.invocation_id, "selected_card_instance_ids": ["good-target"]})).state
    second = repo.apply(state.match_id, ActionRequest(action_type="play_member", player_id=owner, expected_revision=waited.revision,
        payload={"card_instance_id": "second-kotori", "slot": "right", "use_baton_touch": False,
                 "energy_instance_ids": [i for i in waited.players[owner].energy_area if waited.cards[i].orientation == "active"]})).state
    result = repo.apply(state.match_id, _resolve(second, ["good-target"])).state
    assert len(result.member_ready_history.events) == 2
    assert {e.source.instance_id for e in result.member_ready_history.events} == {"source-live", "second-kotori"}
    assert _members(result, owner) == ["good-target"]
    assert len({e.target_object_id for e in result.member_ready_history.events}) == 1
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_formal_choice_hidden_invariance_and_full_privacy(owner, policy):
    initial = _state(owner=owner, control=True)
    entered = apply_action(initial, _play_for(initial))
    moved = apply_action(entered.state, _manual(entered.state, "CONTROL", [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "main_deck"}]))
    state = moved.state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    changed = state.model_copy(deep=True)
    for p in changed.players.values():
        for key in list(p.main_deck + (p.hand if p.player_id != owner else [])):
            item = changed.cards.pop(key); replacement = "HIDDEN-" + key
            item.instance_id = replacement; item.card.name_ja = item.card.card_code = "HIDDEN"
            item.card.unit_keys, item.card.work_keys = ["bibi"], ["hasunosora"]; item.card.blade = 99
            changed.cards[replacement] = item
            p.main_deck = [replacement if i == key else i for i in p.main_deck]
            p.hand = [replacement if i == key else i for i in p.hand]
            for inv in changed.pending_effects:
                if inv.source_card_instance_id == key:
                    inv.source_card_instance_id = replacement
                    inv.trigger_data[SOURCE_KEY]["instance_id"] = replacement
    changed_before = match_state_hash(changed)
    second = controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner})
    assert isinstance(second, SimpleAIDecision) and second.action == decision.action
    assert match_state_hash(state) == before and match_state_hash(changed) == changed_before
    assert decision.action.payload.get("selected_card_instance_ids") == ["good-target"]
    result, other = apply_action(state, decision.action), apply_action(changed, second.action)
    assert _members(result.state, owner) == _members(other.state, owner) == ["good-target"]
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(result.state, events=[*entered.events, *moved.events, *result.events], legal_actions=result.legal_actions, player_id=viewer)
        assert "member_ready_history" not in payload["state"] and SOURCE_KEY not in json.dumps(payload)
        for p in result.state.players.values():
            assert not any(i in payload["state"]["cards"] for i in p.main_deck)
            if p.player_id != viewer: assert not any(i in payload["state"]["cards"] for i in p.hand)
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    for builder in [build_api_play_context, build_agent_context]: assert SOURCE_KEY not in json.dumps(builder(state, generate_legal_actions(state)))
    assert match_state_hash(state) == before
