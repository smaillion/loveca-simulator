from contextlib import nullcontext
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_all_active_live_requirement_boundary import _exclusive
from test_mirakura_front_position_boundary import _swap_roles
from test_nijigasaki_inspection import _state as _base_state

from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, LivePerformanceResult
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!S-PR-046"
EFFECT = CODE + ":1"
OP = "draw_if_opponent_current_yell_live"
RULE_REFERENCE_IDS = ("4.1.4", "8.4.4", "8.4.5", "9.6.2.4.2", "9.7.7", "10.2.2.1", "11.6.2")


@lru_cache
def _raw():
    candidate = next((c for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True) if c.effect_id == EFFECT), None)
    return candidate.to_registry_entry() if candidate else next(e.model_dump(mode="json") for e in load_effect_registry().effects if e.effect_id == EFFECT)


def _state(*, count=1, two=False, control=False, legacy=False):
    state = _base_state(CODE)
    raw = deepcopy(_raw())
    if legacy:
        raw.update(choice=None, actions=[{"action_type": "manual_resolution"}], duration="live",
            execution_mode="manual_resolution", simulation_support="manual_resolution", review_status="parsed_draft")
    effect = EffectDefinition.model_validate(raw)
    state.effect_definitions = {EFFECT: effect}
    for instance in state.cards.values():
        instance.card.effect_ids = []
    state.cards["source-live"].card.effect_ids = [EFFECT]
    p, q = state.players["player_1"], state.players["player_2"]
    p.hand, p.main_deck = ["cost"], ["good-member", "good-live", "wrong-work", "tail"]
    p.member_area = {"left": None, "center": "source-live", "right": None}
    p.live_area = ["deck-live-1"]
    state.cards["source-2"] = state.cards["source-live"].model_copy(update={"instance_id": "source-2"}, deep=True)
    if two:
        p.member_area["left"] = "source-2"
    for key, template in [("op-live", "deck-live-2"), ("op-yell-0", "deck-live-2"), ("op-yell-1", "deck-live-2"), ("op-other", "good-member"), ("not-yell", "deck-live-2")]:
        state.cards[key] = state.cards[template].model_copy(update={"instance_id": key, "owner_id": "player_2", "face_up": True}, deep=True)
        state.cards[key].card.effect_ids = []
    q.live_area = ["op-live"]
    original = [f"op-yell-{i}" for i in range(count)] + ["op-other"]
    q.resolution_area = original + ["not-yell"]
    q.live_result = LivePerformanceResult(revealed_instance_ids=original, remaining_yell_instance_ids=list(original), yell_tracking_turn=state.turn_number)
    state.phase, state.active_player_id = "live_judgment", None
    state.effect_order_policy = "ap_nap_player_choice"
    if control:
        audit = deepcopy(raw)
        audit.update(effect_id="CONTROL", choice=None, actions=[{"action_type": "manual_resolution"}], execution_mode="manual_resolution", simulation_support="manual_resolution", review_status="parsed_draft")
        state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(audit)
        state.cards["source-live"].card.effect_ids.append("CONTROL")
    _exclusive(state)
    return state


def _begin(state):
    return apply_action(state, ActionRequest(action_type="advance_phase", expected_revision=state.revision))


def _events(result):
    return [e.data for e in result.events if e.event_type == "effect_opponent_yell_live_draw_resolved"]


def _resolve(state, **extra):
    inv = next(i for i in state.pending_effects if i.effect_id == EFFECT)
    return ActionRequest(action_type="resolve_effect", player_id=inv.player_id, expected_revision=state.revision,
        payload={"invocation_id": inv.invocation_id, **extra})


def test_native_live_success_opponent_yell_draw_red():
    result = _begin(_state())
    assert result.state.effect_definitions[EFFECT].simulation_support == "test_validated_executable"
    assert _events(result)[0]["condition_met"] is True
    assert _events(result)[0]["drawn_count"] == 1


def _repo(state, tmp_path):
    repo = MatchRepository(tmp_path / "audit.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    return repo


def _replay(repo, state):
    _exclusive(state)
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == state.model_dump(mode="json")


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("count", [0, 1, 2])
def test_two_sources_one_draw_each_current_opponent_only_sql(tmp_path, owner, first, count):
    state = _state(count=count, two=True)
    if owner == "player_2":
        state = _swap_roles(state)
    state.first_player_id, state.second_player_id = first, "player_2" if first == "player_1" else "player_1"
    repo = _repo(state, tmp_path)
    started = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", expected_revision=state.revision)).state
    assert len([i for i in started.pending_effects if i.effect_id == EFFECT]) == 2
    result = repo.apply(state.match_id, _resolve(started))
    assert len(_events(result)) == 2
    assert all(e["opponent_yell_live_count"] == count and e["drawn_count"] == int(count > 0) for e in _events(result))
    assert len(result.state.players[owner].hand) == 1 + 2 * int(count > 0)
    _replay(repo, result.state)


def _manual(state, changes, effect_id="CONTROL"):
    inv = next(i for i in state.pending_effects if i.effect_id == effect_id)
    return ActionRequest(action_type="manual_adjustment", player_id=inv.player_id, expected_revision=state.revision,
        payload={"reason": "AUDIT CONTROL, not a production ability", "source_invocation_id": inv.invocation_id,
            "source_effect_id": inv.effect_id, "source_card_instance_id": inv.source_card_instance_id,
            "adjustments": [{"target_player_id": inv.player_id, **c} for c in changes]})


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("move", ["hand", "deck", "return", "same_stage"])
def test_native_control_source_departure_does_not_cancel_sql(tmp_path, owner, move):
    state = _state(two=True, control=True)
    if owner == "player_2":
        state = _swap_roles(state)
    repo = _repo(state, tmp_path)
    started = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", expected_revision=state.revision)).state
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live",
        "to_zone": "main_deck" if move == "deck" else "member_right" if move == "same_stage" else "hand"}]
    if move == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_right"})
    moved = repo.apply(state.match_id, _manual(started, changes)).state
    result = repo.apply(state.match_id, _resolve(moved))
    assert len(_events(result)) == 2 and all(e["drawn_count"] == 1 for e in _events(result))
    other = "player_2" if owner == "player_1" else "player_1"
    for viewer in [owner, other]:
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        if move == "deck" or (move == "hand" and viewer != owner):
            assert "source-live" not in payload["state"]["cards"]
        assert ("good-member" in payload["state"]["cards"]) is (viewer == owner)
        assert "tail" not in payload["state"]["cards"]
    _replay(repo, result.state)


@pytest.mark.parametrize("move,expected", [("out", 0), ("return", 0), ("same", 1), ("one_of_two", 1), ("new_object", 0)])
def test_q253_q107_current_original_objects_not_permanent_history_sql(tmp_path, move, expected):
    state = _state(count=2 if move == "one_of_two" else 1, two=True, control=True)
    repo = _repo(state, tmp_path)
    started = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", expected_revision=state.revision)).state
    changes = [{"adjustment_type": "move_card", "target_player_id": "player_2", "target_card_instance_id": "op-yell-0",
        "to_zone": "resolution_area" if move == "same" else "hand"}]
    if move == "return":
        changes.append({"adjustment_type": "move_card", "target_player_id": "player_2", "target_card_instance_id": "op-yell-0", "to_zone": "resolution_area"})
    if move == "new_object":
        changes.append({"adjustment_type": "move_card", "target_player_id": "player_2", "target_card_instance_id": "op-yell-1", "to_zone": "resolution_area"})
    moved = repo.apply(state.match_id, _manual(started, changes)).state
    result = repo.apply(state.match_id, _resolve(moved))
    assert all(e["opponent_yell_live_count"] == expected and e["condition_met"] is bool(expected) for e in _events(result))
    _replay(repo, result.state)


@pytest.mark.parametrize("cards,waiting", [(0, False), (0, True), (1, False), (1, True)])
def test_possible_draw_short_empty_deck_and_post_draw_refresh_sql(tmp_path, cards, waiting):
    state = _state()
    p = state.players["player_1"]
    p.main_deck = ["good-member"][:cards]
    p.waiting_room = ["good-live"] if waiting else []
    repo = _repo(state, tmp_path)
    result = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", expected_revision=state.revision))
    assert _events(result)[0]["drawn_count"] == int(bool(cards or waiting))
    if waiting:
        assert not result.state.players["player_1"].waiting_room
    _replay(repo, result.state)


@pytest.mark.parametrize("bad", [None, -1, True])
def test_missing_old_or_boolean_yell_round_is_atomic(bad):
    state = _begin(_state(two=True)).state
    state.players["player_2"].live_result.yell_tracking_turn = bad
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError, match="current-turn opponent Yell"):
        apply_action(state, _resolve(state))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("bad", ["trigger_turn", "phase", "owner_success", "missing_objects", "not_started"])
def test_invalid_live_context_is_atomic(bad):
    state = _begin(_state(two=True)).state
    if bad == "trigger_turn":
        state.pending_effects[0].trigger_data["turn_number"] = state.turn_number - 1
    elif bad == "phase":
        state.phase = "first_main"
    elif bad == "owner_success":
        state.live_success_player_ids = []
    elif bad == "not_started":
        state.live_success_effects_queued = False
    else:
        state.players["player_2"].live_result.remaining_yell_instance_ids = None
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("ids", [["op-yell-0", "op-yell-0"], [True]])
def test_malformed_tracking_rejected_without_draw(ids):
    state = _begin(_state(two=True)).state
    state.players["player_2"].live_result.remaining_yell_instance_ids = ids
    with pytest.warns(UserWarning, match="Pydantic serializer warnings") if ids == [True] else nullcontext():
        before = match_state_hash(state)
        with pytest.raises(IllegalActionError, match="tracking is invalid"):
            apply_action(state, _resolve(state))
        assert match_state_hash(state) == before


def test_opponent_failed_or_departed_live_does_not_remove_current_yell_condition():
    state = _state()
    state.players["player_2"].live_area = []
    state.players["player_2"].live_result.requirements_satisfied = False
    result = _begin(state)
    assert _events(result)[0]["condition_met"] is True
    assert _events(result)[0]["drawn_count"] == 1


@pytest.mark.parametrize("zone", ["resolution_area", "success_live_area"])
def test_own_yell_and_opponent_past_success_are_not_current_opponent_yell(zone):
    state = _state(count=0)
    if zone == "resolution_area":
        p = state.players["player_1"]
        p.main_deck.remove("good-live")
        p.resolution_area = ["good-live"]
        p.live_result = LivePerformanceResult(revealed_instance_ids=["good-live"], remaining_yell_instance_ids=["good-live"], yell_tracking_turn=state.turn_number)
    else:
        q = state.players["player_2"]
        q.success_live_area = ["op-yell-1"]
    _exclusive(state)
    result = _begin(state)
    assert _events(result)[0]["condition_met"] is False
    assert _events(result)[0]["drawn_count"] == 0


@pytest.mark.parametrize("extra", [{"selected_card_instance_ids": ["cost"]}, {"energy_instance_ids": ["energy-0"]}, {"selected_branch": "draw"}, {"target_player_id": "player_2"}, {"selected_color_slot": "heart05"}])
def test_extra_choice_cost_and_non_owner_rejected(extra):
    state = _begin(_state(two=True)).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, **extra))
    wrong = _resolve(state)
    wrong.player_id = "player_2"
    with pytest.raises(IllegalActionError):
        apply_action(state, wrong)
    assert match_state_hash(state) == before


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("positive", [False, True])
def test_four_ai_two_sources_hidden_identity_invariance(policy, owner, positive):
    from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
    state = _state(two=True, count=int(positive))
    if owner == "player_2":
        state = _swap_roles(state)
    state = _begin(state).state
    changed = state.model_copy(deep=True)
    for key in ["good-member", "good-live", "wrong-work", "tail", "cost", "opponent-secret"]:
        instance = changed.cards.pop(key)
        replacement = "HIDDEN-" + key
        instance.instance_id = replacement
        instance.card.name_ja = instance.card.card_code = "HIDDEN-IDENTITY"
        instance.card.blade = 99
        changed.cards[replacement] = instance
        for p in changed.players.values():
            for zone in ["main_deck", "hand"]:
                setattr(p, zone, [replacement if i == key else i for i in getattr(p, zone)])
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner}).action == decision.action
    assert match_state_hash(state) == before
    result = apply_action(state, decision.action)
    assert len(_events(result)) == 2 and all(e["drawn_count"] == int(positive) for e in _events(result))


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("skip", [False, True])
def test_native_performance_yell_new_old_and_no_opponent_live_sql(tmp_path, legacy, skip):
    state = _state(legacy=legacy)
    p, q = state.players["player_1"], state.players["player_2"]
    p.live_result = LivePerformanceResult()
    q.live_result = LivePerformanceResult()
    # Isolate the native phase sequence, not a complete official-card game.
    for key in [*p.live_area, *q.live_area]:
        state.cards[key].card.required_hearts = {}
    p.resolution_area, q.resolution_area = [], []
    q.member_area["center"] = "op-other"
    state.cards["op-other"].card.blade = 1
    q.main_deck = ["op-yell-0", "op-yell-1"]
    if skip:
        q.live_area = []
    state.phase, state.active_player_id = "performance_first", "player_1"
    _exclusive(state)
    repo = _repo(state, tmp_path)
    current = state
    seen = []
    for _ in range(15):
        result = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id=current.active_player_id, expected_revision=current.revision))
        current = result.state
        seen += _events(result)
        if current.live_success_effects_queued or seen:
            break
    assert current.players["player_2"].live_result.yell_tracking_turn == (None if legacy else state.turn_number)
    if legacy:
        assert "yell_tracking_turn" not in current.players["player_2"].live_result.model_dump(mode="json")
        final = repo.apply(state.match_id, _manual(current, [{"adjustment_type": "set_flag", "flag": "AUDIT-legacy", "duration": "turn"}], EFFECT))
        assert not _events(final)
        current = final.state
    else:
        assert seen and seen[0]["condition_met"] is (not skip)
    _replay(repo, current)


@pytest.mark.parametrize("field,value", [("amount", 2), ("target", "opponent"), ("amount_source", "own_hand_size"), ("branch", "other"), ("is_optional", True), ("timing", "live_start"), ("duration", "live"), ("cost", [{"action_type": "draw_card", "amount": 1}])])
def test_bounded_snapshot_rejects_widening(field, value):
    raw = deepcopy(_raw())
    if field in {"amount", "target", "amount_source", "branch"}:
        raw["actions"][0][field] = value
    else:
        raw[field] = value
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


def test_exact_generator_identity_and_repeat_revision_atomic():
    from loveca.simulation.effect_candidates import _live_success_opponent_yell_live_draw
    from loveca.simulation.engine import StaleRevisionError
    raw = _raw()
    assert (raw["text_revision_id"], raw["raw_text_hash"]) == (1219, "a8e630b24ea2d9956c6e64421ef222f7f627a68a36eb7ee148b9600fdbb5c97e")
    row = {k: raw[k] for k in ["card_code", "text_revision_id", "raw_text_hash"]}
    row["raw_effect_text_ja"] = raw["label_ja"]
    assert _live_success_opponent_yell_live_draw(row)
    for key in row:
        bad = dict(row)
        bad[key] = 0 if key == "text_revision_id" else "WRONG"
        assert _live_success_opponent_yell_live_draw(bad) is None
    state = _begin(_state(two=True)).state
    action = _resolve(state)
    result = apply_action(state, action)
    before = match_state_hash(result.state)
    with pytest.raises(StaleRevisionError):
        apply_action(result.state, action)
    action.expected_revision = result.state.revision
    with pytest.raises(IllegalActionError):
        apply_action(result.state, action)
    assert match_state_hash(result.state) == before

