import json
from collections import Counter

import pytest

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.engine import IllegalActionError, StaleRevisionError, generate_legal_actions
from loveca.simulation.models import ActionRequest, MatchState
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload
from test_mulligan_boundary import _replay
from test_normal_phase_boundary import _constructed


def _fixture(tmp_path, first, case="mixed", orientation="mixed"):
    _, state = _constructed(tmp_path / "base", first, stage_count=3)
    state.phase = "performance_first"
    player = state.players[first]
    # Fixed no-ability snapshots isolate ordinary Blade and colored Heart rules.
    for index, item in enumerate(player.member_area.values()):
        state.cards[item].card = state.cards[item].card.model_copy(
            update={"blade": (1, 2, 4)[index], "basic_hearts": {"blue" if index == 1 else "red": 1}})
        active = orientation == "all_active" or (orientation == "mixed" and index != 1)
        state.cards[item].orientation = "active" if active else "wait"
    live = next(item for item in player.main_deck if state.cards[item].card.card_type == "live")
    decoys = [item for item in player.main_deck if state.cards[item].card.card_type == "member"][:2]
    player.live_area = {"empty": [], "decoys": decoys, "live": [live],
                        "mixed": [decoys[0], live, decoys[1]], "unmet": [live]}[case]
    state.cards[live].card = state.cards[live].card.model_copy(
        update={"required_hearts": {"red": 99} if case == "unmet" else {"red": 2, "blue": 1}, "score": 6})
    for item in player.live_area:
        player.main_deck.remove(item)
        state.cards[item].face_up = False
    for index, item in enumerate(player.main_deck):
        state.cards[item].card = state.cards[item].card.model_copy(
            update={"blade_heart_color_slot": "red" if index % 2 == 0 else "blue", "special_blade_hearts": []})
    other = state.players[state.second_player_id]
    other_live = next(item for item in other.main_deck if state.cards[item].card.card_type == "live")
    other.main_deck.remove(other_live)
    other.live_area = [other_live]
    state.cards[other_live].face_up = False
    state = MatchState.model_validate(state.model_dump())
    repo = MatchRepository(tmp_path / "performance.sqlite3")
    repo.create_match(state, card_database_path=tmp_path / "base/setup/cards.sqlite3")
    return repo, state


def _action(state):
    return ActionRequest(action_type="advance_phase", player_id=state.active_player_id,
                         expected_revision=state.revision, payload={})


def _privacy(result):
    state = result.state
    for viewer in state.players:
        hidden = []
        for owner, player in state.players.items():
            hidden.extend(player.main_deck + player.energy_deck)
            if owner != viewer:
                hidden.extend(player.hand + [item for item in player.live_area if not state.cards[item].face_up])
        payload = _match_state_payload(state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        assert all(json.dumps(item) not in json.dumps(payload) for item in hidden)
        for player in state.players.values():
            assert all(item in payload["state"]["cards"] for item in player.resolution_area)


def _assert_step(before, result, *, ai=False):
    state = result.state
    owner, other = before.active_player_id, before.second_player_id
    previous, player = before.players[owner], state.players[owner]
    expected = previous.model_copy(deep=True)
    expected_cards = {item: card.model_copy(deep=True) for item, card in before.cards.items()}
    events = result.events
    if ai:
        assert events[0].event_type == "ai_action_selected"
        events = events[1:]
    if before.phase == "performance_first":
        lives = [item for item in previous.live_area if before.cards[item].card.card_type == "live"]
        decoys = [item for item in previous.live_area if item not in lives]
        expected.live_area = lives
        expected.waiting_room.extend(decoys)
        for item in previous.live_area:
            expected_cards[item].face_up = True
        assert state.phase == "yell_first" and state.active_player_id == owner
        assert [event.event_type for event in events] == ["live_cards_revealed", "phase_changed"]
        assert events[0].data == {"live_instance_ids": lives, "non_live_discarded_instance_ids": decoys}
    else:
        assert before.phase == "yell_first"
        count = sum(before.cards[item].card.blade for item in previous.member_area.values()
                    if before.cards[item].orientation == "active") if previous.live_area else 0
        revealed = previous.main_deck[:count]
        expected.main_deck = previous.main_deck[count:]
        expected.resolution_area.extend(revealed)
        for item in revealed:
            expected_cards[item].face_up = True
        live_result = player.live_result
        assert live_result.blade_count == count
        assert live_result.revealed_instance_ids == revealed
        assert live_result.draw_count == live_result.score_bonus == live_result.all_color_hearts == 0
        assert live_result.special_blade_heart_results == [] and live_result.manual_hearts == {}
        if previous.live_area:
            member_hearts = {"red": 2, "blue": 1}
            yell_hearts = dict(Counter(before.cards[item].card.blade_heart_color_slot for item in revealed))
            owned = dict(Counter(member_hearts) + Counter(yell_hearts))
            assert live_result.member_hearts == member_hearts
            assert live_result.yell_hearts == yell_hearts and live_result.available_hearts == owned
            live = previous.live_area[0]
            required = before.cards[live].card.required_hearts
            satisfied = all(owned.get(color, 0) >= number for color, number in required.items())
            assert live_result.requirements_satisfied is satisfied
            assert live_result.base_score == live_result.total_score == (6 if satisfied else 0)
            allocation, = live_result.live_allocations
            assert allocation["live_instance_id"] == live and allocation["required_hearts"] == required
            assert allocation["satisfied"] is satisfied
            assert allocation["consumed_hearts"] == {color: min(owned[color], number) for color, number in required.items()}
            assert allocation["missing_hearts"] == {color: number - owned[color] for color, number in required.items() if number > owned[color]}
            if not satisfied:
                expected.waiting_room.extend(expected.live_area)
                expected.live_area = []
            assert [event.event_type for event in events] == ["yell_completed", "live_requirements_resolved", "phase_changed"]
            assert events[0].data["blade_count"] == events[0].data["raw_blade_count"] == count
            assert events[0].data["revealed_instance_ids"] == revealed
            assert events[0].data["live_owned_hearts"] == owned
        else:
            assert live_result.member_hearts == live_result.yell_hearts == live_result.available_hearts == {}
            assert live_result.requirements_satisfied is False
            assert live_result.live_allocations == []
            assert [event.event_type for event in events] == ["yell_skipped", "phase_changed"]
        assert state.phase == "performance_second" and state.active_player_id == other
    assert player.model_dump(exclude={"live_result"}) == expected.model_dump(exclude={"live_result"})
    assert state.cards == expected_cards
    assert state.players[other] == before.players[other]
    assert state.revision == before.revision + 1 and state.turn_number == before.turn_number
    assert state.pending_choice is None and state.pending_effects == []
    assert events[-1].data == {"phase": state.phase}
    _privacy(result)


def _walk(repo, state, controller=None):
    for _ in range(2):
        before_hash = match_state_hash(state)
        action = _action(state)
        if controller is not None:
            decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids=set(state.players))
            assert isinstance(decision, SimpleAIDecision) and decision.action.action_type == "advance_phase"
            altered = state.model_copy(deep=True)
            for owner, player in altered.players.items():
                hidden = player.main_deck + player.energy_deck
                if owner != state.active_player_id:
                    hidden += player.hand + [item for item in player.live_area if not state.cards[item].face_up]
                for item in hidden:
                    altered.cards[item].card = altered.cards[item].card.model_copy(update={"name_ja": "UNSEEN", "score": 999})
            altered_hash = match_state_hash(altered)
            alternative = controller.choose_action(altered, generate_legal_actions(altered), controlled_player_ids=set(state.players))
            assert isinstance(alternative, SimpleAIDecision)
            assert alternative.action.model_dump() == decision.action.model_dump()
            assert match_state_hash(altered) == altered_hash
            action = decision.action
        result = repo.apply(state.match_id, action)
        assert match_state_hash(state) == before_hash
        _assert_step(state, result, ai=controller is not None)
        state = result.state
        repo = MatchRepository(repo.path)
        assert repo.get_state(state.match_id) == state
        _replay(repo, state)
    return state


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("case", ["empty", "decoys", "live", "mixed", "unmet"])
@pytest.mark.parametrize("orientation", ["all_wait", "mixed", "all_active"])
def test_basic_performance_reveal_active_blade_all_member_hearts_and_sql(tmp_path, first, case, orientation):
    repo, state = _fixture(tmp_path, first, case, orientation)
    _walk(repo, state)


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("step", [0, 1])
@pytest.mark.parametrize("invalid", ["wrong_player", "stale"])
def test_performance_invalid_actions_preserve_sql(tmp_path, first, step, invalid):
    repo, state = _fixture(tmp_path, first)
    if step:
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
    assert MatchRepository(repo.path).replay(state.match_id) == before


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_performance_ignores_hidden_cards_and_replays(tmp_path, first, policy):
    repo, state = _fixture(tmp_path, first)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    _walk(repo, state, controller)
