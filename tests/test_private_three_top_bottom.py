from copy import deepcopy
from itertools import permutations
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_nijigasaki_inspection import _state as _base_state, _play, _resolve

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effect_candidates import (
    PRIVATE_THREE_TOP_BOTTOM_FULL_TEXT, _onplay_private_three_top_bottom,
    discover_effect_candidates,
)
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.online import match_state_hash
from loveca.simulation.models import ActionRequest
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!S-bp7-008"
POLICY = "private_three_top_bottom_order"
RULE_REFERENCE_IDS = ("5.7.1", "9.6.3.1", "10.2.2.2", "10.2.3")


def _state(*, legacy=False):
    state = _base_state(CODE, legacy=legacy)
    player = state.players["player_1"]
    player.hand = ["source-live", "cost"]
    for p in state.players.values():
        ids = [key for zone in [p.main_deck, p.hand, p.energy_deck, p.energy_area, p.live_area,
            p.waiting_room, p.resolution_area, p.success_live_area,
            [key for key in p.member_area.values() if key]] for key in zone]
        assert len(ids) == len(set(ids))
    return state


def _begin(state=None):
    state = _state() if state is None else state
    played = apply_action(state, _play(state)).state
    return apply_action(played, _resolve(played)).state


def _finish(state, top, bottom, **extra):
    return ActionRequest(action_type="resolve_effect_choice", player_id="player_1",
        expected_revision=state.revision, payload={"selected_card_instance_ids": top,
        "ordered_card_instance_ids": top, "bottom_ordered_card_instance_ids": bottom, **extra})


def test_native_onplay_is_private_split_order_not_manual():
    state = _begin()
    assert state.pending_choice.choice_type == "effect_inspection_selection"
    assert state.pending_choice.options["selection_policy"] == POLICY


@pytest.mark.parametrize("order", list(permutations(["good-member", "good-live", "wrong-work"])))
@pytest.mark.parametrize("count", range(4))
def test_every_partition_and_both_orders_preserve_original_tail(order, count):
    state = _begin()
    before = match_state_hash(state)
    top, bottom = list(order[:count]), list(order[count:])
    result = apply_action(state, _finish(state, top, bottom))
    player = result.state.players["player_1"]
    assert player.main_deck == top + ["blade-heart", "tail", "deck-live-1"] + bottom
    assert player.hand == ["cost"] and not player.waiting_room and not player.resolution_area
    assert not result.state.pending_effects and result.state.pending_choice is None
    assert all(not result.state.cards[key].face_up for key in order)
    assert match_state_hash(state) == before
    assert not any(e.event_type in {"cards_drawn", "cards_revealed"} for e in result.events)


@pytest.mark.parametrize("top,bottom", [([], []), (["good-live"], ["good-member"]),
    (["good-member"], ["good-member", "wrong-work"]), ([], ["good-member"] * 3),
    (["tail"], ["good-live", "wrong-work"]), ([], ["opponent-secret"]),
    ([123], []), ([], None), ([], "wrong-work")])
def test_invalid_partition_is_atomic(top, bottom):
    state = _begin()
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _finish(state, top, bottom))
    assert match_state_hash(state) == before


def test_opponent_cannot_order_and_manual_cannot_swap_inspected_objects():
    state = _begin()
    action = _finish(state, [], ["good-member", "good-live", "wrong-work"])
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, action.model_copy(update={"player_id": "player_2"}))
    with pytest.raises(IllegalActionError):
        apply_action(state, ActionRequest(action_type="manual_adjustment", player_id="player_1",
            expected_revision=state.revision, payload={"adjustments": []}))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("deck,waiting", [(0, 0), (0, 4), (1, 0), (1, 1), (1, 4), (2, 4), (3, 4)])
def test_short_deck_refresh_is_beneath_remaining_prefix(deck, waiting):
    initial = _state()
    player = initial.players["player_1"]
    pool = list(player.main_deck)
    player.main_deck = pool[:deck]
    player.waiting_room = pool[deck:deck + waiting]
    state = _begin(initial)
    inspected = state.pending_choice.options["inspected_card_instance_ids"]
    assert inspected[:deck] == pool[:deck]
    assert len(inspected) == min(3, deck + waiting)
    assert state.players["player_1"].refresh_count == int(deck < 3 and waiting > 0)
    untouched = list(state.players["player_1"].main_deck)
    final = apply_action(state, _finish(state, [], inspected[::-1])).state
    assert final.players["player_1"].main_deck == untouched + inspected[::-1]
    assert final.players["player_1"].refresh_count == state.players["player_1"].refresh_count


def test_full_response_private_before_during_after_and_hidden_tail_invariance():
    initial = _state()
    played = apply_action(initial, _play(initial)).state
    inspected = apply_action(played, _resolve(played))
    ids = inspected.state.pending_choice.options["inspected_card_instance_ids"]
    own = _match_state_payload(inspected.state, events=inspected.events,
        legal_actions=inspected.legal_actions, player_id="player_1")
    assert set(ids) <= own["state"]["cards"].keys()
    final = apply_action(inspected.state, _finish(inspected.state, ids[:1], ids[1:][::-1]))
    for state, events in [(played, []), (inspected.state, inspected.events), (final.state, final.events)]:
        for viewer in ("player_1", "player_2"):
            payload = _match_state_payload(state, events=events,
                legal_actions=generate_legal_actions(state), player_id=viewer)
            assert "tail" not in payload["state"]["cards"]
            if viewer == "player_2" or state is final.state:
                assert not set(ids).intersection(payload["state"]["cards"])
                assert all(key not in json.dumps(payload) for key in ids)


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_native_choice_hidden_identity_invariance(policy):
    state = apply_action(_state(), _play(_state())).state
    ai = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    for _ in range(2):
        before = match_state_hash(state)
        decision = ai.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
        assert isinstance(decision, SimpleAIDecision) and match_state_hash(state) == before
        changed = state.model_copy(deep=True)
        for key in ("tail", "opponent-secret"):
            changed.cards[key].card.card_code = changed.cards[key].card.name_ja = "HIDDEN-REPLACED"
            changed.cards[key].card.blade = 99
            replacement = "changed-" + key
            changed.cards[replacement] = changed.cards.pop(key).model_copy(update={"instance_id": replacement})
            owner = changed.players[changed.cards[replacement].owner_id]
            owner.main_deck = [replacement if item == key else item for item in owner.main_deck]
            owner.hand = [replacement if item == key else item for item in owner.hand]
        assert ai.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}).action == decision.action
        state = apply_action(state, decision.action).state
    assert state.pending_choice is None and not state.pending_effects


@pytest.mark.parametrize("legacy", [False, True])
def test_native_sql_replay_private_order_and_old_manual(tmp_path, legacy):
    state = _state(legacy=legacy)
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
                    "target_card_instance_id": "good-member", "to_zone": "waiting_room"}]}))
    else:
        inspected = repository.apply(state.match_id, _resolve(played)).state
        final = repository.apply(state.match_id, _finish(inspected, ["wrong-work"], ["good-live", "good-member"]))
    replay = repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


def test_exact_binding_and_second_segment_remains_manual():
    state = _state()
    effect = state.effect_definitions[CODE + ":1"]
    candidate = next(c for c in discover_effect_candidates(Path("data/loveca.sqlite3"),
        include_registered=True) if c.effect_id == effect.effect_id)
    assert effect == EffectDefinition.model_validate(candidate.to_registry_entry())
    assert (effect.text_revision_id, effect.raw_text_hash) == (
        853, "1de3807181773c1f9c909324ecf5885928876ce992a6ed6f4d93e2f000a63f6b")
    assert effect.review_status == "test_validated"
    second = next(e for e in load_effect_registry().effects if e.effect_id == CODE + ":2")
    assert second.simulation_support == "manual_resolution" and second.execution_mode == "manual_resolution"


@pytest.mark.parametrize("changes", [{"card_code": "OTHER"}, {"text_revision_id": 854},
    {"raw_text_hash": "changed"}, {"raw_effect_text_ja": PRIVATE_THREE_TOP_BOTTOM_FULL_TEXT + "。"},
    {"raw_effect_text_ja": PRIVATE_THREE_TOP_BOTTOM_FULL_TEXT.split(" ")[0]}])
def test_full_two_segment_generator_identity_guard(changes):
    row = {"card_code": CODE, "text_revision_id": 853,
        "raw_text_hash": "1de3807181773c1f9c909324ecf5885928876ce992a6ed6f4d93e2f000a63f6b",
        "raw_effect_text_ja": PRIVATE_THREE_TOP_BOTTOM_FULL_TEXT}
    assert _onplay_private_three_top_bottom({**row, **changes}) is None


@pytest.mark.parametrize("changes", [{"amount": 4}, {"minimum": 1}, {"maximum": 2},
    {"reveal_selected_to_opponent": True}, {"requires_order": False}, {"work_key": "aqours"},
    {"unselected_destination": "waiting_room"}, {"amount_source": "own_stage_member_count_plus_2"}])
def test_bounded_choice_snapshot_rejects_widening(changes):
    raw = deepcopy(_state().effect_definitions[CODE + ":1"].model_dump(mode="json"))
    raw["choice"].update(changes)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("changes", [{"is_optional": True}, {"duration": "live"},
    {"condition": {"success_live_count_at_least": 1}}, {"trigger": "player_activation"}])
def test_bounded_sequence_rejects_other_contracts(changes):
    raw = _state().effect_definitions[CODE + ":1"].model_dump(mode="json")
    raw.update(changes)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


def test_old_snapshot_retains_original_unselected_order():
    state = _state()
    raw = state.effect_definitions[CODE + ":1"].model_dump(mode="json")
    raw["choice"].pop("selection_policy")
    state.effect_definitions[CODE + ":1"] = EffectDefinition.model_validate(raw)
    state = _begin(state)
    assert "selection_policy" not in state.pending_choice.options
    result = apply_action(state, _finish(state, ["wrong-work"], ["good-live", "good-member"]))
    assert result.state.players["player_1"].main_deck == [
        "wrong-work", "blade-heart", "tail", "deck-live-1", "good-member", "good-live"]


def test_legacy_sandbox_and_semantic_examples_supply_legal_new_partition_only():
    from tools.ai_sandbox.blackbox_playtest import choose_action
    from tools.ai_sandbox.semantic_playtest import payload_example_for_action, payload_hint_for_action

    state = _begin()
    legal = generate_legal_actions(state)
    decision = choose_action(state, legal, manual_policy="block")
    assert decision is not None
    kind, player, payload = decision
    result = apply_action(state, ActionRequest(action_type=kind, player_id=player,
        expected_revision=state.revision, payload=payload))
    assert not result.state.pending_effects
    action = next(a for a in legal if a.action_type == "resolve_effect_choice")
    example = payload_example_for_action(action)
    assert "bottom_ordered_card_instance_ids" in payload_hint_for_action(action)
    assert example["selected_card_instance_ids"] == []
    assert len(example["bottom_ordered_card_instance_ids"]) == 3
    final = apply_action(state, _finish(state, [], example["bottom_ordered_card_instance_ids"]))
    assert not final.state.pending_effects


@pytest.mark.parametrize("order", [["good-live"], ["good-member", "good-member"], ["tail"], "good-member"])
def test_top_order_must_match_selected_group_atomically(order):
    state = _begin()
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _finish(state, ["good-member"], ["good-live", "wrong-work"],
            ordered_card_instance_ids=order))
    assert match_state_hash(state) == before


def test_semantic_api_context_includes_only_owner_inspected_cards_and_legal_example():
    from tools.ai_sandbox.semantic_playtest import build_api_play_context

    state = _begin()
    before = match_state_hash(state)
    context = build_api_play_context(state, generate_legal_actions(state))
    text = json.dumps(context)
    assert "AUDIT-good-member" in text
    assert "AUDIT-tail" not in text and "opponent-secret" not in text
    assert "bottom_ordered_card_instance_ids" in text
    assert match_state_hash(state) == before


def test_old_structured_snapshot_sql_keeps_original_bottom_order(tmp_path):
    state = _state()
    raw = state.effect_definitions[CODE + ":1"].model_dump(mode="json")
    raw["choice"].pop("selection_policy")
    state.effect_definitions[CODE + ":1"] = EffectDefinition.model_validate(raw)
    repo = MatchRepository(tmp_path / "old-structured.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state)).state
    inspected = repo.apply(state.match_id, _resolve(played)).state
    final = repo.apply(state.match_id, _finish(inspected, [], ["wrong-work", "good-live", "good-member"]))
    assert final.state.players["player_1"].main_deck[-3:] == ["good-member", "good-live", "wrong-work"]
    assert repo.replay(state.match_id)["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_both_player_roles_keep_private_inspection_and_valid_partition(owner):
    state = _state()
    if owner == "player_2":
        def swap(value):
            if isinstance(value, str):
                return {"player_1": "player_2", "player_2": "player_1"}.get(value, value)
            if isinstance(value, list):
                return [swap(item) for item in value]
            if isinstance(value, dict):
                return {swap(key): swap(item) for key, item in value.items()}
            return value
        state = type(state).model_validate(swap(state.model_dump(mode="json")))
    play = _play(state).model_copy(update={"player_id": owner})
    play.payload = {**play.payload, "energy_instance_ids": state.players[owner].energy_area}
    played = apply_action(state, play).state
    inspected = apply_action(played, _resolve(played).model_copy(update={"player_id": owner}))
    ids = inspected.state.pending_choice.options["inspected_card_instance_ids"]
    other = "player_2" if owner == "player_1" else "player_1"
    public = _match_state_payload(inspected.state, events=inspected.events,
        legal_actions=inspected.legal_actions, player_id=other)
    assert not set(ids).intersection(public["state"]["cards"])
    final = apply_action(inspected.state, _finish(inspected.state, ids[:1], ids[1:][::-1]).model_copy(update={"player_id": owner}))
    assert not final.state.pending_effects and not final.state.players[owner].resolution_area


@pytest.mark.parametrize("movement", ["hand", "return", "main_deck", "position"])
def test_native_source_interference_sql_still_reorders_actual_deck(tmp_path, movement):
    from test_moved_source_ready import _manual

    state = _state()
    control = _state(legacy=True).effect_definitions[CODE + ":1"].model_copy(update={"effect_id": "CONTROL"})
    state.effect_definitions["CONTROL"] = control
    state.cards["source-live"].card.effect_ids.append("CONTROL")
    repo = MatchRepository(tmp_path / "source.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state)).state
    ctrl = next(i for i in played.pending_effects if i.effect_id == "CONTROL")
    if movement == "position":
        changes = [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "right"}]
    else:
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live",
                    "to_zone": "main_deck" if movement == "main_deck" else "hand"}]
        if movement == "return":
            changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_right"})
    moved = repo.apply(state.match_id, _manual(played, changes, ctrl)).state
    original_deck = list(moved.players["player_1"].main_deck)
    inspected = repo.apply(state.match_id, _resolve(moved)).state
    ids = inspected.pending_choice.options["inspected_card_instance_ids"]
    final = repo.apply(state.match_id, _finish(inspected, ids[1:], ids[:1]))
    assert final.state.players["player_1"].main_deck == ids[1:] + original_deck[3:] + ids[:1]
    assert not final.state.pending_effects
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("deck,waiting", [(0, 0), (0, 4), (1, 0), (1, 1), (1, 4), (2, 4), (3, 3)])
def test_short_private_inspection_sql(tmp_path, deck, waiting):
    state = _state()
    player = state.players["player_1"]
    pool = list(player.main_deck)
    player.main_deck, player.waiting_room = pool[:deck], pool[deck:deck + waiting]
    repo = MatchRepository(tmp_path / "short.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state)).state
    inspected = repo.apply(state.match_id, _resolve(played)).state
    ids = inspected.pending_choice.options["inspected_card_instance_ids"]
    final = repo.apply(state.match_id, _finish(inspected, ids[::-1], []))
    assert final.state.players["player_1"].main_deck[:len(ids)] == ids[::-1]
    assert repo.replay(state.match_id)["final_state"] == final.state.model_dump(mode="json")
