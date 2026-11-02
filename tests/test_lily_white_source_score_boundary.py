from contextlib import closing
from functools import lru_cache
from pathlib import Path

import pytest
from test_effect_execution import _minimal_effect_state

from loveca.db.bootstrap import connect_database
from loveca.simulation.ai import SimpleAIBlocker, SimpleAIController, SimpleAIPolicy
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effects import load_effect_registry
from loveca.simulation.engine import (
    _card_score,
    _effect_unavailable_reason,
    apply_action,
    generate_legal_actions,
)
from loveca.simulation.models import ActionRequest, EffectInvocation
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository

CODE = "PL!-pb2-041"
EFFECT = CODE + ":2"
COUNTING = CODE + ":1"


@lru_cache
def _definitions():
    return {
        effect.effect_id: effect
        for effect in load_effect_registry().effects
        if effect.card_code == CODE
    }


@lru_cache
def _card():
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        return _load_definition(connection, CODE, None, _definitions(), {})


def _state(count=0, *, doubler=False):
    state = _minimal_effect_state(_definitions()[EFFECT])
    state.effect_definitions = dict(_definitions())
    state.pending_effects = []
    state.phase = "performance_first"
    state.active_player_id = "player_1"
    state.effect_order_policy = "ap_nap_player_choice"
    state.cards["source-live"].card = _card().model_copy(deep=True)
    player = state.players["player_1"]
    player.live_area = ["source-live"]
    player.success_live_area = []
    state.cards["secret"] = state.cards["source-live"].model_copy(
        update={"instance_id": "secret", "owner_id": "player_2", "face_up": False}, deep=True
    )
    state.cards["secret"].card.effect_ids = []
    state.players["player_2"].hand = ["secret"]
    for index in range(count):
        instance_id = f"success-{index}"
        state.cards[instance_id] = state.cards["source-live"].model_copy(
            update={"instance_id": instance_id}, deep=True
        )
        if not (doubler and index == 0):
            state.cards[instance_id].card.effect_ids = []
        player.success_live_area.append(instance_id)
    return state


def _advance(state):
    return ActionRequest(
        action_type="advance_phase", player_id="player_1", expected_revision=state.revision
    )


def _physical_count_probe(state):
    # This is an isolated legacy predicate probe, never a proposed registry entry.
    probe = state.model_copy(deep=True)
    probe.effect_definitions[EFFECT] = probe.effect_definitions[EFFECT].model_copy(
        update={"condition": {
            "success_live_unit_count_at_least": {"unit_key": "lily_white", "count": 2}
        }}, deep=True
    )
    invocation = EffectInvocation(
        invocation_id="physical-count-probe", effect_id=EFFECT,
        source_card_instance_id="source-live", player_id="player_1",
        trigger_event="live_started",
    )
    return _effect_unavailable_reason(probe, invocation)


def test_exact_card_identity_and_both_manual_boundaries_remain_explicit():
    definitions = _definitions()
    assert set(definitions) == {COUNTING, EFFECT}
    for effect in definitions.values():
        assert effect.text_revision_id == 1020
        assert effect.raw_text_hash == (
            "d4db99fac1de6ee00db00cb77d66c86b4adb1920ebed6198e0d68490f915c0a8"
        )
        assert effect.execution_mode == effect.simulation_support == "manual_resolution"
        assert effect.review_status == "parsed_draft"
    assert "2枚として扱う" in definitions[COUNTING].label_ja
    assert "lily_white" in _card().unit_keys
    assert _card().work_keys == ["love_live"]
    assert _card().effect_ids == [COUNTING, EFFECT]


@pytest.mark.parametrize("count", [0, 1, 2])
def test_real_live_start_remains_a_manual_wait_not_a_score_or_skip(count):
    state = _state(count)
    result = apply_action(state, _advance(state))
    assert [item.effect_id for item in result.state.pending_effects] == [EFFECT]
    action = next(a for a in result.legal_actions if a.action_type == "resolve_effect")
    assert action.options["invocations"][0]["simulation_support"] == "manual_resolution"
    assert _card_score(result.state, "player_1", "source-live") == 7
    assert not result.state.players["player_1"].manual_modifiers
    assert not any(event.event_type == "effect_skipped_due_to_error" for event in result.events)


def test_legacy_unit_predicate_does_not_implement_the_known_double_count_dependency():
    ordinary_one = _state(1)
    double_count_one = _state(1, doubler=True)
    assert len(double_count_one.players["player_1"].success_live_area) == 1
    assert COUNTING in double_count_one.cards["success-0"].card.effect_ids
    assert _physical_count_probe(ordinary_one) == "success_live_unit_count_too_low"
    assert _physical_count_probe(double_count_one) == "success_live_unit_count_too_low"
    assert _physical_count_probe(_state(2)) is None


def test_unit_work_and_zone_counts_cannot_be_interchanged():
    state = _state(2)
    state.cards["success-0"].card.unit_keys = ["printemps"]
    assert state.cards["success-0"].card.work_keys == ["love_live"]
    assert _physical_count_probe(state) == "success_live_unit_count_too_low"
    state.cards["success-0"].card.unit_keys = ["lily_white"]
    state.players["player_1"].success_live_area.remove("success-0")
    state.players["player_1"].hand.append("success-0")
    assert _physical_count_probe(state) == "success_live_unit_count_too_low"
    state.players["player_1"].hand.remove("success-0")
    state.players["player_2"].success_live_area.append("success-0")
    assert _physical_count_probe(state) == "success_live_unit_count_too_low"


@pytest.mark.parametrize("policy", [
    "simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"
])
def test_four_ai_block_without_mutating_or_peeking_at_hidden_identity(policy):
    base = _state(1, doubler=True)
    state = apply_action(base, _advance(base)).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    decision = controller.choose_action(
        state, generate_legal_actions(state), controlled_player_ids={"player_1"}
    )
    assert isinstance(decision, SimpleAIBlocker)
    assert match_state_hash(state) == before
    changed = state.model_copy(deep=True)
    hidden = state.players["player_2"].hand[0]
    changed.cards[hidden].card = _card().model_copy(deep=True)
    assert controller.choose_action(
        changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}
    ) == decision


@pytest.mark.parametrize("doubler", [False, True])
def test_sql_replay_preserves_manual_wait_and_dependency_snapshot(tmp_path, doubler):
    state = _state(1, doubler=doubler)
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repository.apply(state.match_id, _advance(state))
    replay = repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")
    assert result.state.pending_effects[0].effect_id == EFFECT
    assert result.state.effect_definitions[COUNTING].simulation_support == "manual_resolution"
