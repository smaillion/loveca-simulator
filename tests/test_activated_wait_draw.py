from contextlib import closing
from functools import lru_cache
from pathlib import Path

import pytest
from test_effect_execution import _minimal_effect_state

from loveca.db.bootstrap import connect_database
from loveca.simulation.ai import (
    SimpleAIBlocker,
    SimpleAIController,
    SimpleAIDecision,
    SimpleAIPolicy,
)
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effect_candidates import (
    _activated_wait_draw_then_discard,
    discover_effect_candidates,
)
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, ManualModifier, MatchState
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CARDS = ("PL!SP-bp7-008", "PL!N-bp7-023")
RULE_REFERENCE_IDS = ("9.4.1", "9.4.2.1", "9.4.2.3", "9.5.2", "9.6.2", "11.3")


@lru_cache
def _candidate(card_code):
    return next(
        c
        for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
        if c.effect_id == card_code + ":1"
    )


def _state(card_code):
    effect = EffectDefinition.model_validate(_candidate(card_code).to_registry_entry())
    definitions = {e.effect_id: e for e in load_effect_registry().effects}
    definitions[effect.effect_id] = effect
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        card = _load_definition(connection, card_code, None, definitions, {})
    assert card.raw_text_hash == effect.raw_text_hash
    assert card.text_revision_id == effect.text_revision_id
    assert not card.effect_registry_errors
    state = _minimal_effect_state(effect)
    state.effect_definitions = definitions
    state.phase = "first_main"
    state.pending_effects = []
    state.players["player_1"].live_area = []
    state.cards["source-live"].card = card
    state.players["player_1"].member_area["center"] = "source-live"
    for i in range(2):
        key = f"held-{i}"
        state.cards[key] = state.cards["deck-member-1"].model_copy(
            update={"instance_id": key}, deep=True
        )
        state.players["player_1"].hand.append(key)
    state.cards["opponent-secret"] = state.cards["deck-member-1"].model_copy(
        update={"instance_id": "opponent-secret", "owner_id": "player_2"},
        deep=True,
    )
    state.players["player_2"].hand = ["opponent-secret"]
    return state


def _activation(state, card_code, **changes):
    return ActionRequest(
        action_type="activate_effect",
        player_id="player_1",
        expected_revision=state.revision,
        payload={"effect_id": card_code + ":1", "source_card_instance_id": "source-live"},
        **changes,
    )


def _resolve(state, selected):
    return ActionRequest(
        action_type="resolve_effect",
        player_id="player_1",
        expected_revision=state.revision,
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": selected,
        },
    )


@pytest.mark.parametrize("card_code", CARDS)
def test_exact_candidates_match_real_revision_and_full_skill_segment(card_code):
    candidate = _candidate(card_code)
    state = _state(card_code)
    assert candidate.simulation_support == "test_validated_executable"
    assert candidate.review_status == "test_validated"
    assert candidate.label_ja in state.cards["source-live"].card.raw_effect_text_ja
    assert candidate.frequency_limit == ("none" if card_code == CARDS[0] else "once_per_turn")
    assert candidate.cost == [{"action_type": "apply_wait", "target": "source"}]
    assert [a["action_type"] for a in candidate.actions] == (
        ["draw_card"] if card_code == CARDS[0] else ["draw_card", "discard_from_hand"]
    )
    if card_code == CARDS[0]:
        moved = state.effect_definitions[card_code + ":2"]
        assert moved.simulation_support == "test_validated_executable"
        assert moved.effect_index == 2 and moved.raw_text_hash == candidate.raw_text_hash
        assert moved.actions[0].source_object_policy == "original_moved_stage_member"


@pytest.mark.parametrize("card_code", CARDS)
def test_wait_cost_and_draw_happen_once_before_native_post_draw_selection(card_code):
    state = _state(card_code)
    before = state.model_dump_json()
    result = apply_action(state, _activation(state, card_code))
    after = result.state
    count = 1 if card_code == CARDS[0] else 2
    assert after.cards["source-live"].orientation == "wait"
    assert after.players["player_1"].hand == [
        "held-0",
        "held-1",
        *state.players["player_1"].main_deck[:count],
    ]
    assert after.players["player_1"].main_deck == state.players["player_1"].main_deck[count:]
    assert (
        sum(len(e.data["instance_ids"]) for e in result.events if e.event_type == "cards_drawn")
        == count
    )
    assert state.model_dump_json() == before
    assert not any(a.action_type == "activate_effect" for a in generate_legal_actions(after))
    if count == 1:
        assert not after.pending_effects
    else:
        invocation = after.pending_effects[0]
        assert invocation.resolution_stage == "after_cost"
        options = next(
            a for a in generate_legal_actions(after) if a.action_type == "resolve_effect"
        ).options["invocations"][0]
        assert options["choice_type"] == "post_action_card_from_zone"
        assert options["card_selection_minimum"] == options["card_selection_maximum"] == 2
        assert set(after.players["player_1"].hand) == set(options["candidate_card_instance_ids"])
        finished = apply_action(after, _resolve(after, ["deck-live-1", "deck-member-1"]))
        assert finished.state.players["player_1"].hand == ["held-0", "held-1"]
        assert finished.state.players["player_1"].waiting_room == ["deck-live-1", "deck-member-1"]
        assert finished.state.players["player_1"].main_deck == ["deck-live-2"]
        assert not finished.state.pending_effects
        assert not any(e.event_type == "cards_drawn" for e in finished.events)


@pytest.mark.parametrize(
    "phase,active",
    [
        ("setup_mulligan_first", "player_1"),
        ("performance_first", "player_1"),
        ("second_main", "player_2"),
        ("first_main", "player_2"),
    ],
)
@pytest.mark.parametrize("card_code", CARDS)
def test_activation_outside_own_main_is_atomic(card_code, phase, active):
    state = _state(card_code)
    state.phase, state.active_player_id = phase, active
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _activation(state, card_code))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("card_code", CARDS)
def test_already_wait_source_cannot_pay_cost(card_code):
    state = _state(card_code)
    state.cards["source-live"].orientation = "wait"
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _activation(state, card_code))
    assert match_state_hash(state) == before


@pytest.mark.parametrize(
    "selection",
    [
        [],
        ["deck-live-1"],
        ["deck-live-1", "deck-live-1"],
        ["deck-live-1", "opponent-secret"],
        ["held-0", "held-1", "deck-live-1"],
    ],
)
def test_invalid_discard_rolls_back_without_repeating_draw_or_wait_payment(selection):
    initial = _state(CARDS[1])
    state = apply_action(initial, _activation(initial, CARDS[1])).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, selection))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("card_code", CARDS)
def test_reactivated_ready_control_state_respects_only_explicit_frequency_limit(card_code):
    state = _state(card_code)
    state = apply_action(state, _activation(state, card_code)).state
    if state.pending_effects:
        state = apply_action(state, _resolve(state, ["held-0", "held-1"])).state
    # Model the boundary after a separate ready effect, without testing that effect here.
    state.cards["source-live"].orientation = "active"
    before = match_state_hash(state)
    if card_code == CARDS[0]:
        result = apply_action(state, _activation(state, card_code))
        assert len(result.state.players["player_1"].hand) == len(state.players["player_1"].hand) + 1
    else:
        with pytest.raises(IllegalActionError):
            apply_action(state, _activation(state, card_code))
        assert match_state_hash(state) == before


@pytest.mark.parametrize("card_code", CARDS)
def test_actual_sqlite_replay_and_legacy_manual_snapshot(tmp_path, card_code):
    state = _state(card_code)
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repo.apply(state.match_id, _activation(state, card_code))
    if result.state.pending_effects:
        result = repo.apply(
            state.match_id, _resolve(result.state, ["deck-live-1", "deck-member-1"])
        )
    replay = repo.replay(state.match_id)
    assert replay["final_state"] == result.state.model_dump()
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert MatchState.model_validate_json(result.state.model_dump_json()) == result.state
    legacy = _state(card_code)
    raw = legacy.effect_definitions[card_code + ":1"].model_dump(mode="json")
    raw.update(
        execution_mode="manual_resolution",
        simulation_support="manual_resolution",
        review_status="parsed_draft",
        condition={"source_zone": "stage"},
        cost=[],
        choice=None,
        actions=[{"action_type": "manual_resolution"}],
    )
    legacy.effect_definitions[card_code + ":1"] = EffectDefinition.model_validate(raw)
    restored = MatchState.model_validate_json(legacy.model_dump_json())
    result = apply_action(restored, _activation(restored, card_code))
    assert result.state.cards["source-live"].orientation == "active"
    assert len(result.state.players["player_1"].hand) == 2
    assert result.state.pending_effects[0].effect_id == card_code + ":1"
    legacy.match_id = "legacy-manual"
    repo.create_match(legacy, card_database_path=Path("data/loveca.sqlite3"))
    old_result = repo.apply(legacy.match_id, _activation(legacy, card_code))
    assert (
        old_result.state.effect_definitions[card_code + ":1"].simulation_support
        == "manual_resolution"
    )
    assert repo.replay(legacy.match_id)["final_state"] == old_result.state.model_dump()


@pytest.mark.parametrize(
    "policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"]
)
@pytest.mark.parametrize("card_code", CARDS)
def test_ai_only_uses_legal_actions_and_is_independent_of_opponent_hand(card_code, policy):
    state = _state(card_code)
    # A controlled temporary Blade reduction makes the draw worth the Wait cost.
    state.players["player_1"].manual_modifiers.append(
        ManualModifier(
            modifier_id="audit-reduced-blade",
            modifier_type="blade",
            duration="live",
            created_turn=state.turn_number,
            target_card_instance_id="source-live",
            amount=-(state.cards["source-live"].card.blade or 0),
        )
    )
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    # Isolate the skill decision from the unrelated choice to end Main Phase.
    legal = [a for a in generate_legal_actions(state) if a.action_type == "activate_effect"]
    before = match_state_hash(state)
    decision = controller.choose_action(state, legal, controlled_player_ids={"player_1"})
    changed = state.model_copy(deep=True)
    changed.cards["opponent-secret"].card.name_ja = "different hidden identity"
    changed.cards["opponent-secret"].card.cost = 99
    other = controller.choose_action(changed, legal, controlled_player_ids={"player_1"})
    if policy == "simple_ai_v0":
        assert isinstance(decision, SimpleAIBlocker)
        assert isinstance(other, SimpleAIBlocker)
        action = _activation(state, card_code)
    else:
        assert isinstance(decision, SimpleAIDecision)
        assert decision.action.action_type == "activate_effect"
        assert other.action.payload == decision.action.payload
        action = decision.action
    assert match_state_hash(state) == before
    after = apply_action(state, action).state
    if after.pending_effects:
        choice = controller.choose_action(
            after, generate_legal_actions(after), controlled_player_ids={"player_1"}
        )
        assert isinstance(choice, SimpleAIDecision)
        after = apply_action(after, choice.action).state
    assert not after.pending_effects
    assert after.cards["source-live"].orientation == "wait"
    for viewer, opponent in (("player_1", "player_2"), ("player_2", "player_1")):
        payload = _match_state_payload(
            after, events=[], legal_actions=generate_legal_actions(after), player_id=viewer
        )
        assert all(key not in payload["state"]["cards"] for key in after.players[opponent].hand)


@pytest.mark.parametrize("card_code", CARDS)
def test_legacy_manual_with_existing_structured_prefix_keeps_historical_draw(card_code):
    state = _state(card_code)
    raw = state.effect_definitions[card_code + ":1"].model_dump(mode="json")
    raw.update(
        simulation_support="manual_resolution",
        execution_mode="manual_resolution",
        cost=[],
        choice=None,
        actions=[{"action_type": "draw_card", "amount": 1}],
    )
    state.effect_definitions[card_code + ":1"] = EffectDefinition.model_validate(raw)
    after = apply_action(state, _activation(state, card_code)).state
    assert after.players["player_1"].hand == ["held-0", "held-1", "deck-live-1"]
    assert after.pending_effects[0].effect_id == card_code + ":1"
    assert after.cards["source-live"].orientation == "active"


@pytest.mark.parametrize("card_code", CARDS)
def test_manual_placeholder_does_not_bypass_explicit_registered_wait_cost(card_code):
    state = _state(card_code)
    raw = state.effect_definitions[card_code + ":1"].model_dump(mode="json")
    raw.update(
        simulation_support="manual_resolution",
        execution_mode="manual_resolution",
        choice=None,
        actions=[{"action_type": "manual_resolution"}],
    )
    state.effect_definitions[card_code + ":1"] = EffectDefinition.model_validate(raw)
    after = apply_action(state, _activation(state, card_code)).state
    assert after.cards["source-live"].orientation == "wait"
    assert after.players["player_1"].hand == ["held-0", "held-1"]
    assert after.pending_effects[0].resolution_stage == "after_cost"


def test_similar_but_different_text_is_not_fuzzy_matched():
    row = {"raw_effect_text_ja": "【起動】このメンバーをウェイトにする：カードを3枚引く。"}
    assert _activated_wait_draw_then_discard(row) is None
