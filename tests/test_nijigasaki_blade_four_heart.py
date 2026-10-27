from contextlib import closing
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_effect_execution import _minimal_effect_state

from loveca.db.bootstrap import connect_database
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import (
    IllegalActionError,
    _effect_candidates_for_choice,
    _effective_member_blade,
    apply_action,
    generate_legal_actions,
)
from loveca.simulation.models import ActionRequest, ManualModifier, MatchState
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!N-sd2-026"
EFFECT = CODE + ":1"
RULE_REFERENCE_IDS = (
    "2.8.1",
    "2.8.2",
    "9.9.1.1",
    "9.9.1.5",
    "9.6.3.1",
    "9.6.3.1.3",
    "11.5.2",
    "8.4.11",
)


@lru_cache
def _candidate():
    return next(
        c
        for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
        if c.effect_id == EFFECT
    )


def _state(blade=4, *, legacy=False):
    effect = EffectDefinition.model_validate(_candidate().to_registry_entry())
    if legacy:
        raw = effect.model_dump(mode="json")
        raw.update(
            choice=None,
            execution_mode="manual_resolution",
            simulation_support="manual_resolution",
            review_status="parsed_draft",
            actions=[{"action_type": "manual_resolution"}],
        )
        effect = EffectDefinition.model_validate(raw)
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        card = _load_definition(connection, CODE, None, {EFFECT: effect}, {})
    assert card.card_type == "live"
    state = _minimal_effect_state(effect)
    state.pending_effects = []
    state.phase, state.active_player_id = "performance_first", "player_1"
    state.effect_order_policy = "ap_nap_player_choice"
    state.stage_departure_policy = "clear_departed_card_modifiers"
    state.cards["source-live"].card = card
    state.cards["source-live"].face_up = False
    player = state.players["player_1"]
    player.live_area = ["source-live"]
    template = state.cards["deck-member-1"]
    for key in ["target", "wrong-work", "held", "attached", "opponent", "secret"]:
        state.cards[key] = template.model_copy(
            update={"instance_id": key, "face_up": True}, deep=True
        )
        state.cards[key].card.work_keys = ["nijigasaki"]
        state.cards[key].card.blade = blade
        state.cards[key].card.effect_ids = []
    state.cards["wrong-work"].card.work_keys = ["aqours"]
    player.member_area = {"left": "target", "center": None, "right": "wrong-work"}
    player.member_area_attachments["right"] = ["attached"]
    player.hand = ["held"]
    state.cards["opponent"].owner_id = state.cards["secret"].owner_id = "player_2"
    state.cards["secret"].face_up = False
    state.players["player_2"].member_area["left"] = "opponent"
    state.players["player_2"].hand = ["secret"]
    return state


def _begin(state):
    return apply_action(
        state,
        ActionRequest(
            action_type="advance_phase",
            player_id=state.active_player_id,
            expected_revision=state.revision,
        ),
    )


def _resolve(state, selected=None, **extra):
    invocation = next(i for i in state.pending_effects if i.effect_id == EFFECT)
    return ActionRequest(
        action_type="resolve_effect",
        player_id=invocation.player_id,
        expected_revision=state.revision,
        payload={
            "invocation_id": invocation.invocation_id,
            "selected_card_instance_ids": ["target"] if selected is None else selected,
            **extra,
        },
    )


def _options(state):
    return next(
        a for a in generate_legal_actions(state) if a.action_type == "resolve_effect"
    ).options["invocations"][0]


def _modifier(state, amount, *, target="target", kind="blade"):
    state.players["player_1"].manual_modifiers.append(
        ManualModifier(
            modifier_id="AUDIT-modifier",
            modifier_type=kind,
            duration="live",
            created_turn=state.turn_number,
            amount=amount,
            target_card_instance_id=target,
        )
    )


def _static(state, amount):
    raw = deepcopy(_candidate().to_registry_entry())
    raw.update(
        effect_id="AUDIT-static",
        choice=None,
        effect_type="continuous",
        timing="static_always",
        trigger="static_always",
        execution_mode="auto_resolve",
        frequency_limit="none",
        duration=None,
        actions=[{"action_type": "gain_blade", "amount": amount}],
    )
    effect = EffectDefinition.model_validate(raw)
    state.effect_definitions[effect.effect_id] = effect
    state.cards["target"].card.effect_ids = [effect.effect_id]


def test_identity_and_old_manual_blocker():
    c = _candidate()
    assert c.pattern_id == "live_start_nijigasaki_blade_four_heart"
    assert c.text_revision_id == 958
    assert c.raw_text_hash == "8b847fb338647ea95bba010ac586cf3e5880289f44ee9a5a0de0c4119ffa0ebb"
    assert c.choice["minimum_blade"] == 4 and c.choice["minimum"] == c.choice["maximum"] == 1
    assert not c.is_optional and not c.cost and not c.condition
    assert _options(_begin(_state(legacy=True)).state)["simulation_support"] == "manual_resolution"


@pytest.mark.parametrize("blade", [3, 4, 5])
@pytest.mark.parametrize("orientation", ["active", "wait"])
def test_native_blade_threshold_and_only_selected_target_gets_two_hearts(blade, orientation):
    state = _state(blade)
    state.cards["target"].orientation = orientation
    started = _begin(state).state
    assert _options(started)["candidate_card_instance_ids"] == ([] if blade < 4 else ["target"])
    resolved = apply_action(started, _resolve(started, [] if blade < 4 else ["target"]))
    mods = resolved.state.players["player_1"].manual_modifiers
    assert [
        (m.modifier_type, m.target_card_instance_id, m.color_slot, m.amount, m.duration)
        for m in mods
    ] == ([] if blade < 4 else [("heart", "target", "heart02", 2, "live")])
    assert not resolved.state.pending_effects and resolved.state.phase == "yell_first"
    if blade < 4:
        assert any(
            e.data.get("reason") == "no_legal_stage_member_at_resolution" for e in resolved.events
        )


@pytest.mark.parametrize(
    "selected",
    [
        [],
        ["wrong-work"],
        ["held"],
        ["attached"],
        ["opponent"],
        ["source-live"],
        ["target", "target"],
        ["missing"],
    ],
)
def test_bad_selection_is_atomic(selected):
    state = _begin(_state()).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, selected))
    assert match_state_hash(state) == before


def test_mandatory_cannot_be_declined_or_advanced_past():
    state = _begin(_state()).state
    for request in [
        _resolve(state, accepted=False),
        ActionRequest(
            action_type="advance_phase", player_id="player_1", expected_revision=state.revision
        ),
    ]:
        before = match_state_hash(state)
        with pytest.raises(IllegalActionError):
            apply_action(state, request)
        assert match_state_hash(state) == before


@pytest.mark.parametrize(
    "base,temporary,static,eligible",
    [
        (3, 1, 0, True),
        (5, -2, 0, False),
        (3, 0, 1, True),
        (5, 0, -2, False),
        (2, 1, 1, True),
        (4, -2, 1, False),
    ],
)
def test_effective_blade_combines_targeted_and_static_modifiers(base, temporary, static, eligible):
    state = _state(base)
    if temporary:
        _modifier(state, temporary)
    if static:
        _static(state, static)
    assert _effective_member_blade(state, "player_1", "target") == max(0, base + temporary + static)
    started = _begin(state).state
    assert ("target" in _options(started)["candidate_card_instance_ids"]) is eligible
    result = apply_action(started, _resolve(started, ["target"] if eligible else []))
    hearts = [
        m for m in result.state.players["player_1"].manual_modifiers if m.modifier_type == "heart"
    ]
    assert len(hearts) == int(eligible)


def test_player_yell_blade_bonus_is_not_member_blade_information():
    state = _state(3)
    _modifier(state, 20, target=None)
    assert _effective_member_blade(state, "player_1", "target") == 3
    started = _begin(state).state
    assert _options(started)["candidate_card_instance_ids"] == []
    assert not apply_action(started, _resolve(started, [])).state.pending_effects


@pytest.mark.parametrize("base,replacement,eligible", [(3, 5, True), (5, 3, False)])
def test_existing_base_blade_information_replacement_is_used(base, replacement, eligible):
    state = _state(base)
    _modifier(state, replacement, kind="base_blade_replacement")
    started = _begin(state).state
    assert ("target" in _options(started)["candidate_card_instance_ids"]) is eligible


@pytest.mark.parametrize("before,delta,eligible", [(3, 1, True), (4, -1, False)])
def test_native_ordered_effect_changes_target_eligibility_at_resolution(before, delta, eligible):
    state = _state(before)
    raw = deepcopy(_candidate().to_registry_entry())
    raw.update(
        effect_id="AUDIT-ordered",
        choice=None,
        actions=[{"action_type": "gain_blade", "target": "source", "amount": delta}],
    )
    control = EffectDefinition.model_validate(raw)
    state.effect_definitions[control.effect_id] = control
    state.cards["target"].card.effect_ids = [control.effect_id]
    started = _begin(state).state
    invocation = next(i for i in started.pending_effects if i.effect_id == control.effect_id)
    changed = apply_action(
        started,
        ActionRequest(
            action_type="resolve_effect",
            player_id="player_1",
            expected_revision=started.revision,
            payload={"invocation_id": invocation.invocation_id},
        ),
    ).state
    assert ("target" in _options(changed)["candidate_card_instance_ids"]) is eligible
    result = apply_action(changed, _resolve(changed, ["target"] if eligible else []))
    assert not result.state.pending_effects
    assert len(
        [m for m in result.state.players["player_1"].manual_modifiers if m.modifier_type == "heart"]
    ) == int(eligible)


@pytest.mark.parametrize("legacy", [False, True])
def test_sql_replay_preserves_new_and_manual_snapshots(tmp_path, legacy):
    state = _state(legacy=legacy)
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    started = repository.apply(
        state.match_id,
        ActionRequest(
            action_type="advance_phase", player_id="player_1", expected_revision=state.revision
        ),
    )
    final = started if legacy else repository.apply(state.match_id, _resolve(started.state))
    replay = repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")
    assert match_state_hash(MatchState.model_validate(replay["final_state"])) == match_state_hash(
        final.state
    )


@pytest.mark.parametrize(
    "policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"]
)
@pytest.mark.parametrize("empty", [False, True])
def test_four_ai_policies_hidden_identity_invariance_and_viewer_privacy(policy, empty):
    state = _begin(_state(3 if empty else 4)).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    decision = controller.choose_action(
        state, generate_legal_actions(state), controlled_player_ids={"player_1"}
    )
    assert (
        isinstance(decision, SimpleAIDecision) and decision.action.action_type == "resolve_effect"
    )
    changed = state.model_copy(deep=True)
    changed.cards["secret"].card = changed.cards["source-live"].card.model_copy(deep=True)
    assert (
        controller.choose_action(
            changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}
        ).action
        == decision.action
    )
    resolved = apply_action(state, decision.action)
    assert not resolved.state.pending_effects
    for viewer, hidden in [("player_1", "secret"), ("player_2", "held")]:
        payload = _match_state_payload(
            resolved.state,
            events=resolved.events,
            legal_actions=resolved.legal_actions,
            player_id=viewer,
        )
        assert hidden not in payload["state"]["cards"]


def test_live_expiry_and_target_departure_clear_the_heart_bonus():
    started = _begin(_state()).state
    resolved = apply_action(started, _resolve(started)).state
    resolved.phase, resolved.active_player_id = "live_judgment", None
    assert not _begin(resolved).state.players["player_1"].manual_modifiers
    started = _begin(_state()).state
    resolved = apply_action(started, _resolve(started)).state
    moved = apply_action(
        resolved,
        ActionRequest(
            action_type="manual_adjustment",
            player_id="player_1",
            expected_revision=resolved.revision,
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
    assert not moved.state.players["player_1"].manual_modifiers


@pytest.mark.parametrize(
    "choice_update",
    [
        {"minimum_blade": 3},
        {"minimum": 0},
        {"maximum": 2},
        {"work_key": "aqours"},
        {"target_player": "opponent"},
        {"minimum_original_blade": 4},
    ],
)
def test_choice_policy_does_not_widen(choice_update):
    raw = deepcopy(_candidate().to_registry_entry())
    raw["choice"].update(choice_update)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize(
    "update",
    [
        {"is_optional": True},
        {"duration": None},
        {"trigger": "member_played"},
        {
            "actions": [
                {
                    "action_type": "gain_heart",
                    "target": "source",
                    "amount": 2,
                    "color_slot": "heart02",
                }
            ]
        },
        {
            "actions": [
                {
                    "action_type": "gain_heart",
                    "target": "selected",
                    "amount": 1,
                    "color_slot": "heart02",
                }
            ]
        },
        {"cost": [{"action_type": "pay_energy", "amount": 1}]},
    ],
)
def test_effect_policy_rejects_different_semantics(update):
    raw = deepcopy(_candidate().to_registry_entry())
    raw.update(update)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


def test_two_eligible_members_require_an_explicit_single_selection():
    state = _state()
    state.cards["second"] = state.cards["target"].model_copy(
        update={"instance_id": "second"}, deep=True
    )
    state.players["player_1"].member_area["center"] = "second"
    started = _begin(state).state
    assert set(_options(started)["candidate_card_instance_ids"]) == {"target", "second"}
    with pytest.raises(IllegalActionError):
        apply_action(started, _resolve(started, ["target", "second"]))
    resolved = apply_action(started, _resolve(started, ["second"]))
    assert [
        m.target_card_instance_id for m in resolved.state.players["player_1"].manual_modifiers
    ] == ["second"]


def test_old_choice_snapshot_keeps_its_original_blade_filter():
    state = _state(3)
    _static(state, 1)
    started = _begin(state).state
    invocation = started.pending_effects[0]
    old_choice = started.effect_definitions[EFFECT].choice.model_copy(
        update={"selection_policy": None}
    )
    assert _effect_candidates_for_choice(started, invocation, old_choice) == []
    assert _options(started)["candidate_card_instance_ids"] == ["target"]


@pytest.mark.parametrize("returned", [False, True])
def test_native_pending_target_departure_and_reentry(returned):
    state = _state()
    raw = _state(legacy=True).effect_definitions[EFFECT].model_dump(mode="json")
    raw["effect_id"] = "AUDIT-move"
    control = EffectDefinition.model_validate(raw)
    state.effect_definitions[control.effect_id] = control
    state.cards["control-live"] = state.cards["source-live"].model_copy(
        update={"instance_id": "control-live"}, deep=True
    )
    state.cards["control-live"].card.effect_ids = [control.effect_id]
    state.players["player_1"].live_area.append("control-live")
    started = _begin(state).state
    invocation = next(i for i in started.pending_effects if i.effect_id == control.effect_id)
    changed = apply_action(
        started,
        ActionRequest(
            action_type="manual_adjustment",
            player_id="player_1",
            expected_revision=started.revision,
            payload={
                "source_invocation_id": invocation.invocation_id,
                "source_effect_id": control.effect_id,
                "source_card_instance_id": "control-live",
                "adjustments": [
                    {
                        "adjustment_type": "move_card",
                        "target_player_id": "player_1",
                        "target_card_instance_id": "target",
                        "to_zone": zone,
                    }
                    for zone in (["waiting_room", "member_left"] if returned else ["waiting_room"])
                ],
            },
        ),
    ).state
    assert _options(changed)["candidate_card_instance_ids"] == (["target"] if returned else [])
    resolved = apply_action(changed, _resolve(changed, ["target"] if returned else []))
    assert len(resolved.state.players["player_1"].manual_modifiers) == int(returned)


def test_second_player_uses_its_own_targets():
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
    started = _begin(state).state
    result = apply_action(started, _resolve(started))
    assert result.state.players["player_2"].manual_modifiers[0].target_card_instance_id == "target"
    assert not result.state.players["player_1"].manual_modifiers
