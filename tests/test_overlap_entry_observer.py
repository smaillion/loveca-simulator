import json
from contextlib import closing
from functools import lru_cache
from pathlib import Path

import pytest
from test_member_entry_area_history import _play
from test_member_entry_area_history import _state as normal_state
from test_occupied_effect_deployment import ROOT, _request
from test_occupied_effect_deployment import _state as effect_state

from loveca.db.bootstrap import connect_database
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, MatchState
from loveca.simulation.online import match_state_hash

POLICY_FIELD = "member_overlap_policy"
POLICY = "capture_fixed_draw_entry_observers"
ACTUAL = "PL!N-pb1-005:1"
RULE_REFERENCE_IDS = ("9.5.3", "9.7.2", "9.7.7", "10.1.2", "10.4.1", "9.6.2.3.2")


@lru_cache
def _actual():
    effect = next(e for e in load_effect_registry().effects if e.effect_id == ACTUAL)
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        card = _load_definition(connection, effect.card_code, None, {ACTUAL: effect}, {})
    return effect, card


def _state(*, modern=True, cost=10, effect=False):
    state = effect_state() if effect else normal_state()
    definition, card = _actual()
    state.effect_definitions[ACTUAL] = definition.model_copy(deep=True)
    state.cards["old"].card = card.model_copy(deep=True)
    if effect:
        state.cards["target"].card.cost = cost
        state.effect_definitions[ROOT].choice.maximum_cost = cost
    else:
        state.cards["entrant"].card.cost = cost
        player = state.players["player_1"]
        for i in range(6, max(10, cost)):
            key = f"energy-{i}"
            state.cards[key] = state.cards["energy-0"].model_copy(
                update={"instance_id": key}, deep=True
            )
            player.energy_area.append(key)
    raw = state.model_dump(mode="json")
    if modern:
        raw[POLICY_FIELD] = POLICY
    else:
        raw.pop(POLICY_FIELD, None)
    return MatchState.model_validate(raw)


@pytest.mark.parametrize(
    "modern,baton,expected", [(True, False, 1), (True, True, 0), (False, False, 0)]
)
def test_real_ai_draw_observer_survives_normal_overlap_but_not_baton(modern, baton, expected):
    state = _state(modern=modern)
    before = len(state.players["player_1"].hand)
    result = _play(state, slot="center", baton=baton)
    assert len(result.state.players["player_1"].hand) == before - 1 + expected
    assert "old" in result.state.players["player_1"].waiting_room
    actual = [
        e
        for e in result.events
        if e.event_type == "effect_triggered" and e.data["effect_id"] == ACTUAL
    ]
    assert len(actual) == expected
    if expected:
        cleanup = next(
            i for i, e in enumerate(result.events) if e.event_type == "duplicate_member_resolved"
        )
        capture = next(i for i, e in enumerate(result.events) if e in actual)
        drawn = next(i for i, e in enumerate(result.events) if e.event_type == "cards_drawn")
        assert capture < cleanup < drawn


def test_bounded_effect_deployment_captures_actual_cost10_observer_before_cleanup():
    state = _state(effect=True)
    options = next(
        a for a in generate_legal_actions(state) if a.action_type == "resolve_effect"
    ).options["invocations"][0]
    assert options["position_change_slots_by_candidate"]["target"] == ["right"]
    before = len(state.players["player_1"].hand)
    result = apply_action(state, _request(state))
    assert len(result.state.players["player_1"].hand) == before + 3
    assert any(
        e.event_type == "effect_triggered" and e.data["effect_id"] == ACTUAL for e in result.events
    )
    parent = next(
        i
        for i, e in enumerate(result.events)
        if e.event_type == "effect_resolved" and e.data["effect_id"] == ROOT
    )
    assert parent < next(i for i, e in enumerate(result.events) if e.event_type == "cards_drawn")


@pytest.mark.parametrize("cost", [2, 9, 11])
def test_actual_observer_requires_exact_cost10(cost):
    state = _state(cost=cost)
    result = _play(state, slot="center")
    assert not any(
        e.event_type == "effect_triggered" and e.data["effect_id"] == ACTUAL for e in result.events
    )


def test_actual_observer_once_per_turn_limit_is_not_reset_by_leaving():
    from loveca.simulation.models import EffectUsage

    state = _state()
    state.effect_usage.append(
        EffectUsage(effect_id=ACTUAL, source_card_instance_id="old", turn_number=state.turn_number)
    )
    result = _play(state, slot="center")
    assert not any(
        e.event_type == "effect_triggered" and e.data["effect_id"] == ACTUAL for e in result.events
    )


@pytest.mark.parametrize("modern", [False, True])
def test_actual_snapshot_replay_preserves_policy_shape_and_previous_draw_behavior(tmp_path, modern):
    from loveca.simulation.runtime import MatchRepository

    state = _state(modern=modern)
    raw = state.model_dump(mode="json")
    assert (POLICY_FIELD in raw) is modern
    assert MatchState.model_validate_json(state.model_dump_json()) == state
    probe = _play(state, slot="center")
    play = next(e for e in probe.events if e.event_type == "member_played")
    action = ActionRequest(
        action_type="play_member",
        player_id="player_1",
        expected_revision=state.revision,
        payload={
            "card_instance_id": "entrant",
            "slot": "center",
            "use_baton_touch": False,
            "energy_instance_ids": play.data["energy_instance_ids"],
        },
    )
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repository.apply(state.match_id, action)
    replay = repository.replay(state.match_id)
    assert replay["final_state"] == result.state.model_dump(mode="json")
    assert replay["events"] == [e.model_dump(mode="json") for e in result.events]
    assert match_state_hash(MatchState.model_validate(replay["final_state"])) == match_state_hash(
        result.state
    )
    assert len(result.state.players["player_1"].hand) == 2 + int(modern)
    from loveca.webapp import _match_state_payload

    opponent = _match_state_payload(
        result.state,
        events=result.events,
        legal_actions=generate_legal_actions(result.state),
        player_id="player_2",
    )
    assert not set(result.state.players["player_1"].hand) & set(opponent["state"]["cards"])


@pytest.mark.parametrize(
    "payload",
    [
        {"energy_instance_ids": []},
        {"slot": "missing"},
        {"card_instance_id": "old"},
        {"energy_instance_ids": ["energy-0"] * 10},
    ],
)
def test_normal_play_rejects_before_observer_or_payment_mutates_state(payload):
    state = _state()
    before = state.model_dump(mode="json")
    action = ActionRequest(
        action_type="play_member",
        player_id="player_1",
        expected_revision=state.revision,
        payload={
            "card_instance_id": "entrant",
            "slot": "center",
            "use_baton_touch": False,
            "energy_instance_ids": [f"energy-{i}" for i in range(10)],
            **payload,
        },
    )
    with pytest.raises(IllegalActionError):
        apply_action(state, action)
    assert state.model_dump(mode="json") == before


@pytest.mark.parametrize(
    "change",
    [
        {"condition": {"source_slot": "right"}},
        {"condition": {"total_stage_member_count_at_least": 4}},
        {"actions": [{"action_type": "draw_card", "amount_source": "own_stage_member_count"}]},
        {"actions": [{"action_type": "gain_blade", "amount": 1}]},
        {"trigger": "own_member_played|member_moved"},
    ],
)
def test_complex_outgoing_observer_still_blocks_bounded_effect_and_has_normal_diagnostic(change):
    from loveca.simulation.engine import _effect_deployment_slots

    state = _state(effect=True)
    state.effect_definitions[ACTUAL] = EffectDefinition.model_validate(
        {**state.effect_definitions[ACTUAL].model_dump(), **change}
    )
    assert "right" not in _effect_deployment_slots(state, state.pending_effects[0], "target")
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalActionError):
        apply_action(state, _request(state))
    assert state.model_dump(mode="json") == before
    normal = _state()
    normal.effect_definitions[ACTUAL] = state.effect_definitions[ACTUAL]
    result = _play(normal, slot="center")
    assert any(
        e.event_type == "effect_not_activatable"
        and e.data.get("reason") == "overlap_entry_observer_requires_timing_review"
        for e in result.events
    )


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1"])
def test_ai_native_effect_resolution_and_private_hand_independence(policy):
    from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
    from loveca.webapp import _match_state_payload

    state = _state(effect=True)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    decision = controller.choose_action(
        state, generate_legal_actions(state), controlled_player_ids={"player_1"}
    )
    assert (
        isinstance(decision, SimpleAIDecision) and decision.action.action_type == "resolve_effect"
    )
    changed = state.model_copy(deep=True)
    changed.cards["opponent-private"].card.card_code = "PRIVATE-CHANGED"
    assert (
        controller.choose_action(
            changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}
        ).action
        == decision.action
    )
    result = apply_action(state, decision.action)
    assert any(
        e.event_type == "effect_triggered" and e.data["effect_id"] == ACTUAL for e in result.events
    )
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(
            result.state,
            events=result.events,
            legal_actions=generate_legal_actions(result.state),
            player_id=viewer,
        )
        other = "player_2" if viewer == "player_1" else "player_1"
        assert not set(result.state.players[other].hand) & set(payload["state"]["cards"])


def test_new_local_and_room_match_defaults_enable_policy_without_request_changes(tmp_path):
    from test_webapp import SAMPLE_DECK, _client

    client = _client(tmp_path)
    deck = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))
    local = client.post(
        "/api/matches",
        json={
            "player_1": {"name": "A", "deck": deck},
            "player_2": {"name": "B", "deck": deck},
            "seed": 1,
        },
    )
    assert local.status_code == 200 and local.json()["state"][POLICY_FIELD] == POLICY
    room = client.post("/api/rooms", json={"player_name": "Host", "deck": deck, "seed": 2}).json()
    joined = client.post(
        f"/api/rooms/{room['room_code']}/join", json={"player_name": "Guest", "deck": deck}
    )
    assert joined.status_code == 200 and joined.json()["match"]["state"][POLICY_FIELD] == POLICY


def test_actual_registry_identity_is_unchanged_and_no_manual_deployment_is_promoted():
    effect, card = _actual()
    assert effect.text_revision_id == card.text_revision_id == 312
    assert (
        effect.raw_text_hash
        == card.raw_text_hash
        == "a24c05703cd27bdf500e947ef67c575ee7ef3c5fba24dc06ced37d0b2b504a8b"
    )
    assert (
        effect.simulation_support == "test_validated_executable"
        and effect.review_status == "test_validated"
    )
    ids = {
        "PL!-PR-015:1",
        "PL!SP-PR-020:1",
        "PL!N-pb1-013:1",
        "PL!N-pb1-015:1",
        "PL!N-pb1-017:1",
        "PL!N-pb1-023:1",
    }
    assert all(
        e.execution_mode == "manual_resolution"
        for e in load_effect_registry().effects
        if e.effect_id in ids
    )


def test_legacy_effect_deployment_keeps_its_strict_overlap_guard():
    from loveca.simulation.engine import _occupied_deployment_gaps

    state = _state(effect=True, modern=False)
    assert _occupied_deployment_gaps(state, state.pending_effects[0], "target")["right"] == (
        "outgoing_effect_requires_overlap_timing_review"
    )


@pytest.mark.parametrize("value", ["unknown", False])
def test_unknown_match_policy_is_rejected(value):
    raw = _state().model_dump(mode="json")
    raw[POLICY_FIELD] = value
    with pytest.raises(ValueError):
        MatchState.model_validate(raw)


def test_complex_observer_does_not_warn_when_immutable_entry_filter_cannot_match():
    state = _state(cost=9)
    raw = state.effect_definitions[ACTUAL].model_dump()
    raw["condition"]["source_slot"] = "center"
    state.effect_definitions[ACTUAL] = EffectDefinition.model_validate(raw)
    result = _play(state, slot="center")
    assert not any(
        e.data.get("reason") == "overlap_entry_observer_requires_timing_review"
        for e in result.events
    )


def test_second_player_control_uses_the_same_normal_replacement_observer_rules():
    state = _state()
    first, second = state.players["player_1"], state.players["player_2"]
    first.player_id, second.player_id = "player_2", "player_1"
    state.players = {"player_1": second, "player_2": first}
    for card in state.cards.values():
        card.owner_id = "player_2" if card.owner_id == "player_1" else "player_1"
    state.first_player_id, state.second_player_id = "player_2", "player_1"
    state.active_player_id = "player_2"
    result = apply_action(
        state,
        ActionRequest(
            action_type="play_member",
            player_id="player_2",
            expected_revision=state.revision,
            payload={
                "card_instance_id": "entrant",
                "slot": "center",
                "use_baton_touch": False,
                "energy_instance_ids": [f"energy-{i}" for i in range(10)],
            },
        ),
    )
    assert len(result.state.players["player_2"].hand) == 3
    assert any(
        e.event_type == "effect_triggered"
        and e.player_id == "player_2"
        and e.data["effect_id"] == ACTUAL
        for e in result.events
    )
