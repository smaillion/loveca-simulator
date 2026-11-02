import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_moved_source_ready import _manual
from test_nijigasaki_inspection import _candidate, _play, _resolve
from test_nijigasaki_inspection import _state as _base_state

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effect_candidates import BOTH_WAITING_LIVE_FULL_TEXT, BOTH_WAITING_LIVE_TEXT, _onplay_both_waiting_live
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, EffectInvocation
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!N-bp4-007"
EFFECT = CODE + ":1"
RULE_REFERENCE_IDS = ("1.3.4", "1.3.4.1", "7.2.1.1", "7.2.1.2", "9.6.3.1", "9.6.3.1.3", "9.7.7")


def _state(first=2, second=2, *, legacy=False):
    state = _base_state(CODE, legacy=legacy)
    if legacy:
        raw = state.effect_definitions[EFFECT].model_dump(mode="json")
        raw.update(actions=[{"action_type": "manual_resolution"}], review_status="parsed_draft",
                   source_reference="Official card text; timing-only manual fallback pending structured effect modeling")
        state.effect_definitions[EFFECT] = EffectDefinition.model_validate(raw)
    state.effect_order_policy = "ap_nap_player_choice"
    for player_id, count in (("player_1", first), ("player_2", second)):
        player = state.players[player_id]
        player.waiting_room = []
        for i in range(count):
            key = f"{player_id}-live-{i}"
            card = state.cards["good-live"].model_copy(deep=True)
            card.instance_id = key
            card.owner_id = player_id
            card.card.card_code = card.card.card_id = card.card.name_ja = "AUDIT-" + key
            card.card.score = i + 1
            state.cards[key] = card
            player.waiting_room.append(key)
        key = player_id + "-not-live"
        card = state.cards["good-member"].model_copy(deep=True)
        card.instance_id, card.owner_id = key, player_id
        state.cards[key] = card
        player.waiting_room.append(key)
    return state


def _begin(first=2, second=2):
    state = _state(first, second)
    played = apply_action(state, _play(state)).state
    return apply_action(played, _resolve(played))


def _choose(state, selected, *, player=None):
    return ActionRequest(action_type="resolve_effect_choice", player_id=player or state.pending_choice.player_id,
        expected_revision=state.revision, payload={"selected_card_instance_ids": selected})


def _settle(state):
    while state.pending_choice is not None:
        ids = state.pending_choice.options["candidate_card_instance_ids"]
        state = apply_action(state, _choose(state, ids[:1])).state
    return state


def test_exact_full_card_binding_and_only_first_segment_changes():
    state = _state()
    effect = state.effect_definitions[EFFECT]
    assert effect == EffectDefinition.model_validate(_candidate(CODE).to_registry_entry())
    assert (effect.text_revision_id, effect.raw_text_hash) == (363, "7076ae1f8dd1872704b75e15e069471bcc1d8ee6dcf21abb1b2cd4521ed3fe94")
    assert effect.label_ja == BOTH_WAITING_LIVE_TEXT
    assert state.cards["source-live"].card.raw_effect_text_ja == BOTH_WAITING_LIVE_FULL_TEXT
    siblings = [e for e in load_effect_registry().effects if e.card_code == CODE and e.effect_index > 1]
    assert [e.actions[0].action_type for e in siblings] == ["gain_heart", "place_energy_from_deck"]
    assert [e.label_ja for e in siblings] == BOTH_WAITING_LIVE_FULL_TEXT.split(" ")[1:]


@pytest.mark.parametrize("first", [0, 1, 2])
@pytest.mark.parametrize("second", [0, 1, 2])
def test_actual_onplay_each_player_recovers_exactly_one_when_possible(first, second):
    result = _begin(first, second)
    if first == second == 0:
        assert result.state.pending_choice is None and not result.state.pending_effects
    final = _settle(result.state)
    for player_id, count in (("player_1", first), ("player_2", second)):
        player = final.players[player_id]
        assert sum(item.startswith(player_id + "-live-") for item in player.hand) == int(count > 0)
        assert len(player.waiting_room) == max(0, count - 1) + 1
        assert player_id + "-not-live" in player.waiting_room
    assert not final.pending_effects


def test_first_public_selection_is_known_before_simultaneous_movement():
    result = _begin()
    state = result.state
    assert state.pending_choice.player_id == "player_1"
    first = apply_action(state, _choose(state, ["player_1-live-0"]))
    assert "player_1-live-0" in first.state.players["player_1"].waiting_room
    assert "player_1-live-0" not in first.state.players["player_1"].hand
    assert first.state.pending_choice.player_id == "player_2"
    public = _match_state_payload(first.state, events=first.events, legal_actions=first.legal_actions, player_id="player_2")
    assert public["state"]["pending_choice"]["options"]["selections"]["player_1"]["selected_card_instance_ids"] == ["player_1-live-0"]
    selected = next(e for e in public["events"] if e["event_type"] == "effect_public_waiting_live_selected")
    assert selected["data"]["revealed_cards"][0]["instance_id"] == "player_1-live-0"
    final = apply_action(first.state, _choose(first.state, ["player_2-live-1"]))
    assert "player_1-live-0" in final.state.players["player_1"].hand
    assert "player_2-live-1" in final.state.players["player_2"].hand
    assert sum(e.event_type == "effect_waiting_lives_recovered" for e in final.events) == 1


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("phase,expected", [("first_main", "player_1"), ("second_main", "player_2"),
                                            ("live_set_second", "player_1"), ("live_judgment", "player_1")])
@pytest.mark.parametrize("legacy_order", [False, True])
def test_rule_active_player_not_source_owner_or_ui_active_pointer(owner, phase, expected, legacy_order):
    state = _state()
    state.players["player_1"].hand.remove("source-live")
    state.cards["source-live"].owner_id = owner
    state.players[owner].member_area["center"] = "source-live"
    state.phase, state.active_player_id = phase, "player_2"
    if legacy_order:
        state.effect_order_policy = None
    state.pending_effects = [EffectInvocation(invocation_id="isolated", effect_id=EFFECT,
        source_card_instance_id="source-live", player_id=owner, trigger_event="member_played")]
    result = apply_action(state, ActionRequest(action_type="resolve_effect", player_id=owner,
        expected_revision=state.revision, payload={"invocation_id": "isolated"}))
    assert result.state.pending_choice.player_id == expected


@pytest.mark.parametrize("selected", [[], ["player_2-live-0"], ["player_1-not-live"],
    ["player_1-live-0", "player_1-live-0"], ["player_1-live-0", "player_1-live-1"], [123], None])
def test_illegal_public_selection_is_atomic(selected):
    state = _begin().state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _choose(state, selected))
    assert match_state_hash(state) == before


def test_cannot_choose_for_other_player_or_mutate_cards_between_choices():
    state = _begin().state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _choose(state, ["player_2-live-0"], player="player_2"))
    with pytest.raises(IllegalActionError, match="public recovery"):
        apply_action(state, _manual(state, [{"adjustment_type": "move_card", "target_card_instance_id": "player_1-live-0", "to_zone": "hand"}]))
    assert match_state_hash(state) == before


def test_stale_original_selection_rejects_final_movement_atomically():
    state = _begin().state
    state = apply_action(state, _choose(state, ["player_1-live-0"])).state
    state.players["player_1"].waiting_room.remove("player_1-live-0")
    state.players["player_1"].hand.append("player_1-live-0")
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError, match="original public recovery"):
        apply_action(state, _choose(state, ["player_2-live-0"]))
    assert match_state_hash(state) == before


def test_private_other_hands_and_tails_stay_hidden_while_known_choices_have_public_history():
    state = _begin().state
    first = apply_action(state, _choose(state, ["player_1-live-0"]))
    final = apply_action(first.state, _choose(first.state, ["player_2-live-0"]))
    for viewer, opponent in (("player_1", "player_2"), ("player_2", "player_1")):
        p = _match_state_payload(final.state, events=final.events, legal_actions=final.legal_actions, player_id=viewer)
        assert opponent + "-live-0" not in p["state"]["cards"]
        assert "tail" not in json.dumps(p) and "AUDIT-tail" not in json.dumps(p)
        if viewer == "player_1":
            assert "opponent-secret" not in json.dumps(p)
        else:
            assert "AUDIT-cost" not in json.dumps(p)
        event = next(e for e in p["events"] if e["event_type"] == "effect_waiting_lives_recovered")
        assert len(event["data"]["revealed_cards"]) == 2


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("counts", [(0, 0), (0, 2), (2, 0), (2, 2)])
def test_four_ai_owners_choices_hidden_identity_invariance_and_no_input_mutation(policy, counts):
    state = _state(*counts)
    state = apply_action(state, _play(state)).state
    ai = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    for _ in range(3):
        if not state.pending_effects and state.pending_choice is None:
            break
        legal = generate_legal_actions(state)
        before = match_state_hash(state)
        decision = ai.choose_action(state, legal, controlled_player_ids=set(state.players))
        assert isinstance(decision, SimpleAIDecision) and match_state_hash(state) == before
        changed = state.model_copy(deep=True)
        secret = "opponent-secret" if decision.action.player_id == "player_1" else "cost"
        changed.cards[secret].card.card_code = "HIDDEN-CHANGED"
        changed.cards["tail"].card.card_code = "TAIL-CHANGED"
        assert ai.choose_action(changed, generate_legal_actions(changed), controlled_player_ids=set(state.players)).action == decision.action
        state = apply_action(state, decision.action).state
    assert not state.pending_effects and state.pending_choice is None


@pytest.mark.parametrize("counts", [(0, 0), (0, 2), (2, 0), (2, 2)])
def test_native_sql_replay_each_candidate_matrix(tmp_path, counts):
    state = _state(*counts)
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state)).state
    current = repo.apply(state.match_id, _resolve(played))
    while current.state.pending_choice:
        ids = current.state.pending_choice.options["candidate_card_instance_ids"]
        current = repo.apply(state.match_id, _choose(current.state, ids[:1]))
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == current.state.model_dump(mode="json")


def test_old_manual_sql_snapshot_does_not_gain_multi_player_choices(tmp_path):
    state = _state(legacy=True)
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state)).state
    final = repo.apply(state.match_id, _manual(played, [{"adjustment_type": "move_card", "target_card_instance_id": "player_1-live-0", "to_zone": "hand"}], played.pending_effects[0]))
    assert final.state.pending_choice is None
    assert "player_2-live-0" in final.state.players["player_2"].waiting_room
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("returning", [False, True])
def test_native_pending_source_departure_does_not_cancel_both_recoveries(tmp_path, returning):
    state = _state()
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id="CONTROL", trigger="own_member_played", choice=None,
               execution_mode="manual_resolution", simulation_support="manual_resolution",
               actions=[{"action_type": "manual_resolution"}])
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    observer = state.cards["good-member"].model_copy(deep=True)
    observer.instance_id = "observer"
    observer.card.effect_ids = ["CONTROL"]
    state.cards[observer.instance_id] = observer
    state.players["player_1"].member_area["left"] = observer.instance_id
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state)).state
    control = next(i for i in played.pending_effects if i.effect_id == "CONTROL")
    adjustments = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"}]
    if returning:
        adjustments.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_right"})
    moved = repo.apply(state.match_id, _manual(played, adjustments, control)).state
    current = repo.apply(state.match_id, _resolve(moved))
    while current.state.pending_choice:
        if not returning and current.state.pending_choice.player_id == "player_2":
            payload = _match_state_payload(current.state, events=current.events,
                legal_actions=current.legal_actions, player_id="player_2")
            assert "source-live" not in payload["state"]["cards"]
            assert "source-live" not in json.dumps(payload)
        current = repo.apply(state.match_id, _choose(current.state, current.state.pending_choice.options["candidate_card_instance_ids"][:1]))
    assert "player_1-live-0" in current.state.players["player_1"].hand
    assert "player_2-live-0" in current.state.players["player_2"].hand
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == current.state.model_dump(mode="json")


def test_forged_marker_cannot_upgrade_old_multi_player_snapshot():
    from test_multi_player_entry import _state as old_state, _begin as old_begin
    state = old_begin(old_state())
    state.pending_choice.options["multi_player_choice_type"] = "multi_player_waiting_live_recovery"
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError, match="actual snapshot definition"):
        apply_action(state, _choose(state, []))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("changes", [{"minimum": 0}, {"maximum": 2}, {"card_type": "member"},
    {"target_player": "opponent"}, {"selection_policy": None}, {"selected_destination": "waiting_room"}])
def test_snapshot_choice_is_narrow(changes):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw["choice"].update(changes)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("changes", [{"is_optional": True}, {"duration": "live"}, {"trigger": "live_started"}])
def test_snapshot_definition_is_narrow(changes):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(changes)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("changes", [{"card_code": "OTHER"}, {"text_revision_id": 364}, {"raw_text_hash": "changed"},
    {"raw_effect_text_ja": BOTH_WAITING_LIVE_FULL_TEXT + "カードを1枚引く。"}])
def test_generator_binds_full_card_not_prefix(changes):
    row = {"card_code": CODE, "text_revision_id": 363, "raw_text_hash": _state().effect_definitions[EFFECT].raw_text_hash,
           "raw_effect_text_ja": BOTH_WAITING_LIVE_FULL_TEXT}
    assert _onplay_both_waiting_live({**row, **changes}) is None
