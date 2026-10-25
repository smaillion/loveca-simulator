import json
from pathlib import Path

import pytest
from test_empty_effect_deployment import _resolve
from test_empty_effect_deployment import _state as deployment_state
from test_member_entry_area_history import ENTRY_FIELD

from loveca.simulation.effects import EffectDefinition, EffectOperation, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, ManualModifier, MatchState
from loveca.simulation.online import match_state_hash, sha256_json

RULE_REFERENCE_IDS = ("4.1.4", "4.5.5", "9.6.2.4.2.1", "11.4.2")
POLICY = "member_area_external_only"


def _trigger(effect_id, trigger):
    return EffectDefinition(
        effect_id=effect_id, card_code="AUDIT", text_revision_id=1,
        raw_text_hash="a" * 64, effect_index=1, label_ja="監査用の登場ドロー",
        effect_type="triggered", timing="on_play", trigger=trigger,
        execution_mode="auto_resolve", frequency_limit="none", is_optional=False,
        actions=[{"action_type": "draw_card", "amount": 1}],
        simulation_support="test_validated_executable", review_status="test_validated",
        source_reference="Rules 4.5.5 / 11.4.2; controlled transition fixture",
    )


def _state(*, external=False, legacy=False, history=True):
    effect_id = "PL!HS-bp5-002:2" if external else "PL!-bp6-003:2"
    state = deployment_state(effect_id)
    raw = state.effect_definitions[effect_id].model_dump()
    if legacy:
        raw["actions"][0].pop("entry_trigger_policy", None)
    else:
        raw["actions"][0]["entry_trigger_policy"] = POLICY
    state.effect_definitions[effect_id] = EffectDefinition.model_validate(raw)
    if history:
        setattr(state.players["player_1"], ENTRY_FIELD, [])
    onplay = _trigger("audit-onplay:1", "member_played")
    observer = _trigger("audit-observer:1", "own_member_played")
    state.effect_definitions.update({e.effect_id: e for e in [onplay, observer]})
    state.cards["target"].card.effect_ids = [onplay.effect_id]
    state.cards["source-live"].card.effect_ids = [observer.effect_id]
    state.cards["opponent-private"] = state.cards["deck-live-2"].model_copy(
        update={"instance_id": "opponent-private", "owner_id": "player_2"}, deep=True,
    )
    state.players["player_2"].hand = ["opponent-private"]
    return state


def _promote(state, slot="right"):
    effect = state.effect_definitions[state.pending_effects[0].effect_id]
    energies = ["energy-0", "energy-1"] if effect.cost else []
    return _resolve(state, selected_card_instance_ids=["target"], to_slot=slot,
                    energy_instance_ids=energies)


@pytest.mark.parametrize("slot", ["left", "right"])
def test_attachment_promotion_does_not_invent_onplay_or_own_member_entry(slot):
    state = _state()
    player = state.players["player_1"]
    before = state.model_dump(mode="json")
    before_deck, before_hand = list(player.main_deck), list(player.hand)
    result = _promote(state, slot)
    player = result.state.players["player_1"]
    assert player.member_area[slot] == "target"
    assert player.member_area_attachments["center"] == []
    assert result.state.cards["target"].orientation == "active"
    assert result.state.cards["target"].face_up is True
    assert player.member_entered_count_this_turn == 0
    assert player.member_areas_entered_this_turn == []
    assert getattr(player, ENTRY_FIELD) == []
    assert player.main_deck == before_deck and player.hand == before_hand
    assert not result.state.pending_effects
    assert not any(e.event_type in {"effect_triggered", "cards_drawn"} for e in result.events)
    assert state.model_dump(mode="json") == before


def test_external_waiting_room_deployment_still_triggers_both_real_draws():
    state = _state(external=True)
    before = state.players["player_1"]
    result = _promote(state)
    player = result.state.players["player_1"]
    assert player.member_entered_count_this_turn == 1
    assert player.member_areas_entered_this_turn == ["right"]
    assert getattr(player, ENTRY_FIELD) == ["target"]
    assert len(player.hand) == len(before.hand) + 2
    assert player.main_deck == before.main_deck[2:]
    assert {e.data["effect_id"] for e in result.events if e.event_type == "effect_triggered"} == {
        "audit-onplay:1", "audit-observer:1"
    }


@pytest.mark.parametrize("history", [False, True])
def test_legacy_effect_snapshot_preserves_triggers_even_with_new_area_history(history):
    state = _state(legacy=True, history=history)
    raw = state.model_dump(mode="json")
    assert "entry_trigger_policy" not in raw["effect_definitions"]["PL!-bp6-003:2"]["actions"][0]
    restored = MatchState.model_validate_json(json.dumps(raw))
    assert match_state_hash(restored) == sha256_json(raw)
    result = _promote(restored)
    assert result.state.players["player_1"].member_entered_count_this_turn == 1
    assert len(result.state.players["player_1"].hand) == len(state.players["player_1"].hand) + 2
    assert match_state_hash(_promote(state).state) == match_state_hash(result.state)


def test_invalid_promotion_is_atomic():
    state = _state()
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalActionError):
        _promote(state, "center")
    assert state.model_dump(mode="json") == before


@pytest.mark.parametrize("history", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
def test_actual_runtime_replay_preserves_effect_snapshot_and_events(tmp_path, history, legacy):
    from loveca.simulation.runtime import MatchRepository

    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    initial = _state(legacy=legacy, history=history)
    repository.create_match(initial, card_database_path=Path("data/loveca.sqlite3"))
    action = ActionRequest(action_type="resolve_effect", player_id="player_1",
        expected_revision=initial.revision, payload={"invocation_id": "inv-1", "accepted": True,
            "selected_card_instance_ids": ["target"], "to_slot": "right"})
    result = repository.apply(initial.match_id, action)
    replay = repository.replay(initial.match_id)
    assert replay["final_state"] == result.state.model_dump(mode="json")
    assert result.state.players["player_1"].member_entered_count_this_turn == int(legacy)
    assert match_state_hash(MatchState.model_validate(replay["final_state"])) == match_state_hash(
        result.state
    )
    replay_events = replay["events"]
    assert replay_events == [e.model_dump(mode="json") for e in result.events]


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1"])
def test_ai_submits_native_promotion_and_does_not_gain_unearned_draws(policy):
    from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy

    state = _state()
    before = state.model_dump(mode="json")
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    decision = controller.choose_action(state, generate_legal_actions(state),
                                        controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision)
    assert decision.action.action_type == "resolve_effect"
    assert decision.action.payload["selected_card_instance_ids"] == ["target"]
    assert decision.action.payload["to_slot"] in {"left", "right"}
    changed_hidden = state.model_copy(deep=True)
    changed_hidden.cards["opponent-private"].card.name_ja = "相手の非公開カード"
    changed_hidden.cards["opponent-private"].card.card_code = "PRIVATE-CHANGED"
    other_decision = controller.choose_action(
        changed_hidden, generate_legal_actions(changed_hidden), controlled_player_ids={"player_1"}
    )
    assert other_decision.action == decision.action
    result = apply_action(state, decision.action)
    assert result.state.players["player_1"].hand == state.players["player_1"].hand
    assert result.state.players["player_1"].member_entered_count_this_turn == 0
    assert state.model_dump(mode="json") == before


@pytest.mark.parametrize("fresh", [False, True])
def test_stage_internal_promotion_keeps_prior_entry_identity_and_modifiers(fresh):
    from loveca.simulation.engine import _member_area_blocks_entry

    state = _state()
    player = state.players["player_1"]
    if fresh:
        setattr(player, ENTRY_FIELD, ["target"])
    player.manual_modifiers.append(ManualModifier(
        modifier_id="prior-stage-modifier", modifier_type="blade", duration="live",
        amount=2, created_turn=state.turn_number, target_card_instance_id="target",
    ))
    result = _promote(state)
    player = result.state.players["player_1"]
    assert getattr(player, ENTRY_FIELD) == (["target"] if fresh else [])
    assert _member_area_blocks_entry(player, "right") is fresh
    assert _member_area_blocks_entry(player, "center") is False
    assert player.member_entered_count_this_turn == 0
    assert player.manual_modifiers == state.players["player_1"].manual_modifiers


def test_real_live_success_trigger_queues_promotion_then_finishes_without_onplay():
    state = _state()
    effect_id = "PL!-bp6-003:2"
    state.pending_effects = []
    state.phase = "live_judgment"
    state.active_player_id = None
    player = state.players["player_1"]
    player.hand = []
    player.live_area = ["live-1"]
    state.cards["source-live"].card.effect_ids.append(effect_id)
    started = apply_action(state, ActionRequest(action_type="advance_phase",
                           expected_revision=state.revision))
    assert [e.effect_id for e in started.state.pending_effects] == [effect_id]
    assert any(e.event_type == "effect_triggered" for e in started.events)
    result = _promote(started.state)
    assert result.state.players["player_1"].member_area["right"] == "target"
    assert result.state.players["player_1"].hand == []
    assert not result.state.pending_effects
    assert not any(e.event_type in {"effect_triggered", "cards_drawn"} for e in result.events)
    assert any(e.event_type == "effect_member_promoted_from_attachment" for e in result.events)


@pytest.mark.parametrize("kwargs", [
    {"action_type": "draw_card", "amount": 1, "entry_trigger_policy": POLICY},
    {"action_type": "deploy_selected_to_empty_stage", "entry_trigger_policy": "always"},
])
def test_policy_is_controlled_and_not_a_generic_operation_flag(kwargs):
    with pytest.raises(ValueError):
        EffectOperation.model_validate(kwargs)


def test_registry_exact_binding_and_legacy_policy_omission():
    from loveca.simulation.effect_candidates import discover_effect_candidates

    effect = next(e for e in load_effect_registry().effects if e.effect_id == "PL!-bp6-003:2")
    assert effect.text_revision_id == 4
    assert effect.raw_text_hash == (
        "a97fbfd44a384f8217e07218649736855af4a6fd725dd9de9c7242520f6ed06e"
    )
    assert effect.actions[0].entry_trigger_policy == POLICY
    candidate = next(e for e in discover_effect_candidates(Path("data/loveca.sqlite3"),
        include_registered=True) if e.effect_id == effect.effect_id)
    assert candidate.actions == [op.model_dump(exclude_none=True) for op in effect.actions]
    assert effect.review_status == "test_validated"
    assert effect.simulation_support == "test_validated_executable"
    old_operation = EffectOperation(action_type="draw_card", amount=1)
    assert "entry_trigger_policy" not in old_operation.model_dump()
    assert "entry_trigger_policy" not in json.loads(old_operation.model_dump_json())


def test_both_online_views_show_promoted_member_but_not_opponents_hand():
    from loveca.webapp import _match_state_payload

    result = _promote(_state())
    payloads = {
        player_id: _match_state_payload(result.state, events=result.events,
            legal_actions=generate_legal_actions(result.state), player_id=player_id)
        for player_id in result.state.players
    }
    for payload in payloads.values():
        assert payload["state"]["cards"]["target"]["face_up"] is True
        assert payload["state"]["players"]["player_1"]["member_area"]["right"] == "target"
        assert "\"opponent-private\"" not in json.dumps(payload["events"])
        assert "\"live-1\"" not in json.dumps(payload["events"])
    assert "opponent-private" not in payloads["player_1"]["state"]["cards"]
    assert "live-1" not in payloads["player_2"]["state"]["cards"]


def test_promotion_does_not_skip_subsequent_operations():
    state = _state()
    effect = state.effect_definitions["PL!-bp6-003:2"]
    effect.actions.append(EffectOperation(action_type="draw_card", amount=1))
    result = _promote(state)
    assert len(result.state.players["player_1"].hand) == len(state.players["player_1"].hand) + 1
    assert len([e for e in result.events if e.event_type == "cards_drawn"]) == 1
    assert not any(e.event_type == "effect_triggered" for e in result.events)


def test_declining_optional_promotion_keeps_all_zones_and_counts():
    state = _state()
    result = apply_action(state, ActionRequest(action_type="resolve_effect", player_id="player_1",
        expected_revision=state.revision, payload={"invocation_id": "inv-1", "accepted": False}))
    assert result.state.players == state.players
    assert result.state.cards == state.cards
    assert not result.state.pending_effects
    assert any(e.event_type == "effect_declined" for e in result.events)
