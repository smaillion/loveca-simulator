from pathlib import Path
import json

import pytest

from test_mirakura_front_position_boundary import EFFECT, FRONT, STATIC, _manual, _play, _state, _swap_roles
from loveca.simulation.effect_candidates import _static_mirrored_front_cost_heart, discover_effect_candidates
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import _static_heart_bonus, apply_action
from loveca.simulation.models import ActionRequest
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.simulation.ai import SimpleAIBlocker, SimpleAIController, SimpleAIPolicy
from loveca.simulation.engine import generate_legal_actions
from loveca.simulation.rule_evaluation import build_ai_observation
from loveca.webapp import _match_state_payload

KEY = "opposing_member_cost_greater_than_source_mirrored_v1"


def _initial(slot, owner="player_1", *, front_cost=10, same_cost=4, legacy=False):
    state = _state()
    for position in FRONT:
        state.cards["opponent-" + position].card.cost = same_cost
    state.cards["opponent-" + FRONT[slot]].card.cost = front_cost
    if legacy:
        state.effect_definitions[STATIC].condition = {"opposing_member_cost_greater_than_source": True}
    return _swap_roles(state) if owner == "player_2" else state


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("slot", ["left", "right"])
@pytest.mark.parametrize("front_cost,same_cost,expected", [(10, 4, 1), (4, 10, 0)])
def test_native_onplay_uses_mirrored_front_not_same_named_slot(owner, slot, front_cost, same_cost, expected):
    initial = _initial(slot, owner, front_cost=front_cost, same_cost=same_cost)
    before = match_state_hash(initial)
    result = apply_action(initial, _play(initial, slot, owner))
    assert _static_heart_bonus(result.state, owner, "source-live")["heart01"] == expected
    assert match_state_hash(initial) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("slot", FRONT)
@pytest.mark.parametrize("cost", [8, 9, 10])
def test_dynamic_cost_threshold_all_positions_and_roles(owner, slot, cost):
    state = _initial(slot, owner, front_cost=cost)
    result = apply_action(state, _play(state, slot, owner))
    assert _static_heart_bonus(result.state, owner, "source-live")["heart01"] == int(cost > 9)
    assert result.state.effect_definitions[EFFECT].simulation_support == "manual_resolution"


@pytest.mark.parametrize("slot", FRONT)
@pytest.mark.parametrize("case", ["missing", "attached_high", "wait"])
def test_top_member_only_and_wait_does_not_disable_condition(slot, case):
    state = _initial(slot, front_cost=10 if case == "wait" else 4)
    front = FRONT[slot]
    if case == "missing":
        card = state.players["player_2"].member_area[front]
        state.players["player_2"].member_area[front] = None
        state.players["player_2"].hand.append(card)
    elif case == "attached_high":
        child = state.cards["opponent-" + front].model_copy(deep=True)
        child.instance_id = "attached-high"
        child.card.cost = 99
        state.cards[child.instance_id] = child
        state.players["player_2"].member_area_attachments[front] = [child.instance_id]
    else:
        state.cards["opponent-" + front].orientation = "wait"
    result = apply_action(state, _play(state, slot))
    result.state.cards["source-live"].orientation = "wait"
    assert _static_heart_bonus(result.state, "player_1", "source-live")["heart01"] == int(case == "wait")


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("movement", ["position", "formation", "leave", "return"])
def test_native_sql_recomputes_current_position_and_preserves_legacy_snapshot(tmp_path, owner, legacy, movement):
    initial = _initial("left", owner, legacy=legacy)
    repo = MatchRepository(tmp_path / "mirror.sqlite3")
    repo.create_match(initial, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(initial.match_id, _play(initial, "left", owner)).state
    assert _static_heart_bonus(played, owner, "source-live")["heart01"] == int(not legacy)
    if movement == "position":
        changes = [{"adjustment_type": "position_change", "target_player_id": owner,
                    "from_slot": "left", "to_slot": "right"}]
    elif movement == "formation":
        changes = [{"adjustment_type": "formation_change", "target_player_id": owner,
                    "slot_assignments": {"left": None, "center": None, "right": "source-live"}}]
    else:
        changes = [{"adjustment_type": "move_card", "target_player_id": owner,
                    "target_card_instance_id": "source-live", "to_zone": "hand"}]
        if movement == "return":
            changes.append({"adjustment_type": "move_card", "target_player_id": owner,
                            "target_card_instance_id": "source-live", "to_zone": "member_right"})
    # Explicit human adjustment of the still-manual first ability, not an automatic position executor.
    result = repo.apply(initial.match_id, _manual(played, changes, owner=owner))
    expected = int(legacy and movement != "leave")
    assert _static_heart_bonus(result.state, owner, "source-live")["heart01"] == expected
    assert not result.state.players[owner].manual_modifiers
    replay = repo.replay(initial.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("slot", FRONT)
@pytest.mark.parametrize("wait", [False, True])
@pytest.mark.parametrize("front_cost", [4, 10])
def test_actual_yell_sql_uses_static_heart_and_full_projection_stays_private(tmp_path, owner, slot, wait, front_cost):
    # Independent valid Yell fixture; this does not resolve or bypass the manual on-play ability.
    state = _initial(slot, owner, front_cost=front_cost)
    player = state.players[owner]
    player.hand.remove("source-live")
    player.member_area[slot] = "source-live"
    player.main_deck.remove("good-live")
    player.live_area = ["good-live"]
    state.cards["source-live"].orientation = "wait" if wait else "active"
    state.phase = "yell_first" if owner == state.first_player_id else "yell_second"
    state.active_player_id = owner
    repo = MatchRepository(tmp_path / "yell.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    before = match_state_hash(state)
    result = repo.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id=owner,
        expected_revision=state.revision))
    event = next(e for e in result.events if e.event_type == "yell_completed")
    expected = 2 + int(front_cost > 9)
    assert event.data["member_hearts"]["heart01"] == expected
    assert event.data["raw_blade_count"] == (0 if wait else 4)
    assert result.state.players[owner].live_result.member_hearts["heart01"] == expected
    assert match_state_hash(state) == before
    for viewer in result.state.players:
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        assert payload["state"]["players"][owner]["live_result"]["member_hearts"]["heart01"] == expected
        if viewer == owner:
            assert "opponent-secret" not in json.dumps(payload)
        for hidden in result.state.players[owner].main_deck:
            assert hidden not in payload["state"]["cards"]
    assert repo.replay(state.match_id)["final_state"] == result.state.model_dump(mode="json")


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("slot", FRONT)
def test_native_opponent_swap_moves_group_and_recalculates_bonus(tmp_path, owner, slot):
    initial = _initial(slot, owner)
    other = "player_2" if owner == "player_1" else "player_1"
    front = FRONT[slot]
    moving = next(position for position in FRONT if position != front)
    for position in (front, moving):
        top = initial.cards["opponent-" + position]
        top.orientation = "wait"
        child = top.model_copy(deep=True)
        child.instance_id = "child-" + position
        child.card.cost = 99
        initial.cards[child.instance_id] = child
        initial.players[other].member_area_attachments[position] = [child.instance_id]
    repo = MatchRepository(tmp_path / "opponent-swap.sqlite3")
    repo.create_match(initial, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(initial.match_id, _play(initial, slot, owner)).state
    assert _static_heart_bonus(played, owner, "source-live")["heart01"] == 1
    result = repo.apply(initial.match_id, _manual(played, [{"adjustment_type": "position_change",
        "target_player_id": other, "from_slot": moving, "to_slot": front}], owner=owner))
    assert _static_heart_bonus(result.state, owner, "source-live")["heart01"] == 0
    assert result.state.players[other].member_area[front] == "opponent-" + moving
    assert result.state.players[other].member_area_attachments[front] == ["child-" + moving]
    assert result.state.cards["opponent-" + moving].orientation == "wait"
    assert repo.replay(initial.match_id)["final_state"] == result.state.model_dump(mode="json")


def test_exact_candidate_and_first_segment_unchanged():
    state = _state()
    candidate = next(c for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
                     if c.effect_id == STATIC)
    assert candidate.pattern_id == "static_mirrored_front_cost_heart_v1"
    assert candidate.condition == state.effect_definitions[STATIC].condition == {KEY: True}
    card = state.cards["source-live"].card
    row = {"card_code": card.card_code, "text_revision_id": card.text_revision_id,
           "raw_text_hash": card.raw_text_hash, "raw_effect_text_ja": card.raw_effect_text_ja}
    for key, value in [("card_code", "OTHER"), ("text_revision_id", 131), ("raw_text_hash", "bad"),
                       ("raw_effect_text_ja", card.raw_effect_text_ja + " ")]:
        assert _static_mirrored_front_cost_heart({**row, key: value}) is None


@pytest.mark.parametrize("change", [
    {"condition": {KEY: False}}, {"condition": {KEY: 1}}, {"condition": {KEY: "true"}},
    {"condition": {KEY: True, "source_orientation": "wait"}},
    {"effect_type": "triggered"}, {"timing": "on_play"}, {"trigger": "member_played"},
    {"execution_mode": "prompt_then_resolve"}, {"frequency_limit": "once_per_live"},
    {"is_optional": True}, {"duration": "live"}, {"simulation_support": "manual_resolution"},
    {"cost": [{"action_type": "draw_card", "amount": 1}]},
    {"actions": [{"action_type": "gain_heart", "amount": 2, "color_slot": "heart01"}]},
    {"actions": [{"action_type": "gain_heart", "amount": 1, "color_slot": "heart02"}]},
])
def test_new_condition_rejects_unbounded_or_false_snapshot_shapes(change):
    raw = _state().effect_definitions[STATIC].model_dump(mode="json")
    with pytest.raises(ValueError, match="mirrored front cost"):
        EffectDefinition.model_validate({**raw, **change})


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_rule_view_uses_mirror_but_first_manual_still_blocks(owner, policy):
    initial = _initial("left", owner)
    state = apply_action(initial, _play(initial, "left", owner)).state
    before = match_state_hash(state)
    observation = build_ai_observation(state, owner, generate_legal_actions(state))
    assert dict(observation.evaluation.stage_hearts)["heart01"] == 3
    assert "tail" not in observation.cards and "opponent-secret" not in observation.cards
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIBlocker) and decision.reason == "no_safe_ai_action"
    changed = state.model_copy(deep=True)
    for key in ("tail", "opponent-secret"):
        card = changed.cards[key]
        card.card.name_ja = card.card.card_code = "HIDDEN-REPLACED"
        card.card.cost = 99
        replacement = "new-" + key
        changed.cards[replacement] = changed.cards.pop(key).model_copy(update={"instance_id": replacement})
        for player in changed.players.values():
            player.hand = [replacement if item == key else item for item in player.hand]
            player.main_deck = [replacement if item == key else item for item in player.main_deck]
    assert build_ai_observation(changed, owner, generate_legal_actions(changed)).evaluation == observation.evaluation
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner}) == decision
    assert match_state_hash(state) == before
