import pytest

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.engine import IllegalActionError, StaleRevisionError, generate_legal_actions
from loveca.simulation.models import ActionRequest, MatchState
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from test_mulligan_boundary import _replay
from test_normal_phase_boundary import _constructed, _private


def _fixture(tmp_path, first, new_cost=5, orientation="active"):
    _, state = _constructed(tmp_path / "base", first, stage_count=0)
    state.phase = "first_main"
    player = state.players[first]
    members = [item for item in player.main_deck if state.cards[item].card.card_type == "member"]
    old, new = members[:2]
    # Construct a no-ability payment boundary, not a formal card or complete game.
    player.main_deck.extend(player.hand)
    player.hand = [new]
    for item in (old, new):
        player.main_deck.remove(item)
    player.member_area["center"] = old
    state.cards[old].card = state.cards[old].card.model_copy(update={"cost": 3, "blade": 0, "basic_hearts": {}})
    state.cards[new].card = state.cards[new].card.model_copy(update={"cost": new_cost, "blade": 12, "basic_hearts": {"red": 8}})
    state.cards[old].orientation = orientation
    state.cards[old].face_up = True
    state.cards[new].face_up = True
    for index, item in enumerate(player.energy_area):
        state.cards[item].orientation = "active" if index < 2 else "wait"
    state = MatchState.model_validate(state.model_dump())
    repo = MatchRepository(tmp_path / "baton.sqlite3")
    repo.create_match(state, card_database_path=tmp_path / "base/setup/cards.sqlite3")
    return repo, state, old, new


def _action(state, new):
    player = state.players[state.active_player_id]
    cost = max(0, state.cards[new].card.cost - 3)
    return ActionRequest(action_type="play_member", player_id=state.active_player_id,
                         expected_revision=state.revision,
                         payload={"card_instance_id": new, "slot": "center", "use_baton_touch": True,
                                  "energy_instance_ids": player.energy_area[:cost]})


def _assert_replacement(before, result, old, new, *, ai=False):
    state = result.state
    owner = before.active_player_id
    previous, player = before.players[owner], state.players[owner]
    payment = max(0, before.cards[new].card.cost - 3)
    paid = previous.energy_area[:payment]
    expected_player = previous.model_copy(deep=True)
    expected_player.hand.remove(new)
    expected_player.waiting_room.append(old)
    expected_player.member_area["center"] = new
    expected_player.member_entered_count_this_turn += 1
    expected_player.member_areas_entered_this_turn.append("center")
    expected_player.member_areas_baton_entered_this_turn.append("center")
    expected_player.member_instance_ids_baton_entered_this_turn.append(new)
    expected_player.member_card_instance_ids_entered_stage_this_turn.append(new)
    assert player == expected_player
    for item, card in before.cards.items():
        expected_card = card.model_copy(deep=True)
        if item in paid:
            expected_card.orientation = "wait"
        if item == new:
            expected_card.orientation, expected_card.face_up = "active", True
        assert state.cards[item] == expected_card
    other = next(item for item in state.players if item != owner)
    assert state.players[other] == before.players[other]
    assert state.phase == before.phase and state.active_player_id == owner
    assert state.turn_number == before.turn_number and state.revision == before.revision + 1
    assert state.pending_choice is None and state.pending_effects == []
    events = result.events
    if ai:
        assert events[0].event_type == "ai_action_selected"
        events = events[1:]
    assert [event.event_type for event in events] == ["baton_touch_performed", "member_played"]
    assert events[0].data == {"replaced_card_instance_id": old, "replaced_member_cost": 3,
                              "new_member_cost": before.cards[new].card.cost,
                              "payment_cost": payment, "slot": "center"}
    assert events[1].data == {"card_instance_id": new, "slot": "center", "energy_instance_ids": paid,
                              "payment_cost": payment, "baton_touch": True, "replaced_card_instance_id": old}
    assert all(event.player_id == owner for event in events)
    _private(result)


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("new_cost", [5, 3, 2])
@pytest.mark.parametrize("orientation", ["active", "wait"])
def test_baton_cost_difference_exact_zones_energy_and_sql(tmp_path, first, new_cost, orientation):
    repo, state, old, new = _fixture(tmp_path, first, new_cost, orientation)
    legal = next(item for item in generate_legal_actions(state) if item.action_type == "play_member")
    placement = next(item for item in legal.options["placements"] if item["slot"] == "center" and item["use_baton_touch"])
    assert placement["card_instance_id"] == new and placement["payment_cost"] == max(0, new_cost - 3)
    before_hash = match_state_hash(state)
    result = repo.apply(state.match_id, _action(state, new))
    assert match_state_hash(state) == before_hash
    _assert_replacement(state, result, old, new)
    reopened = MatchRepository(repo.path)
    assert reopened.get_state(state.match_id) == result.state
    _replay(reopened, result.state)


INVALID = ("short", "excess", "duplicate", "wait", "opponent_energy", "deck_energy",
           "zero_cost", "empty_area", "entered", "wrong_player", "stale", "repeat")


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("invalid", INVALID)
def test_baton_invalid_payment_is_atomic_in_sql(tmp_path, first, invalid):
    repo, state, old, new = _fixture(tmp_path, first)
    player = state.players[first]
    action = _action(state, new)
    error = IllegalActionError
    if invalid == "short":
        action.payload["energy_instance_ids"] = player.energy_area[:1]
    elif invalid == "excess":
        action.payload["energy_instance_ids"] = player.energy_area[:3]
    elif invalid == "duplicate":
        action.payload["energy_instance_ids"] = player.energy_area[:1] * 2
    elif invalid == "wait":
        action.payload["energy_instance_ids"] = [player.energy_area[0], player.energy_area[2]]
    elif invalid == "opponent_energy":
        action.payload["energy_instance_ids"] = state.players[state.second_player_id].energy_area[:2]
    elif invalid == "deck_energy":
        action.payload["energy_instance_ids"] = player.energy_deck[:2]
    elif invalid in {"zero_cost", "empty_area", "entered"}:
        if invalid == "zero_cost":
            state.cards[new].card = state.cards[new].card.model_copy(update={"cost": 0})
            action.payload["energy_instance_ids"] = []
        elif invalid == "empty_area":
            action.payload["slot"] = "left"
        else:
            player.member_card_instance_ids_entered_stage_this_turn.append(old)
        repo = MatchRepository(tmp_path / "invalid.sqlite3")
        repo.create_match(state, card_database_path=tmp_path / "base/setup/cards.sqlite3")
    elif invalid == "wrong_player":
        action.player_id = state.second_player_id
    elif invalid == "stale":
        action.expected_revision -= 1
        error = StaleRevisionError
    elif invalid == "repeat":
        state = repo.apply(state.match_id, action).state
        action.expected_revision = state.revision
    before = repo.replay(state.match_id)
    state_hash = match_state_hash(state)
    with pytest.raises(error):
        repo.apply(state.match_id, action)
    assert match_state_hash(state) == state_hash
    assert MatchRepository(repo.path).replay(state.match_id) == before


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_baton_payment_ignores_hidden_cards_and_replays(tmp_path, first, policy):
    repo, state, old, new = _fixture(tmp_path, first)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before_hash = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids=set(state.players))
    assert isinstance(decision, SimpleAIDecision)
    assert decision.action.action_type == "play_member" and decision.action.payload["use_baton_touch"] is True
    altered = state.model_copy(deep=True)
    for owner, player in altered.players.items():
        for item in player.main_deck + player.energy_deck + (player.hand if owner != first else []):
            altered.cards[item].card = altered.cards[item].card.model_copy(update={"name_ja": "UNSEEN", "score": 999})
    altered_hash = match_state_hash(altered)
    alternative = controller.choose_action(altered, generate_legal_actions(altered), controlled_player_ids=set(state.players))
    assert isinstance(alternative, SimpleAIDecision)
    assert decision.action.model_dump() == alternative.action.model_dump()
    assert match_state_hash(altered) == altered_hash and match_state_hash(state) == before_hash
    result = repo.apply(state.match_id, decision.action)
    _assert_replacement(state, result, old, new, ai=True)
    _replay(MatchRepository(repo.path), result.state)
