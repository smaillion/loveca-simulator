import json
from pathlib import Path

import pytest
from test_attachment_promotion import _state as external_state
from test_attachment_promotion import _trigger
from test_member_entry_area_history import ENTRY_FIELD

from loveca.simulation.effects import EffectDefinition, EffectOperation, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, EffectInvocation, ManualModifier, MatchState
from loveca.simulation.online import match_state_hash

RULE_REFERENCE_IDS = (
    "4.1.4",
    "4.3.2.3",
    "4.5.5.4",
    "9.6.2.1.2.1",
    "9.6.2.4.2.1",
    "10.4.1",
    "10.5.5",
)
ROOT = "audit-stage-deployment:1"


def _state(zone="waiting_room", orientation="active"):
    state = external_state(external=True)
    original = state.effect_definitions[state.pending_effects[0].effect_id]
    raw = original.model_dump()
    raw.update(
        effect_id=ROOT,
        card_code="AUDIT",
        condition={},
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        label_ja="監査用の効果登場（未登録）",
        choice={
            "choice_type": "card_from_zone",
            "zone": zone,
            "card_type": "member",
            "maximum_cost": 4,
            "minimum": 1,
            "maximum": 1,
        },
        cost=[{"action_type": "pay_energy", "amount": 2}],
        cost_choice=None,
        follow_up_choice=None,
        actions=[{"action_type": "deploy_selected_to_stage", "orientation": orientation}],
    )
    state.effect_definitions[ROOT] = EffectDefinition.model_validate(raw)
    state.pending_effects = [
        EffectInvocation(
            invocation_id="audit-parent",
            effect_id=ROOT,
            source_card_instance_id="source-live",
            player_id="player_1",
            trigger_event="member_played",
        )
    ]
    player = state.players["player_1"]
    for key in ["old", "left-old", "attached-member"]:
        state.cards[key] = state.cards["target"].model_copy(update={"instance_id": key}, deep=True)
        state.cards[key].card.effect_ids = []
    left = _trigger("audit-leave:1", "member_left_stage_to_waiting_room")
    state.effect_definitions[left.effect_id] = left
    state.cards["old"].card.effect_ids = [left.effect_id]
    player.member_area.update(left="left-old", right="old")
    setattr(player, ENTRY_FIELD, ["source-live", "left-old"])
    player.member_area_attachments["right"] = ["attached-member", "energy-3"]
    player.energy_area.remove("energy-3")
    player.manual_modifiers.append(
        ManualModifier(
            modifier_id="old-blade",
            modifier_type="blade",
            target_card_instance_id="old",
            amount=2,
            duration="live",
            created_turn=state.turn_number,
        )
    )
    if zone == "hand":
        player.waiting_room.remove("target")
        player.hand.append("target")
    for i in range(4):
        key = f"extra-deck-{i}"
        state.cards[key] = state.cards["deck-member-1"].model_copy(
            update={"instance_id": key}, deep=True
        )
        player.main_deck.append(key)
    return state


def _request(state, **payload):
    return ActionRequest(
        action_type="resolve_effect",
        player_id="player_1",
        expected_revision=state.revision,
        payload={
            "invocation_id": "audit-parent",
            "accepted": True,
            "selected_card_instance_ids": ["target"],
            "to_slot": "right",
            "energy_instance_ids": ["energy-0", "energy-1"],
            **payload,
        },
    )


@pytest.mark.parametrize("zone", ["hand", "waiting_room"])
@pytest.mark.parametrize("orientation", ["active", "wait"])
def test_simple_occupied_area_deployment_cleans_overlap_and_triggers_after_parent(
    zone, orientation
):
    state = _state(zone, orientation)
    before = state.model_dump(mode="json")
    result = apply_action(state, _request(state))
    player = result.state.players["player_1"]
    assert player.member_area["right"] == "target"
    assert result.state.cards["target"].orientation == orientation
    assert result.state.cards["target"].face_up is True
    assert "target" not in getattr(player, zone)
    assert {"old", "attached-member"} <= set(player.waiting_room)
    assert all(result.state.cards[i].face_up for i in ["old", "attached-member"])
    assert "energy-3" in player.energy_deck and "energy-3" not in player.waiting_room
    assert result.state.cards["energy-3"].face_up is False
    assert all(
        result.state.cards[i].orientation == "active"
        for i in ["old", "attached-member", "energy-3"]
    )
    assert player.member_area_attachments["right"] == []
    assert not player.manual_modifiers
    assert player.member_entered_count_this_turn == 1
    assert "target" in getattr(player, ENTRY_FIELD)
    assert player.member_instance_ids_baton_entered_this_turn == []
    assert len(player.hand) == len(state.players["player_1"].hand) + 3 - int(zone == "hand")
    assert all(result.state.cards[i].orientation == "wait" for i in ["energy-0", "energy-1"])
    assert not any("baton_touch" in e.event_type for e in result.events)
    triggered = [e for e in result.events if e.event_type == "effect_triggered"]
    assert {e.data["effect_id"] for e in triggered} == {
        "audit-leave:1",
        "audit-onplay:1",
        "audit-observer:1",
    }
    resolved = next(
        i
        for i, e in enumerate(result.events)
        if e.event_type == "effect_resolved" and e.data["effect_id"] == ROOT
    )
    assert resolved < next(i for i, e in enumerate(result.events) if e.event_type == "cards_drawn")
    assert state.model_dump(mode="json") == before


@pytest.mark.parametrize(
    "payload",
    [
        {"to_slot": "center"},
        {"to_slot": "missing"},
        {"selected_card_instance_ids": ["old"]},
        {"selected_card_instance_ids": ["target", "old"]},
        {"energy_instance_ids": ["energy-0"]},
        {"energy_instance_ids": ["energy-0", "energy-0"]},
    ],
)
def test_illegal_selection_rolls_back_cost_zones_history_and_modifiers(payload):
    state = _state()
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalActionError):
        apply_action(state, _request(state, **payload))
    assert state.model_dump(mode="json") == before


@pytest.mark.parametrize(
    "gap",
    [
        "outgoing_observer",
        "conditional_leave",
        "unknown",
        "attached",
        "incoming_condition",
        "incoming_static",
        "other_observer",
    ],
)
def test_unsupported_overlap_semantics_are_explicitly_excluded_before_cost(gap):
    state = _state()
    if gap == "outgoing_observer":
        state.cards["old"].card.effect_ids = ["audit-observer:1"]
    elif gap == "conditional_leave":
        state.effect_definitions["audit-leave:1"].condition = {"source_slot": "right"}
    elif gap == "unknown":
        state.cards["old"].card.effect_ids = ["missing:1"]
    elif gap == "attached":
        state.cards["attached-member"].card.effect_ids = ["audit-leave:1"]
    elif gap == "incoming_condition":
        state.effect_definitions["audit-onplay:1"].condition = {
            "total_stage_member_count_at_least": 4
        }
    elif gap == "incoming_static":
        state.effect_definitions["audit-onplay:1"].trigger = "static_always"
    else:
        state.effect_definitions["audit-observer:1"].condition = {
            "total_stage_member_count_at_least": 4
        }
    from loveca.simulation.engine import _effect_deployment_slots, _occupied_deployment_gaps

    invocation = state.pending_effects[0]
    assert "right" not in _effect_deployment_slots(state, invocation, "target")
    assert (
        "overlap_timing_review" in _occupied_deployment_gaps(state, invocation, "target")["right"]
    )
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalActionError):
        apply_action(state, _request(state))
    assert state.model_dump(mode="json") == before


def test_current_member_identity_moves_the_blocked_area_but_not_old_location():
    from loveca.simulation.engine import _effect_deployment_slots

    state = _state()
    player = state.players["player_1"]
    player.member_area["left"], player.member_area["right"] = (
        player.member_area["right"],
        player.member_area["left"],
    )
    player.member_area_attachments["left"], player.member_area_attachments["right"] = (
        player.member_area_attachments["right"],
        [],
    )
    assert _effect_deployment_slots(state, state.pending_effects[0], "target") == ["left"]
    result = apply_action(state, _request(state, to_slot="left"))
    assert result.state.players["player_1"].member_area["left"] == "target"


@pytest.mark.parametrize("zone", ["hand", "waiting_room"])
def test_actual_runtime_replay_and_both_private_views(tmp_path, zone):
    from loveca.simulation.runtime import MatchRepository
    from loveca.webapp import _match_state_payload

    state = _state(zone)
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repository.apply(state.match_id, _request(state))
    replay = repository.replay(state.match_id)
    assert replay["final_state"] == result.state.model_dump(mode="json")
    assert replay["events"] == [e.model_dump(mode="json") for e in result.events]
    assert match_state_hash(MatchState.model_validate(replay["final_state"])) == match_state_hash(
        result.state
    )
    for actor, hidden in [("player_1", "opponent-private"), ("player_2", "live-1")]:
        payload = _match_state_payload(
            result.state,
            events=result.events,
            legal_actions=generate_legal_actions(result.state),
            player_id=actor,
        )
        assert hidden not in payload["state"]["cards"]
        assert f'"{hidden}"' not in json.dumps(payload["events"])
        assert payload["state"]["players"]["player_1"]["member_area"]["right"] == "target"


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1"])
def test_three_ai_policies_and_script_only_use_native_legal_area(policy):
    from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
    from tools.ai_sandbox.blackbox_playtest import choose_action

    state = _state()
    legal = generate_legal_actions(state)
    options = next(a for a in legal if a.action_type == "resolve_effect").options["invocations"][0]
    assert options["position_change_slots_by_candidate"]["target"] == ["right"]
    assert options["deployment_unsupported_slots"]["center"] == "member_entered_stage_this_turn"
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    decision = controller.choose_action(state, legal, controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision)
    assert decision.action.payload["to_slot"] == "right"
    changed = state.model_copy(deep=True)
    changed.cards["opponent-private"].card.card_code = "PRIVATE-CHANGED"
    assert (
        controller.choose_action(
            changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}
        ).action
        == decision.action
    )
    assert (
        apply_action(state, decision.action).state.players["player_1"].member_area["right"]
        == "target"
    )
    action_type, actor, payload = choose_action(state, legal, manual_policy="block")
    assert (
        apply_action(
            state,
            ActionRequest(
                action_type=action_type,
                player_id=actor,
                expected_revision=state.revision,
                payload=payload,
            ),
        )
        .state.players["player_1"]
        .member_area["right"]
        == "target"
    )


@pytest.mark.parametrize("orientation", [None, "up"])
def test_new_operation_requires_explicit_controlled_orientation(orientation):
    with pytest.raises(ValueError):
        EffectOperation(action_type="deploy_selected_to_stage", orientation=orientation)


def test_old_empty_stage_snapshot_still_rejects_an_occupied_area_and_registry_is_not_promoted():
    state = _state()
    raw = state.effect_definitions[ROOT].model_dump()
    raw["actions"] = [{"action_type": "deploy_selected_to_empty_stage", "orientation": "active"}]
    state.effect_definitions[ROOT] = EffectDefinition.model_validate(raw)
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalActionError):
        apply_action(state, _request(state))
    assert state.model_dump(mode="json") == before
    ids = {
        "PL!-PR-015:1",
        "PL!SP-PR-020:1",
        "PL!N-pb1-013:1",
        "PL!N-pb1-015:1",
        "PL!N-pb1-017:1",
        "PL!N-pb1-023:1",
    }
    entries = [e for e in load_effect_registry().effects if e.effect_id in ids]
    assert {e.effect_id for e in entries} == ids
    assert all(e.execution_mode == "manual_resolution" for e in entries)


@pytest.mark.parametrize(
    "change",
    [
        {"choice": None},
        {"cost_choice": {"choice_type": "card_from_zone", "zone": "hand"}},
        {
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "source_attachments",
                "card_type": "member",
                "minimum": 1,
                "maximum": 1,
            }
        },
        {
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "card_type": "member",
                "minimum": 0,
                "maximum": 1,
            }
        },
        {
            "actions": [
                {"action_type": "deploy_selected_to_stage", "orientation": "active"},
                {"action_type": "draw_card", "amount": 1},
            ]
        },
        {"cost": [{"action_type": "discard_from_hand"}]},
    ],
)
def test_foundation_rejects_unimplemented_multi_step_semantics(change):
    raw = _state().effect_definitions[ROOT].model_dump()
    with pytest.raises(ValueError):
        EffectDefinition.model_validate({**raw, **change})


def test_native_activated_cost_is_paid_once_and_lost_target_finishes_visibly():
    state = _state()
    state.pending_effects = []
    state.effect_definitions[ROOT].trigger = "player_activation"
    state.effect_definitions[ROOT].timing = "activated_main"
    state.effect_definitions[ROOT].effect_type = "activated"
    state.effect_definitions[ROOT].condition = {"source_zone": "stage"}
    state.cards["source-live"].card.effect_ids.append(ROOT)
    started = apply_action(
        state,
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
    state = started.state
    assert state.pending_effects[0].resolution_stage == "after_cost"
    state.players["player_1"].waiting_room.remove("target")
    state.players["player_1"].main_deck.append("target")
    result = apply_action(
        state,
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
    assert result.state.pending_effects == []
    assert result.state.players["player_1"].member_area["right"] == "old"
    assert any(e.event_type == "effect_operation_not_applied" for e in result.events)
    assert not any(e.event_type == "effect_cost_paid" for e in result.events)
    assert all(result.state.cards[i].orientation == "wait" for i in ["energy-0", "energy-1"])


@pytest.mark.parametrize("change", ["cost", "card_type", "owner"])
def test_target_constraints_are_revalidated_atomically(change):
    state = _state()
    if change == "cost":
        state.cards["target"].card.cost = 5
    elif change == "card_type":
        state.cards["target"].card.card_type = "live"
    else:
        state.cards["target"].owner_id = "player_2"
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalActionError):
        apply_action(state, _request(state))
    assert state.model_dump(mode="json") == before


def test_the_new_operation_still_accepts_an_empty_area_without_fake_departure():
    state = _state()
    player = state.players["player_1"]
    player.member_area["right"] = None
    player.member_area_attachments["right"] = []
    player.waiting_room.extend(["old", "attached-member"])
    player.energy_deck.append("energy-3")
    player.manual_modifiers = []
    result = apply_action(state, _request(state))
    assert result.state.players["player_1"].member_area["right"] == "target"
    assert len(result.state.players["player_1"].hand) == len(player.hand) + 2
    assert not any(
        e.event_type in {"duplicate_member_resolved", "stage_attachments_cleaned"}
        for e in result.events
    )


def test_orphan_attachments_do_not_silently_become_attached_to_a_new_member():
    from loveca.simulation.engine import _occupied_deployment_gaps

    state = _state()
    state.players["player_1"].member_area["right"] = None
    gaps = _occupied_deployment_gaps(state, state.pending_effects[0], "target")
    assert gaps["right"] == "orphan_attachments_require_rule_check"
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalActionError):
        apply_action(state, _request(state))
    assert state.model_dump(mode="json") == before


def test_other_members_own_onplay_condition_does_not_block_a_different_entrant():
    state = _state()
    effect = _trigger("irrelevant-onplay:1", "member_played")
    effect.condition = {"total_stage_member_count_at_least": 99}
    state.effect_definitions[effect.effect_id] = effect
    state.cards["source-live"].card.effect_ids.append(effect.effect_id)
    result = apply_action(state, _request(state))
    assert result.state.players["player_1"].member_area["right"] == "target"
    assert not any(
        e.event_type == "effect_triggered" and e.data["effect_id"] == effect.effect_id
        for e in result.events
    )
