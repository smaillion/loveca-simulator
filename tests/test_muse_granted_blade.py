import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_moved_source_ready import _manual
from test_nijigasaki_inspection import _candidate, _play, _resolve
from test_nijigasaki_inspection import _state as base_state

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effect_candidates import MUSE_GRANTED_BLADE_TEXT, _onplay_muse_granted_blade
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, _effective_member_blade, _public_overlap_source_gap, _run_current_yell, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, EffectInvocation, ManualModifier, MatchState, SpecialBladeHeart
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!-pb2-005"
EFFECT = CODE + ":1"
RULE_REFERENCE_IDS = ("2.7.1", "2.12.2", "4.1.4", "9.7.7", "9.9.1", "9.9.2", "9.9.3", "8.4.11")


def _state(*, legacy=False):
    state = base_state(CODE)
    raw = _candidate(CODE).to_registry_entry()
    if legacy:
        raw.update(execution_mode="manual_resolution", simulation_support="manual_resolution",
                   review_status="parsed_draft", actions=[{"action_type": "manual_resolution"}])
    state.effect_definitions[EFFECT] = EffectDefinition.model_validate(raw)
    state.players["player_1"].hand = ["source-live"]
    state.cards["good-live"].card.work_keys = ["love_live"]
    state.cards["good-live"].card.special_blade_hearts = [SpecialBladeHeart(effect_type="score", source_alt="スコア", value=1)]
    state.players["player_1"].main_deck.remove("good-live")
    state.players["player_1"].success_live_area = ["good-live"]
    return state


def _event(result):
    return next(e for e in result.events if e.event_type == "effect_muse_blade_aura_resolved")


def _pending():
    state = _state()
    state.effect_order_policy = "ap_nap_player_choice"
    state.players["player_1"].hand.remove("source-live")
    state.players["player_1"].member_area["center"] = "source-live"
    state.cards["source-live"].face_up = True
    state.pending_effects = [EffectInvocation(invocation_id="isolated-aura", effect_id=EFFECT,
        source_card_instance_id="source-live", player_id="player_1", trigger_event="member_played",
        trigger_data={"original_source_stage_object": True, "_condition_checked_at_trigger": True})]
    return state


def _control_state():
    state = _state()
    state.effect_order_policy = "ap_nap_player_choice"
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id="CONTROL", trigger="own_member_played", execution_mode="manual_resolution",
               simulation_support="manual_resolution", actions=[{"action_type": "manual_resolution"}])
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    observer = state.cards["good-member"].model_copy(deep=True)
    observer.instance_id, observer.card.effect_ids = "observer", ["CONTROL"]
    state.cards["observer"] = observer
    state.players["player_1"].member_area["left"] = "observer"
    return state


def test_native_onplay_grants_live_limited_dynamic_blade_not_manual():
    state = _state()
    result = apply_action(state, _play(state))
    assert not result.state.pending_effects
    assert _effective_member_blade(result.state, "player_1", "source-live") == 1
    assert _event(result).data["aura_delta"] == 1
    effect = result.state.effect_definitions[EFFECT]
    assert effect == next(e for e in load_effect_registry().effects if e.effect_id == EFFECT)
    assert effect.label_ja == MUSE_GRANTED_BLADE_TEXT
    assert (effect.text_revision_id, effect.raw_text_hash) == (
        978, "e972ec2ccacf722aa4a5f2ff2f55ece68dabbc676d988590c3d27079da601682")


@pytest.mark.parametrize("kind", ["score", "draw", "all_color", "unknown", None])
@pytest.mark.parametrize("card_type", ["member", "live"])
def test_score_blade_heart_icon_not_numeric_score_or_other_icon(kind, card_type):
    state = _state()
    card = state.cards["good-live"].card
    card.card_type, card.score = card_type, 99
    card.special_blade_hearts = [] if kind is None else [SpecialBladeHeart(effect_type=kind, source_alt="AUDIT", value=0)]
    result = apply_action(state, _play(state))
    assert _event(result).data["aura_delta"] == int(kind == "score")
    assert _effective_member_blade(result.state, "player_1", "source-live") == int(kind == "score")


@pytest.mark.parametrize("where", ["hand", "waiting_room", "main_deck", "live_area", "opponent", "wrong_work", "unit_only"])
def test_condition_only_own_success_area_muse_group(where):
    state = _state()
    player = state.players["player_1"]
    if where == "opponent":
        player.success_live_area = []
        state.cards["good-live"].owner_id = "player_2"
        state.players["player_2"].success_live_area = ["good-live"]
    elif where in {"wrong_work", "unit_only"}:
        state.cards["good-live"].card.work_keys = ["love_live_superstar"]
        state.cards["good-live"].card.unit_keys = ["love_live"] if where == "unit_only" else []
    else:
        player.success_live_area = []
        getattr(player, where).append("good-live")
    result = apply_action(state, _play(state))
    assert _event(result).data["aura_delta"] == 0


@pytest.mark.parametrize("work", ["love_live", "nijigasaki", "love_live_superstar"])
def test_new_member_gets_dynamic_bonus_only_for_current_muse_group(work):
    state = apply_action(_state(), _play(_state())).state
    player = state.players["player_1"]
    player.main_deck.remove("good-member")
    player.hand.append("good-member")
    card = state.cards["good-member"].card
    card.cost, card.blade, card.work_keys = 0, 2, [work]
    result = apply_action(state, ActionRequest(action_type="play_member", player_id="player_1",
        expected_revision=state.revision, payload={"card_instance_id": "good-member", "slot": "right", "energy_instance_ids": []}))
    assert _effective_member_blade(result.state, "player_1", "good-member") == 2 + int(work == "love_live")
    assert _effective_member_blade(result.state, "player_1", "source-live") == 1


def test_condition_is_checked_once_at_resolution_not_continuously_after_grant():
    state = apply_action(_state(), _play(_state())).state
    result = apply_action(state, _manual(state, [{"adjustment_type": "move_card",
        "target_card_instance_id": "good-live", "to_zone": "waiting_room"}]))
    assert _effective_member_blade(result.state, "player_1", "source-live") == 1


@pytest.mark.parametrize("present_at_trigger", [False, True])
def test_other_pending_ability_can_change_condition_before_resolution(tmp_path, present_at_trigger):
    state = _control_state()
    if not present_at_trigger:
        state.players["player_1"].success_live_area = []
        state.players["player_1"].waiting_room = ["good-live"]
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state)).state
    control = next(i for i in played.pending_effects if i.effect_id == "CONTROL")
    result = repo.apply(state.match_id, _manual(played, [{"adjustment_type": "move_card",
        "target_card_instance_id": "good-live", "to_zone": "waiting_room" if present_at_trigger else "success_live_area"}], control))
    final = result
    assert _event(final).data["aura_delta"] == int(not present_at_trigger)
    assert repo.replay(state.match_id)["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("movement", ["leave", "return", "position"])
def test_native_pending_source_object_interference_sql(tmp_path, movement):
    state = _control_state()
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state)).state
    control = next(i for i in played.pending_effects if i.effect_id == "CONTROL")
    adjustments = [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "right"}] if movement == "position" else [
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"}]
    if movement == "return":
        adjustments.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_right"})
    final = repo.apply(state.match_id, _manual(played, adjustments, control))
    assert _event(final).data["aura_delta"] == int(movement == "position")
    assert not final.state.pending_effects
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("policy", [None, "clear_departed_card_modifiers"])
@pytest.mark.parametrize("movement", ["leave", "return", "position"])
def test_granted_aura_follows_original_source_and_clears_even_old_match_policy(policy, movement):
    initial = _state()
    initial.stage_departure_policy = policy
    state = apply_action(initial, _play(initial)).state
    changes = [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "right"}] if movement == "position" else [
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"}]
    if movement == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_right"})
    result = apply_action(state, _manual(state, changes))
    assert bool(result.state.players["player_1"].manual_modifiers) is (movement == "position")
    assert _effective_member_blade(result.state, "player_1", "source-live") == int(movement == "position")


@pytest.mark.parametrize("active", [False, True])
def test_effective_blade_and_actual_yell_agree_without_counting_wait_member(active):
    state = apply_action(_state(), _play(_state())).state
    state.cards["source-live"].orientation = "active" if active else "wait"
    state.players["player_1"].success_live_area = []
    state.players["player_1"].live_area = ["good-live"]
    events = []
    _run_current_yell(state, events)
    event = next(e for e in events if e.event_type == "yell_completed")
    assert event.data["blade_count"] == int(active)
    assert _effective_member_blade(state, "player_1", "source-live") == 1


def test_live_end_expires_granted_ability():
    state = apply_action(_state(), _play(_state())).state
    state.phase = "live_judgment"
    result = apply_action(state, ActionRequest(action_type="advance_phase", player_id="player_1", expected_revision=state.revision))
    assert not result.state.players["player_1"].manual_modifiers


@pytest.mark.parametrize("legacy", [False, True])
def test_new_and_old_manual_sql_snapshots_remain_distinct(tmp_path, legacy):
    state = _state(legacy=legacy)
    restored = MatchState.model_validate_json(state.model_dump_json())
    assert match_state_hash(restored) == match_state_hash(state)
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(restored, card_database_path=Path("data/loveca.sqlite3"))
    result = repo.apply(state.match_id, _play(restored))
    if legacy:
        result = repo.apply(state.match_id, _manual(result.state, [{"adjustment_type": "set_flag", "flag": "audit-old", "duration": "turn"}], result.state.pending_effects[0]))
        assert _effective_member_blade(result.state, "player_1", "source-live") == 0
        assert result.state.effect_definitions[EFFECT].actions[0].source_object_policy is None
    else:
        assert _effective_member_blade(result.state, "player_1", "source-live") == 1
    assert repo.replay(state.match_id)["final_state"] == result.state.model_dump(mode="json")


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_pending_resolution_is_private_and_does_not_mutate_input(policy):
    state = _pending()
    ai = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    first = ai.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(first, SimpleAIDecision) and match_state_hash(state) == before
    changed = state.model_copy(deep=True)
    for key in ["opponent-secret", *state.players["player_1"].main_deck]:
        changed.cards[key].card.name_ja = changed.cards[key].card.card_code = "HIDDEN-CHANGED"
    assert ai.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}).action == first.action
    result = apply_action(state, first.action)
    assert _event(result).data["aura_delta"] == 1
    for viewer in ("player_1", "player_2"):
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        assert "AUDIT-tail" not in json.dumps(payload)
        if viewer == "player_1":
            assert "opponent-secret" not in payload["state"]["cards"]


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_actual_play_resolves_granted_aura(policy):
    state = _state()
    ai = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    decision = ai.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision) and decision.action.action_type == "play_member"
    assert _event(apply_action(state, decision.action)).data["aura_delta"] == 1


@pytest.mark.parametrize("change", [{"amount": 2}, {"target": "both"}, {"source_object_policy": None}, {"color_slot": "heart01"}])
def test_bounded_operation_rejects_widening(change):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw["actions"][0].update(change)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("change", [{"duration": "turn"}, {"is_optional": True}, {"trigger": "live_started"}, {"condition": {"source_zone": "stage"}}])
def test_bounded_definition_rejects_widening(change):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(change)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("field,value", [("raw_effect_text_ja", MUSE_GRANTED_BLADE_TEXT + "追加"), ("text_revision_id", 979), ("raw_text_hash", "0" * 64), ("card_code", "AUDIT")])
def test_generator_requires_exact_full_text_and_identity(field, value):
    state = _state()
    row = {"card_code": CODE, "text_revision_id": 978, "raw_text_hash": state.cards["source-live"].card.raw_text_hash,
           "raw_effect_text_ja": MUSE_GRANTED_BLADE_TEXT, field: value}
    assert _onplay_muse_granted_blade(row) is None


def test_granted_static_overlap_semantics_remain_explicitly_unavailable():
    state = apply_action(_state(), _play(_state())).state
    assert _public_overlap_source_gap(state, "player_1", "source-live", None) == "overlap_granted_static_ability_requires_review"


def test_native_strict_overlap_rejects_granted_static_source_before_payment():
    from test_disjoint_overlap_source import _options
    from test_overlap_source_binding import _state as overlap_state
    from test_occupied_effect_deployment import _request
    state = overlap_state(strict=True)
    player_id, slot = next((p, slot) for p, player in state.players.items()
                           for slot, item in player.member_area.items() if item is None)
    source = _state().cards["source-live"].model_copy(deep=True)
    source.instance_id, source.owner_id, source.face_up = "aura-public", player_id, True
    state.cards[source.instance_id] = source
    state.players[player_id].member_area[slot] = source.instance_id
    state.effect_definitions[EFFECT] = _state().effect_definitions[EFFECT]
    options = _options(state)
    assert options["deployment_unsupported_slots_by_candidate"]["target"]["right"] == "overlap_granted_static_ability_requires_review"
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _request(state))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("defect", ["missing_snapshot", "opponent", "decline"])
def test_invalid_resolution_is_atomic(defect):
    state = _pending()
    if defect == "missing_snapshot":
        state.pending_effects[0].trigger_data.pop("original_source_stage_object")
    action = _resolve(state, accepted=defect != "decline")
    if defect == "opponent":
        action.player_id = "player_2"
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, action)
    assert match_state_hash(state) == before


def test_multiple_original_sources_stack_and_one_departure_removes_only_one_aura():
    state = apply_action(_state(), _play(_state())).state
    player = state.players["player_1"]
    second = state.cards["source-live"].model_copy(update={"instance_id": "second-source"}, deep=True)
    state.cards[second.instance_id] = second
    player.hand = [second.instance_id]
    energies = []
    for i in range(5):
        key = f"second-energy-{i}"
        card = state.cards["energy-0"].model_copy(update={"instance_id": key, "orientation": "active"}, deep=True)
        state.cards[key] = card
        player.energy_area.append(key)
        energies.append(key)
    result = apply_action(state, ActionRequest(action_type="play_member", player_id="player_1",
        expected_revision=state.revision, payload={"card_instance_id": second.instance_id, "slot": "right", "energy_instance_ids": energies}))
    assert _effective_member_blade(result.state, "player_1", "source-live") == 2
    assert _effective_member_blade(result.state, "player_1", second.instance_id) == 2
    final = apply_action(result.state, _manual(result.state, [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"}]))
    assert _effective_member_blade(final.state, "player_1", second.instance_id) == 1


@pytest.mark.parametrize("target", ["opponent", "hand", "attachment", "returned"])
def test_only_current_own_top_stage_members_receive_dynamic_bonus(target):
    state = apply_action(_state(), _play(_state())).state
    player = state.players["player_1"]
    player.main_deck.remove("good-member")
    state.cards["good-member"].card.work_keys, state.cards["good-member"].card.blade = ["love_live"], 2
    owner = "player_1"
    if target == "opponent":
        owner = "player_2"
        state.cards["good-member"].owner_id = owner
        state.players[owner].member_area["right"] = "good-member"
    elif target == "hand":
        player.hand.append("good-member")
    elif target == "attachment":
        player.member_area_attachments["center"] = ["good-member"]
    else:
        player.member_area["right"] = "good-member"
        state = apply_action(state, _manual(state, [
            {"adjustment_type": "move_card", "target_card_instance_id": "good-member", "to_zone": "hand"},
            {"adjustment_type": "move_card", "target_card_instance_id": "good-member", "to_zone": "member_right"}])).state
    assert _effective_member_blade(state, owner, "good-member") == 2 + int(target == "returned")


def test_second_player_source_does_not_buff_the_first_players_muse_member():
    state = _state()
    swap = {"player_1": "player_2", "player_2": "player_1"}
    state.players = {swap[key]: player for key, player in state.players.items()}
    for key, player in state.players.items():
        player.player_id = key
    for card in state.cards.values():
        card.owner_id = swap[card.owner_id]
    state.active_player_id, state.phase = "player_2", "second_main"
    state.players["player_1"].hand.remove("opponent-secret")
    state.players["player_1"].member_area["center"] = "opponent-secret"
    state.cards["opponent-secret"].card.work_keys, state.cards["opponent-secret"].card.blade = ["love_live"], 2
    result = apply_action(state, ActionRequest(action_type="play_member", player_id="player_2",
        expected_revision=state.revision, payload={"card_instance_id": "source-live", "slot": "center",
        "energy_instance_ids": state.players["player_2"].energy_area}))
    assert _effective_member_blade(result.state, "player_2", "source-live") == 1
    assert _effective_member_blade(result.state, "player_1", "opponent-secret") == 2


@pytest.mark.parametrize("change", [{"target_card_instance_id": None}, {"amount": 2}, {"duration": "turn"}, {"value": True}])
def test_unversioned_or_malformed_flags_do_not_grant_an_aura(change):
    state = _pending()
    modifier = ManualModifier(modifier_id="audit", modifier_type="flag", flag="granted_muse_stage_blade",
        amount=1, duration="live", created_turn=state.turn_number, target_card_instance_id="source-live",
        value={"policy": "original_onplay_muse_blade_aura"})
    state.players["player_1"].manual_modifiers = [modifier.model_copy(update=change)]
    assert _effective_member_blade(state, "player_1", "source-live") == 0


@pytest.mark.parametrize("changed", [False, True])
def test_semantic_audit_accepts_only_exact_granted_aura_text(changed):
    from tools.ai_sandbox.rule_conformance import _semantic_operation_alignment
    assert _semantic_operation_alignment(MUSE_GRANTED_BLADE_TEXT + ("追加" if changed else ""),
        {"grant_muse_blade_aura_if_success_score_icon"}) is (not changed)
