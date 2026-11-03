import hashlib
import json
from pathlib import Path

import pytest

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.engine import IllegalActionError, StaleRevisionError, generate_legal_actions
from loveca.simulation.models import ActionRequest
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.simulation.rulesets import current_ruleset_identity
from loveca.webapp import _match_state_payload
from tools.ai_sandbox.live_judgment_audit import _build_state, _live_instance, judgment_action


CASES = [
    (None, None, ()),
    (2, None, ("first",)),
    (None, 2, ("second",)),
    (2, 2, ("first", "second")),
    (3, 2, ("first",)),
    (2, 3, ("second",)),
]


def _state(first, scores=(None, 2), *, choice=False):
    second = "player_2" if first == "player_1" else "player_1"
    by_player = {first: scores[0], second: scores[1]}
    state = _build_state(first_live_score=by_player["player_1"],
                         second_live_score=by_player["player_2"],
                         first_success_count=0, second_success_count=0, first_effect=None)
    state.match_id = "next-first-" + first
    profile, fingerprint = current_ruleset_identity()
    state.ruleset_id = profile.ruleset_id
    state.ruleset_fingerprint = fingerprint
    state.ruling_pack_version = profile.ruling_pack_version
    state.first_player_id, state.second_player_id = first, second
    state.victory_check_policy = "before_end_expiry_v1"
    state.draw_refresh_policy = "after_each_draw_v1"
    if choice:
        state.cards["extra-live"] = _live_instance("extra-live", second, 1)
        state.players[second].live_area.append("extra-live")
    for owner, player in state.players.items():
        for zone in ("hand", "main_deck"):
            item = f"{owner}-hidden-{zone}"
            state.cards[item] = _live_instance(item, owner, 0)
            state.cards[item].face_up = zone == "hand"
            getattr(player, zone).append(item)
    return state


def _repo(tmp_path, state):
    repository = MatchRepository(tmp_path / "match.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    return repository


def _start(state):
    return ActionRequest(action_type="start_next_turn", player_id=state.next_first_player_id,
                         expected_revision=state.revision, payload={})


def _assert_replay(repository, state):
    replay = repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["metadata"]["ruleset_identity_verified"] is True
    assert replay["final_state"] == state.model_dump()


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("first_score,second_score,moved_roles", CASES)
def test_next_turn_roles_follow_actual_live_placement_sql(tmp_path, first, first_score, second_score, moved_roles):
    # Post-Heart constructed states isolate CR 1.06 8.4.13; no match-point cases.
    assert hashlib.sha256(Path("raw_doc/LoveLiveTCG_cr_1.06_260428.pdf").read_bytes()).hexdigest() == "c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485"
    initial = _state(first, (first_score, second_score))
    second = initial.second_player_id
    roles = {"first": first, "second": second}
    moved = [roles[role] for role in moved_roles]
    expected = moved[0] if len(moved) == 1 else first
    repo = _repo(tmp_path, initial)
    judged = repo.apply(initial.match_id, judgment_action(initial))
    state = judged.state
    assert state.phase == "turn_complete" and state.game_result is None
    assert set(state.success_live_moved_player_ids) == set(moved)
    assert state.next_first_player_id == expected
    assert (state.first_player_id, state.second_player_id) == (first, second)
    for owner, player in state.players.items():
        assert player.success_live_area == ([owner + "-current-live"] if owner in moved else [])
        assert not player.live_area and not player.resolution_area
    completed = next(e for e in judged.events if e.event_type == "turn_completed")
    assert completed.data["next_first_player_id"] == expected
    assert set(completed.data["success_live_moved_player_ids"]) == set(moved)
    assert len(judged.legal_actions) == 1
    assert judged.legal_actions[0].action_type == "start_next_turn"
    assert judged.legal_actions[0].player_id == expected
    _assert_replay(repo, state)
    zones = {owner: player.model_dump() for owner, player in state.players.items()}
    started = repo.apply(state.match_id, _start(state))
    result = started.state
    assert result.phase == "first_active" and result.turn_number == initial.turn_number + 1
    assert result.first_player_id == result.active_player_id == expected
    assert result.second_player_id == next(owner for owner in state.players if owner != expected)
    assert result.next_first_player_id is None and result.live_judgment_summary is None
    assert not result.success_live_moved_player_ids and not result.live_winner_ids
    for owner, player in result.players.items():
        for zone in ("hand", "main_deck", "waiting_room", "success_live_area"):
            assert getattr(player, zone) == zones[owner][zone]
    event = next(e for e in started.events if e.event_type == "turn_started")
    assert event.player_id == expected and event.data["first_player_id"] == expected
    for viewer in result.players:
        other = next(owner for owner in result.players if owner != viewer)
        hidden = result.players[other].hand + result.players[other].main_deck + result.players[viewer].main_deck
        payload = _match_state_payload(result, events=started.events, legal_actions=started.legal_actions, player_id=viewer)
        assert all(json.dumps(item) not in json.dumps(payload) for item in hidden)
    _assert_replay(repo, result)


@pytest.mark.parametrize("first", ["player_1", "player_2"])
def test_next_turn_waits_for_success_live_selection(tmp_path, first):
    state = _state(first, choice=True)
    owner = state.second_player_id
    repo = _repo(tmp_path, state)
    state = repo.apply(state.match_id, judgment_action(state)).state
    assert state.pending_choice is not None and state.pending_choice.choice_type == "success_live"
    assert state.next_first_player_id is None
    assert all(a.action_type != "start_next_turn" for a in generate_legal_actions(state))
    before = repo.replay(state.match_id)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _start(state))
    assert repo.replay(state.match_id) == before
    selected = repo.apply(state.match_id, ActionRequest(action_type="resolve_live_requirements", player_id=owner,
                         expected_revision=state.revision, payload={"success_live_instance_id": "extra-live"}))
    assert selected.state.players[owner].success_live_area == ["extra-live"]
    assert selected.state.next_first_player_id == owner
    started = repo.apply(state.match_id, _start(selected.state))
    assert started.state.first_player_id == owner
    _assert_replay(repo, started.state)


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("invalid", ["stale", "repeat"])
def test_rejected_next_turn_command_preserves_sql(tmp_path, first, invalid):
    state = _state(first)
    repo = _repo(tmp_path, state)
    state = repo.apply(state.match_id, judgment_action(state)).state
    command = _start(state)
    if invalid == "repeat":
        state = repo.apply(state.match_id, command).state
        command = _start(state)
        error = IllegalActionError
    else:
        command = command.model_copy(update={"expected_revision": state.revision - 1})
        error = StaleRevisionError
    before = repo.replay(state.match_id)
    with pytest.raises(error):
        repo.apply(state.match_id, command)
    assert repo.replay(state.match_id) == before


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_policies_start_new_first_players_turn(tmp_path, first, policy):
    initial = _state(first)
    repo = _repo(tmp_path, initial)
    state = repo.apply(initial.match_id, judgment_action(initial)).state
    owner = initial.second_player_id
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    assert decision.action.action_type == "start_next_turn" and decision.action.player_id == owner
    altered = state.model_copy(deep=True)
    for item in altered.players[first].hand + altered.players[first].main_deck:
        altered.cards[item].card = altered.cards[item].card.model_copy(update={"name_ja": "UNSEEN", "score": 999})
    altered_before = match_state_hash(altered)
    alternative = controller.choose_action(altered, generate_legal_actions(altered), controlled_player_ids={owner})
    assert isinstance(alternative, SimpleAIDecision)
    assert alternative.action.model_dump() == decision.action.model_dump()
    assert match_state_hash(state) == before and match_state_hash(altered) == altered_before
    result = repo.apply(state.match_id, decision.action)
    assert result.state.first_player_id == result.state.active_player_id == owner
    assert result.state.phase == "first_active"
    _assert_replay(repo, result.state)
