from contextlib import closing
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_aqours_blade_six_score import _state as _live_state
from test_moved_source_ready import _manual

from loveca.db.bootstrap import connect_database
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import apply_action, _effective_required_hearts
from loveca.simulation.models import ActionRequest, EffectInvocation, ManualModifier
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository

CODE = "PL!S-bp7-020"
EFFECT = CODE + ":2"
POLICY = "original_live_start_bottom_aqours_requirement"
RULE_REFERENCE_IDS = ("2.11.3", "4.1.4", "9.2.1.2", "9.7.7", "9.9.1.4", "9.9.1.5", "10.2.1", "10.2.2.1", "10.2.3")


@lru_cache
def _candidate():
    return next(c for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
                if c.effect_id == EFFECT)


def _state(*, kind="member", work=True, legacy=False):
    raw = deepcopy(_candidate().to_registry_entry())
    if legacy:
        raw.update(actions=[{"action_type": "manual_resolution"}], execution_mode="manual_resolution",
                   simulation_support="manual_resolution", review_status="parsed_draft", duration=None)
    effect = EffectDefinition.model_validate(raw)
    state = _live_state()
    state.effect_definitions = {EFFECT: effect}
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        state.cards["source-live"].card = _load_definition(connection, CODE, None, {EFFECT: effect}, {})
    p = state.players["player_1"]
    for key in ["bottom", "tail"]:
        state.cards[key] = state.cards["target"].model_copy(update={"instance_id": key}, deep=True)
        state.cards[key].card.effect_ids = []
        state.cards[key].face_up = False
    state.cards["bottom"].card.card_type = kind
    state.cards["bottom"].card.work_keys = ["love_live_sunshine"] if work else ["love_live"]
    state.cards["bottom"].card.unit_keys = ["aqours"]
    p.main_deck = ["tail", "bottom"]
    p.waiting_room = []
    p.member_area_attachments = {"left": [], "center": [], "right": []}
    state.stage_departure_policy = "clear_departed_card_modifiers"
    _exclusive(state)
    return state


def _advance(state):
    return ActionRequest(action_type="advance_phase", player_id=state.active_player_id, expected_revision=state.revision)


def _pending(**kwargs):
    state = _state(**kwargs)
    state.pending_effects = [EffectInvocation(invocation_id="bottom-one", effect_id=EFFECT,
        source_card_instance_id="source-live", player_id="player_1", trigger_event="live_started",
        trigger_data={"original_source_live_object": True, "_condition_checked_at_trigger": True})]
    return state


def _resolve(state):
    inv = next(i for i in state.pending_effects if i.effect_id == EFFECT)
    return ActionRequest(action_type="resolve_effect", player_id=inv.player_id, expected_revision=state.revision,
                         payload={"invocation_id": inv.invocation_id, "accepted": True})


def _event(result):
    return next(e.data for e in result.events if e.event_type == "effect_bottom_aqours_requirement_resolved")


def _requirements(state, key="source-live"):
    return _effective_required_hearts(state.players["player_1"], key, state.cards[key].card.required_hearts)


def test_native_live_start_only_reduces_original_live_generic_requirement():
    state = _state()
    before = match_state_hash(state)
    result = apply_action(state, _advance(state))
    assert match_state_hash(state) == before
    assert _event(result)["required_heart_delta"] == -1
    assert _requirements(result.state) == {"heart0": 2, "heart02": 1, "heart04": 2, "heart05": 2}
    assert _requirements(result.state, "live-1") == _requirements(state, "live-1")
    assert result.state.players["player_1"].main_deck == ["tail"]
    modifier = result.state.players["player_1"].manual_modifiers[-1]
    assert modifier.duration == "game" and modifier.value == {"policy": POLICY}


@pytest.mark.parametrize("kind,work,expected", [("member", True, -1), ("member", False, 0), ("live", True, 0), ("live", False, 0)])
def test_actual_bottom_type_and_work_not_unit(kind, work, expected):
    state = _pending(kind=kind, work=work)
    result = apply_action(state, _resolve(state))
    assert _event(result)["required_heart_delta"] == expected
    assert _event(result)["milled_count"] == 1
    assert result.state.players["player_1"].waiting_room == ["bottom"]


@pytest.mark.parametrize("deck,waiting", [([], []), (["bottom"], []), ([], ["bottom"]), (["tail", "bottom"], ["held"])])
def test_empty_and_one_card_refresh_sql(tmp_path, deck, waiting):
    state = _pending()
    p = state.players["player_1"]
    p.main_deck, p.waiting_room = deck, waiting
    if "held" in waiting:
        p.hand.remove("held")
    repo = MatchRepository(tmp_path / "short.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repo.apply(state.match_id, _resolve(state))
    assert _event(result)["milled_count"] == int(bool(deck or waiting))
    assert _event(result)["required_heart_delta"] == -int(bool(deck or waiting))
    if deck == ["bottom"]:
        names = [e.event_type for e in result.events]
        assert names.index("effect_cards_milled") < names.index("deck_refreshed") < names.index("effect_bottom_aqours_requirement_resolved")
    if not deck and waiting:
        assert sum(e.event_type == "deck_refreshed" for e in result.events) == 2
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


def _control():
    state = _state()
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id="CONTROL", actions=[{"action_type": "manual_resolution"}],
               execution_mode="manual_resolution", simulation_support="manual_resolution", frequency_limit="none")
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    state.cards["live-1"].card.effect_ids = ["CONTROL"]
    return state


@pytest.mark.parametrize("movement", ["hand", "main_deck", "return", "same_area"])
@pytest.mark.parametrize("old_policy", [False, True])
def test_native_source_interference_sql(tmp_path, movement, old_policy):
    state = _control()
    if old_policy:
        state.stage_departure_policy = None
    repo = MatchRepository(tmp_path / "source.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    begun = repo.apply(state.match_id, _advance(state)).state
    inv = next(i for i in begun.pending_effects if i.effect_id == "CONTROL")
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live",
                "to_zone": "live_area" if movement == "same_area" else "main_deck" if movement == "main_deck" else "hand"}]
    if movement == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "live_area"})
    result = repo.apply(state.match_id, _manual(begun, changes, inv))
    if result.state.pending_effects:
        result = repo.apply(state.match_id, _resolve(result.state))
    assert _event(result)["milled_count"] == 1
    assert _event(result)["required_heart_delta"] == (-1 if movement == "same_area" else 0)
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")


@pytest.mark.parametrize("old_policy", [False, True])
def test_game_duration_is_not_live_duration_but_departure_clears_only_new_marker(old_policy):
    from loveca.simulation.engine import _expire_modifiers, _on_live_card_departure
    state = apply_action(_state(), _advance(_state())).state
    p = state.players["player_1"]
    if old_policy:
        state.stage_departure_policy = None
    p.manual_modifiers.append(ManualModifier(modifier_id="legacy", modifier_type="required_heart", amount=-1,
        color_slot="heart0", duration="game", target_card_instance_id="source-live", created_turn=state.turn_number))
    _expire_modifiers(state, "player_1", "live", [])
    assert len(p.manual_modifiers) == 2
    _on_live_card_departure(state, "player_1", "source-live")
    assert [m.modifier_id for m in p.manual_modifiers] == ["legacy"]


def test_replacement_then_additive_and_no_colored_underflow():
    state = _pending()
    p = state.players["player_1"]
    p.manual_modifiers.append(ManualModifier(modifier_id="replace", modifier_type="required_heart", duration="game",
        target_card_instance_id="source-live", created_turn=state.turn_number,
        value={"mode": "replace", "required_hearts": {"heart02": 2}}))
    result = apply_action(state, _resolve(state))
    assert _requirements(result.state) == {"heart02": 2}
    assert all(m.modifier_type != "heart" for m in result.state.players["player_1"].manual_modifiers)


@pytest.mark.parametrize("change", [{"amount": 2}, {"color_slot": "heart02"}, {"target": "all"}, {"amount_source": "selected_count"}, {"source_object_policy": None}])
def test_bounded_operation(change):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw["actions"][0].update(change)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("change", [{"duration": "live"}, {"is_optional": True}, {"frequency_limit": "none"}, {"trigger": "member_played"}, {"condition": {"stage_member_count_at_least": 1}}, {"execution_mode": "prompt_then_resolve"}])
def test_bounded_definition(change):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(change)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


def test_cost_rejected_and_missing_snapshot_atomic():
    from loveca.simulation.engine import IllegalActionError
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(cost=raw["actions"], actions=[])
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)
    state = _pending()
    state.pending_effects[0].trigger_data.pop("original_source_live_object")
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("field,value", [("card_code", "OTHER"), ("text_revision_id", 913), ("raw_text_hash", "bad"), ("raw_effect_text_ja", "bad")])
def test_exact_generator_binding(field, value):
    from loveca.simulation.effect_candidates import _live_start_bottom_aqours_requirement
    c = _candidate()
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        text = connection.execute("SELECT raw_effect_text_ja FROM card_text_revisions WHERE id=912").fetchone()[0]
    row = {"card_code": CODE, "text_revision_id": 912, "raw_text_hash": c.raw_text_hash, "raw_effect_text_ja": text}
    assert _live_start_bottom_aqours_requirement(row) is not None
    assert _live_start_bottom_aqours_requirement({**row, field: value}) is None


def test_legacy_manual_sql(tmp_path):
    state = _pending(legacy=True)
    repo = MatchRepository(tmp_path / "old.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    inv = state.pending_effects[0]
    result = repo.apply(state.match_id, _manual(state, [{"adjustment_type": "set_flag", "flag": "legacy", "duration": "turn"}], inv))
    assert not any(e.event_type == "effect_bottom_aqours_requirement_resolved" for e in result.events)
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


def _exclusive(state):
    for p in state.players.values():
        ids = [x for z in [p.main_deck, p.energy_deck, p.hand, p.energy_area, p.waiting_room, p.resolution_area,
                          p.live_area, p.success_live_area, [x for x in p.member_area.values() if x],
                          *p.member_area_attachments.values()] for x in z]
        assert len(ids) == len(set(ids))


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_native_both_owners_sql_and_live_end_departure(tmp_path, owner):
    state = _state()
    if owner == "player_2":
        state.players["player_1"], state.players["player_2"] = state.players["player_2"], state.players["player_1"]
        for key, p in state.players.items():
            p.player_id = key
        for c in state.cards.values():
            c.owner_id = "player_2" if c.owner_id == "player_1" else "player_1"
        state.phase, state.active_player_id = "performance_second", "player_2"
    _exclusive(state)
    repo = MatchRepository(tmp_path / "owners.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repo.apply(state.match_id, _advance(state))
    _exclusive(result.state)
    assert _event(result)["required_heart_delta"] == -1
    assert result.state.players[owner].manual_modifiers[-1].target_card_instance_id == "source-live"
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


def test_actual_live_end_zone_departure_clears_game_object_modifier():
    state = apply_action(_state(), _advance(_state())).state
    state.phase = "live_judgment"
    result = apply_action(state, _advance(state))
    if result.state.pending_choice:
        result = apply_action(result.state, ActionRequest(action_type="resolve_live_requirements", player_id="player_1",
            expected_revision=result.state.revision, payload={"success_live_instance_id": "source-live"}))
    assert "source-live" not in result.state.players["player_1"].live_area
    assert not any(m.value == {"policy": POLICY} for m in result.state.players["player_1"].manual_modifiers)


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("pending", [False, True])
def test_four_ai_actual_action_and_hidden_identity_invariance(policy, pending):
    from loveca.simulation.ai import SimpleAIController, SimpleAIPolicy, SimpleAIDecision
    from loveca.simulation.engine import generate_legal_actions
    state = _pending() if pending else _state()
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision) and before == match_state_hash(state)
    changed = state.model_copy(deep=True)
    for key in ["secret", *state.players["player_1"].main_deck]:
        changed.cards[key].card.card_code = changed.cards[key].card.name_ja = "HIDDEN-CHANGED"
        changed.cards[key].card.blade = 99
        renamed = "hidden-" + key
        changed.cards[renamed] = changed.cards.pop(key)
        changed.cards[renamed].instance_id = renamed
        for p in changed.players.values():
            p.main_deck = [renamed if item == key else item for item in p.main_deck]
            p.hand = [renamed if item == key else item for item in p.hand]
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}).action == decision.action
    assert _event(apply_action(state, decision.action))["required_heart_delta"] == -1


@pytest.mark.parametrize("short", [False, True])
def test_complete_dual_view_keeps_hidden_tail_and_refreshed_current_map_private(short):
    import json
    from loveca.webapp import _match_state_payload
    state = _pending()
    if short:
        state.players["player_1"].main_deck = ["bottom"]
    result = apply_action(state, _resolve(state))
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        assert "tail" not in json.dumps(payload)
        assert "secret" not in payload["state"]["cards"] if viewer == "player_1" else "held" not in payload["state"]["cards"]
        if short:
            assert "bottom" not in payload["state"]["cards"]
        else:
            assert "bottom" in payload["state"]["cards"]


def test_native_post_resolution_departure_return_clears_only_new_policy_sql(tmp_path):
    state = apply_action(_state(), _advance(_state())).state
    state.stage_departure_policy = None
    repo = MatchRepository(tmp_path / "depart.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repo.apply(state.match_id, _manual(state, [
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"},
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "live_area"},
    ]))
    assert _requirements(result.state) == state.cards["source-live"].card.required_hearts
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


def test_official_both_segments_queue_first_stays_manual_sql(tmp_path):
    from loveca.simulation.effects import load_effect_registry
    registry = load_effect_registry()
    definitions = {e.effect_id: e for e in registry.effects if e.card_code == CODE}
    assert definitions[CODE + ":1"].execution_mode == "manual_resolution"
    assert definitions[CODE + ":1"].simulation_support == "manual_resolution"
    assert [op.action_type for op in definitions[CODE + ":1"].actions] == ["manual_resolution"]
    state = _state()
    state.effect_definitions = definitions
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        state.cards["source-live"].card = _load_definition(connection, CODE, None, definitions, {})
    repo = MatchRepository(tmp_path / "both.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    begun = repo.apply(state.match_id, _advance(state)).state
    assert {i.effect_id for i in begun.pending_effects} == {CODE + ":1", EFFECT}
    result = repo.apply(state.match_id, _resolve(begun))
    assert _event(result)["required_heart_delta"] == -1
    assert [i.effect_id for i in result.state.pending_effects] == [CODE + ":1"]
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True
