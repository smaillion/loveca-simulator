from pathlib import Path

import pytest
from test_member_entry_area_history import _manual, _play
from test_member_entry_area_history import _state as base_state

from loveca.simulation.engine import IllegalActionError, StaleRevisionError, apply_action
from loveca.simulation.models import ActionRequest, ManualModifier, MatchState
from loveca.simulation.online import match_state_hash

FIELD = "stage_departure_policy"
POLICY = "clear_departed_card_modifiers"
RULE_REFERENCE_IDS = ("4.1.4", "9.9.2", "4.5.5.4", "10.5.5")


def _modifier(key, target, kind="blade"):
    return ManualModifier(
        modifier_id=key,
        modifier_type=kind,
        duration="live",
        created_turn=1,
        amount=2,
        color_slot="heart01" if kind == "heart" else None,
        flag="skip_next_active_phase_ready" if kind == "flag" else None,
        value=True if kind == "flag" else None,
        target_card_instance_id=target,
    )


def _state(*, modern=True):
    state = base_state()
    state.stage_departure_policy = POLICY if modern else None
    return state


def test_normal_replacement_discards_existing_card_targeted_modifiers():
    state = _state()
    state.players["player_1"].manual_modifiers = [_modifier("old-blade", "old")]
    result = _play(state, slot="center")
    assert not result.state.players["player_1"].manual_modifiers


@pytest.mark.parametrize("baton", [False, True])
@pytest.mark.parametrize("kind", ["blade", "heart", "flag"])
def test_leave_cleans_targets_across_owners_but_keeps_global_and_other_cards(baton, kind):
    state = _state()
    player = state.players["player_1"]
    player.hand.remove("attachment")
    player.member_area_attachments["center"] = ["attachment", "energy-5"]
    player.energy_area.remove("energy-5")
    player.manual_modifiers = [
        _modifier("top", "old", kind),
        _modifier("under", "attachment", kind),
        _modifier("energy", "energy-5", kind),
        _modifier("global", None, kind),
        _modifier("entrant", "entrant", kind),
    ]
    state.players["player_2"].manual_modifiers = [
        _modifier("opponent-effect", "old", kind),
        _modifier("opponent-global", None, kind),
    ]
    result = _play(state, slot="center", baton=baton)
    assert [m.modifier_id for m in result.state.players["player_1"].manual_modifiers] == [
        "global",
        "entrant",
    ]
    assert [m.modifier_id for m in result.state.players["player_2"].manual_modifiers] == [
        "opponent-global",
    ]
    assert {"old", "attachment"} <= set(result.state.players["player_1"].waiting_room)
    assert "energy-5" in result.state.players["player_1"].energy_deck
    cleared = [e for e in result.events if e.event_type == "stage_card_modifiers_cleared"]
    assert sum(e.data["removed_count"] for e in cleared) == 4
    assert all(set(e.data) == {"reason", "removed_count"} for e in cleared)


@pytest.mark.parametrize("destination", ["waiting_room", "hand", "main_deck"])
def test_manual_departure_clears_and_return_does_not_restore(destination):
    state = _state()
    state.players["player_1"].manual_modifiers = [_modifier("old", "old")]
    state = _manual(
        state, adjustment_type="move_card", target_card_instance_id="old", to_zone=destination
    )
    assert not state.players["player_1"].manual_modifiers
    returned = _manual(
        state, adjustment_type="move_card", target_card_instance_id="old", to_zone="member_right"
    )
    assert returned.players["player_1"].member_area["right"] == "old"
    assert not returned.players["player_1"].manual_modifiers


@pytest.mark.parametrize("movement", ["position_change", "formation_change", "move_card"])
def test_stage_internal_movement_retains_existing_modifiers(movement):
    state = _state()
    state.players["player_1"].manual_modifiers = [_modifier("old", "old")]
    payload = {
        "position_change": {"from_slot": "center", "to_slot": "left"},
        "formation_change": {"slot_assignments": {"left": "old", "center": None, "right": None}},
        "move_card": {"target_card_instance_id": "old", "to_zone": "member_left"},
    }[movement]
    moved = _manual(state, adjustment_type=movement, **payload)
    assert moved.players["player_1"].member_area["left"] == "old"
    assert moved.players["player_1"].manual_modifiers == state.players["player_1"].manual_modifiers


@pytest.mark.parametrize("modern", [False, True])
def test_bounded_deployment_keeps_legacy_cleanup_and_new_cross_owner_cleanup(modern):
    from test_occupied_effect_deployment import _request
    from test_occupied_effect_deployment import _state as deployment_state

    state = deployment_state()
    state.stage_departure_policy = POLICY if modern else None
    state.players["player_2"].manual_modifiers = [_modifier("cross-player", "old")]
    result = apply_action(state, _request(state))
    assert not result.state.players["player_1"].manual_modifiers
    assert bool(result.state.players["player_2"].manual_modifiers) is not modern
    assert any(e.event_type == "stage_card_modifiers_cleared" for e in result.events) is modern


@pytest.mark.parametrize("modern", [False, True])
def test_existing_actual_kaho_bonus_does_not_follow_later_departure(modern):
    from test_overlap_source_modifier import _state as kaho_state

    state = kaho_state()
    state.stage_departure_policy = POLICY if modern else None
    player = state.players["player_1"]
    for i in range(10, 12):
        key = f"energy-{i}"
        state.cards[key] = state.cards["energy-0"].model_copy(
            update={"instance_id": key}, deep=True
        )
        player.energy_area.append(key)
    state = _play(state, slot="left").state
    assert (
        sum(
            m.amount or 0
            for m in state.players["player_1"].manual_modifiers
            if m.target_card_instance_id == "old"
        )
        == 2
    )
    state = _play(state, card_id="next", slot="center").state
    assert "old" in state.players["player_1"].waiting_room
    state = _manual(
        state, adjustment_type="move_card", target_card_instance_id="old", to_zone="member_right"
    )
    assert sum(
        m.amount or 0
        for m in state.players["player_1"].manual_modifiers
        if m.target_card_instance_id == "old"
    ) == (0 if modern else 2)


@pytest.mark.parametrize("modern", [False, True])
@pytest.mark.parametrize("baton", [False, True])
def test_sql_replay_preserves_policy_and_exact_events(tmp_path, modern, baton):
    from loveca.simulation.runtime import MatchRepository

    state = _state(modern=modern)
    state.players["player_1"].manual_modifiers = [_modifier("old", "old")]
    assert (FIELD in state.model_dump()) is modern
    assert MatchState.model_validate_json(state.model_dump_json()) == state
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    action = _play(state, slot="center", baton=baton)
    play = next(e for e in action.events if e.event_type == "member_played")
    result = repository.apply(
        state.match_id,
        ActionRequest(
            action_type="play_member",
            player_id="player_1",
            expected_revision=state.revision,
            payload={
                "card_instance_id": "entrant",
                "slot": "center",
                "use_baton_touch": baton,
                "energy_instance_ids": play.data["energy_instance_ids"],
            },
        ),
    )
    replay = repository.replay(state.match_id)
    assert replay["events"] == [e.model_dump(mode="json") for e in result.events]
    assert replay["final_state"] == result.state.model_dump(mode="json")
    assert match_state_hash(MatchState.model_validate(replay["final_state"])) == match_state_hash(
        result.state
    )
    assert bool(result.state.players["player_1"].manual_modifiers) is not modern


@pytest.mark.parametrize("bad", ["energy", "slot", "stale"])
def test_rejected_action_is_atomic_before_cleanup(bad):
    state = _state()
    state.players["player_1"].manual_modifiers = [_modifier("old", "old")]
    before = state.model_dump(mode="json")
    with pytest.raises(StaleRevisionError if bad == "stale" else IllegalActionError):
        apply_action(
            state,
            ActionRequest(
                action_type="play_member",
                player_id="player_1",
                expected_revision=state.revision - int(bad == "stale"),
                payload={
                    "card_instance_id": "entrant",
                    "slot": "bad" if bad == "slot" else "center",
                    "use_baton_touch": False,
                    "energy_instance_ids": ["energy-0"] * 2
                    if bad == "energy"
                    else ["energy-0", "energy-1"],
                },
            ),
        )
    assert state.model_dump(mode="json") == before


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1"])
def test_ai_legal_entry_cleans_without_reading_opponent_hand(policy):
    from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
    from loveca.simulation.engine import generate_legal_actions
    from loveca.webapp import _match_state_payload

    state = _state()
    state.players["player_1"].manual_modifiers = [_modifier("old", "old")]
    state.players["player_1"].member_area["left"] = "replaced"
    state.cards["entrant"].card.blade = 8
    state.cards["next"].card.blade = 8
    state.players["player_1"].member_area["right"] = "attachment"
    state.players["player_1"].hand.remove("attachment")
    state.cards["private"] = state.cards["entrant"].model_copy(
        update={"instance_id": "private", "owner_id": "player_2"}, deep=True
    )
    state.players["player_2"].hand = ["private"]
    legal = [a for a in generate_legal_actions(state) if a.action_type == "play_member"]
    for action in legal:
        action.options["placements"] = [
            p for p in action.options["placements"] if p["slot"] == "center"
        ]
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    decision = controller.choose_action(state, legal, controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision)
    assert decision.action.action_type == "play_member"
    changed = state.model_copy(deep=True)
    changed.cards["private"].card.name_ja = "非公開変更"
    assert (
        controller.choose_action(changed, legal, controlled_player_ids={"player_1"}).action
        == decision.action
    )
    result = apply_action(state, decision.action)
    assert not result.state.players["player_1"].manual_modifiers
    visible = _match_state_payload(
        result.state, events=result.events, legal_actions=result.legal_actions, player_id="player_1"
    )
    assert "private" not in visible["state"]["cards"]


@pytest.mark.parametrize("hosted", [False, True])
def test_new_local_and_room_matches_enable_cleanup_without_new_request_fields(tmp_path, hosted):
    import json

    from test_webapp import SAMPLE_DECK, _client

    client = _client(tmp_path)
    deck = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))
    if hosted:
        created = client.post("/api/rooms", json={"player_name": "A", "deck": deck, "seed": 1})
        assert created.status_code == 200
        response = client.post(
            f"/api/rooms/{created.json()['room_code']}/join",
            json={"player_name": "B", "deck": deck},
        )
        assert response.status_code == 200
        raw = response.json()["match"]["state"]
    else:
        response = client.post(
            "/api/matches",
            json={
                "player_1": {"name": "A", "deck": deck},
                "player_2": {"name": "B", "deck": deck},
                "seed": 1,
            },
        )
        assert response.status_code == 200
        raw = response.json()["state"]
    assert raw[FIELD] == POLICY
    raw[FIELD] = "unknown"
    with pytest.raises(ValueError):
        MatchState.model_validate(raw)


def test_source_to_waiting_room_operation_clears_before_following_draw():
    from test_attachment_promotion import _trigger

    from loveca.simulation.effects import EffectOperation
    from loveca.simulation.models import EffectInvocation

    state = _state()
    effect = _trigger("AUDIT-leave:1", "member_played")
    effect.actions = [
        EffectOperation(action_type="source_to_waiting_room"),
        EffectOperation(action_type="draw_card", amount=1),
    ]
    state.effect_definitions[effect.effect_id] = effect
    state.pending_effects = [
        EffectInvocation(
            invocation_id="leave",
            effect_id=effect.effect_id,
            source_card_instance_id="old",
            player_id="player_1",
            trigger_event="member_played",
        )
    ]
    state.players["player_1"].manual_modifiers = [_modifier("old", "old")]
    before = len(state.players["player_1"].hand)
    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            player_id="player_1",
            expected_revision=state.revision,
            payload={"invocation_id": "leave", "accepted": True},
        ),
    )
    assert "old" in result.state.players["player_1"].waiting_room
    assert not result.state.players["player_1"].manual_modifiers
    assert len(result.state.players["player_1"].hand) == before + 1
    clear = next(
        i for i, e in enumerate(result.events) if e.event_type == "stage_card_modifiers_cleared"
    )
    drawn = next(i for i, e in enumerate(result.events) if e.event_type == "cards_drawn")
    assert clear < drawn


def test_actual_kaho_grant_leave_return_sequence_replays_from_sql(tmp_path):
    from test_overlap_source_modifier import _state as kaho_state

    from loveca.simulation.runtime import MatchRepository

    state = kaho_state()
    state.stage_departure_policy = POLICY
    for i in range(10, 12):
        key = f"energy-{i}"
        state.cards[key] = state.cards["energy-0"].model_copy(
            update={"instance_id": key}, deep=True
        )
        state.players["player_1"].energy_area.append(key)
    repo = MatchRepository(tmp_path / "actual.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    events = []
    for card_id, slot, energies in [
        ("entrant", "left", [f"energy-{i}" for i in range(10)]),
        ("next", "center", ["energy-10", "energy-11"]),
    ]:
        result = repo.apply(
            state.match_id,
            ActionRequest(
                action_type="play_member",
                player_id="player_1",
                expected_revision=state.revision,
                payload={
                    "card_instance_id": card_id,
                    "slot": slot,
                    "use_baton_touch": False,
                    "energy_instance_ids": energies,
                },
            ),
        )
        state = result.state
        events.extend(result.events)
        assert sum(
            m.amount or 0
            for m in state.players["player_1"].manual_modifiers
            if m.target_card_instance_id == "old"
        ) == (2 if slot == "left" else 0)
    result = repo.apply(
        state.match_id,
        ActionRequest(
            action_type="manual_adjustment",
            player_id="player_1",
            expected_revision=state.revision,
            payload={
                "reason": "离场回场审计",
                "adjustments": [
                    {
                        "target_player_id": "player_1",
                        "adjustment_type": "move_card",
                        "target_card_instance_id": "old",
                        "to_zone": "member_right",
                    }
                ],
            },
        ),
    )
    events.extend(result.events)
    assert result.state.players["player_1"].member_area["right"] == "old"
    assert not result.state.players["player_1"].manual_modifiers
    replay = repo.replay(state.match_id)
    assert replay["final_state"] == result.state.model_dump(mode="json")
    assert replay["events"] == [e.model_dump(mode="json") for e in events]
    assert match_state_hash(MatchState.model_validate(replay["final_state"])) == match_state_hash(
        result.state
    )
