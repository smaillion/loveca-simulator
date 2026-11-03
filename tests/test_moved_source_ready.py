from contextlib import closing
from functools import lru_cache
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_effect_execution import _minimal_effect_state

from loveca.db.bootstrap import connect_database
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, EffectInvocation, MatchState
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!SP-bp7-008"
EFFECT = CODE + ":2"
CONTROL = "AUDIT-movement-control:1"
RULE_REFERENCE_IDS = ("4.1.4", "9.7.7", "11.10.1", "11.10.2", "11.11.1")


def _attachment_source_fixture(tmp_path, owner, *, stage_policy=True, legacy=False):
    from loveca.simulation.rulesets import current_ruleset_identity
    state = _state(control=True, policy=not legacy)
    profile, fingerprint = current_ruleset_identity()
    state.rule_version = profile.rule_version
    state.ruleset_id = profile.ruleset_id
    state.ruleset_fingerprint = fingerprint
    state.ruling_pack_version = profile.ruling_pack_version
    state.attached_member_departure_policy = "clear_target_modifiers_v1"
    state.stage_departure_policy = "clear_departed_card_modifiers" if stage_policy else None
    for player in state.players.values():
        player.member_card_instance_ids_entered_stage_this_turn = []
    if owner == "player_2":
        swapped = {"player_1": "player_2", "player_2": "player_1"}
        state.players = {swapped[key]: player for key, player in state.players.items()}
        for key, player in state.players.items():
            player.player_id = key
        for card in state.cards.values():
            card.owner_id = swapped[card.owner_id]
        for field in ("first_player_id", "second_player_id", "active_player_id", "next_first_player_id"):
            value = getattr(state, field)
            if value in swapped:
                setattr(state, field, swapped[value])
    state = MatchState.model_validate_json(state.model_dump_json())
    repo = MatchRepository(tmp_path / "attachment-source.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    return repo, state


def _owner_manual(state, adjustments, invocation=None):
    action = _manual(state, adjustments, invocation)
    action.player_id = state.active_player_id
    for adjustment in action.payload["adjustments"]:
        adjustment["target_player_id"] = state.active_player_id
    return action


def _attachment_source_step(repo, state, action):
    from test_normal_phase_boundary import _private
    before = match_state_hash(state)
    result = repo.apply(state.match_id, action)
    assert match_state_hash(state) == before
    assert MatchRepository(repo.path).get_state(state.match_id) == result.state
    replay = MatchRepository(repo.path).replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["metadata"]["ruleset_identity_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")
    _private(result)
    return result


def _attachment_source_pending(repo, state):
    result = _attachment_source_step(repo, state, _owner_manual(state, [
        {"adjustment_type": "position_change", "from_slot": "center", "to_slot": "left"}]))
    source = next(i for i in result.state.pending_effects if i.effect_id == EFFECT)
    assert len(result.state.pending_effects) == 2
    return result.state, source


def _attachment_source_changes(route):
    if route == "within_stage":
        return [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_right"}]
    changes = [
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"},
        {"adjustment_type": "attach_card_under_member", "target_card_instance_id": "source-live", "target_slot": "center"},
    ]
    if route == "promoted":
        changes.append({"adjustment_type": "move_attached_card", "target_card_instance_id": "source-live", "to_zone": "member_right"})
    return changes


def _attachment_source_finish(repo, state, route, *, legacy=False):
    owner = state.active_player_id
    control = next(i for i in state.pending_effects if i.effect_id == CONTROL)
    result = _attachment_source_step(repo, state, _owner_manual(state, _attachment_source_changes(route), control))
    events = list(result.events)
    if route == "within_stage":
        assert len(result.state.pending_effects) == 2
        assert len({i.invocation_id for i in result.state.pending_effects}) == 2
        assert all(i.effect_id == EFFECT for i in result.state.pending_effects)
        pending = result.state.pending_effects[0]
        assert pending.effect_id == EFFECT
        result = _attachment_source_step(repo, result.state, ActionRequest(
            action_type="resolve_effect", player_id=owner, expected_revision=result.state.revision,
            payload={"invocation_id": pending.invocation_id}))
        events.extend(result.events)
    assert not result.state.pending_effects
    assert result.state.players[owner].member_area["center"] == "control"
    assert result.state.players[owner].member_area_attachments["center"] == (["source-live"] if route == "attached" else [])
    assert result.state.players[owner].member_area["right"] == (None if route == "attached" else "source-live")
    history = result.state.players[owner].member_card_instance_ids_entered_stage_this_turn
    assert history == ([] if route == "within_stage" else ["source-live"])
    assert result.state.players[owner].member_entered_count_this_turn == state.players[owner].member_entered_count_this_turn
    departed = route != "within_stage" and not legacy
    assert result.state.cards["source-live"].orientation == ("wait" if departed else "active")
    assert any(e.data.get("reason") == "original_source_stage_member_departed" for e in events) is departed
    assert sum(u.usage_count for u in result.state.effect_usage if u.effect_id == EFFECT) == (2 if route == "within_stage" else 1)
    return result


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("stage_policy", [False, True])
@pytest.mark.parametrize("route", ["attached", "promoted", "within_stage"])
def test_pending_original_source_does_not_rebind_via_hand_and_attachment_sql(tmp_path, owner, stage_policy, route):
    repo, state = _attachment_source_fixture(tmp_path, owner, stage_policy=stage_policy)
    state, source = _attachment_source_pending(repo, state)
    assert source.trigger_data["original_source_stage_object"] is True
    _attachment_source_finish(repo, state, route)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("route", ["attached", "promoted"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_continue_after_original_source_attachment_roundtrip(tmp_path, owner, route, policy):
    from loveca.simulation.ai import SimpleAIController, SimpleAIPolicy
    from test_yell_icons_boundary import _choose
    repo, state = _attachment_source_fixture(tmp_path, owner)
    state, _ = _attachment_source_pending(repo, state)
    result = _attachment_source_finish(repo, state, route)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    _attachment_source_step(repo, result.state, _choose(controller, result.state))


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("fault", ["missing_top", "occupied_promotion"])
def test_failed_attachment_batch_preserves_pending_source_identity_sql(tmp_path, owner, fault):
    repo, state = _attachment_source_fixture(tmp_path, owner)
    state, _ = _attachment_source_pending(repo, state)
    control = next(i for i in state.pending_effects if i.effect_id == CONTROL)
    changes = _attachment_source_changes("promoted")
    if fault == "missing_top":
        changes[1]["target_slot"] = "right"
    else:
        changes[2]["to_zone"] = "member_center"
    before = repo.replay(state.match_id)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _owner_manual(state, changes, control))
    assert MatchRepository(repo.path).replay(state.match_id) == before
    source = next(i for i in repo.get_state(state.match_id).pending_effects if i.effect_id == EFFECT)
    assert source.trigger_data.get("original_source_stage_object_departed", False) is False
    _attachment_source_finish(repo, state, "within_stage")


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_legacy_source_operation_keeps_attachment_return_replay(tmp_path, owner):
    repo, state = _attachment_source_fixture(tmp_path, owner, legacy=True)
    assert "source_object_policy" not in state.effect_definitions[EFFECT].model_dump()["actions"][0]
    state, _ = _attachment_source_pending(repo, state)
    _attachment_source_finish(repo, state, "promoted", legacy=True)


@lru_cache
def _candidate():
    return next(
        c
        for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
        if c.effect_id == EFFECT
    )


def _state(*, control=False, policy=True):
    effect = EffectDefinition.model_validate(_candidate().to_registry_entry())
    if not policy:
        raw = effect.model_dump()
        raw["actions"][0].pop("source_object_policy", None)
        effect = EffectDefinition.model_validate(raw)
    definitions = {e.effect_id: e for e in load_effect_registry().effects if e.card_code == CODE}
    definitions[EFFECT] = effect
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        card = _load_definition(connection, CODE, None, definitions, {})
    state = _minimal_effect_state(effect)
    state.pending_effects = []
    state.phase = "first_main"
    state.effect_order_policy = "ap_nap_player_choice"
    state.effect_definitions = definitions
    player = state.players["player_1"]
    player.live_area = []
    player.member_area["center"] = "source-live"
    state.cards["source-live"].card = card
    state.cards["source-live"].orientation = "wait"
    if control:
        raw = effect.model_dump()
        raw.update(
            effect_id=CONTROL,
            card_code="AUDIT-control",
            condition={},
            simulation_support="manual_resolution",
            execution_mode="manual_resolution",
            review_status="parsed_draft",
            actions=[{"action_type": "manual_resolution"}],
            label_ja="AUDIT: manual movement interference",
        )
        definitions[CONTROL] = EffectDefinition.model_validate(raw)
        state.cards["control"] = state.cards["deck-member-1"].model_copy(
            update={"instance_id": "control"}, deep=True
        )
        state.cards["control"].card.effect_ids = [CONTROL]
        player.member_area["left"] = "control"
    return state


def _manual(state, adjustments, invocation=None):
    payload = {
        "adjustments": [{"target_player_id": "player_1", **item} for item in adjustments],
        "reason": "AUDIT source object",
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


def _move(state):
    return _manual(
        state, [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "left"}]
    )


def _interfere(state, *, returning=True):
    invocation = next(i for i in state.pending_effects if i.effect_id == CONTROL)
    adjustments = [
        {
            "adjustment_type": "move_card",
            "target_card_instance_id": "source-live",
            "to_zone": "waiting_room",
        }
    ]
    if returning:
        adjustments.append(
            {
                "adjustment_type": "move_card",
                "target_card_instance_id": "source-live",
                "to_zone": "member_right",
            }
        )
    return _manual(state, adjustments, invocation)


def _resolve_source(state):
    invocation = next(i for i in state.pending_effects if i.effect_id == EFFECT)
    return ActionRequest(
        action_type="resolve_effect",
        player_id="player_1",
        expected_revision=state.revision,
        payload={"invocation_id": invocation.invocation_id},
    )


def _settle(result):
    if any(i.effect_id == EFFECT for i in result.state.pending_effects):
        resolved = apply_action(result.state, _resolve_source(result.state))
        resolved.events = result.events + resolved.events
        return resolved
    return result


def test_pending_source_departure_does_not_ready_returned_object():
    state = _state(control=True)
    moved = apply_action(state, _move(state)).state
    assert len(moved.pending_effects) == 2
    result = apply_action(moved, _interfere(moved))
    assert result.state.players["player_1"].member_area["right"] == "source-live"
    assert result.state.cards["source-live"].orientation == "wait"
    assert not result.state.pending_effects
    assert any(
        e.data.get("reason") == "original_source_stage_member_departed" for e in result.events
    )


def test_candidate_matches_actual_revision_hash_and_only_the_second_segment():
    state = _state()
    candidate = _candidate()
    card = state.cards["source-live"].card
    assert candidate.pattern_id == "wait_moved_original_source_ready"
    assert candidate.effect_index == 2 and candidate.label_ja in card.raw_effect_text_ja
    assert candidate.text_revision_id == card.text_revision_id == 895
    assert candidate.raw_text_hash == card.raw_text_hash
    assert state.effect_definitions[CODE + ":1"].actions[0].action_type == "draw_card"
    assert not card.effect_registry_errors


@pytest.mark.parametrize("movement", ["position_change", "formation_change", "move_card"])
def test_wait_source_readies_after_an_actual_area_movement(movement):
    state = _state()
    adjustment = {
        "position_change": {"from_slot": "center", "to_slot": "left"},
        "formation_change": {
            "slot_assignments": {"left": "source-live", "center": None, "right": None}
        },
        "move_card": {"target_card_instance_id": "source-live", "to_zone": "member_left"},
    }[movement]
    before = match_state_hash(state)
    result = _settle(
        apply_action(state, _manual(state, [{"adjustment_type": movement, **adjustment}]))
    )
    assert result.state.cards["source-live"].orientation == "active"
    assert not result.state.pending_effects
    assert any(
        e.event_type == "effect_source_member_readied" and e.data["changed"] for e in result.events
    )
    assert len([u for u in result.state.effect_usage if u.effect_id == EFFECT]) == 1
    assert match_state_hash(state) == before


@pytest.mark.parametrize("orientation", ["active", "wait"])
def test_stationary_formation_never_triggers(orientation):
    state = _state()
    state.cards["source-live"].orientation = orientation
    result = apply_action(
        state,
        _manual(
            state,
            [
                {
                    "adjustment_type": "formation_change",
                    "slot_assignments": {"left": None, "center": "source-live", "right": None},
                }
            ],
        ),
    )
    assert result.state.cards["source-live"].orientation == orientation
    assert not any(e.data.get("effect_id") == EFFECT for e in result.events)
    assert not result.state.effect_usage


def test_active_source_does_not_trigger_and_no_turn_limit_is_invented():
    state = _state()
    state.cards["source-live"].orientation = "active"
    result = apply_action(state, _move(state))
    assert not any(
        e.event_type == "effect_triggered" and e.data.get("effect_id") == EFFECT
        for e in result.events
    )
    state = result.state
    state.cards["source-live"].orientation = "wait"  # controlled independent Wait effect
    moved = _settle(
        apply_action(
            state,
            _manual(
                state,
                [{"adjustment_type": "position_change", "from_slot": "left", "to_slot": "right"}],
            ),
        )
    )
    assert moved.state.cards["source-live"].orientation == "active"
    assert moved.state.effect_definitions[EFFECT].frequency_limit == "none"
    moved.state.cards["source-live"].orientation = "wait"
    again = _settle(
        apply_action(
            moved.state,
            _manual(
                moved.state,
                [{"adjustment_type": "position_change", "from_slot": "right", "to_slot": "center"}],
            ),
        )
    )
    assert len([u for u in again.state.effect_usage if u.effect_id == EFFECT]) == 2


@pytest.mark.parametrize("cleanup_policy", [None, "clear_departed_card_modifiers"])
@pytest.mark.parametrize("returning", [False, True])
def test_departure_is_independent_of_modifier_cleanup_and_does_not_cancel_invocation(
    cleanup_policy, returning
):
    state = _state(control=True)
    state.stage_departure_policy = cleanup_policy
    moved = apply_action(state, _move(state)).state
    result = apply_action(moved, _interfere(moved, returning=returning))
    assert result.state.cards["source-live"].orientation == "wait"
    assert not result.state.pending_effects
    assert len([u for u in result.state.effect_usage if u.effect_id == EFFECT]) == 1
    assert any(
        e.event_type == "effect_auto_resolved" and e.data.get("effect_id") == EFFECT
        for e in result.events
    )


def test_further_stage_movement_keeps_the_same_original_object():
    state = apply_action(_state(control=True), _move(_state(control=True))).state
    invocation = next(i for i in state.pending_effects if i.effect_id == CONTROL)
    result = _settle(
        apply_action(
            state,
            _manual(
                state,
                [
                    {
                        "adjustment_type": "move_card",
                        "target_card_instance_id": "source-live",
                        "to_zone": "member_right",
                    }
                ],
                invocation,
            ),
        )
    )
    assert result.state.cards["source-live"].orientation == "active"
    assert not any(
        e.data.get("reason") == "original_source_stage_member_departed" for e in result.events
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"adjustment_type": "position_change", "from_slot": "center", "to_slot": "center"},
        {
            "adjustment_type": "move_card",
            "target_card_instance_id": "opponent-secret",
            "to_zone": "member_left",
        },
    ],
)
def test_invalid_movement_is_atomic(payload):
    state = _state()
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _manual(state, [payload]))
    assert match_state_hash(state) == before


def test_departure_then_return_survives_json_and_real_sqlite_replay(tmp_path):
    state = _state(control=True)
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    moved = repo.apply(state.match_id, _move(state)).state
    persisted = repo.get_state(state.match_id)
    assert persisted == moved
    result = repo.apply(state.match_id, _interfere(persisted))
    assert repo.replay(state.match_id)["final_state"] == result.state.model_dump()
    assert MatchState.model_validate_json(result.state.model_dump_json()) == result.state


def test_old_unflagged_snapshot_retains_its_historical_same_id_behavior(tmp_path):
    state = _state(control=True, policy=False)
    assert "source_object_policy" not in state.effect_definitions[EFFECT].model_dump()["actions"][0]
    repo = MatchRepository(tmp_path / "legacy.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    moved = repo.apply(state.match_id, _move(state)).state
    result = repo.apply(state.match_id, _interfere(moved))
    assert result.state.cards["source-live"].orientation == "active"
    assert repo.replay(state.match_id)["final_state"] == result.state.model_dump()


def test_old_manual_snapshot_remains_manual_without_rebinding_to_new_registry():
    state = _state()
    raw = state.effect_definitions[EFFECT].model_dump()
    raw.update(
        trigger="auto_triggered_event",
        timing="auto_triggered_event",
        condition={},
        execution_mode="manual_resolution",
        simulation_support="manual_resolution",
        review_status="parsed_draft",
        actions=[{"action_type": "manual_resolution"}],
    )
    legacy = EffectDefinition.model_validate(raw)
    assert legacy.simulation_support == "manual_resolution"
    state.effect_definitions[EFFECT] = legacy
    state = MatchState.model_validate_json(state.model_dump_json())
    result = apply_action(state, _move(state))
    assert result.state.cards["source-live"].orientation == "wait"
    assert not any(i.effect_id == EFFECT for i in result.state.pending_effects)
    assert result.state.effect_definitions[EFFECT].simulation_support == "manual_resolution"


@pytest.mark.parametrize(
    "changes",
    [
        {"trigger": "member_played"},
        {"is_optional": True},
        {"frequency_limit": "once_per_turn"},
        {"condition": {}},
        {"duration": "live"},
        {"execution_mode": "prompt_then_resolve"},
        {"cost": [{"action_type": "pay_energy", "amount": 1}]},
        {
            "actions": [
                {
                    "action_type": "ready_member",
                    "target": "selected",
                    "source_object_policy": "original_moved_stage_member",
                }
            ]
        },
    ],
)
def test_source_object_policy_rejects_unmodeled_families(changes):
    raw = _state().effect_definitions[EFFECT].model_dump()
    raw.update(changes)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


def test_new_policy_requires_a_captured_trigger_snapshot():
    state = _state()
    state.pending_effects = [
        EffectInvocation(
            invocation_id="bad",
            effect_id=EFFECT,
            player_id="player_1",
            source_card_instance_id="source-live",
            trigger_event="member_moved",
        )
    ]
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError, match="snapshot is missing"):
        apply_action(
            state,
            ActionRequest(
                action_type="resolve_effect",
                player_id="player_1",
                expected_revision=state.revision,
                payload={"invocation_id": "bad"},
            ),
        )
    assert match_state_hash(state) == before


def test_automatic_source_effect_rejects_arbitrary_selected_targets_atomically():
    state = _state()
    state = apply_action(state, _move(state)).state
    action = _resolve_source(state)
    action.payload["selected_card_instance_ids"] = ["deck-member-1"]
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError, match="does not accept card selections"):
        apply_action(state, action)
    assert match_state_hash(state) == before


def test_structured_effect_leaves_source_but_original_pending_effect_finishes():
    state = _state()
    root = state.effect_definitions[EFFECT].model_dump()
    root.update(
        effect_id="AUDIT-leave:1",
        condition={},
        execution_mode="prompt_then_resolve",
        actions=[{"action_type": "source_to_waiting_room"}],
    )
    state.effect_definitions[root["effect_id"]] = EffectDefinition.model_validate(root)
    state.cards["source-live"].card.effect_ids.append(root["effect_id"])
    state = apply_action(state, _move(state)).state
    leaving = next(i for i in state.pending_effects if i.effect_id == root["effect_id"])
    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            player_id="player_1",
            expected_revision=state.revision,
            payload={"invocation_id": leaving.invocation_id},
        ),
    )
    assert "source-live" in result.state.players["player_1"].waiting_room
    assert not result.state.pending_effects
    assert result.state.cards["source-live"].orientation == "wait"
    assert any(
        e.data.get("reason") == "original_source_stage_member_departed" for e in result.events
    )


@pytest.mark.parametrize("baton", [False, True])
def test_replacement_handlers_invalidate_captured_source_without_bypassing_player_priority(baton):
    from test_member_entry_area_history import _state as replacement_state

    from loveca.simulation.engine import _play_member, _queue_member_moved_effects

    state = replacement_state()
    effect = _state().effect_definitions[EFFECT]
    state.effect_definitions[EFFECT] = effect
    state.cards["old"].card.effect_ids = [EFFECT]
    state.cards["old"].orientation = "wait"
    events = []
    _queue_member_moved_effects(
        state, "player_1", ["old"], events, from_slot="right", to_slot="center"
    )
    captured = next(i for i in state.pending_effects if i.effect_id == EFFECT)
    legal_request = ActionRequest(
        action_type="play_member",
        player_id="player_1",
        expected_revision=state.revision,
        payload={
            "card_instance_id": "entrant",
            "slot": "center",
            "use_baton_touch": baton,
            "energy_instance_ids": [f"energy-{i}" for i in range(1 if baton else 2)],
        },
    )
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError, match="pending card effect"):
        apply_action(state, legal_request)
    assert match_state_hash(state) == before
    # Handler-only boundary test: real player actions above must not bypass pending priority.
    _play_member(state, legal_request, events)
    assert captured.trigger_data["original_source_stage_object_departed"] is True
    assert "old" in state.players["player_1"].waiting_room


def test_trigger_condition_is_not_rechecked_after_another_effect_readies_source():
    state = _state(control=True)
    state = apply_action(state, _move(state)).state
    state.cards["source-live"].orientation = "active"  # independent earlier ready effect
    result = apply_action(state, _resolve_source(state))
    assert result.state.cards["source-live"].orientation == "active"
    assert any(
        e.event_type == "effect_source_member_readied" and not e.data["changed"]
        for e in result.events
    )


@pytest.mark.parametrize("movement", ["position_change", "formation_change", "move_card"])
def test_native_movement_and_ready_replay_from_sqlite(movement, tmp_path):
    state = _state()
    adjustment = {
        "position_change": {"from_slot": "center", "to_slot": "left"},
        "formation_change": {
            "slot_assignments": {"left": "source-live", "center": None, "right": None}
        },
        "move_card": {"target_card_instance_id": "source-live", "to_zone": "member_left"},
    }[movement]
    repo = MatchRepository(tmp_path / "positive.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    moved = repo.apply(
        state.match_id, _manual(state, [{"adjustment_type": movement, **adjustment}])
    ).state
    final = repo.apply(state.match_id, _resolve_source(moved)).state
    assert final.cards["source-live"].orientation == "active"
    assert repo.replay(state.match_id)["final_state"] == final.model_dump()


@pytest.mark.parametrize(
    "policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"]
)
def test_ai_can_resolve_the_queued_source_effect_without_hidden_information(policy):
    from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy

    state = apply_action(_state(control=True), _move(_state(control=True))).state
    state.cards["opponent-secret"] = state.cards["deck-member-1"].model_copy(
        update={"instance_id": "opponent-secret", "owner_id": "player_2"}, deep=True
    )
    state.players["player_2"].hand = ["opponent-secret"]
    controller = SimpleAIController(
        SimpleAIPolicy(policy_version=policy, manual_effect_policy="block")
    )
    legal = generate_legal_actions(state)
    decision = controller.choose_action(state, legal, controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision)
    changed = state.model_copy(deep=True)
    changed.cards["opponent-secret"].card.name_ja = "PRIVATE-UNKNOWN"
    changed.cards["opponent-secret"].card.card_code = "PRIVATE-UNKNOWN"
    changed.players["player_1"].main_deck.reverse()
    repeated = controller.choose_action(
        changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}
    )
    assert isinstance(repeated, SimpleAIDecision) and decision.action == repeated.action
    applied = apply_action(state, decision.action)
    assert applied.state.cards["source-live"].orientation == "active"
    hidden = _match_state_payload(
        state, events=[], legal_actions=generate_legal_actions(state), player_id="player_2"
    )
    assert "deck-member-1" not in hidden["state"]["cards"]
    assert (
        "opponent-secret"
        not in _match_state_payload(state, events=[], legal_actions=legal, player_id="player_1")[
            "state"
        ]["cards"]
    )
