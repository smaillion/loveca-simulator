from contextlib import closing
from functools import lru_cache
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_effect_execution import _minimal_effect_state

from loveca.db.bootstrap import connect_database
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import (
    ActionRequest,
    CardDefinition,
    CardInstance,
    GameEvent,
    MatchState,
)
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!N-bp7-006"
EFFECT = CODE + ":1"
RULE_REFERENCE_IDS = ("9.4.1", "9.4.2.3", "9.6.3.1", "10.2.2.2", "10.2.3")


@lru_cache
def _candidate():
    return next(
        c
        for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
        if c.effect_id == EFFECT
    )


def _state():
    effect = EffectDefinition.model_validate(_candidate().to_registry_entry())
    definitions = {e.effect_id: e for e in load_effect_registry().effects if e.card_code == CODE}
    definitions[EFFECT] = effect
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        card = _load_definition(connection, CODE, None, definitions, {})
    assert (
        card.raw_text_hash == effect.raw_text_hash
        and card.text_revision_id == effect.text_revision_id
    )
    assert not card.effect_registry_errors
    state = _minimal_effect_state(effect)
    state.effect_definitions = definitions
    state.pending_effects = []
    state.phase = "first_main"
    state.cards["source-live"].card = card
    player = state.players["player_1"]
    player.live_area = []
    player.member_area["center"] = "source-live"
    template = state.cards["deck-member-1"]
    player.main_deck = []
    for index in range(6):
        key = f"top-{index}"
        state.cards[key] = template.model_copy(update={"instance_id": key}, deep=True)
        player.main_deck.append(key)
    state.cards["held"] = template.model_copy(update={"instance_id": "held"}, deep=True)
    player.hand = ["held"]
    state.cards["opponent-secret"] = template.model_copy(
        update={"instance_id": "opponent-secret", "owner_id": "player_2"}, deep=True
    )
    state.players["player_2"].hand = ["opponent-secret"]
    for index in range(2):
        key = f"energy-{index}"
        state.cards[key] = CardInstance(
            instance_id=key,
            owner_id="player_1",
            card=CardDefinition(
                card_code="AUDIT-ENERGY", card_id=key, name_ja="Energy", card_type="energy"
            ),
        )
        player.energy_area.append(key)
    return state


def _activate(state, energy_ids=None):
    return ActionRequest(
        action_type="activate_effect",
        player_id="player_1",
        expected_revision=state.revision,
        payload={
            "effect_id": EFFECT,
            "source_card_instance_id": "source-live",
            "energy_instance_ids": ["energy-0"] if energy_ids is None else energy_ids,
        },
    )


def _begin(state):
    activated = apply_action(state, _activate(state))
    state = activated.state
    if state.pending_choice is None:
        state = apply_action(
            state,
            ActionRequest(
                action_type="resolve_effect",
                player_id="player_1",
                expected_revision=state.revision,
                payload={"invocation_id": state.pending_effects[0].invocation_id},
            ),
        ).state
    return state


def _finish(state, order):
    return ActionRequest(
        action_type="resolve_effect_choice",
        player_id="player_1",
        expected_revision=state.revision,
        payload={"selected_card_instance_ids": order, "ordered_card_instance_ids": order},
    )


def test_real_exact_binding_and_existing_inspection_operations():
    state = _state()
    effect = state.effect_definitions[EFFECT]
    assert effect.frequency_limit == "once_per_turn"
    assert effect.label_ja in state.cards["source-live"].card.raw_effect_text_ja
    assert [op.action_type for op in effect.actions] == [
        "inspect_top_cards",
        "reorder_deck_top",
        "move_remaining_cards",
    ]
    assert effect.choice.minimum == effect.choice.maximum == effect.choice.amount == 4
    assert effect.choice.unselected_destination is None


def test_activation_pays_once_and_reorders_all_four_without_draw_or_reveal():
    initial = _state()
    before = match_state_hash(initial)
    state = _begin(initial)
    assert state.cards["energy-0"].orientation == "wait"
    assert state.cards["energy-1"].orientation == "active"
    assert state.cards["source-live"].orientation == "active"
    assert state.players["player_1"].hand == ["held"]
    assert state.pending_choice.options["inspected_card_instance_ids"] == [
        "top-0",
        "top-1",
        "top-2",
        "top-3",
    ]
    assert state.players["player_1"].main_deck == ["top-4", "top-5"]
    order = ["top-3", "top-1", "top-0", "top-2"]
    result = apply_action(state, _finish(state, order))
    after = result.state
    assert after.players["player_1"].main_deck == order + ["top-4", "top-5"]
    assert after.players["player_1"].hand == ["held"]
    assert after.players["player_1"].waiting_room == []
    assert after.players["player_1"].resolution_area == []
    assert not after.pending_effects and after.pending_choice is None
    assert all(after.cards[key].face_up is False for key in order)
    assert not any(e.event_type in {"cards_drawn", "cards_revealed"} for e in result.events)
    assert not any(
        entry["effect_id"] == EFFECT
        for a in generate_legal_actions(after)
        if a.action_type == "activate_effect"
        for entry in a.options["activations"]
    )
    assert match_state_hash(initial) == before


@pytest.mark.parametrize(
    "ids", [[], ["energy-0", "energy-1"], ["energy-0", "energy-0"], ["held"], ["opponent-secret"]]
)
def test_invalid_energy_payment_does_not_inspect_or_change_state(ids):
    state = _state()
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _activate(state, ids))
    assert match_state_hash(state) == before


@pytest.mark.parametrize(
    "phase,active",
    [
        ("setup_mulligan_first", "player_1"),
        ("performance_first", "player_1"),
        ("second_main", "player_2"),
    ],
)
def test_wrong_timing_rejected_without_payment(phase, active):
    state = _state()
    state.phase, state.active_player_id = phase, active
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _activate(state))
    assert match_state_hash(state) == before


@pytest.mark.parametrize(
    "order",
    [
        [],
        ["top-0"],
        ["top-0", "top-1", "top-2"],
        ["top-0", "top-1", "top-2", "top-2"],
        ["top-0", "top-1", "top-2", "opponent-secret"],
    ],
)
def test_incomplete_or_illegal_order_is_atomic_after_payment(order):
    state = _begin(_state())
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _finish(state, order))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("available", [0, 1, 2, 3])
def test_short_deck_uses_available_cards_and_never_discards_them(available):
    initial = _state()
    initial.players["player_1"].main_deck = initial.players["player_1"].main_deck[:available]
    state = _begin(initial)
    inspected = state.pending_choice.options["inspected_card_instance_ids"]
    assert len(inspected) == available
    order = list(reversed(inspected))
    after = apply_action(state, _finish(state, order)).state
    assert after.players["player_1"].main_deck == order
    assert not after.players["player_1"].waiting_room
    assert after.cards["energy-0"].orientation == "wait"
    assert not after.pending_effects and after.pending_choice is None


def test_refresh_when_inspection_needs_four_is_deterministic():
    initial = _state()
    initial.players["player_1"].waiting_room = ["top-2", "top-3", "top-4"]
    initial.players["player_1"].main_deck = ["top-0", "top-1"]
    first, repeated = _begin(initial), _begin(initial.model_copy(deep=True))
    assert first.pending_choice.options == repeated.pending_choice.options
    inspected = first.pending_choice.options["inspected_card_instance_ids"]
    assert len(inspected) == 4
    assert set(inspected) <= {f"top-{i}" for i in range(5)}
    assert not first.players["player_1"].waiting_room
    after = apply_action(first, _finish(first, list(reversed(inspected)))).state
    assert len(after.players["player_1"].main_deck) == 5


def test_private_inspected_cards_only_visible_to_owner():
    initial = _state()
    result = apply_action(initial, _activate(initial))
    state = result.state
    inspected = state.pending_choice.options["inspected_card_instance_ids"]
    own = _match_state_payload(
        state,
        events=result.events,
        legal_actions=generate_legal_actions(state),
        player_id="player_1",
    )
    other = _match_state_payload(
        state,
        events=result.events,
        legal_actions=generate_legal_actions(state),
        player_id="player_2",
    )
    assert all(key in own["state"]["cards"] for key in inspected)
    assert all(key not in other["state"]["cards"] for key in inspected)
    assert not other["state"]["pending_choice"]["options"]
    assert all(key not in str(other["events"]) for key in inspected)
    assert all(key in str(own["events"]) for key in inspected)
    resolved = apply_action(state, _finish(state, list(reversed(inspected))))
    other = _match_state_payload(
        resolved.state,
        events=resolved.events,
        legal_actions=resolved.legal_actions,
        player_id="player_2",
    )
    assert all(key not in str(other["events"]) for key in inspected)
    assert all(key in str([event.model_dump() for event in resolved.events]) for key in inspected)


@pytest.mark.parametrize("reveal", [False, True])
def test_event_redaction_preserves_explicit_reveal_and_raw_history(reveal):
    state = _state()
    event = GameEvent(
        event_type="effect_resolved",
        player_id="player_1",
        data={
            "inspected_card_instance_ids": ["secret", "public"],
            "selected_card_instance_ids": ["public"],
            "ordered_card_instance_ids": ["secret"],
            "unselected_card_instance_ids": ["secret"],
            "reveal_selected_to_opponent": reveal,
            "revealed_cards": [{"instance_id": "public", "card_code": "PUBLIC"}] if reveal else [],
        },
    )
    before = event.model_dump()
    other = _match_state_payload(state, events=[event], legal_actions=[], player_id="player_2")
    visible = other["events"][0]["data"]
    assert "secret" not in str(visible)
    assert visible["revealed_cards"] == before["data"]["revealed_cards"]
    assert ("selected_card_instance_ids" in visible) is reveal
    assert event.model_dump() == before
    for viewer in (None, "player_1"):
        payload = _match_state_payload(state, events=[event], legal_actions=[], player_id=viewer)
        assert payload["events"] == [before]


def test_actual_sqlite_replay_and_old_manual_snapshot(tmp_path):
    initial = _state()
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(initial, card_database_path=Path("data/loveca.sqlite3"))
    state = repo.apply(initial.match_id, _activate(initial)).state
    if state.pending_choice is None:
        state = repo.apply(
            state.match_id,
            ActionRequest(
                action_type="resolve_effect",
                player_id="player_1",
                expected_revision=state.revision,
                payload={"invocation_id": state.pending_effects[0].invocation_id},
            ),
        ).state
    inspected = state.pending_choice.options["inspected_card_instance_ids"]
    result = repo.apply(state.match_id, _finish(state, list(reversed(inspected))))
    assert repo.replay(state.match_id)["final_state"] == result.state.model_dump()
    assert MatchState.model_validate_json(result.state.model_dump_json()) == result.state
    legacy = _state()
    raw = legacy.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(
        simulation_support="manual_resolution",
        execution_mode="manual_resolution",
        condition={"source_zone": "stage"},
        cost=[],
        choice=None,
        actions=[{"action_type": "manual_resolution"}],
    )
    legacy.effect_definitions[EFFECT] = EffectDefinition.model_validate(raw)
    after = apply_action(legacy, _activate(legacy, [])).state
    assert after.pending_effects and after.pending_choice is None
    assert after.cards["energy-0"].orientation == "active"


@pytest.mark.parametrize(
    "policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"]
)
def test_ai_resolves_native_inspection_without_opponent_hidden_information(policy):
    state = _begin(_state())
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    legal = generate_legal_actions(state)
    decision = controller.choose_action(state, legal, controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision)
    changed = state.model_copy(deep=True)
    changed.cards["opponent-secret"].card.cost = 99
    other = controller.choose_action(changed, legal, controlled_player_ids={"player_1"})
    assert other.action.payload == decision.action.payload
    after = apply_action(state, decision.action).state
    assert after.pending_choice is None and not after.pending_effects
    assert len(after.players["player_1"].main_deck) == 6
    assert after.cards["energy-1"].orientation == "active"


def test_unflagged_legacy_inspection_keeps_serialization_and_previous_rejection(tmp_path):
    state = _state()
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw["choice"].pop("inspection_activation_policy")
    state.effect_definitions[EFFECT] = EffectDefinition.model_validate(raw)
    assert state.effect_definitions[EFFECT].model_dump(mode="json") == raw
    restored = MatchState.model_validate_json(state.model_dump_json())
    assert match_state_hash(state) == match_state_hash(restored)
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError, match="unsupported effect operation: inspect_top_cards"):
        apply_action(state, _activate(state))
    assert match_state_hash(state) == before
    repo = MatchRepository(tmp_path / "legacy.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    assert repo.replay(state.match_id)["final_state"] == state.model_dump()


@pytest.mark.parametrize(
    "invalid",
    [
        "wrong_choice",
        "partial_selection",
        "public_reveal",
        "wrong_destination",
        "manual",
        "triggered",
        "wrong_cost",
        "wrong_actions",
        "cost_choice",
    ],
)
def test_policy_rejects_unsupported_contracts(invalid):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    if invalid == "wrong_choice":
        raw["choice"]["choice_type"] = "card_from_zone"
    elif invalid == "partial_selection":
        raw["choice"]["minimum"] = 0
    elif invalid == "public_reveal":
        raw["choice"]["reveal_selected_to_opponent"] = True
    elif invalid == "wrong_destination":
        raw["choice"]["selected_destination"] = "hand"
    elif invalid == "manual":
        raw["simulation_support"] = "manual_resolution"
    elif invalid == "triggered":
        raw["effect_type"] = "triggered"
    elif invalid == "wrong_cost":
        raw["cost"] = []
    elif invalid == "wrong_actions":
        raw["actions"] = [{"action_type": "draw_card", "amount": 4}]
    else:
        raw["cost_choice"] = raw["choice"]
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)
