from contextlib import closing
from functools import lru_cache
import json
from pathlib import Path

import pytest
from test_nijigasaki_inspection import _state as _base_state

from loveca.db.bootstrap import connect_database
from loveca.simulation.ai import SimpleAIBlocker, SimpleAIController, SimpleAIPolicy
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import (
    IllegalActionError, _effect_unavailable_reason, _static_heart_bonus,
    apply_action, generate_legal_actions,
)
from loveca.simulation.models import ActionRequest, CardDefinition, CardInstance
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!HS-pb1-014"
EFFECT = CODE + ":1"
STATIC = CODE + ":2"
RULE_REFERENCE_IDS = ("4.5.7.1", "9.6.3", "9.7.7", "9.11.1", "11.10.1", "11.10.2")
FRONT = {"left": "right", "center": "center", "right": "left"}


@lru_cache
def _definitions():
    return {effect.effect_id: effect for effect in load_effect_registry().effects if effect.card_code == CODE}


def _state(*, slot="center", opponents=3):
    state = _base_state(CODE)
    state.effect_definitions = {key: value.model_copy(deep=True) for key, value in _definitions().items()}
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        state.cards["source-live"].card = _load_definition(connection, CODE, None, state.effect_definitions, {})
    other = state.players["player_2"]
    other.member_area = {"left": None, "center": None, "right": None}
    for index, position in enumerate(("left", "center", "right")[:opponents]):
        key = "opponent-" + position
        state.cards[key] = CardInstance(instance_id=key, owner_id="player_2",
            card=CardDefinition(card_code="AUDIT-" + key, card_id="AUDIT-" + key,
                name_ja="AUDIT-" + key, card_type="member", cost=4 + index,
                work_keys=["hasunosora"], unit_keys=["miracra_park"]))
        other.member_area[position] = key
    state.players["player_1"].member_area = {"left": None, "center": None, "right": None}
    for player in state.players.values():
        ids = [key for zone in [player.main_deck, player.hand, player.energy_deck,
            player.energy_area, player.live_area, player.waiting_room, player.resolution_area,
            player.success_live_area, [key for key in player.member_area.values() if key]] for key in zone]
        assert len(ids) == len(set(ids))
    return state


def _play(state, slot="center", owner="player_1"):
    return ActionRequest(action_type="play_member", player_id=owner, expected_revision=state.revision,
        payload={"card_instance_id": "source-live", "slot": slot,
            "energy_instance_ids": list(state.players[owner].energy_area), "use_baton_touch": False})


def _manual(state, changes, *, invocation=None, owner="player_1"):
    invocation = invocation or next(item for item in state.pending_effects if item.effect_id == EFFECT)
    return ActionRequest(action_type="manual_adjustment", player_id=owner, expected_revision=state.revision,
        payload={"source_invocation_id": invocation.invocation_id, "source_effect_id": invocation.effect_id,
            "source_card_instance_id": invocation.source_card_instance_id, "adjustments": changes})


def _swap_roles(state):
    def swap(value):
        if isinstance(value, str):
            return {"player_1": "player_2", "player_2": "player_1"}.get(value, value)
        if isinstance(value, list):
            return [swap(item) for item in value]
        if isinstance(value, dict):
            return {swap(key): swap(item) for key, item in value.items()}
        return value
    return type(state).model_validate(swap(state.model_dump(mode="json")))


def test_exact_full_binding_keeps_manual_first_and_existing_executable_static():
    state = _state()
    card = state.cards["source-live"].card
    assert (card.text_revision_id, card.raw_text_hash) == (
        130, "542b68ba2435dd4aafaaf2f88d9fc0d75cf33321d245934e772175c21e009591")
    assert card.unit_keys == ["miracra_park"] and card.work_keys == ["hasunosora"]
    assert card.effect_ids == [EFFECT, STATIC] and not card.effect_registry_errors
    assert state.effect_definitions[EFFECT].simulation_support == "manual_resolution"
    assert state.effect_definitions[STATIC].simulation_support == "test_validated_executable"
    candidate = next(c for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
        if c.effect_id == EFFECT)
    assert candidate.simulation_support == "manual_resolution"


@pytest.mark.parametrize("slot", FRONT)
@pytest.mark.parametrize("opponents", [0, 1, 3])
def test_native_onplay_retains_manual_obligation_without_automatic_move(slot, opponents):
    initial = _state(slot=slot, opponents=opponents)
    before = match_state_hash(initial)
    result = apply_action(initial, _play(initial, slot))
    assert match_state_hash(initial) == before
    assert result.state.players["player_2"].member_area == initial.players["player_2"].member_area
    assert [item.effect_id for item in result.state.pending_effects] == [EFFECT]
    inv = next(a for a in result.legal_actions if a.action_type == "resolve_effect").options["invocations"][0]
    assert inv["execution_mode"] == inv["simulation_support"] == "manual_resolution"
    assert not any(event.event_type in {"stage_member_group_moved", "stage_member_groups_swapped", "effect_resolved"}
                   for event in result.events)


@pytest.mark.parametrize("actor", ["player_1", "player_2"])
def test_manual_card_cannot_be_bypassed_by_structured_target_submission(actor):
    state = apply_action(_state(), _play(_state())).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, ActionRequest(action_type="resolve_effect", player_id=actor,
            expected_revision=state.revision, payload={"invocation_id": state.pending_effects[0].invocation_id,
                "selected_card_instance_ids": ["opponent-left"], "to_slot": "center"}))
    assert match_state_hash(state) == before


def test_unregistered_generic_probe_does_not_support_opponent_position_change():
    state = apply_action(_state(), _play(_state())).state
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(execution_mode="prompt_then_resolve", simulation_support="test_validated_executable",
        source_reference="UNREGISTERED TEST PROBE - not a ruling", choice={"choice_type": "member_from_stage",
            "zone": "stage", "card_type": "member", "target_player": "opponent", "minimum": 1, "maximum": 1},
        actions=[{"action_type": "position_change_selected"}])
    state.effect_definitions[EFFECT] = EffectDefinition.model_validate(raw)
    offered = next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect").options["invocations"][0]
    assert "opponent-left" in offered["candidate_card_instance_ids"]
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError, match="target is not on Stage"):
        apply_action(state, ActionRequest(action_type="resolve_effect", player_id="player_1",
            expected_revision=state.revision, payload={"invocation_id": state.pending_effects[0].invocation_id,
                "selected_card_instance_ids": ["opponent-left"], "to_slot": "center"}))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("unit,work,empty,expected", [
    (["miracra_park"], ["hasunosora"], False, None),
    (["cerise_bouquet"], ["hasunosora"], False, "stage_member_unit_mismatch"),
    ([], ["hasunosora"], False, "stage_member_unit_mismatch"),
    (["miracra_park"], ["other"], False, None),
    (["miracra_park"], ["hasunosora"], True, "stage_member_unit_mismatch"),
])
def test_read_only_unit_condition_probe_is_not_full_card_executor(unit, work, empty, expected):
    state = apply_action(_state(), _play(_state())).state
    probe = state.effect_definitions[EFFECT].model_copy(update={
        "condition": {"own_stage_members_only_unit_key": "miracra_park"}})
    state.effect_definitions[EFFECT] = probe
    source = state.cards["source-live"]
    source.card.unit_keys, source.card.work_keys = unit, work
    if empty:
        state.players["player_1"].member_area["center"] = None
        state.players["player_1"].hand.append("source-live")
    before = match_state_hash(state)
    assert _effect_unavailable_reason(state, state.pending_effects[0]) == expected
    assert match_state_hash(state) == before


@pytest.mark.parametrize("slot", FRONT)
@pytest.mark.parametrize("occupied", [False, True])
def test_native_explicit_manual_swap_sql_preserves_groups_without_reinterpreting_side_static(tmp_path, slot, occupied):
    initial = _state()
    front = FRONT[slot]
    moving_slot = next(position for position in FRONT if position != front)
    moving_id, front_id = "opponent-" + moving_slot, "opponent-" + front
    initial.cards[moving_id].card.cost = 4
    initial.cards[moving_id].orientation = "wait"
    initial.cards[front_id].card.cost = 10
    if not occupied:
        initial.players["player_2"].member_area[front] = None
        initial.players["player_2"].hand.append(front_id)
    for position, key in [(moving_slot, "moving-child"), (front, "front-child")]:
        if initial.players["player_2"].member_area[position] is None:
            continue
        initial.cards[key] = initial.cards[moving_id].model_copy(update={"instance_id": key}, deep=True)
        initial.players["player_2"].member_area_attachments[position] = [key]
    repo = MatchRepository(tmp_path / "manual-position.sqlite3")
    repo.create_match(initial, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(initial.match_id, _play(initial, slot)).state
    if slot == "center":
        assert _static_heart_bonus(played, "player_1", "source-live")["heart01"] == int(occupied)
    result = repo.apply(initial.match_id, _manual(played, [{"adjustment_type": "position_change",
        "target_player_id": "player_2", "from_slot": moving_slot, "to_slot": front}]))
    player = result.state.players["player_2"]
    assert player.member_area[front] == moving_id
    assert player.member_area[moving_slot] == (front_id if occupied else None)
    assert player.member_area_attachments[front] == ["moving-child"]
    assert player.member_area_attachments[moving_slot] == (["front-child"] if occupied else [])
    assert result.state.cards[moving_id].orientation == "wait"
    if slot == "center":
        assert _static_heart_bonus(result.state, "player_1", "source-live")["heart01"] == 0
    assert not result.state.pending_effects
    replay = repo.replay(initial.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")


def test_same_area_manual_move_is_atomic_not_a_ruling_on_card_target_eligibility():
    state = apply_action(_state(), _play(_state())).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError, match="two different slots"):
        apply_action(state, _manual(state, [{"adjustment_type": "position_change",
            "target_player_id": "player_2", "from_slot": "center", "to_slot": "center"}]))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("returning", [False, True])
def test_native_source_moves_then_departs_sql_has_no_original_last_position_binding(tmp_path, returning):
    initial = _state()
    control = initial.effect_definitions[EFFECT].model_copy(update={"effect_id": "CONTROL"})
    initial.effect_definitions["CONTROL"] = control
    initial.cards["source-live"].card.effect_ids.append("CONTROL")
    repo = MatchRepository(tmp_path / "last-position.sqlite3")
    repo.create_match(initial, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(initial.match_id, _play(initial)).state
    original = next(item for item in played.pending_effects if item.effect_id == EFFECT)
    ctrl = next(item for item in played.pending_effects if item.effect_id == "CONTROL")
    changes = [{"adjustment_type": "position_change", "target_player_id": "player_1",
                "from_slot": "center", "to_slot": "left"},
        {"adjustment_type": "move_card", "target_player_id": "player_1",
         "target_card_instance_id": "source-live", "to_zone": "main_deck"}]
    if returning:
        changes.append({"adjustment_type": "move_card", "target_player_id": "player_1",
            "target_card_instance_id": "source-live", "to_zone": "member_right"})
    result = repo.apply(initial.match_id, _manual(played, changes, invocation=ctrl))
    invocation = next(item for item in result.state.pending_effects if item.invocation_id == original.invocation_id)
    assert invocation.trigger_data["slot"] == "center"
    assert not invocation.trigger_data.get("original_source_stage_object")
    assert "last_stage_slot" not in invocation.trigger_data
    assert result.state.players["player_1"].member_area["left"] is None
    assert result.state.players["player_1"].member_area["right"] == ("source-live" if returning else None)
    assert repo.replay(initial.match_id)["final_state"] == result.state.model_dump(mode="json")


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_four_ai_both_roles_block_without_hidden_identity_or_input_mutation(policy, owner):
    initial = _state()
    if owner == "player_2":
        initial = _swap_roles(initial)
    state = apply_action(initial, _play(initial, owner=owner)).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIBlocker) and decision.reason == "no_safe_ai_action"
    changed = state.model_copy(deep=True)
    for key in ("tail", "opponent-secret"):
        instance = changed.cards[key]
        instance.card.card_code = instance.card.name_ja = "REPLACED-HIDDEN"
        replacement = "changed-" + key
        changed.cards[replacement] = changed.cards.pop(key).model_copy(update={"instance_id": replacement})
        player = changed.players[instance.owner_id]
        player.hand = [replacement if item == key else item for item in player.hand]
        player.main_deck = [replacement if item == key else item for item in player.main_deck]
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner}) == decision
    assert match_state_hash(state) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_full_player_projection_retains_own_manual_handle_without_hidden_source_face(owner):
    initial = _state()
    if owner == "player_2":
        initial = _swap_roles(initial)
    played = apply_action(initial, _play(initial, owner=owner)).state
    # A separate pending test CONTROL moves the source, leaving the real invocation waiting.
    control = played.pending_effects[0].model_copy(update={"invocation_id": "CONTROL", "effect_id": "CONTROL"})
    played.effect_definitions["CONTROL"] = played.effect_definitions[EFFECT].model_copy(update={"effect_id": "CONTROL"})
    played.pending_effects.append(control)
    result = apply_action(played, _manual(played, [{"adjustment_type": "move_card",
        "target_player_id": owner, "target_card_instance_id": "source-live", "to_zone": "main_deck"}],
        invocation=control, owner=owner))
    other = "player_2" if owner == "player_1" else "player_1"
    for viewer in (owner, other):
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        assert "source-live" not in payload["state"]["cards"]
        assert "tail" not in payload["state"]["cards"]
        if viewer == other:
            assert "source-live" not in json.dumps(payload)
        else:
            action = next(item for item in payload["legal_actions"] if item["action_type"] == "manual_adjustment")
            assert action["options"]["source_invocations"][0]["source_card_instance_id"] == "source-live"
