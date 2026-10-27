from contextlib import closing
from functools import lru_cache
from pathlib import Path

import pytest
from test_effect_execution import _minimal_effect_state

from loveca.db.bootstrap import connect_database
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import (
    IllegalActionError, _effective_member_blade, apply_action, generate_legal_actions,
)
from loveca.simulation.models import ActionRequest, MatchState
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!SP-bp7-025"
EFFECT = CODE + ":1"
RULE_REFERENCE_IDS = ("9.6.3.1", "9.6.3.1.3", "9.7.2", "11.5.2", "4.1.4", "8.4.11")


@lru_cache
def _candidate():
    return next(c for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
                if c.effect_id == EFFECT)


def _state(*, copies=2, legacy=False):
    effect = EffectDefinition.model_validate(_candidate().to_registry_entry())
    if legacy:
        raw = effect.model_dump(mode="json")
        raw.update(execution_mode="manual_resolution", simulation_support="manual_resolution",
                   review_status="parsed_draft", choice=None, frequency_limit="once_per_live",
                   actions=[{"action_type": "manual_resolution"}])
        effect = EffectDefinition.model_validate(raw)
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        card = _load_definition(connection, CODE, None, {EFFECT: effect}, {})
    state = _minimal_effect_state(effect)
    state.pending_effects = []
    state.phase = "performance_first"
    state.effect_order_policy = "ap_nap_player_choice"
    state.stage_departure_policy = "clear_departed_card_modifiers"
    state.cards["source-live"].card = card
    state.cards["source-live"].face_up = False
    state.players["player_1"].live_area = ["source-live"]
    template = state.cards["deck-member-1"]
    for index, slot in enumerate(["left", "center", "right"]):
        key = f"member-{index}"
        state.cards[key] = template.model_copy(update={"instance_id": key, "face_up": True}, deep=True)
        state.cards[key].card.name_ja = "嵐 千砂都" if index < copies else "別のメンバー"
        state.cards[key].card.effect_ids = []
        state.players["player_1"].member_area[slot] = key
    for key, owner in [("opponent-member", "player_2"), ("opponent-secret", "player_2"),
                       ("held", "player_1"), ("attached", "player_1")]:
        state.cards[key] = state.cards["member-0"].model_copy(update={"instance_id": key, "owner_id": owner}, deep=True)
        state.cards[key].card.name_ja = "嵐 千砂都"
    state.players["player_2"].member_area["center"] = "opponent-member"
    state.players["player_2"].hand = ["opponent-secret"]
    state.players["player_1"].hand = ["held"]
    state.players["player_1"].member_area_attachments["right"] = ["attached"]
    return state


def _begin(state):
    return apply_action(state, ActionRequest(action_type="advance_phase", player_id=state.active_player_id,
                                            expected_revision=state.revision))


def _resolve(state, selected=None, **extra):
    return ActionRequest(action_type="resolve_effect", player_id=state.pending_effects[0].player_id, expected_revision=state.revision,
        payload={"invocation_id": state.pending_effects[0].invocation_id,
                 "selected_card_instance_ids": ["member-1"] if selected is None else selected, **extra})


def test_exact_candidate_requires_a_single_explicit_named_target():
    candidate = _candidate()
    assert candidate.pattern_id == "live_start_named_chisato_selected_blade"
    assert candidate.text_revision_id == 928
    assert candidate.raw_text_hash == "76ad7caa94837eb2944d4236b2339690552e985a14129513e981c03cf8e0ad39"
    assert candidate.execution_mode == "prompt_then_resolve"
    assert candidate.choice == {"choice_type": "member_from_stage", "zone": "stage", "card_type": "member",
                                "name_ja_any": ["嵐 千砂都"], "minimum": 1, "maximum": 1,
                                "selection_policy": "public_single_as_much_as_possible"}
    assert candidate.actions == [{"action_type": "gain_blade", "target": "selected", "amount": 1}]
    assert candidate.duration == "live" and not candidate.cost and not candidate.is_optional
    assert candidate.frequency_limit == "once_per_live"


@pytest.mark.parametrize("target", ["member-0", "member-1"])
@pytest.mark.parametrize("orientation", ["active", "wait"])
def test_native_live_start_prompts_and_applies_only_to_the_chosen_copy(target, orientation):
    state = _state()
    state.cards[target].orientation = orientation
    before = match_state_hash(state)
    started = _begin(state)
    assert started.state.phase == "performance_first" and len(started.state.pending_effects) == 1
    assert started.state.cards["source-live"].face_up
    assert not started.state.players["player_1"].manual_modifiers
    options = next(a for a in started.legal_actions if a.action_type == "resolve_effect").options["invocations"][0]
    assert set(options["candidate_card_instance_ids"]) == {"member-0", "member-1"}
    result = apply_action(started.state, _resolve(started.state, [target]))
    modifiers = result.state.players["player_1"].manual_modifiers
    assert len(modifiers) == 1
    assert (modifiers[0].modifier_type, modifiers[0].target_card_instance_id, modifiers[0].amount,
            modifiers[0].duration) == ("blade", target, 1, "live")
    assert _effective_member_blade(result.state, "player_1", target) == 2
    assert result.state.cards[target].orientation == orientation
    assert result.state.phase == "yell_first" and not result.state.pending_effects
    assert match_state_hash(state) == before


@pytest.mark.parametrize("selection", [[], ["member-2"], ["held"], ["attached"], ["opponent-member"],
                                      ["member-0", "member-1"], ["member-1", "member-1"], ["missing"]])
def test_illegal_or_missing_target_is_atomic(selection):
    state = _begin(_state()).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, selection))
    assert match_state_hash(state) == before


def test_mandatory_effect_cannot_be_declined_or_advanced_past():
    state = _begin(_state()).state
    before = match_state_hash(state)
    for action in [_resolve(state, accepted=False), ActionRequest(action_type="advance_phase",
                   player_id="player_1", expected_revision=state.revision)]:
        with pytest.raises(IllegalActionError):
            apply_action(state, action)
        assert match_state_hash(state) == before


@pytest.mark.parametrize("name,eligible", [("嵐千砂都", True), ("嵐 千砂都", True),
                                           ("嵐 千砂都の別名", False), ("嵐 千沙都", False)])
def test_name_matching_only_normalizes_whitespace_not_fuzzy_characters(name, eligible):
    state = _state(copies=0)
    state.cards["member-0"].card.name_ja = name
    result = _begin(state)
    assert result.state.pending_effects
    if not eligible:
        result = apply_action(result.state, _resolve(result.state, []))
        assert any(e.data.get("reason") == "no_legal_stage_member_at_resolution" for e in result.events)
        assert not result.state.players["player_1"].manual_modifiers


def test_no_eligible_own_top_member_finishes_with_a_readable_reason():
    started = _begin(_state(copies=0))
    assert started.state.pending_effects
    result = apply_action(started.state, _resolve(started.state, []))
    assert result.state.phase == "yell_first" and not result.state.pending_effects
    assert any(e.event_type == "effect_operation_not_applied" and e.data.get("effect_id") == EFFECT
               and e.data.get("reason") == "no_legal_stage_member_at_resolution" for e in result.events)


def test_third_same_name_copy_can_be_chosen_instead_of_first():
    state = _begin(_state(copies=3)).state
    result = apply_action(state, _resolve(state, ["member-2"]))
    assert [m.target_card_instance_id for m in result.state.players["player_1"].manual_modifiers] == ["member-2"]


def test_player_two_first_player_uses_its_own_named_targets():
    state = _state()
    old_players = state.players
    state.players = {
        "player_1": old_players["player_2"].model_copy(update={"player_id": "player_1"}, deep=True),
        "player_2": old_players["player_1"].model_copy(update={"player_id": "player_2"}, deep=True),
    }
    for card in state.cards.values():
        card.owner_id = "player_2" if card.owner_id == "player_1" else "player_1"
    state.first_player_id, state.second_player_id, state.active_player_id = "player_2", "player_1", "player_2"
    started = _begin(state).state
    result = apply_action(started, _resolve(started))
    assert len(result.state.players["player_2"].manual_modifiers) == 1
    assert not result.state.players["player_1"].manual_modifiers


def test_opponent_performance_does_not_trigger_own_live_area_card():
    state = _state()
    state.phase, state.active_player_id = "performance_second", "player_2"
    result = _begin(state)
    assert not result.state.pending_effects
    assert not any(e.data.get("effect_id") == EFFECT for e in result.events)


def test_live_end_expires_only_this_live_duration_modifier():
    state = _begin(_state()).state
    state = apply_action(state, _resolve(state)).state
    state.phase, state.active_player_id = "live_judgment", None
    result = apply_action(state, ActionRequest(action_type="advance_phase", expected_revision=state.revision))
    assert not result.state.players["player_1"].manual_modifiers
    assert _effective_member_blade(result.state, "player_1", "member-1") == 1
    assert any(e.event_type == "manual_modifiers_expired" and e.data.get("duration") == "live" for e in result.events)


def test_target_departure_clears_bonus_and_reentry_does_not_inherit_it():
    state = _begin(_state()).state
    state = apply_action(state, _resolve(state)).state
    action = ActionRequest(action_type="manual_adjustment", player_id="player_1", expected_revision=state.revision,
        payload={"adjustments": [{"adjustment_type": "move_card", "target_player_id": "player_1",
                                  "target_card_instance_id": "member-1", "to_zone": zone}
                                 for zone in ["waiting_room", "member_center"]]})
    result = apply_action(state, action)
    assert not result.state.players["player_1"].manual_modifiers
    assert result.state.players["player_1"].member_area["center"] == "member-1"
    assert any(e.event_type == "stage_card_modifiers_cleared" for e in result.events)


def test_source_departure_after_trigger_does_not_cancel_member_bonus():
    state = _begin(_state()).state
    # Controlled ordered-effect boundary, not an extra legal player action while pending.
    state.players["player_1"].live_area.remove("source-live")
    state.players["player_1"].waiting_room.append("source-live")
    result = apply_action(state, _resolve(state))
    assert len(result.state.players["player_1"].manual_modifiers) == 1


def test_target_entering_during_another_ordered_effect_is_selected_at_resolution():
    state = _state(copies=0)
    effect = state.effect_definitions[EFFECT]
    raw = effect.model_dump(mode="json")
    raw.update(effect_id="AUDIT-enter-target:1", card_code="AUDIT-enter-target", choice=None,
               execution_mode="manual_resolution", simulation_support="manual_resolution",
               review_status="parsed_draft", actions=[{"action_type": "manual_resolution"}])
    control = EffectDefinition.model_validate(raw)
    state.effect_definitions[control.effect_id] = control
    state.cards["live-1"].card.effect_ids = [control.effect_id]
    state.players["player_1"].live_area.append("live-1")
    started = _begin(state).state
    assert {i.effect_id for i in started.pending_effects} == {EFFECT, control.effect_id}
    invocation = next(i for i in started.pending_effects if i.effect_id == control.effect_id)
    result = apply_action(started, ActionRequest(action_type="manual_adjustment", player_id="player_1",
        expected_revision=started.revision, payload={"source_invocation_id": invocation.invocation_id,
            "source_effect_id": control.effect_id, "source_card_instance_id": "live-1", "adjustments": [
                {"adjustment_type": "move_card", "target_player_id": "player_1",
                 "target_card_instance_id": "member-1", "to_zone": "waiting_room"},
                {"adjustment_type": "move_card", "target_player_id": "player_1",
                 "target_card_instance_id": "held", "to_zone": "member_center"},
            ]}))
    result = apply_action(result.state, _resolve(result.state, ["held"]))
    assert result.state.players["player_1"].manual_modifiers[0].target_card_instance_id == "held"


def test_old_no_policy_snapshot_retains_historical_no_target_queue_behavior():
    state = _state(copies=0)
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw["choice"].pop("selection_policy")
    state.effect_definitions[EFFECT] = EffectDefinition.model_validate(raw)
    assert "selection_policy" not in state.effect_definitions[EFFECT].choice.model_dump()
    restored = MatchState.model_validate_json(state.model_dump_json())
    assert match_state_hash(restored) == match_state_hash(state)
    result = _begin(restored)
    assert not result.state.pending_effects
    assert any(e.data.get("reason") == "choice_candidates_unavailable" for e in result.events)


@pytest.mark.parametrize("defect", ["cost", "optional", "wrong_trigger", "two_operations", "wrong_target", "wrong_zone"])
def test_public_single_policy_rejects_unmodeled_semantics(defect):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    if defect == "cost":
        raw["cost"] = [{"action_type": "pay_energy", "amount": 1}]
    elif defect == "optional":
        raw["is_optional"] = True
    elif defect == "wrong_trigger":
        raw["trigger"] = "member_played"
    elif defect == "two_operations":
        raw["actions"].append({"action_type": "draw_card", "amount": 1})
    elif defect == "wrong_target":
        raw["actions"][0]["target"] = "self"
    else:
        raw["choice"]["zone"] = "hand"
    with pytest.raises(ValueError, match="public single selection"):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("zone", ["hand", "waiting_room", "success_live_area"])
def test_live_start_ability_is_not_active_outside_the_live_area(zone):
    state = _state()
    player = state.players["player_1"]
    player.live_area = ["live-1"]
    getattr(player, zone).append("source-live")
    result = _begin(state)
    assert not result.state.pending_effects
    assert not any(e.data.get("effect_id") == EFFECT for e in result.events)


def test_expired_target_is_logged_and_does_not_stall_after_another_pending_effect():
    state = _begin(_state(copies=1)).state
    # A controlled post-trigger snapshot represents another ordered ability's departure.
    state.players["player_1"].member_area["left"] = None
    state.players["player_1"].waiting_room.append("member-0")
    result = apply_action(state, _resolve(state, []))
    assert not result.state.pending_effects and result.state.phase == "yell_first"
    assert not result.state.players["player_1"].manual_modifiers
    assert any(e.data.get("reason") == "no_legal_stage_member_at_resolution" for e in result.events)


@pytest.mark.parametrize("legacy", [False, True])
def test_actual_sql_replay_preserves_new_selection_and_old_manual_snapshot(tmp_path, legacy):
    state = _state(legacy=legacy)
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    started = repository.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id="player_1",
                                                            expected_revision=state.revision))
    if legacy:
        assert started.state.pending_effects
        with pytest.raises(IllegalActionError):
            repository.apply(state.match_id, _resolve(started.state))
        final = started
    else:
        final = repository.apply(state.match_id, _resolve(started.state))
    replay = repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")
    restored = MatchState.model_validate(replay["final_state"])
    assert match_state_hash(restored) == match_state_hash(final.state)
    for viewer, secret in [("player_1", "opponent-secret"), ("player_2", "held")]:
        payload = _match_state_payload(final.state, events=final.events, legal_actions=final.legal_actions, player_id=viewer)
        assert secret not in payload["state"]["cards"]


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("copies", [0, 2])
def test_four_ai_policies_choose_native_targets_without_opponent_private_identity(policy, copies):
    state = _begin(_state(copies=copies)).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision)
    assert decision.action.action_type == "resolve_effect"
    assert decision.action.payload.get("selected_card_instance_ids", []) in (
        [["member-0"], ["member-1"]] if copies else [[]]
    )
    changed = state.model_copy(deep=True)
    changed.cards["opponent-secret"].card.name_ja = "嵐 千砂都"
    changed.cards["opponent-secret"].card.card_code = "HIDDEN-CHANGED"
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}).action == decision.action
    assert not apply_action(state, decision.action).state.pending_effects


def test_candidate_is_review_only_and_registry_matches_its_structured_contract():
    assert not any(c.effect_id == EFFECT for c in discover_effect_candidates(Path("data/loveca.sqlite3")))
    effect = next(e for e in load_effect_registry().effects if e.effect_id == EFFECT)
    candidate = EffectDefinition.model_validate(_candidate().to_registry_entry())
    assert effect == candidate
    assert effect.review_status == "test_validated" and effect.simulation_support == "test_validated_executable"
