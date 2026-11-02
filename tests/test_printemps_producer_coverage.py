from contextlib import closing
from pathlib import Path

import pytest
from test_nijigasaki_inspection import _state as _entry_state, _play
from test_bottom_one_aqours_requirement import _exclusive
from test_mirakura_front_position_boundary import _swap_roles

from loveca.db.bootstrap import connect_database
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, CardDefinition, CardInstance
from loveca.simulation.online import match_state_hash
from test_printemps_ready_history_boundary import _repo, _replay, _manual
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.ready_history import OPERATION, current_effect_readied_members
from loveca.webapp import _match_state_payload

CODE = "PL!-pb1-012"
EFFECT = CODE + ":1"
PRODUCERS = {"PL!-PR-001:1", "PL!-bp3-001:2", "PL!-bp6-008:1", EFFECT, "PL!-pb1-028:1"}


def _producer_inventory():
    definitions = {e.effect_id: e for e in load_effect_registry().effects}
    rows = []
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        for code in sorted({e.card_code for e in definitions.values()
                            if any(a.action_type in {"ready_member", "ready_member_with_provenance_v1", "ready_member_after_source_wait_provenance_v2"} for a in e.actions)}):
            card = _load_definition(db, code, None, definitions, {})
            if "printemps" not in card.unit_keys:
                continue
            rows.extend({"card": card.model_dump(mode="json"), "effect": e.model_dump(mode="json")}
                for e in definitions.values() if e.card_code == code
                and any(a.action_type in {"ready_member", "ready_member_with_provenance_v1", "ready_member_after_source_wait_provenance_v2"} for a in e.actions))
    return rows


def _legacy_hanayo(effect):
    raw = effect.model_dump(mode="json")
    raw["actions"] = [{"action_type": "ready_member"}]
    raw["choice"]["orientation"] = "wait"
    raw["condition"] = {"source_zone": "stage", "source_orientation": "active"}
    return EffectDefinition.model_validate(raw)


def _state(*, owner="player_1", targets="both", legacy=False, control=False):
    state = _entry_state(CODE)
    effect = state.effect_definitions[EFFECT]
    # This audit fixture preserves the pre-provenance v2 snapshot.
    effect = effect.model_copy(update={"actions": [effect.actions[0].model_copy(update={"action_type": "ready_member"})],
                                     "choice": effect.choice.model_copy(update={"orientation": "wait"})})
    state.effect_definitions[EFFECT] = effect
    if legacy:
        raw = effect.model_dump(mode="json")
        raw["choice"]["unit_key"] = None
        state.effect_definitions[EFFECT] = EffectDefinition.model_validate(raw)
    p = state.players["player_1"]
    p.member_area = {"left": None, "center": None, "right": None}
    p.member_area_attachments = {"left": [], "center": [], "right": []}
    for key, slot, unit in [("good-target", "left", "printemps"), ("wrong-target", "right", "bibi")]:
        state.cards[key] = CardInstance(instance_id=key, owner_id="player_1", orientation="wait",
            card=CardDefinition(card_code="AUDIT-" + key, card_id="AUDIT-" + key, name_ja="AUDIT-" + key,
                                card_type="member", cost=4, blade=1, unit_keys=[unit], work_keys=["love_live"]))
        if targets == "both" or (targets == "good" and unit == "printemps") or (targets == "wrong" and unit == "bibi") or targets == "two-good":
            p.member_area[slot] = key
        else:
            p.hand.append(key)
    if targets == "two-good":
        state.cards["wrong-target"].card.unit_keys = ["printemps"]
        state.cards["wrong-target"].card.name_ja = state.cards["good-target"].card.name_ja
    if control:
        raw = effect.model_dump(mode="json")
        raw.update(effect_id="CONTROL", actions=[{"action_type": "manual_resolution"}], choice=None,
                   execution_mode="manual_resolution", simulation_support="manual_resolution", is_optional=False)
        state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
        state.cards["source-live"].card.effect_ids.append("CONTROL")
    if owner == "player_2":
        state = _swap_roles(state)
    _exclusive(state)
    return state


def _play_for(state):
    action = _play(state)
    action.player_id = state.active_player_id
    action.payload["energy_instance_ids"] = state.players[action.player_id].energy_area
    return action


def _resolve(state, ids):
    inv = next(i for i in state.pending_effects if i.effect_id == EFFECT)
    return ActionRequest(action_type="resolve_effect", player_id=inv.player_id, expected_revision=state.revision,
        payload={"invocation_id": inv.invocation_id, "selected_card_instance_ids": ids})


def test_native_kotori_must_not_ready_non_printemps_red():
    initial = _state()
    current = apply_action(initial, _play_for(initial)).state
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        apply_action(current, _resolve(current, ["wrong-target"]))
    assert match_state_hash(current) == before


def test_native_kotori_candidates_exclude_non_printemps_red():
    initial = _state()
    result = apply_action(initial, _play_for(initial))
    action = next(a for a in result.legal_actions if a.action_type == "resolve_effect")
    inv = next(i for i in action.options["invocations"] if i["effect_id"] == EFFECT)
    assert inv["candidate_card_instance_ids"] == ["good-target"]


def test_inventory_uses_real_source_unit_and_does_not_promote_consumer():
    rows = _producer_inventory()
    assert {r["effect"]["effect_id"] for r in rows} == PRODUCERS
    assert all("printemps" in r["card"]["unit_keys"] for r in rows)
    assert all(r["card"]["raw_text_hash"] == r["effect"]["raw_text_hash"] for r in rows)
    assert all(r["card"]["text_revision_id"] == r["effect"]["text_revision_id"] for r in rows)
    assert {r["effect"]["effect_id"] for r in rows if OPERATION in [a["action_type"] for a in r["effect"]["actions"]]} == {EFFECT, "PL!-bp3-001:2", "PL!-pb1-028:1"}
    assert any("Printemps" not in r["effect"]["label_ja"] for r in rows)
    consumer = next(e for e in load_effect_registry().effects if e.effect_id == "PL!-pb2-010:1")
    assert consumer.simulation_support == "manual_resolution"


def test_exact_generator_binding_rejects_changed_identity():
    from loveca.simulation.effect_candidates import _onplay_ready_printemps_member_up_to1
    card = _state().cards["source-live"].card
    row = {"card_code": CODE, "raw_effect_text_ja": card.raw_effect_text_ja,
           "raw_text_hash": card.raw_text_hash, "text_revision_id": card.text_revision_id}
    candidate = _onplay_ready_printemps_member_up_to1(row)
    assert candidate.choice["unit_key"] == "printemps"
    assert candidate.pattern_id.endswith("_provenance_v3")
    for key, value in [("card_code", "OTHER"), ("raw_effect_text_ja", "OTHER"),
                       ("raw_effect_text_ja", " " + card.raw_effect_text_ja),
                       ("raw_text_hash", "OTHER"), ("text_revision_id", 428)]:
        assert _onplay_ready_printemps_member_up_to1(dict(row, **{key: value})) is None


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("targets", ["none", "wrong", "good", "both", "two-good"])
def test_native_candidates_and_optional_zero_or_one_sql(tmp_path, owner, targets):
    state = _state(owner=owner, targets=targets)
    before = match_state_hash(state)
    repo = _repo(state, tmp_path)
    played = repo.apply(state.match_id, _play_for(state))
    assert match_state_hash(state) == before
    current = played.state
    if current.pending_effects:
        legal = next(a for a in generate_legal_actions(current) if a.action_type == "resolve_effect")
        inv = next(i for i in legal.options["invocations"] if i["effect_id"] == EFFECT)
        expected = ([] if targets in {"none", "wrong"} else ["good-target"]) + (["wrong-target"] if targets == "two-good" else [])
        assert inv["candidate_card_instance_ids"] == expected
        current = repo.apply(state.match_id, _resolve(current, expected[:1])).state
        assert current.cards["good-target"].orientation == ("active" if expected else "wait")
    assert current.member_ready_history is None
    _replay(repo, current)


@pytest.mark.parametrize("legacy", [False, True])
def test_old_snapshot_replays_old_unfiltered_behavior_not_correct_rules_sql(tmp_path, legacy):
    state = _state(legacy=legacy)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state)).state
    current = repo.apply(state.match_id, _resolve(current, ["wrong-target"] if legacy else [])).state
    assert current.cards["wrong-target"].orientation == ("active" if legacy else "wait")
    assert "member_ready_history" not in current.model_dump(mode="json")
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("movement", ["hand", "main_deck", "return", "position"])
def test_source_interference_does_not_change_current_target_unit_sql(tmp_path, owner, movement):
    state = _state(owner=owner, control=True)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state)).state
    if movement == "position":
        changes = [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "right"}]
    else:
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "main_deck" if movement == "main_deck" else "hand"}]
        if movement == "return":
            changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_center"})
    moved = repo.apply(state.match_id, _manual(current, "CONTROL", changes)).state
    result = repo.apply(state.match_id, _resolve(moved, ["good-target"]))
    assert result.state.cards["good-target"].orientation == "active"
    assert result.state.cards["wrong-target"].orientation == "wait"
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        for p in result.state.players.values():
            assert not any(i in payload["state"]["cards"] for i in p.main_deck)
            if p.player_id != viewer:
                assert not any(i in payload["state"]["cards"] for i in p.hand)
        if movement in {"main_deck", "hand"} and (movement == "main_deck" or viewer != owner):
            assert "source-live" not in payload["state"]["cards"]
    _replay(repo, result.state)


@pytest.mark.parametrize("ids", [["wrong-target"], ["good-target", "good-target"], ["good-target", "wrong-target"], ["missing"]])
def test_illegal_target_submissions_are_atomic(ids):
    initial = _state()
    state = apply_action(initial, _play_for(initial)).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, ids))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_actual_selection_hidden_invariance(owner, policy):
    initial = _state(owner=owner)
    state = apply_action(initial, _play_for(initial)).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    assert set(decision.action.payload.get("selected_card_instance_ids", [])) <= {"good-target"}
    changed = state.model_copy(deep=True)
    for p in changed.players.values():
        for key in list(p.main_deck + (p.hand if p.player_id != owner else [])):
            item = changed.cards.pop(key)
            name = "HIDDEN-" + key
            item.instance_id = name
            item.card.name_ja = item.card.card_code = "HIDDEN"
            changed.cards[name] = item
            p.main_deck = [name if i == key else i for i in p.main_deck]
            p.hand = [name if i == key else i for i in p.hand]
    changed_before = match_state_hash(changed)
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner}).action == decision.action
    assert match_state_hash(state) == before and match_state_hash(changed) == changed_before
    result = apply_action(state, decision.action).state
    assert not result.pending_effects and result.cards["wrong-target"].orientation == "wait"


def test_actual_cost_producer_cannot_be_blindly_upgraded():
    from pydantic import ValidationError
    row = next(r for r in _producer_inventory() if r["effect"]["effect_id"] == "PL!-bp6-008:1")
    raw = _legacy_hanayo(EffectDefinition.model_validate(row["effect"])).model_dump(mode="json")
    assert raw["cost"] and raw["choice"]["exclude_source"]
    raw["actions"][0]["action_type"] = OPERATION
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


def test_legacy_producer_is_unknown_not_zero_in_opted_in_snapshot():
    from test_member_ready_provenance import _state as _probe_state, _advance
    state = _probe_state()
    from test_printemps_ready_history_boundary import _definitions
    legacy = _definitions()["PL!-pb1-028:1"].model_dump(mode="json")
    state.effect_definitions[legacy["effect_id"]] = EffectDefinition.model_validate(legacy)
    state.cards["live-1"].card.effect_ids.append(legacy["effect_id"])
    current = apply_action(state, _advance(state)).state
    inv = next(i for i in current.pending_effects if i.effect_id == legacy["effect_id"])
    result = apply_action(current, ActionRequest(action_type="resolve_effect", player_id=inv.player_id, expected_revision=current.revision,
        payload={"invocation_id": inv.invocation_id})).state
    assert result.member_ready_history.coverage_complete is False
    assert current_effect_readied_members(result, "player_1", unit_key="printemps") is None


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_actual_hanayo_cost_then_other_non_printemps_target_sql(tmp_path, owner):
    state = _state(owner=owner)
    defs = {e.effect_id: e for e in load_effect_registry().effects}
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        state.cards["good-target"].card = _load_definition(db, "PL!-bp6-008", None, defs, {})
    state.cards["good-target"].orientation = "active"
    state.effect_definitions["PL!-bp6-008:1"] = _legacy_hanayo(defs["PL!-bp6-008:1"])
    repo = _repo(state, tmp_path)
    result = repo.apply(state.match_id, ActionRequest(action_type="activate_effect", player_id=owner,
        expected_revision=state.revision, payload={"effect_id": "PL!-bp6-008:1", "source_card_instance_id": "good-target",
                "energy_instance_ids": []}))
    current = result.state
    if current.pending_effects:
        inv = next(i for i in current.pending_effects if i.effect_id == "PL!-bp6-008:1")
        current = repo.apply(state.match_id, ActionRequest(action_type="resolve_effect", player_id=owner, expected_revision=current.revision,
            payload={"invocation_id": inv.invocation_id, "selected_card_instance_ids": ["wrong-target"]})).state
    assert current.cards["good-target"].orientation == "wait"
    assert current.cards["wrong-target"].orientation == "active"
    assert current.member_ready_history is None
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_actual_departed_source_is_outside_prototype_initial_capture_sql(tmp_path, owner):
    from loveca.simulation.ready_history import prepare_ready_source
    state = _state(owner=owner)
    defs = {e.effect_id: e for e in load_effect_registry().effects}
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        state.cards["good-target"].card = _load_definition(db, "PL!-PR-001", None, defs, {})
    state.effect_definitions["PL!-PR-001:1"] = defs["PL!-PR-001:1"]
    # Native Baton moves the original source before its leave-stage trigger resolves.
    play = _play_for(state)
    play.payload.update(slot="left", use_baton_touch=True, energy_instance_ids=[])
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, play).state
    inv = next(i for i in current.pending_effects if i.effect_id == "PL!-PR-001:1")
    assert "good-target" in current.players[owner].waiting_room
    probe = current.model_copy(deep=True)
    raw = probe.effect_definitions[inv.effect_id].model_dump(mode="json")
    raw["actions"][0]["action_type"] = OPERATION
    probe.effect_definitions[inv.effect_id] = EffectDefinition.model_validate(raw)
    before = match_state_hash(probe)
    with pytest.raises(ValueError, match="original Stage or Live source"):
        prepare_ready_source(probe, next(i for i in probe.pending_effects if i.effect_id == inv.effect_id))
    assert match_state_hash(probe) == before
    current = repo.apply(state.match_id, ActionRequest(action_type="resolve_effect", player_id=owner, expected_revision=current.revision,
        payload={"invocation_id": inv.invocation_id, "accepted": True, "selected_card_instance_ids": ["wrong-target"]})).state
    assert current.cards["wrong-target"].orientation == "active" and current.member_ready_history is None
    _replay(repo, current)
