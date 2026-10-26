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
    StaleRevisionError,
    _effective_member_blade,
    apply_action,
    generate_legal_actions,
)
from loveca.simulation.models import ActionRequest, MatchState
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!-pb2-039"
EFFECT = CODE + ":1"
RULE_REFERENCE_IDS = ("8.3.8", "8.3.9", "8.3.10", "8.3.11", "8.4.11", "9.6.2.4.2", "9.7.3")


@lru_cache
def _candidate():
    return next(
        c
        for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
        if c.effect_id == EFFECT
    )


def _state(count=2, *, legacy=False, work="love_live", deck_size=20):
    effect = EffectDefinition.model_validate(_candidate().to_registry_entry())
    if legacy:
        raw = effect.model_dump(mode="json")
        raw.update(
            execution_mode="manual_resolution",
            simulation_support="manual_resolution",
            review_status="parsed_draft",
            condition={},
            actions=[{"action_type": "manual_resolution"}],
        )
        effect = EffectDefinition.model_validate(raw)
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        card = _load_definition(connection, CODE, None, {EFFECT: effect}, {})
    state = _minimal_effect_state(effect)
    state.pending_effects = []
    state.phase = "performance_first"
    state.effect_order_policy = "ap_nap_player_choice"
    # Scope this fixture to segment 1, not the still-manual Live-success segment.
    card.effect_ids = [EFFECT]
    state.cards["source-live"].card = card
    state.cards["source-live"].face_up = False
    player = state.players["player_1"]
    player.live_area = ["source-live"]
    template = state.cards["deck-member-1"].model_copy(deep=True)
    template.card.effect_ids = []
    template.card.work_keys = ["love_live"]
    template.face_up = True
    state.cards["stage"] = template.model_copy(update={"instance_id": "stage"}, deep=True)
    player.member_area["center"] = "stage"
    player.main_deck = []
    for i in range(deck_size):
        key = f"deck-{i}"
        state.cards[key] = template.model_copy(
            update={"instance_id": key, "face_up": False}, deep=True
        )
        player.main_deck.append(key)
    for i in range(count):
        key = f"success-{i}"
        state.cards[key] = state.cards["source-live"].model_copy(
            update={"instance_id": key, "face_up": True}, deep=True
        )
        state.cards[key].card.effect_ids = []
        state.cards[key].card.work_keys = [work]
        player.success_live_area.append(key)
    state.cards["opponent-secret"] = template.model_copy(
        update={"instance_id": "opponent-secret", "owner_id": "player_2", "face_up": False},
        deep=True,
    )
    state.players["player_2"].hand = ["opponent-secret"]
    return state


def _advance(state):
    return ActionRequest(
        action_type="advance_phase",
        player_id=state.active_player_id,
        expected_revision=state.revision,
    )


def _begin(state):
    return apply_action(state, _advance(state))


def test_exact_candidate_checks_body_condition_at_resolution_not_trigger():
    c = _candidate()
    assert c.pattern_id == "live_start_success_muse_two_yell_ten"
    assert c.text_revision_id == 1018
    assert c.raw_text_hash == "c64c225ab648e5389537066b41874ad2905e24eb668f1a651fde9bd7b45780f9"
    assert c.condition == {} and not c.cost and c.choice is None and not c.is_optional
    assert c.execution_mode == "auto_resolve" and c.frequency_limit == "once_per_live"
    assert c.duration == "live" and c.trigger == "live_started" and c.effect_index == 1
    assert c.actions == [
        {
            "action_type": "modify_yell_count",
            "amount": 10,
            "value": {
                "condition": {
                    "success_live_work_count_at_least": {"work_key": "love_live", "count": 2}
                }
            },
        }
    ]


@pytest.mark.parametrize(
    "count,work,bonus",
    [(0, "love_live", 0), (1, "love_live", 0), (2, "love_live", 10), (2, "nijigasaki", 0)],
)
def test_native_live_start_and_yell_reveal_count(count, work, bonus):
    state = _state(count, work=work)
    before = match_state_hash(state)
    started = _begin(state)
    assert started.state.phase == "yell_first" and not started.state.pending_effects
    assert _effective_member_blade(started.state, "player_1", "stage") == 1
    assert not any(
        m.modifier_type == "blade" for m in started.state.players["player_1"].manual_modifiers
    )
    result = apply_action(started.state, _advance(started.state))
    event = next(e for e in result.events if e.event_type == "yell_completed")
    assert event.data["raw_blade_count"] == 1 and event.data["yell_count_modifier"] == bonus
    assert len(result.state.players["player_1"].resolution_area) == 1 + bonus
    assert match_state_hash(state) == before


def test_legacy_manual_snapshot_reproduces_false_condition_blocker():
    result = _begin(_state(0, legacy=True))
    assert result.state.pending_effects[0].effect_id == EFFECT
    invocation = next(a for a in result.legal_actions if a.action_type == "resolve_effect")
    assert invocation.options["invocations"][0]["simulation_support"] == "manual_resolution"


@pytest.mark.parametrize("zone", ["hand", "waiting_room", "live_area", "opponent_success"])
def test_only_own_success_live_zone_counts(zone):
    state = _state(2)
    own = state.players["player_1"]
    ids = list(own.success_live_area)
    own.success_live_area.clear()
    if zone == "opponent_success":
        state.players["player_2"].success_live_area = ids
        for key in ids:
            state.cards[key].owner_id = "player_2"
    else:
        getattr(own, zone).extend(ids)
    result = _begin(state)
    assert not result.state.pending_effects
    assert not result.state.players["player_1"].manual_modifiers


@pytest.mark.parametrize("count", [0, 2])
def test_sql_replay_preserves_new_and_legacy_snapshots(tmp_path, count):
    for legacy in (False, True):
        state = _state(count, legacy=legacy)
        repo = MatchRepository(tmp_path / f"runtime-{legacy}.sqlite3")
        repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
        result = repo.apply(state.match_id, _advance(state))
        replay = repo.replay(state.match_id)
        assert replay["metadata"]["deterministic_replay_verified"] is True
        assert replay["final_state"] == result.state.model_dump(mode="json")
        assert bool(result.state.pending_effects) == legacy
        restored = MatchState.model_validate_json(state.model_dump_json())
        assert match_state_hash(restored) == match_state_hash(state)


def test_short_deck_refresh_reveals_all_requested_cards_without_reusing_yell():
    state = _state(2, deck_size=3)
    for i in range(12):
        key = f"waiting-{i}"
        state.cards[key] = state.cards["deck-0"].model_copy(update={"instance_id": key}, deep=True)
        state.players["player_1"].waiting_room.append(key)
    started = _begin(state).state
    result = apply_action(started, _advance(started))
    revealed = result.state.players["player_1"].live_result.revealed_instance_ids
    assert len(revealed) == len(set(revealed)) == 11
    assert any("refresh" in e.event_type for e in result.events)


def test_live_duration_expires_and_does_not_change_stage_blade():
    state = _begin(_state()).state
    assert state.players["player_1"].manual_modifiers[0].amount == 10
    state.phase, state.active_player_id = "live_judgment", None
    result = apply_action(state, _advance(state))
    assert not result.state.players["player_1"].manual_modifiers
    assert _effective_member_blade(result.state, "player_1", "stage") == 1


def test_wait_member_does_not_contribute_blade_but_bonus_still_reveals_ten():
    state = _state()
    state.cards["stage"].orientation = "wait"
    started = _begin(state).state
    result = apply_action(started, _advance(started))
    event = next(e for e in result.events if e.event_type == "yell_completed")
    assert event.data["raw_blade_count"] == 0 and event.data["yell_count_modifier"] == 10
    assert len(result.state.players["player_1"].resolution_area) == 10


def test_other_player_performance_does_not_use_own_live_area_ability():
    state = _state()
    state.phase, state.active_player_id = "performance_second", "player_2"
    result = _begin(state)
    assert not result.state.pending_effects
    assert not any(e.data.get("effect_id") == EFFECT for e in result.events)


def test_second_player_can_use_its_own_success_cards():
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
    result = _begin(state)
    assert result.state.players["player_2"].manual_modifiers[0].amount == 10
    assert not result.state.players["player_1"].manual_modifiers


@pytest.mark.parametrize("starts_satisfied", [False, True])
def test_body_condition_uses_current_success_zone_after_another_ordered_effect(starts_satisfied):
    state = _state(2)
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(
        effect_id="AUDIT-control:1",
        card_code="AUDIT-control",
        execution_mode="manual_resolution",
        simulation_support="manual_resolution",
        review_status="parsed_draft",
        actions=[{"action_type": "manual_resolution"}],
    )
    control = EffectDefinition.model_validate(raw)
    state.effect_definitions[control.effect_id] = control
    state.cards["live-1"].card.effect_ids = [control.effect_id]
    state.players["player_1"].live_area.append("live-1")
    if not starts_satisfied:
        state.players["player_1"].success_live_area = []
        state.players["player_1"].waiting_room = ["success-0", "success-1"]
    started = _begin(state).state
    assert {i.effect_id for i in started.pending_effects} == {EFFECT, control.effect_id}
    invocation = next(i for i in started.pending_effects if i.effect_id == control.effect_id)
    action = ActionRequest(
        action_type="manual_adjustment",
        player_id="player_1",
        expected_revision=started.revision,
        payload={
            "source_invocation_id": invocation.invocation_id,
            "source_effect_id": control.effect_id,
            "source_card_instance_id": "live-1",
            "adjustments": [
                {
                    "adjustment_type": "move_card",
                    "target_player_id": "player_1",
                    "target_card_instance_id": f"success-{i}",
                    "to_zone": "waiting_room" if starts_satisfied else "success_live_area",
                }
                for i in range(2)
            ],
        },
    )
    changed = apply_action(started, action).state
    # The remaining automatic ability may finish immediately after the control effect.
    if changed.pending_effects:
        own = next(i for i in changed.pending_effects if i.effect_id == EFFECT)
        changed = apply_action(
            changed,
            ActionRequest(
                action_type="resolve_effect",
                player_id="player_1",
                expected_revision=changed.revision,
                payload={"invocation_id": own.invocation_id},
            ),
        ).state
    modifiers = changed.players["player_1"].manual_modifiers
    assert sum(m.amount or 0 for m in modifiers) == (0 if starts_satisfied else 10)


@pytest.mark.parametrize(
    "policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"]
)
@pytest.mark.parametrize("count", [0, 2])
def test_four_ai_policies_advance_without_manual_block_or_hidden_hand_dependency(policy, count):
    state = _state(count)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    decision = controller.choose_action(
        state, generate_legal_actions(state), controlled_player_ids={"player_1"}
    )
    assert isinstance(decision, SimpleAIDecision)
    changed = state.model_copy(deep=True)
    changed.cards["opponent-secret"].card.card_code = "HIDDEN-CHANGED"
    assert (
        controller.choose_action(
            changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}
        ).action
        == decision.action
    )
    result = apply_action(state, decision.action)
    assert result.state.phase == "yell_first" and not result.state.pending_effects
    for viewer in ("player_1", "player_2"):
        payload = _match_state_payload(
            result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer
        )
        if viewer == "player_1":
            assert "opponent-secret" not in payload["state"]["cards"]
        assert not any(a["action_type"] == "resolve_effect" for a in payload["legal_actions"])


def test_replayed_action_is_rejected_atomically_and_segment_two_stays_manual():
    state = _state()
    action = _advance(state)
    result = apply_action(state, action)
    before = match_state_hash(result.state)
    with pytest.raises(StaleRevisionError):
        apply_action(result.state, action)
    assert match_state_hash(result.state) == before
    effects = {e.effect_id: e for e in load_effect_registry().effects}
    assert effects[EFFECT] == EffectDefinition.model_validate(_candidate().to_registry_entry())
    assert effects[CODE + ":2"].simulation_support == "manual_resolution"
