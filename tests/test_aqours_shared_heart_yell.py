from contextlib import closing
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pytest
from test_aqours_blade_six_score import _state as _live_state
from test_all_active_live_requirement_boundary import _exclusive

from loveca.db.bootstrap import connect_database
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, LivePerformanceResult, ManualModifier
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository

CODE = "PL!S-cl1-011"
EFFECT = CODE + ":1"
POLICY = "public_aqours_shared_heart_yell_one"
RULE_REFERENCE_IDS = ("2.9.1", "2.9.3", "4.1.4", "8.4.4", "8.4.5", "9.6.2.4.2", "9.6.3.1.3", "9.7.7", "9.9.1.5", "11.6.2")


@lru_cache
def _raw():
    candidate = next((c for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True) if c.effect_id == EFFECT), None)
    return candidate.to_registry_entry() if candidate else next(e.model_dump(mode="json") for e in load_effect_registry().effects if e.effect_id == EFFECT)


def _state(*, legacy=False):
    raw = deepcopy(_raw())
    if legacy:
        raw.update(choice=None, actions=[{"action_type": "manual_resolution"}], execution_mode="manual_resolution", simulation_support="manual_resolution", review_status="parsed_draft")
    effect = EffectDefinition.model_validate(raw)
    state = _live_state()
    state.effect_definitions = {EFFECT: effect}
    for instance in state.cards.values():
        instance.card.effect_ids = []
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        state.cards["source-live"].card = _load_definition(db, CODE, None, {EFFECT: effect}, {})
    p = state.players["player_1"]
    for key in ["stage-0", "stage-1", "stage-2", "yell-r", "yell-g", "yell-rg", "not-yell", "yell-wrong", "yell-live"]:
        state.cards[key] = state.cards["target"].model_copy(update={"instance_id": key, "face_up": True}, deep=True)
        card = state.cards[key].card
        card.card_code = card.name_ja = key
        card.work_keys = ["nijigasaki"] if key == "yell-wrong" else ["love_live_sunshine"]
        card.basic_hearts = {"heart02": 1, "heart04": 1} if key in {"stage-0", "stage-1", "stage-2", "yell-rg"} else {"heart04" if key == "yell-g" else "heart02": 1}
        card.blade_heart_color_slot = None
        card.special_blade_hearts = []
    state.cards["yell-live"].card.card_type = "live"
    p.member_area = {"left": "stage-0", "center": "stage-1", "right": "stage-2"}
    p.member_area_attachments = {"left": [], "center": [], "right": []}
    p.live_area = ["source-live"]
    p.main_deck = ["deck-member-1", "deck-live-1"]
    p.resolution_area = ["yell-r", "yell-g", "yell-rg", "yell-wrong", "yell-live", "not-yell"]
    original = list(p.resolution_area[:-1])
    p.live_result = LivePerformanceResult(requirements_satisfied=True, total_score=state.cards["source-live"].card.score or 0, revealed_instance_ids=original,
        remaining_yell_instance_ids=None if legacy else list(original))
    state.phase, state.active_player_id = "live_judgment", None
    _exclusive(state)
    return state


def _begin(state):
    return apply_action(state, ActionRequest(action_type="advance_phase", expected_revision=state.revision))


def _resolve(state, ids=None, **extra):
    inv = next(i for i in state.pending_effects if i.effect_id == EFFECT)
    return ActionRequest(action_type="resolve_effect", player_id=inv.player_id, expected_revision=state.revision,
        payload={"invocation_id": inv.invocation_id, "selected_card_instance_ids": ["yell-r"] if ids is None else ids, **extra})


def _options(state):
    return next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect").options["invocations"][0]


def test_native_live_success_recovery_from_shared_heart_yell():
    state = _begin(_state()).state
    assert _options(state)["selection_policy"] == POLICY
    assert set(_options(state)["candidate_card_instance_ids"]) == {"yell-r", "yell-g", "yell-rg"}
    result = apply_action(state, _resolve(state))
    assert "yell-r" in result.state.players["player_1"].hand
    assert not result.state.pending_effects


def _event(result):
    return next(e.data for e in result.events if e.event_type == "effect_aqours_shared_yell_recovered")


def _repo(state, tmp_path):
    repo = MatchRepository(tmp_path / "audit.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    return repo


def _start(repo, state):
    return repo.apply(state.match_id, ActionRequest(action_type="advance_phase", expected_revision=state.revision)).state


def _replay(repo, state):
    _exclusive(state)
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == state.model_dump(mode="json")


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("case", ["zero", "two", "three", "mixed_work", "attached", "wait", "union_only", "two_common", "no_candidate"])
def test_native_conditions_and_current_yell_sql(tmp_path, owner, case):
    from test_mirakura_front_position_boundary import _swap_roles
    state = _state()
    p = state.players["player_1"]
    if case in {"zero", "two", "attached"}:
        p.member_area["right"] = None
        if case == "zero":
            p.member_area = {k: None for k in p.member_area}
        if case == "attached":
            p.member_area_attachments["left"] = ["stage-2"]
    elif case == "mixed_work":
        state.cards["stage-2"].card.work_keys = ["nijigasaki"]
    elif case == "wait":
        state.cards["stage-2"].orientation = "wait"
    elif case == "union_only":
        for key, hearts in zip(["stage-0", "stage-1", "stage-2"], [{"heart02": 1}, {"heart04": 1}, {"heart06": 1}]):
            state.cards[key].card.basic_hearts = hearts
    elif case == "no_candidate":
        for key in p.resolution_area:
            state.cards[key].card.basic_hearts = {"heart06": 1}
    if owner == "player_2":
        state = _swap_roles(state)
    _exclusive(state)
    repo = _repo(state, tmp_path)
    begun = _start(repo, state)
    expected = case in {"three", "wait", "two_common"}
    options = _options(begun)
    assert options["card_selection_minimum"] == int(expected)
    ids = ["yell-g"] if expected else []
    final = repo.apply(state.match_id, _resolve(begun, ids))
    data = _event(final)
    assert data["condition_met"] is (expected or case == "no_candidate")
    assert data["recovered_count"] == int(expected)
    assert ("yell-g" in final.state.players[owner].hand) is expected
    _replay(repo, final.state)


@pytest.mark.parametrize("kind", ["stage_blade_only", "stage_all_blade", "target_blade_only", "target_all_blade", "target_live", "not_yell", "opponent", "temporary_add", "temporary_remove", "base_replace"])
def test_basic_heart_scope_and_effective_stage_values(kind):
    from loveca.simulation.models import SpecialBladeHeart
    state = _state()
    ids = ["yell-r"]
    expected = kind in {"temporary_add", "base_replace"}
    if kind.startswith("stage_"):
        state.cards["stage-2"].card.basic_hearts = {}
        state.cards["stage-2"].card.blade_heart_color_slot = "heart02"
        if kind == "stage_all_blade":
            state.cards["stage-2"].card.special_blade_hearts = [SpecialBladeHeart(effect_type="all_color", value=9, source_alt="ALL")]
    elif kind.startswith("target_"):
        state.cards["yell-r"].card.basic_hearts = {}
        state.cards["yell-r"].card.blade_heart_color_slot = "heart02"
        if kind == "target_all_blade":
            state.cards["yell-r"].card.special_blade_hearts = [SpecialBladeHeart(effect_type="all_color", value=9, source_alt="ALL")]
        if kind == "target_live":
            state.cards["yell-r"].card.card_type = "live"
            state.cards["yell-r"].card.required_hearts = {"heart02": 99}
    elif kind in {"not_yell", "opponent"}:
        ids = ["not-yell" if kind == "not_yell" else "opponent"]
    elif kind == "temporary_add":
        state.cards["stage-2"].card.basic_hearts = {}
        state.players["player_1"].manual_modifiers.append(ManualModifier(modifier_id="AUDIT", modifier_type="heart", duration="live",
            created_turn=state.turn_number, target_card_instance_id="stage-2", color_slot="heart02", amount=1))
    elif kind == "temporary_remove":
        state.cards["stage-2"].card.basic_hearts = {"heart02": 1}
        state.players["player_1"].manual_modifiers.append(ManualModifier(modifier_id="AUDIT", modifier_type="heart", duration="live",
            created_turn=state.turn_number, target_card_instance_id="stage-2", color_slot="heart02", amount=-1))
    else:
        state.cards["stage-2"].card.basic_hearts = {"heart06": 9}
        state.players["player_1"].manual_modifiers.append(ManualModifier(modifier_id="AUDIT", modifier_type="base_heart_replacement", duration="live",
            created_turn=state.turn_number, target_card_instance_id="stage-2", color_slot="heart02"))
    begun = _begin(state).state
    before = match_state_hash(begun)
    if expected:
        result = apply_action(begun, _resolve(begun, ids))
        assert _event(result)["recovered_count"] == 1
    else:
        with pytest.raises(IllegalActionError):
            apply_action(begun, _resolve(begun, ids))
        assert match_state_hash(begun) == before


@pytest.mark.parametrize("bad", [[], ["yell-r", "yell-g"], ["yell-r", "yell-r"], ["yell-live"], ["yell-wrong"], ["not-yell"], ["held"], ["missing"], [True]])
def test_illegal_public_card_selection_atomic(bad):
    state = _begin(_state()).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, bad))
    assert match_state_hash(state) == before


def _control(state):
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id="CONTROL", choice=None, actions=[{"action_type": "manual_resolution"}], execution_mode="manual_resolution", simulation_support="manual_resolution", review_status="parsed_draft")
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    state.cards["source-live"].card.effect_ids.append("CONTROL")
    return state


def _manual(state, changes, *, control=True):
    inv = next(i for i in state.pending_effects if i.effect_id == ("CONTROL" if control else EFFECT))
    payload = {"reason": "AUDIT CONTROL only", "adjustments": [{"target_player_id": inv.player_id, **c} for c in changes],
               "source_invocation_id": inv.invocation_id, "source_effect_id": inv.effect_id, "source_card_instance_id": inv.source_card_instance_id}
    return ActionRequest(action_type="manual_adjustment", player_id=inv.player_id, expected_revision=state.revision, payload=payload)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("move", ["hand", "deck", "return", "same_live"])
def test_native_control_source_moves_do_not_cancel_sql(tmp_path, owner, move):
    from test_mirakura_front_position_boundary import _swap_roles
    from loveca.webapp import _match_state_payload
    state = _control(_state())
    if owner == "player_2":
        state = _swap_roles(state)
    repo = _repo(state, tmp_path)
    begun = _start(repo, state)
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "main_deck" if move == "deck" else "live_area" if move == "same_live" else "hand"}]
    if move == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "live_area"})
    moved = repo.apply(state.match_id, _manual(begun, changes)).state
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(moved, events=[], legal_actions=generate_legal_actions(moved), player_id=viewer)
        if move == "deck" or (move == "hand" and viewer != owner):
            assert "source-live" not in payload["state"]["cards"]
    final = repo.apply(state.match_id, _resolve(moved))
    assert _event(final)["recovered_count"] == 1
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(final.state, events=final.events, legal_actions=final.legal_actions, player_id=viewer)
        if move == "deck" or (move == "hand" and viewer != owner):
            assert "source-live" not in payload["state"]["cards"]
        assert ("yell-r" in payload["state"]["cards"]) is (viewer == owner)
    _replay(repo, final.state)


@pytest.mark.parametrize("change", ["two_to_three", "three_to_two", "add_color", "remove_color"])
def test_condition_reads_state_after_other_waiting_effect_sql(tmp_path, change):
    state = _control(_state())
    if change == "two_to_three":
        state.players["player_1"].member_area["right"] = None
        state.players["player_1"].hand.append("stage-2")
    elif change == "add_color":
        state.cards["stage-2"].card.basic_hearts = {}
    elif change == "remove_color":
        state.cards["stage-2"].card.basic_hearts = {"heart02": 1}
    state.cards["held"].card.work_keys = ["love_live_sunshine"]
    state.cards["held"].card.basic_hearts = {"heart02": 1} if change == "add_color" else {}
    _exclusive(state)
    repo = _repo(state, tmp_path)
    begun = _start(repo, state)
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "stage-2", "to_zone": "member_right" if change == "two_to_three" else "hand"}]
    if change in {"add_color", "remove_color"}:
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "held", "to_zone": "member_right"})
    moved = repo.apply(state.match_id, _manual(begun, changes)).state
    positive = change in {"two_to_three", "add_color"}
    final = repo.apply(state.match_id, _resolve(moved, ["yell-r"] if positive else []))
    assert _event(final)["condition_met"] is positive
    assert _event(final)["recovered_count"] == int(positive)
    _replay(repo, final.state)


@pytest.mark.parametrize("timing", ["before", "pending"])
@pytest.mark.parametrize("move", ["out", "return", "same_area"])
def test_only_original_yell_objects_survive_public_moves_sql(tmp_path, timing, move):
    state = _control(_state())
    repo = _repo(state, tmp_path)
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "yell-r", "to_zone": "resolution_area" if move == "same_area" else "waiting_room"}]
    if move == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "yell-r", "to_zone": "resolution_area"})
    if timing == "before":
        current = repo.apply(state.match_id, ActionRequest(action_type="manual_adjustment", player_id="player_1", expected_revision=state.revision,
            payload={"reason": "AUDIT before success checkpoint", "adjustments": [{"target_player_id": "player_1", **c} for c in changes]})).state
        begun = _start(repo, current)
        moved = repo.apply(state.match_id, _manual(begun, [{"adjustment_type": "set_flag", "flag": "AUDIT-before", "duration": "turn"}])).state
    else:
        begun = _start(repo, state)
        moved = repo.apply(state.match_id, _manual(begun, changes)).state
    assert ("yell-r" in _options(moved)["candidate_card_instance_ids"]) is (move == "same_area")
    final = repo.apply(state.match_id, _resolve(moved, ["yell-r" if move == "same_area" else "yell-g"]))
    _replay(repo, final.state)


@pytest.mark.parametrize("legacy", [False, True])
def test_native_performance_yell_tracking_and_sql_snapshot(legacy, tmp_path):
    state = _state(legacy=legacy)
    p = state.players["player_1"]
    p.live_result = LivePerformanceResult()
    p.resolution_area = []
    p.main_deck = ["yell-r", "yell-g", "yell-rg", "deck-member-1", "deck-live-1"]
    state.cards["source-live"].card.required_hearts = {}
    for key in p.member_area.values():
        state.cards[key].card.blade = 1
    state.phase, state.active_player_id = "performance_first", "player_1"
    _exclusive(state)
    repo = _repo(state, tmp_path)
    current = state
    for _ in range(12):
        if any(i.effect_id == EFFECT for i in current.pending_effects):
            break
        current = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id=current.active_player_id, expected_revision=current.revision)).state
    assert any(i.effect_id == EFFECT for i in current.pending_effects)
    result = current.players["player_1"].live_result
    assert len(result.revealed_instance_ids) == 3
    assert result.remaining_yell_instance_ids == (None if legacy else result.revealed_instance_ids)
    if legacy:
        with pytest.raises(IllegalActionError, match="manual_resolution"):
            apply_action(current, _resolve(current))
        final = repo.apply(state.match_id, _manual(current, [{"adjustment_type": "set_flag", "flag": "AUDIT-legacy", "duration": "turn"}], control=False))
        assert not any(e.event_type == "effect_aqours_shared_yell_recovered" for e in final.events)
    else:
        final = repo.apply(state.match_id, _resolve(current))
        assert _event(final)["recovered_count"] == 1
    _replay(repo, final.state)


def test_missing_original_snapshot_rejected_without_mutating():
    state = _state()
    state.players["player_1"].live_result.remaining_yell_instance_ids = None
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError, match="snapshot is missing"):
        _begin(state)
    assert match_state_hash(state) == before


@pytest.mark.parametrize("orientation", ["active", "wait"])
def test_shared_colors_include_current_static_heart(orientation):
    state = _state()
    state.cards["stage-2"].card.basic_hearts = {"heart06": 1}
    state.cards["stage-2"].orientation = orientation
    raw = deepcopy(_raw())
    raw.update(effect_id="AUDIT-static", choice=None, actions=[{"action_type": "gain_heart", "amount": 1, "color_slot": "heart02", "target": "self"}],
        effect_type="static", timing="static_always", trigger="static_always", execution_mode="auto_resolve", frequency_limit="none", duration="game")
    state.effect_definitions["AUDIT-static"] = EffectDefinition.model_validate(raw)
    state.cards["stage-2"].card.effect_ids = ["AUDIT-static"]
    state = _begin(state).state
    result = apply_action(state, _resolve(state))
    assert _event(result)["shared_heart_color_slots"] == ["heart02"]


def test_stale_and_repeat_submission_are_atomic():
    from loveca.simulation.engine import StaleRevisionError
    state = _begin(_state()).state
    old = _resolve(state)
    final = apply_action(state, old).state
    before = match_state_hash(final)
    with pytest.raises(StaleRevisionError):
        apply_action(final, old)
    old.expected_revision = final.revision
    with pytest.raises(IllegalActionError):
        apply_action(final, old)
    assert match_state_hash(final) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("positive", [False, True])
def test_four_ai_actual_native_actions_private_invariance_no_mutation(owner, policy, positive):
    from test_mirakura_front_position_boundary import _swap_roles
    from loveca.simulation.ai import SimpleAIController, SimpleAIPolicy, SimpleAIDecision
    state = _state()
    if not positive:
        state.cards["stage-2"].card.basic_hearts = {"heart06": 1}
    if owner == "player_2":
        state = _swap_roles(state)
    state = _begin(state).state
    changed = state.model_copy(deep=True)
    for key in ["deck-member-1", "deck-live-1", "held", "secret"]:
        instance = changed.cards.pop(key)
        replacement = "HIDDEN-" + key
        instance.instance_id = replacement
        instance.card.card_code = instance.card.name_ja = "HIDDEN-IDENTITY"
        instance.card.blade = 99
        changed.cards[replacement] = instance
        for p in changed.players.values():
            for zone in ["main_deck", "hand"]:
                setattr(p, zone, [replacement if item == key else item for item in getattr(p, zone)])
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner}).action == decision.action
    assert match_state_hash(state) == before
    final = apply_action(state, decision.action)
    assert _event(final)["recovered_count"] == int(positive)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_full_projection_public_history_not_current_hand_permission(owner):
    from test_mirakura_front_position_boundary import _swap_roles
    from loveca.webapp import _match_state_payload
    state = _state()
    if owner == "player_2":
        state = _swap_roles(state)
    state = _begin(state).state
    result = apply_action(state, _resolve(state))
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        assert ("yell-r" in payload["state"]["cards"]) is (viewer == owner)
        event = next(e for e in payload["events"] if e["event_type"] == "effect_aqours_shared_yell_recovered")
        assert event["data"]["revealed_cards"][0]["instance_id"] == "yell-r"
        assert all(key not in payload["state"]["cards"] for key in ["deck-member-1", "deck-live-1"])


@pytest.mark.parametrize("extra", [{"selected_color_slot": "heart02"}, {"selected_branch": "x"}, {"energy_instance_ids": ["energy-1"]}, {"target_player_id": "player_2"}])
def test_no_extra_mode_color_or_cost_and_wrong_player_atomic(extra):
    state = _begin(_state()).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, **extra))
    wrong = _resolve(state)
    wrong.player_id = "player_2"
    with pytest.raises(IllegalActionError):
        apply_action(state, wrong)
    assert match_state_hash(state) == before


@pytest.mark.parametrize("field,value", [("card_code", "PL!S-cl1-012"), ("text_revision_id", 971), ("raw_text_hash", "0" * 64), ("raw_effect_text_ja", "【ライブ成功時】カードを1枚引く。")])
def test_generator_exact_full_identity(field, value):
    from loveca.simulation.effect_candidates import _effect_text_rows, _live_success_aqours_shared_heart_yell
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        row = dict(next(r for r in _effect_text_rows(db) if r["card_code"] == CODE))
    assert _live_success_aqours_shared_heart_yell(row) is not None
    row[field] = value
    assert _live_success_aqours_shared_heart_yell(row) is None


@pytest.mark.parametrize("change", [{"minimum": 0}, {"maximum": 2}, {"requires_order": True}, {"work_key": "nijigasaki"}, {"zone": "waiting_room"}, {"is_optional": True}, {"duration": "live"}, {"actions": [{"action_type": "move_selected_to_deck_bottom"}]}])
def test_snapshot_is_fixed_and_does_not_widen_old_yell_policy(change):
    from pydantic import ValidationError
    raw = deepcopy(_raw())
    (raw if set(change).intersection({"is_optional", "duration", "actions"}) else raw["choice"]).update(change)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)
