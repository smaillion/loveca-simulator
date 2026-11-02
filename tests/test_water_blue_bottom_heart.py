from contextlib import closing
from copy import deepcopy
from pathlib import Path

import pytest
from test_aqours_blade_six_score import _state as _live_state
from test_all_active_live_requirement_boundary import _exclusive
from test_nijigasaki_inspection import _candidate

from loveca.db.bootstrap import connect_database
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, SpecialBladeHeart
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository

CODE = "PL!S-cl1-013"
EFFECT = CODE + ":1"
POLICY = "public_water_blue_bottom_heart"
RULE_REFERENCE_IDS = ("1.3.2.2", "1.3.5.1", "4.1.4", "4.1.5.1", "5.5.1", "5.5.1.2", "9.6.3.1.3", "9.7.7", "10.2.2.1")


def _state(*, legacy=False):
    raw = deepcopy(_candidate(CODE).to_registry_entry())
    if legacy:
        raw.update(choice=None, follow_up_choice=None, actions=[{"action_type": "manual_resolution"}], execution_mode="manual_resolution", simulation_support="manual_resolution", review_status="parsed_draft")
    effect = EffectDefinition.model_validate(raw)
    state = _live_state()
    state.effect_definitions = {EFFECT: effect}
    for instance in state.cards.values():
        instance.card.effect_ids = []
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        state.cards["source-live"].card = _load_definition(db, CODE, None, {EFFECT: effect}, {})
    p = state.players["player_1"]
    p.live_area = ["source-live"]
    p.main_deck = ["deck-member-1", "deck-live-1"]
    p.waiting_room = []
    for i in range(8):
        key = f"return-{i}"
        instance = state.cards["target"].model_copy(update={"instance_id": key, "face_up": True}, deep=True)
        instance.card.card_code = f"AUDIT-{i}"
        instance.card.name_ja = "同名" if i < 2 else key
        instance.card.blade_heart_color_slot = None
        instance.card.special_blade_hearts = []
        state.cards[key] = instance
        p.waiting_room.append(key)
    p.member_area = {"left": "target", "center": None, "right": "wrong-work"}
    state.phase, state.active_player_id = "performance_first", "player_1"
    state.stage_departure_policy = "clear_departed_card_modifiers"
    _exclusive(state)
    return state


def _begin(state):
    return apply_action(state, ActionRequest(action_type="advance_phase", player_id=state.active_player_id, expected_revision=state.revision))


def _resolve(state, ids=None, **extra):
    inv = next(i for i in state.pending_effects if i.effect_id == EFFECT)
    return ActionRequest(action_type="resolve_effect", player_id=inv.player_id, expected_revision=state.revision,
        payload={"invocation_id": inv.invocation_id, "selected_card_instance_ids": [] if ids is None else ids, **extra})


def test_native_live_start_returns_then_selects_original_stage_member():
    begun = _begin(_state()).state
    assert begun.effect_definitions[EFFECT].choice.selection_policy == POLICY
    returned = apply_action(begun, _resolve(begun, ["return-0", "return-1"])).state
    assert returned.pending_effects[0].resolution_stage == "after_cost"
    result = apply_action(returned, _resolve(returned, ["target"]))
    assert not result.state.pending_effects
    modifier = result.state.players["player_1"].manual_modifiers[-1]
    assert (modifier.target_card_instance_id, modifier.color_slot, modifier.amount) == ("target", "heart05", 2)


@pytest.mark.parametrize("field,value", [("card_code", "PL!S-cl1-014"), ("text_revision_id", 973),
    ("raw_text_hash", "0" * 64), ("raw_effect_text_ja", "【ライブ開始時】カードを1枚引く。")])
def test_generator_requires_complete_official_identity(field, value):
    from loveca.simulation.effect_candidates import _effect_text_rows, _live_start_water_blue_bottom_heart
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        row = dict(next(row for row in _effect_text_rows(db) if row["card_code"] == CODE))
    assert _live_start_water_blue_bottom_heart(row) is not None
    row[field] = value
    assert _live_start_water_blue_bottom_heart(row) is None


def _event(result, kind="effect_water_blue_heart_resolved"):
    return next(e.data for e in result.events if e.event_type == kind)


def _pending(**kwargs):
    return _begin(_state(**kwargs)).state


def _finish(state, ids, *, repo=None):
    result = repo.apply(state.match_id, _resolve(state, ids)) if repo else apply_action(state, _resolve(state, ids))
    if any(i.effect_id == EFFECT for i in result.state.pending_effects):
        result = repo.apply(state.match_id, _resolve(result.state, ["target"])) if repo else apply_action(result.state, _resolve(result.state, ["target"]))
    return result


@pytest.mark.parametrize("count", [0, 1, 2, 5, 6])
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_actual_return_count_prefix_and_selected_heart_sql(tmp_path, count, owner):
    from test_mirakura_front_position_boundary import _swap_roles
    from loveca.simulation.engine import _member_heart_count
    state = _state()
    if owner == "player_2":
        state = _swap_roles(state)
        state.phase, state.active_player_id = "performance_first", owner
    old_main = list(state.players[owner].main_deck)
    before = _member_heart_count(state, owner, "target", "heart05")
    repo = MatchRepository(tmp_path / "return.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    begun = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id=owner, expected_revision=state.revision)).state
    returned = repo.apply(state.match_id, _resolve(begun, [f"return-{i}" for i in range(count)]))
    assert _event(returned, "effect_water_blue_cards_returned")["shuffle_performed"] is True
    result = repo.apply(state.match_id, _resolve(returned.state, ["target"])) if count >= 2 else returned
    assert _event(result)["returned_count"] == count
    assert _event(result)["heart_amount"] == (count // 2) * 2
    assert result.state.players[owner].main_deck[:len(old_main)] == old_main
    assert set(result.state.players[owner].main_deck[len(old_main):]) == {f"return-{i}" for i in range(count)}
    assert _member_heart_count(result.state, owner, "target", "heart05") == before + (count // 2) * 2
    _exclusive(result.state)
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


@pytest.mark.parametrize("kind", ["colored", "all", "draw", "score", "unknown", "wrong_work", "live", "hand"])
def test_only_waiting_aqours_members_without_any_blade_heart(kind):
    state = _state()
    card = state.cards["return-0"].card
    if kind == "colored":
        card.blade_heart_color_slot = "heart05"
    elif kind in {"all", "draw", "score", "unknown"}:
        card.special_blade_hearts = [SpecialBladeHeart(effect_type="all_color" if kind == "all" else kind, value=1, source_alt=kind)]
    elif kind == "wrong_work":
        card.work_keys = ["nijigasaki"]
    elif kind == "live":
        card.card_type = "live"
    else:
        state.players["player_1"].waiting_room.remove("return-0")
        state.players["player_1"].hand.append("return-0")
    state = _begin(state).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, ["return-0"]))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("bad", [["return-0"] * 2, [f"return-{i}" for i in range(7)], ["secret"], ["target"], [123]])
def test_initial_illegal_selection_atomic(bad):
    state = _pending()
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, bad))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("bad", [[], ["wrong-work"], ["attached"], ["opponent"], ["target", "target"]])
def test_followup_illegal_target_atomic(bad):
    state = _pending()
    state = apply_action(state, _resolve(state, ["return-0", "return-1"])).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, bad))
    assert match_state_hash(state) == before


def test_shuffle_is_not_request_order_and_is_not_fixed_across_seeds():
    orders = set()
    for seed in range(10, 15):
        state = _state()
        state.seed = seed
        state = _begin(state).state
        ids = [f"return-{i}" for i in range(6)]
        first = apply_action(state, _resolve(state, ids)).state
        second = apply_action(state, _resolve(state, list(reversed(ids)))).state
        assert match_state_hash(first) == match_state_hash(second)
        orders.add(tuple(first.players["player_1"].main_deck[-6:]))
    assert len(orders) > 1


@pytest.mark.parametrize("waiting", [False, True])
def test_empty_deck_rule_refresh_precedes_public_selection_sql(tmp_path, waiting):
    state = _state()
    state.players["player_1"].main_deck = []
    if not waiting:
        state.players["player_1"].waiting_room = []
    repo = MatchRepository(tmp_path / "empty.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    begun = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id="player_1", expected_revision=state.revision)).state
    options = next(a for a in generate_legal_actions(begun) if a.action_type == "resolve_effect").options["invocations"][0]
    assert options["candidate_card_instance_ids"] == []
    result = repo.apply(state.match_id, _resolve(begun, []))
    assert _event(result)["returned_count"] == 0 and not result.state.pending_effects
    assert bool(result.state.players["player_1"].main_deck) is waiting
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


@pytest.mark.parametrize("stage", ["no_aqours", "wait", "multiple"])
def test_stage_targets_are_current_top_members_sql(tmp_path, stage):
    state = _state()
    if stage == "no_aqours":
        state.cards["target"].card.work_keys = ["nijigasaki"]
    elif stage == "wait":
        state.cards["target"].orientation = "wait"
    else:
        state.cards["wrong-work"].card.work_keys = ["love_live_sunshine"]
    repo = MatchRepository(tmp_path / "target.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    begun = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id="player_1", expected_revision=state.revision)).state
    returned = repo.apply(state.match_id, _resolve(begun, ["return-0", "return-1"]))
    if stage == "no_aqours":
        assert _event(returned)["heart_amount"] == 0 and not returned.state.pending_effects
    else:
        options = next(a for a in returned.legal_actions if a.action_type == "resolve_effect").options["invocations"][0]
        assert set(options["candidate_card_instance_ids"]) == ({"target", "wrong-work"} if stage == "multiple" else {"target"})
        final = repo.apply(state.match_id, _resolve(returned.state, ["wrong-work" if stage == "multiple" else "target"]))
        assert _event(final)["heart_amount"] == 2
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


def _manual(state, owner, changes, invocation=None):
    payload = {"reason": "AUDIT CONTROL only", "adjustments": [{"target_player_id": owner, **c} for c in changes]}
    if invocation:
        payload.update(source_invocation_id=invocation.invocation_id, source_effect_id=invocation.effect_id, source_card_instance_id=invocation.source_card_instance_id)
    return ActionRequest(action_type="manual_adjustment", player_id=owner, expected_revision=state.revision, payload=payload)


@pytest.mark.parametrize("move", ["hand", "deck", "return", "same_live"])
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_native_control_source_departure_before_selection_sql(tmp_path, owner, move):
    from test_mirakura_front_position_boundary import _swap_roles
    from loveca.webapp import _match_state_payload
    state = _state()
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id="CONTROL", choice=None, follow_up_choice=None, actions=[{"action_type": "manual_resolution"}], execution_mode="manual_resolution", simulation_support="manual_resolution", review_status="parsed_draft")
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    state.cards["source-live"].card.effect_ids.append("CONTROL")
    if owner == "player_2":
        state = _swap_roles(state)
        state.active_player_id = owner
    repo = MatchRepository(tmp_path / "source.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    begun = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id=owner, expected_revision=state.revision)).state
    ctrl = next(i for i in begun.pending_effects if i.effect_id == "CONTROL")
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "main_deck" if move == "deck" else "live_area" if move == "same_live" else "hand"}]
    if move == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "live_area"})
    moved = repo.apply(state.match_id, _manual(begun, owner, changes, ctrl)).state
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(moved, events=[], legal_actions=generate_legal_actions(moved), player_id=viewer)
        if move == "deck" or (move == "hand" and viewer != owner):
            assert "source-live" not in payload["state"]["cards"]
    final = _finish(moved, ["return-0", "return-1"], repo=repo)
    assert _event(final)["heart_amount"] == 2
    _exclusive(final.state)
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


@pytest.mark.parametrize("move", ["leave", "return", "position"])
@pytest.mark.parametrize("policy", [None, "clear_departed_card_modifiers"])
def test_selected_member_object_cleanup_sql(tmp_path, move, policy):
    state = _finish(_pending(), ["return-0", "return-1"]).state
    state.stage_departure_policy = policy
    repo = MatchRepository(tmp_path / "departure.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    changes = [{"adjustment_type": "position_change", "from_slot": "left", "to_slot": "center"}] if move == "position" else [{"adjustment_type": "move_card", "target_card_instance_id": "target", "to_zone": "hand"}]
    if move == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "target", "to_zone": "member_left"})
    result = repo.apply(state.match_id, _manual(state, "player_1", changes))
    assert bool(result.state.players["player_1"].manual_modifiers) is (move == "position")
    _exclusive(result.state)
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


def test_live_end_cleanup_through_real_ai_actions_sql(tmp_path):
    from loveca.simulation.ai import SimpleAIController, SimpleAIPolicy, SimpleAIDecision
    state = _finish(_pending(), ["return-0", "return-1"]).state
    repo = MatchRepository(tmp_path / "live-end.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    controller = SimpleAIController(SimpleAIPolicy(policy_version="simple_ai_v1_2", manual_effect_policy="block"))
    for _ in range(60):
        if state.phase in {"turn_complete", "complete"}:
            break
        decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1", "player_2"})
        assert isinstance(decision, SimpleAIDecision)
        state = repo.apply(state.match_id, decision.action).state
    assert state.phase in {"turn_complete", "complete"}
    assert not state.players["player_1"].manual_modifiers
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_shuffled_order_and_current_card_faces_hidden_with_public_history(owner):
    from test_mirakura_front_position_boundary import _swap_roles
    from loveca.webapp import _match_state_payload
    state = _pending()
    if owner == "player_2":
        state = _swap_roles(state)
    result = apply_action(state, _resolve(state, [f"return-{i}" for i in range(6)]))
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        assert all(f"return-{i}" not in payload["state"]["cards"] for i in range(6))
        assert payload["state"]["seed"] == 0
        history = payload["state"]["pending_effects"][0]["trigger_data"]["revealed_cards"]
        assert [c["instance_id"] for c in history] == [f"return-{i}" for i in range(6)]
        assert "secret" not in payload["state"]["cards"] if viewer == owner else True


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_actual_choices_hidden_invariance_no_mutation(owner, after, policy):
    from test_mirakura_front_position_boundary import _swap_roles
    from loveca.simulation.ai import SimpleAIController, SimpleAIPolicy, SimpleAIDecision
    state = _pending()
    if after:
        state = apply_action(state, _resolve(state, ["return-0", "return-1"])).state
    if owner == "player_2":
        state = _swap_roles(state)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    changed = state.model_copy(deep=True)
    hidden = ["deck-member-1", "deck-live-1", "secret", *(["return-0", "return-1"] if after else [])]
    for key in hidden:
        instance = changed.cards.pop(key)
        replacement = "HIDDEN-" + key
        instance.instance_id = replacement
        instance.card.card_code = instance.card.name_ja = "REPLACED-HIDDEN"
        changed.cards[replacement] = instance
        for p in changed.players.values():
            for zone in ["main_deck", "hand"]:
                setattr(p, zone, [replacement if item == key else item for item in getattr(p, zone)])
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner}).action == decision.action
    assert match_state_hash(state) == before
    result = apply_action(state, decision.action)
    if result.state.pending_effects:
        follow = controller.choose_action(result.state, result.legal_actions, controlled_player_ids={owner})
        assert isinstance(follow, SimpleAIDecision)
        result = apply_action(result.state, follow.action)
    assert not result.state.pending_effects


def test_parent_locks_manual_wrong_owner_stale_and_inline_targets():
    state = _pending()
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, ["return-0", "return-1"], target_card_instance_id="target"))
    assert match_state_hash(state) == before
    stale = _resolve(state, [])
    state = apply_action(state, _resolve(state, ["return-0", "return-1"])).state
    before = match_state_hash(state)
    wrong = _resolve(state, ["target"])
    wrong.player_id = "player_2"
    with pytest.raises(IllegalActionError):
        apply_action(state, wrong)
    with pytest.raises(Exception, match="revision"):
        apply_action(state, stale)
    with pytest.raises(IllegalActionError):
        apply_action(state, _manual(state, "player_1", [{"adjustment_type": "move_card", "target_card_instance_id": "target", "to_zone": "hand"}]))
    assert match_state_hash(state) == before


def test_old_manual_sql_replay_unchanged(tmp_path):
    state = _state(legacy=True)
    repo = MatchRepository(tmp_path / "legacy.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    begun = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id="player_1", expected_revision=state.revision)).state
    with pytest.raises(IllegalActionError, match="manual_resolution"):
        apply_action(begun, _resolve(begun, []))
    result = repo.apply(state.match_id, _manual(begun, "player_1", [{"adjustment_type": "set_flag", "flag": "AUDIT-legacy", "duration": "turn"}], begun.pending_effects[0]))
    assert not any(e.event_type.startswith("effect_water_blue") for e in result.events)
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


@pytest.mark.parametrize("change", [{"amount": 5}, {"target": "source"}, {"is_optional": True}, {"duration": "game"}])
def test_strict_snapshot_and_operation_variants_rejected(change):
    from pydantic import ValidationError
    raw = deepcopy(_candidate(CODE).to_registry_entry())
    (raw["actions"][0] if "amount" in change or "target" in change else raw).update(change)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)
