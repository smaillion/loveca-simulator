from __future__ import annotations

from pathlib import Path

import pytest

from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, StaleRevisionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, CardDefinition, CardInstance
from test_effect_execution import _minimal_effect_state


def _effect():
    return EffectDefinition(
        effect_id="cost-branch:2", card_code="TEST", text_revision_id=1,
        raw_text_hash="a" * 64, effect_index=2, label_ja="費用による分岐",
        effect_type="activated", timing="activated_main", trigger="player_activation",
        execution_mode="prompt_then_resolve", frequency_limit="once_per_turn",
        is_optional=False, condition={"source_zone": "stage", "minimum_active_energy": 2},
        cost=[{"action_type": "pay_energy", "amount": 2}, {"action_type": "discard_from_hand"}],
        cost_choice={"choice_type": "card_from_zone", "zone": "hand", "minimum": 1, "maximum": 1},
        choice={
            "choice_type": "choose_effect_branch",
            "branch_ids": ["discarded_muse", "discarded_other"],
            "auto_branch_from_cost_choice": True,
            "branch_cost_conditions": {
                "discarded_muse": {"selected_cost_has_work_key": "love_live"},
                "discarded_other": {"selected_cost_lacks_work_key": "love_live"},
            },
            "branch_selection_minimum": {"discarded_other": 1},
            "branch_selection_maximum": {"discarded_other": 1},
            "branch_choice_filters": {
                "discarded_muse": {
                    "choice_type": "inspect_top_select", "amount": 4, "minimum": 2, "maximum": 2,
                    "selected_destination": "hand", "unselected_destination": "waiting_room",
                },
                "discarded_other": {
                    "choice_type": "card_from_zone", "zone": "waiting_room", "card_type": "live",
                    "minimum": 1, "maximum": 1,
                },
            },
        },
        actions=[
            {"action_type": "inspect_top_cards", "amount": 4, "branch": "discarded_muse"},
            {"action_type": "select_to_hand_from_inspected", "branch": "discarded_muse"},
            {"action_type": "move_remaining_cards", "branch": "discarded_muse"},
            {"action_type": "return_from_waiting_room", "branch": "discarded_other"},
        ],
        simulation_support="test_validated_executable", review_status="test_validated",
        source_reference="Official card text; rules 1.3.2 / 9.4.2 / 9.6.2.3",
    )


def _state(work="love_live", *, discard_live=False, waiting=True):
    effect = _effect()
    state = _minimal_effect_state(effect)
    state.phase = "first_main"
    state.pending_effects = []
    state.cards["source-live"].card = CardDefinition(
        card_code="TEST", card_id="TEST", name_ja="分岐メンバー", card_type="member",
        effect_ids=[effect.effect_id],
    )
    state.cards["cost"] = CardInstance(instance_id="cost", owner_id="player_1", card=CardDefinition(
        card_code="COST", card_id="COST", name_ja="費用", card_type="live" if discard_live else "member",
        work_keys=[work],
    ))
    for i in range(2):
        state.cards[f"energy-{i}"] = CardInstance(
            instance_id=f"energy-{i}", owner_id="player_1",
            card=CardDefinition(card_code="ENERGY", card_id="ENERGY", name_ja="E", card_type="energy"),
        )
    state.cards["deck-four"] = state.cards["deck-member-1"].model_copy(
        update={"instance_id": "deck-four"}, deep=True,
    )
    player = state.players["player_1"]
    player.member_area["center"] = "source-live"
    player.hand = ["cost"]
    player.live_area = []
    player.energy_area = ["energy-0", "energy-1"]
    player.main_deck.append("deck-four")
    player.waiting_room = ["live-1"] if waiting else []
    return state


def _action(state, action_type, **payload):
    return ActionRequest(action_type=action_type, expected_revision=state.revision,
                         player_id="player_1", payload=payload)


def _activate(state, **payload):
    return apply_action(state, _action(state, "activate_effect", effect_id="cost-branch:2",
                                      source_card_instance_id="source-live", **payload)).state


def _pay(state, **payload):
    return apply_action(state, _action(state, "resolve_effect",
        invocation_id=state.pending_effects[0].invocation_id, selected_card_instance_ids=["cost"],
        energy_instance_ids=["energy-0", "energy-1"], **payload))


def test_paid_muse_card_determines_inspection_and_only_that_branch_executes():
    initial = _activate(_state())
    before = initial.model_dump(mode="json")
    result = _pay(initial)
    state = result.state
    assert initial.model_dump(mode="json") == before
    assert state.pending_effects[0].trigger_data["selected_branch"] == "discarded_muse"
    assert state.pending_choice.choice_type == "effect_inspection_selection"
    assert state.pending_choice.options["minimum"] == 2
    assert state.pending_choice.options["maximum"] == 2
    assert "cost" in state.players["player_1"].waiting_room
    assert all(state.cards[x].orientation == "wait" for x in ["energy-0", "energy-1"])
    assert sum(event.event_type == "effect_cost_paid" for event in result.events) == 1
    selected = state.pending_choice.options["candidate_card_instance_ids"][:2]
    final = apply_action(state, _action(state, "resolve_effect_choice", selected_card_instance_ids=selected)).state
    assert final.players["player_1"].hand == selected
    assert "live-1" in final.players["player_1"].waiting_room
    assert len(final.players["player_1"].waiting_room) == 4
    assert not final.pending_effects and final.pending_choice is None
    assert not any(a.action_type == "activate_effect" for a in generate_legal_actions(final))


@pytest.mark.parametrize("waiting,discard_live,expected", [(True, False, 1), (False, False, 0), (False, True, 1)])
def test_other_branch_uses_post_cost_waiting_room_and_requires_available_live(waiting, discard_live, expected):
    state = _pay(_activate(_state("nijigasaki", waiting=waiting, discard_live=discard_live))).state
    assert state.pending_choice is None
    options = next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect").options["invocations"][0]
    assert options["selected_branch"] == "discarded_other"
    assert options["card_selection_minimum"] == expected
    candidates = options["candidate_card_instance_ids"]
    assert len(candidates) == expected
    if expected:
        with pytest.raises(IllegalActionError):
            apply_action(state, _action(state, "resolve_effect", invocation_id=state.pending_effects[0].invocation_id))
    final = apply_action(state, _action(state, "resolve_effect", invocation_id=state.pending_effects[0].invocation_id,
                                      selected_card_instance_ids=candidates)).state
    assert final.players["player_1"].hand == candidates
    assert not final.pending_effects


@pytest.mark.parametrize("payload", [
    {"selected_branch": "discarded_other"}, {"energy_instance_ids": ["energy-0"]},
    {"selected_card_instance_ids": ["missing"]}, {"selected_card_instance_ids": ["cost", "cost"]},
])
def test_invalid_cost_or_forged_branch_is_atomic(payload):
    state = _activate(_state())
    before = state.model_dump(mode="json")
    request = {"invocation_id": state.pending_effects[0].invocation_id,
               "selected_card_instance_ids": ["cost"], "energy_instance_ids": ["energy-0", "energy-1"], **payload}
    with pytest.raises(IllegalActionError):
        apply_action(state, _action(state, "resolve_effect", **request))
    assert state.model_dump(mode="json") == before


def test_inline_activation_cost_and_serialized_replay_take_same_branch():
    state = _state()
    request = _action(state, "activate_effect", effect_id="cost-branch:2", source_card_instance_id="source-live",
                      selected_card_instance_ids=["cost"], energy_instance_ids=["energy-0", "energy-1"])
    first = apply_action(state, request).state
    restored = type(state).model_validate_json(state.model_dump_json())
    replayed = apply_action(restored, request).state
    assert first.pending_choice is not None
    assert first.model_dump(mode="json") == replayed.model_dump(mode="json")


def test_exact_candidate_and_registry_identity_preserve_static_segment():
    from loveca.simulation.effect_candidates import discover_effect_candidates
    from loveca.simulation.effects import load_effect_registry
    root = Path(__file__).parents[1]
    if not (root / "data/loveca.sqlite3").exists():
        pytest.skip("full local card database is required for exact candidate validation")
    candidates = discover_effect_candidates(root / "data/loveca.sqlite3", include_registered=True)
    candidate = next(x for x in candidates if x.effect_id == "PL!-bp5-003:2")
    assert candidate.choice["auto_branch_from_cost_choice"] is True
    registry = load_effect_registry()
    effect = next(x for x in registry.effects if x.effect_id == candidate.effect_id)
    assert effect.effect_index == 2 and effect.text_revision_id == candidate.text_revision_id
    assert effect.raw_text_hash == candidate.raw_text_hash
    expected = EffectDefinition.model_validate(candidate.to_registry_entry())
    assert effect.actions == expected.actions
    assert effect.cost == expected.cost and effect.choice == expected.choice
    assert effect.simulation_support == "test_validated_executable"
    static = next(x for x in registry.effects if x.effect_id == "PL!-bp5-003:1")
    assert static.effect_type == "static" and static.trigger == "static_always"
    assert static.raw_text_hash == "e4736c87b50acd3129afbe1de6e1845496a08c41dfe1c08ca61951edb60653d7"


@pytest.mark.parametrize("work", ["love_live", "nijigasaki"])
def test_real_registered_cost_effect_completes_both_branches(work):
    from loveca.simulation.effects import load_effect_registry
    from loveca.simulation.ai import SimpleAIController, SimpleAIDecision
    effect = next(x for x in load_effect_registry().effects if x.effect_id == "PL!-bp5-003:2")
    state = _state(work)
    state.effect_definitions = {effect.effect_id: effect}
    state.cards["source-live"].card.effect_ids = [effect.effect_id]
    state = apply_action(state, _action(state, "activate_effect", effect_id=effect.effect_id,
                                       source_card_instance_id="source-live")).state
    for _ in range(3):
        if not state.pending_effects:
            break
        decision = SimpleAIController().choose_action(
            state, generate_legal_actions(state), controlled_player_ids={"player_1"},
        )
        assert isinstance(decision, SimpleAIDecision)
        state = apply_action(state, decision.action).state
    assert not state.pending_effects and state.pending_choice is None
    assert len(state.players["player_1"].hand) == (2 if work == "love_live" else 1)
    assert "cost" in state.players["player_1"].waiting_room


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1"])
@pytest.mark.parametrize("work", ["love_live", "nijigasaki"])
def test_ai_resolves_both_cost_branches_legally_and_replayably(policy, work):
    from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
    initial = _activate(_state(work))
    state = initial
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    actions = []
    for _ in range(4):
        if not state.pending_effects:
            break
        decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
        assert isinstance(decision, SimpleAIDecision)
        assert decision.action.action_type in {"resolve_effect", "resolve_effect_choice"}
        if len(actions) == 0:
            assert decision.action.payload["selected_card_instance_ids"] == ["cost"]
            assert "selected_branch" not in decision.action.payload
        actions.append(decision.action)
        state = apply_action(state, decision.action).state
    assert not state.pending_effects and state.pending_choice is None
    replay = type(initial).model_validate_json(initial.model_dump_json())
    for action in actions:
        replay = apply_action(replay, action).state
    assert replay.model_dump(mode="json") == state.model_dump(mode="json")


def test_inspected_cards_are_private_to_owner_in_online_ai_and_agent_views():
    from loveca.webapp import _match_state_payload
    from loveca.simulation.rule_evaluation import build_ai_observation
    from tools.ai_sandbox.semantic_playtest import build_api_play_context
    state = _pay(_activate(_state())).state
    inspected = state.pending_choice.options["inspected_card_instance_ids"]
    actions = generate_legal_actions(state)
    own = _match_state_payload(state, events=[], legal_actions=actions, player_id="player_1")
    other = _match_state_payload(state, events=[], legal_actions=actions, player_id="player_2")
    assert all(item in own["state"]["cards"] for item in inspected)
    assert all(item not in other["state"]["cards"] for item in inspected)
    assert other["state"]["pending_choice"]["options"] == {}
    view = build_ai_observation(state, "player_2", actions)
    assert all(item not in view.cards for item in inspected)
    from loveca.simulation.models import LegalAction
    other_context = build_api_play_context(state, [LegalAction(
        action_type="advance_phase", player_id="player_2", label_ja="待機", label_zh="等待",
    )])
    assert other_context["players"]["player_1"]["resolution_area"] == []
    assert state.pending_choice.options["inspected_card_instance_ids"] == inspected
    changed = state.model_copy(deep=True)
    changed.cards[inspected[0]].card = CardDefinition(
        card_code="PRIVATE-DIFFERENT", card_id="PRIVATE-DIFFERENT", card_type="live", name_ja="非公開変更",
    )
    assert build_ai_observation(changed, "player_2", actions) == view
    final = apply_action(state, _action(state, "resolve_effect_choice",
                                       selected_card_instance_ids=inspected[:2])).state
    other_final = _match_state_payload(final, events=[], legal_actions=generate_legal_actions(final), player_id="player_2")
    assert all(item not in other_final["state"]["cards"] for item in inspected[:2])
    assert all(item in other_final["state"]["cards"] for item in inspected[2:])


def test_stale_revision_and_short_inspection_selection_do_not_mutate_state():
    state = _activate(_state())
    request = _action(state, "resolve_effect", invocation_id=state.pending_effects[0].invocation_id,
                      selected_card_instance_ids=["cost"], energy_instance_ids=["energy-0", "energy-1"])
    before = state.model_dump(mode="json")
    with pytest.raises(StaleRevisionError, match="revision"):
        apply_action(state, request.model_copy(update={"expected_revision": state.revision - 1}))
    assert state.model_dump(mode="json") == before
    state = apply_action(state, request).state
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalActionError, match="inspection selection"):
        apply_action(state, _action(state, "resolve_effect_choice", selected_card_instance_ids=[]))
    assert state.model_dump(mode="json") == before


def test_inspection_refreshes_short_deck_before_viewing_and_preserves_existing_top(monkeypatch):
    from loveca.simulation import engine
    state = _activate(_state())
    player = state.players["player_1"]
    player.main_deck = ["deck-live-1", "deck-member-1"]
    player.waiting_room = ["live-1", "deck-live-2", "deck-four"]
    observed_before_take = []
    take = engine._take_main_deck_card

    def record_take(current, player_id, events):
        current_player = current.players[player_id]
        observed_before_take.append((current_player.refresh_count, list(current_player.main_deck)))
        return take(current, player_id, events)

    monkeypatch.setattr(engine, "_take_main_deck_card", record_take)
    result = _pay(state)
    assert observed_before_take[0][0] == 1
    assert observed_before_take[0][1][:2] == ["deck-live-1", "deck-member-1"]
    assert len(observed_before_take[0][1]) == 6
    assert result.state.pending_choice.options["inspected_card_instance_ids"][:2] == ["deck-live-1", "deck-member-1"]
    assert result.state.players["player_1"].refresh_count == 1
    assert sum(event.event_type == "deck_refreshed" for event in result.events) == 1


@pytest.mark.parametrize("changes", [
    {"branch_cost_conditions": {}},
    {"branch_cost_conditions": {"discarded_muse": {"bad": "x"}, "discarded_other": {"bad": "x"}}},
    {"branch_cost_conditions": {"discarded_muse": {"selected_cost_has_work_key": "a"},
                                "discarded_other": {"selected_cost_lacks_work_key": "b"}}},
])
def test_cost_result_branch_metadata_rejects_unknown_or_noncomplementary_conditions(changes):
    from pydantic import ValidationError
    payload = _effect().model_dump()
    payload["choice"].update(changes)
    with pytest.raises(ValidationError, match="cost result branch"):
        EffectDefinition.model_validate(payload)
