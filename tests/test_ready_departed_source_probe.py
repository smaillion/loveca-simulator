import hashlib
import json
import pytest

from test_printemps_producer_coverage import _state as _base_state, _play_for
from test_printemps_ready_history_boundary import _repo, _replay, _manual
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import apply_action, generate_legal_actions, IllegalActionError, StaleRevisionError
from loveca.simulation.models import ActionRequest, CardDefinition
from loveca.simulation.online import match_state_hash
from loveca.simulation.ready_history import current_effect_readied_members, prepare_ready_source, record_member_ready
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.webapp import _match_state_payload
from pydantic import ValidationError

PROBE = "UNREGISTERED-DEPARTED-READY:1"
OPERATION = "ready_member_from_departed_source_provenance_v1"
KEY = "ready_departed_source_v1"
LABEL = "AUDIT unregistered Stage-to-waiting optional Member ready"


def _state(owner="player_1", *, control=False, legacy=False):
    state = _base_state(owner=owner)
    raw = state.effect_definitions["PL!-pb1-012:1"].model_dump(mode="json")
    raw.update(effect_id=PROBE, card_code="UNREGISTERED-DEPARTED-READY", text_revision_id=1,
        raw_text_hash=hashlib.sha256(LABEL.encode()).hexdigest(), label_ja=LABEL,
        effect_type="triggered", timing="auto_triggered_event", trigger="member_left_stage_to_waiting_room",
        frequency_limit="none", is_optional=True, condition={}, cost=[], cost_choice=None, follow_up_choice=None, duration=None,
        actions=[{"action_type": "ready_member" if legacy else OPERATION, "target": "selected"}],
        choice={"choice_type": "member_from_stage", "zone": "stage", "card_type": "member", "target_player": "self",
                "orientation": "wait", "minimum": 0, "maximum": 1})
    state.effect_definitions[PROBE] = EffectDefinition.model_validate(raw)
    state.cards["good-target"].card = CardDefinition(card_code="UNREGISTERED-DEPARTED-READY", card_id="AUDIT-DEPARTED",
        name_ja="AUDIT departed source", card_type="member", cost=4, blade=1, unit_keys=["printemps"], work_keys=["love_live"],
        effect_ids=[PROBE], raw_effect_text_ja=LABEL, raw_text_hash=raw["raw_text_hash"], text_revision_id=1)
    state.cards["source-live"].card.effect_ids = []
    if control:
        manual = state.effect_definitions["PL!-pb1-012:1"].model_dump(mode="json")
        manual.update(effect_id="CONTROL", execution_mode="manual_resolution", simulation_support="manual_resolution",
            actions=[{"action_type": "manual_resolution"}], choice=None, is_optional=False)
        state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(manual)
        state.cards["source-live"].card.effect_ids = ["CONTROL"]
    return state


def _play(state, baton=True):
    action = _play_for(state)
    action.payload.update(slot="left", use_baton_touch=baton,
        energy_instance_ids=[] if baton else state.players[state.active_player_id].energy_area)
    return action


def _resolve(state, ids=None, accepted=True):
    inv = next(i for i in state.pending_effects if i.effect_id == PROBE)
    return ActionRequest(action_type="resolve_effect", player_id=inv.player_id, expected_revision=state.revision,
        payload={"invocation_id": inv.invocation_id, "accepted": accepted,
                 "selected_card_instance_ids": ["wrong-target"] if ids is None else ids})


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("baton", [False, True])
@pytest.mark.parametrize("choice", ["one", "zero", "decline"])
@pytest.mark.parametrize("orientation", ["active", "wait"])
def test_native_baton_binds_source_before_it_enters_waiting_sql(tmp_path, owner, baton, choice, orientation):
    state = _state(owner)
    state.cards["good-target"].orientation = orientation
    repo = _repo(state, tmp_path)
    departed = repo.apply(state.match_id, _play(state, baton)).state
    assert "good-target" in departed.players[owner].waiting_room
    inv = next(i for i in departed.pending_effects if i.effect_id == PROBE)
    assert inv.trigger_data[KEY]["unit_keys"] == ["printemps"]
    result = repo.apply(state.match_id, _resolve(departed, None if choice == "one" else [], accepted=choice != "decline")).state
    assert result.cards["wrong-target"].orientation == ("active" if choice == "one" else "wait")
    assert len(result.member_ready_history.events) == int(choice == "one")
    if choice == "one":
        assert result.member_ready_history.events[0].source.departed is True
        assert result.member_ready_history.events[0].source.owner_id == owner
        assert current_effect_readied_members(result, owner, unit_key="printemps") == ["wrong-target"]
    _replay(repo, result)


def _departed(owner="player_1", control=False):
    state = _state(owner, control=control)
    return apply_action(state, _play(state)).state


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("movement", ["hand", "main_deck", "return", "waiting_room", "return_position"])
def test_native_source_after_trigger_moves_do_not_replace_last_information_sql(tmp_path, owner, movement):
    state = _state(owner, control=True)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play(state)).state
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "good-target",
        "to_zone": "hand" if movement == "return" else "member_center" if movement == "return_position" else movement}]
    if movement == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "good-target", "to_zone": "member_center"})
    elif movement == "return_position":
        changes.append({"adjustment_type": "position_change", "from_slot": "center", "to_slot": "left"})
    moved = repo.apply(state.match_id, _manual(current, "CONTROL", changes)).state
    result = repo.apply(state.match_id, _resolve(moved)).state
    event = result.member_ready_history.events[0]
    assert event.source.unit_keys == ["printemps"] and event.source.work_keys == ["love_live"] and event.source.departed
    assert current_effect_readied_members(result, owner, unit_key="printemps") == ["wrong-target"]
    _replay(repo, result)


def test_returned_source_card_is_not_its_old_source_information():
    state = _departed(control=True)
    state = apply_action(state, _manual(state, "CONTROL", [{"adjustment_type": "move_card",
        "target_card_instance_id": "good-target", "to_zone": "member_center"}])).state
    state.cards["good-target"].card.unit_keys = ["lily_white"]
    state.cards["good-target"].card.work_keys = ["hasunosora"]
    result = apply_action(state, _resolve(state)).state
    assert result.member_ready_history.events[0].source.unit_keys == ["printemps"]
    assert current_effect_readied_members(result, "player_1", unit_key="lily_white") == []
    assert result.players["player_1"].effect_ready_flags_this_turn == ["love_live:member"]


@pytest.mark.parametrize("legacy", [False, True])
def test_old_leave_snapshot_keeps_old_json_and_replay_sql(tmp_path, legacy):
    state = _state(legacy=legacy)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play(state)).state
    inv = next(i for i in current.pending_effects if i.effect_id == PROBE)
    assert (KEY in inv.trigger_data) is (not legacy)
    result = repo.apply(state.match_id, _resolve(current)).state
    assert ("member_ready_history" in result.model_dump(mode="json")) is (not legacy)
    _replay(repo, result)


def test_old_v1_does_not_guess_an_initially_departed_source():
    state = _state(legacy=True)
    raw = state.effect_definitions[PROBE].model_dump(mode="json")
    raw["actions"][0]["action_type"] = "ready_member_with_provenance_v1"
    state.effect_definitions[PROBE] = EffectDefinition.model_validate(raw)
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError, match="original Stage or Live source"):
        apply_action(state, _play(state))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_manual_stage_departure_uses_pre_move_capture_sql(tmp_path, owner):
    state = _state(owner, control=True)
    action = _play(state, baton=False); action.payload["slot"] = "center"
    repo = _repo(state, tmp_path)
    entered = repo.apply(state.match_id, action).state
    assert not any(i.effect_id == PROBE for i in entered.pending_effects)
    left = repo.apply(state.match_id, _manual(entered, "CONTROL", [{"adjustment_type": "move_card",
        "target_card_instance_id": "good-target", "to_zone": "waiting_room"}])).state
    result = repo.apply(state.match_id, _resolve(left)).state
    assert result.member_ready_history.events[0].source.unit_keys == ["printemps"]
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_other_ability_source_to_waiting_cost_triggers_new_probe_sql(tmp_path, owner):
    state = _state(owner)
    raw = state.effect_definitions[PROBE].model_dump(mode="json")
    raw.update(effect_id="AUDIT-LEAVE-COST", effect_type="activated", timing="activated_main", trigger="player_activation",
        is_optional=False, choice=None, actions=[{"action_type": "draw_card", "amount": 0}],
        cost=[{"action_type": "source_to_waiting_room", "target": "source"}])
    state.effect_definitions["AUDIT-LEAVE-COST"] = EffectDefinition.model_validate(raw)
    state.cards["good-target"].card.effect_ids.append("AUDIT-LEAVE-COST")
    repo = _repo(state, tmp_path)
    departed = repo.apply(state.match_id, ActionRequest(action_type="activate_effect", player_id=owner, expected_revision=0,
        payload={"effect_id": "AUDIT-LEAVE-COST", "source_card_instance_id": "good-target", "energy_instance_ids": []})).state
    result = repo.apply(state.match_id, _resolve(departed)).state
    assert result.member_ready_history.events[0].source.effect_id == PROBE
    _replay(repo, result)


@pytest.mark.parametrize("movement", ["hand", "return", "position", "wait"])
def test_original_readied_target_does_not_survive_departure_or_lose_fact_on_wait_sql(tmp_path, movement):
    state = _state(control=True)
    if movement == "wait":
        raw = state.effect_definitions["CONTROL"].model_dump(mode="json")
        raw.update(execution_mode="prompt_then_resolve", simulation_support="test_validated_executable",
            choice={"choice_type": "member_from_stage", "zone": "stage", "card_type": "member", "minimum": 1, "maximum": 1},
            actions=[{"action_type": "apply_wait_member", "target": "selected"}])
        state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play(state)).state
    current = repo.apply(state.match_id, _resolve(current)).state
    if movement == "position":
        changes = [{"adjustment_type": "position_change", "from_slot": "right", "to_slot": "center"}]
    elif movement == "wait":
        changes = []
    else:
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": "wrong-target", "to_zone": "hand"}]
        if movement == "return": changes.append({"adjustment_type": "move_card", "target_card_instance_id": "wrong-target", "to_zone": "member_right"})
    if movement == "wait":
        inv = next(i for i in current.pending_effects if i.effect_id == "CONTROL")
        action = ActionRequest(action_type="resolve_effect", player_id=inv.player_id, expected_revision=current.revision,
            payload={"invocation_id": inv.invocation_id, "selected_card_instance_ids": ["wrong-target"]})
    else:
        action = _manual(current, "CONTROL", changes)
    final = repo.apply(state.match_id, action).state
    assert current_effect_readied_members(final, "player_1", unit_key="printemps") == (["wrong-target"] if movement in {"position", "wait"} else [])
    _replay(repo, final)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_returned_source_can_only_gain_a_new_target_object_token_sql(tmp_path, owner):
    from loveca.simulation.ready_history import MemberReadyHistoryV1
    state = _state(owner, control=True)
    state.member_ready_history = MemberReadyHistoryV1(turn_number=state.turn_number, next_object_id=1,
        object_ids={"good-target": "member-ready-v1/1"})
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play(state)).state
    assert "good-target" not in current.member_ready_history.object_ids
    returned = repo.apply(state.match_id, _manual(current, "CONTROL", [{"adjustment_type": "move_card",
        "target_card_instance_id": "good-target", "to_zone": "member_center"}])).state
    final = repo.apply(state.match_id, _resolve(returned, ["good-target"])).state
    assert final.member_ready_history.object_ids["good-target"] != "member-ready-v1/1"
    assert final.member_ready_history.events[0].source.departed is True
    assert current_effect_readied_members(final, owner, unit_key="printemps") == ["good-target"]
    _replay(repo, final)


def test_wrong_player_stale_revision_and_duplicate_submission_are_atomic():
    state = _departed()
    for bad in ["player", "revision"]:
        action = _resolve(state)
        if bad == "player": action.player_id = "player_2"
        else: action.expected_revision = 0
        before = match_state_hash(state)
        with pytest.raises(StaleRevisionError if bad == "revision" else IllegalActionError): apply_action(state, action)
        assert match_state_hash(state) == before
    action = _resolve(state); final = apply_action(state, action).state
    action.expected_revision = final.revision
    before = match_state_hash(final)
    with pytest.raises(IllegalActionError): apply_action(final, action)
    assert match_state_hash(final) == before


@pytest.mark.parametrize("mutation", ["cost", "cost_choice", "followup", "wrong_trigger", "wrong_timing", "mandatory", "condition", "source_target", "choice_count", "manual", "amount", "branch"])
def test_only_fixed_optional_departure_snapshot_is_supported(mutation):
    raw = _state().effect_definitions[PROBE].model_dump(mode="json")
    if mutation == "cost": raw["cost"] = [{"action_type": "pay_energy", "amount": 1}]
    elif mutation == "cost_choice": raw["cost_choice"] = raw["choice"]
    elif mutation == "followup": raw["follow_up_choice"] = raw["choice"]
    elif mutation == "wrong_trigger": raw["trigger"] = "member_played"
    elif mutation == "wrong_timing": raw["timing"] = "live_start"
    elif mutation == "mandatory": raw["is_optional"] = False
    elif mutation == "condition": raw["condition"] = {"source_is_center": True}
    elif mutation == "source_target": raw["actions"][0]["target"] = "source"
    elif mutation == "choice_count": raw["choice"]["maximum"] = 2
    elif mutation == "manual": raw["simulation_support"] = "manual_resolution"
    elif mutation == "amount": raw["actions"][0]["amount"] = 1
    else: raw["actions"][0]["branch"] = "fake"
    with pytest.raises(ValidationError): EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_effect_occupied_deployment_captures_outgoing_source_before_cleanup_sql(tmp_path, owner):
    from test_occupied_effect_deployment import _state as _occupied, _request
    from test_mirakura_front_position_boundary import _swap_roles
    state = _occupied()
    template = _state()
    state.effect_definitions[PROBE] = template.effect_definitions[PROBE]
    state.cards["old"].card = template.cards["good-target"].card.model_copy(deep=True)
    state.cards["left-old"].orientation = "wait"
    if owner == "player_2": state = _swap_roles(state)
    action = _request(state); action.player_id = owner
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, action).state
    inv = next(i for i in current.pending_effects if i.effect_id == PROBE)
    assert inv.trigger_data[KEY]["from_slot"] == "right"
    result = repo.apply(state.match_id, _resolve(current, ["left-old"])).state
    assert result.member_ready_history.events[0].source.instance_id == "old"
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_attached_source_entering_waiting_is_not_a_top_member_departure_sql(tmp_path, owner):
    state = _state(owner)
    p = state.players[owner]
    p.member_area["left"] = None
    p.member_area_attachments["right"].append("good-target")
    action = _play(state); action.payload["slot"] = "right"
    repo = _repo(state, tmp_path)
    result = repo.apply(state.match_id, action).state
    assert "good-target" in result.players[owner].waiting_room
    assert not any(i.effect_id == PROBE for i in result.pending_effects)
    assert not result.member_ready_history.events
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("zone", ["hand", "main_deck"])
def test_leaving_to_other_zone_does_not_trigger_waiting_prototype_sql(tmp_path, owner, zone):
    state = _state(owner, control=True)
    action = _play(state, baton=False); action.payload["slot"] = "center"
    repo = _repo(state, tmp_path)
    entered = repo.apply(state.match_id, action).state
    final = repo.apply(state.match_id, _manual(entered, "CONTROL", [{"adjustment_type": "move_card",
        "target_card_instance_id": "good-target", "to_zone": zone}])).state
    assert not any(i.effect_id == PROBE for i in final.pending_effects)
    assert not final.member_ready_history.events
    _replay(repo, final)


@pytest.mark.parametrize("field,value", [("turn_number", True), ("turn_number", 100), ("owner_id", "player_2"),
    ("instance_id", "wrong-target"), ("effect_id", "OTHER"), ("invocation_id", "OTHER"),
    ("from_slot", "center"), ("policy", "old"), ("unit_keys", ["bibi"]), ("work_keys", ["hasunosora"])])
def test_corrupt_departure_proof_rejected_atomically(field, value):
    state = _departed(); state.pending_effects[0].trigger_data[KEY][field] = value
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError): apply_action(state, _resolve(state))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("key", [KEY, "ready_source_lki_v1"])
def test_missing_proof_rejected_by_resolver_and_recording_path(key):
    state = _departed(); inv = state.pending_effects[0]; inv.trigger_data.pop(key)
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError): apply_action(state, _resolve(state))
    with pytest.raises(ValueError): record_member_ready(state, inv, "wrong-target", "wait")
    assert match_state_hash(state) == before


def test_no_pre_move_capture_cannot_be_reconstructed_from_waiting_card():
    state = _departed(); inv = state.pending_effects[0]
    before = match_state_hash(state)
    with pytest.raises(ValueError): prepare_ready_source(state, inv)
    assert match_state_hash(state) == before


@pytest.mark.parametrize("payload", [{KEY: {}}, {"ready_source_lki_v1": {}}, {"energy_instance_ids": ["fake"]},
    {"selected_card_instance_ids": ["wrong-target", "wrong-target"]}, {"selected_card_instance_ids": ["good-target"]},
    {"selected_card_instance_ids": ["missing"]}, {"selected_color_slot": "heart01"}, {"accepted": 1}])
def test_client_context_and_bad_choices_rejected_atomically(payload):
    state = _departed(); before = match_state_hash(state)
    action = _resolve(state); action.payload.update(payload)
    with pytest.raises(IllegalActionError): apply_action(state, action)
    assert match_state_hash(state) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_real_departed_source_choices_hidden_invariance(owner, policy):
    state = _departed(owner, control=True)
    state = apply_action(state, _manual(state, "CONTROL", [{"adjustment_type": "move_card",
        "target_card_instance_id": "good-target", "to_zone": "main_deck"}])).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    a = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(a, SimpleAIDecision)
    changed = state.model_copy(deep=True)
    for p in changed.players.values():
        for key in list(p.main_deck + (p.hand if p.player_id != owner else [])):
            item = changed.cards.pop(key); replacement = "HIDDEN-" + key
            item.instance_id = replacement; item.card.name_ja = item.card.card_code = "HIDDEN"
            item.card.unit_keys = ["lily_white"]; item.card.work_keys = ["hasunosora"]; item.card.blade = 99
            changed.cards[replacement] = item
            p.main_deck = [replacement if i == key else i for i in p.main_deck]
            p.hand = [replacement if i == key else i for i in p.hand]
            for inv in changed.pending_effects:
                if inv.source_card_instance_id == key:
                    inv.source_card_instance_id = replacement
                    inv.trigger_data[KEY]["instance_id"] = replacement
                    inv.trigger_data["ready_source_lki_v1"]["instance_id"] = replacement
    changed_before = match_state_hash(changed)
    b = controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner})
    assert isinstance(b, SimpleAIDecision) and a.action == b.action
    assert match_state_hash(state) == before and match_state_hash(changed) == changed_before
    one, two = apply_action(state, a.action).state, apply_action(changed, b.action).state
    assert len(one.member_ready_history.events) == len(two.member_ready_history.events)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_complete_player_and_provider_views_exclude_departure_proof(owner):
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    initial = _state(owner, control=True)
    entered = apply_action(initial, _play(initial))
    moved = apply_action(entered.state, _manual(entered.state, "CONTROL", [{"adjustment_type": "move_card",
        "target_card_instance_id": "good-target", "to_zone": "main_deck"}]))
    state = moved.state
    before = match_state_hash(state); legal = generate_legal_actions(state)
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(state, events=[*entered.events, *moved.events], legal_actions=legal, player_id=viewer)
        assert KEY not in json.dumps(payload) and "ready_source_lki_v1" not in json.dumps(payload)
        assert "member_ready_history" not in payload["state"] and "good-target" not in payload["state"]["cards"]
        for p in state.players.values():
            assert not any(i in payload["state"]["cards"] for i in p.main_deck)
            if p.player_id != viewer: assert not any(i in payload["state"]["cards"] for i in p.hand)
    for builder in [build_api_play_context, build_agent_context]:
        text = json.dumps(builder(state, legal))
        assert KEY not in text and "ready_source_lki_v1" not in text and "member_ready_history" not in text
    assert match_state_hash(state) == before
