from itertools import permutations

import pytest

from loveca.simulation.ai import SimpleAIController, SimpleAIPolicy
from loveca.simulation.engine import IllegalActionError, StaleRevisionError
from loveca.simulation.models import ActionRequest, MatchState
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from test_mulligan_boundary import _replay
from test_performance_yell_boundary import _fixture, _privacy
from test_yell_icons_boundary import _choose


ORDERS = [order for count in (2, 3) for order in permutations(range(count))]


def _setup(tmp_path, first, count, passed):
    _, state = _fixture(tmp_path / "base", first, "live", "mixed")
    state.phase = "yell_first"
    state.live_choice_guard_policy = "require_resolution_v1"
    player = state.players[first]
    extra = [item for item in player.main_deck if state.cards[item].card.card_type == "live"][:count - 1]
    assert len(extra) == count - 1
    for item in extra:
        player.main_deck.remove(item)
        player.live_area.append(item)
    requirements = [{"red": 2}, {"red": 2 if passed else 4, "blue": 2}, {"red": 1, "blue": 1}]
    for index, item in enumerate(player.live_area):
        state.cards[item].face_up = True
        state.cards[item].card.required_hearts = requirements[index]
        state.cards[item].card.score = index + 2
    for index, item in enumerate(player.main_deck):
        state.cards[item].card.blade_heart_color_slot = "red" if index % 2 == 0 else "blue"
        state.cards[item].card.special_blade_hearts = []
    state = MatchState.model_validate(state.model_dump())
    repo = MatchRepository(tmp_path / "multi.sqlite3")
    repo.create_match(state, card_database_path=tmp_path / "base/base/setup/cards.sqlite3")
    return repo, state


def _action(state, order=None):
    return ActionRequest(action_type="advance_phase" if order is None else "resolve_live_requirements",
                         player_id=state.active_player_id, expected_revision=state.revision,
                         payload={} if order is None else {"live_instance_ids": order})


def _allocation_expectation(initial, owner, ordered):
    # Ordinary colored Hearts only: prefix sums expose shared-pool reuse errors.
    available = {"red": 5, "blue": 3}
    spent = {"red": 0, "blue": 0}
    allocations = []
    for item in ordered:
        required = initial.cards[item].card.required_hearts
        assert all(amount <= available[color] for color, amount in required.items())
        missing = {color: spent[color] + amount - available[color]
                   for color, amount in required.items() if spent[color] + amount > available[color]}
        consumed = {color: amount - missing.get(color, 0) for color, amount in required.items()}
        for color, amount in consumed.items():
            spent[color] += amount
        allocations.append({"live_instance_id": item, "required_hearts": required,
                            "consumed_hearts": consumed, "all_color_hearts_used": 0,
                            "missing_hearts": missing,
                            "remaining_hearts": {color: amount - spent[color] for color, amount in available.items()
                                                 if amount > spent[color]},
                            "remaining_all_color_hearts": 0, "satisfied": not missing})
        if missing:
            break
    return allocations


def _walk(repo, initial, passed, order=None, controller=None):
    owner = initial.active_player_id
    old = initial.players[owner]
    revealed = old.main_deck[:5]
    state = initial
    for step in range(2):
        ordered = [old.live_area[index] for index in order] if order is not None else list(old.live_area)
        action = _choose(controller, state) if controller else _action(state, ordered if step else None)
        assert action.action_type == ("resolve_live_requirements" if step else "advance_phase")
        if step:
            ordered = action.payload["live_instance_ids"]
            assert sorted(ordered) == sorted(old.live_area)
        digest = match_state_hash(state)
        result = repo.apply(state.match_id, action)
        assert match_state_hash(state) == digest
        after = result.state
        player = after.players[owner]
        expected = old.model_copy(deep=True)
        expected.main_deck = old.main_deck[5:]
        expected.resolution_area = old.resolution_area + revealed
        expected.live_result = player.live_result
        if step and not passed:
            expected.live_area = []
            expected.waiting_room = old.waiting_room + old.live_area
        assert player == expected
        assert after.players[initial.second_player_id] == initial.players[initial.second_player_id]
        expected_cards = {item: card.model_copy(deep=True) for item, card in initial.cards.items()}
        for item in revealed:
            expected_cards[item].face_up = True
        assert after.cards == expected_cards
        live = player.live_result
        assert live.blade_count == 5 and live.revealed_instance_ids == revealed
        assert live.member_hearts == {"red": 2, "blue": 1}
        assert live.yell_hearts == {"red": 3, "blue": 2}
        assert live.available_hearts == {"red": 5, "blue": 3}
        assert live.all_color_hearts == live.draw_count == live.score_bonus == 0
        assert live.special_blade_heart_results == []
        events = result.events[1:] if controller else result.events
        if controller:
            assert result.events[0].event_type == "ai_action_selected"
        if not step:
            assert [event.event_type for event in events] == ["yell_completed"]
            assert after.phase == "yell_first" and after.active_player_id == owner
            assert after.pending_choice.choice_type == "live_requirements"
            assert after.pending_choice.player_id == owner
            assert after.pending_choice.options["live_instance_ids"] == old.live_area
            assert live.live_allocations == [] and live.total_score == live.base_score == 0
        else:
            assert after.pending_choice is None and after.phase == "performance_second"
            assert after.active_player_id == initial.second_player_id
            allocations = _allocation_expectation(initial, owner, ordered)
            score = sum(initial.cards[item].card.score for item in old.live_area) if passed else 0
            assert live.requirements_satisfied is passed
            assert live.live_allocations == allocations
            assert live.base_score == live.total_score == score
            assert [event.event_type for event in events] == ["live_requirements_resolved", "phase_changed"]
            assert events[0].data == {"ordered_live_instance_ids": ordered, "satisfied": passed,
                                      "allocations": allocations, "base_score": score,
                                      "score_bonus": 0, "total_score": score}
            if not passed:
                assert allocations[0]["satisfied"] is True
                assert allocations[-1]["satisfied"] is False
        assert after.pending_effects == [] and after.turn_number == initial.turn_number
        assert after.revision == state.revision + 1
        _privacy(result)
        repo = MatchRepository(repo.path)
        assert repo.get_state(after.match_id) == after
        _replay(repo, after)
        state = after
    return state


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("order", ORDERS)
@pytest.mark.parametrize("passed", [False, True])
def test_colored_multi_live_all_orders_share_hearts_and_move_all_on_failure(tmp_path, first, order, passed):
    repo, state = _setup(tmp_path, first, len(order), passed)
    _walk(repo, state, passed, order)


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("invalid", ["wrong_player", "stale", "empty", "duplicate", "foreign", "missing", "advance"])
def test_multi_live_pending_rejects_invalid_order_without_sql_mutation(tmp_path, first, invalid):
    repo, state = _setup(tmp_path, first, 3, True)
    state = repo.apply(state.match_id, _action(state)).state
    lives = state.players[first].live_area
    action = _action(state, list(lives))
    error = IllegalActionError
    if invalid == "wrong_player":
        action.player_id = state.second_player_id
    elif invalid == "stale":
        action.expected_revision -= 1
        error = StaleRevisionError
    elif invalid == "advance":
        action = _action(state)
    else:
        action.payload["live_instance_ids"] = {"empty": [], "duplicate": [lives[0], lives[0], lives[2]],
                                               "missing": lives[:2],
                                               "foreign": [*lives[:2], state.players[state.second_player_id].live_area[0]]}[invalid]
    before = repo.replay(state.match_id)
    with pytest.raises(error):
        repo.apply(state.match_id, action)
    assert MatchRepository(repo.path).replay(state.match_id) == before


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_multi_live_choice_is_private_and_uses_shared_pool(tmp_path, first, policy):
    repo, state = _setup(tmp_path, first, 3, False)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    _walk(repo, state, False, controller=controller)
