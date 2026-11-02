import json
import pytest
from pydantic import ValidationError

from test_member_ready_provenance import _state, _advance, _resolve, PROBE
from test_printemps_ready_history_boundary import _repo, _replay, _manual
from loveca.simulation.engine import apply_action, generate_legal_actions, IllegalActionError
from loveca.simulation.ready_history import current_effect_readied_members, current_qualified_effect_readied_members as query
from loveca.simulation.models import ActionRequest, MatchState
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.online import match_state_hash
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.webapp import _match_state_payload

POLICY = "qualified_source_v1"
KEY = "qualified_ready_source_v1"
OLD = "UNREGISTERED-OLD-READY"


def _query(state, owner="player_1", **kwargs):
    return query(state, owner, source_owner_id=owner, effect_player_id=owner,
                 unit_key=kwargs.get("unit_key", "printemps"), work_key=kwargs.get("work_key", "love_live"))


def _mixed(owner="player_1", unit="bibi", work="love_live", *, enabled=True, repeat=False):
    state = _state(owner=owner, selected=True)
    state.member_ready_coverage_policy = POLICY if enabled else None
    raw = state.effect_definitions[PROBE].model_dump(mode="json")
    raw.update(effect_id=OLD, card_code="UNREGISTERED-OLD-READY", actions=[{"action_type": "ready_member", "target": "selected"}])
    if repeat:
        raw["actions"] += [{"action_type": "apply_wait_member", "target": "selected"}, {"action_type": "ready_member", "target": "selected"}]
    state.effect_definitions[OLD] = EffectDefinition.model_validate(raw)
    state.cards["source-live"].card.effect_ids = [OLD]
    state.cards["source-live"].card.unit_keys = [unit]
    state.cards["source-live"].card.work_keys = [work]
    return state


def _old(state):
    inv = next(i for i in state.pending_effects if i.effect_id == OLD)
    return ActionRequest(action_type="resolve_effect", player_id=inv.player_id, expected_revision=state.revision,
                         payload={"invocation_id": inv.invocation_id, "selected_card_instance_ids": ["wrong-work"]})


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("waits", [0, 1, 3])
def test_explicit_qualified_policy_has_separate_read_only_query_sql(tmp_path, owner, waits):
    state = _state(waits=waits, owner=owner)
    state.member_ready_coverage_policy = POLICY
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _resolve(current)).state
    before = match_state_hash(result)
    assert len(_query(result, owner)) == waits
    assert len(current_effect_readied_members(result, owner)) == waits
    assert match_state_hash(result) == before
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("unit,work", [("printemps", "love_live"), ("bibi", "love_live"), ("printemps", "hasunosora")])
def test_legacy_changes_only_disprove_matching_qualified_scope_sql(tmp_path, owner, unit, work):
    state = _mixed(owner, unit, work)
    repo = _repo(state, tmp_path)
    begun = repo.apply(state.match_id, _advance(state)).state
    legacy = repo.apply(state.match_id, _old(begun)).state
    result = repo.apply(state.match_id, _resolve(legacy, ["target"])).state
    assert current_effect_readied_members(result, owner) is None
    assert _query(result, owner) == (None if unit == "printemps" and work == "love_live" else ["target"])
    assert len(result.member_ready_qualified_coverage.unknown_changes) == 1
    assert len(result.member_ready_history.events) == 1
    assert _query(result, owner, unit_key=unit, work_key=work) is None
    other = "player_2" if owner == "player_1" else "player_1"
    assert _query(result, other) == []
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("repeat", [False, True])
def test_already_active_and_repeat_legacy_change_are_not_counted_sql(tmp_path, owner, repeat):
    state = _mixed(owner, repeat=repeat)
    if not repeat: state.cards["wrong-work"].orientation = "active"
    repo = _repo(state, tmp_path)
    begun = repo.apply(state.match_id, _advance(state)).state
    legacy = repo.apply(state.match_id, _old(begun)).state
    result = repo.apply(state.match_id, _resolve(legacy, ["target"])).state
    assert _query(result, owner) == ["target"]
    assert len(result.member_ready_qualified_coverage.unknown_changes) == int(repeat)
    assert result.member_ready_history.coverage_complete is (not repeat)
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("movement", ["hand", "main_deck", "return", "position"])
def test_legacy_original_source_lki_excludes_only_its_proven_nonmatching_scope_sql(tmp_path, owner, movement):
    state = _mixed(owner)
    repo = _repo(state, tmp_path)
    begun = repo.apply(state.match_id, _advance(state)).state
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live",
                "to_zone": "hand" if movement == "return" else movement}]
    if movement == "position": changes = [{"adjustment_type": "position_change", "from_slot": "left", "to_slot": "center"}]
    if movement == "return": changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_left"})
    moved = repo.apply(state.match_id, _manual(begun, "CONTROL", changes)).state
    legacy = repo.apply(state.match_id, _old(moved)).state
    result = repo.apply(state.match_id, _resolve(legacy, ["target"])).state
    assert _query(result, owner) == ["target"]
    assert result.member_ready_qualified_coverage.unknown_changes[0].source.departed is (movement != "position")
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("movement", [None, "hand", "return"])
def test_initially_departed_legacy_source_cannot_be_guessed_from_current_card_sql(tmp_path, owner, movement):
    from test_ready_departed_source_probe import _state as departed, _play, _resolve as finish
    state = departed(owner, legacy=True, control=movement is not None)
    state.member_ready_coverage_policy = POLICY
    state.effect_definitions["DORMANT-UNREGISTERED-V1"] = _state().effect_definitions[PROBE].model_copy(deep=True)
    state.cards["good-target"].card.unit_keys = ["bibi"]
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play(state)).state
    if movement:
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": "good-target", "to_zone": "hand"}]
        if movement == "return": changes.append({"adjustment_type": "move_card", "target_card_instance_id": "good-target", "to_zone": "member_center"})
        current = repo.apply(state.match_id, _manual(current, "CONTROL", changes)).state
    result = repo.apply(state.match_id, finish(current)).state
    assert result.member_ready_qualified_coverage.unknown_changes[0].source is None
    assert _query(result, owner) is None
    assert _query(result, owner, unit_key="bibi") is None
    _replay(repo, result)


@pytest.mark.parametrize("enabled", [False, True])
def test_opt_in_snapshot_does_not_change_old_json_or_query_sql(tmp_path, enabled):
    state = _mixed(enabled=enabled)
    repo = _repo(state, tmp_path)
    begun = repo.apply(state.match_id, _advance(state)).state
    inv = next(i for i in begun.pending_effects if i.effect_id == OLD)
    assert (KEY in inv.trigger_data) is enabled
    legacy = repo.apply(state.match_id, _old(begun)).state
    result = repo.apply(state.match_id, _resolve(legacy, ["target"])).state
    payload = result.model_dump(mode="json")
    assert ("member_ready_coverage_policy" in payload) is enabled
    assert ("member_ready_qualified_coverage" in payload) is enabled
    assert current_effect_readied_members(result, "player_1") is None
    assert _query(result) == (["target"] if enabled else None)
    _replay(repo, result)


@pytest.mark.parametrize("movement", ["hand", "return", "position", "formation"])
def test_current_original_target_objects_only_sql(tmp_path, movement):
    state = _state(); state.member_ready_coverage_policy = POLICY
    repo = _repo(state, tmp_path)
    begun = repo.apply(state.match_id, _advance(state)).state
    current = repo.apply(state.match_id, _resolve(begun)).state
    if movement == "position": changes = [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "right"}]
    elif movement == "formation": changes = [{"adjustment_type": "formation_change", "slot_assignments": {"left": "target", "center": "wrong-work", "right": "source-live"}}]
    else:
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": "target", "to_zone": "hand"}]
        if movement == "return": changes.append({"adjustment_type": "move_card", "target_card_instance_id": "target", "to_zone": "member_center"})
    result = repo.apply(state.match_id, _manual(current, "CONTROL", changes)).state
    assert ("target" in _query(result)) is (movement in {"position", "formation"})
    _replay(repo, result)


def test_true_active_phase_is_not_a_card_effect_sql(tmp_path):
    state = _state(); state.member_ready_coverage_policy = POLICY
    state.phase, state.active_player_id = "first_active", "player_1"
    repo = _repo(state, tmp_path)
    result = repo.apply(state.match_id, _advance(state)).state
    assert _query(result) == [] and not result.member_ready_qualified_coverage.unknown_changes
    _replay(repo, result)


def test_next_turn_clears_qualified_unknowns_and_old_global_coverage_sql(tmp_path):
    state = _mixed(unit="printemps")
    current = apply_action(state, _advance(state)).state
    current = apply_action(current, _old(current)).state
    assert _query(current) is None
    current.pending_effects = []
    current.phase, current.next_first_player_id = "turn_complete", "player_1"
    repo = _repo(current, tmp_path)
    result = repo.apply(current.match_id, ActionRequest(action_type="start_next_turn", expected_revision=current.revision)).state
    assert _query(result) == [] and not result.member_ready_qualified_coverage.unknown_changes
    assert result.member_ready_history.coverage_complete
    _replay(repo, result)


@pytest.mark.parametrize("reason", ["late", "flags", "old_history"])
def test_missing_prior_evidence_is_unknown_never_zero(reason):
    state = _state(); state.member_ready_coverage_policy = POLICY
    if reason == "late": state.revision = 3
    elif reason == "flags": state.players["player_1"].effect_ready_flags_this_turn = ["love_live:member"]
    else:
        state = apply_action(state, _advance(state)).state
        state.member_ready_qualified_coverage = None
    result = apply_action(state, _advance(state)).state if reason != "old_history" else apply_action(state, _resolve(state)).state
    assert _query(result) is None


@pytest.mark.parametrize("field,value", [("turn_number", True), ("baseline_complete", 1), ("policy", "old")])
def test_qualified_ledger_is_strict(field, value):
    state = _state(); state.member_ready_coverage_policy = POLICY
    raw = apply_action(state, _advance(state)).state.model_dump(mode="json")
    raw["member_ready_qualified_coverage"][field] = value
    with pytest.raises(ValidationError): MatchState.model_validate(raw)


@pytest.mark.parametrize("field,value", [("turn_number", True), ("effect_id", "OTHER"), ("invocation_id", "OTHER"), ("instance_id", "OTHER")])
def test_malformed_original_source_proof_is_atomically_rejected(field, value):
    state = _mixed(); current = apply_action(state, _advance(state)).state
    inv = next(i for i in current.pending_effects if i.effect_id == OLD)
    inv.trigger_data[KEY][field] = value
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError): apply_action(current, _old(current))
    assert match_state_hash(current) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_real_choice_keeps_qualified_coverage_private_and_hidden_invariant(owner, policy):
    state = _mixed(owner)
    begun = apply_action(state, _advance(state))
    moved = apply_action(begun.state, _manual(begun.state, "CONTROL", [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "main_deck"}]))
    legacy = apply_action(moved.state, _old(moved.state))
    current = legacy.state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(current)
    decision = controller.choose_action(current, generate_legal_actions(current), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    changed = current.model_copy(deep=True)
    for p in changed.players.values():
        for key in list(p.main_deck + (p.hand if p.player_id != owner else [])):
            item = changed.cards.pop(key); replacement = "HIDDEN-" + key
            item.instance_id = replacement
            item.card.name_ja = item.card.card_code = "HIDDEN"
            item.card.unit_keys, item.card.work_keys = ["printemps"], ["hasunosora"]
            item.card.blade = 99
            changed.cards[replacement] = item
            p.main_deck = [replacement if i == key else i for i in p.main_deck]
            p.hand = [replacement if i == key else i for i in p.hand]
            for change in changed.member_ready_qualified_coverage.unknown_changes:
                if change.source and change.source.instance_id == key: change.source.instance_id = replacement
    changed_before = match_state_hash(changed)
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner}).action == decision.action
    assert match_state_hash(current) == before and match_state_hash(changed) == changed_before
    result = apply_action(current, decision.action)
    other = apply_action(changed, decision.action)
    assert _query(result.state, owner) == _query(other.state, owner) == decision.action.payload["selected_card_instance_ids"]
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(result.state, events=[*begun.events, *moved.events, *legacy.events, *result.events],
                                       legal_actions=result.legal_actions, player_id=viewer)
        text = json.dumps(payload)
        assert KEY not in text and "member_ready_qualified_coverage" not in text and "member_ready_coverage_policy" not in text
        assert "source-live" not in payload["state"]["cards"]
        for p in result.state.players.values():
            assert not any(i in payload["state"]["cards"] for i in p.main_deck)
            if p.player_id != viewer: assert not any(i in payload["state"]["cards"] for i in p.hand)
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    for builder in [build_api_play_context, build_agent_context]:
        text = json.dumps(builder(current, generate_legal_actions(current)))
        assert KEY not in text and "member_ready_qualified_coverage" not in text


@pytest.mark.parametrize("policy", [False, True])
def test_without_trusted_producer_history_legacy_lki_remains_private_but_unknown_sql(tmp_path, policy):
    state = _state(legacy=True)
    state.member_ready_coverage_policy = POLICY if policy else None
    repo = _repo(state, tmp_path)
    begun = repo.apply(state.match_id, _advance(state)).state
    moved = repo.apply(state.match_id, _manual(begun, "CONTROL", [{"adjustment_type": "move_card", "target_card_instance_id": "live-1", "to_zone": "hand"}])).state
    result = repo.apply(state.match_id, _resolve(moved)).state
    assert _query(result) is None
    assert result.member_ready_history is None
    _replay(repo, result)


def test_legacy_source_cost_is_unknown_not_falsely_attested_sql(tmp_path):
    from test_ready_source_wait_cost_probe import _state as cost_state, _activate, _resolve as finish
    state = cost_state(legacy=True); state.member_ready_coverage_policy = POLICY
    state.effect_definitions["DORMANT-UNREGISTERED-V1"] = _state().effect_definitions[PROBE].model_copy(deep=True)
    state.cards["source-live"].card.unit_keys = ["bibi"]
    repo = _repo(state, tmp_path)
    paid = repo.apply(state.match_id, _activate(state)).state
    result = repo.apply(state.match_id, finish(paid)).state
    assert result.member_ready_qualified_coverage.unknown_changes[0].source is None
    assert _query(result) is None
    _replay(repo, result)


def test_query_does_not_guess_past_unit_from_returned_new_card():
    state = _mixed()
    begun = apply_action(state, _advance(state)).state
    moved = apply_action(begun, _manual(begun, "CONTROL", [
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"},
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_left"}])).state
    moved.cards["source-live"].card.unit_keys = ["printemps"]
    legacy = apply_action(moved, _old(moved)).state
    result = apply_action(legacy, _resolve(legacy, ["target"])).state
    assert _query(result) == ["target"]
    assert _query(result, unit_key="bibi") is None


@pytest.mark.parametrize("repeat", [False, True])
def test_trusted_duplicate_and_later_wait_keep_one_original_object_sql(tmp_path, repeat):
    state = _state(selected=True, repeat=repeat); state.member_ready_coverage_policy = POLICY
    raw = state.effect_definitions["CONTROL"].model_dump(mode="json")
    raw.update(execution_mode="prompt_then_resolve", simulation_support="test_validated_executable",
        actions=[{"action_type": "apply_wait_member", "target": "selected"}],
        choice={"choice_type": "member_from_stage", "zone": "stage", "card_type": "member", "minimum": 1, "maximum": 1})
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    repo = _repo(state, tmp_path)
    begun = repo.apply(state.match_id, _advance(state)).state
    current = repo.apply(state.match_id, _resolve(begun, ["target"])).state
    inv = next(i for i in current.pending_effects if i.effect_id == "CONTROL")
    result = repo.apply(state.match_id, ActionRequest(action_type="resolve_effect", player_id="player_1", expected_revision=current.revision,
        payload={"invocation_id": inv.invocation_id, "selected_card_instance_ids": ["target"]})).state
    assert result.cards["target"].orientation == "wait"
    assert _query(result) == ["target"] and len(result.member_ready_history.events) == 1
    _replay(repo, result)


@pytest.mark.parametrize("payload", [{KEY: {}}, {"member_ready_coverage_policy": POLICY}, {"member_ready_qualified_coverage": {}}, {"energy_instance_ids": ["fake"]}])
def test_client_cannot_submit_coverage_or_source_proof(payload):
    state = _mixed(); current = apply_action(state, _advance(state)).state
    action = _old(current); action.payload.update(payload)
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError): apply_action(current, action)
    assert match_state_hash(current) == before


@pytest.mark.parametrize("field,value", [("source_owner_id", "missing"), ("effect_player_id", "missing"), ("unit_key", True), ("work_key", "")])
def test_invalid_qualified_query_is_rejected(field, value):
    state = _state(); state.member_ready_coverage_policy = POLICY
    current = apply_action(state, _advance(state)).state
    kwargs = {"source_owner_id": "player_1", "effect_player_id": "player_1", "unit_key": "printemps", "work_key": "love_live", field: value}
    with pytest.raises(ValueError): query(current, "player_1", **kwargs)


@pytest.mark.parametrize("field,value", [("turn_number", 99), ("invocation_id", "OTHER"), ("effect_player_id", "player_2")])
def test_stale_qualified_unknown_cannot_prove_nonmatching_scope(field, value):
    state = _mixed(); begun = apply_action(state, _advance(state)).state
    current = apply_action(begun, _old(begun)).state
    setattr(current.member_ready_qualified_coverage.unknown_changes[0].source, field, value)
    with pytest.raises(ValueError): _query(current)


def test_source_owner_effect_player_and_target_owner_are_separate_qualifiers():
    state = _state(); state.member_ready_coverage_policy = POLICY
    current = apply_action(state, _advance(state)).state
    result = apply_action(current, _resolve(current)).state
    before = match_state_hash(result)
    assert len(_query(result)) == 3
    assert query(result, "player_1", source_owner_id="player_2", effect_player_id="player_1") == []
    assert query(result, "player_1", source_owner_id="player_1", effect_player_id="player_2") == []
    assert query(result, "player_2", source_owner_id="player_1", effect_player_id="player_1") == []
    assert match_state_hash(result) == before


def test_late_trusted_history_cannot_upgrade_existing_incomplete_baseline():
    from loveca.simulation.ready_history import begin_ready_tracking, MemberReadyQualifiedCoverageV1
    state = _state(); state.revision = 10; state.member_ready_coverage_policy = POLICY
    state.member_ready_qualified_coverage = MemberReadyQualifiedCoverageV1(turn_number=state.turn_number, baseline_complete=True)
    begin_ready_tracking(state)
    assert _query(state) is None


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_unknown_legacy_ready_is_bound_to_actual_opponent_target_owner_sql(tmp_path, owner):
    state = _mixed(owner)
    other = "player_2" if owner == "player_1" else "player_1"
    state.players[owner].member_area["right"] = None
    displaced = state.players[other].member_area["left"]
    if displaced: state.players[other].hand.append(displaced)
    state.players[other].member_area["left"] = "wrong-work"
    state.cards["wrong-work"].owner_id = other
    raw = state.effect_definitions[OLD].model_dump(mode="json")
    raw["choice"]["target_player"] = "opponent"
    state.effect_definitions[OLD] = EffectDefinition.model_validate(raw)
    repo = _repo(state, tmp_path)
    begun = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _old(begun)).state
    assert result.member_ready_qualified_coverage.unknown_changes[0].target_owner_id == other
    assert query(result, other, source_owner_id=owner, effect_player_id=owner, unit_key="bibi") is None
    assert query(result, owner, source_owner_id=owner, effect_player_id=owner, unit_key="bibi") == []
    _replay(repo, result)
