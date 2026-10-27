from pathlib import Path
import json

import pytest
from test_nijigasaki_inspection import _state as _base_state
from test_nijigasaki_inspection import _candidate
from test_mirakura_front_position_boundary import _swap_roles

from loveca.simulation.engine import IllegalActionError, StaleRevisionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.webapp import _match_state_payload

CODE = "PL!SP-bp5-010"
EFFECT = CODE + ":1"
CHOICE = "multi_player_center_position_change"
POLICY = "public_both_center_position_sequential"


def _legacy_effect():
    raw = _candidate(CODE).to_registry_entry()
    raw.update(choice=None, actions=[{"action_type": "manual_resolution"}], execution_mode="manual_resolution",
        simulation_support="manual_resolution", review_status="parsed_draft",
        source_reference="Official card text; timing-only manual fallback pending structured effect modeling")
    return EffectDefinition.model_validate(raw)


def _state(own_center=True, other_center=True, *, owner="player_1", occupied=False):
    state = _base_state(CODE)
    state.effect_order_policy = "ap_nap_player_choice"
    for player_id, center in (("player_1", own_center), ("player_2", other_center)):
        player = state.players[player_id]
        player.member_area = {"left": None, "center": None, "right": None}
        for slot in (["center"] if center else []) + (["right"] if occupied else []):
            key = player_id + "-" + slot
            card = state.cards["good-member"].model_copy(deep=True)
            card.instance_id, card.owner_id = key, player_id
            card.orientation = "wait"
            state.cards[key] = card
            player.member_area[slot] = key
    return _swap_roles(state) if owner == "player_2" else state


def _play(state, owner="player_1"):
    return ActionRequest(action_type="play_member", player_id=owner, expected_revision=state.revision,
        payload={"card_instance_id": "source-live", "slot": "left", "use_baton_touch": False,
                 "energy_instance_ids": list(state.players[owner].energy_area)})


def _begin(state, owner="player_1"):
    played = apply_action(state, _play(state, owner)).state
    inv = next(item for item in played.pending_effects if item.effect_id == EFFECT)
    return apply_action(played, ActionRequest(action_type="resolve_effect", player_id=owner,
        expected_revision=played.revision, payload={"invocation_id": inv.invocation_id}))


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_native_onplay_starts_independent_center_position_choices(owner):
    state = _state(owner=owner)
    result = _begin(state, owner)
    assert result.state.pending_choice.options["multi_player_choice_type"] == CHOICE
    assert result.state.pending_choice.options["selection_policy"] == POLICY


def _choose(state, slot="right", *, actor=None, **extra):
    return ActionRequest(action_type="resolve_effect_choice", player_id=actor or state.pending_choice.player_id,
        expected_revision=state.revision, payload={"slot": slot, **extra})


@pytest.mark.parametrize("first", [False, True])
@pytest.mark.parametrize("second", [False, True])
@pytest.mark.parametrize("occupied", [False, True])
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_native_sql_both_players_move_only_their_current_center(tmp_path, first, second, occupied, owner):
    initial = _state(first, second, owner=owner, occupied=occupied)
    for player_id in initial.players:
        for slot, top in initial.players[player_id].member_area.items():
            if top:
                child = initial.cards[top].model_copy(deep=True)
                child.instance_id = top + "-child"
                initial.cards[child.instance_id] = child
                initial.players[player_id].member_area_attachments[slot] = [child.instance_id]
    repo = MatchRepository(tmp_path / "centers.sqlite3")
    repo.create_match(initial, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(initial.match_id, _play(initial, owner)).state
    inv = next(item for item in played.pending_effects if item.effect_id == EFFECT)
    state = repo.apply(initial.match_id, ActionRequest(action_type="resolve_effect", player_id=owner,
        expected_revision=played.revision, payload={"invocation_id": inv.invocation_id})).state
    while state.pending_choice:
        chooser = state.pending_choice.player_id
        moving = state.players[chooser].member_area["center"]
        swapped = state.players[chooser].member_area["right"]
        children = list(state.players[chooser].member_area_attachments["center"])
        before = match_state_hash(state)
        result = repo.apply(initial.match_id, _choose(state))
        assert match_state_hash(state) == before
        assert result.state.players[chooser].member_area["right"] == moving
        assert result.state.players[chooser].member_area["center"] == swapped
        assert result.state.players[chooser].member_area_attachments["right"] == children
        assert result.state.cards[moving].orientation == "wait"
        state = result.state
    assert not state.pending_effects
    assert repo.replay(initial.match_id)["final_state"] == state.model_dump(mode="json")


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("phase,expected", [("first_main", "player_1"), ("second_main", "player_2"),
                                         ("live_judgment", "player_1"), ("live_set_second", "player_1")])
def test_active_phase_player_not_owner_or_ui_pointer_selects_first(owner, phase, expected):
    initial = _state()
    state = apply_action(initial, _play(initial)).state
    state.phase, state.active_player_id = phase, "player_2"
    state.pending_effects[0].player_id = owner
    inv = state.pending_effects[0]
    result = apply_action(state, ActionRequest(action_type="resolve_effect", player_id=owner,
        expected_revision=state.revision, payload={"invocation_id": inv.invocation_id}))
    assert result.state.pending_choice.player_id == expected


@pytest.mark.parametrize("payload", [{"slot": "center"}, {"slot": "hand"}, {"slot": True}, {"slot": []},
    {"selected_card_instance_ids": ["opponent-secret"]}, {"selected_card_instance_id": "source-live"},
    {"ordered_card_instance_ids": ["player_2-center"]}, {"to_slot": "left"},
    {"target_player_id": "player_2"}, {"from_slot": "right"}])
def test_invalid_submissions_are_atomic(payload):
    state = _begin(_state()).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _choose(state, **payload))
    assert match_state_hash(state) == before


def test_other_player_and_duplicate_revision_cannot_move_first_player():
    state = _begin(_state()).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _choose(state, actor="player_2"))
    assert match_state_hash(state) == before
    action = _choose(state)
    first = apply_action(state, action).state
    with pytest.raises(StaleRevisionError):
        apply_action(first, action)
    assert first.players["player_2"].member_area["center"] == "player_2-center"


def test_first_move_is_public_before_next_choice_and_no_automatic_resolution_between():
    from test_moved_source_ready import _state as moved_state
    state = _state(occupied=True)
    moved = moved_state()
    state.effect_definitions.update(moved.effect_definitions)
    state.cards["player_1-center"].card = moved.cards["source-live"].card.model_copy(deep=True)
    state.cards["player_1-right"].card = moved.cards["source-live"].card.model_copy(deep=True)
    started = _begin(state).state
    first = apply_action(started, _choose(started))
    assert first.state.cards["player_1-center"].orientation == "wait"
    assert first.state.cards["player_1-right"].orientation == "wait"
    assert len([e for e in first.state.pending_effects if e.effect_id == "PL!SP-bp7-008:2"]) == 2
    for viewer in first.state.players:
        payload = _match_state_payload(first.state, events=first.events, legal_actions=first.legal_actions, player_id=viewer)
        assert payload["state"]["players"]["player_1"]["member_area"]["right"] == "player_1-center"
        assert payload["state"]["pending_choice"]["options"]["selections"]["player_1"]["to_slot"] == "right"
    final = apply_action(first.state, _choose(first.state))
    assert not final.state.pending_choice
    assert len(final.state.pending_effects) == 2
    assert final.state.cards["player_1-center"].orientation == "wait"
    while final.state.pending_effects:
        inv = final.state.pending_effects[0]
        final = apply_action(final.state, ActionRequest(action_type="resolve_effect", player_id=inv.player_id,
            expected_revision=final.state.revision, payload={"invocation_id": inv.invocation_id}))
    assert final.state.cards["player_1-center"].orientation == "active"
    assert final.state.cards["player_1-right"].orientation == "active"
    assert not final.state.pending_choice and not final.state.pending_effects


@pytest.mark.parametrize("action_type", ["manual_adjustment", "skip_effect"])
def test_selection_cannot_be_bypassed_to_replace_fixed_center(action_type):
    state = _begin(_state()).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, ActionRequest(action_type=action_type, player_id="player_1", expected_revision=state.revision,
            payload={"adjustments": [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "left"}],
                     "invocation_id": state.pending_effects[0].invocation_id}))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_four_ai_complete_both_choices_without_using_hidden_identity(policy, owner):
    state = _begin(_state(owner=owner), owner).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    while state.pending_choice:
        actor = state.pending_choice.player_id
        before = match_state_hash(state)
        decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={actor})
        assert isinstance(decision, SimpleAIDecision)
        changed = state.model_copy(deep=True)
        for key in ("tail", "opponent-secret"):
            card = changed.cards[key]
            card.card.name_ja = card.card.card_code = "HIDDEN-REPLACED"
            replacement = "hidden-" + key
            changed.cards[replacement] = changed.cards.pop(key).model_copy(update={"instance_id": replacement})
            for player in changed.players.values():
                player.hand = [replacement if item == key else item for item in player.hand]
                player.main_deck = [replacement if item == key else item for item in player.main_deck]
        assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={actor}) == decision
        assert match_state_hash(state) == before
        state = apply_action(state, decision.action).state
    assert not state.pending_effects


@pytest.mark.parametrize("zone", ["hand", "main_deck", "waiting_room", "member_right", "returned"])
def test_native_sql_source_departure_does_not_cancel_center_choices(tmp_path, zone):
    from test_moved_source_ready import _manual
    initial = _state()
    raw = _legacy_effect().model_dump(mode="json")
    raw["effect_id"] = "CONTROL"
    initial.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    initial.cards["source-live"].card.effect_ids.append("CONTROL")
    repo = MatchRepository(tmp_path / "departure.sqlite3")
    repo.create_match(initial, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(initial.match_id, _play(initial)).state
    control = next(i for i in played.pending_effects if i.effect_id == "CONTROL")
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live",
                "to_zone": "waiting_room" if zone == "returned" else zone}]
    if zone == "returned":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_right"})
    moved = repo.apply(initial.match_id, _manual(played, changes, control)).state
    inv = next(i for i in moved.pending_effects if i.effect_id == EFFECT)
    state = repo.apply(initial.match_id, ActionRequest(action_type="resolve_effect", player_id=inv.player_id,
        expected_revision=moved.revision, payload={"invocation_id": inv.invocation_id})).state
    for viewer in state.players:
        payload = _match_state_payload(state, events=[], legal_actions=generate_legal_actions(state), player_id=viewer)
        assert "tail" not in payload["state"]["cards"]
        if zone in {"hand", "main_deck"} and (viewer == "player_2" or zone == "main_deck"):
            assert "source-live" not in payload["state"]["cards"]
    while state.pending_choice:
        state = repo.apply(initial.match_id, _choose(state)).state
    assert state.players["player_1"].member_area["right"] == "player_1-center"
    assert state.players["player_2"].member_area["right"] == "player_2-center"
    assert repo.replay(initial.match_id)["final_state"] == state.model_dump(mode="json")


def test_legacy_manual_snapshot_still_uses_original_adjustment_sql(tmp_path):
    from test_moved_source_ready import _manual
    initial = _state()
    initial.effect_definitions[EFFECT] = _legacy_effect()
    repo = MatchRepository(tmp_path / "legacy.sqlite3")
    repo.create_match(initial, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(initial.match_id, _play(initial)).state
    inv = next(i for i in played.pending_effects if i.effect_id == EFFECT)
    final = repo.apply(initial.match_id, _manual(played, [
        {"adjustment_type": "position_change", "target_player_id": player_id,
         "from_slot": "center", "to_slot": "right"} for player_id in played.players], inv)).state
    assert not final.pending_effects
    assert repo.replay(initial.match_id)["final_state"] == final.model_dump(mode="json")


@pytest.mark.parametrize("change", [{"is_optional": True}, {"duration": "turn"}, {"condition": {"x": True}},
    {"actions": [{"action_type": "draw_cards", "amount": 1}]}, {"timing": "live_start"},
    {"frequency_limit": "turn1"}, {"trigger": "member_moved"}])
def test_new_policy_rejects_unbounded_snapshot_changes(change):
    from pydantic import ValidationError
    raw = _candidate(CODE).to_registry_entry()
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate({**raw, **change})


@pytest.mark.parametrize("field,value", [("text_revision_id", 216), ("raw_text_hash", "wrong"),
    ("card_code", "OTHER"), ("raw_effect_text_ja", "different")])
def test_generator_requires_exact_identity(field, value):
    from loveca.simulation.effect_candidates import _onplay_both_center_position
    candidate = _candidate(CODE)
    row = {"card_code": CODE, "text_revision_id": candidate.text_revision_id,
           "raw_text_hash": candidate.raw_text_hash, "raw_effect_text_ja": candidate.label_ja}
    assert _onplay_both_center_position(row) is not None
    assert _onplay_both_center_position({**row, **{field: value}}) is None


def test_forged_public_choice_marker_does_not_disclose_other_options():
    state = _begin(_state()).state
    state.effect_definitions[EFFECT] = _legacy_effect()
    state.pending_choice.options["selections"] = {"player_1": {"to_slot": "right", "secret": "opponent-secret"}}
    payload = _match_state_payload(state, events=[], legal_actions=generate_legal_actions(state), player_id="player_2")
    assert payload["state"]["pending_choice"]["options"] == {}


def test_semantic_provider_submits_only_own_destination():
    from tools.ai_sandbox.semantic_playtest import payload_example_for_action
    result = _begin(_state())
    action = next(item for item in result.legal_actions if item.action_type == "resolve_effect_choice")
    example = payload_example_for_action(action)
    assert example == {"slot": "left"}
    assert apply_action(result.state, _choose(result.state, **example)).state.pending_choice.player_id == "player_2"


def test_official_registry_matches_full_text_candidate():
    effect = next(e for e in load_effect_registry().effects if e.effect_id == EFFECT)
    assert effect == EffectDefinition.model_validate(_candidate(CODE).to_registry_entry())
    assert effect.simulation_support == "test_validated_executable"


def test_public_previous_destination_never_grants_hidden_card_identity():
    state = apply_action(_begin(_state()).state, _choose(_begin(_state()).state)).state
    state.pending_choice.options["selections"]["player_1"]["secret"] = "tail"
    payload = _match_state_payload(state, events=[], legal_actions=generate_legal_actions(state), player_id="player_1")
    assert payload["state"]["pending_choice"]["options"] == {"selections": {"player_1": {"to_slot": "right"}}}
    assert "tail" not in payload["state"]["cards"]
