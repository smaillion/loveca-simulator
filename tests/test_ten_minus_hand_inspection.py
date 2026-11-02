from copy import deepcopy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_nijigasaki_inspection import _candidate, _play, _resolve, _select
from test_nijigasaki_inspection import _state as _base_state

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effect_candidates import (
    TEN_MINUS_HAND_PRIVATE_TWO_TEXT, _onplay_ten_minus_hand_private_two,
)
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!SP-PR-028"
POLICY = "private_ten_minus_hand_keep_two"
RULE_REFERENCE_IDS = ("1.3.2.2", "5.7.1", "9.6.3.1.1", "10.2.2.2", "10.2.3")


def _state(hand=1, *, legacy=False):
    state = _base_state(CODE, legacy=legacy)
    player = state.players["player_1"]
    player.hand = ["source-live"]
    for prefix, count, zone in (("hand", hand, player.hand), ("peek", 15, [])):
        for i in range(count):
            key = f"{prefix}-{i}"
            card = state.cards["good-live" if i % 2 else "good-member"].model_copy(deep=True)
            card.instance_id = key
            card.card.card_code = card.card.card_id = card.card.name_ja = "AUDIT-" + key
            card.face_up = False
            state.cards[key] = card
            zone.append(key)
        if prefix == "peek":
            player.main_deck = zone
    return state


def _played(hand=1):
    state = _state(hand)
    return apply_action(state, _play(state)).state


def _inspected(hand=1):
    state = _played(hand)
    return apply_action(state, _resolve(state))


def test_exact_identity_candidate_registry_and_private_contract():
    effect = _state().effect_definitions[CODE + ":1"]
    assert effect == EffectDefinition.model_validate(_candidate(CODE).to_registry_entry())
    assert effect.label_ja == TEN_MINUS_HAND_PRIVATE_TWO_TEXT
    assert (effect.text_revision_id, effect.raw_text_hash) == (
        1232, "4e93a5a5a79f7b2afe0fba115053b86de413fd60bd6f84d34fdadb84676fe116")
    assert effect.review_status == "test_validated"
    assert effect.simulation_support == "test_validated_executable"
    assert effect.choice.selection_policy == POLICY and effect.choice.amount_source is None
    assert not effect.cost and not effect.cost_choice and not effect.is_optional
    assert not effect.choice.reveal_selected_to_opponent


@pytest.mark.parametrize("changes", [
    {"card_code": "OTHER"}, {"text_revision_id": 1233}, {"raw_text_hash": "changed"},
    {"raw_effect_text_ja": TEN_MINUS_HAND_PRIVATE_TWO_TEXT + "カードを1枚引く。"},
    {"raw_effect_text_ja": TEN_MINUS_HAND_PRIVATE_TWO_TEXT.replace("2枚まで", "2枚")},
])
def test_generator_never_generalizes_binding(changes):
    row = {"card_code": CODE, "text_revision_id": 1232,
           "raw_text_hash": _state().effect_definitions[CODE + ":1"].raw_text_hash,
           "raw_effect_text_ja": TEN_MINUS_HAND_PRIVATE_TWO_TEXT}
    assert _onplay_ten_minus_hand_private_two({**row, **changes}) is None


@pytest.mark.parametrize("hand", [0, 1, 9, 10, 11])
@pytest.mark.parametrize("keep", [0, 1, 2])
def test_resolution_hand_count_and_zero_to_two_exact_zones(hand, keep):
    played = _played(hand)
    assert len(played.players["player_1"].hand) == hand
    assert played.pending_choice is None
    assert not played.players["player_1"].resolution_area
    result = apply_action(played, _resolve(played))
    count = max(0, 10 - hand)
    options = result.state.pending_choice.options
    assert options["inspected_card_instance_ids"] == [f"peek-{i}" for i in range(count)]
    assert options["minimum"] == 0 and options["maximum"] == min(2, count)
    assert options["candidate_card_instance_ids"] == options["inspected_card_instance_ids"]
    assert not any(e.event_type == "effect_cost_paid" for e in result.events)
    selected = options["inspected_card_instance_ids"][:min(keep, count)]
    final = apply_action(result.state, _select(result.state, selected)).state
    player = final.players["player_1"]
    assert player.hand == [f"hand-{i}" for i in range(hand)] + selected
    assert player.waiting_room == [f"peek-{i}" for i in range(len(selected), count)]
    assert player.main_deck == [f"peek-{i}" for i in range(count, 15)]
    assert not player.resolution_area and not final.pending_effects and final.pending_choice is None


def test_native_hand_change_while_waiting_is_counted_at_resolution():
    state = _played(9)
    other = _base_state(CODE, legacy=True).effect_definitions[CODE + ":1"].model_copy(
        update={"effect_id": "AUDIT-other"})
    state.effect_definitions[other.effect_id] = other
    invocation = state.pending_effects[0].model_copy(update={
        "invocation_id": "other-invocation", "effect_id": other.effect_id})
    state.pending_effects.insert(0, invocation)
    moved = apply_action(state, ActionRequest(action_type="manual_adjustment", player_id="player_1",
        expected_revision=state.revision, payload={
            "source_invocation_id": invocation.invocation_id, "source_effect_id": invocation.effect_id,
            "source_card_instance_id": invocation.source_card_instance_id, "adjustments": [
            {"adjustment_type": "move_card", "target_player_id": "player_1",
             "target_card_instance_id": "hand-0", "to_zone": "waiting_room"}]})).state
    result = apply_action(moved, _resolve(moved))
    assert len(result.state.pending_choice.options["inspected_card_instance_ids"]) == 2
    assert result.state.players["player_1"].hand == [f"hand-{i}" for i in range(1, 9)]


@pytest.mark.parametrize("waiting", [False, True])
def test_short_private_deck_refreshes_below_remaining_prefix(waiting):
    state = _played(6)
    player = state.players["player_1"]
    player.main_deck = ["peek-0"]
    player.waiting_room = ["peek-1", "peek-2", "peek-3", "peek-4"] if waiting else []
    result = apply_action(state, _resolve(state))
    inspected = result.state.pending_choice.options["inspected_card_instance_ids"]
    assert inspected[0] == "peek-0" and len(inspected) == (4 if waiting else 1)
    assert result.state.players["player_1"].refresh_count == player.refresh_count + int(waiting)
    assert result.state.pending_choice.options["maximum"] == (2 if waiting else 1)
    final = apply_action(result.state, _select(result.state, inspected[:1])).state
    assert not final.players["player_1"].resolution_area


def test_exact_private_deck_refreshes_after_discard_not_while_looking():
    state = _played(8)
    player = state.players["player_1"]
    player.main_deck = ["peek-0", "peek-1"]
    player.waiting_room = ["peek-2"]
    result = apply_action(state, _resolve(state))
    assert result.state.players["player_1"].refresh_count == player.refresh_count
    final = apply_action(result.state, _select(result.state, ["peek-1"])).state
    assert final.players["player_1"].refresh_count == player.refresh_count + 1
    assert set(final.players["player_1"].main_deck) == {"peek-0", "peek-2"}


@pytest.mark.parametrize("ids", [["peek-0", "peek-1", "peek-2"], ["peek-0", "peek-0"],
                                  ["peek-14"], ["hand-0"], ["opponent-secret"], [123]])
def test_illegal_selection_is_atomic(ids):
    state = _inspected().state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _select(state, ids))
    assert match_state_hash(state) == before


def test_private_dual_view_before_during_and_after_selection():
    played = _played()
    result = apply_action(played, _resolve(played))
    ids = result.state.pending_choice.options["inspected_card_instance_ids"]
    for current in (played, result.state):
        payload = _match_state_payload(current, events=result.events, legal_actions=generate_legal_actions(current), player_id="player_2")
        assert not set(ids).intersection(payload["state"]["cards"])
        assert "peek-14" not in payload["state"]["cards"]
        assert all(item not in json.dumps(payload) for item in ids)
    own_before = _match_state_payload(played, events=[], legal_actions=generate_legal_actions(played), player_id="player_1")
    assert not set(ids).intersection(own_before["state"]["cards"])
    own = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id="player_1")
    assert set(ids) <= own["state"]["cards"].keys()
    assert "opponent-secret" not in own["state"]["cards"] and "peek-14" not in own["state"]["cards"]
    final = apply_action(result.state, _select(result.state, ids[:2]))
    public = _match_state_payload(final.state, events=final.events, legal_actions=final.legal_actions, player_id="player_2")
    assert not set(ids[:2]).intersection(public["state"]["cards"])
    assert all(item not in json.dumps(public) for item in ids[:2])
    assert set(ids[2:]) <= public["state"]["cards"].keys()
    assert all(not e["data"].get("revealed_cards") for e in public["events"])


def test_empty_deck_and_no_waiting_finishes_without_invented_candidates():
    state = _played(0)
    state.players["player_1"].main_deck = []
    result = apply_action(state, _resolve(state))
    assert result.state.pending_choice.options["candidate_card_instance_ids"] == []
    assert result.state.pending_choice.options["maximum"] == 0
    final = apply_action(result.state, _select(result.state, [])).state
    assert not final.pending_effects and not final.players["player_1"].hand


def test_old_fixed_private_snapshot_does_not_gain_dynamic_hand_behavior():
    state = _state(9)
    raw = state.effect_definitions[CODE + ":1"].model_dump(mode="json")
    raw["choice"].pop("selection_policy")
    raw["choice"]["amount"] = 4
    raw["actions"][0]["amount"] = 4
    state.effect_definitions[CODE + ":1"] = EffectDefinition.model_validate(raw)
    played = apply_action(state, _play(state)).state
    result = apply_action(played, _resolve(played))
    assert result.state.pending_choice.options["inspected_card_instance_ids"] == [f"peek-{i}" for i in range(4)]


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("hand", [0, 9, 11])
def test_four_ai_native_resolution_hidden_identity_invariance(policy, hand):
    state = _played(hand)
    ai = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    for _ in range(2):
        before = match_state_hash(state)
        decision = ai.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
        assert isinstance(decision, SimpleAIDecision) and match_state_hash(state) == before
        changed = state.model_copy(deep=True)
        changed.cards["opponent-secret"].card.card_code = "SECRET-CHANGED"
        changed.cards["peek-14"].card.card_code = "HIDDEN-TAIL-CHANGED"
        assert ai.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}).action == decision.action
        state = apply_action(state, decision.action).state
    assert state.pending_choice is None and not state.pending_effects
    assert len(state.players["player_1"].hand) == hand + min(2, max(0, 10 - hand))


@pytest.mark.parametrize("legacy", [False, True])
def test_sql_replay_keeps_new_private_and_old_manual_snapshots(tmp_path, legacy):
    state = _state(1, legacy=legacy)
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repository.apply(state.match_id, _play(state)).state
    if legacy:
        invocation = played.pending_effects[0]
        final = repository.apply(state.match_id, ActionRequest(action_type="manual_adjustment",
            player_id="player_1", expected_revision=played.revision, payload={
                "source_invocation_id": invocation.invocation_id, "source_effect_id": invocation.effect_id,
                "source_card_instance_id": invocation.source_card_instance_id, "adjustments": [{
                    "adjustment_type": "move_card", "target_player_id": "player_1",
                    "target_card_instance_id": "peek-0", "to_zone": "waiting_room"}]}))
        assert final.state.players["player_1"].hand == ["hand-0"]
        assert final.state.effect_definitions[CODE + ":1"].choice is None
    else:
        inspected = repository.apply(state.match_id, _resolve(played)).state
        final = repository.apply(state.match_id, _select(inspected, ["peek-0", "peek-1"]))
    replay = repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("changes", [{"amount": 10}, {"minimum": 1}, {"maximum": 3},
    {"reveal_selected_to_opponent": True}, {"amount_source": "own_stage_member_count_plus_2"},
    {"work_key": "love_live_superstar"}, {"requires_order": True}])
def test_snapshot_policy_rejects_widened_choices(changes):
    raw = deepcopy(_state().effect_definitions[CODE + ":1"].model_dump(mode="json"))
    raw["choice"].update(changes)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("changes", [{"is_optional": True}, {"duration": "live"},
    {"condition": {"success_live_count_at_least": 1}}, {"trigger": "player_activation"}])
def test_snapshot_policy_rejects_other_execution_contracts(changes):
    raw = _state().effect_definitions[CODE + ":1"].model_dump(mode="json")
    raw.update(changes)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)
