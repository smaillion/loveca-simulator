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
    _card_score,
    _effective_member_blade,
    apply_action,
    generate_legal_actions,
)
from loveca.simulation.models import ActionRequest, ManualModifier, MatchState
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!S-bp3-025"
EFFECT = CODE + ":1"
RULE_REFERENCE_IDS = (
    "2.8.1",
    "2.10.1",
    "4.1.4",
    "8.3.8",
    "8.4.2",
    "9.6.3.1",
    "9.6.3.1.3",
    "9.9.1.5",
)


@lru_cache
def _candidate():
    return next(
        c
        for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
        if c.effect_id == EFFECT
    )


def _definition(legacy=False):
    raw = deepcopy(_candidate().to_registry_entry())
    if legacy:
        raw.update(
            choice={
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "minimum": 1,
                "maximum": 1,
                "work_key": "love_live_sunshine",
                "minimum_blade": 6,
            },
            actions=[{"action_type": "modify_score", "amount": 1}],
        )
    return EffectDefinition.model_validate(raw)


def _state(blade=6, *, legacy=False):
    effect = _definition(legacy)
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        card = _load_definition(connection, CODE, None, {EFFECT: effect}, {})
    assert card.card_type == "live"
    state = _minimal_effect_state(effect)
    state.pending_effects = []
    state.phase, state.active_player_id = "performance_first", "player_1"
    state.effect_order_policy = "ap_nap_player_choice"
    player = state.players["player_1"]
    state.cards["source-live"].card = card
    player.live_area = ["source-live", "live-1"]
    template = state.cards["deck-member-1"]
    for key in ["target", "wrong-work", "held", "attached", "opponent", "secret"]:
        state.cards[key] = template.model_copy(update={"instance_id": key}, deep=True)
        state.cards[key].card.effect_ids = []
        state.cards[key].card.blade = blade
        state.cards[key].card.work_keys = ["aqours", "love_live_sunshine"]
    state.cards["wrong-work"].card.work_keys = ["nijigasaki"]
    player.member_area = {"left": "target", "center": None, "right": "wrong-work"}
    player.hand = ["held"]
    player.member_area_attachments["right"] = ["attached"]
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


def test_low_blade_must_still_be_selectable_before_the_body_condition():
    started = _begin(_state(5)).state
    assert started.pending_effects, (
        "Blade5 must be selectable; >=6 is a body condition, not a target filter"
    )
    assert _options(started)["candidate_card_instance_ids"] == ["target"]
    result = apply_action(started, _resolve(started))
    assert not result.state.players["player_1"].manual_modifiers


def test_bonus_must_be_bound_to_source_live_instead_of_player_global_score():
    state = _state()
    before = _card_score(state, "player_1", "source-live")
    started = _begin(state).state
    result = apply_action(started, _resolve(started))
    assert _card_score(result.state, "player_1", "source-live") == before + 1
    assert _card_score(result.state, "player_1", "live-1") == _card_score(
        state, "player_1", "live-1"
    )
    assert all(
        m.modifier_type != "score" for m in result.state.players["player_1"].manual_modifiers
    )


def test_legacy_snapshot_preserves_recorded_wrong_behavior_for_replay_only():
    low = _begin(_state(5, legacy=True))
    assert not low.state.pending_effects
    assert any(e.data.get("reason") == "choice_candidates_unavailable" for e in low.events)
    high = _begin(_state(6, legacy=True)).state
    result = apply_action(high, _resolve(high))
    assert [
        (m.modifier_type, m.target_card_instance_id)
        for m in result.state.players["player_1"].manual_modifiers
    ] == [("score", None)]


def test_exact_identity_and_no_threshold_in_target_filter():
    c = _candidate()
    assert c.text_revision_id == 504
    assert c.raw_text_hash == "0016b3bd6db1b30ca828f2dec99189841d606578a9d974ba1aaf919a52510cbb"
    assert c.pattern_id == "live_start_aqours_selected_blade_six_source_score"
    assert "minimum_blade" not in c.choice
    assert c.choice["work_key"] == "aqours"
    assert not c.is_optional and not c.condition and not c.cost


@pytest.mark.parametrize("blade", [0, 5, 6, 7])
@pytest.mark.parametrize("orientation", ["active", "wait"])
def test_threshold_is_evaluated_after_selection_and_score_is_source_only(blade, orientation):
    state = _state(blade)
    state.cards["target"].orientation = orientation
    before = _card_score(state, "player_1", "source-live")
    started = _begin(state).state
    assert _options(started)["candidate_card_instance_ids"] == ["target"]
    result = apply_action(started, _resolve(started))
    assert _card_score(result.state, "player_1", "source-live") == before + int(blade >= 6)
    assert _card_score(result.state, "player_1", "live-1") == _card_score(
        state, "player_1", "live-1"
    )
    event = next(
        e for e in result.events if e.event_type == "effect_selected_blade_threshold_resolved"
    )
    assert event.data["selected_blade"] == blade
    assert event.data["score_delta"] == int(blade >= 6)


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
def test_illegal_selection_is_atomic(selected):
    state = _begin(_state()).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, selected))
    assert match_state_hash(state) == before


def test_no_aqours_members_finishes_explicitly_without_source_fallback():
    state = _state()
    state.players["player_1"].member_area["left"] = None
    started = _begin(state).state
    assert (
        _options(started)["card_selection_minimum"]
        == _options(started)["card_selection_maximum"]
        == 0
    )
    resolved = apply_action(started, _resolve(started, []))
    assert (
        not resolved.state.pending_effects
        and not resolved.state.players["player_1"].manual_modifiers
    )
    event = next(
        e for e in resolved.events if e.event_type == "effect_selected_blade_threshold_resolved"
    )
    assert event.data["selected_blade"] is None and event.data["score_delta"] == 0


def _modifier(state, amount, *, target="target"):
    state.players["player_1"].manual_modifiers.append(
        ManualModifier(
            modifier_id="AUDIT-blade",
            modifier_type="blade",
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


@pytest.mark.parametrize(
    "base,temporary,static,bonus",
    [
        (5, 1, 0, 1),
        (7, -2, 0, 0),
        (5, 0, 1, 1),
        (7, 0, -2, 0),
        (4, 1, 1, 1),
    ],
)
def test_effective_blade_includes_temporary_and_supported_static_modifiers(
    base, temporary, static, bonus
):
    state = _state(base)
    if temporary:
        _modifier(state, temporary)
    if static:
        _static(state, static)
    started = _begin(state).state
    assert _options(started)["candidate_blade_counts"] == {"target": base + temporary + static}
    assert _effective_member_blade(started, "player_1", "target") == base + temporary + static
    before = _card_score(state, "player_1", "source-live")
    resolved = apply_action(started, _resolve(started))
    assert _card_score(resolved.state, "player_1", "source-live") == before + bonus


@pytest.mark.parametrize("before,delta", [(5, 1), (6, -1)])
def test_native_ordered_effect_changes_body_condition_without_changing_targets(before, delta):
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
    assert _options(changed)["candidate_card_instance_ids"] == ["target"]
    resolved = apply_action(changed, _resolve(changed))
    assert _card_score(resolved.state, "player_1", "source-live") == (
        _card_score(state, "player_1", "source-live") + int(before + delta >= 6)
    )


def _move(state, key, destinations, *, invocation=None):
    payload = {
        "adjustments": [
            {
                "adjustment_type": "move_card",
                "target_player_id": "player_1",
                "target_card_instance_id": key,
                "to_zone": zone,
            }
            for zone in destinations
        ]
    }
    if invocation:
        payload.update(
            source_invocation_id=invocation.invocation_id,
            source_effect_id=invocation.effect_id,
            source_card_instance_id=invocation.source_card_instance_id,
        )
    return ActionRequest(
        action_type="manual_adjustment",
        player_id="player_1",
        expected_revision=state.revision,
        payload=payload,
    )


def _pending_move_state():
    state = _state()
    raw = deepcopy(_candidate().to_registry_entry())
    raw.update(
        effect_id="AUDIT-move",
        choice=None,
        execution_mode="manual_resolution",
        simulation_support="manual_resolution",
        review_status="parsed_draft",
        actions=[{"action_type": "manual_resolution"}],
    )
    control = EffectDefinition.model_validate(raw)
    state.effect_definitions[control.effect_id] = control
    state.cards["live-1"].card.effect_ids = [control.effect_id]
    return _begin(state).state


@pytest.mark.parametrize(
    "destinations,available",
    [
        (["waiting_room"], False),
        (["waiting_room", "live_area"], False),
        (["live_area"], True),
    ],
)
def test_native_pending_source_object_departure_and_return(destinations, available):
    state = _pending_move_state()
    control = next(i for i in state.pending_effects if i.effect_id == "AUDIT-move")
    changed = apply_action(
        state, _move(state, "source-live", destinations, invocation=control)
    ).state
    resolved = apply_action(changed, _resolve(changed))
    modifiers = resolved.state.players["player_1"].manual_modifiers
    assert len(modifiers) == int(available)
    if modifiers:
        assert modifiers[0].target_card_instance_id == "source-live"
    event = next(
        e for e in resolved.events if e.event_type == "effect_selected_blade_threshold_resolved"
    )
    assert event.data["source_available"] is available


@pytest.mark.parametrize(
    "destinations,preserve",
    [
        (["waiting_room"], False),
        (["waiting_room", "live_area"], False),
        (["live_area"], True),
    ],
)
def test_source_departure_clears_score_but_same_live_area_move_preserves_it(destinations, preserve):
    state = _begin(_state()).state
    state = apply_action(state, _resolve(state)).state
    changed = apply_action(state, _move(state, "source-live", destinations)).state
    assert len(changed.players["player_1"].manual_modifiers) == int(preserve)
    assert _card_score(changed, "player_1", "live-1") == _card_score(state, "player_1", "live-1")


@pytest.mark.parametrize("legacy", [False, True])
def test_sql_replay_keeps_new_and_historical_effect_snapshots(tmp_path, legacy):
    state = _state(legacy=legacy)
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    started = repository.apply(
        state.match_id,
        ActionRequest(
            action_type="advance_phase", player_id="player_1", expected_revision=state.revision
        ),
    )
    resolved = repository.apply(state.match_id, _resolve(started.state))
    replay = repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == resolved.state.model_dump(mode="json")
    assert match_state_hash(MatchState.model_validate(replay["final_state"])) == match_state_hash(
        resolved.state
    )


@pytest.mark.parametrize(
    "policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"]
)
@pytest.mark.parametrize("empty", [False, True])
def test_ai_legal_resolution_hidden_identity_invariance_and_viewer_privacy(policy, empty):
    state = _state()
    if empty:
        state.players["player_1"].member_area["left"] = None
    state = _begin(state).state
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


@pytest.mark.parametrize("policy", ["simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_ai_uses_engine_effective_blade_metadata_to_choose_a_scoring_target(policy):
    state = _state(5)
    state.cards["better"] = state.cards["target"].model_copy(
        update={"instance_id": "better"}, deep=True
    )
    state.cards["better"].card.blade = 6
    state.players["player_1"].member_area["center"] = "better"
    state = _begin(state).state
    decision = SimpleAIController(SimpleAIPolicy(policy_version=policy)).choose_action(
        state,
        generate_legal_actions(state),
        controlled_player_ids={"player_1"},
    )
    assert decision.action.payload["selected_card_instance_ids"] == ["better"]
    assert not apply_action(state, decision.action).state.pending_effects


@pytest.mark.parametrize(
    "choice_update",
    [{"minimum_blade": 6}, {"minimum": 0}, {"maximum": 2}, {"work_key": "nijigasaki"}],
)
def test_new_policy_rejects_pre_filtering_or_different_targets(choice_update):
    raw = deepcopy(_candidate().to_registry_entry())
    raw["choice"].update(choice_update)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


def test_pending_target_departure_resolves_without_a_target():
    state = _pending_move_state()
    control = next(i for i in state.pending_effects if i.effect_id == "AUDIT-move")
    changed = apply_action(
        state, _move(state, "target", ["waiting_room"], invocation=control)
    ).state
    assert _options(changed)["candidate_card_instance_ids"] == []
    assert not apply_action(changed, _resolve(changed, [])).state.pending_effects


def test_missing_original_live_object_marker_is_rejected_atomically():
    state = _begin(_state()).state
    state.pending_effects[0].trigger_data.pop("original_source_live_object")
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError, match="snapshot is missing"):
        apply_action(state, _resolve(state))
    assert match_state_hash(state) == before


def test_failed_live_cleanup_clears_bonus_before_same_id_can_return():
    state = _state()
    for key in state.players["player_1"].member_area.values():
        if key is not None:
            state.cards[key].card.basic_hearts = {}
    started = _begin(state).state
    resolved = apply_action(started, _resolve(started)).state
    yelled = _begin(resolved).state
    yelled = apply_action(
        yelled,
        ActionRequest(
            action_type="resolve_live_requirements",
            player_id="player_1",
            expected_revision=yelled.revision,
            payload={"live_instance_ids": ["source-live", "live-1"]},
        ),
    ).state
    assert "source-live" in yelled.players["player_1"].waiting_room
    assert not yelled.players["player_1"].manual_modifiers
    returned = apply_action(yelled, _move(yelled, "source-live", ["live_area"])).state
    assert _card_score(returned, "player_1", "source-live") == _card_score(
        state, "player_1", "source-live"
    )


def test_live_judgment_cleanup_expires_source_score():
    state = _state()
    state.players["player_1"].live_area = ["source-live"]
    started = _begin(state).state
    resolved = apply_action(started, _resolve(started)).state
    resolved.players["player_1"].live_result.requirements_satisfied = True
    resolved.phase, resolved.active_player_id = "live_judgment", None
    result = _begin(resolved)
    assert not result.state.players["player_1"].manual_modifiers
    assert "source-live" in result.state.players["player_1"].success_live_area


@pytest.mark.parametrize(
    "destinations", [["waiting_room"], ["waiting_room", "live_area"], ["live_area"]]
)
def test_pending_source_object_sql_replay(tmp_path, destinations):
    initial = _state()
    raw = deepcopy(_candidate().to_registry_entry())
    raw.update(
        effect_id="AUDIT-move",
        choice=None,
        execution_mode="manual_resolution",
        simulation_support="manual_resolution",
        review_status="parsed_draft",
        actions=[{"action_type": "manual_resolution"}],
    )
    control = EffectDefinition.model_validate(raw)
    initial.effect_definitions[control.effect_id] = control
    initial.cards["live-1"].card.effect_ids = [control.effect_id]
    repository = MatchRepository(tmp_path / "objects.sqlite3")
    repository.create_match(initial, card_database_path=Path("data/loveca.sqlite3"))
    started = repository.apply(
        initial.match_id,
        ActionRequest(
            action_type="advance_phase", player_id="player_1", expected_revision=initial.revision
        ),
    ).state
    invocation = next(i for i in started.pending_effects if i.effect_id == control.effect_id)
    changed = repository.apply(
        initial.match_id, _move(started, "source-live", destinations, invocation=invocation)
    ).state
    resolved = repository.apply(initial.match_id, _resolve(changed))
    replay = repository.replay(initial.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == resolved.state.model_dump(mode="json")


@pytest.mark.parametrize(
    "update",
    [
        {"is_optional": True},
        {"duration": None},
        {"actions": [{"action_type": "modify_score", "amount": 1}]},
        {"actions": [{"action_type": "modify_source_score_if_selected_blade_six", "amount": 2}]},
        {"cost": [{"action_type": "pay_energy", "amount": 1}]},
    ],
)
def test_new_policy_rejects_changed_operations(update):
    raw = deepcopy(_candidate().to_registry_entry())
    raw.update(update)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)
