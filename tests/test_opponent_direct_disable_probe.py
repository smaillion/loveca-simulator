import json
import pytest
from pydantic import ValidationError

from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import apply_action, generate_legal_actions, IllegalActionError, _source_trigger_disabled
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.online import match_state_hash
from loveca.simulation.models import ManualModifier
from loveca.webapp import _match_state_payload
from test_opponent_live_success_disable_scope import _state, _resolve, PROBE
from test_printemps_ready_history_boundary import _advance, _manual, _repo, _replay

OPERATION = "disable_opponent_direct_live_success_v1"
POLICY = "original_opponent_direct_disable_source_v1"


def _raw():
    raw = _state("player_1", probe=True).effect_definitions[PROBE].model_dump(mode="json")
    raw["actions"] = [{"action_type": OPERATION, "target": "selected", "source_object_policy": POLICY}]
    return raw


def test_explicit_unregistered_probe_is_valid():
    effect = EffectDefinition.model_validate(_raw())
    assert effect.actions[0].action_type == OPERATION


@pytest.mark.parametrize("field,value", [("card_code", "FORMAL"), ("is_optional", True),
    ("duration", "game"), ("condition", {"unknown": True}), ("trigger", "member_played"),
    ("cost", [{"action_type": "discard_from_hand"}])])
def test_probe_rejects_other_parent_shapes(field, value):
    raw = _raw(); raw[field] = value
    with pytest.raises(ValidationError): EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("field,value", [("target_player", "self"), ("minimum", 0), ("maximum", 2),
    ("card_type", "live"), ("unit_key", "aqours")])
def test_probe_rejects_other_choice_shapes(field, value):
    raw = _raw(); raw["choice"][field] = value
    with pytest.raises(ValidationError): EffectDefinition.model_validate(raw)


def _probe(owner, *, direct=True, duplicate=False, control=False, target=True):
    state = _state(owner, probe=True, duplicate=duplicate, control=control, target=target)
    for effect_id in [PROBE, PROBE + "-SECOND"] if duplicate else [PROBE]:
        raw = state.effect_definitions[effect_id].model_dump(mode="json")
        raw["actions"] = _raw()["actions"]
        state.effect_definitions[effect_id] = EffectDefinition.model_validate(raw)
    state.cards["source-live"].card.card_code = "UNREGISTERED-OPPONENT-DISABLE"
    if target and direct:
        raw = state.effect_definitions[PROBE].model_dump(mode="json")
        raw.update(effect_id="AUDIT-OPPONENT:1", card_code="AUDIT-OPPONENT", timing="live_success",
                   trigger="live_succeeded", execution_mode="auto_resolve", choice=None,
                   actions=[{"action_type": "draw_card", "amount": 1}])
        state.effect_definitions[raw["effect_id"]] = EffectDefinition.model_validate(raw)
        state.cards["opponent-member"].card.effect_ids = [raw["effect_id"]]
    return state


def _event(result):
    return next(e for e in result.events if e.event_type == "opponent_direct_success_disable_probe")


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("direct", [False, True])
def test_probe_records_only_known_direct_effects_and_unknown_coverage_sql(tmp_path, owner, direct):
    state = _probe(owner, direct=direct); repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _resolve(current, PROBE, "opponent-member"))
    event = _event(result)
    assert event.data["known_direct_newly_disabled"] == int(direct)
    assert event.data["coverage_complete"] is False
    opponent = "player_2" if owner == "player_1" else "player_1"
    assert _source_trigger_disabled(result.state, opponent, "opponent-member", "live_succeeded", effect_id="AUDIT-OPPONENT:1") is direct
    assert not _source_trigger_disabled(result.state, opponent, "opponent-member", "live_succeeded", effect_id="OTHER")
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_duplicate_probe_has_no_new_known_effect_sql(tmp_path, owner):
    state = _probe(owner, duplicate=True); repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    first = repo.apply(state.match_id, _resolve(current, PROBE, "opponent-member"))
    second = repo.apply(state.match_id, _resolve(first.state, PROBE + "-SECOND", "opponent-member"))
    assert _event(first).data["known_direct_newly_disabled"] == 1
    assert _event(second).data["known_direct_newly_disabled"] == 0
    assert _event(second).data["coverage_complete"] is False
    _replay(repo, second.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_existing_source_only_flag_does_not_count_as_new_sql(tmp_path, owner):
    state = _probe(owner); opponent = "player_2" if owner == "player_1" else "player_1"
    state.players[opponent].manual_modifiers.append(ManualModifier(modifier_id="AUDIT-OLD-FLAG",
        modifier_type="flag", duration="live", created_turn=state.turn_number,
        flag="disabled_live_success_effects", target_card_instance_id="opponent-member",
        value={"trigger": "live_succeeded"}))
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _resolve(current, PROBE, "opponent-member"))
    assert _event(result).data["known_direct_newly_disabled"] == 0
    assert _event(result).data["coverage_complete"] is False
    assert len([m for m in result.state.players[opponent].manual_modifiers if m.flag == "disabled_live_success_effects"]) == 1
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_live_success_really_suppresses_known_effect_and_expires_sql(tmp_path, owner):
    state = _probe(owner); opponent = "player_2" if owner == "player_1" else "player_1"
    live = state.cards["live-1"].model_copy(deep=True)
    live.instance_id, live.owner_id = "opponent-live", opponent
    live.card.required_hearts = {}; live.card.effect_ids = []
    state.cards[live.instance_id] = live; state.players[opponent].live_area = [live.instance_id]
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    current = repo.apply(state.match_id, _resolve(current, PROBE, "opponent-member")).state
    observed = []
    for _ in range(5):
        if current.phase == "turn_complete": break
        result = repo.apply(state.match_id, _advance(current))
        observed.extend(result.events); current = result.state
    assert current.phase == "turn_complete" and opponent in current.live_success_player_ids
    assert any(e.event_type == "effect_trigger_disabled" and e.data.get("effect_id") == "AUDIT-OPPONENT:1" for e in observed)
    assert not any(e.event_type == "effect_triggered" and e.data.get("effect_id") == "AUDIT-OPPONENT:1" for e in observed)
    assert not _source_trigger_disabled(current, opponent, "opponent-member", "live_succeeded", effect_id="AUDIT-OPPONENT:1")
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_unknown_effect_reference_does_not_become_complete_zero_sql(tmp_path, owner):
    state = _probe(owner, direct=False)
    state.cards["opponent-member"].card.effect_ids = ["UNKNOWN:1"]
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _resolve(current, PROBE, "opponent-member"))
    assert _event(result).data["known_direct_newly_disabled"] == 0
    assert _event(result).data["coverage_complete"] is False
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_empty_opponent_stage_does_not_invent_target_sql(tmp_path, owner):
    state = _probe(owner, target=False); opponent = "player_2" if owner == "player_1" else "player_1"
    player = state.players[opponent]
    player.hand += [i for i in player.member_area.values() if i]
    player.member_area = {"left": None, "center": None, "right": None}
    repo = _repo(state, tmp_path)
    result = repo.apply(state.match_id, _advance(state))
    assert not any(i.effect_id == PROBE for i in result.state.pending_effects)
    assert any(e.event_type == "effect_not_activatable" and e.data.get("reason") == "choice_candidates_unavailable" for e in result.events)
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("ids", [["source-live"], ["secret"], ["missing"],
    ["opponent-member", "opponent-member"], ["opponent-member", "source-live"]])
def test_invalid_target_selection_is_atomic_sql(tmp_path, owner, ids):
    state = _probe(owner); repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    request = _resolve(current, PROBE, "opponent-member")
    request.payload["selected_card_instance_ids"] = ids
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError): repo.apply(state.match_id, request)
    assert match_state_hash(repo.get_state(state.match_id)) == before
    _replay(repo, current)


@pytest.mark.parametrize("field,value", [("opponent_direct_disable_source_v1", {}),
    ("selected_branch", "forged"), ("energy_instance_ids", ["fake"]), ("accepted", 1)])
def test_client_cannot_submit_source_proof_or_extra_parameters(field, value):
    initial = _probe("player_1")
    current = apply_action(initial, _advance(initial)).state
    request = _resolve(current, PROBE, "opponent-member"); request.payload[field] = value
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError): apply_action(current, request)
    assert match_state_hash(current) == before


@pytest.mark.parametrize("field,value", [("turn_number", True), ("turn_number", 999),
    ("stage_member", 1), ("instance_id", "another"), ("owner_id", "player_2")])
def test_forged_source_snapshot_is_atomically_rejected(field, value):
    initial = _probe("player_1")
    current = apply_action(initial, _advance(initial)).state
    inv = next(i for i in current.pending_effects if i.effect_id == PROBE)
    inv.trigger_data["opponent_direct_disable_source_v1"][field] = value
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        apply_action(current, _resolve(current, PROBE, "opponent-member"))
    assert match_state_hash(current) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_opponent_position_change_keeps_original_object_flag_sql(tmp_path, owner):
    state = _probe(owner, control=True); repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    current = repo.apply(state.match_id, _resolve(current, PROBE, "opponent-member")).state
    opponent = "player_2" if owner == "player_1" else "player_1"
    current = repo.apply(state.match_id, _manual(current, "CONTROL", [{"adjustment_type": "position_change",
        "target_player_id": opponent, "from_slot": "center", "to_slot": "right"}])).state
    assert _source_trigger_disabled(current, opponent, "opponent-member", "live_succeeded", effect_id="AUDIT-OPPONENT:1")
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("returned", [False, True])
@pytest.mark.parametrize("legacy_cleanup", [False, True])
def test_target_departure_never_inherits_probe_flag_sql(tmp_path, owner, returned, legacy_cleanup):
    state = _probe(owner, control=True)
    if legacy_cleanup: state.stage_departure_policy = None
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    current = repo.apply(state.match_id, _resolve(current, PROBE, "opponent-member")).state
    opponent = "player_2" if owner == "player_1" else "player_1"
    assert _source_trigger_disabled(current, opponent, "opponent-member", "live_succeeded", effect_id="AUDIT-OPPONENT:1")
    changes = [{"adjustment_type": "move_card", "target_player_id": opponent,
                "target_card_instance_id": "opponent-member", "to_zone": "hand"}]
    if returned:
        changes.append({"adjustment_type": "move_card", "target_player_id": opponent,
            "target_card_instance_id": "opponent-member", "to_zone": "member_center"})
    current = repo.apply(state.match_id, _manual(current, "CONTROL", changes)).state
    assert not _source_trigger_disabled(current, opponent, "opponent-member", "live_succeeded", effect_id="AUDIT-OPPONENT:1")
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("zone", ["hand", "main_deck", "return"])
def test_source_hidden_after_entry_does_not_change_bound_source_sql(tmp_path, owner, zone):
    state = _probe(owner, control=True); repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live",
                "to_zone": "hand" if zone == "return" else zone}]
    if zone == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_left"})
    current = repo.apply(state.match_id, _manual(current, "CONTROL", changes)).state
    before = match_state_hash(current)
    result = repo.apply(state.match_id, _resolve(current, PROBE, "opponent-member"))
    assert match_state_hash(current) == before
    assert _event(result).data["known_direct_newly_disabled"] == 1
    for viewer in ("player_1", "player_2"):
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        assert '"opponent_direct_disable_source_v1":' not in json.dumps(payload)
        if zone == "main_deck" or (zone == "hand" and viewer != owner):
            assert "source-live" not in payload["state"]["cards"]
            assert json.dumps("source-live") not in json.dumps(payload)
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("source_hidden", [False, True])
def test_four_ai_submit_probe_and_hidden_opponent_identity_invariance(owner, policy, source_hidden):
    initial = _probe(owner, control=source_hidden)
    state = apply_action(initial, _advance(initial)).state
    if source_hidden:
        state = apply_action(state, _manual(state, "CONTROL", [{"adjustment_type": "move_card",
            "target_card_instance_id": "source-live", "to_zone": "main_deck"}])).state
    before = match_state_hash(state)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    changed = state.model_copy(deep=True); opponent = "player_2" if owner == "player_1" else "player_1"
    for key in list(changed.players[opponent].hand + changed.players[opponent].main_deck):
        item = changed.cards.pop(key); replacement = "HIDDEN-" + key
        item.instance_id = replacement; item.card.card_code = item.card.name_ja = "HIDDEN"
        item.card.unit_keys, item.card.work_keys, item.card.blade = ["bibi"], ["hasunosora"], 99
        changed.cards[replacement] = item
        changed.players[opponent].hand = [replacement if i == key else i for i in changed.players[opponent].hand]
        changed.players[opponent].main_deck = [replacement if i == key else i for i in changed.players[opponent].main_deck]
    if source_hidden:
        item = changed.cards.pop("source-live"); item.instance_id = "hidden-source"
        item.card.card_code = item.card.name_ja = "HIDDEN SOURCE"
        item.card.unit_keys, item.card.work_keys, item.card.blade = ["bibi"], ["hasunosora"], 99
        changed.cards[item.instance_id] = item
        changed.players[owner].main_deck = [item.instance_id if i == "source-live" else i for i in changed.players[owner].main_deck]
        for inv in changed.pending_effects:
            if inv.source_card_instance_id == "source-live":
                inv.source_card_instance_id = item.instance_id
                inv.trigger_data["opponent_direct_disable_source_v1"]["instance_id"] = item.instance_id
    changed_before = match_state_hash(changed)
    other = controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner})
    assert isinstance(other, SimpleAIDecision) and other.action == decision.action
    assert match_state_hash(state) == before and match_state_hash(changed) == changed_before
    apply_action(state, decision.action); apply_action(changed, other.action)
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    for builder in (build_api_play_context, build_agent_context):
        assert '"opponent_direct_disable_source_v1":' not in json.dumps(builder(state, generate_legal_actions(state)))
