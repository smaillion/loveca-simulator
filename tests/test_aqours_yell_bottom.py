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
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, LivePerformanceResult, MatchState
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!S-cl1-002"
EFFECT = CODE + ":1"
RULE_REFERENCE_IDS = ("8.4.4", "8.4.5", "8.4.8", "11.6.2", "4.1.4", "4.1.5.1", "9.6.3.1.1")


@lru_cache
def _candidate():
    return next(
        c
        for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
        if c.effect_id == EFFECT
    )


def _state(*, legacy=False):
    effect = EffectDefinition.model_validate(_candidate().to_registry_entry())
    if legacy:
        raw = effect.model_dump(mode="json")
        raw.update(
            choice=None,
            actions=[{"action_type": "manual_resolution"}],
            execution_mode="manual_resolution",
            simulation_support="manual_resolution",
            review_status="parsed_draft",
            duration="live",
        )
        effect = EffectDefinition.model_validate(raw)
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        card = _load_definition(connection, CODE, None, {EFFECT: effect}, {})
    state = _minimal_effect_state(effect)
    state.pending_effects = []
    state.phase, state.active_player_id = "live_judgment", None
    state.effect_order_policy = "ap_nap_player_choice"
    state.cards["source-live"].card = card
    state.players["player_1"].member_area["center"] = "source-live"
    player = state.players["player_1"]
    template_member = state.cards["deck-member-1"]
    template_live = state.cards["deck-live-1"]
    for key in ["aq-member", "aq-live", "aq-2", "aq-3", "wrong-work", "not-yell"]:
        template = template_live if key == "aq-live" else template_member
        state.cards[key] = template.model_copy(
            update={"instance_id": key, "face_up": True}, deep=True
        )
        state.cards[key].card.work_keys = ["nijigasaki"] if key == "wrong-work" else ["aqours"]
        state.cards[key].card.effect_ids = []
        player.resolution_area.append(key)
    history = list(player.resolution_area[:-1])
    player.live_result = LivePerformanceResult(
        requirements_satisfied=True,
        total_score=1,
        revealed_instance_ids=history,
        remaining_yell_instance_ids=None if legacy else list(history),
    )
    return state


def _begin(state):
    return apply_action(
        state, ActionRequest(action_type="advance_phase", expected_revision=state.revision)
    )


def _resolve(state, selected):
    return ActionRequest(
        action_type="resolve_effect",
        player_id="player_1",
        expected_revision=state.revision,
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": selected,
        },
    )


def test_exact_segment_and_legacy_manual_boundary():
    c = _candidate()
    assert c.pattern_id == "live_success_aqours_yell_bottom_three"
    assert c.text_revision_id == 961
    assert c.raw_text_hash == "78ec1681287a8bd2a185e7342012afd53d066ee9dea57b3e5b40fe6480c511f1"
    assert c.choice["requires_order"] and c.choice["minimum"] == 0 and c.choice["maximum"] == 3
    assert not c.is_optional and not c.cost and not c.condition
    started = _begin(_state(legacy=True))
    options = next(a for a in started.legal_actions if a.action_type == "resolve_effect").options
    assert options["invocations"][0]["simulation_support"] == "manual_resolution"


@pytest.mark.parametrize(
    "selected", [[], ["aq-live"], ["aq-member", "aq-live"], ["aq-2", "aq-live", "aq-member"]]
)
def test_native_success_choice_returns_zero_to_three_in_exact_order(selected):
    initial = _state()
    original_deck = list(initial.players["player_1"].main_deck)
    started = _begin(initial)
    options = next(a for a in started.legal_actions if a.action_type == "resolve_effect").options[
        "invocations"
    ][0]
    assert set(options["candidate_card_instance_ids"]) == {"aq-member", "aq-live", "aq-2", "aq-3"}
    assert options["card_selection_requires_order"] is True
    before = match_state_hash(started.state)
    result = apply_action(started.state, _resolve(started.state, selected))
    player = result.state.players["player_1"]
    assert player.main_deck == original_deck + selected
    assert all(not result.state.cards[key].face_up for key in selected)
    assert not set(selected).intersection(player.resolution_area)
    assert not set(selected).intersection(player.waiting_room)
    assert match_state_hash(started.state) == before


@pytest.mark.parametrize(
    "selected",
    [
        ["aq-member", "aq-live", "aq-2", "aq-3"],
        ["aq-live", "aq-live"],
        ["wrong-work"],
        ["not-yell"],
        ["source-live"],
        ["missing"],
    ],
)
def test_illegal_targets_fail_atomically(selected):
    state = _begin(_state()).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, selected))
    assert match_state_hash(state) == before


def _move(state, destinations):
    payload = {
        "adjustments": [
            {
                "adjustment_type": "move_card",
                "target_player_id": "player_1",
                "target_card_instance_id": "aq-live",
                "to_zone": zone,
            }
            for zone in destinations
        ]
    }
    control = next((i for i in state.pending_effects if i.effect_id == "AUDIT-control"), None)
    if control is not None:
        payload.update(
            source_invocation_id=control.invocation_id,
            source_effect_id=control.effect_id,
            source_card_instance_id=control.source_card_instance_id,
        )
    return ActionRequest(
        action_type="manual_adjustment",
        player_id="player_1",
        expected_revision=state.revision,
        payload=payload,
    )


@pytest.mark.parametrize("timing", ["before_trigger", "while_pending"])
@pytest.mark.parametrize(
    "destinations,eligible",
    [
        (["waiting_room"], False),
        (["waiting_room", "resolution_area"], False),
        (["resolution_area"], True),
    ],
)
def test_yell_object_departure_and_return_does_not_reuse_original_identity(
    timing, destinations, eligible
):
    state = _state()
    if timing == "while_pending":
        control = (
            _state(legacy=True)
            .effect_definitions[EFFECT]
            .model_copy(update={"effect_id": "AUDIT-control"}, deep=True)
        )
        state.effect_definitions[control.effect_id] = control
        state.cards["control"] = state.cards["live-1"].model_copy(
            update={"instance_id": "control"}, deep=True
        )
        state.cards["control"].card.effect_ids = [control.effect_id]
        state.players["player_1"].live_area.append("control")
        state = _begin(state).state
    changed = apply_action(state, _move(state, destinations)).state
    if timing == "before_trigger":
        changed = _begin(changed).state
    options = next(
        a for a in generate_legal_actions(changed) if a.action_type == "resolve_effect"
    ).options
    assert ("aq-live" in options["invocations"][0]["candidate_card_instance_ids"]) == eligible


@pytest.mark.parametrize("legacy", [False, True])
def test_sql_replay_and_historical_snapshot_shape(tmp_path, legacy):
    state = _state(legacy=legacy)
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    started = repository.apply(
        state.match_id, ActionRequest(action_type="advance_phase", expected_revision=state.revision)
    )
    final = (
        started
        if legacy
        else repository.apply(state.match_id, _resolve(started.state, ["aq-live", "aq-member"]))
    )
    replay = repository.replay(state.match_id)
    assert replay["final_state"] == final.state.model_dump(mode="json")
    assert replay["metadata"]["deterministic_replay_verified"] is True
    result = MatchState.model_validate(replay["initial_state"])
    dumped = result.players["player_1"].live_result.model_dump()
    assert ("remaining_yell_instance_ids" in dumped) is not legacy


@pytest.mark.parametrize(
    "policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"]
)
def test_ai_and_order_privacy(policy):
    state = _begin(_state()).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    decision = controller.choose_action(
        state, generate_legal_actions(state), controlled_player_ids={"player_1"}
    )
    assert isinstance(decision, SimpleAIDecision)
    result = apply_action(state, decision.action)
    assert not result.state.pending_effects
    # Exercise a non-empty private ordering independently of the policy's conservative choice.
    result = apply_action(state, _resolve(state, ["aq-live", "aq-member"]))
    opponent = _match_state_payload(
        result.state, events=result.events, legal_actions=result.legal_actions, player_id="player_2"
    )
    assert "aq-live" not in str(opponent) and "aq-member" not in str(opponent)


def test_missing_yell_object_snapshot_does_not_silently_execute():
    state = _state()
    state.players["player_1"].live_result.remaining_yell_instance_ids = None
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError, match="snapshot is missing"):
        _begin(state)
    assert match_state_hash(state) == before


@pytest.mark.parametrize("legacy", [False, True])
def test_native_yell_initializes_only_new_snapshot_tracking(legacy):
    state = _state(legacy=legacy)
    player = state.players["player_1"]
    player.resolution_area.clear()
    player.live_result = LivePerformanceResult()
    state.phase, state.active_player_id = "performance_first", "player_1"
    state.cards["source-live"].card.blade = 3
    revealed = _begin(state)
    yelled = _begin(revealed.state)
    result = yelled.state.players["player_1"].live_result
    assert len(result.revealed_instance_ids) == 3
    assert result.remaining_yell_instance_ids == (None if legacy else result.revealed_instance_ids)


@pytest.mark.parametrize("deck_size", [0, 1])
def test_short_deck_and_cleanup_preserve_cached_live_result(deck_size):
    state = _state()
    player = state.players["player_1"]
    player.main_deck = player.main_deck[:deck_size]
    started = _begin(state).state
    old_result = started.players["player_1"].live_result.model_dump()
    resolved = apply_action(started, _resolve(started, ["aq-live", "aq-member"]))
    player = resolved.state.players["player_1"]
    assert player.main_deck[-2:] == ["aq-live", "aq-member"]
    assert player.live_result.total_score == old_result["total_score"]
    assert player.live_result.revealed_instance_ids == old_result["revealed_instance_ids"]
    assert not player.resolution_area
    assert "aq-live" not in player.waiting_room and "aq-member" not in player.waiting_room


@pytest.mark.parametrize(
    "policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"]
)
def test_hidden_opponent_identity_does_not_change_choice(policy):
    state = _begin(_state()).state
    state.cards["opponent-hand"] = state.cards["aq-member"].model_copy(
        update={"instance_id": "opponent-hand", "owner_id": "player_2", "face_up": False}, deep=True
    )
    state.players["player_2"].hand = ["opponent-hand"]
    changed = state.model_copy(deep=True)
    for key in changed.players["player_2"].hand:
        changed.cards[key].card = changed.cards["aq-live"].card.model_copy(deep=True)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))

    def choose(current):
        return controller.choose_action(
            current, generate_legal_actions(current), controlled_player_ids={"player_1"}
        ).action

    assert choose(state).model_dump() == choose(changed).model_dump()


@pytest.mark.parametrize(
    "choice_update",
    [
        {"maximum": 4},
        {"minimum": 1},
        {"work_key": "nijigasaki"},
        {"card_type": "member"},
        {"requires_order": False},
        {"zone": "waiting_room"},
    ],
)
def test_narrow_policy_rejects_semantic_widening(choice_update):
    raw = deepcopy(_candidate().to_registry_entry())
    raw["choice"].update(choice_update)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize(
    "update",
    [
        {"is_optional": True},
        {"trigger": "live_started"},
        {"duration": "live"},
        {"actions": [{"action_type": "move_selected_to_hand"}]},
    ],
)
def test_narrow_effect_rejects_different_timing_or_operation(update):
    raw = deepcopy(_candidate().to_registry_entry())
    raw.update(update)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)
