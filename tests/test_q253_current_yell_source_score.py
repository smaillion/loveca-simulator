from contextlib import closing
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_aqours_shared_heart_yell import _state as _base_state
from test_mirakura_front_position_boundary import _swap_roles
from test_all_active_live_requirement_boundary import _exclusive

from loveca.db.bootstrap import connect_database
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions, _card_score, _modifier_total
from loveca.simulation.models import ActionRequest, LivePerformanceResult
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!S-bp6-023"
EFFECT = CODE + ":1"
OP = "gain_source_score_if_current_yell_live"
POLICY = "original_live_success_yell_source"
RULE_REFERENCE_IDS = ("4.1.4", "8.4.4", "8.4.5", "9.2.1.2", "9.6.2.4.2", "9.7.7", "9.9.1.4", "9.9.1.5")


@lru_cache
def _raw():
    candidate = next((c for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True) if c.effect_id == EFFECT), None)
    return candidate.to_registry_entry() if candidate else next(e.model_dump(mode="json") for e in load_effect_registry().effects if e.effect_id == EFFECT)


def _state(*, count=1, legacy=False, control=True):
    state = _base_state()
    raw = deepcopy(_raw())
    if legacy:
        raw.update(condition={"yell_revealed_card_type_count_at_least": {"card_type": "live", "count": 1}},
            actions=[{"action_type": "modify_score", "amount": 1}], duration="live", execution_mode="auto_resolve")
    effect = EffectDefinition.model_validate(raw)
    state.effect_definitions = {EFFECT: effect}
    for card in state.cards.values():
        card.card.effect_ids = []
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        state.cards["source-live"].card = _load_definition(db, CODE, None, state.effect_definitions, {})
    p = state.players["player_1"]
    p.live_area = ["source-live", "live-1"]
    ids = []
    for i in range(count):
        key = f"current-yell-{i}"
        state.cards[key] = state.cards["yell-live"].model_copy(update={"instance_id": key}, deep=True)
        ids.append(key)
    p.resolution_area = [*ids, "yell-r"]
    p.live_result = LivePerformanceResult(requirements_satisfied=True, revealed_instance_ids=[*ids, "yell-r"],
        remaining_yell_instance_ids=[*ids, "yell-r"], yell_tracking_turn=state.turn_number)
    state.cards["live-1"].card.effect_ids = []
    if control:
        for key in ["CONTROL", "TAIL"]:
            audit = deepcopy(raw)
            audit.update(effect_id=key, condition={}, actions=[{"action_type": "manual_resolution"}], duration="live",
                execution_mode="manual_resolution", simulation_support="manual_resolution", review_status="parsed_draft")
            state.effect_definitions[key] = EffectDefinition.model_validate(audit)
            state.cards["source-live"].card.effect_ids.append(key)
    _exclusive(state)
    return state


def _begin(state):
    return apply_action(state, ActionRequest(action_type="advance_phase", expected_revision=state.revision))


def _manual(state, changes, effect_id="CONTROL"):
    inv = next(i for i in state.pending_effects if i.effect_id == effect_id)
    return ActionRequest(action_type="manual_adjustment", player_id=inv.player_id, expected_revision=state.revision,
        payload={"reason": "AUDIT CONTROL only", "source_invocation_id": inv.invocation_id,
            "source_effect_id": inv.effect_id, "source_card_instance_id": inv.source_card_instance_id,
            "adjustments": [{"target_player_id": inv.player_id, **c} for c in changes]})


def _resolve(state, **extra):
    inv = next(i for i in state.pending_effects if i.effect_id == EFFECT)
    return ActionRequest(action_type="resolve_effect", player_id=inv.player_id, expected_revision=state.revision,
        payload={"invocation_id": inv.invocation_id, **extra})


def _event(result):
    return next(e.data for e in result.events if e.event_type == "effect_current_yell_source_score_resolved")


def test_q253_removed_last_yell_live_native_red():
    state = _begin(_state()).state
    moved = apply_action(state, _manual(state, [{"adjustment_type": "move_card", "target_card_instance_id": "current-yell-0", "to_zone": "hand"}])).state
    result = apply_action(moved, _resolve(moved))
    assert _modifier_total(result.state.players["player_1"], "score") == 0
    assert _event(result)["score_delta"] == 0


def test_positive_score_is_on_source_live_not_global_native_red():
    state = _begin(_state()).state
    before = _card_score(state, "player_1", "source-live")
    other = _card_score(state, "player_1", "live-1")
    result = apply_action(state, _resolve(state))
    assert _card_score(result.state, "player_1", "source-live") == before + 1
    assert _card_score(result.state, "player_1", "live-1") == other
    assert _modifier_total(result.state.players["player_1"], "score") == 0


def _repo(state, tmp_path):
    repo = MatchRepository(tmp_path / "audit.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    return repo


def _replay(repo, state):
    _exclusive(state)
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == state.model_dump(mode="json")


def _start(repo, state):
    return repo.apply(state.match_id, ActionRequest(action_type="advance_phase", expected_revision=state.revision)).state


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("count", [0, 1, 2])
def test_native_current_count_and_only_source_score_sql(tmp_path, owner, first, count):
    state = _state(count=count)
    if owner == "player_2":
        state = _swap_roles(state)
    state.first_player_id, state.second_player_id = first, "player_2" if first == "player_1" else "player_1"
    before = _card_score(state, owner, "source-live")
    other = _card_score(state, owner, "live-1")
    repo = _repo(state, tmp_path)
    result = repo.apply(state.match_id, _resolve(_start(repo, state)))
    assert _event(result)["current_yell_live_count"] == count
    assert _event(result)["score_delta"] == int(count > 0)
    assert _card_score(result.state, owner, "source-live") == before + int(count > 0)
    assert _card_score(result.state, owner, "live-1") == other
    assert _modifier_total(result.state.players[owner], "score") == 0
    _replay(repo, result.state)


@pytest.mark.parametrize("timing", ["before_success", "pending"])
@pytest.mark.parametrize("move,expected", [("out", 0), ("return", 0), ("same", 1), ("partial", 1), ("new_object", 0)])
def test_q253_current_original_yell_moves_sql(tmp_path, timing, move, expected):
    state = _state(count=2 if move == "partial" else 1)
    state.cards["yell-live"].owner_id = "player_1"
    repo = _repo(state, tmp_path)
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "current-yell-0", "to_zone": "resolution_area" if move == "same" else "hand"}]
    if move == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "current-yell-0", "to_zone": "resolution_area"})
    if move == "new_object":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "yell-live", "to_zone": "resolution_area"})
    if timing == "before_success":
        state = repo.apply(state.match_id, ActionRequest(action_type="manual_adjustment", player_id="player_1", expected_revision=state.revision,
            payload={"reason": "AUDIT before success checkpoint", "adjustments": [{"target_player_id": "player_1", **c} for c in changes]})).state
        current = _start(repo, state)
    else:
        current = repo.apply(state.match_id, _manual(_start(repo, state), changes)).state
    result = repo.apply(state.match_id, _resolve(current))
    assert _event(result)["score_delta"] == expected
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("departure", [None, "clear_departed_card_modifiers"])
@pytest.mark.parametrize("move", ["hand", "deck", "waiting", "success", "return", "same"])
def test_native_control_source_original_object_sql(tmp_path, owner, departure, move):
    state = _state()
    state.stage_departure_policy = departure
    if owner == "player_2":
        state = _swap_roles(state)
    repo = _repo(state, tmp_path)
    current = _start(repo, state)
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": {
        "deck": "main_deck", "waiting": "waiting_room", "success": "success_live_area", "same": "live_area"}.get(move, "hand")}]
    if move == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "live_area"})
    current = repo.apply(state.match_id, _manual(current, changes)).state
    result = repo.apply(state.match_id, _resolve(current))
    assert _event(result)["condition_met"] is True
    assert _event(result)["source_available"] is (move == "same")
    assert _event(result)["score_delta"] == int(move == "same")
    assert _modifier_total(result.state.players[owner], "score") == 0
    if move == "deck":
        for viewer in ["player_1", "player_2"]:
            payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
            assert "source-live" not in payload["state"]["cards"]
    _replay(repo, result.state)


@pytest.mark.parametrize("departure", [None, "clear_departed_card_modifiers"])
@pytest.mark.parametrize("move", ["hand", "deck", "success", "return", "same"])
def test_applied_marker_cleanup_and_same_area_retention_sql(tmp_path, departure, move):
    state = _state()
    state.stage_departure_policy = departure
    repo = _repo(state, tmp_path)
    gained = repo.apply(state.match_id, _resolve(_start(repo, state))).state
    modifier = next(m for m in gained.players["player_1"].manual_modifiers if m.modifier_type == "live_card_score")
    assert modifier.duration == "game" and modifier.value == {"policy": POLICY}
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": {
        "deck": "main_deck", "success": "success_live_area", "same": "live_area"}.get(move, "hand")}]
    if move == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "live_area"})
    moved = repo.apply(state.match_id, _manual(gained, changes)).state
    assert any(m.modifier_type == "live_card_score" for m in moved.players["player_1"].manual_modifiers) is (move == "same")
    _replay(repo, moved)


def test_q119_resolved_condition_does_not_become_a_static_aura():
    state = _begin(_state()).state
    result = apply_action(state, _resolve(state))
    moved = apply_action(result.state, _manual(result.state, [{"adjustment_type": "move_card", "target_card_instance_id": "current-yell-0", "to_zone": "hand"}])).state
    assert _card_score(moved, "player_1", "source-live") == 5


def test_no_written_duration_is_game_separate_from_zone_object():
    from loveca.simulation.engine import _expire_modifiers
    state = _begin(_state()).state
    state = apply_action(state, _resolve(state)).state
    _expire_modifiers(state, "player_1", "live", [])
    assert _card_score(state, "player_1", "source-live") == 5
    assert state.players["player_1"].manual_modifiers[0].duration == "game"


def test_score_replacement_then_source_addition():
    from loveca.simulation.models import ManualModifier
    state = _state()
    state.players["player_1"].manual_modifiers.append(ManualModifier(modifier_id="replace", modifier_type="score_replacement",
        duration="game", created_turn=state.turn_number, amount=7, target_card_instance_id="source-live"))
    current = _begin(state).state
    result = apply_action(current, _resolve(current))
    assert _card_score(result.state, "player_1", "source-live") == 8


@pytest.mark.parametrize("legacy", [False, True])
def test_old_generic_snapshot_keeps_historical_q253_replay_sql(tmp_path, legacy):
    state = _state(legacy=legacy)
    repo = _repo(state, tmp_path)
    current = _start(repo, state)
    current = repo.apply(state.match_id, _manual(current, [{"adjustment_type": "move_card", "target_card_instance_id": "current-yell-0", "to_zone": "hand"}])).state
    result = repo.apply(state.match_id, _resolve(current))
    assert _modifier_total(result.state.players["player_1"], "score") == int(legacy)
    if not legacy:
        assert _event(result)["score_delta"] == 0
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("legacy", [False, True])
def test_native_performance_yell_tracking_and_both_orders_sql(tmp_path, owner, first, legacy):
    state = _state(legacy=legacy)
    p = state.players["player_1"]
    p.waiting_room += ["current-yell-0"]
    p.waiting_room.append("live-1")
    p.live_area = ["source-live"]
    p.resolution_area = []
    p.live_result = LivePerformanceResult(revealed_instance_ids=["current-yell-0"], remaining_yell_instance_ids=[])
    p.main_deck = ["yell-live", "deck-member-1", "deck-live-1"]
    for i, key in enumerate(p.member_area.values()):
        state.cards[key].card.blade = int(i == 0)
    # Isolate native phase order; this is not a full official-deck match.
    for key in p.live_area:
        state.cards[key].card.required_hearts = {}
    if owner == "player_2":
        state = _swap_roles(state)
    state.first_player_id, state.second_player_id = first, "player_2" if first == "player_1" else "player_1"
    state.phase, state.active_player_id = "performance_first", first
    repo = _repo(state, tmp_path)
    current, events = state, []
    for _ in range(14):
        result = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id=current.active_player_id, expected_revision=current.revision))
        current = result.state
        events += [e.data for e in result.events if e.event_type == "effect_current_yell_source_score_resolved"]
        if any(i.effect_id == EFFECT for i in current.pending_effects):
            break
    tracker = current.players[owner].live_result
    assert tracker.revealed_instance_ids == ["yell-live"]
    assert "current-yell-0" not in tracker.revealed_instance_ids
    assert tracker.yell_tracking_turn == (None if legacy else state.turn_number)
    resolved = repo.apply(state.match_id, _resolve(current))
    events += [e.data for e in resolved.events if e.event_type == "effect_current_yell_source_score_resolved"]
    assert bool(events) is (not legacy)
    if events:
        assert events[0]["score_delta"] == 1
    current = resolved.state
    _replay(repo, current)


def test_native_live_end_actual_departure_cleans_game_marker_sql(tmp_path):
    state = _state()
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _resolve(_start(repo, state))).state
    for effect in ["CONTROL", "TAIL"]:
        current = repo.apply(state.match_id, _manual(current, [{"adjustment_type": "set_flag", "flag": "AUDIT-finished", "duration": "turn"}], effect)).state
    if current.pending_choice is not None:
        current = repo.apply(state.match_id, ActionRequest(action_type="resolve_live_requirements", player_id="player_1",
            expected_revision=current.revision, payload={"success_live_instance_id": "source-live"})).state
    assert not any(m.modifier_type == "live_card_score" for m in current.players["player_1"].manual_modifiers)
    _replay(repo, current)


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("positive", [False, True])
def test_four_ai_two_sources_and_hidden_identity_invariance(policy, owner, positive):
    from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
    state = _state(count=int(positive), control=False)
    state.cards["source-2"] = state.cards["source-live"].model_copy(update={"instance_id": "source-2"}, deep=True)
    state.players["player_1"].live_area = ["source-live", "source-2"]
    if owner == "player_2":
        state = _swap_roles(state)
    state = _begin(state).state
    changed = state.model_copy(deep=True)
    for key in ["deck-member-1", "deck-live-1", "held", "secret"]:
        if key not in changed.cards:
            continue
        card = changed.cards.pop(key)
        replacement = "HIDDEN-" + key
        card.instance_id = replacement
        card.card.name_ja = card.card.card_code = "HIDDEN-IDENTITY"
        card.card.blade = 99
        changed.cards[replacement] = card
        for p in changed.players.values():
            for zone in ["hand", "main_deck"]:
                setattr(p, zone, [replacement if i == key else i for i in getattr(p, zone)])
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner}).action == decision.action
    assert match_state_hash(state) == before
    result = apply_action(state, decision.action)
    events = [e.data for e in result.events if e.event_type == "effect_current_yell_source_score_resolved"]
    assert len(events) == 2 and all(e["score_delta"] == int(positive) for e in events)


@pytest.mark.parametrize("bad", ["missing_source", "non_boolean_source", "missing_yell", "old_turn", "boolean_turn", "duplicate", "not_started"])
def test_missing_or_stale_snapshot_is_atomic(bad):
    state = _begin(_state()).state
    inv = next(i for i in state.pending_effects if i.effect_id == EFFECT)
    if bad == "missing_source":
        inv.trigger_data.pop("original_source_live_object")
    elif bad == "non_boolean_source":
        inv.trigger_data["original_source_live_object"] = 1
    elif bad == "missing_yell":
        state.players["player_1"].live_result.remaining_yell_instance_ids = None
    elif bad == "old_turn":
        state.players["player_1"].live_result.yell_tracking_turn -= 1
    elif bad == "boolean_turn":
        state.players["player_1"].live_result.yell_tracking_turn = True
    elif bad == "duplicate":
        state.players["player_1"].live_result.remaining_yell_instance_ids.append("current-yell-0")
    else:
        state.live_success_effects_queued = False
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("extra", [{"selected_card_instance_ids": ["live-1"]}, {"energy_instance_ids": ["energy-1"]}, {"selected_branch": "other"}, {"selected_color_slot": "heart05"}])
def test_non_owner_extra_selection_and_cost_are_atomic(extra):
    state = _begin(_state()).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, **extra))
    wrong = _resolve(state)
    wrong.player_id = "player_2"
    with pytest.raises(IllegalActionError):
        apply_action(state, wrong)
    assert match_state_hash(state) == before


@pytest.mark.parametrize("field,value", [("amount", 2), ("target", "self"), ("source_object_policy", None), ("duration", "live"), ("is_optional", True), ("timing", "live_start"), ("cost", [{"action_type": "draw_card", "amount": 1}])])
def test_snapshot_rejects_widening(field, value):
    raw = deepcopy(_raw())
    if field in {"amount", "target", "source_object_policy"}:
        raw["actions"][0][field] = value
    else:
        raw[field] = value
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


def test_exact_generator_and_no_unsafe_legacy_fallback():
    from loveca.simulation.effect_candidates import _live_success_current_yell_source_score, _live_success_simple_effects
    raw = _raw()
    row = {k: raw[k] for k in ["card_code", "text_revision_id", "raw_text_hash"]}
    row["raw_effect_text_ja"] = raw["label_ja"]
    assert _live_success_current_yell_source_score(row)
    assert _live_success_simple_effects(row) is None
    for key in row:
        bad = dict(row)
        bad[key] = 0 if key == "text_revision_id" else "WRONG"
        assert _live_success_current_yell_source_score(bad) is None


def test_repeat_and_stale_resolution_are_atomic():
    from loveca.simulation.engine import StaleRevisionError
    state = _begin(_state()).state
    action = _resolve(state)
    resolved = apply_action(state, action).state
    before = match_state_hash(resolved)
    with pytest.raises(StaleRevisionError):
        apply_action(resolved, action)
    action.expected_revision = resolved.revision
    with pytest.raises(IllegalActionError):
        apply_action(resolved, action)
    assert match_state_hash(resolved) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_full_both_views_after_public_yell_enters_private_hand(owner):
    state = _state()
    if owner == "player_2":
        state = _swap_roles(state)
    current = _begin(state).state
    current = apply_action(current, _manual(current, [{"adjustment_type": "move_card", "target_card_instance_id": "current-yell-0", "to_zone": "hand"}])).state
    result = apply_action(current, _resolve(current))
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        cards = payload["state"]["cards"]
        assert ("current-yell-0" in cards) is (viewer == owner)
        for p in result.state.players.values():
            assert not any(key in cards for key in p.main_deck)
            if p.player_id != viewer:
                assert not any(key in cards for key in p.hand)
    assert _event(result)["score_delta"] == 0
