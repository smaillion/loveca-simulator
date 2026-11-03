import hashlib
import json

import pytest

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.engine import IllegalActionError, StaleRevisionError, generate_legal_actions
from loveca.simulation.models import ActionRequest, MatchState, SpecialBladeHeart
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from test_mulligan_boundary import _replay
from test_performance_yell_boundary import _fixture, _privacy


CASES = {"none": (0, 0, 0), "draw": (1, 0, 0), "draw2": (2, 0, 0),
         "score": (0, 2, 0), "all": (0, 0, 1), "combined": (2, 2, 2), "unmet": (1, 2, 1)}


def _setup(tmp_path, first, case, *, legacy=False):
    _, state = _fixture(tmp_path / "base", first, "live", "mixed")
    state.phase = "yell_first"
    state.live_choice_guard_policy = None if legacy else "require_resolution_v1"
    if legacy:
        state.live_heart_allocation_policy = None
        state.attached_member_departure_policy = None
    player = state.players[first]
    live = player.live_area[0]
    state.cards[live].face_up = True
    draws, score, wild = CASES[case]
    if wild:
        state.cards[live].card.required_hearts = {"green": 3 if case == "unmet" else 1}
    for kind, count in (("draw", draws), ("score", score), ("all_color", wild)):
        for index in range(count):
            state.cards[player.main_deck[index]].card.special_blade_hearts.append(
                SpecialBladeHeart(effect_type=kind, value=1, source_alt=f"AUDIT-{kind}-1"))
    # Icons on the subsequent drawn cards must not be treated as Yell results.
    for item in player.main_deck[5:7]:
        state.cards[item].card.special_blade_hearts = [
            SpecialBladeHeart(effect_type=kind, value=99, source_alt="AUDIT-NOT-YELL")
            for kind in ("draw", "score", "all_color")]
    state = MatchState.model_validate(state.model_dump())
    repo = MatchRepository(tmp_path / "icons.sqlite3")
    repo.create_match(state, card_database_path=tmp_path / "base/base/setup/cards.sqlite3")
    return repo, state


def _action(state):
    if state.pending_choice:
        return ActionRequest(action_type="resolve_live_requirements", player_id=state.active_player_id,
                             expected_revision=state.revision,
                             payload={"live_instance_ids": list(state.players[state.active_player_id].live_area)})
    return ActionRequest(action_type="advance_phase", player_id=state.active_player_id,
                         expected_revision=state.revision, payload={})


def _choose(controller, state):
    legal = generate_legal_actions(state)
    decision = controller.choose_action(state, legal, controlled_player_ids=set(state.players))
    assert isinstance(decision, SimpleAIDecision)
    changed = state.model_copy(deep=True)
    for owner, player in changed.players.items():
        hidden = player.main_deck + player.energy_deck
        if owner != state.active_player_id:
            hidden += player.hand + [item for item in player.live_area if not state.cards[item].face_up]
        for item in hidden:
            changed.cards[item].card = changed.cards[item].card.model_copy(update={"name_ja": "HIDDEN", "score": 999})
    digest = match_state_hash(changed)
    other = controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids=set(changed.players))
    assert isinstance(other, SimpleAIDecision) and other.action.model_dump() == decision.action.model_dump()
    assert match_state_hash(changed) == digest
    return decision.action


def _walk(repo, initial, case, controller=None):
    owner = initial.active_player_id
    old = initial.players[owner]
    draws, score, wild = CASES[case]
    revealed, drawn = old.main_deck[:5], old.main_deck[5:5 + draws]
    expected_results = [{"card_instance_id": item, "effect_type": icon.effect_type,
                         "value": icon.value, "source_alt": icon.source_alt}
                        for item in revealed for icon in initial.cards[item].card.special_blade_hearts]
    state = initial
    for step in range(2 if wild else 1):
        digest = match_state_hash(state)
        action = _choose(controller, state) if controller else _action(state)
        assert action.action_type == ("advance_phase" if step == 0 else "resolve_live_requirements")
        result = repo.apply(state.match_id, action)
        assert match_state_hash(state) == digest
        after = result.state
        player = after.players[owner]
        live_result = player.live_result
        assert player.main_deck == old.main_deck[5 + draws:]
        assert player.hand == old.hand + drawn
        assert player.resolution_area == old.resolution_area + revealed
        assert player.member_area == old.member_area and player.energy_area == old.energy_area
        assert after.players[initial.second_player_id] == initial.players[initial.second_player_id]
        expected_cards = {item: card.model_copy(deep=True) for item, card in initial.cards.items()}
        for item in revealed + drawn:
            expected_cards[item].face_up = True
        assert after.cards == expected_cards
        assert live_result.blade_count == 5 and live_result.revealed_instance_ids == revealed
        assert live_result.draw_count == draws
        assert live_result.score_bonus == score
        assert live_result.all_color_hearts == wild
        assert live_result.special_blade_heart_results == expected_results
        assert live_result.member_hearts == {"red": 2, "blue": 1}
        assert live_result.yell_hearts == {"red": 3, "blue": 2}
        assert live_result.available_hearts == {"red": 5, "blue": 3}
        events = result.events[1:] if controller else result.events
        if controller:
            assert result.events[0].event_type == "ai_action_selected"
        if step == 0:
            types = (["cards_drawn"] if draws else []) + ["yell_completed"]
            if not wild:
                types += ["live_requirements_resolved", "phase_changed"]
            assert [e.event_type for e in events] == types
            if draws:
                assert events[0].data == {"instance_ids": drawn, "reason": "special_blade_heart_draw"}
        else:
            assert [e.event_type for e in events] == ["live_requirements_resolved", "phase_changed"]
        if wild and step == 0:
            assert after.phase == "yell_first" and after.active_player_id == owner
            assert after.pending_choice.choice_type == "live_requirements"
            assert after.pending_choice.options["live_instance_ids"] == old.live_area
            assert live_result.live_allocations == [] and live_result.total_score == 0
            assert player.live_area == old.live_area and player.waiting_room == old.waiting_room
        else:
            passed = case != "unmet"
            assert after.pending_choice is None and after.phase == "performance_second"
            assert after.active_player_id == initial.second_player_id
            assert live_result.requirements_satisfied is passed
            assert live_result.base_score == (6 if passed else 0)
            assert live_result.total_score == (6 + score if passed else 0)
            allocation, = live_result.live_allocations
            assert allocation["all_color_hearts_used"] == (1 if wild else 0)
            assert allocation["remaining_all_color_hearts"] == max(0, wild - 1)
            assert allocation["missing_hearts"] == ({} if passed else {"green": 2})
            assert player.live_area == (old.live_area if passed else [])
            assert player.waiting_room == old.waiting_room + ([] if passed else old.live_area)
        assert after.pending_effects == [] and after.turn_number == initial.turn_number
        assert after.revision == state.revision + 1
        _privacy(result)
        repo = MatchRepository(repo.path)
        assert repo.get_state(after.match_id) == after
        _replay(repo, after)
        state = after
    return state


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("case", list(CASES))
def test_special_yell_icons_draw_after_reveal_and_resume_sql(tmp_path, first, case):
    repo, state = _setup(tmp_path, first, case)
    _walk(repo, state, case)


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("invalid", ["wrong_player", "stale", "empty", "duplicate", "foreign", "advance", "anonymous_advance"])
def test_all_heart_pending_choice_rejects_without_sql_mutation(tmp_path, first, invalid):
    repo, state = _setup(tmp_path, first, "combined")
    state = repo.apply(state.match_id, _action(state)).state
    action = _action(state)
    error = IllegalActionError
    if invalid == "wrong_player":
        action.player_id = state.second_player_id
    elif invalid == "stale":
        action.expected_revision -= 1
        error = StaleRevisionError
    elif invalid in {"advance", "anonymous_advance"}:
        action.action_type = "advance_phase"
        action.payload = {}
        if invalid == "anonymous_advance":
            action.player_id = None
    else:
        action.payload["live_instance_ids"] = {"empty": [], "duplicate": state.players[first].live_area * 2,
                                               "foreign": state.players[state.second_player_id].live_area}[invalid]
    before = repo.replay(state.match_id)
    with pytest.raises(error):
        repo.apply(state.match_id, action)
    assert MatchRepository(repo.path).replay(state.match_id) == before


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_special_yell_and_all_choice_use_private_projection(tmp_path, first, policy):
    repo, state = _setup(tmp_path, first, "combined")
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    _walk(repo, state, "combined", controller)


@pytest.mark.parametrize("first,state_hash,event_hash", [
    ("player_1", "55a70d5e668d66e844a4a4f378501107f2ffaee06280df87643c0ec92f70c899", "1dda1b47d7965cb3385e625c1bb93b9c5b19e2491b2fc43232713e81ee63a41b"),
    ("player_2", "b3f8ad7482a5b6861cedff8ebd04f26ba4d4fd3b044ef4f3b4496e9d02809904", "d6c106fee9476b6d8b9d15ccb0f367970d5e1002f8d9f02a8614b192ef093634"),
])
def test_legacy_repeat_yell_keeps_prechange_hashes_and_replay(tmp_path, first, state_hash, event_hash):
    repo, state = _setup(tmp_path, first, "combined", legacy=True)
    result = repo.apply(state.match_id, _action(state))
    repeat = _action(state).model_copy(update={"expected_revision": result.state.revision})
    result = repo.apply(state.match_id, repeat)
    assert "live_choice_guard_policy" not in result.state.model_dump()
    assert match_state_hash(result.state) == state_hash
    assert hashlib.sha256(json.dumps([e.model_dump() for e in result.events], ensure_ascii=False, sort_keys=True).encode()).hexdigest() == event_hash
    _replay(repo, result.state)


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("anonymous", [False, True])
def test_pending_success_live_cannot_repeat_judgment(tmp_path, first, anonymous):
    from test_next_first_player_boundary import _state, _repo, judgment_action

    state = _state(first, (None, 2), choice=True)
    state.live_choice_guard_policy = "require_resolution_v1"
    repo = _repo(tmp_path, state)
    state = repo.apply(state.match_id, judgment_action(state)).state
    assert state.pending_choice.choice_type == "success_live"
    digest = match_state_hash(state)
    before = repo.replay(state.match_id)
    with pytest.raises(IllegalActionError, match="pending Live choice"):
        repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id=None if anonymous else state.active_player_id,
                                                expected_revision=state.revision, payload={}))
    assert match_state_hash(state) == digest
    assert MatchRepository(repo.path).replay(state.match_id) == before
    chosen = state.pending_choice.options["card_instance_ids"][0]
    result = repo.apply(state.match_id, ActionRequest(action_type="resolve_live_requirements",
                       player_id=state.active_player_id, expected_revision=state.revision,
                       payload={"success_live_instance_id": chosen}))
    assert result.state.pending_choice is None and result.state.phase == "turn_complete"
    assert result.state.players[state.active_player_id].success_live_area == [chosen]
    _replay(repo, result.state)


@pytest.mark.parametrize("value", [True, 1, {}, "unknown"])
def test_unknown_live_choice_guard_policy_rejected(value):
    from loveca.simulation.models import PlayerState
    with pytest.raises(ValueError):
        MatchState(match_id="invalid", seed=1, players={"player_1": PlayerState(player_id="player_1", name="A")},
                   cards={}, live_choice_guard_policy=value)


@pytest.mark.parametrize("hosted", [False, True])
def test_new_local_and_room_match_enable_live_choice_guard(tmp_path, hosted):
    from test_webapp import SAMPLE_DECK, _client

    client = _client(tmp_path)
    deck = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))
    if hosted:
        room = client.post("/api/rooms", json={"player_name": "A", "deck": deck, "seed": 1})
        assert room.status_code == 200
        response = client.post(f"/api/rooms/{room.json()['room_code']}/join", json={"player_name": "B", "deck": deck})
        assert response.status_code == 200
        raw = response.json()["match"]["state"]
    else:
        response = client.post("/api/matches", json={"player_1": {"name": "A", "deck": deck},
                                                    "player_2": {"name": "B", "deck": deck}, "seed": 1})
        assert response.status_code == 200
        raw = response.json()["state"]
    assert raw["live_choice_guard_policy"] == "require_resolution_v1"
    assert raw["live_heart_allocation_policy"] == "preserve_feasibility_v1"
    assert raw["attached_member_departure_policy"] == "clear_target_modifiers_v1"
