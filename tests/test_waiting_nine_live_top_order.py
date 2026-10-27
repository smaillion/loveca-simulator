from contextlib import closing
from copy import deepcopy
from functools import lru_cache
from itertools import permutations
from pathlib import Path

import pytest
from test_water_blue_bottom_heart import _state as _base_state
from test_all_active_live_requirement_boundary import _exclusive
from test_mirakura_front_position_boundary import _swap_roles

from loveca.db.bootstrap import connect_database
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!S-PR-048"
EFFECT = CODE + ":1"
POLICY = "public_waiting_nine_live_three_private_top"
RULE_REFERENCE_IDS = ("1.3.5.1", "4.1.4", "4.1.5.1", "4.8.2", "4.12.2", "9.6.2.4.2", "9.7.7", "10.2.1", "10.2.2.1", "10.2.3")


@lru_cache
def _raw():
    candidate = next((c for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True) if c.effect_id == EFFECT), None)
    return candidate.to_registry_entry() if candidate else next(e.model_dump(mode="json") for e in load_effect_registry().effects if e.effect_id == EFFECT)


def _state(total=9, live_count=4, *, legacy=False, control=False):
    state = _base_state()
    raw = deepcopy(_raw())
    if legacy:
        raw.update(choice=None, actions=[{"action_type": "manual_resolution"}], execution_mode="manual_resolution", simulation_support="manual_resolution")
    effect = EffectDefinition.model_validate(raw)
    state.effect_definitions = {EFFECT: effect}
    for instance in state.cards.values():
        instance.card.effect_ids = []
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        state.cards["source-live"].card = _load_definition(db, CODE, None, state.effect_definitions, {})
    p = state.players["player_1"]
    p.live_area = ["live-1"]
    p.member_area = {"left": "source-live", "center": "target", "right": None}
    p.member_area_attachments = {"left": [], "center": [], "right": []}
    p.waiting_room = []
    for i in range(total):
        key = f"waiting-{i}"
        state.cards[key] = state.cards["live-1" if i < live_count else "target"].model_copy(update={"instance_id": key, "face_up": True}, deep=True)
        state.cards[key].card.name_ja = "同名Live" if i < 2 else "AUDIT-" + key
        state.cards[key].card.effect_ids = []
        p.waiting_room.append(key)
    if control:
        for key in ["CONTROL", "TAIL"]:
            audit = {**raw, "effect_id": key, "choice": None, "actions": [{"action_type": "manual_resolution"}], "execution_mode": "manual_resolution", "simulation_support": "manual_resolution"}
            state.effect_definitions[key] = EffectDefinition.model_validate(audit)
            state.cards["source-live"].card.effect_ids.append(key)
    _exclusive(state)
    return state


def _begin(state):
    return apply_action(state, ActionRequest(action_type="advance_phase", player_id=state.active_player_id, expected_revision=state.revision))


def _resolve(state, ids=None, **extra):
    inv = next(i for i in state.pending_effects if i.effect_id == EFFECT)
    return ActionRequest(action_type="resolve_effect", player_id=inv.player_id, expected_revision=state.revision,
        payload={"invocation_id": inv.invocation_id, "selected_card_instance_ids": ids or [], **extra})


def _event(result):
    return next(e.data for e in result.events if e.event_type == "effect_waiting_live_top_resolved")


def test_native_live_start_up_to_three_live_to_exact_top_order_red():
    state = _begin(_state()).state
    tail = list(state.players["player_1"].main_deck)
    result = apply_action(state, _resolve(state, ["waiting-2", "waiting-0"]))
    assert result.state.players["player_1"].main_deck == ["waiting-2", "waiting-0", *tail]
    assert _event(result)["returned_count"] == 2


def test_native_body_condition_counts_all_waiting_cards_red():
    result = _begin(_state(10, 1))
    assert not result.state.pending_effects
    assert _event(result)["condition_met"] is False


def _repo(state, tmp_path):
    repo = MatchRepository(tmp_path / "audit.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    return repo


def _replay(repo, state):
    _exclusive(state)
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == state.model_dump(mode="json")


def _manual(state, changes, effect_id="CONTROL"):
    inv = next(i for i in state.pending_effects if i.effect_id == effect_id)
    return ActionRequest(action_type="manual_adjustment", player_id=inv.player_id, expected_revision=state.revision,
        payload={"reason": "AUDIT CONTROL only", "source_invocation_id": inv.invocation_id,
            "source_effect_id": inv.effect_id, "source_card_instance_id": inv.source_card_instance_id,
            "adjustments": [{"target_player_id": inv.player_id, **c} for c in changes]})


ORDERS = [list(p) for n in range(4) for p in permutations(["waiting-0", "waiting-1", "waiting-2"], n)]


@pytest.mark.parametrize("ids", ORDERS)
def test_every_zero_to_three_subset_order_keeps_original_tail_sql(tmp_path, ids):
    state = _state()
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id="player_1", expected_revision=0)).state
    tail = list(current.players["player_1"].main_deck)
    waiting = list(current.players["player_1"].waiting_room)
    result = repo.apply(state.match_id, _resolve(current, ids))
    assert result.state.players["player_1"].main_deck == [*ids, *tail]
    assert result.state.players["player_1"].waiting_room == [i for i in waiting if i not in ids]
    assert _event(result)["selected_card_instance_ids"] == [i for i in waiting if i in ids]
    assert _event(result)["returned_count"] == len(ids)
    assert not any(e.event_type == "deck_shuffled" for e in result.events)
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("total,lives", [(0, 0), (1, 1), (9, 0), (9, 1), (9, 4), (10, 1)])
def test_total_waiting_not_live_count_and_both_roles_sql(tmp_path, owner, total, lives):
    state = _state(total, lives)
    if owner == "player_2":
        state = _swap_roles(state)
        state.phase, state.active_player_id = "performance_second", owner
    repo = _repo(state, tmp_path)
    result = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id=owner, expected_revision=state.revision))
    if result.state.pending_effects:
        ids = [f"waiting-{i}" for i in range(min(3, lives))]
        result = repo.apply(state.match_id, _resolve(result.state, ids))
    assert _event(result)["condition_met"] is (total <= 9)
    assert _event(result)["waiting_count_at_resolution"] == total
    assert _event(result)["returned_count"] == (min(3, lives) if total <= 9 else 0)
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("start,end", [(9, 10), (10, 9), (0, 1)])
def test_body_condition_is_read_after_sibling_changes_sql(tmp_path, owner, start, end):
    state = _state(start, min(start, 4), control=True)
    state.cards["new-live"] = state.cards["live-1"].model_copy(update={"instance_id": "new-live"}, deep=True)
    state.cards["new-live"].card.effect_ids = []
    state.players["player_1"].hand.append("new-live")
    if owner == "player_2":
        state = _swap_roles(state)
        state.phase, state.active_player_id = "performance_second", owner
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id=owner, expected_revision=state.revision)).state
    change = {"adjustment_type": "move_card", "target_card_instance_id": "new-live" if end > start else "waiting-9",
        "to_zone": "waiting_room" if end > start else "hand"}
    current = repo.apply(state.match_id, _manual(current, [change])).state
    selected = ["new-live" if start == 0 else "waiting-0"] if end <= 9 else []
    result = repo.apply(state.match_id, _resolve(current, selected))
    assert _event(result)["condition_met"] is (end <= 9)
    assert _event(result)["waiting_count_at_resolution"] == end
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("move", ["hand", "deck", "waiting", "return", "position"])
def test_source_departure_return_and_position_do_not_cancel_sql(tmp_path, owner, move):
    state = _state(control=True)
    if owner == "player_2":
        state = _swap_roles(state)
        state.phase, state.active_player_id = "performance_second", owner
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id=owner, expected_revision=state.revision)).state
    if move == "position":
        changes = [{"adjustment_type": "position_change", "from_slot": "left", "to_slot": "right"}]
    else:
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live",
            "to_zone": {"deck": "main_deck", "waiting": "waiting_room"}.get(move, "hand")}]
        if move == "return":
            changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_left"})
    current = repo.apply(state.match_id, _manual(current, changes)).state
    result = repo.apply(state.match_id, _resolve(current, [] if move == "waiting" else ["waiting-0"]))
    assert _event(result)["returned_count"] == int(move != "waiting")
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        cards = payload["state"]["cards"]
        for p in result.state.players.values():
            assert not any(i in cards for i in p.main_deck)
            if p.player_id != viewer:
                assert not any(i in cards for i in p.hand)
    _replay(repo, result.state)


@pytest.mark.parametrize("deck_size,total", [(0, 0), (0, 9), (0, 10), (1, 9), (2, 9)])
def test_empty_refresh_before_condition_not_private_look_prefill_sql(tmp_path, deck_size, total):
    state = _state(total, min(3, total))
    p = state.players["player_1"]
    p.hand += p.main_deck[deck_size:]
    p.main_deck = p.main_deck[:deck_size]
    original = list(p.main_deck)
    waiting = set(p.waiting_room)
    repo = _repo(state, tmp_path)
    result = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id="player_1", expected_revision=state.revision))
    if result.state.pending_effects:
        result = repo.apply(state.match_id, _resolve(result.state, [f"waiting-{i}" for i in range(min(3, total))]))
    data = _event(result)
    if deck_size:
        assert result.state.players["player_1"].main_deck == ["waiting-0", "waiting-1", "waiting-2", *original]
        assert not any(e.event_type == "deck_refreshed" for e in result.events)
    else:
        assert data["returned_count"] == 0 and data["waiting_count_at_resolution"] == 0
        assert set(result.state.players["player_1"].main_deck) == waiting
        assert result.state.players["player_1"].refresh_count == int(bool(waiting))
    _replay(repo, result.state)


@pytest.mark.parametrize("legacy", [False, True])
def test_new_and_old_manual_live_start_snapshot_sql(tmp_path, legacy):
    state = _state(legacy=legacy)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id="player_1", expected_revision=state.revision)).state
    if legacy:
        with pytest.raises(IllegalActionError, match="ManualAdjustmentAction"):
            apply_action(current, _resolve(current, ["waiting-0"]))
        final = repo.apply(state.match_id, _manual(current, [{"adjustment_type": "set_flag", "flag": "AUDIT-legacy", "duration": "turn"}], EFFECT)).state
    else:
        final = repo.apply(state.match_id, _resolve(current, ["waiting-0"])).state
    _replay(repo, final)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_all_six_orders_have_identical_complete_opponent_projection(owner):
    state = _state()
    if owner == "player_2":
        state = _swap_roles(state)
        state.phase, state.active_player_id = "performance_second", owner
    current = _begin(state).state
    opponent = "player_2" if owner == "player_1" else "player_1"
    visible = []
    for ids in permutations(["waiting-0", "waiting-1", "waiting-2"]):
        result = apply_action(current, _resolve(current, list(ids)))
        assert result.state.players[owner].main_deck[:3] == list(ids)
        before = match_state_hash(result.state)
        for viewer in [owner, opponent]:
            payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
            assert not any(i in payload["state"]["cards"] for i in ids)
            if viewer == opponent:
                visible.append(payload)
        assert match_state_hash(result.state) == before
    assert all(p == visible[0] for p in visible)


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_four_ai_actual_ordered_choice_and_hidden_identity_invariance(policy, owner):
    from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
    state = _state()
    if owner == "player_2":
        state = _swap_roles(state)
        state.phase, state.active_player_id = "performance_second", owner
    current = _begin(state).state
    changed = current.model_copy(deep=True)
    for p in changed.players.values():
        for key in list(p.main_deck + (p.hand if p.player_id != owner else [])):
            card = changed.cards.pop(key)
            new = "HIDDEN-" + key
            card.instance_id = new
            card.card.name_ja = card.card.card_code = "HIDDEN-IDENTITY"
            changed.cards[new] = card
            for zone in ["main_deck", "hand"]:
                setattr(p, zone, [new if i == key else i for i in getattr(p, zone)])
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(current)
    decision = controller.choose_action(current, generate_legal_actions(current), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner}).action == decision.action
    assert match_state_hash(current) == before
    selected = decision.action.payload.get("selected_card_instance_ids", [])
    result = apply_action(current, decision.action)
    assert _event(result)["returned_count"] == len(selected) <= 3
    assert result.state.players[owner].main_deck[:len(selected)] == selected


@pytest.mark.parametrize("ids", [["waiting-0", "waiting-0"], ["waiting-0", "waiting-1", "waiting-2", "waiting-3"], ["waiting-4"], ["deck-member-1"], ["secret"], [1], "waiting-0"])
def test_illegal_card_lists_are_atomic(ids):
    current = _begin(_state()).state
    action = _resolve(current)
    action.payload["selected_card_instance_ids"] = ids
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        apply_action(current, action)
    assert match_state_hash(current) == before


@pytest.mark.parametrize("extra", [{"energy_instance_ids": ["energy-0"]}, {"accepted": False}, {"accepted": 1}, {"selected_branch": "top"}, {"ordered_card_instance_ids": ["waiting-0"]}, {"public_reveal_policy": POLICY}])
def test_extra_parameters_and_wrong_owner_rejected(extra):
    current = _begin(_state()).state
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        apply_action(current, _resolve(current, ["waiting-0"], **extra))
    wrong = _resolve(current, ["waiting-0"])
    wrong.player_id = "player_2"
    with pytest.raises(IllegalActionError):
        apply_action(current, wrong)
    assert match_state_hash(current) == before


def test_stale_and_repeat_submit_rejected():
    from loveca.simulation.engine import StaleRevisionError
    current = _begin(_state()).state
    request = _resolve(current, ["waiting-0"])
    result = apply_action(current, request)
    with pytest.raises(StaleRevisionError):
        apply_action(result.state, request)
    request.expected_revision = result.state.revision
    with pytest.raises(IllegalActionError):
        apply_action(result.state, request)


@pytest.mark.parametrize("field,value", [("condition", {"own_waiting_room_count_at_most": 9}), ("is_optional", True), ("duration", "live"), ("frequency_limit", "none"), ("timing", "on_play"), ("cost", [{"action_type": "draw_card", "amount": 1}])])
def test_fixed_snapshot_rejects_widening(field, value):
    from pydantic import ValidationError
    raw = deepcopy(_raw())
    raw[field] = value
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


def test_exact_full_text_revision_hash_and_choice_shape():
    from pydantic import ValidationError
    from loveca.simulation.effect_candidates import _live_start_waiting_nine_live_top
    raw = _raw()
    row = {k: raw[k] for k in ["card_code", "text_revision_id", "raw_text_hash"]}
    row["raw_effect_text_ja"] = raw["label_ja"]
    assert _live_start_waiting_nine_live_top(row)
    for key in row:
        bad = dict(row)
        bad[key] = 0 if key == "text_revision_id" else "WRONG"
        assert _live_start_waiting_nine_live_top(bad) is None
    for key, value in [("maximum", 4), ("card_type", "member"), ("target_player", "opponent"), ("requires_order", False)]:
        bad = deepcopy(raw)
        bad["choice"][key] = value
        with pytest.raises(ValidationError):
            EffectDefinition.model_validate(bad)


@pytest.mark.parametrize("field,value", [("turn_number", True), ("turn_number", -1), ("performance_player_id", "player_2"), ("trigger", "member_played"), ("stage", "after_cost")])
def test_invalid_original_live_start_context_atomic(field, value):
    current = _begin(_state()).state
    inv = current.pending_effects[0]
    if field == "trigger":
        inv.trigger_event = value
    elif field == "stage":
        inv.resolution_stage = value
    else:
        inv.trigger_data[field] = value
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        apply_action(current, _resolve(current, ["waiting-0"]))
    assert match_state_hash(current) == before
