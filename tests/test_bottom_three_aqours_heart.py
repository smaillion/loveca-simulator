import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_moved_source_ready import _manual
from test_nijigasaki_inspection import _candidate, _resolve
from test_nijigasaki_inspection import _state as _base_state

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, _member_heart_count, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, EffectInvocation
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!S-bp7-006"
EFFECT = CODE + ":1"
POLICY = "original_live_start_bottom_three_source"
RULE_REFERENCE_IDS = ("4.1.4", "4.8.2", "4.8.3", "9.7.7", "10.2.1", "10.2.2.1", "10.2.3", "8.4.11")


def _state(*, legacy=False, manual=False):
    state = _base_state(CODE)
    raw = _candidate(CODE).to_registry_entry()
    if legacy:
        raw.update(execution_mode="prompt_then_resolve", actions=[
            {"action_type": "mill_bottom_cards", "amount": 3},
            {"action_type": "gain_heart", "target": "source", "amount": 1, "color_slot": "heart04",
             "value": {"condition": {"milled_all_card_type": "member", "milled_all_work_key": "love_live_sunshine"}}},
        ])
    if manual:
        raw.update(execution_mode="manual_resolution", simulation_support="manual_resolution",
                   review_status="parsed_draft", actions=[{"action_type": "manual_resolution"}])
    state.effect_definitions[EFFECT] = EffectDefinition.model_validate(raw)
    p = state.players["player_1"]
    p.hand.remove("source-live")
    p.hand = []
    p.member_area["center"] = "source-live"
    p.main_deck = ["tail", "good-member", "cost", "blade-heart"]
    p.live_area = ["deck-live-1"]
    for key in ["good-member", "cost", "blade-heart"]:
        state.cards[key].card.work_keys = ["love_live_sunshine"]
        state.cards[key].card.unit_keys = ["guilty_kiss"]
    state.phase = "performance_first"
    state.stage_departure_policy = "clear_departed_card_modifiers"
    state.effect_order_policy = "ap_nap_player_choice"
    return state


def _advance(state):
    return ActionRequest(action_type="advance_phase", player_id="player_1", expected_revision=state.revision)


def _pending(**kwargs):
    state = _state(**kwargs)
    state.pending_effects = [EffectInvocation(invocation_id="bottom-three", effect_id=EFFECT,
        source_card_instance_id="source-live", player_id="player_1", trigger_event="live_started",
        trigger_data={"original_source_stage_object": True, "_condition_checked_at_trigger": True})]
    return state


def _event(result):
    return next(e for e in result.events if e.event_type == "effect_bottom_aqours_heart_resolved")


def _control(*, legacy=False):
    state = _state(legacy=legacy)
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id="CONTROL", frequency_limit="none", execution_mode="manual_resolution",
               simulation_support="manual_resolution", actions=[{"action_type": "manual_resolution"}])
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    card = state.cards["wrong-work"].model_copy(deep=True)
    card.instance_id, card.card.effect_ids = "observer", ["CONTROL"]
    state.cards["observer"] = card
    state.players["player_1"].member_area["left"] = "observer"
    return state


@pytest.mark.parametrize("movement", ["leave", "return", "position"])
@pytest.mark.parametrize("legacy_departure", [False, True])
def test_native_source_interference_and_sql_replay(tmp_path, movement, legacy_departure):
    state = _control()
    if legacy_departure:
        state.stage_departure_policy = None
    repo = MatchRepository(tmp_path / "source.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    started = repo.apply(state.match_id, _advance(state)).state
    invocation = next(i for i in started.pending_effects if i.effect_id == "CONTROL")
    if movement == "position":
        changes = [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "right"}]
    else:
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"}]
        if movement == "return":
            changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_right"})
    final = repo.apply(state.match_id, _manual(started, changes, invocation))
    if final.state.pending_effects:
        final = repo.apply(state.match_id, _resolve(final.state))
    assert final.state.players["player_1"].waiting_room[-3:] == ["blade-heart", "cost", "good-member"]
    assert len(final.state.players["player_1"].manual_modifiers) == int(movement == "position")
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


def test_exact_binding_native_order_and_only_source_heart():
    state = _state()
    for player in state.players.values():
        zones = [player.main_deck, player.energy_deck, player.hand, player.energy_area,
                 player.live_area, player.waiting_room, player.resolution_area, player.success_live_area,
                 [item for item in player.member_area.values() if item]]
        ids = [item for zone in zones for item in zone]
        assert len(ids) == len(set(ids))
    before = match_state_hash(state)
    result = apply_action(state, _advance(state))
    assert match_state_hash(state) == before
    effect = result.state.effect_definitions[EFFECT]
    assert (effect.text_revision_id, effect.raw_text_hash) == (
        851, "3c87d290b7b11b30c7b72683a74b6ec5a871266062a46567c1c8258fe5198821")
    assert _event(result).data["condition_met"] is True
    assert result.state.players["player_1"].main_deck == ["tail"]
    assert result.state.players["player_1"].waiting_room == ["blade-heart", "cost", "good-member"]
    assert _member_heart_count(result.state, "player_1", "source-live", "heart04") == 2
    modifier = result.state.players["player_1"].manual_modifiers[0]
    assert (modifier.target_card_instance_id, modifier.color_slot, modifier.amount, modifier.duration) == ("source-live", "heart04", 1, "live")
    assert modifier.value == {"policy": POLICY} and not result.state.pending_effects


@pytest.mark.parametrize("card_type,work,units,delta", [
    ("member", ["love_live_sunshine"], [], 1),
    ("member", ["nijigasaki", "love_live_sunshine"], ["other"], 1),
    ("member", ["nijigasaki"], ["aqours"], 0),
    ("live", ["love_live_sunshine"], [], 0),
    ("energy", ["love_live_sunshine"], [], 0),
    ("member", [], ["guilty_kiss"], 0),
])
def test_actual_moves_require_member_and_aqours_work_not_unit(card_type, work, units, delta):
    state = _pending()
    state.cards["cost"].card.card_type = card_type
    state.cards["cost"].card.work_keys = work
    state.cards["cost"].card.unit_keys = units
    # The top and pre-existing waiting cards are not part of this condition.
    state.players["player_1"].waiting_room = ["wrong-work"]
    result = apply_action(state, _resolve(state))
    assert _event(result).data["heart_delta"] == delta


@pytest.mark.parametrize("deck,waiting,refreshes,moves", [
    ([], [], 0, []),
    (["cost"], [], 3, ["cost"] * 3),
    ([], ["cost"], 4, ["cost"] * 3),
    (["cost", "good-member"], [], 1, None),
    (["cost", "good-member", "blade-heart"], [], 1, ["blade-heart", "good-member", "cost"]),
])
def test_short_deck_refresh_tracks_moves_not_unique_ids(tmp_path, deck, waiting, refreshes, moves):
    state = _pending()
    state.players["player_1"].main_deck, state.players["player_1"].waiting_room = deck, waiting
    repo = MatchRepository(tmp_path / "short.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repo.apply(state.match_id, _resolve(state))
    milled = [x for e in result.events if e.event_type == "effect_cards_milled" for x in e.data["milled_card_instance_ids"]]
    if moves is not None:
        assert milled == moves
    assert _event(result).data["milled_count"] == (3 if deck or waiting else 0)
    assert _event(result).data["heart_delta"] == int(bool(deck or waiting))
    assert result.state.players["player_1"].refresh_count == refreshes
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True
    if len(deck) == 1:
        names = [e.event_type for e in result.events]
        assert names.index("effect_cards_milled") < names.index("deck_refreshed") < names.index("effect_bottom_aqours_heart_resolved")


def test_last_refresh_does_not_replace_original_move_condition():
    state = _pending()
    state.players["player_1"].main_deck = ["cost", "good-member", "blade-heart"]
    state.players["player_1"].waiting_room = ["wrong-work"]
    result = apply_action(state, _resolve(state))
    assert _event(result).data["heart_delta"] == 1
    assert result.state.players["player_1"].waiting_room == []
    assert set(result.state.players["player_1"].main_deck) == {"cost", "good-member", "blade-heart", "wrong-work"}


@pytest.mark.parametrize("legacy_departure", [False, True])
def test_departure_after_grant_and_native_live_end_clear_only_new_heart(legacy_departure):
    initial = _state()
    if legacy_departure:
        initial.stage_departure_policy = None
    state = apply_action(initial, _advance(initial)).state
    left = apply_action(state, _manual(state, [
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"},
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_right"},
    ]))
    assert not left.state.players["player_1"].manual_modifiers
    state = apply_action(_state(), _advance(_state())).state
    state.phase = "live_judgment"
    assert not apply_action(state, _advance(state)).state.players["player_1"].manual_modifiers


@pytest.mark.parametrize("legacy,manual", [(False, False), (True, False), (False, True)])
def test_new_old_structured_and_manual_sql_snapshots(tmp_path, legacy, manual):
    state = _state(legacy=legacy, manual=manual)
    repo = MatchRepository(tmp_path / "snapshot.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repo.apply(state.match_id, _advance(state))
    if manual:
        result = repo.apply(state.match_id, _manual(result.state, [{"adjustment_type": "set_flag", "flag": "old", "duration": "game"}], result.state.pending_effects[0]))
    if legacy:
        assert result.state.players["player_1"].manual_modifiers[0].value is None
        assert not any(e.event_type == "effect_bottom_aqours_heart_resolved" for e in result.events)
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("pending", [False, True])
def test_four_ai_native_and_pending_hidden_identity_invariance(policy, pending):
    state = _pending() if pending else _state()
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    legal = generate_legal_actions(state)
    decision = controller.choose_action(state, legal, controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision) and match_state_hash(state) == before
    changed = state.model_copy(deep=True)
    for key in ["opponent-secret", *state.players["player_1"].main_deck]:
        changed.cards[key].card.card_code = changed.cards[key].card.name_ja = "HIDDEN-CHANGED"
        changed.cards[key].card.basic_hearts = {"heart06": 99}
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}).action == decision.action
    assert _event(apply_action(state, decision.action)).data["heart_delta"] == 1


def test_public_move_history_does_not_authorize_refreshed_current_card_map():
    state = _pending()
    state.players["player_1"].main_deck = ["good-member"]
    state.players["player_1"].waiting_room = ["wrong-work"]
    result = apply_action(state, _resolve(state))
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        visible = payload["state"]["cards"]
        assert not set(result.state.players["player_1"].main_deck).intersection(visible)
        history = [c for e in payload["events"] for c in e["data"].get("revealed_cards", [])]
        assert len(history) == 3
        assert all(c["card_code"].startswith("AUDIT-") for c in history)
        assert "opponent-secret" not in json.dumps(payload) if viewer == "player_1" else True


def test_dual_view_bottom_public_top_and_opponent_hand_hidden():
    result = apply_action(_state(), _advance(_state()))
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        assert {"blade-heart", "cost", "good-member"}.issubset(payload["state"]["cards"])
        assert "AUDIT-tail" not in json.dumps(payload) and "tail" not in json.dumps(payload)
        if viewer == "player_1":
            assert "opponent-secret" not in json.dumps(payload)


@pytest.mark.parametrize("zone", ["hand", "waiting_room", "main_deck"])
def test_source_outside_stage_does_not_trigger(zone):
    state = _state()
    state.players["player_1"].member_area["center"] = None
    getattr(state.players["player_1"], zone).append("source-live")
    result = apply_action(state, _advance(state))
    assert not any(e.event_type == "effect_bottom_aqours_heart_resolved" for e in result.events)


def test_no_live_attempt_does_not_trigger():
    state = _state()
    state.players["player_1"].live_area = []
    assert not any(e.event_type == "effect_bottom_aqours_heart_resolved" for e in apply_action(state, _advance(state)).events)


@pytest.mark.parametrize("orientation", ["active", "wait"])
def test_source_wait_does_not_cancel_trigger(orientation):
    state = _state()
    state.cards["source-live"].orientation = orientation
    assert _event(apply_action(state, _advance(state))).data["heart_delta"] == 1


@pytest.mark.parametrize("defect", ["missing_snapshot", "opponent", "decline"])
def test_bad_resolution_atomic(defect):
    state = _pending()
    if defect == "missing_snapshot":
        state.pending_effects[0].trigger_data.clear()
    action = _resolve(state, accepted=defect != "decline")
    if defect == "opponent":
        action.player_id = "player_2"
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, action)
    assert match_state_hash(state) == before


@pytest.mark.parametrize("changes", [{"amount": 2}, {"color_slot": "heart02"}, {"target": "self"}, {"source_object_policy": None}])
def test_bounded_operation(changes):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw["actions"][0].update(changes)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("changes", [{"is_optional": True}, {"duration": "turn"}, {"frequency_limit": "none"},
    {"condition": {"minimum_energy": 1}}, {"trigger": "member_played"}, {"execution_mode": "prompt_then_resolve"}])
def test_bounded_definition(changes):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(changes)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("change", [{"card_code": "OTHER"}, {"text_revision_id": 852}, {"raw_text_hash": "wrong"},
    {"raw_effect_text_ja": "【ライブ開始時】自分のデッキの下からカードを3枚控え室に置く。"}])
def test_exact_generator_rejects_variants(change):
    from loveca.simulation.effect_candidates import BOTTOM_THREE_AQOURS_HEART_TEXT, _live_start_bottom_three_aqours_heart
    row = {"card_code": CODE, "text_revision_id": 851, "raw_effect_text_ja": BOTTOM_THREE_AQOURS_HEART_TEXT,
           "raw_text_hash": _state().effect_definitions[EFFECT].raw_text_hash}
    assert _live_start_bottom_three_aqours_heart({**row, **change}) is None


def test_new_operation_is_not_a_cost():
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(cost=raw["actions"], actions=[{"action_type": "draw_card", "amount": 1}])
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("matching", [False, True])
def test_second_performer_only_uses_own_bottom_and_source(matching):
    state = _state()
    if not matching:
        state.cards["cost"].card.card_type = "live"
    first, second = state.players["player_1"], state.players["player_2"]
    state.players["player_1"], state.players["player_2"] = second, first
    for key, player in state.players.items():
        player.player_id = key
    for card in state.cards.values():
        card.owner_id = "player_2" if card.owner_id == "player_1" else "player_1"
    state.phase, state.active_player_id = "performance_second", "player_2"
    result = apply_action(state, ActionRequest(action_type="advance_phase", player_id="player_2", expected_revision=state.revision))
    assert _event(result).player_id == "player_2"
    assert _event(result).data["heart_delta"] == int(matching)
    assert not result.state.players["player_1"].manual_modifiers


def test_historical_structured_source_return_keeps_original_sql_behavior(tmp_path):
    state = _control(legacy=True)
    repo = MatchRepository(tmp_path / "historical-return.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    started = repo.apply(state.match_id, _advance(state)).state
    control = next(i for i in started.pending_effects if i.effect_id == "CONTROL")
    moved = repo.apply(state.match_id, _manual(started, [
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"},
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_right"},
    ], control))
    if moved.state.pending_effects:
        moved = repo.apply(state.match_id, _resolve(moved.state))
    # Historical Replay keeps the former behavior; only the new policy fixes it.
    assert len(moved.state.players["player_1"].manual_modifiers) == 1
    assert moved.state.players["player_1"].manual_modifiers[0].value is None
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True
