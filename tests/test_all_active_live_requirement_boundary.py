from contextlib import closing
from functools import lru_cache
from pathlib import Path

import pytest
from test_bottom_one_aqours_requirement import _state as _bottom_state, _exclusive
from test_mirakura_front_position_boundary import _swap_roles

from loveca.db.bootstrap import connect_database
from loveca.simulation.ai import SimpleAIBlocker, SimpleAIController, SimpleAIPolicy
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!S-bp7-020"
EFFECT = CODE + ":1"
SECOND = CODE + ":2"
RULE_REFERENCE_IDS = ("4.1.4", "4.5.5.2", "9.2.1.2", "9.6.2.4.2", "9.7.7")


@lru_cache
def _definitions():
    return {e.effect_id: e for e in load_effect_registry().effects if e.card_code == CODE}


def _state(*, count=3, waits=0, owner="player_1", control=False, both=False):
    state = _bottom_state()
    state.effect_definitions = {key: e.model_copy(deep=True) for key, e in _definitions().items()}
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        state.cards["source-live"].card = _load_definition(connection, CODE, None, state.effect_definitions, {})
    if not both:
        state.cards["source-live"].card.effect_ids = [EFFECT]
    p = state.players["player_1"]
    ids = ["target", "wrong-work", "held"]
    p.member_area = {slot: ids[i] if i < count else None for i, slot in enumerate(["left", "center", "right"])}
    p.hand = ids[count:]
    for i, key in enumerate(ids):
        state.cards[key].orientation = "wait" if i < waits else "active"
    if count:
        p.member_area_attachments["left"] = ["attached"]
    if control:
        raw = state.effect_definitions[EFFECT].model_dump(mode="json")
        raw.update(effect_id="CONTROL", label_ja="AUDIT CONTROL", frequency_limit="none")
        state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
        state.cards["live-1"].card.effect_ids = ["CONTROL"]
    _exclusive(state)
    if owner == "player_2":
        state = _swap_roles(state)
        state.phase, state.active_player_id = "performance_second", owner
    return state


def _advance(state):
    return ActionRequest(action_type="advance_phase", player_id=state.active_player_id, expected_revision=state.revision)


def _manual(state, invocation, changes):
    return ActionRequest(action_type="manual_adjustment", player_id=invocation.player_id, expected_revision=state.revision,
        payload={"reason": "AUDIT unresolved ability, not automatic adjudication",
                 "source_invocation_id": invocation.invocation_id, "source_effect_id": invocation.effect_id,
                 "source_card_instance_id": invocation.source_card_instance_id,
                 "adjustments": [{"target_player_id": invocation.player_id, **c} for c in changes]})


def test_exact_identity_and_both_existing_registrations_are_preserved():
    state = _state(both=True)
    card = state.cards["source-live"].card
    assert (card.text_revision_id, card.raw_text_hash) == (912,
        "2762be94925766143618a17b7a60b0cb252f776311eaf3f8198af0c49a60d046")
    assert card.effect_ids == [EFFECT, SECOND] and not card.effect_registry_errors
    first, second = state.effect_definitions[EFFECT], state.effect_definitions[SECOND]
    assert first.execution_mode == first.simulation_support == "manual_resolution"
    assert [a.action_type for a in first.actions] == ["manual_resolution"]
    assert second.actions[0].action_type == "mill_bottom_one_aqours_source_requirement"
    assert second.duration == "game"
    candidate = next(c for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
                     if c.effect_id == EFFECT)
    assert candidate.simulation_support == "manual_resolution"


@pytest.mark.parametrize("count,waits", [(0, 0), (1, 0), (1, 1), (3, 0), (3, 1), (3, 3)])
def test_native_live_start_does_not_adjudicate_any_stage_shape(count, waits):
    state = _state(count=count, waits=waits)
    before = match_state_hash(state)
    result = apply_action(state, _advance(state))
    assert match_state_hash(state) == before
    _exclusive(result.state)
    assert [i.effect_id for i in result.state.pending_effects] == [EFFECT]
    assert not result.state.players["player_1"].manual_modifiers
    assert result.state.players["player_1"].main_deck == state.players["player_1"].main_deck
    assert not any(e.event_type == "effect_auto_resolved" for e in result.events)
    assert len([x for x in result.state.players["player_1"].member_area.values() if x]) == count
    # Attached cards are separate from top-level Members; no truth value is assigned to the condition here.
    assert bool(result.state.players["player_1"].member_area_attachments["left"]) == bool(count)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("movement", ["hand", "main_deck", "return", "same_area"])
def test_native_source_interference_keeps_manual_handle_and_sql(tmp_path, owner, movement):
    state = _state(owner=owner, control=True)
    repo = MatchRepository(tmp_path / "manual-source.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    begun = repo.apply(state.match_id, _advance(state)).state
    ctrl = next(i for i in begun.pending_effects if i.effect_id == "CONTROL")
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live",
                "to_zone": "live_area" if movement == "same_area" else "main_deck" if movement == "main_deck" else "hand"}]
    if movement == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "live_area"})
    result = repo.apply(state.match_id, _manual(begun, ctrl, changes))
    inv = next(i for i in result.state.pending_effects if i.effect_id == EFFECT)
    assert not result.state.players[owner].manual_modifiers
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        if movement == "main_deck" or (movement == "hand" and viewer != owner):
            assert "source-live" not in payload["state"]["cards"]
        if viewer == owner:
            manual = next(a for a in payload["legal_actions"] if a["action_type"] == "manual_adjustment")
            assert manual["options"]["source_invocations"][0]["source_card_instance_id"] == "source-live"
    final = repo.apply(state.match_id, _manual(result.state, inv,
        [{"adjustment_type": "set_flag", "flag": "audit-only-manual-entry", "duration": "turn"}]))
    assert not final.state.pending_effects
    assert not any(m.modifier_type == "required_heart" for m in final.state.players[owner].manual_modifiers)
    _exclusive(final.state)
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("ready", [False, True])
def test_native_sibling_control_changes_orientation_before_manual_resolution_sql(tmp_path, ready):
    state = _state(waits=int(ready))
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id="CONTROL", label_ja="AUDIT orientation CONTROL", execution_mode="prompt_then_resolve",
               simulation_support="test_validated_executable", review_status="test_validated", frequency_limit="none",
               duration=None, choice={"choice_type": "member_from_stage", "zone": "stage", "card_type": "member", "minimum": 1, "maximum": 1},
               actions=[{"action_type": "ready_member" if ready else "apply_wait_member", "target": "selected"}])
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    state.cards["live-1"].card.effect_ids = ["CONTROL"]
    repo = MatchRepository(tmp_path / "orientation.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    begun = repo.apply(state.match_id, _advance(state)).state
    ctrl = next(i for i in begun.pending_effects if i.effect_id == "CONTROL")
    result = repo.apply(state.match_id, ActionRequest(action_type="resolve_effect", player_id="player_1",
        expected_revision=begun.revision, payload={"invocation_id": ctrl.invocation_id, "selected_card_instance_ids": ["target"]}))
    assert result.state.cards["target"].orientation == ("active" if ready else "wait")
    assert [i.effect_id for i in result.state.pending_effects] == [EFFECT]
    assert not result.state.players["player_1"].manual_modifiers
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_do_not_guess_manual_condition_or_use_hidden_identities(owner, policy):
    state = apply_action(_state(owner=owner), _advance(_state(owner=owner))).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIBlocker) and decision.reason == "no_safe_ai_action"
    changed = state.model_copy(deep=True)
    for key in ["tail", "secret"]:
        item = changed.cards.pop(key)
        renamed = "hidden-" + key
        item.instance_id = renamed
        item.card.name_ja = item.card.card_code = "CHANGED-HIDDEN"
        item.card.blade = 99
        changed.cards[renamed] = item
        for p in changed.players.values():
            p.hand = [renamed if x == key else x for x in p.hand]
            p.main_deck = [renamed if x == key else x for x in p.main_deck]
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner}) == decision
    assert match_state_hash(state) == before


@pytest.mark.parametrize("bad_player", [False, True])
def test_unconfirmed_automatic_submission_is_atomic(bad_player):
    state = apply_action(_state(), _advance(_state())).state
    before = match_state_hash(state)
    inv = state.pending_effects[0]
    with pytest.raises(IllegalActionError):
        apply_action(state, ActionRequest(action_type="resolve_effect", player_id="player_2" if bad_player else "player_1",
            expected_revision=state.revision, payload={"invocation_id": inv.invocation_id, "accepted": True}))
    assert match_state_hash(state) == before


def test_formal_second_segment_still_executes_while_first_waits_sql(tmp_path):
    state = _state(both=True)
    repo = MatchRepository(tmp_path / "both.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    begun = repo.apply(state.match_id, _advance(state)).state
    inv = next(i for i in begun.pending_effects if i.effect_id == SECOND)
    result = repo.apply(state.match_id, ActionRequest(action_type="resolve_effect", player_id="player_1",
        expected_revision=begun.revision, payload={"invocation_id": inv.invocation_id, "accepted": True}))
    assert [i.effect_id for i in result.state.pending_effects] == [EFFECT]
    assert any(e.event_type == "effect_bottom_aqours_requirement_resolved" for e in result.events)
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True
