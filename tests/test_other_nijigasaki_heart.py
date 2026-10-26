from contextlib import closing
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_effect_execution import _minimal_effect_state

from loveca.db.bootstrap import connect_database
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import (
    IllegalActionError,
    _branch_choice_filter,
    _effect_candidates_for_choice,
    _effective_member_play_cost,
    apply_action,
    generate_legal_actions,
)
from loveca.simulation.models import ActionRequest, MatchState
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!N-PR-036"
EFFECT = CODE + ":1"
RULE_REFERENCE_IDS = ("2.6.1", "9.6.3.1", "9.6.3.1.3", "11.5.2", "8.4.11", "4.1.4")


@lru_cache
def _candidate():
    return next(
        c
        for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
        if c.effect_id == EFFECT
    )


def _state(cost=15, *, empty=False, legacy=False):
    effect = EffectDefinition.model_validate(_candidate().to_registry_entry())
    if legacy:
        raw = effect.model_dump(mode="json")
        raw.update(
            choice=None,
            execution_mode="manual_resolution",
            simulation_support="manual_resolution",
            review_status="parsed_draft",
            actions=[{"action_type": "manual_resolution"}],
            source_reference=(
                "Official card text; timing-only manual fallback pending structured effect modeling"
            ),
        )
        effect = EffectDefinition.model_validate(raw)
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        card = _load_definition(connection, CODE, None, {EFFECT: effect}, {})
    state = _minimal_effect_state(effect)
    state.phase = "performance_first"
    state.pending_effects = []
    state.effect_order_policy = "ap_nap_player_choice"
    state.stage_departure_policy = "clear_departed_card_modifiers"
    state.cards["source-live"].card = card
    state.players["player_1"].member_area["center"] = "source-live"
    template = state.cards["deck-member-1"].model_copy(deep=True)
    template.card.work_keys = ["nijigasaki"]
    template.card.cost = cost
    template.card.effect_ids = []
    for key in ("target", "wrong-work", "held", "attached", "opponent"):
        state.cards[key] = template.model_copy(
            update={"instance_id": key, "face_up": True}, deep=True
        )
    state.cards["wrong-work"].card.work_keys = ["hasunosora"]
    state.players["player_1"].member_area["left"] = None if empty else "target"
    state.players["player_1"].member_area["right"] = "wrong-work"
    state.players["player_1"].hand = ["held"]
    state.players["player_1"].member_area_attachments["right"] = ["attached"]
    state.cards["opponent"].owner_id = "player_2"
    state.players["player_2"].member_area["left"] = "opponent"
    return state


def _begin(state):
    return apply_action(
        state,
        ActionRequest(
            action_type="advance_phase", player_id="player_1", expected_revision=state.revision
        ),
    )


def _resolve(state, selected=None):
    return ActionRequest(
        action_type="resolve_effect",
        player_id="player_1",
        expected_revision=state.revision,
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": ["target"] if selected is None else selected,
        },
    )


def test_original_manual_snapshot_reproduces_blocker():
    started = _begin(_state(legacy=True))
    option = next(a for a in started.legal_actions if a.action_type == "resolve_effect")
    assert option.options["invocations"][0]["simulation_support"] == "manual_resolution"


def test_exact_segment_identity_and_restricted_candidate():
    c = _candidate()
    assert c.pattern_id == "live_start_other_nijigasaki_cost_heart"
    assert c.text_revision_id == 1225
    assert c.raw_text_hash == "efcae675449686825bdddf0b5f7a013d74837a06441dfa296f1677bed2d04ab4"
    assert not c.condition and not c.cost and not c.is_optional
    assert c.choice["exclude_source"] and c.choice["work_key"] == "nijigasaki"
    assert c.actions[0]["amount_source"] == "selected_member_cost15_heart_amount"
    registered = next(e for e in load_effect_registry().effects if e.effect_id == EFFECT)
    assert registered == EffectDefinition.model_validate(c.to_registry_entry())
    assert registered.review_status == "test_validated"


@pytest.mark.parametrize("cost,amount", [(14, 1), (15, 2), (16, 2)])
def test_native_choice_filters_other_members_and_adds_one_or_two_hearts(cost, amount):
    started = _begin(_state(cost))
    options = next(a for a in started.legal_actions if a.action_type == "resolve_effect")
    assert options.options["invocations"][0]["candidate_card_instance_ids"] == ["target"]
    result = apply_action(started.state, _resolve(started.state))
    modifiers = result.state.players["player_1"].manual_modifiers
    assert len(modifiers) == 1
    assert (
        modifiers[0].modifier_type,
        modifiers[0].target_card_instance_id,
        modifiers[0].color_slot,
        modifiers[0].amount,
        modifiers[0].duration,
    ) == ("heart", "target", "heart03", amount, "live")
    assert result.state.phase == "yell_first" and not result.state.pending_effects


@pytest.mark.parametrize(
    "bad",
    [
        [],
        ["source-live"],
        ["wrong-work"],
        ["held"],
        ["attached"],
        ["opponent"],
        ["missing"],
        ["target", "target"],
    ],
)
def test_illegal_choice_is_atomic(bad):
    state = _begin(_state()).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, bad))
    assert match_state_hash(state) == before


def test_no_target_finishes_explicitly_without_source_fallback():
    started = _begin(_state(empty=True)).state
    result = apply_action(started, _resolve(started, []))
    assert not result.state.players["player_1"].manual_modifiers
    assert not result.state.pending_effects and result.state.phase == "yell_first"
    assert any(e.data.get("reason") == "no_legal_stage_member_at_resolution" for e in result.events)


def test_target_departing_before_selection_does_not_grant_to_source():
    state = _begin(_state()).state
    state.players["player_1"].member_area["left"] = None
    state.players["player_1"].waiting_room.append("target")
    result = apply_action(state, _resolve(state, []))
    assert not result.state.pending_effects
    assert not result.state.players["player_1"].manual_modifiers


def test_payment_reduction_is_not_card_information_cost():
    state = _state(15)
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(
        effect_id="AUDIT-reduction:1",
        card_code="TEST-MEMBER",
        choice=None,
        effect_type="continuous",
        timing="static_always",
        trigger="static_always",
        execution_mode="auto_resolve",
        frequency_limit="none",
        duration=None,
        actions=[{"action_type": "reduce_play_cost", "amount": 10}],
    )
    effect = EffectDefinition.model_validate(raw)
    state.effect_definitions[effect.effect_id] = effect
    state.cards["target"].card.effect_ids = [effect.effect_id]
    assert _effective_member_play_cost(state, "player_1", "target") == 5
    started = _begin(state).state
    result = apply_action(started, _resolve(started))
    assert result.state.players["player_1"].manual_modifiers[0].amount == 2


@pytest.mark.parametrize("before,after,amount", [(14, 15, 2), (15, 14, 1)])
def test_selected_card_cost_is_read_at_resolution(before, after, amount):
    state = _begin(_state(before)).state
    # Controlled ordered-effect boundary, not an extra player action while pending.
    state.cards["target"].card.cost = after
    result = apply_action(state, _resolve(state))
    assert result.state.players["player_1"].manual_modifiers[0].amount == amount


@pytest.mark.parametrize(
    "defect",
    [
        "policy",
        "color",
        "cost",
        "optional",
        "action",
        "threshold",
        "extra_filter",
        "wrong_target_player",
        "extra_operation_field",
    ],
)
def test_bounded_policy_rejects_unmodeled_semantics(defect):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    if defect == "policy":
        raw["choice"]["selection_policy"] = None
    elif defect == "color":
        raw["actions"][0]["color_slot"] = "heart01"
    elif defect == "cost":
        raw["cost"] = [{"action_type": "pay_energy", "amount": 1}]
    elif defect == "optional":
        raw["is_optional"] = True
    elif defect == "action":
        raw["actions"][0]["action_type"] = "draw_card"
    elif defect == "threshold":
        raw["actions"][0]["value"] = {"minimum_cost": 14}
    elif defect == "extra_filter":
        raw["choice"]["exclude_name_ja_any"] = ["excluded"]
    elif defect == "wrong_target_player":
        raw["choice"]["target_player"] = "opponent"
    else:
        raw["actions"][0]["orientation"] = "wait"
    with pytest.raises(ValueError):
        EffectDefinition.model_validate(raw)


def _controlled_state():
    state = _state(empty=True)
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(
        effect_id="AUDIT-control:1",
        card_code="AUDIT-control",
        choice=None,
        execution_mode="manual_resolution",
        simulation_support="manual_resolution",
        review_status="parsed_draft",
        actions=[{"action_type": "manual_resolution"}],
    )
    effect = EffectDefinition.model_validate(raw)
    state.effect_definitions[effect.effect_id] = effect
    key = "control-live"
    state.cards[key] = state.cards["live-1"].model_copy(update={"instance_id": key}, deep=True)
    state.cards[key].card.effect_ids = [effect.effect_id]
    state.players["player_1"].live_area.append(key)
    return state


def _move_source(state, *, reenter=True, within_stage=False):
    control = next(i for i in state.pending_effects if i.effect_id == "AUDIT-control:1")
    destinations = ["member_left"] if within_stage else ["waiting_room"]
    if reenter and not within_stage:
        destinations.append("member_center")
    return ActionRequest(
        action_type="manual_adjustment",
        player_id="player_1",
        expected_revision=state.revision,
        payload={
            "source_invocation_id": control.invocation_id,
            "source_effect_id": control.effect_id,
            "source_card_instance_id": "control-live",
            "adjustments": [
                {
                    "adjustment_type": "move_card",
                    "target_player_id": "player_1",
                    "target_card_instance_id": "source-live",
                    "to_zone": destination,
                }
                for destination in destinations
            ],
        },
    )


@pytest.mark.parametrize("mode", ["departed", "returned", "within_stage"])
def test_source_object_identity_and_sql_replay_across_native_zone_moves(tmp_path, mode):
    initial = _controlled_state()
    repository = MatchRepository(tmp_path / "objects.sqlite3")
    repository.create_match(initial, card_database_path=Path("data/loveca.sqlite3"))
    started = repository.apply(
        initial.match_id,
        ActionRequest(
            action_type="advance_phase", player_id="player_1", expected_revision=initial.revision
        ),
    ).state
    state = repository.apply(
        initial.match_id,
        _move_source(started, reenter=mode == "returned", within_stage=mode == "within_stage"),
    ).state
    invocation = next(i for i in state.pending_effects if i.effect_id == EFFECT)
    assert invocation.trigger_data["original_source_stage_object"] is True
    candidates = next(
        a for a in generate_legal_actions(state) if a.action_type == "resolve_effect"
    ).options["invocations"][0]
    expected = ["source-live"] if mode == "returned" else []
    assert candidates["candidate_card_instance_ids"] == expected
    result = repository.apply(initial.match_id, _resolve(state, expected))
    modifiers = result.state.players["player_1"].manual_modifiers
    assert [(m.target_card_instance_id, m.amount) for m in modifiers] == (
        [("source-live", 1)] if mode == "returned" else []
    )
    replay = repository.replay(initial.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")


@pytest.mark.parametrize("legacy", [False, True])
def test_new_and_legacy_snapshot_sql_replay(tmp_path, legacy):
    state = _state(legacy=legacy)
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    started = repository.apply(
        state.match_id,
        ActionRequest(
            action_type="advance_phase", player_id="player_1", expected_revision=state.revision
        ),
    )
    if legacy:
        with pytest.raises(IllegalActionError):
            repository.apply(state.match_id, _resolve(started.state))
        final = started
    else:
        final = repository.apply(state.match_id, _resolve(started.state))
    replay = repository.replay(state.match_id)
    assert replay["final_state"] == final.state.model_dump(mode="json")
    restored = MatchState.model_validate(replay["final_state"])
    assert match_state_hash(restored) == match_state_hash(final.state)


def test_target_departure_clears_bonus_and_reentry_does_not_inherit():
    started = _begin(_state()).state
    state = apply_action(started, _resolve(started)).state
    result = apply_action(
        state,
        ActionRequest(
            action_type="manual_adjustment",
            player_id="player_1",
            expected_revision=state.revision,
            payload={
                "adjustments": [
                    {
                        "adjustment_type": "move_card",
                        "target_player_id": "player_1",
                        "target_card_instance_id": "target",
                        "to_zone": zone,
                    }
                    for zone in ["waiting_room", "member_left"]
                ]
            },
        ),
    )
    assert not result.state.players["player_1"].manual_modifiers


def test_live_end_expires_only_the_live_duration_bonus():
    started = _begin(_state()).state
    state = apply_action(started, _resolve(started)).state
    state.phase, state.active_player_id = "live_judgment", None
    result = apply_action(
        state, ActionRequest(action_type="advance_phase", expected_revision=state.revision)
    )
    assert not result.state.players["player_1"].manual_modifiers


@pytest.mark.parametrize(
    "policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"]
)
@pytest.mark.parametrize("empty", [False, True])
def test_four_ai_policies_and_private_hand_independence(policy, empty):
    state = _begin(_state(empty=empty)).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    decision = controller.choose_action(
        state, generate_legal_actions(state), controlled_player_ids={"player_1"}
    )
    assert isinstance(decision, SimpleAIDecision)
    assert decision.action.action_type == "resolve_effect"
    changed = state.model_copy(deep=True)
    # Opponent's private identity must not affect a public own-Stage choice.
    key = "secret"
    for snapshot, code in [(state, "SECRET-A"), (changed, "SECRET-B")]:
        snapshot.cards[key] = snapshot.cards["opponent"].model_copy(
            update={"instance_id": key, "face_up": False}, deep=True
        )
        snapshot.cards[key].card.card_code = code
        snapshot.players["player_2"].hand = [key]
    assert (
        controller.choose_action(
            changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}
        ).action
        == decision.action
    )
    result = apply_action(state, decision.action)
    assert not result.state.pending_effects
    for viewer, hidden in [("player_1", key), ("player_2", "held")]:
        payload = _match_state_payload(
            result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer
        )
        assert hidden not in payload["state"]["cards"]


def test_second_player_selects_its_own_other_nijigasaki_member():
    state = _state()
    own, other = state.players["player_1"], state.players["player_2"]
    state.players = {
        "player_1": other.model_copy(update={"player_id": "player_1"}, deep=True),
        "player_2": own.model_copy(update={"player_id": "player_2"}, deep=True),
    }
    for card in state.cards.values():
        card.owner_id = "player_2" if card.owner_id == "player_1" else "player_1"
    state.first_player_id, state.second_player_id = "player_2", "player_1"
    state.active_player_id = "player_2"
    started = apply_action(
        state,
        ActionRequest(
            action_type="advance_phase", player_id="player_2", expected_revision=state.revision
        ),
    ).state
    invocation = started.pending_effects[0]
    result = apply_action(
        started,
        ActionRequest(
            action_type="resolve_effect",
            player_id="player_2",
            expected_revision=started.revision,
            payload={
                "invocation_id": invocation.invocation_id,
                "selected_card_instance_ids": ["target"],
            },
        ),
    )
    assert result.state.players["player_2"].manual_modifiers[0].amount == 2
    assert not result.state.players["player_1"].manual_modifiers


@pytest.mark.parametrize("departed", [False, True])
def test_legacy_branch_choice_adapter_without_selection_policy_still_excludes_source(departed):
    state = _begin(_state()).state
    invocation = state.pending_effects[0]
    invocation.trigger_data["original_source_stage_object_departed"] = departed
    effect = SimpleNamespace(
        choice=SimpleNamespace(
            branch_choice_filters={
                "old": {
                    "choice_type": "member_from_stage",
                    "zone": "stage",
                    "card_type": "member",
                    "exclude_source": True,
                }
            }
        )
    )
    choice = _branch_choice_filter(effect, "old")
    assert not hasattr(choice, "selection_policy")
    assert set(_effect_candidates_for_choice(state, invocation, choice)) == {"target", "wrong-work"}
