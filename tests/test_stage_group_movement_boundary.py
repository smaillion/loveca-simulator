from itertools import permutations

import pytest

from loveca.simulation.ai import SimpleAIController, SimpleAIPolicy
from loveca.simulation.engine import IllegalActionError, StaleRevisionError, _effective_member_blade
from loveca.simulation.models import ActionRequest, ManualModifier, MatchState
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from test_mulligan_boundary import _replay
from test_normal_phase_boundary import _constructed, _private
from test_yell_icons_boundary import _choose


SLOTS = ("left", "center", "right")
ORDERS = tuple(permutations(SLOTS))
PAIRS = tuple(permutations(SLOTS, 2))


def _fixture(tmp_path, owner, empty=None):
    _, state = _constructed(tmp_path / "base", owner, stage_count=3)
    state.phase = "first_main"
    for card in state.cards.values():
        card.card.effect_ids = []
        card.card.raw_effect_text_ja = None
        card.card.ability_bucket = "none"
    player = state.players[owner]
    player.main_deck.extend(player.hand)
    player.hand = []
    for index, slot in enumerate(SLOTS):
        top = player.member_area[slot]
        state.cards[top].orientation = "active" if index % 2 else "wait"
        state.cards[top].card.blade = 2
        member = next(item for item in player.main_deck if state.cards[item].card.card_type == "member")
        player.main_deck.remove(member)
        energy = player.energy_deck.pop(0)
        player.member_area_attachments[slot] = [member, energy]
        for item in (member, energy):
            state.cards[item].face_up = True
        player.manual_modifiers.append(ManualModifier(
            modifier_id="AUDIT-" + slot, modifier_type="blade", duration="turn",
            created_turn=state.turn_number, amount=index + 1, target_card_instance_id=top))
    if empty:
        top = player.member_area[empty]
        player.waiting_room.extend([top, *player.member_area_attachments[empty]])
        player.member_area[empty] = None
        player.member_area_attachments[empty] = []
        player.manual_modifiers = [m for m in player.manual_modifiers if m.target_card_instance_id != top]
    # The setup is synthetic; only the following manual movement uses the action pipeline.
    state = MatchState.model_validate(state.model_dump())
    repo = MatchRepository(tmp_path / "movement.sqlite3")
    repo.create_match(state, card_database_path=tmp_path / "base/setup/cards.sqlite3")
    return repo, state


def _action(state, adjustment):
    return ActionRequest(action_type="manual_adjustment", player_id=state.active_player_id,
        expected_revision=state.revision, payload={"reason": "AUDIT Stage internal movement",
        "adjustments": [{"target_player_id": state.active_player_id, **adjustment}]})


def _assert_groups(before, result, assignments, moved):
    state = result.state
    owner = before.active_player_id
    old = before.players[owner]
    expected = old.model_copy(deep=True)
    by_member = {old.member_area[s]: old.member_area_attachments[s] for s in SLOTS if old.member_area[s]}
    expected.member_area = assignments
    expected.member_area_attachments = {s: by_member.get(assignments[s], []) for s in SLOTS}
    for slot in moved:
        if slot not in expected.member_areas_moved_this_turn:
            expected.member_areas_moved_this_turn.append(slot)
    assert state.players[owner] == expected
    assert state.cards == before.cards
    for other in state.players:
        if other != owner:
            assert state.players[other] == before.players[other]
    assert state.phase == before.phase and state.turn_number == before.turn_number
    assert state.active_player_id == owner and state.revision == before.revision + 1
    assert not state.pending_effects and state.pending_choice is None
    for index, slot in enumerate(SLOTS):
        top = old.member_area[slot]
        if top:
            assert _effective_member_blade(before, owner, top) == 3 + index
            assert _effective_member_blade(state, owner, top) == 3 + index
    # Internal IDs alone are not a general cross-zone lifecycle identity proof.
    assert state.players[owner].member_card_instance_ids_entered_stage_this_turn == old.member_card_instance_ids_entered_stage_this_turn
    _private(result)


def _apply(repo, state, adjustment, assignments, moved):
    digest = match_state_hash(state)
    result = repo.apply(state.match_id, _action(state, adjustment))
    assert match_state_hash(state) == digest
    _assert_groups(state, result, assignments, moved)
    assert result.events[-1].event_type == "manual_adjustment_applied"
    assert len(result.events) == 2
    reopened = MatchRepository(repo.path)
    assert reopened.get_state(state.match_id) == result.state
    _replay(reopened, result.state)
    return result


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("order", ORDERS)
def test_formation_all_permutations_preserve_groups_effects_and_sql(tmp_path, owner, order):
    repo, state = _fixture(tmp_path, owner)
    player = state.players[owner]
    assignments = {to: player.member_area[source] for to, source in zip(SLOTS, order)}
    moved = [to for to, source in zip(SLOTS, order) if to != source]
    result = _apply(repo, state, {"adjustment_type": "formation_change", "slot_assignments": assignments}, assignments, moved)
    event = result.events[0]
    assert event.event_type == "stage_formation_changed" and event.source == "manual"
    assert event.data == {"before": player.member_area, "after": assignments,
        "before_attachments": player.member_area_attachments,
        "after_attachments": result.state.players[owner].member_area_attachments}


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("pair", PAIRS)
@pytest.mark.parametrize("occupied", [False, True])
def test_position_move_and_swap_preserve_complete_groups_and_sql(tmp_path, owner, pair, occupied):
    source, target = pair
    repo, state = _fixture(tmp_path, owner, empty=None if occupied else target)
    player = state.players[owner]
    assignments = dict(player.member_area)
    assignments[source], assignments[target] = assignments[target], assignments[source]
    result = _apply(repo, state, {"adjustment_type": "move_member",
        "target_card_instance_id": player.member_area[source], "to_slot": target},
        assignments, [target, source] if occupied else [target])
    event = result.events[0]
    assert event.event_type == ("stage_member_groups_swapped" if occupied else "stage_member_group_moved")
    assert event.data == {"from_slot": source, "to_slot": target,
        "moving_member_instance_id": player.member_area[source], "target_member_instance_id": player.member_area[target],
        "moving_attached_card_instance_ids": player.member_area_attachments[source],
        "target_attached_card_instance_ids": player.member_area_attachments[target]}


INVALID = ("duplicate", "missing", "foreign", "attachment", "deck", "same_slot", "stale", "batch")


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("fault", INVALID)
def test_invalid_stage_movement_preserves_sql_even_after_prior_batch_entry(tmp_path, owner, fault):
    repo, state = _fixture(tmp_path, owner)
    player = state.players[owner]
    assignments = dict(player.member_area)
    adjustment = {"adjustment_type": "formation_change", "slot_assignments": assignments}
    if fault in {"duplicate", "batch"}:
        assignments["right"] = assignments["left"]
    elif fault == "missing":
        assignments.pop("center")
    elif fault == "foreign":
        other = next(p for p in state.players if p != owner)
        assignments["right"] = state.players[other].member_area["right"]
    elif fault in {"attachment", "deck", "same_slot"}:
        item = (player.member_area_attachments["left"][0] if fault == "attachment" else
                player.main_deck[0] if fault == "deck" else player.member_area["left"])
        adjustment = {"adjustment_type": "move_member", "target_card_instance_id": item, "to_slot": "left"}
    action = _action(state, adjustment)
    if fault == "stale":
        action.expected_revision -= 1
    if fault == "batch":
        action.payload["adjustments"].insert(0, {"adjustment_type": "position_change", "target_player_id": owner,
                                               "from_slot": "left", "to_slot": "center"})
    before = repo.replay(state.match_id)
    with pytest.raises(StaleRevisionError if fault == "stale" else IllegalActionError):
        repo.apply(state.match_id, action)
    assert MatchRepository(repo.path).replay(state.match_id) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_continue_after_manual_stage_move_without_hidden_card_influence(tmp_path, owner, policy):
    repo, state = _fixture(tmp_path, owner)
    player = state.players[owner]
    assignments = {to: player.member_area[source] for to, source in zip(SLOTS, reversed(SLOTS))}
    result = _apply(repo, state, {"adjustment_type": "formation_change", "slot_assignments": assignments},
                    assignments, ["left", "right"])
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    action = _choose(controller, result.state)
    assert action.action_type == "end_main_phase"
    continued = repo.apply(state.match_id, action)
    assert continued.state.phase == "second_active"
    assert continued.state.players[owner].member_area == assignments
    assert continued.state.players[owner].member_area_attachments == result.state.players[owner].member_area_attachments
    assert continued.state.players[owner].manual_modifiers == player.manual_modifiers
    _private(continued)
    _replay(MatchRepository(repo.path), continued.state)
