import hashlib
import json
from pathlib import Path

import pytest

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.engine import IllegalActionError, StaleRevisionError, generate_legal_actions
from loveca.simulation.models import ActionRequest, MatchState
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload
from test_mulligan_boundary import _create, _command, _replay


def _setup(tmp_path, first):
    tmp_path.mkdir(parents=True, exist_ok=True)
    repo, state = _create(tmp_path, first)
    for _ in range(2):
        state = repo.apply(state.match_id, _command(state, [])).state
    assert state.phase == "first_active"
    return repo, state


def _constructed(tmp_path, first, stage_count=3, orientation="wait"):
    _, state = _setup(tmp_path / "setup", first)
    # Isolate basic phase actions, not real card abilities or attached-card rules.
    for card in state.cards.values():
        card.card = card.card.model_copy(update={"effect_ids": []})
    state.effect_definitions = {}
    for player in state.players.values():
        members = [item for item in player.main_deck if state.cards[item].card.card_type == "member"]
        for slot, item in zip(player.member_area, members[:stage_count]):
            player.main_deck.remove(item)
            player.member_area[slot] = item
            state.cards[item].face_up = True
        for item in player.energy_area + members[:stage_count]:
            state.cards[item].orientation = orientation
    state = MatchState.model_validate(state.model_dump())
    repo = MatchRepository(tmp_path / "match.sqlite3")
    repo.create_match(state, card_database_path=tmp_path / "setup/cards.sqlite3")
    return repo, state


def _action(state, kind="advance_phase"):
    return ActionRequest(action_type=kind, player_id=state.active_player_id,
                         expected_revision=state.revision, payload={})


def _private(result):
    state = result.state
    for viewer in state.players:
        hidden = []
        for owner, player in state.players.items():
            hidden.extend(player.main_deck + player.energy_deck)
            if owner != viewer:
                hidden.extend(player.hand)
        payload = _match_state_payload(state, events=result.events, legal_actions=result.legal_actions,
                                       player_id=viewer)
        assert all(json.dumps(item) not in json.dumps(payload) for item in hidden)


def _assert_step(before, result, *, ai=False):
    state = result.state
    events = result.events
    if ai:
        assert events[0].event_type == "ai_action_selected"
        events = events[1:]
    owner = before.active_player_id
    other = next(player for player in state.players if player != owner)
    old, new = before.players[owner], state.players[owner]
    assert state.players[other] == before.players[other]
    assert all(state.cards[item] == card for item, card in before.cards.items() if card.owner_id == other)
    assert state.active_player_id == owner and state.turn_number == before.turn_number
    assert (state.first_player_id, state.second_player_id) == (before.first_player_id, before.second_player_id)
    assert state.revision == before.revision + 1
    assert state.pending_choice is None and not state.pending_effects
    stage = [item for item in old.member_area.values() if item]
    assert new.member_area == old.member_area
    assert new.waiting_room == old.waiting_room
    if before.phase.endswith("_active"):
        assert state.phase == before.phase.replace("_active", "_energy")
        assert new.main_deck == old.main_deck and new.hand == old.hand
        assert new.energy_deck == old.energy_deck and new.energy_area == old.energy_area
        assert all(state.cards[item].orientation == "active" for item in stage + old.energy_area)
        assert [event.event_type for event in events] == ["cards_readied", "phase_changed"]
        assert set(events[0].data["instance_ids"]) == set(stage + old.energy_area)
        assert events[0].data["skipped_instance_ids"] == []
    elif before.phase.endswith("_energy"):
        assert state.phase == before.phase.replace("_energy", "_draw")
        assert new.energy_area == old.energy_area + old.energy_deck[:1]
        assert new.energy_deck == old.energy_deck[1:]
        added = old.energy_deck[0]
        assert state.cards[added].face_up and state.cards[added].orientation == "active"
        assert new.hand == old.hand and new.main_deck == old.main_deck
        assert [event.event_type for event in events] == ["energy_added", "phase_changed"]
        assert events[0].data["instance_ids"] == [added]
        assert events[0].data["reason"] == "energy_phase"
    else:
        assert before.phase.endswith("_draw")
        assert state.phase == before.phase.replace("_draw", "_main")
        assert new.hand == old.hand + old.main_deck[:1]
        assert new.main_deck == old.main_deck[1:]
        assert state.cards[old.main_deck[0]].face_up
        assert new.energy_area == old.energy_area and new.energy_deck == old.energy_deck
        assert [event.event_type for event in events] == ["cards_drawn", "phase_changed"]
        assert events[0].data == {"instance_ids": old.main_deck[:1], "reason": "draw_phase"}
    assert result.events[-1].player_id == owner
    assert result.events[-1].data == {"phase": state.phase}
    _private(result)


def _walk(repo, state, *, controller=None):
    for role in ("first", "second"):
        for step in ("active", "energy", "draw"):
            assert state.phase == f"{role}_{step}"
            before_hash = match_state_hash(state)
            action = _action(state)
            if controller is not None:
                decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids=set(state.players))
                assert isinstance(decision, SimpleAIDecision)
                assert decision.action.action_type == "advance_phase"
                altered = state.model_copy(deep=True)
                for owner, player in altered.players.items():
                    hidden = player.main_deck + player.energy_deck + (player.hand if owner != state.active_player_id else [])
                    for item in hidden:
                        altered.cards[item].card = altered.cards[item].card.model_copy(update={"name_ja": "UNSEEN", "score": 999})
                altered_hash = match_state_hash(altered)
                alternative = controller.choose_action(altered, generate_legal_actions(altered), controlled_player_ids=set(altered.players))
                assert isinstance(alternative, SimpleAIDecision)
                assert alternative.action.model_dump() == decision.action.model_dump()
                assert match_state_hash(altered) == altered_hash
                action = decision.action
            result = repo.apply(state.match_id, action)
            assert match_state_hash(state) == before_hash
            _assert_step(state, result, ai=controller is not None)
            state = result.state
            # Reopen after every real action to exercise persisted phase continuation.
            repo = MatchRepository(repo.path)
            assert repo.get_state(state.match_id) == state
            _replay(repo, state)
        if role == "first":
            state = repo.apply(state.match_id, _action(state, "end_main_phase")).state
            assert state.phase == "second_active" and state.active_player_id == state.second_player_id
    return state


@pytest.mark.parametrize("first", ["player_1", "player_2"])
def test_native_setup_reaches_both_normal_main_phases_in_order(tmp_path, first):
    assert hashlib.sha256(Path("raw_doc/LoveLiveTCG_cr_1.06_260428.pdf").read_bytes()).hexdigest() == "c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485"
    repo, state = _setup(tmp_path, first)
    result = _walk(repo, state)
    for owner, player in result.players.items():
        assert len(player.hand) == 7 and len(player.energy_area) == 4
    assert result.phase == "second_main"


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("stage_count", [0, 1, 3])
@pytest.mark.parametrize("orientation", ["active", "wait"])
def test_basic_normal_phases_ready_only_owner_then_add_top_energy_and_draw(tmp_path, first, stage_count, orientation):
    repo, state = _constructed(tmp_path, first, stage_count, orientation)
    _walk(repo, state)


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("step", range(3))
@pytest.mark.parametrize("invalid", ["wrong_player", "stale"])
def test_normal_phase_invalid_action_preserves_sql_state_and_history(tmp_path, first, step, invalid):
    repo, state = _constructed(tmp_path, first)
    for _ in range(step):
        state = repo.apply(state.match_id, _action(state)).state
    action = _action(state)
    error = IllegalActionError
    if invalid == "wrong_player":
        action.player_id = state.second_player_id
    else:
        action.expected_revision -= 1
        error = StaleRevisionError
    before = repo.replay(state.match_id)
    with pytest.raises(error):
        repo.apply(state.match_id, action)
    assert repo.replay(state.match_id) == before


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_advance_both_normal_phases_without_hidden_card_influence(tmp_path, first, policy):
    repo, state = _constructed(tmp_path, first)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    _walk(repo, state, controller=controller)
