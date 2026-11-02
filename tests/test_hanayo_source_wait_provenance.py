import hashlib
from contextlib import closing
from pathlib import Path

import pytest

from test_ready_source_wait_active_target_v2 import _state as _probe_state, PROBE
from test_ready_source_wait_cost_probe import _control_checkpoint
from test_printemps_producer_coverage import _legacy_hanayo
from test_printemps_ready_history_boundary import _repo, _replay, _manual
from loveca.db.bootstrap import connect_database
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effects import load_effect_registry
from loveca.simulation.engine import apply_action, generate_legal_actions, IllegalActionError
from loveca.simulation.models import ActionRequest
from loveca.simulation.ready_history import current_effect_readied_members
from loveca.simulation.online import match_state_hash
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIBlocker, SimpleAIPolicy
from loveca.webapp import _match_state_payload

CODE = "PL!-bp6-008"
EFFECT = CODE + ":1"
HASH = "c5c21450dc637b1907f36eb45ba9c264b4fbd1a6a7092aa2dbc6a5bc9b27179c"
TEXT = "【起動】【ターン1回】このメンバーをウェイトにする：自分のステージにいるほかのメンバー1人をアクティブにする。"


def _state(owner="player_1", *, active=False, legacy=False):
    state = _probe_state(owner, active=active)
    state.effect_definitions.pop(PROBE)
    definitions = {e.effect_id: e for e in load_effect_registry().effects}
    state.effect_definitions[EFFECT] = _legacy_hanayo(definitions[EFFECT]) if legacy else definitions[EFFECT]
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        state.cards["source-live"].card = _load_definition(db, CODE, None, definitions, {})
    state.member_ready_history = None
    return state


def _activate(state):
    return ActionRequest(action_type="activate_effect", player_id=state.active_player_id, expected_revision=state.revision,
        payload={"effect_id": EFFECT, "source_card_instance_id": "source-live", "energy_instance_ids": []})


def _resolve(state, target="target"):
    invocation = next(i for i in state.pending_effects if i.effect_id == EFFECT)
    return ActionRequest(action_type="resolve_effect", player_id=invocation.player_id, expected_revision=state.revision,
        payload={"invocation_id": invocation.invocation_id, "selected_card_instance_ids": [target]})


def test_old_formal_snapshot_does_not_record_hanayo_source_red():
    state = _state()
    paid = apply_action(state, _activate(state)).state
    result = apply_action(paid, _resolve(paid)).state
    assert current_effect_readied_members(result, "player_1", unit_key="printemps") == ["target"]


def test_old_formal_snapshot_rejects_active_target_red():
    state = _state(active=True)
    paid = apply_action(state, _activate(state)).state
    assert apply_action(paid, _resolve(paid)).state.cards["target"].orientation == "active"


def test_formal_card_identity_and_source():
    card = _state().cards["source-live"].card
    assert card.name_ja == "小泉花陽" and card.text_revision_id == 10
    assert card.raw_effect_text_ja == TEXT
    assert hashlib.sha256(TEXT.encode()).hexdigest() == card.raw_text_hash == HASH
    assert card.unit_keys == ["printemps"] and card.work_keys == ["love_live"]


def test_precise_generator_and_unchanged_registry_scope():
    from loveca.simulation.effect_candidates import _activated_wait_ready_other, _PATTERNS
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        from loveca.simulation.effect_candidates import _effect_text_rows
        row = next(dict(r) for r in _effect_text_rows(db) if r["card_code"] == CODE)
    candidate = _activated_wait_ready_other(row)
    assert candidate.pattern_id == "activated_hanayo_wait_ready_other_provenance_v2"
    assert candidate.actions == [{"action_type": "ready_member_after_source_wait_provenance_v2", "target": "selected"}]
    for field, value in [("text_revision_id", 11), ("raw_text_hash", "OTHER"),
                         ("raw_effect_text_ja", " " + TEXT), ("raw_effect_text_ja", TEXT + " ")]:
        changed = dict(row, **{field: value})
        assert not any(pattern(changed) is not None for pattern in _PATTERNS)
    assert _activated_wait_ready_other(dict(row, card_code="OTHER")).pattern_id != candidate.pattern_id
    definitions = load_effect_registry().effects
    new = next(e for e in definitions if e.effect_id == EFFECT)
    old = _legacy_hanayo(new)
    assert old.condition == {"source_zone": "stage", "source_orientation": "active"}
    assert old.choice.orientation == "wait" and old.actions[0].action_type == "ready_member"
    assert new.condition == {} and new.choice.orientation is None
    assert new.actions[0].action_type == "ready_member_after_source_wait_provenance_v2"
    producers = {e.effect_id for e in definitions if any(a.action_type in {"ready_member_with_provenance_v1", "ready_member_after_source_wait_provenance_v2"} for a in e.actions)}
    assert producers == {EFFECT, "PL!-pb1-012:1", "PL!-bp3-001:2", "PL!-pb1-028:1"}
    assert next(e for e in definitions if e.effect_id == "PL!-pb2-010:1").simulation_support == "manual_resolution"


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("target", ["target", "wrong-work"])
def test_formal_two_step_and_original_source_sql(tmp_path, owner, active, target):
    state = _state(owner, active=active); before = match_state_hash(state); repo = _repo(state, tmp_path)
    paid = repo.apply(state.match_id, _activate(state)).state
    inv = next(i for i in paid.pending_effects if i.effect_id == EFFECT)
    assert paid.cards["source-live"].orientation == "wait"
    assert inv.trigger_data["ready_source_wait_cost_v1"]["paid"] is True
    prior = paid.cards[target].orientation
    result = repo.apply(state.match_id, _resolve(paid, target)).state
    assert result.cards[target].orientation == "active" and match_state_hash(state) == before
    assert len(result.member_ready_history.events) == int(prior == "wait")
    assert current_effect_readied_members(result, owner, unit_key="printemps", work_key="love_live") == ([target] if prior == "wait" else [])
    if prior == "wait":
        source = result.member_ready_history.events[0].source
        assert (source.effect_id, source.owner_id, source.effect_player_id) == (EFFECT, owner, owner)
        assert source.unit_keys == ["printemps"] and source.work_keys == ["love_live"]
    assert len([usage for usage in result.effect_usage if usage.effect_id == EFFECT]) == 1
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("invalid", ["wait", "missing_target", "attached_source", "wrong_owner"])
def test_source_conditions_match_actual_payment_and_legal_actions_sql(tmp_path, owner, invalid):
    state = _state(owner, active=True); p = state.players[owner]
    if invalid == "wait": state.cards["source-live"].orientation = "wait"
    elif invalid == "missing_target":
        for slot in ["center", "right"]:
            key = p.member_area[slot]
            if key is not None: p.hand.append(key)
            p.member_area[slot] = None
    elif invalid == "attached_source":
        p.member_area["left"] = None; p.member_area_attachments["center"].append("source-live")
    else: state.cards["source-live"].owner_id = "player_2" if owner == "player_1" else "player_1"
    repo = _repo(state, tmp_path); before = match_state_hash(state)
    actions = [entry for action in generate_legal_actions(state) if action.action_type == "activate_effect" for entry in action.options["activations"]]
    assert not any(a["effect_id"] == EFFECT for a in actions)
    with pytest.raises(IllegalActionError): repo.apply(state.match_id, _activate(state))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    _replay(repo, state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("movement", ["hand", "main_deck", "return", "position"])
def test_original_paid_source_lki_legacy_order_checkpoint_sql(tmp_path, owner, active, movement):
    state = _state(owner, active=active)
    paid = apply_action(state, _activate(state)).state
    checkpoint = _control_checkpoint(paid, legacy_order=True); repo = _repo(checkpoint, tmp_path)
    if movement == "position": changes = [{"adjustment_type": "position_change", "from_slot": "left", "to_slot": "right"}]
    else:
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "main_deck" if movement == "main_deck" else "hand"}]
        if movement == "return": changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_left"})
    moved = repo.apply(checkpoint.match_id, _manual(checkpoint, "CONTROL", changes)).state
    result = repo.apply(checkpoint.match_id, _resolve(moved)).state
    assert len(result.member_ready_history.events) == int(not active)
    if not active:
        source = result.member_ready_history.events[0].source
        assert source.departed is (movement != "position") and source.unit_keys == ["printemps"] and source.owner_id == owner
    _replay(repo, result)


@pytest.mark.parametrize("scenario", ["valid", "source_wait", "no_other"])
def test_old_and_new_source_preconditions_match_when_target_was_already_eligible(scenario):
    available = []
    for legacy in [True, False]:
        state = _state(legacy=legacy)
        if scenario == "source_wait": state.cards["source-live"].orientation = "wait"
        if scenario == "no_other":
            for slot in ["center", "right"]:
                key = state.players["player_1"].member_area[slot]
                if key is not None: state.players["player_1"].hand.append(key)
                state.players["player_1"].member_area[slot] = None
        entries = [entry for action in generate_legal_actions(state) if action.action_type == "activate_effect"
                   for entry in action.options["activations"]]
        available.append(any(entry["effect_id"] == EFFECT for entry in entries))
    assert available == [scenario == "valid", scenario == "valid"]


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("payload", [
    {"selected_card_instance_ids": []}, {"selected_card_instance_ids": ["source-live"]},
    {"selected_card_instance_ids": ["target", "target"]}, {"energy_instance_ids": ["fake"]},
    {"selected_branch": "fake"}, {"color_slot": "heart01"}, {"accepted": False},
    {"ready_source_wait_cost_v1": {"paid": True}},
])
def test_formal_invalid_submissions_are_atomic(owner, payload):
    state = _state(owner, active=True); paid = apply_action(state, _activate(state)).state
    request = _resolve(paid); request.payload.update(payload); before = match_state_hash(paid)
    with pytest.raises(IllegalActionError): apply_action(paid, request)
    assert match_state_hash(paid) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_activation_cannot_inline_target_or_extra_energy(owner):
    for extra in [{"selected_card_instance_ids": ["target"]}, {"energy_instance_ids": ["fake"]}]:
        state = _state(owner); request = _activate(state); request.payload.update(extra); before = match_state_hash(state)
        with pytest.raises(IllegalActionError): apply_action(state, request)
        assert match_state_hash(state) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_old_formal_snapshot_remains_replayable_sql(tmp_path, owner):
    state = _state(owner, legacy=True); repo = _repo(state, tmp_path)
    paid = repo.apply(state.match_id, _activate(state)).state
    result = repo.apply(state.match_id, _resolve(paid)).state
    assert result.member_ready_history is None and result.cards["target"].orientation == "active"
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("movement", ["hand", "return", "position", "wait"])
def test_actual_target_object_after_ready_sql(tmp_path, owner, movement):
    state = _state(owner); paid = apply_action(state, _activate(state)).state
    ready = apply_action(paid, _resolve(paid)).state
    token = ready.member_ready_history.object_ids["target"]
    checkpoint = _control_checkpoint(ready)
    if movement == "wait":
        from loveca.simulation.effects import EffectDefinition
        raw = checkpoint.effect_definitions["CONTROL"].model_dump(mode="json")
        raw.update(execution_mode="prompt_then_resolve", simulation_support="test_validated_executable",
            actions=[{"action_type": "apply_wait_member", "target": "selected"}],
            choice={"choice_type": "member_from_stage", "zone": "stage", "card_type": "member", "minimum": 1, "maximum": 1})
        checkpoint.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
        inv = next(i for i in checkpoint.pending_effects if i.effect_id == "CONTROL")
        action = ActionRequest(action_type="resolve_effect", player_id=owner, expected_revision=checkpoint.revision,
            payload={"invocation_id": inv.invocation_id, "selected_card_instance_ids": ["target"]})
    elif movement == "position":
        action = _manual(checkpoint, "CONTROL", [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "right"}])
    else:
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": "target", "to_zone": "hand"}]
        if movement == "return": changes.append({"adjustment_type": "move_card", "target_card_instance_id": "target", "to_zone": "member_center"})
        action = _manual(checkpoint, "CONTROL", changes)
    repo = _repo(checkpoint, tmp_path)
    result = repo.apply(checkpoint.match_id, action).state
    retained = movement in {"position", "wait"}
    assert current_effect_readied_members(result, owner, unit_key="printemps") == (["target"] if retained else [])
    assert (result.member_ready_history.object_ids.get("target") == token) is retained
    _replay(repo, result)


def test_modern_paid_parent_lock_rejects_interposed_control():
    state = _state(); paid = apply_action(state, _activate(state)).state
    checkpoint = _control_checkpoint(paid); before = match_state_hash(checkpoint)
    with pytest.raises(IllegalActionError, match="another effect must resolve first"):
        apply_action(checkpoint, _manual(checkpoint, "CONTROL", [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"}]))
    assert match_state_hash(checkpoint) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_two_original_hanayo_sources_ready_same_member_sql(tmp_path, owner):
    from loveca.simulation.effects import EffectDefinition
    state = _state(owner)
    state.cards["wrong-work"].card = state.cards["source-live"].card.model_copy(deep=True)
    state.cards["wrong-work"].orientation = "active"
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id="CONTROL-WAIT", card_code="AUDIT-CONTROL", frequency_limit="none", cost=[],
        actions=[{"action_type": "apply_wait_member", "target": "selected"}],
        choice={"choice_type": "member_from_stage", "zone": "stage", "card_type": "member", "minimum": 1, "maximum": 1})
    state.effect_definitions["CONTROL-WAIT"] = EffectDefinition.model_validate(raw)
    state.cards["target"].card.effect_ids = ["CONTROL-WAIT"]
    repo = _repo(state, tmp_path)
    paid = repo.apply(state.match_id, _activate(state)).state
    first = repo.apply(paid.match_id, _resolve(paid)).state
    control = repo.apply(first.match_id, ActionRequest(action_type="activate_effect", player_id=owner, expected_revision=first.revision,
        payload={"effect_id": "CONTROL-WAIT", "source_card_instance_id": "target", "energy_instance_ids": []})).state
    control_invocation = next(i for i in control.pending_effects if i.effect_id == "CONTROL-WAIT")
    waited = repo.apply(control.match_id, ActionRequest(action_type="resolve_effect", player_id=owner, expected_revision=control.revision,
        payload={"invocation_id": control_invocation.invocation_id, "selected_card_instance_ids": ["target"]})).state
    activate = _activate(waited); activate.payload["source_card_instance_id"] = "wrong-work"
    paid = repo.apply(waited.match_id, activate).state
    result = repo.apply(paid.match_id, _resolve(paid)).state
    assert len(result.member_ready_history.events) == 2
    assert {event.source.instance_id for event in result.member_ready_history.events} == {"source-live", "wrong-work"}
    assert current_effect_readied_members(result, owner, unit_key="printemps") == ["target"]
    assert len([usage for usage in result.effect_usage if usage.effect_id == EFFECT]) == 2
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_real_formal_target_and_hidden_source(owner, active, policy):
    import json
    from loveca.simulation.ready_history import COST_KEY, SOURCE_KEY
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    state = _state(owner, active=active); before = match_state_hash(state)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    legal = [a for a in generate_legal_actions(state) if a.action_type == "activate_effect"]
    decision = controller.choose_action(state, legal, controlled_player_ids={owner})
    if isinstance(decision, SimpleAIBlocker):
        assert decision.reason == "no_safe_ai_action"
        paid = apply_action(state, _activate(state)).state
    else:
        assert isinstance(decision, SimpleAIDecision)
        paid = apply_action(state, decision.action).state
    assert match_state_hash(state) == before
    checkpoint = _control_checkpoint(paid, legacy_order=True)
    moved = apply_action(checkpoint, _manual(checkpoint, "CONTROL", [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "main_deck"}]))
    current = moved.state; before = match_state_hash(current)
    decision = controller.choose_action(current, generate_legal_actions(current), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    changed = current.model_copy(deep=True)
    for player in changed.players.values():
        for key in list(player.main_deck + (player.hand if player.player_id != owner else [])):
            card = changed.cards.pop(key); replacement = "HIDDEN-" + key; card.instance_id = replacement
            card.card.name_ja = card.card.card_code = "HIDDEN"
            card.card.unit_keys, card.card.work_keys, card.card.blade = ["bibi"], ["hasunosora"], 99
            changed.cards[replacement] = card
            player.main_deck = [replacement if i == key else i for i in player.main_deck]
            player.hand = [replacement if i == key else i for i in player.hand]
            for inv in changed.pending_effects:
                if inv.source_card_instance_id == key:
                    inv.source_card_instance_id = replacement
                    inv.trigger_data[SOURCE_KEY]["instance_id"] = replacement
                    inv.trigger_data[COST_KEY]["source_instance_id"] = replacement
    changed_before = match_state_hash(changed)
    other = controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner})
    assert isinstance(other, SimpleAIDecision) and other.action == decision.action
    assert match_state_hash(current) == before and match_state_hash(changed) == changed_before
    result, other_result = apply_action(current, decision.action), apply_action(changed, other.action)
    assert len(result.state.member_ready_history.events) == len(other_result.state.member_ready_history.events) == int(not active)
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(result.state, events=[*moved.events, *result.events], legal_actions=result.legal_actions, player_id=viewer)
        assert COST_KEY not in json.dumps(payload) and SOURCE_KEY not in json.dumps(payload)
        assert "member_ready_history" not in payload["state"]
        for player in result.state.players.values():
            assert not any(i in payload["state"]["cards"] for i in player.main_deck)
            if player.player_id != viewer: assert not any(i in payload["state"]["cards"] for i in player.hand)
    for builder in [build_api_play_context, build_agent_context]:
        payload = json.dumps(builder(current, generate_legal_actions(current)))
        assert COST_KEY not in payload and SOURCE_KEY not in payload and "member_ready_history" not in payload
