from contextlib import closing
from copy import deepcopy
from pathlib import Path

import pytest
from test_aqours_blade_six_score import _state as _live_state
from test_all_active_live_requirement_boundary import _exclusive
from test_nijigasaki_inspection import _candidate

from loveca.db.bootstrap import connect_database
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository

CODE = "PL!S-bp7-025"
EFFECT = CODE + ":1"
POLICY = "public_opponent_cost4_wait_or_draw"
RULE_REFERENCE_IDS = ("1.3.2.1", "1.3.5.1", "4.1.4", "7.1.2", "7.3.3", "7.4.1", "9.6.3.1.1", "9.7.7")


def _state(*, legacy=False):
    effect = next(e for e in load_effect_registry().effects if e.effect_id == EFFECT)
    if not legacy:
        effect = EffectDefinition.model_validate(_candidate(CODE).to_registry_entry())
    if legacy:
        raw = effect.model_dump(mode="json")
        raw.update(choice=None, actions=[{"action_type": "manual_resolution"}], execution_mode="manual_resolution", simulation_support="manual_resolution", review_status="parsed_draft")
        effect = EffectDefinition.model_validate(raw)
    state = _live_state()
    state.cards["deck-member-2"] = state.cards["deck-member-1"].model_copy(update={"instance_id": "deck-member-2"}, deep=True)
    state.effect_definitions = {EFFECT: effect}
    for card in state.cards.values():
        card.card.effect_ids = []
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        state.cards["source-live"].card = _load_definition(db, CODE, None, {EFFECT: effect}, {})
    p = state.players["player_1"]
    p.live_area = ["source-live"]
    p.hand = ["held"]
    p.member_area = {"left": "target", "center": None, "right": "wrong-work"}
    p.main_deck = ["deck-member-1", "deck-member-2", "deck-live-1"]
    p.waiting_room = []
    other = state.players["player_2"]
    other.live_area = []
    for n, cost in enumerate([2, 4, 5]):
        key = f"opponent-{n}"
        state.cards[key] = state.cards["opponent"].model_copy(update={"instance_id": key}, deep=True)
        state.cards[key].card.cost = cost
        state.cards[key].face_up = True
    other.member_area = {"left": "opponent-0", "center": "opponent-1", "right": "opponent-2"}
    other.member_area_attachments = {"left": [], "center": [], "right": []}
    state.phase, state.active_player_id = "live_judgment", None
    state.effect_order_policy = "ap_nap_player_choice"
    _exclusive(state)
    assert all(item in state.cards for player in state.players.values() for zone in [player.hand, player.main_deck, player.waiting_room] for item in zone)
    return state


def _begin(state):
    return apply_action(state, ActionRequest(action_type="advance_phase", player_id=None, expected_revision=state.revision))


def _resolve(state, **extra):
    inv = next(i for i in state.pending_effects if i.effect_id == EFFECT)
    return ActionRequest(action_type="resolve_effect", player_id=inv.player_id, expected_revision=state.revision,
        payload={"invocation_id": inv.invocation_id, **extra})


def test_native_success_offers_structured_branches():
    result = _begin(_state())
    assert result.state.pending_effects
    assert result.state.effect_definitions[EFFECT].choice.selection_policy == POLICY
    selected = apply_action(result.state, _resolve(result.state, selected_branch="wait_opponent")).state
    final = apply_action(selected, _resolve(selected, selected_card_instance_ids=["opponent-0", "opponent-1"]))
    assert final.state.cards["opponent-0"].orientation == "wait"
    assert len(final.state.players["player_2"].manual_modifiers) == 2


def _event(result):
    return next(e.data for e in result.events if e.event_type == "effect_opponent_member_next_active_resolved")


def _pending(**kwargs):
    return _begin(_state(**kwargs)).state


def _wait(state, ids, *, repo=None):
    step = repo.apply if repo else lambda _, a: apply_action(state, a)
    selected = step(state.match_id, _resolve(state, selected_branch="wait_opponent")).state
    return repo.apply(state.match_id, _resolve(selected, selected_card_instance_ids=ids)) if repo else apply_action(selected, _resolve(selected, selected_card_instance_ids=ids))


@pytest.mark.parametrize("count", [0, 1, 2])
@pytest.mark.parametrize("already_wait", [False, True])
def test_zero_to_two_selected_and_already_wait_sql(tmp_path, count, already_wait):
    state = _state()
    if already_wait:
        state.cards["opponent-0"].orientation = "wait"
    repo = MatchRepository(tmp_path / "count.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    state = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id=None, expected_revision=state.revision)).state
    result = _wait(state, [f"opponent-{i}" for i in range(count)], repo=repo)
    assert _event(result)["restricted_count"] == count
    assert _event(result)["waited_count"] == count - int(already_wait and count > 0)
    assert result.state.cards["opponent-2"].orientation == "active"
    _exclusive(result.state)
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


@pytest.mark.parametrize("short", ["normal", "one", "empty_refresh", "empty_all"])
def test_draw_branch_short_deck_and_private_payload_sql(tmp_path, short):
    from loveca.webapp import _match_state_payload
    state = _state()
    p = state.players["player_1"]
    if short == "one":
        p.main_deck = ["deck-member-1"]
        p.waiting_room = ["deck-member-2"]
    if short.startswith("empty"):
        p.main_deck = []
        p.waiting_room = ["deck-member-2"] if short == "empty_refresh" else []
    repo = MatchRepository(tmp_path / "draw.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    state = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id=None, expected_revision=state.revision)).state
    before = len(state.players["player_1"].hand)
    result = repo.apply(state.match_id, _resolve(state, selected_branch="draw_one"))
    assert not result.state.pending_effects
    assert _event(result)["drawn_count"] == int(short != "empty_all")
    assert len(result.state.players["player_1"].hand) == before + int(short != "empty_all")
    assert not result.state.players["player_2"].manual_modifiers
    payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id="player_2")
    assert "deck-member-1" not in payload["state"]["cards"]
    assert "deck-member-2" not in payload["state"]["cards"]
    _exclusive(result.state)
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


def _manual(state, owner, changes, invocation=None):
    payload = {"reason": "AUDIT CONTROL only", "adjustments": [{"target_player_id": owner, **c} for c in changes]}
    if invocation:
        payload.update(source_invocation_id=invocation.invocation_id, source_effect_id=invocation.effect_id, source_card_instance_id=invocation.source_card_instance_id)
    return ActionRequest(action_type="manual_adjustment", player_id=owner, expected_revision=state.revision, payload=payload)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("first", ["player_1", "player_2"])
def test_complete_native_turns_skip_selected_opponent_once_sql(tmp_path, owner, first):
    from test_mirakura_front_position_boundary import _swap_roles
    from test_wait_energy_next_active import _phase_action, _walk
    state = _state()
    if owner == "player_2":
        state = _swap_roles(state)
    state.first_player_id, state.second_player_id = first, "player_2" if first == "player_1" else "player_1"
    repo = MatchRepository(tmp_path / "turns.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    begun = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id=None, expected_revision=state.revision)).state
    selected = _wait(begun, ["opponent-0"], repo=repo).state
    target_owner = "player_2" if owner == "player_1" else "player_1"
    ended = _walk(selected, lambda s: s.phase == "turn_complete", repo=repo)
    next_turn = repo.apply(state.match_id, _phase_action(ended)).state
    active = _walk(next_turn, lambda s: s.phase.endswith("_active") and s.active_player_id == target_owner, repo=repo)
    result = repo.apply(state.match_id, _phase_action(active))
    assert result.state.cards["opponent-0"].orientation == "wait"
    assert result.state.cards["opponent-1"].orientation == "active"
    assert not result.state.players[target_owner].manual_modifiers
    ended = _walk(result.state, lambda s: s.phase == "turn_complete", repo=repo)
    next_turn = repo.apply(state.match_id, _phase_action(ended)).state
    active = _walk(next_turn, lambda s: s.phase.endswith("_active") and s.active_player_id == target_owner, repo=repo)
    final = repo.apply(state.match_id, _phase_action(active))
    assert final.state.cards["opponent-0"].orientation == "active"
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


@pytest.mark.parametrize("move", ["hand", "return", "main_deck", "position", "formation"])
@pytest.mark.parametrize("departure_policy", [None, "clear_departed_card_modifiers"])
def test_target_object_and_group_changes_sql(tmp_path, move, departure_policy):
    from test_wait_energy_next_active import _phase_action, _walk
    state = _state()
    state.stage_departure_policy = departure_policy
    repo = MatchRepository(tmp_path / "object.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    begun = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id=None, expected_revision=state.revision)).state
    selected = _wait(begun, ["opponent-0"], repo=repo).state
    if move in {"hand", "main_deck", "return"}:
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": "opponent-0", "to_zone": "main_deck" if move == "main_deck" else "hand"}]
        if move == "return":
            changes.append({"adjustment_type": "move_card", "target_card_instance_id": "opponent-0", "to_zone": "member_left"})
    elif move == "position":
        changes = [{"adjustment_type": "position_change", "from_slot": "left", "to_slot": "center"}]
    elif move == "formation":
        changes = [{"adjustment_type": "formation_change", "slot_assignments": {"left": "opponent-1", "center": "opponent-2", "right": "opponent-0"}}]
    moved = repo.apply(state.match_id, _manual(selected, "player_2", changes)).state
    retained = move not in {"hand", "main_deck", "return"}
    assert bool(moved.players["player_2"].manual_modifiers) is retained
    _exclusive(moved)
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


def test_control_ready_then_wait_does_not_consume_marker_sql(tmp_path):
    from loveca.simulation.models import EffectInvocation
    state = _wait(_pending(), ["opponent-0"]).state
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id="CONTROL-ready-wait", choice=None, actions=[{"action_type": "ready_member", "target": "source"}, {"action_type": "apply_wait", "target": "source"}])
    state.effect_definitions["CONTROL-ready-wait"] = EffectDefinition.model_validate(raw)
    state.pending_effects = [EffectInvocation(invocation_id="CONTROL", effect_id="CONTROL-ready-wait", player_id="player_2", source_card_instance_id="opponent-0", trigger_event="live_succeeded")]
    repo = MatchRepository(tmp_path / "ready-wait.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repo.apply(state.match_id, ActionRequest(action_type="resolve_effect", player_id="player_2", expected_revision=state.revision, payload={"invocation_id": "CONTROL"}))
    assert result.state.cards["opponent-0"].orientation == "wait"
    assert len(result.state.players["player_2"].manual_modifiers) == 1
    assert any(flag.endswith(":member") for flag in result.state.players["player_2"].effect_ready_flags_this_turn)
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


@pytest.mark.parametrize("bad", [["target"], ["opponent-2"], ["opponent-0", "opponent-0"], ["opponent-0", "opponent-1", "opponent-2"], ["secret"], ["attached"]])
def test_wrong_targets_are_atomic(bad):
    state = _pending()
    state = apply_action(state, _resolve(state, selected_branch="wait_opponent")).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, selected_card_instance_ids=bad))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("bad", [{"selected_branch": "bad"}, {"selected_branch": ["draw_one", "wait_opponent"]}, {"selected_branch": "draw_one", "selected_card_instance_ids": ["opponent-0"]}, {"selected_branch": "draw_one", "energy_instance_ids": ["energy-0"]}, {"accepted": False}, {"target_player_id": "player_2"}])
def test_initial_extra_or_decline_rejected_atomically(bad):
    state = _pending()
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, **bad))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("branch", [None, "wait_opponent"])
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_four_ai_actual_branch_hidden_invariance_and_no_mutation(policy, branch, owner):
    from loveca.simulation.ai import SimpleAIController, SimpleAIPolicy, SimpleAIDecision
    from test_mirakura_front_position_boundary import _swap_roles
    state = _pending()
    if branch:
        state = apply_action(state, _resolve(state, selected_branch=branch)).state
    if owner == "player_2":
        state = _swap_roles(state)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    changed = state.model_copy(deep=True)
    for key in ["held", "secret", "deck-member-1", "deck-member-2"]:
        old = changed.cards.pop(key)
        new = "hidden-" + key
        old.instance_id = new
        old.card.name_ja = old.card.card_code = "HIDDEN-REPLACED"
        changed.cards[new] = old
        for p in changed.players.values():
            for zone in ["hand", "main_deck"]:
                setattr(p, zone, [new if item == key else item for item in getattr(p, zone)])
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner}).action == decision.action
    assert match_state_hash(state) == before
    result = apply_action(state, decision.action)
    if result.state.pending_effects:
        follow = controller.choose_action(result.state, result.legal_actions, controlled_player_ids={owner})
        assert isinstance(follow, SimpleAIDecision)
        result = apply_action(result.state, follow.action)
    assert not result.state.pending_effects
    assert _event(result)["selected_branch"] in {"draw_one", "wait_opponent"}


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("move", ["hand", "main_deck", "return", "same_live_area"])
def test_native_control_source_interference_sql(tmp_path, owner, move):
    from loveca.webapp import _match_state_payload
    from test_mirakura_front_position_boundary import _swap_roles
    state = _state()
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id="CONTROL", choice=None, actions=[{"action_type": "manual_resolution"}], execution_mode="manual_resolution", simulation_support="manual_resolution", review_status="parsed_draft")
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    state.cards["source-live"].card.effect_ids.append("CONTROL")
    if owner == "player_2":
        state = _swap_roles(state)
    repo = MatchRepository(tmp_path / "source.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    begun = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id=None, expected_revision=state.revision)).state
    ctrl = next(i for i in begun.pending_effects if i.effect_id == "CONTROL")
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "main_deck" if move == "main_deck" else "live_area" if move == "same_live_area" else "hand"}]
    if move == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "live_area"})
    moved = repo.apply(state.match_id, _manual(begun, owner, changes, ctrl)).state
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(moved, events=[], legal_actions=generate_legal_actions(moved), player_id=viewer)
        if move == "main_deck" or (move == "hand" and viewer != owner):
            assert "source-live" not in payload["state"]["cards"]
        assert "secret" not in payload["state"]["cards"] if viewer == owner else True
    result = _wait(moved, ["opponent-0"], repo=repo)
    assert _event(result)["restricted_count"] == 1
    _exclusive(result.state)
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


@pytest.mark.parametrize("cost", [3, 4, 5])
def test_cost_bound_and_empty_targets(cost):
    state = _state()
    other = state.players["player_2"]
    other.member_area = {"left": "opponent-0", "center": None, "right": None}
    state.cards["opponent-0"].card.cost = cost
    state = _begin(state).state
    selected = apply_action(state, _resolve(state, selected_branch="wait_opponent")).state
    options = next(a for a in generate_legal_actions(selected) if a.action_type == "resolve_effect").options["invocations"][0]
    assert options["candidate_card_instance_ids"] == (["opponent-0"] if cost <= 4 else [])
    result = apply_action(selected, _resolve(selected, selected_card_instance_ids=[]))
    assert _event(result)["restricted_count"] == 0


def test_attached_member_is_not_a_target_and_other_player_cannot_choose():
    state = _state()
    state.cards["attached"].owner_id = "player_2"
    state.players["player_1"].member_area_attachments["right"] = []
    state.players["player_2"].member_area_attachments["left"] = ["attached"]
    state = _begin(state).state
    state = apply_action(state, _resolve(state, selected_branch="wait_opponent")).state
    before = match_state_hash(state)
    action = _resolve(state, selected_card_instance_ids=["opponent-0"])
    action.player_id = "player_2"
    with pytest.raises(IllegalActionError):
        apply_action(state, action)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, selected_card_instance_ids=["attached"]))
    assert match_state_hash(state) == before


def test_parent_branch_rejects_manual_switch_and_stale_action():
    state = _pending()
    stale = _resolve(state, selected_branch="draw_one")
    state = apply_action(state, _resolve(state, selected_branch="wait_opponent")).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, selected_branch="draw_one"))
    with pytest.raises(Exception, match="revision"):
        apply_action(state, stale)
    with pytest.raises(IllegalActionError):
        apply_action(state, _manual(state, "player_2", [{"adjustment_type": "position_change", "from_slot": "left", "to_slot": "center"}]))
    assert match_state_hash(state) == before


def test_legacy_manual_sql_and_exact_identity(tmp_path):
    state = _state(legacy=True)
    assert (state.effect_definitions[EFFECT].text_revision_id, state.effect_definitions[EFFECT].raw_text_hash) == (917, "8f3f0088db7c0001fda1fbc53680efde3f4bc6bcdccc8dde9ac0345ca80d5bc6")
    repo = MatchRepository(tmp_path / "legacy.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    begun = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id=None, expected_revision=state.revision)).state
    with pytest.raises(IllegalActionError, match="manual_resolution"):
        apply_action(begun, _resolve(begun, selected_branch="draw_one"))
    final = repo.apply(state.match_id, _manual(begun, "player_1", [{"adjustment_type": "set_flag", "flag": "AUDIT-legacy", "duration": "turn"}], begun.pending_effects[0]))
    assert not any(e.event_type == "effect_opponent_member_next_active_resolved" for e in final.events)
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


@pytest.mark.parametrize("field,value", [("card_code", "OTHER"), ("text_revision_id", 918), ("raw_text_hash", "bad"), ("raw_effect_text_ja", "bad")])
def test_generator_full_binding(field, value):
    from loveca.simulation.effect_candidates import _live_success_opponent_cost4_wait_or_draw
    row = dict(card_code=CODE, text_revision_id=917, raw_text_hash="8f3f0088db7c0001fda1fbc53680efde3f4bc6bcdccc8dde9ac0345ca80d5bc6", raw_effect_text_ja=_candidate(CODE).label_ja)
    row[field] = value
    assert _live_success_opponent_cost4_wait_or_draw(row) is None


@pytest.mark.parametrize("change", [{"amount": 3}, {"target": "source"}, {"branch": "draw_one"}])
def test_bounded_operation_rejects_variants(change):
    from pydantic import ValidationError
    raw = deepcopy(_candidate(CODE).to_registry_entry())
    raw["actions"][0].update(change)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("change", [{"is_optional": True}, {"duration": "live"}, {"timing": "on_play"}, {"frequency_limit": "none"}])
def test_bounded_snapshot_rejects_variants(change):
    from pydantic import ValidationError
    raw = deepcopy(_candidate(CODE).to_registry_entry())
    raw.update(change)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("target_turn_delta", [0, 1, 2])
def test_explicit_active_checkpoint_respects_game_turn_not_next_operation(target_turn_delta):
    from test_wait_energy_next_active import _phase_action
    state = _wait(_pending(), ["opponent-0"]).state
    original_turn = state.turn_number
    state.turn_number += target_turn_delta
    state.phase, state.active_player_id = "second_active", "player_2"
    result = apply_action(state, _phase_action(state))
    assert result.state.cards["opponent-0"].orientation == ("wait" if target_turn_delta == 1 else "active")
    assert bool(result.state.players["player_2"].manual_modifiers) is (target_turn_delta == 0)
    assert original_turn + 1 == _event(_wait(_pending(), ["opponent-0"]))["target_turn"]


@pytest.mark.parametrize("value", [{"policy": "wrong", "target_turn": 2}, {"policy": "selected_opponent_cost4_next_turn_active", "target_turn": True}, {"policy": "selected_opponent_cost4_next_turn_active", "target_turn": 2, "extra": True}])
def test_wrong_marker_cannot_restrict_member(value):
    from test_wait_energy_next_active import _phase_action
    state = _wait(_pending(), ["opponent-0"]).state
    state.players["player_2"].manual_modifiers[0].value = value
    state.turn_number += 1
    state.phase, state.active_player_id = "second_active", "player_2"
    assert apply_action(state, _phase_action(state)).state.cards["opponent-0"].orientation == "active"
