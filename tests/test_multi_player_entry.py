import json
from pathlib import Path

import pytest
from test_attachment_promotion import _state as entry_state
from test_member_entry_area_history import ENTRY_FIELD

from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import (
    IllegalActionError,
    StaleRevisionError,
    apply_action,
    generate_legal_actions,
)
from loveca.simulation.models import ActionRequest, EffectInvocation, MatchState
from loveca.simulation.online import match_state_hash, sha256_json

POLICY = "simultaneous_member_area_entry"
EFFECT_ID = "PL!-pb1-018:1"
RULE_REFERENCE_IDS = ("1.3.4.1", "7.2.1", "9.5.3", "9.7.2", "11.4.2")


def _state(*, owner="player_1", active="player_1", legacy=False, both=True):
    state = entry_state(external=True)
    effect = next(e for e in load_effect_registry().effects if e.effect_id == EFFECT_ID)
    raw = effect.model_dump()
    if legacy:
        raw["choice"].pop("deployment_policy", None)
        raw["choice"]["orientation"] = None
    else:
        raw["choice"].update(deployment_policy=POLICY, orientation="wait")
    effect = EffectDefinition.model_validate(raw)
    state.effect_definitions[EFFECT_ID] = effect
    source_id = "source-live" if owner == "player_1" else "opponent-observer"
    state.pending_effects = [
        EffectInvocation(
            invocation_id="multi-parent",
            effect_id=EFFECT_ID,
            source_card_instance_id=source_id,
            player_id=owner,
            trigger_event="member_played",
        )
    ]
    state.active_player_id = active
    state.first_player_id = "player_1"
    state.second_player_id = "player_2"
    state.players["player_2"].main_deck = []
    for i, source in enumerate(["deck-live-1", "deck-member-1", "deck-live-2"]):
        key = f"opponent-deck-{i}"
        state.cards[key] = state.cards[source].model_copy(
            update={"instance_id": key, "owner_id": "player_2"}, deep=True
        )
        state.players["player_2"].main_deck.append(key)
    state.cards["opponent-observer"] = state.cards["source-live"].model_copy(
        update={"instance_id": "opponent-observer", "owner_id": "player_2"}, deep=True
    )
    state.players["player_2"].member_area["center"] = "opponent-observer"
    state.cards["opponent-target"] = state.cards["target"].model_copy(
        update={"instance_id": "opponent-target", "owner_id": "player_2"}, deep=True
    )
    if both:
        state.players["player_2"].waiting_room = ["opponent-target"]
    setattr(state.players["player_2"], ENTRY_FIELD, [])
    return state


def _action(state, action_type, player_id="player_1", **payload):
    return ActionRequest(
        action_type=action_type,
        player_id=player_id,
        expected_revision=state.revision,
        payload=payload,
    )


def _begin(state):
    return apply_action(
        state,
        _action(
            state,
            "resolve_effect",
            state.pending_effects[0].player_id,
            invocation_id="multi-parent",
        ),
    ).state


def _choose(state, player_id="player_1", card="target", slot="right"):
    return apply_action(
        state,
        _action(
            state, "resolve_effect_choice", player_id, selected_card_instance_id=card, slot=slot
        ),
    )


def test_choices_do_not_move_cards_or_resolve_triggers_between_players():
    initial = _state()
    state = _begin(initial)
    first = _choose(state)
    player = first.state.players["player_1"]
    assert player.member_area["right"] is None
    assert "target" in player.waiting_room
    assert player.member_entered_count_this_turn == 0
    assert first.state.pending_choice.player_id == "player_2"
    assert player.hand == initial.players["player_1"].hand
    assert not any(e.event_type in {"cards_drawn", "effect_triggered"} for e in first.events)


def test_both_entries_finish_before_any_onplay_draw_and_observer():
    initial = _state()
    state = _choose(_begin(initial)).state
    result = _choose(state, "player_2", "opponent-target", "left")
    for player_id, card, slot in [
        ("player_1", "target", "right"),
        ("player_2", "opponent-target", "left"),
    ]:
        player = result.state.players[player_id]
        assert player.member_area[slot] == card
        assert player.member_entered_count_this_turn == 1
        assert getattr(player, ENTRY_FIELD) == [card]
        assert result.state.cards[card].orientation == "wait"
        assert len(player.hand) == len(initial.players[player_id].hand) + 2
    assert result.state.pending_choice is None and not result.state.pending_effects
    types = [e.event_type for e in result.events]
    assert types.count("effect_member_deployed_from_waiting_room") == 2
    assert max(
        i for i, kind in enumerate(types) if kind == "effect_member_deployed_from_waiting_room"
    ) < types.index("cards_drawn")
    assert next(
        i
        for i, e in enumerate(result.events)
        if e.event_type == "effect_resolved" and e.data["effect_id"] == EFFECT_ID
    ) < types.index("cards_drawn")


@pytest.mark.parametrize("active", ["player_1", "player_2", None])
def test_active_player_not_effect_owner_chooses_first(active):
    state = _begin(_state(owner="player_2", active=active))
    assert state.pending_choice.player_id == (active or "player_1")


def test_legacy_snapshot_keeps_immediate_move_and_missing_trigger_behavior():
    state = _begin(_state(legacy=True))
    state = _choose(state).state
    assert state.players["player_1"].member_area["right"] == "target"
    before = {p: len(v.hand) for p, v in state.players.items()}
    state = _choose(state, "player_2", "opponent-target", "left").state
    assert {p: len(v.hand) for p, v in state.players.items()} == before


@pytest.mark.parametrize(
    "payload",
    [
        {"selected_card_instance_id": "opponent-target", "slot": "right"},
        {"selected_card_instance_id": "target", "slot": "center"},
        {"selected_card_instance_id": "missing", "slot": "left"},
        {"selected_card_instance_ids": ["target"], "slot": "left"},
    ],
)
def test_invalid_selection_does_not_mutate_state(payload):
    state = _begin(_state())
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalActionError):
        apply_action(state, _action(state, "resolve_effect_choice", **payload))
    assert state.model_dump(mode="json") == before


@pytest.mark.parametrize("failure", ["missing_card", "occupied_area", "changed_cost"])
def test_final_selection_revalidates_both_players_before_movement(failure):
    state = _choose(_begin(_state())).state
    if failure == "missing_card":
        state.players["player_1"].waiting_room.remove("target")
    elif failure == "occupied_area":
        state.players["player_1"].member_area["right"] = "source-live"
    else:
        state.cards["target"].card.cost = 99
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalActionError):
        _choose(state, "player_2", "opponent-target", "left")
    assert state.model_dump(mode="json") == before
    assert "opponent-target" in state.players["player_2"].waiting_room


def test_wrong_actor_and_stale_revision_are_atomic():
    state = _begin(_state())
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalActionError):
        _choose(state, "player_2", "opponent-target", "left")
    stale = _action(
        state, "resolve_effect_choice", selected_card_instance_id="target", slot="right"
    )
    stale.expected_revision -= 1
    with pytest.raises(StaleRevisionError):
        apply_action(state, stale)
    assert state.model_dump(mode="json") == before


def test_no_opponent_target_still_finishes_first_players_entry():
    state = _begin(_state(both=False))
    result = _choose(state)
    assert result.state.pending_choice is None
    assert result.state.players["player_1"].member_area["right"] == "target"
    assert result.state.cards["target"].orientation == "wait"
    assert len([e for e in result.events if e.event_type == "cards_drawn"]) == 2


@pytest.mark.parametrize("legacy", [False, True])
def test_runtime_replay_preserves_partial_choice_and_effect_snapshot(tmp_path, legacy):
    from loveca.simulation.runtime import MatchRepository

    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    initial = _state(legacy=legacy)
    raw = initial.model_dump(mode="json")
    if legacy:
        assert "deployment_policy" not in raw["effect_definitions"][EFFECT_ID]["choice"]
    restored = MatchState.model_validate_json(json.dumps(raw))
    assert match_state_hash(restored) == sha256_json(raw)
    repository.create_match(restored, card_database_path=Path("data/loveca.sqlite3"))
    state = repository.apply(
        initial.match_id, _action(initial, "resolve_effect", invocation_id="multi-parent")
    ).state
    state = repository.apply(
        initial.match_id,
        _action(state, "resolve_effect_choice", selected_card_instance_id="target", slot="right"),
    ).state
    state = MatchState.model_validate_json(state.model_dump_json())
    result = repository.apply(
        initial.match_id,
        _action(
            state,
            "resolve_effect_choice",
            "player_2",
            selected_card_instance_id="opponent-target",
            slot="left",
        ),
    )
    replay = repository.replay(initial.match_id)
    assert replay["final_state"] == result.state.model_dump(mode="json")
    assert len(result.state.players["player_1"].hand) == len(initial.players["player_1"].hand) + (
        0 if legacy else 2
    )


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1"])
def test_ai_finishes_both_native_choices_without_hidden_hand_dependency(policy):
    from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy

    state = _begin(_state())
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    for actor in ["player_1", "player_2"]:
        decision = controller.choose_action(
            state, generate_legal_actions(state), controlled_player_ids={actor}
        )
        assert isinstance(decision, SimpleAIDecision)
        assert decision.action.action_type == "resolve_effect_choice"
        changed = state.model_copy(deep=True)
        hidden_id = "opponent-private" if actor == "player_1" else "live-1"
        changed.cards[hidden_id].card.name_ja = "非公開カード変更"
        changed.cards[hidden_id].card.card_code = "PRIVATE-CHANGED"
        other = controller.choose_action(
            changed, generate_legal_actions(changed), controlled_player_ids={actor}
        )
        assert other.action == decision.action
        state = apply_action(state, decision.action).state
    assert state.pending_choice is None
    assert state.players["player_1"].member_entered_count_this_turn == 1
    assert state.players["player_2"].member_entered_count_this_turn == 1


def test_registry_exact_binding_matches_candidate_and_controls_policy():
    from loveca.simulation.effect_candidates import discover_effect_candidates
    from loveca.simulation.effects import EffectChoice

    effect = next(e for e in load_effect_registry().effects if e.effect_id == EFFECT_ID)
    assert effect.text_revision_id == 433
    assert (
        effect.raw_text_hash == "da401c700c578576b64633e019e182774ba3bfb460610d872de42f1ec418ae3c"
    )
    assert effect.choice.deployment_policy == POLICY
    assert effect.choice.orientation == "wait"
    candidate = next(
        e
        for e in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
        if e.effect_id == EFFECT_ID
    )
    assert EffectChoice.model_validate(candidate.choice) == effect.choice
    raw = effect.choice.model_dump()
    for update in [{"choice_type": "card_from_zone"}, {"orientation": None}, {"maximum": 2}]:
        with pytest.raises(ValueError):
            EffectChoice.model_validate({**raw, **update})


def test_optional_decline_does_not_start_any_player_choice():
    state = _state()
    state.effect_definitions[EFFECT_ID].is_optional = True
    result = apply_action(
        state, _action(state, "resolve_effect", invocation_id="multi-parent", accepted=False)
    )
    assert result.state.players == state.players
    assert result.state.cards == state.cards
    assert not result.state.pending_effects and result.state.pending_choice is None
    assert any(e.event_type == "effect_declined" for e in result.events)


def test_both_online_views_preserve_public_choices_without_private_hands():
    from loveca.webapp import _match_state_payload

    state = _state()
    first = _choose(_begin(state))
    final = _choose(first.state, "player_2", "opponent-target", "left")
    for result in [first, final]:
        for actor, hidden in [("player_1", "opponent-private"), ("player_2", "live-1")]:
            payload = _match_state_payload(
                result.state,
                events=result.events,
                legal_actions=generate_legal_actions(result.state),
                player_id=actor,
            )
            assert hidden not in payload["state"]["cards"]
            assert f'"{hidden}"' not in json.dumps(payload["events"])
            assert "target" in payload["state"]["cards"]
            assert "opponent-target" in payload["state"]["cards"]


def test_both_players_without_targets_can_confirm_without_entering_any_member():
    state = _state(both=False)
    state.players["player_1"].waiting_room = []
    state = _begin(state)
    result = apply_action(state, _action(state, "resolve_effect_choice"))
    assert result.state.pending_choice is None
    assert not result.state.pending_effects
    assert all(p.member_entered_count_this_turn == 0 for p in result.state.players.values())
    assert not any(
        e.event_type == "effect_member_deployed_from_waiting_room" for e in result.events
    )


def test_trigger_resolution_runs_active_player_before_nonactive_owner():
    state = _begin(_state(owner="player_1", active="player_2"))
    state = _choose(state, "player_2", "opponent-target", "left").state
    result = _choose(state)
    draws = [e.player_id for e in result.events if e.event_type == "cards_drawn"]
    assert draws == ["player_2", "player_2", "player_1", "player_1"]


def test_trigger_conditions_observe_both_completed_entries():
    state = _state()
    state.effect_definitions["audit-onplay:1"].condition = {
        "total_stage_member_count_at_least": 4,
    }
    state = _choose(_begin(state)).state
    result = _choose(state, "player_2", "opponent-target", "left")
    assert len([e for e in result.events if e.event_type == "cards_drawn"]) == 4
