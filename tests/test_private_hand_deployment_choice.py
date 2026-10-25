import json
from pathlib import Path

import pytest
from test_occupied_effect_deployment import ROOT, _request, _state

from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, MatchState
from loveca.simulation.online import match_state_hash

POLICY = "private_filtered_may_choose_none"
RULE_REFERENCE_IDS = ("9.6.3.1.4", "9.6.2.3", "9.6.2.4.2.1")


def _private_state(*, target=True):
    state = _state("hand")
    raw = state.effect_definitions[ROOT].model_dump()
    raw["choice"]["selection_policy"] = POLICY
    state.effect_definitions[ROOT] = EffectDefinition.model_validate(raw)
    if not target:
        state.players["player_1"].hand.remove("target")
        state.players["player_1"].main_deck.append("target")
    return state


@pytest.mark.parametrize("target", [True, False])
def test_private_filtered_hand_can_resolve_without_target_and_still_pay(target):
    state = _private_state(target=target)
    legal = next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect")
    choice = legal.options["invocations"][0]
    assert choice["card_selection_minimum"] == 0
    assert choice["selection_policy"] == POLICY
    player = state.players["player_1"].model_copy(deep=True)
    result = apply_action(state, _request(state, selected_card_instance_ids=[], to_slot=None))
    after = result.state.players["player_1"]
    assert after.hand == player.hand and after.member_area == player.member_area
    assert after.member_area_attachments == player.member_area_attachments
    assert not result.state.pending_effects
    assert all(result.state.cards[i].orientation == "wait" for i in ["energy-0", "energy-1"])
    assert any(e.event_type == "effect_cost_paid" for e in result.events)
    assert any(e.event_type == "effect_resolved" for e in result.events)
    skipped = [e for e in result.events if e.event_type == "effect_operation_not_applied"]
    assert len(skipped) == 1 and skipped[0].data["reason"] == "private_selection_none"
    assert not any(
        e.event_type in {"effect_declined", "effect_skipped_due_to_error"} for e in result.events
    )
    assert MatchState.model_validate_json(result.state.model_dump_json()) == result.state


def test_private_filtered_hand_can_still_select_one_member_and_legal_area():
    state = _private_state()
    result = apply_action(state, _request(state))
    assert result.state.players["player_1"].member_area["right"] == "target"
    assert "target" not in result.state.players["player_1"].hand
    assert any(e.event_type == "effect_member_deployed_from_hand" for e in result.events)


def test_no_legal_area_still_allows_zero_without_deploying_or_refunding():
    from test_member_entry_area_history import ENTRY_FIELD

    state = _private_state()
    player = state.players["player_1"]
    setattr(player, ENTRY_FIELD, [i for i in player.member_area.values() if i])
    options = next(
        a for a in generate_legal_actions(state) if a.action_type == "resolve_effect"
    ).options["invocations"][0]
    assert options["candidate_card_instance_ids"] == [] and options["available_slots"] == []
    result = apply_action(state, _request(state, selected_card_instance_ids=[], to_slot=None))
    assert result.state.players["player_1"].member_area == player.member_area
    assert not result.state.pending_effects
    assert any(e.event_type == "effect_cost_paid" for e in result.events)


@pytest.mark.parametrize("target", [True, False])
def test_native_activation_after_cost_none_choice_is_private_and_replayable(tmp_path, target):
    from loveca.simulation.runtime import MatchRepository
    from loveca.webapp import _match_state_payload

    state = _private_state(target=target)
    state.pending_effects = []
    effect = state.effect_definitions[ROOT]
    effect.trigger, effect.timing, effect.effect_type = (
        "player_activation",
        "activated_main",
        "activated",
    )
    effect.condition = {"source_zone": "stage"}
    state.cards["source-live"].card.effect_ids.append(ROOT)
    repository = MatchRepository(tmp_path / "activated.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    started = repository.apply(
        state.match_id,
        ActionRequest(
            action_type="activate_effect",
            player_id="player_1",
            expected_revision=state.revision,
            payload={
                "effect_id": ROOT,
                "source_card_instance_id": "source-live",
                "energy_instance_ids": ["energy-0", "energy-1"],
            },
        ),
    )
    state = repository.get_state(state.match_id)
    assert state.pending_effects[0].resolution_stage == "after_cost"
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(
            state,
            events=started.events,
            legal_actions=generate_legal_actions(state),
            player_id=viewer,
        )
        if viewer == "player_2":
            assert '"target"' not in json.dumps(payload["events"])
        else:
            options = next(
                a for a in payload["legal_actions"] if a["action_type"] == "resolve_effect"
            )
            assert options["options"]["invocations"][0]["card_selection_minimum"] == 0
    result = repository.apply(
        state.match_id,
        ActionRequest(
            action_type="resolve_effect",
            player_id="player_1",
            expected_revision=state.revision,
            payload={
                "invocation_id": state.pending_effects[0].invocation_id,
                "accepted": True,
                "selected_card_instance_ids": [],
            },
        ),
    )
    assert not result.state.pending_effects
    assert not any(e.event_type == "effect_cost_paid" for e in result.events)
    assert all(result.state.cards[i].orientation == "wait" for i in ["energy-0", "energy-1"])
    replay = repository.replay(state.match_id)
    assert replay["final_state"] == result.state.model_dump(mode="json")


def test_optional_decline_is_distinct_from_paying_with_no_target():
    state = _private_state()
    state.effect_definitions[ROOT].is_optional = True
    declined = apply_action(
        state, _request(state, accepted=False, selected_card_instance_ids=[], to_slot=None)
    )
    assert any(e.event_type == "effect_declined" for e in declined.events)
    assert not any(e.event_type == "effect_cost_paid" for e in declined.events)
    assert all(declined.state.cards[i].orientation == "active" for i in ["energy-0", "energy-1"])


@pytest.mark.parametrize(
    "payload",
    [
        {"selected_card_instance_ids": [], "to_slot": "right"},
        {"selected_card_instance_ids": ["target"], "to_slot": None},
        {"selected_card_instance_ids": ["target", "target"]},
        {"selected_card_instance_ids": ["live-1"]},
        {"selected_card_instance_ids": ["opponent-private"]},
        {"selected_card_instance_ids": [], "to_slot": None, "energy_instance_ids": []},
    ],
)
def test_invalid_private_selection_is_atomic(payload):
    state = _private_state()
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalActionError):
        apply_action(state, _request(state, **payload))
    assert state.model_dump(mode="json") == before


@pytest.mark.parametrize("zone", ["hand", "waiting_room"])
def test_legacy_private_and_public_required_choices_do_not_gain_zero_selection(zone):
    state = _state(zone)
    raw = state.model_dump(mode="json")
    assert "selection_policy" not in raw["effect_definitions"][ROOT]["choice"]
    assert match_state_hash(MatchState.model_validate(raw)) == match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _request(state, selected_card_instance_ids=[], to_slot=None))


@pytest.mark.parametrize(
    "change",
    [
        {"zone": "waiting_room"},
        {"zone": "main_deck"},
        {"target_player": "opponent"},
        {"card_type": None},
        {"choice_type": "choose_count"},
        {"maximum": 2},
        {"selection_policy": "unknown"},
    ],
)
def test_policy_rejects_unimplemented_or_public_choices(change):
    raw = _private_state().effect_definitions[ROOT].model_dump()
    raw["choice"].update(change)
    with pytest.raises(ValueError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("selected", [False, True])
def test_runtime_replay_and_private_view_do_not_reveal_unselected_hand(tmp_path, selected):
    from loveca.simulation.runtime import MatchRepository
    from loveca.webapp import _match_state_payload

    state = _private_state()
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(
            state, events=[], legal_actions=generate_legal_actions(state), player_id=viewer
        )
        if viewer == "player_1":
            assert "target" in payload["state"]["cards"]
        else:
            assert "target" not in payload["state"]["cards"]
            assert not any(a["action_type"] == "resolve_effect" for a in payload["legal_actions"])
    result = repository.apply(
        state.match_id,
        _request(
            state,
            selected_card_instance_ids=["target"] if selected else [],
            to_slot="right" if selected else None,
        ),
    )
    replay = repository.replay(state.match_id)
    assert replay["final_state"] == result.state.model_dump(mode="json")
    assert replay["events"] == [e.model_dump(mode="json") for e in result.events]
    payload = _match_state_payload(
        result.state,
        events=result.events,
        legal_actions=generate_legal_actions(result.state),
        player_id="player_2",
    )
    assert ("target" in payload["state"]["cards"]) is selected
    if not selected:
        assert '"target"' not in json.dumps(payload["events"])


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1"])
@pytest.mark.parametrize("target,no_area", [(False, False), (True, False), (True, True)])
def test_three_ai_policies_resolve_native_private_choice(policy, target, no_area):
    from test_member_entry_area_history import ENTRY_FIELD

    from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy

    state = _private_state(target=target)
    if no_area:
        player = state.players["player_1"]
        setattr(player, ENTRY_FIELD, [i for i in player.member_area.values() if i])
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    decision = controller.choose_action(
        state, generate_legal_actions(state), controlled_player_ids={"player_1"}
    )
    assert isinstance(decision, SimpleAIDecision)
    assert decision.action.action_type == "resolve_effect"
    altered = state.model_copy(deep=True)
    altered.cards["opponent-private"].card.card_code = "PRIVATE-CHANGED"
    assert (
        controller.choose_action(
            altered, generate_legal_actions(altered), controlled_player_ids={"player_1"}
        ).action
        == decision.action
    )
    result = apply_action(state, decision.action)
    assert not any(e.effect_id == ROOT for e in result.state.pending_effects)
    assert not any(e.event_type == "effect_skipped_due_to_error" for e in result.events)


@pytest.mark.parametrize("target", [False, True])
def test_deterministic_sandbox_can_resolve_private_selection(target):
    from tools.ai_sandbox.blackbox_playtest import choose_action

    state = _private_state(target=target)
    kind, actor, payload = choose_action(
        state, generate_legal_actions(state), manual_policy="block"
    )
    assert kind == "resolve_effect"
    result = apply_action(
        state,
        ActionRequest(
            action_type=kind, player_id=actor, expected_revision=state.revision, payload=payload
        ),
    )
    assert not any(e.effect_id == ROOT for e in result.state.pending_effects)


@pytest.mark.parametrize("location", ["cost_choice", "follow_up_choice", "actions"])
def test_private_policy_cannot_relax_costs_or_generic_operations(location):
    raw = _private_state().effect_definitions[ROOT].model_dump()
    if location == "actions":
        raw["actions"] = [{"action_type": "discard_from_hand"}]
    else:
        raw[location] = raw["choice"]
    with pytest.raises(ValueError):
        EffectDefinition.model_validate(raw)
