from __future__ import annotations

from pathlib import Path

import pytest

from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, CardDefinition, CardInstance
from test_effect_execution import _minimal_effect_state

CARD_CODES = ("PL!-PR-015", "PL!SP-PR-020")
TEXT_HASH = "33aa98797222c47c047413845271fdc26a493ceab414094984e4b97c39cd4a6d"
CONDITION = {"requires_baton_touch": True, "replacement_member_cost_less_than_source": True}


def _effect(code):
    return next(effect for effect in load_effect_registry().effects if effect.card_code == code)


def _state(code, old_cost):
    effect = _effect(code)
    state = _minimal_effect_state(effect)
    state.phase = "first_main"
    state.pending_effects = []
    state.players["player_1"].live_area = []
    source = state.cards["source-live"]
    source.card = CardDefinition(
        card_code=code, card_id=code, name_ja="登場能力のメンバー", card_type="member", cost=17,
        raw_effect_text_ja=effect.label_ja, effect_ids=[effect.effect_id],
    )
    source.face_up = False
    state.cards["previous"] = CardInstance(
        instance_id="previous", owner_id="player_1",
        card=CardDefinition(card_code="OLD", card_id="OLD", name_ja="前のメンバー", card_type="member", cost=old_cost),
    )
    player = state.players["player_1"]
    player.member_area["center"] = "previous"
    player.hand = ["source-live"]
    for index in range(17):
        instance_id = f"energy-{index}"
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id, owner_id="player_1",
            card=CardDefinition(card_code="E", card_id="E", name_ja="エネルギー", card_type="energy"),
        )
        player.energy_area.append(instance_id)
    return state


@pytest.mark.parametrize("code", CARD_CODES)
@pytest.mark.parametrize("baton,old_cost,should_prompt", [(False, 16, False), (True, 16, True), (True, 17, False), (True, 18, False)])
def test_manual_prompt_requires_actual_baton_from_strictly_lower_cost(code, baton, old_cost, should_prompt):
    state = _state(code, old_cost)
    before = state.model_dump(mode="json")
    payment = max(0, 17 - old_cost) if baton else 17
    request = ActionRequest(
        action_type="play_member", expected_revision=state.revision, player_id="player_1",
        payload={"card_instance_id": "source-live", "slot": "center", "use_baton_touch": baton,
                 "energy_instance_ids": [f"energy-{index}" for index in range(payment)]},
    )
    result = apply_action(state, request)
    assert bool(result.state.pending_effects) is should_prompt
    assert state.model_dump(mode="json") == before
    assert result.state.players["player_1"].member_area["center"] == "source-live"
    assert "previous" in result.state.players["player_1"].waiting_room
    assert sum(card.orientation == "wait" for key, card in result.state.cards.items() if key.startswith("energy-")) == payment
    restored = type(state).model_validate_json(state.model_dump_json())
    assert apply_action(restored, request).state.model_dump(mode="json") == result.state.model_dump(mode="json")
    if should_prompt:
        pending = result.state.pending_effects[0]
        assert pending.trigger_data["used_baton_touch"] is True
        assert pending.trigger_data["replacement_card_instance_id"] == "previous"
        assert any(action.action_type == "manual_adjustment" for action in generate_legal_actions(result.state))


@pytest.mark.parametrize("code", CARD_CODES)
def test_baton_hand_deploy_stays_manual_with_exact_revision_and_known_condition(code):
    effect = _effect(code)
    assert effect.raw_text_hash == TEXT_HASH
    assert effect.text_revision_id == {"PL!-PR-015": 723, "PL!SP-PR-020": 775}[code]
    assert effect.effect_index == 1
    assert effect.condition == CONDITION
    assert effect.simulation_support == "manual_resolution"
    assert effect.execution_mode == "manual_resolution"
    assert [action.action_type for action in effect.actions] == ["manual_resolution"]
    assert effect.choice is None


def test_candidate_generation_does_not_restore_unsafe_empty_stage_executor():
    database = Path(__file__).parents[1] / "data/loveca.sqlite3"
    if not database.exists():
        pytest.skip("full local card database is required for candidate identity checks")
    candidates = discover_effect_candidates(database, include_registered=True)
    matching = [effect for effect in candidates if effect.card_code in CARD_CODES]
    assert {effect.card_code for effect in matching} == set(CARD_CODES)
    for candidate in matching:
        assert candidate.raw_text_hash == TEXT_HASH
        assert candidate.condition == CONDITION
        assert candidate.simulation_support == "manual_resolution"
        assert candidate.execution_mode == "manual_resolution"
        assert candidate.actions == [{"action_type": "manual_resolution"}]


def test_manual_prompt_can_be_declined_but_cannot_be_misrepresented_as_executable():
    state = _state(CARD_CODES[0], 16)
    state = apply_action(state, ActionRequest(
        action_type="play_member", expected_revision=state.revision, player_id="player_1",
        payload={"card_instance_id": "source-live", "slot": "center", "use_baton_touch": True,
                 "energy_instance_ids": ["energy-0"]},
    )).state
    pending = state.pending_effects[0]
    before = state.model_dump(mode="json")
    resolve = ActionRequest(action_type="resolve_effect", expected_revision=state.revision, player_id="player_1",
                            payload={"invocation_id": pending.invocation_id, "accepted": True})
    with pytest.raises(IllegalActionError, match="ManualAdjustmentAction"):
        apply_action(state, resolve)
    assert state.model_dump(mode="json") == before
    result = apply_action(state, resolve.model_copy(update={"payload": {"invocation_id": pending.invocation_id, "accepted": False}}))
    assert not result.state.pending_effects
    assert any(event.event_type == "effect_declined" for event in result.events)
    assert result.state.players["player_1"].hand == state.players["player_1"].hand


@pytest.mark.parametrize("code", CARD_CODES)
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1"])
def test_ai_declines_optional_manual_deployment_without_faking_state_changes(code, policy):
    from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
    state = _state(code, 16)
    player = state.players["player_1"]
    player.main_deck.remove("deck-member-1")
    player.hand.append("deck-member-1")
    state.cards["deck-member-1"].card.cost = 4
    state = apply_action(state, ActionRequest(
        action_type="play_member", expected_revision=state.revision, player_id="player_1",
        payload={"card_instance_id": "source-live", "slot": "center", "use_baton_touch": True,
                 "energy_instance_ids": ["energy-0"]},
    )).state
    decision = SimpleAIController(SimpleAIPolicy(policy_version=policy)).choose_action(
        state, generate_legal_actions(state), controlled_player_ids={"player_1"},
    )
    assert isinstance(decision, SimpleAIDecision)
    assert decision.action.action_type == "resolve_effect"
    assert decision.action.payload["accepted"] is False
    result = apply_action(state, decision.action)
    assert "deck-member-1" in result.state.players["player_1"].hand
    assert not result.state.pending_effects
    assert any(event.event_type == "effect_declined" for event in result.events)
    assert not any(event.event_type.startswith("effect_member_deployed") for event in result.events)
    restored = type(state).model_validate_json(state.model_dump_json())
    assert apply_action(restored, decision.action).state.model_dump(mode="json") == result.state.model_dump(mode="json")


def test_gap_report_explains_why_old_deployment_registration_is_not_restored():
    from tools.ai_sandbox.effect_gap_report import build_effect_gap_report
    report = build_effect_gap_report(database_path=None, top=500)
    group = next(group for group in report["top_manual_patterns"] if "PL!-PR-015:1" in group["sample_effect_ids"])
    assert group["count"] == 2
    assert set(group["sample_effect_ids"]) == {f"{code}:1" for code in CARD_CODES}
    assert group["unresolved_reason"] == "member_deployment_area_orientation_ui_ai_not_rules_conformant"
    assert group["suggested_next_step"] == "implement_rule_9_6_2_1_2_deployment_then_revalidate_exact_text"


def test_baton_condition_compares_card_cost_not_discounted_payment():
    from loveca.simulation.effects import EffectDefinition
    state = _state(CARD_CODES[0], 16)
    discount = EffectDefinition(
        effect_id="test-cost-reduction:1", card_code=CARD_CODES[0], text_revision_id=1,
        raw_text_hash="d" * 64, effect_index=2, label_ja="コスト軽減のテスト",
        effect_type="static", timing="static_always", trigger="static_always",
        execution_mode="auto_resolve", frequency_limit="none", is_optional=False,
        actions=[{"action_type": "reduce_play_cost", "amount": 2}],
        simulation_support="test_validated_executable", review_status="test_validated", source_reference="test",
    )
    state.effect_definitions[discount.effect_id] = discount
    state.cards["source-live"].card.effect_ids.append(discount.effect_id)
    result = apply_action(state, ActionRequest(
        action_type="play_member", expected_revision=state.revision, player_id="player_1",
        payload={"card_instance_id": "source-live", "slot": "center", "use_baton_touch": True,
                 "energy_instance_ids": []},
    ))
    assert result.state.pending_effects[0].effect_id == f"{CARD_CODES[0]}:1"
    played = next(event for event in result.events if event.event_type == "member_played")
    assert played.data["payment_cost"] == 0


def test_gap_report_has_no_remaining_executable_orientation_gaps(tmp_path):
    from tools.ai_sandbox.effect_gap_report import build_effect_gap_report, write_gap_outputs
    report = build_effect_gap_report(database_path=None, top=500)
    warnings = report["executable_audit_warnings"]
    assert warnings == []
    write_gap_outputs(tmp_path, report)
    assert (tmp_path / "effect-gap-report.md").is_file()


def test_manual_deploy_prompt_does_not_expose_hand_targets_to_opponent():
    from loveca.webapp import _match_state_payload
    state = _state(CARD_CODES[0], 16)
    player = state.players["player_1"]
    player.main_deck.remove("deck-member-1")
    player.hand.append("deck-member-1")
    state = apply_action(state, ActionRequest(
        action_type="play_member", expected_revision=state.revision, player_id="player_1",
        payload={"card_instance_id": "source-live", "slot": "center", "use_baton_touch": True,
                 "energy_instance_ids": ["energy-0"]},
    )).state
    legal = generate_legal_actions(state)
    before = state.model_dump(mode="json")
    own = _match_state_payload(state, events=[], legal_actions=legal, player_id="player_1")
    other = _match_state_payload(state, events=[], legal_actions=legal, player_id="player_2")
    assert "deck-member-1" in own["state"]["cards"]
    assert "deck-member-1" not in other["state"]["cards"]
    assert "source-live" in other["state"]["cards"]
    assert other["legal_actions"] == []
    assert state.model_dump(mode="json") == before
