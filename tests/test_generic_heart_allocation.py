import hashlib
import itertools
import json

import pytest

from loveca.simulation.ai import SimpleAIController, SimpleAIPolicy
from loveca.simulation.engine import _apply_live_requirements
from loveca.simulation.models import (
    ActionRequest, CardDefinition, CardInstance, LivePerformanceResult,
    ManualModifier, MatchState, PlayerState,
)
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from test_mulligan_boundary import _replay
from test_performance_yell_boundary import _fixture, _privacy
from test_yell_icons_boundary import _choose


POLICY = "preserve_feasibility_v1"
ORDERS = [order for count in (2, 3) for order in itertools.permutations(range(count))]


def _pure(pool, needs, wild=0, modern=True):
    cards = {str(i): CardInstance(instance_id=str(i), owner_id="player_1", card=CardDefinition(
        card_code="AUDIT", card_id=str(i), name_ja="AUDIT", card_type="live", score=2,
        required_hearts=need)) for i, need in enumerate(needs)}
    return MatchState(match_id="allocation", seed=1, cards=cards,
        live_heart_allocation_policy=POLICY if modern else None,
        players={"player_1": PlayerState(player_id="player_1", name="A", live_area=list(cards),
            live_result=LivePerformanceResult(available_hearts=pool, all_color_hearts=wild))})


def _resolve(state):
    events = []
    _apply_live_requirements(state, "player_1", list(state.players["player_1"].live_area), events)
    return events


def _witness(pool, needs, wild):
    # Independent finite enumeration of physical colored Hearts and ALL choices.
    if not needs:
        return True
    colors = tuple(pool)
    for values in itertools.product(*(range(pool[color] + 1) for color in colors)):
        spent = dict(zip(colors, values))
        for all_used in range(wild + 1):
            if sum(values) + all_used != sum(needs[0].values()):
                continue
            deficit = sum(max(0, n - spent.get(c, 0)) for c, n in needs[0].items() if c != "heart0")
            if deficit <= all_used and _witness({c: pool[c] - spent[c] for c in colors}, needs[1:], wild - all_used):
                return True
    return False


def _conservation(state, pool, wild, needs):
    result = state.players["player_1"].live_result
    available = dict(pool)
    for allocation, required in zip(result.live_allocations, needs, strict=True):
        spent = allocation["consumed_hearts"]
        used = allocation["all_color_hearts_used"]
        assert all(0 <= n <= available.get(c, 0) for c, n in spent.items())
        assert 0 <= used <= wild
        assert sum(spent.values()) + used == sum(required.values())
        assert sum(max(0, n - spent.get(c, 0)) for c, n in required.items() if c != "heart0") <= used
        for color, number in spent.items():
            available[color] = available.get(color, 0) - number
        wild -= used
        assert allocation["remaining_hearts"] == {c: n for c, n in available.items() if n}
        assert allocation["remaining_all_color_hearts"] == wild
        assert allocation["satisfied"] is True and allocation["missing_hearts"] == {}


def test_two_identical_generic_lives_preserve_later_blue_requirement():
    needs = [{"blue": 1, "heart0": 1}] * 2
    state = _pure({"blue": 2, "red": 2}, needs)
    _resolve(state)
    assert state.players["player_1"].live_result.requirements_satisfied is True
    _conservation(state, {"blue": 2, "red": 2}, 0, needs)


def test_small_pools_match_independent_exhaustive_colored_all_and_generic_oracle():
    options = [{}, {"blue": 1}, {"red": 1}, {"heart0": 1}, {"blue": 1, "heart0": 1},
               {"red": 1, "heart0": 1}, {"blue": 1, "red": 1}]
    for blue, red, wild, needs in itertools.product(range(3), range(3), range(3), itertools.product(options, repeat=2)):
        pool = {"blue": blue, "red": red}
        state = _pure(pool, needs, wild)
        _resolve(state)
        possible = _witness(pool, needs, wild)
        assert state.players["player_1"].live_result.requirements_satisfied is possible, (pool, wild, needs)
        if possible:
            _conservation(state, pool, wild, needs)


@pytest.mark.parametrize("color", ["heart01", "heart02", "heart03", "heart04", "heart05", "heart06"])
@pytest.mark.parametrize("wild", [0, 1, 2])
def test_each_production_color_reserves_later_requirements_with_all_competition(color, wild):
    pool = {color: 3 - wild, "heart0": 3}
    needs = [{color: 1, "heart0": 1}] * 3
    state = _pure(pool, needs, wild)
    _resolve(state)
    assert state.players["player_1"].live_result.requirements_satisfied is True
    _conservation(state, pool, wild, needs)


@pytest.mark.parametrize("mode", ["delta", "replace", "global"])
def test_reservations_use_effective_targeted_and_global_required_hearts(mode):
    needs = [{"blue": 1, "heart0": 1}] * 2
    state = _pure({"blue": 2, "red": 2}, needs)
    if mode == "delta":
        state.cards["1"].card.required_hearts["blue"] = 2
        modifier = ManualModifier(modifier_id="requirement", modifier_type="required_heart", duration="live",
            created_turn=1, target_card_instance_id="1", color_slot="blue", amount=-1)
    elif mode == "replace":
        state.cards["1"].card.required_hearts = {"green": 99}
        modifier = ManualModifier(modifier_id="requirement", modifier_type="required_heart", duration="live",
            created_turn=1, target_card_instance_id="1", value={"mode": "replace", "required_hearts": needs[1]})
    else:
        for card in state.cards.values():
            card.card.required_hearts["blue"] = 2
        modifier = ManualModifier(modifier_id="requirement", modifier_type="required_heart", duration="live",
            created_turn=1, color_slot="blue", amount=-1)
    state.players["player_1"].manual_modifiers = [modifier]
    _resolve(state)
    assert state.players["player_1"].live_result.requirements_satisfied is True
    _conservation(state, {"blue": 2, "red": 2}, 0, needs)


def _setup(tmp_path, owner, phase, count, modern=True):
    _, state = _fixture(tmp_path / "base", owner, "live", "mixed")
    state.phase = "yell_" + phase
    if phase == "second":
        state.first_player_id, state.second_player_id = state.second_player_id, state.first_player_id
    state.live_choice_guard_policy = "require_resolution_v1"
    state.live_heart_allocation_policy = POLICY if modern else None
    if not modern:
        state.attached_member_departure_policy = None
    player = state.players[owner]
    for card in state.cards.values():
        card.card.effect_ids = []
        card.card.raw_effect_text_ja = None
        card.card.ability_bucket = "none"
        card.card.special_blade_hearts = []
    for index, item in enumerate(player.member_area.values()):
        state.cards[item].card.blade = 0
        state.cards[item].card.basic_hearts = {"blue": count, "red": count} if index == 0 else {}
    extra = [i for i in player.main_deck if state.cards[i].card.card_type == "live"][:count - 1]
    assert len(extra) == count - 1
    for item in extra:
        player.main_deck.remove(item)
        player.live_area.append(item)
    for item in player.live_area:
        state.cards[item].face_up = True
        state.cards[item].card.required_hearts = {"blue": 1, "heart0": 1}
        state.cards[item].card.score = 2
    state = MatchState.model_validate(state.model_dump())
    repo = MatchRepository(tmp_path / "allocation.sqlite3")
    repo.create_match(state, card_database_path=tmp_path / "base/base/setup/cards.sqlite3")
    return repo, state


def _walk(repo, initial, order, controller=None):
    owner = initial.active_player_id
    state = initial
    for step in range(2):
        action = _choose(controller, state) if controller else ActionRequest(
            action_type="advance_phase" if step == 0 else "resolve_live_requirements",
            player_id=owner, expected_revision=state.revision,
            payload={} if step == 0 else {"live_instance_ids": [initial.players[owner].live_area[i] for i in order]})
        assert action.action_type == ("advance_phase" if step == 0 else "resolve_live_requirements")
        digest = match_state_hash(state)
        result = repo.apply(state.match_id, action)
        assert match_state_hash(state) == digest
        state = result.state
        _privacy(result)
        assert MatchRepository(repo.path).get_state(state.match_id) == state
        _replay(repo, state)
        if step == 0:
            assert state.phase == initial.phase and state.pending_choice.choice_type == "live_requirements"
            assert state.pending_choice.player_id == owner
        else:
            assert state.pending_choice is None
    old, player = initial.players[owner], state.players[owner]
    actual = player.live_result
    expected = old.model_copy(deep=True)
    expected.live_result = actual
    assert player == expected and state.cards == initial.cards
    other = next(p for p in initial.players if p != owner)
    assert state.players[other] == initial.players[other]
    assert state.phase == ("performance_second" if initial.phase == "yell_first" else "live_judgment")
    assert state.revision == initial.revision + 2 and state.pending_effects == []
    assert actual.requirements_satisfied is True
    assert actual.base_score == actual.total_score == 2 * len(old.live_area)
    assert all(a["consumed_hearts"] == {"blue": 1, "red": 1} for a in actual.live_allocations)
    return state


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("phase", ["first", "second"])
@pytest.mark.parametrize("order", ORDERS)
def test_generic_live_all_orders_both_phases_execute_sql_and_private_replay(tmp_path, owner, phase, order):
    repo, state = _setup(tmp_path, owner, phase, len(order))
    _walk(repo, state, order)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("phase", ["first", "second"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_generic_live_shared_pool_is_feasible_and_private(tmp_path, owner, phase, policy):
    repo, state = _setup(tmp_path, owner, phase, 2)
    _walk(repo, state, (0, 1), SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block")))


@pytest.mark.parametrize("value", [True, 1, {}, "unknown"])
def test_unknown_allocation_policy_rejected(value):
    with pytest.raises(ValueError):
        MatchState(match_id="invalid", seed=1, players={}, cards={}, live_heart_allocation_policy=value)


def test_legacy_generic_allocation_still_fails_without_new_serialized_field():
    state = _pure({"blue": 2, "red": 2}, [{"blue": 1, "heart0": 1}] * 2, modern=False)
    _resolve(state)
    assert "live_heart_allocation_policy" not in state.model_dump()
    assert state.players["player_1"].live_result.requirements_satisfied is False
    assert state.players["player_1"].waiting_room == ["0", "1"]


@pytest.mark.parametrize("owner,state_hash,event_hash", [
    ("player_1", "595441b8def3d524498d7f0f14a9c8351b7da9d1c0e71fb3061b9a9468cc6082", "8139bf2c54dc2857429ebe30f37cbe718a5b49c2c58907cea3920cdb74f66550"),
    ("player_2", "822bf0a3e49258509435b08c5b0c48c9c0eb0d9c50aa591691313f846eaca3c8", "865b716da4e439ff1b12cd7e46577f82232e0ae50f27c70c650d670fa132604d"),
])
def test_prechange_sql_failure_state_and_event_hashes_are_preserved(tmp_path, owner, state_hash, event_hash):
    repo, state = _setup(tmp_path, owner, "first", 2, modern=False)
    events = []
    lives = list(state.players[owner].live_area)
    for kind, payload in (("advance_phase", {}), ("resolve_live_requirements", {"live_instance_ids": lives})):
        result = repo.apply(state.match_id, ActionRequest(action_type=kind, player_id=owner,
                           expected_revision=state.revision, payload=payload))
        state = result.state
        events.extend(e.model_dump() for e in result.events)
    assert "live_heart_allocation_policy" not in state.model_dump()
    assert match_state_hash(state) == state_hash
    assert hashlib.sha256(json.dumps(events, ensure_ascii=False, sort_keys=True).encode()).hexdigest() == event_hash
    _replay(repo, state)
