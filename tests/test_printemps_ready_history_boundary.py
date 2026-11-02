from contextlib import closing
from functools import lru_cache
from pathlib import Path

import pytest
from test_water_blue_bottom_heart import _state as _base_state
from test_bottom_one_aqours_requirement import _exclusive
from test_mirakura_front_position_boundary import _swap_roles

from loveca.db.bootstrap import connect_database
from loveca.simulation.ai import SimpleAIBlocker, SimpleAIController, SimpleAIPolicy
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, CardDefinition, CardInstance
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!-pb2-010"
EFFECT = CODE + ":1"
READY = "PL!-pb1-028:1"
RULE_REFERENCE_IDS = ("1.3.2.1", "4.1.4", "4.5.5.2", "9.6.2.4.2", "9.7.7", "9.11.1", "9.12.2")


@lru_cache
def _definitions():
    definitions = {e.effect_id: e for e in load_effect_registry().effects
                   if e.card_code in {CODE, "PL!-pb1-028", "PL!-pb1-012", "PL!-bp3-005"}}
    # Historical boundary snapshots used Kotori's legacy ready operation.
    effect = definitions["PL!-pb1-012:1"]
    definitions[effect.effect_id] = effect.model_copy(update={"actions": [effect.actions[0].model_copy(update={"action_type": "ready_member"})],
                                                           "choice": effect.choice.model_copy(update={"orientation": "wait"})})
    ready = definitions[READY].model_dump(mode="json")
    ready["actions"] = [{"action_type": "ready_member", "target": "self_stage_unit", "value": {"unit_key": "printemps"}},
                        {"action_type": "modify_score", "amount": 1,
                         "value": {"condition": {"effect_ready_member_count_at_least": 3}}}]
    ready["duration"] = "live"
    definitions[READY] = EffectDefinition.model_validate(ready)
    return definitions


def _state(*, waits=0, members=3, owner="player_1", ready=False, control=False, duplicate=False):
    state = _base_state()
    state.effect_definitions = {k: e.model_copy(deep=True) for k, e in _definitions().items()}
    for item in state.cards.values():
        item.card.effect_ids = []
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        state.cards["source-live"].card = _load_definition(db, CODE, None, state.effect_definitions, {})
        if ready:
            state.cards["live-1"].card = _load_definition(db, "PL!-pb1-028", None, state.effect_definitions, {})
    p = state.players["player_1"]
    ids = ["source-live", "target", "wrong-work"]
    p.live_area = ["live-1"]
    p.member_area = {slot: ids[i] if i < members else None for i, slot in enumerate(["left", "center", "right"])}
    p.member_area_attachments = {"left": [], "center": [], "right": []}
    p.hand = [i for i in p.hand if i not in ids + ["live-1"]] + ids[members:]
    for index, key in enumerate(ids):
        state.cards[key].orientation = "wait" if index < waits else "active"
        if key != "source-live":
            state.cards[key].card.work_keys = ["love_live"]
            state.cards[key].card.unit_keys = ["printemps"]
    if duplicate:
        state.cards["target"].card = state.cards["source-live"].card.model_copy(deep=True)
    if control:
        raw = state.effect_definitions[EFFECT].model_dump(mode="json")
        raw.update(effect_id="CONTROL", frequency_limit="none", label_ja="AUDIT CONTROL only")
        state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
        state.cards["live-1"].card.effect_ids.append("CONTROL")
    if owner == "player_2":
        state = _swap_roles(state)
        state.phase, state.active_player_id = "performance_second", owner
    _exclusive(state)
    return state


def _advance(state):
    return ActionRequest(action_type="advance_phase", player_id=state.active_player_id, expected_revision=state.revision)


def _resolve(state, effect=EFFECT, **extra):
    inv = next(i for i in state.pending_effects if i.effect_id == effect)
    return ActionRequest(action_type="resolve_effect", player_id=inv.player_id, expected_revision=state.revision,
                         payload={"invocation_id": inv.invocation_id, **extra})


def _manual(state, effect, changes):
    inv = next(i for i in state.pending_effects if i.effect_id == effect)
    return ActionRequest(action_type="manual_adjustment", player_id=inv.player_id, expected_revision=state.revision,
        payload={"reason": "AUDIT only, not automatic adjudication", "source_invocation_id": inv.invocation_id,
                 "source_effect_id": inv.effect_id, "source_card_instance_id": inv.source_card_instance_id,
                 "adjustments": [{"target_player_id": inv.player_id, **c} for c in changes]})


def _repo(state, tmp_path):
    repo = MatchRepository(tmp_path / "audit.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    return repo


def _replay(repo, state):
    _exclusive(state)
    for p in state.players.values():
        for zone in [p.main_deck, p.energy_deck, p.energy_area, p.hand, p.waiting_room, p.live_area,
                     p.resolution_area, p.success_live_area, [i for i in p.member_area.values() if i], *p.member_area_attachments.values()]:
            assert all(i in state.cards for i in zone)
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == state.model_dump(mode="json")


def test_identity_and_manual_registration_are_not_promoted():
    state = _state()
    card = state.cards["source-live"].card
    assert (card.name_ja, card.cost, card.blade) == ("高坂穂乃果", 7, 1)
    assert (card.text_revision_id, card.raw_text_hash) == (983, "327d07177662f55cdc206df19152fa63fada6d2cb037ee3e61aa7537f658a9b1")
    assert card.unit_keys == ["printemps"] and card.work_keys == ["love_live"]
    effect = state.effect_definitions[EFFECT]
    assert effect.execution_mode == effect.simulation_support == "manual_resolution"
    assert [a.action_type for a in effect.actions] == ["manual_resolution"]
    candidate = next(c for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True) if c.effect_id == EFFECT)
    assert candidate.simulation_support == "manual_resolution"


@pytest.mark.parametrize("members,waits", [(1, 0), (1, 1), (3, 0), (3, 1), (3, 3)])
def test_native_live_start_never_guesses_from_current_orientation(members, waits):
    state = _state(members=members, waits=waits)
    before = match_state_hash(state)
    result = apply_action(state, _advance(state))
    assert match_state_hash(state) == before
    assert [i.effect_id for i in result.state.pending_effects] == [EFFECT]
    assert not result.state.players["player_1"].manual_modifiers
    assert not any(e.event_type == "effect_auto_resolved" for e in result.events)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("waits", [0, 1, 3])
def test_official_printemps_ready_records_only_work_boolean_not_target_count_sql(tmp_path, owner, waits):
    state = _state(owner=owner, waits=waits, ready=True)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _resolve(current, READY))
    assert all(result.state.cards[i].orientation == "active" for i in ["source-live", "target", "wrong-work"])
    flags = result.state.players[owner].effect_ready_flags_this_turn
    assert flags == (["love_live:member"] if waits else [])
    assert not any("printemps" in flag or "target" in flag for flag in flags)
    assert [i.effect_id for i in result.state.pending_effects] == [EFFECT]
    assert not any(m.modifier_type == "blade" for m in result.state.players[owner].manual_modifiers)
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("code", ["PL!-pb1-012", "PL!-bp3-005"])
def test_native_printemps_and_lily_white_ready_share_same_work_flag_sql(tmp_path, owner, code):
    state = _state(members=1, waits=1)
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        card = _load_definition(db, code, None, state.effect_definitions, {})
    state.cards["ready-source"] = state.cards["target"].model_copy(update={"instance_id": "ready-source", "card": card}, deep=True)
    p = state.players["player_1"]
    p.hand.append("ready-source")
    for index in range(card.cost):
        key = f"payment-{index}"
        state.cards[key] = CardInstance(instance_id=key, owner_id="player_1",
            card=CardDefinition(card_code="AUDIT-ENERGY", card_id="AUDIT-ENERGY", name_ja="AUDIT", card_type="energy"))
        p.energy_area.append(key)
    state.phase, state.active_player_id = "first_main", "player_1"
    if owner == "player_2":
        state = _swap_roles(state)
    repo = _repo(state, tmp_path)
    played = repo.apply(state.match_id, ActionRequest(action_type="play_member", player_id=owner, expected_revision=0,
        payload={"card_instance_id": "ready-source", "slot": "right", "use_baton_touch": False,
                 "energy_instance_ids": state.players[owner].energy_area[:card.cost]}))
    result = played if not played.state.pending_effects else repo.apply(state.match_id,
        _resolve(played.state, code + ":1", selected_card_instance_ids=["source-live"]))
    assert result.state.cards["source-live"].orientation == "active"
    assert result.state.cards["ready-source"].card.unit_keys == (["printemps"] if code == "PL!-pb1-012" else ["lily_white"])
    assert result.state.players[owner].effect_ready_flags_this_turn == ["love_live:member"]
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("movement", ["hand", "main_deck", "return", "position", "empty_stage"])
def test_source_movement_keeps_real_manual_handle_and_private_faces_sql(tmp_path, owner, movement):
    state = _state(owner=owner, control=True)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    if movement == "position":
        changes = [{"adjustment_type": "position_change", "from_slot": "left", "to_slot": "right"}]
    else:
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live",
                    "to_zone": "main_deck" if movement == "main_deck" else "hand"}]
        if movement == "return":
            changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_left"})
        if movement == "empty_stage":
            changes += [{"adjustment_type": "move_card", "target_card_instance_id": key, "to_zone": "hand"} for key in ["target", "wrong-work"]]
    result = repo.apply(state.match_id, _manual(current, "CONTROL", changes))
    for viewer in [owner, "player_1" if owner == "player_2" else "player_2"]:
        before = match_state_hash(result.state)
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        assert match_state_hash(result.state) == before
        for p in result.state.players.values():
            assert not any(i in payload["state"]["cards"] for i in p.main_deck)
            if p.player_id != viewer:
                assert not any(i in payload["state"]["cards"] for i in p.hand)
        if movement == "main_deck" or (movement in {"hand", "empty_stage"} and viewer != owner):
            assert "source-live" not in payload["state"]["cards"]
        if viewer == owner:
            legal = next(a for a in payload["legal_actions"] if a["action_type"] == "manual_adjustment")
            assert legal["options"]["source_invocations"][0]["source_card_instance_id"] == "source-live"
    if movement == "empty_stage":
        assert not any(result.state.players[owner].member_area.values())
    final = repo.apply(state.match_id, _manual(result.state, EFFECT,
        [{"adjustment_type": "set_flag", "flag": "AUDIT-manual-only", "duration": "turn"}])).state
    assert not final.pending_effects
    assert not any(m.modifier_type == "blade" for m in final.players[owner].manual_modifiers)
    _replay(repo, final)


@pytest.mark.parametrize("movement", ["hand", "return", "position", "wait"])
def test_ready_target_object_history_is_not_encoded_by_existing_flag_sql(tmp_path, movement):
    state = _state(ready=True, waits=3, control=True)
    if movement == "wait":
        raw = state.effect_definitions["CONTROL"].model_dump(mode="json")
        raw.update(execution_mode="prompt_then_resolve", simulation_support="test_validated_executable",
                   choice={"choice_type": "member_from_stage", "zone": "stage", "card_type": "member", "minimum": 1, "maximum": 1},
                   actions=[{"action_type": "apply_wait_member", "target": "selected"}])
        state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    current = repo.apply(state.match_id, _resolve(current, READY)).state
    if movement == "position":
        changes = [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "right"}]
    elif movement == "wait":
        changes = []
    else:
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": "target", "to_zone": "hand"}]
        if movement == "return":
            changes.append({"adjustment_type": "move_card", "target_card_instance_id": "target", "to_zone": "member_center"})
    result = repo.apply(state.match_id, _resolve(current, "CONTROL", selected_card_instance_ids=["target"])
                        if movement == "wait" else _manual(current, "CONTROL", changes))
    assert result.state.players["player_1"].effect_ready_flags_this_turn == ["love_live:member"]
    assert [i.effect_id for i in result.state.pending_effects] == [EFFECT]
    assert not any(m.modifier_type == "blade" for m in result.state.players["player_1"].manual_modifiers)
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_both_sources_do_not_guess_from_flags_or_hidden_identities(owner, policy):
    state = _state(owner=owner, duplicate=True)
    state.players[owner].effect_ready_flags_this_turn = ["love_live:member"]
    current = apply_action(state, _advance(state)).state
    assert len(current.pending_effects) == 2
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(current)
    decision = controller.choose_action(current, generate_legal_actions(current), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIBlocker) and decision.reason == "no_safe_ai_action"
    changed = current.model_copy(deep=True)
    for p in changed.players.values():
        for key in list(p.main_deck + (p.hand if p.player_id != owner else [])):
            item = changed.cards.pop(key)
            name = "hidden-" + key
            item.instance_id = name
            item.card.name_ja = item.card.card_code = "HIDDEN"
            item.card.blade = 99
            changed.cards[name] = item
            p.main_deck = [name if i == key else i for i in p.main_deck]
            p.hand = [name if i == key else i for i in p.hand]
    changed_before = match_state_hash(changed)
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner}) == decision
    assert match_state_hash(current) == before
    assert match_state_hash(changed) == changed_before


@pytest.mark.parametrize("wrong_owner", [False, True])
def test_structured_automatic_bypass_is_atomic(wrong_owner):
    state = _state()
    current = apply_action(state, _advance(state)).state
    action = _resolve(current, accepted=True, selected_card_instance_ids=["target"])
    if wrong_owner:
        action.player_id = "player_2"
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        apply_action(current, action)
    assert match_state_hash(current) == before
