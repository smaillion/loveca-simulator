import hashlib
import json
from contextlib import closing
from pathlib import Path

import pytest

from test_printemps_ready_history_boundary import _state as _boundary_state, _advance, _repo, _replay, _manual
from test_mirakura_front_position_boundary import _swap_roles
from loveca.db.bootstrap import connect_database
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import apply_action, generate_legal_actions, IllegalActionError, StaleRevisionError
from loveca.simulation.models import ActionRequest
from loveca.simulation.online import match_state_hash
from loveca.simulation.ready_history import SOURCE_KEY, current_effect_readied_members
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.webapp import _match_state_payload

CODE, EFFECT = "PL!-bp3-001", "PL!-bp3-001:2"
HASH = "03019af91423572a345dd28a3ff40213fb05239ed99452cff65fdd8c559bb476"
FULL_TEXT = "【起動】【ターン1回】このメンバーをウェイトにする：カードを1枚引き、手札を1枚控え室に置く。（ウェイト状態のメンバーが持つ【ブレード】は、エールで公開する枚数を増やさない。） 【ライブ開始時】自分のステージにいるメンバーを1人までアクティブにする。"


def _state(*, owner="player_1", legacy=False, control=False, active=False, duplicate=False):
    state = _boundary_state()
    state.effect_definitions = {e.effect_id: e for e in load_effect_registry().effects if e.card_code == CODE}
    if legacy:
        e = state.effect_definitions[EFFECT]
        state.effect_definitions[EFFECT] = e.model_copy(update={"actions": [e.actions[0].model_copy(update={"action_type": "ready_member"})],
            "is_optional": True, "choice": e.choice.model_copy(update={"orientation": "wait"})})
    for item in state.cards.values(): item.card.effect_ids = []
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        state.cards["source-live"].card = _load_definition(db, CODE, None, state.effect_definitions, {})
    state.cards["target"].card.unit_keys, state.cards["target"].card.work_keys = ["bibi"], ["love_live_sunshine"]
    state.cards["target"].orientation = "active" if active else "wait"
    state.cards["wrong-work"].orientation = "wait"
    if duplicate: state.cards["wrong-work"].card = state.cards["source-live"].card.model_copy(deep=True)
    if control:
        raw = state.effect_definitions[EFFECT].model_dump(mode="json")
        raw.update(effect_id="CONTROL", label_ja="AUDIT CONTROL only", frequency_limit="none", is_optional=False,
            actions=[{"action_type": "manual_resolution"}], choice=None, execution_mode="manual_resolution", simulation_support="manual_resolution")
        state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
        state.cards["live-1"].card.effect_ids.append("CONTROL")
    if owner == "player_2":
        state = _swap_roles(state)
        state.phase, state.active_player_id = "performance_second", owner
    return state


def _resolve(state, ids, **extra):
    inv = next(i for i in state.pending_effects if i.effect_id == EFFECT)
    return ActionRequest(action_type="resolve_effect", player_id=inv.player_id, expected_revision=state.revision,
        payload={"invocation_id": inv.invocation_id, "selected_card_instance_ids": ids, **extra})


def _members(state, owner="player_1"):
    return current_effect_readied_members(state, owner, unit_key="printemps", work_key="love_live")


def test_native_live_start_records_real_source_red():
    state = _state()
    begun = apply_action(state, _advance(state)).state
    result = apply_action(begun, _resolve(begun, ["target"])).state
    assert _members(result) == ["target"]
    assert result.member_ready_history.events[0].source.effect_id == EFFECT


def test_active_target_is_legal_without_false_ready_red():
    state = _state(active=True); begun = apply_action(state, _advance(state)).state
    result = apply_action(begun, _resolve(begun, ["target"])).state
    assert not result.member_ready_history.events


def test_mandatory_ability_cannot_be_declined_red():
    state = _state(); begun = apply_action(state, _advance(state)).state
    with pytest.raises(IllegalActionError): apply_action(begun, _resolve(begun, [], accepted=False))


def test_exact_full_identity_first_segment_and_two_producers():
    state = _state(); card = state.cards["source-live"].card
    assert (card.name_ja, card.cost, card.blade, card.text_revision_id) == ("高坂穂乃果", 13, 3, 442)
    assert card.raw_effect_text_ja == FULL_TEXT and hashlib.sha256(FULL_TEXT.encode()).hexdigest() == card.raw_text_hash == HASH
    first = state.effect_definitions[CODE + ":1"]
    assert first.label_ja == FULL_TEXT.split(" 【ライブ開始時】")[0]
    assert (first.trigger, first.timing, first.frequency_limit) == ("player_activation", "activated_main", "once_per_turn")
    assert [(a.action_type, a.target) for a in first.cost] == [("apply_wait", "source")]
    assert [(a.action_type, a.amount) for a in first.actions] == [("draw_card", 1), ("discard_from_hand", None)]
    assert first.choice.zone == "hand" and first.choice.minimum == first.choice.maximum == 1
    definitions = load_effect_registry().effects
    assert {e.effect_id for e in definitions if any(a.action_type == "ready_member_with_provenance_v1" for a in e.actions)} == {EFFECT, "PL!-pb1-012:1", "PL!-pb1-028:1"}
    assert next(e for e in definitions if e.effect_id == "PL!-pb2-010:1").simulation_support == "manual_resolution"


@pytest.mark.parametrize("field,value", [("card_code", "OTHER"), ("text_revision_id", 443), ("raw_text_hash", "OTHER"),
    ("raw_effect_text_ja", " " + FULL_TEXT), ("raw_effect_text_ja", FULL_TEXT + " "), ("raw_effect_text_ja", FULL_TEXT.replace("1枚引き", "2枚引き"))])
def test_generator_rejects_changed_full_card_identity(field, value):
    from loveca.simulation.effect_candidates import _live_start_honoka_ready_provenance, _PATTERNS
    row = {"card_code": CODE, "text_revision_id": 442, "raw_text_hash": HASH, "raw_effect_text_ja": FULL_TEXT}
    candidate = _live_start_honoka_ready_provenance(row)
    assert candidate.effect_index == 2 and not candidate.is_optional and "orientation" not in candidate.choice
    row[field] = value
    assert _live_start_honoka_ready_provenance(row) is None
    assert not any((c := pattern(row)) is not None and c.effect_index == 2 for pattern in _PATTERNS)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("ids,active", [([], False), (["target"], False), (["wrong-work"], False),
    (["source-live"], False), (["target"], True), ([], True)])
def test_native_live_start_zero_one_and_any_unit_sql(tmp_path, owner, ids, active):
    state = _state(owner=owner, active=active); before = match_state_hash(state)
    repo = _repo(state, tmp_path); begun = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _resolve(begun, ids)).state
    expected = [i for i in ids if state.cards[i].orientation == "wait"]
    assert match_state_hash(state) == before and _members(result, owner) == expected
    assert len(result.member_ready_history.events) == len(expected)
    for event in result.member_ready_history.events:
        assert event.source.effect_id == EFFECT and event.source.owner_id == event.source.effect_player_id == owner
        assert event.source.unit_keys == ["printemps"] and event.source.work_keys == ["love_live"]
        assert event.source.turn_number == result.turn_number
    assert result.member_ready_coverage_policy is None and result.member_ready_qualified_coverage is None
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("movement", ["hand", "main_deck", "waiting_room", "return", "position", "formation"])
def test_source_departure_or_in_stage_move_keeps_original_lki_sql(tmp_path, owner, movement):
    state = _state(owner=owner, control=True); repo = _repo(state, tmp_path)
    begun = repo.apply(state.match_id, _advance(state)).state
    if movement == "position": changes = [{"adjustment_type": "position_change", "from_slot": "left", "to_slot": "center"}]
    elif movement == "formation": changes = [{"adjustment_type": "formation_change", "slot_assignments": {"left": "target", "center": "source-live", "right": "wrong-work"}}]
    else:
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand" if movement == "return" else movement}]
        if movement == "return": changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_left"})
    moved = repo.apply(state.match_id, _manual(begun, "CONTROL", changes)).state
    result = repo.apply(state.match_id, _resolve(moved, ["target"])).state
    event = result.member_ready_history.events[0]
    assert event.source.departed is (movement not in {"position", "formation"})
    assert event.source.unit_keys == ["printemps"] and event.source.effect_id == EFFECT
    assert _members(result, owner) == ["target"]
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("movement", ["hand", "main_deck", "return", "position", "formation", "attached_return", "wait"])
def test_original_member_not_bare_instance_id_sql(tmp_path, owner, movement):
    state = _state(owner=owner, control=True)
    if movement == "wait":
        raw = state.effect_definitions["CONTROL"].model_dump(mode="json")
        raw.update(execution_mode="prompt_then_resolve", simulation_support="test_validated_executable",
            actions=[{"action_type": "apply_wait_member", "target": "selected"}],
            choice={"choice_type": "member_from_stage", "zone": "stage", "card_type": "member", "minimum": 1, "maximum": 1})
        state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    repo = _repo(state, tmp_path)
    begun = repo.apply(state.match_id, _advance(state)).state
    ready = repo.apply(state.match_id, _resolve(begun, ["target"])).state
    token = ready.member_ready_history.object_ids["target"]
    if movement == "position": changes = [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "right"}]
    elif movement == "formation": changes = [{"adjustment_type": "formation_change", "slot_assignments": {"left": "target", "center": "source-live", "right": "wrong-work"}}]
    elif movement == "wait": changes = []
    else:
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": "target", "to_zone": "main_deck" if movement == "main_deck" else "hand"}]
        if movement == "return": changes.append({"adjustment_type": "move_card", "target_card_instance_id": "target", "to_zone": "member_center"})
        elif movement == "attached_return": changes += [{"adjustment_type": "attach_card_under_member", "target_card_instance_id": "target", "target_slot": "left"},
            {"adjustment_type": "move_attached_card", "target_card_instance_id": "target", "to_zone": "member_center"}]
    if movement == "wait":
        inv = next(i for i in ready.pending_effects if i.effect_id == "CONTROL")
        action = ActionRequest(action_type="resolve_effect", player_id=owner, expected_revision=ready.revision,
            payload={"invocation_id": inv.invocation_id, "selected_card_instance_ids": ["target"]})
    else: action = _manual(ready, "CONTROL", changes)
    result = repo.apply(state.match_id, action).state
    retained = movement in {"position", "formation", "wait"}
    assert _members(result, owner) == (["target"] if retained else [])
    assert (result.member_ready_history.object_ids.get("target") == token) is retained
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_two_same_name_live_start_sources_remain_independent_sql(tmp_path, owner):
    state = _state(owner=owner, duplicate=True, control=True)
    raw = state.effect_definitions["CONTROL"].model_dump(mode="json")
    raw.update(execution_mode="prompt_then_resolve", simulation_support="test_validated_executable",
        actions=[{"action_type": "apply_wait_member", "target": "selected"}],
        choice={"choice_type": "member_from_stage", "zone": "stage", "card_type": "member", "minimum": 1, "maximum": 1})
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    repo = _repo(state, tmp_path); begun = repo.apply(state.match_id, _advance(state)).state
    assert len([i for i in begun.pending_effects if i.effect_id == EFFECT]) == 2
    first = repo.apply(state.match_id, _resolve(begun, ["target"])).state
    inv = next(i for i in first.pending_effects if i.effect_id == "CONTROL")
    waited = repo.apply(state.match_id, ActionRequest(action_type="resolve_effect", player_id=owner, expected_revision=first.revision,
        payload={"invocation_id": inv.invocation_id, "selected_card_instance_ids": ["target"]})).state
    result = repo.apply(state.match_id, _resolve(waited, ["target"])).state
    assert len(result.member_ready_history.events) == 2 and _members(result, owner) == ["target"]
    assert len({e.source.invocation_id for e in result.member_ready_history.events}) == 2
    assert {e.source.instance_id for e in result.member_ready_history.events} == {"source-live", "wrong-work"}
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_attached_target_is_not_top_level_sql(tmp_path, owner):
    state = _state(owner=owner); p = state.players[owner]
    p.member_area["center"] = None; p.member_area_attachments["left"].append("target")
    repo = _repo(state, tmp_path); begun = repo.apply(state.match_id, _advance(state)).state
    before = match_state_hash(begun)
    with pytest.raises(IllegalActionError): repo.apply(state.match_id, _resolve(begun, ["target"]))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    result = repo.apply(state.match_id, _resolve(begun, [])).state
    assert _members(result, owner) == []
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_no_stage_after_trigger_ends_with_zero_sql(tmp_path, owner):
    state = _state(owner=owner, control=True); repo = _repo(state, tmp_path)
    begun = repo.apply(state.match_id, _advance(state)).state
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": i, "to_zone": "hand"} for i in state.players[owner].member_area.values()]
    moved = repo.apply(state.match_id, _manual(begun, "CONTROL", changes)).state
    if any(i.effect_id == EFFECT for i in moved.pending_effects): result = repo.apply(state.match_id, _resolve(moved, [])).state
    else: result = moved
    assert _members(result, owner) == []
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("legacy", [True, False])
def test_old_snapshot_json_and_replay_sql(tmp_path, owner, legacy):
    state = _state(owner=owner, legacy=legacy); repo = _repo(state, tmp_path)
    begun = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _resolve(begun, ["target"])).state
    assert (SOURCE_KEY in begun.pending_effects[0].trigger_data) is (not legacy)
    assert ("member_ready_history" in result.model_dump(mode="json")) is (not legacy)
    assert result.cards["target"].orientation == "active"
    _replay(repo, result)


@pytest.mark.parametrize("payload", [{"selected_card_instance_ids": ["target", "target"]}, {"selected_card_instance_ids": ["target", "wrong-work"]},
    {"selected_card_instance_ids": ["deck-member-1"]}, {"selected_card_instance_ids": ["opponent-secret"]}, {"energy_instance_ids": ["fake"]},
    {"selected_branch": "fake"}, {"selected_color_slot": "heart01"}, {SOURCE_KEY: {}}, {"accepted": 1}, {"accepted": False}])
def test_invalid_submissions_are_atomic(payload):
    state = _state(); begun = apply_action(state, _advance(state)).state
    action = _resolve(begun, ["target"]); action.payload.update(payload); before = match_state_hash(begun)
    with pytest.raises(IllegalActionError): apply_action(begun, action)
    assert match_state_hash(begun) == before


def test_wrong_role_revision_and_duplicate_are_atomic():
    state = _state(); begun = apply_action(state, _advance(state)).state; before = match_state_hash(begun)
    action = _resolve(begun, ["target"]); action.player_id = "player_2"
    with pytest.raises(IllegalActionError): apply_action(begun, action)
    action = _resolve(begun, ["target"]); action.expected_revision -= 1
    with pytest.raises(StaleRevisionError): apply_action(begun, action)
    assert match_state_hash(begun) == before
    result = apply_action(begun, _resolve(begun, ["target"])).state
    with pytest.raises(IllegalActionError): apply_action(result, _resolve(begun, ["target"]).model_copy(update={"expected_revision": result.revision}))


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_original_first_segment_wait_draw_discard_is_unchanged_sql(tmp_path, owner):
    state = _state(owner=owner); state.phase = "first_main" if owner == "player_1" else "second_main"
    repo = _repo(state, tmp_path); p = state.players[owner]; count = len(p.hand)
    first = repo.apply(state.match_id, ActionRequest(action_type="activate_effect", player_id=owner, expected_revision=state.revision,
        payload={"effect_id": CODE + ":1", "source_card_instance_id": "source-live"})).state
    assert first.cards["source-live"].orientation == "wait" and len(first.players[owner].hand) == count + 1
    inv = next(i for i in first.pending_effects if i.effect_id == CODE + ":1")
    discard = first.players[owner].hand[0]
    result = repo.apply(state.match_id, ActionRequest(action_type="resolve_effect", player_id=owner, expected_revision=first.revision,
        payload={"invocation_id": inv.invocation_id, "selected_card_instance_ids": [discard]})).state
    assert discard in result.players[owner].waiting_room
    assert result.member_ready_history is None or not result.member_ready_history.events
    assert not any(a.action_type == "activate_effect" and any(o.get("effect_id") == CODE + ":1" for o in a.options.get("effects", [])) for a in generate_legal_actions(result))
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_wait_source_can_ready_itself_sql(tmp_path, owner):
    state = _state(owner=owner); state.cards["source-live"].orientation = "wait"
    repo = _repo(state, tmp_path); begun = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _resolve(begun, ["source-live"])).state
    assert _members(result, owner) == ["source-live"]
    _replay(repo, result)


def test_returned_source_new_information_does_not_overwrite_old_lki_sql(tmp_path):
    state = _state(control=True); begun = apply_action(state, _advance(state)).state
    returned = apply_action(begun, _manual(begun, "CONTROL", [
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"},
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_left"}])).state
    returned.cards["source-live"].card.unit_keys, returned.cards["source-live"].card.work_keys = ["bibi"], ["hasunosora"]
    repo = _repo(returned, tmp_path); result = repo.apply(returned.match_id, _resolve(returned, ["target"])).state
    assert _members(result) == ["target"]
    assert result.member_ready_history.events[0].source.unit_keys == ["printemps"]
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_hidden_source_invariance_and_full_privacy(owner, policy):
    state = _state(owner=owner, control=True); entered = apply_action(state, _advance(state))
    moved = apply_action(entered.state, _manual(entered.state, "CONTROL", [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "main_deck"}]))
    state = moved.state; before = match_state_hash(state)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
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
                    inv.source_card_instance_id = replacement; inv.trigger_data[SOURCE_KEY]["instance_id"] = replacement
    changed_before = match_state_hash(changed)
    second = controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner})
    assert isinstance(second, SimpleAIDecision) and second.action == decision.action
    assert match_state_hash(state) == before and match_state_hash(changed) == changed_before
    result, other = apply_action(state, decision.action), apply_action(changed, second.action)
    assert _members(result.state, owner) == _members(other.state, owner)
    assert len(result.state.member_ready_history.events) == 1
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(result.state, events=[*entered.events, *moved.events, *result.events], legal_actions=result.legal_actions, player_id=viewer)
        assert SOURCE_KEY not in json.dumps(payload) and "member_ready_history" not in payload["state"]
        for p in result.state.players.values():
            assert not any(i in payload["state"]["cards"] for i in p.main_deck)
            if p.player_id != viewer: assert not any(i in payload["state"]["cards"] for i in p.hand)
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    for builder in [build_api_play_context, build_agent_context]: assert SOURCE_KEY not in json.dumps(builder(state, generate_legal_actions(state)))
