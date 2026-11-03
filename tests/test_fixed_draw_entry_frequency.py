"""Opt-in fixed draw observers only; constructed chains, not complete games."""

import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from pydantic import ValidationError

from loveca.simulation.ai import SimpleAIController, SimpleAIPolicy
from loveca.simulation.engine import IllegalActionError, apply_action
from loveca.simulation.models import ActionRequest, FixedDrawEntryFrequencyV1, MatchState
from loveca.simulation.online import match_state_hash
from loveca.simulation.rulesets import current_ruleset_identity
from loveca.simulation.runtime import MatchRepository, _events_for_persisted_action
from loveca.webapp import _match_state_payload
from test_normal_phase_boundary import _private
from test_overlap_entry_observer import ACTUAL, _actual, _state
from test_yell_icons_boundary import _choose
from test_attachment_promotion import _trigger


OWNERS = ("player_1", "player_2")
ROUTES = ("stay", "within_stage", "hand", "waiting", "different_copy", "overlap_return")


def _fixture(owner, *, modern=True, prior=True):
    state = _state(cost=10 if prior else 9)
    state.effect_definitions = {ACTUAL: _actual()[0].model_copy(deep=True)}
    state.fixed_draw_entry_frequency = FixedDrawEntryFrequencyV1() if modern else None
    player = state.players["player_1"]
    state.cards["next"].card.cost = 10
    state.cards["old-copy"] = state.cards["old"].model_copy(update={"instance_id": "old-copy"}, deep=True)
    player.hand.append("old-copy")
    for i in range(10, 30):
        key = f"energy-{i}"
        state.cards[key] = state.cards["energy-0"].model_copy(update={"instance_id": key}, deep=True)
        player.energy_area.append(key)
    profile, fingerprint = current_ruleset_identity()
    state.rule_version = profile.rule_version
    state.ruleset_id = profile.ruleset_id
    state.ruleset_fingerprint = fingerprint
    state.ruling_pack_version = profile.ruling_pack_version
    if owner == "player_2":
        swap = {"player_1": "player_2", "player_2": "player_1"}
        state.players = {swap[k]: p for k, p in state.players.items()}
        for key, player in state.players.items():
            player.player_id = key
        for card in state.cards.values():
            card.owner_id = swap[card.owner_id]
        for key in ("first_player_id", "second_player_id", "active_player_id", "next_first_player_id"):
            if getattr(state, key) in swap:
                setattr(state, key, swap[getattr(state, key)])
    return MatchState.model_validate_json(state.model_dump_json())


def _apply(repo, state, action):
    before = match_state_hash(state)
    result = repo.apply(state.match_id, action)
    assert match_state_hash(state) == before
    assert repo.get_state(state.match_id) == result.state
    _private(result)
    for viewer in state.players:
        payload = _match_state_payload(result.state, events=result.events,
                                       legal_actions=result.legal_actions, player_id=viewer)
        assert "fixed_draw_entry_frequency" not in payload["state"]
        assert "source_stage_generation" not in json.dumps(payload)
    return result


def _step(repo, state, kind, **payload):
    return _apply(repo, state, ActionRequest(action_type=kind, player_id=state.active_player_id,
                                            expected_revision=state.revision, payload=payload))


def _play(repo, state, key, slot):
    player = state.players[state.active_player_id]
    energy = [k for k in player.energy_area if state.cards[k].orientation == "active"]
    return _step(repo, state, "play_member", card_instance_id=key, slot=slot,
                 use_baton_touch=False, energy_instance_ids=energy[:state.cards[key].card.cost])


def _manual(repo, state, **change):
    return _step(repo, state, "manual_adjustment", reason="TEST constructed source reentry",
                 adjustments=[{"target_player_id": state.active_player_id, **change}])


def _triggers(result):
    return [e for e in result.events if e.event_type == "effect_triggered" and e.data.get("effect_id") == ACTUAL]


def _verify_sql(repo, final):
    digest = hashlib.sha256(repo.path.read_bytes()).hexdigest()
    with closing(sqlite3.connect(repo.path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        initial = db.execute("SELECT initial_state_json FROM matches").fetchone()[0]
        actions = db.execute("SELECT sequence,action_id,action_type,player_id,payload_json,expected_revision FROM match_actions ORDER BY sequence").fetchall()
        events = db.execute("SELECT action_sequence,event_json FROM match_events ORDER BY action_sequence,event_index").fetchall()
    state = MatchState.model_validate_json(initial)
    for seq, aid, kind, owner, payload, revision in actions:
        action = ActionRequest(action_id=aid, action_type=kind, player_id=owner,
                               payload=json.loads(payload), expected_revision=revision)
        result = apply_action(state, action)
        assert [e.model_dump(mode="json") for e in _events_for_persisted_action(action, result.events)] == [json.loads(e) for n, e in events if n == seq]
        state = result.state
    assert state == final
    copy = repo.path.with_name("copy.sqlite3")
    shutil.copy2(repo.path, copy)
    replay = MatchRepository(copy).replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"]
    assert replay["metadata"]["ruleset_identity_verified"]
    assert replay["final_state"] == state.model_dump(mode="json")
    assert hashlib.sha256(repo.path.read_bytes()).hexdigest() == digest


def _chain(tmp_path, owner, route, *, modern=True, prior=True):
    state = _fixture(owner, modern=modern, prior=prior)
    repo = MatchRepository(tmp_path / "original.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    first = _play(repo, state, "entrant", "center" if route == "overlap_return" else "left")
    assert len(_triggers(first)) == int(prior)
    state = first.state
    slot = "right"
    if route == "overlap_return":
        if prior:
            kinds = [e.event_type for e in first.events]
            assert kinds.index("effect_triggered") < kinds.index("duplicate_member_resolved") < kinds.index("cards_drawn")
            assert state.effect_usage[-1].source_stage_generation == (0 if modern else None)
        state = _manual(repo, state, adjustment_type="move_card", target_card_instance_id="old", to_zone="hand").state
        state = _play(repo, state, "old", "right").state
        slot = "left"
    elif route == "within_stage":
        state = _manual(repo, state, adjustment_type="position_change", from_slot="center", to_slot="right").state
        slot = "center"
    elif route != "stay":
        zone = "waiting_room" if route == "waiting" else "hand"
        state = _manual(repo, state, adjustment_type="move_card", target_card_instance_id="old", to_zone=zone).state
        if zone == "waiting_room":
            state = _manual(repo, state, adjustment_type="move_card", target_card_instance_id="old", to_zone="hand").state
        state = _play(repo, state, "old-copy" if route == "different_copy" else "old", "center").state
    second = _play(repo, state, "next", slot)
    expected = not prior or route == "different_copy" or (modern and route in {"hand", "waiting", "overlap_return"})
    assert len(_triggers(second)) == int(expected)
    assert len([e for e in second.events if e.event_type == "cards_drawn"]) == int(expected)
    assert not second.state.pending_effects
    if modern and prior and route in {"hand", "waiting", "overlap_return"}:
        assert [u.source_stage_generation for u in second.state.effect_usage if u.effect_id == ACTUAL] == [0, 1]
    if not modern:
        raw = second.state.model_dump_json()
        assert "fixed_draw_entry_frequency" not in raw and "source_stage_generation" not in raw
    return repo, second.state


@pytest.mark.parametrize("owner", OWNERS)
@pytest.mark.parametrize("modern", [False, True])
@pytest.mark.parametrize("prior", [False, True])
@pytest.mark.parametrize("route", ROUTES)
def test_bounded_observer_reentry_and_same_object_controls(tmp_path, owner, modern, prior, route):
    repo, state = _chain(tmp_path, owner, route, modern=modern, prior=prior)
    _verify_sql(repo, state)


@pytest.mark.parametrize("owner", OWNERS)
@pytest.mark.parametrize("route", ["hand", "waiting", "overlap_return"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_after_constructed_reentry(tmp_path, owner, route, policy):
    repo, state = _chain(tmp_path, owner, route)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    result = _apply(repo, state, _choose(controller, state))
    _verify_sql(repo, result.state)


@pytest.mark.parametrize("owner", OWNERS)
def test_rejected_batch_rolls_back_generation_and_usage(tmp_path, owner):
    state = _fixture(owner)
    repo = MatchRepository(tmp_path / "original.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    state = _play(repo, state, "entrant", "left").state
    before = state.model_dump_json()
    action = ActionRequest(action_type="manual_adjustment", player_id=owner, expected_revision=state.revision,
                           payload={"reason": "TEST atomic rollback", "adjustments": [
                               {"target_player_id": owner, "adjustment_type": "move_card", "target_card_instance_id": "old", "to_zone": "hand"},
                               {"target_player_id": owner, "adjustment_type": "move_card", "target_card_instance_id": "missing", "to_zone": "hand"},
                           ]})
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, action)
    assert state.model_dump_json() == before == repo.get_state(state.match_id).model_dump_json()
    _verify_sql(repo, state)


@pytest.mark.parametrize("bad", [-1, True, "1", 1.5])
def test_generation_rejects_invalid_serialized_counter(bad):
    with pytest.raises(ValidationError):
        FixedDrawEntryFrequencyV1(stage_generations={"old": bad})


def test_pinned_real_source_and_rules():
    effect, card = _actual()
    assert effect.text_revision_id == card.text_revision_id == 312
    assert effect.raw_text_hash == card.raw_text_hash == "a24c05703cd27bdf500e947ef67c575ee7ef3c5fba24dc06ced37d0b2b504a8b"
    assert effect.frequency_limit == "once_per_turn"
    assert hashlib.sha256(Path("raw_doc/LoveLiveTCG_cr_1.06_260428.pdf").read_bytes()).hexdigest() == "c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485"


def _pending_fixture(tmp_path, owner):
    state = _fixture(owner)
    state.effect_order_policy = "ap_nap_player_choice"
    control = _trigger("frequency-control:1", "member_played")
    control.simulation_support = "manual_resolution"
    control.execution_mode = "manual_resolution"
    state.effect_definitions[control.effect_id] = control
    state.cards["entrant"].card.effect_ids = [control.effect_id]
    repo = MatchRepository(tmp_path / "original.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    state = _play(repo, state, "entrant", "left").state
    assert len(state.pending_effects) == 2 and not state.effect_usage
    assert next(i for i in state.pending_effects if i.effect_id == ACTUAL).source_stage_generation == 0
    return repo, state


def _pending_manual(state, changes):
    invocation = next(i for i in state.pending_effects if i.effect_id == "frequency-control:1")
    return ActionRequest(action_type="manual_adjustment", player_id=invocation.player_id,
                         expected_revision=state.revision, payload={
                             "reason": "TEST synthetic manual interference, not a registered recovery effect",
                             "source_invocation_id": invocation.invocation_id,
                             "source_effect_id": invocation.effect_id,
                             "source_card_instance_id": invocation.source_card_instance_id,
                             "adjustments": [{"target_player_id": invocation.player_id, **c} for c in changes],
                         })


@pytest.mark.parametrize("owner", OWNERS)
@pytest.mark.parametrize("route", ["return", "promoted", "within_stage"])
def test_pending_old_source_records_old_generation_after_return(tmp_path, owner, route):
    repo, state = _pending_fixture(tmp_path, owner)
    if route == "within_stage":
        changes = [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "right"}]
    else:
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": "old", "to_zone": "hand"}]
        if route == "return":
            changes.append({"adjustment_type": "move_card", "target_card_instance_id": "old", "to_zone": "member_center"})
        else:
            changes.extend([
                {"adjustment_type": "attach_card_under_member", "target_card_instance_id": "old", "target_slot": "left"},
                {"adjustment_type": "move_attached_card", "target_card_instance_id": "old", "to_zone": "member_center"},
            ])
    result = _apply(repo, state, _pending_manual(state, changes))
    assert not result.state.pending_effects
    assert [u.source_stage_generation for u in result.state.effect_usage if u.effect_id == ACTUAL] == [0]
    assert result.state.fixed_draw_entry_frequency.stage_generations.get("old", 0) == int(route != "within_stage")
    second = _play(repo, result.state, "next", "center" if route == "within_stage" else "right")
    assert len(_triggers(second)) == int(route != "within_stage")
    assert [u.source_stage_generation for u in second.state.effect_usage if u.effect_id == ACTUAL] == ([0] if route == "within_stage" else [0, 1])
    _verify_sql(repo, second.state)


@pytest.mark.parametrize("owner", OWNERS)
def test_pending_generation_survives_rejected_interference_batch(tmp_path, owner):
    repo, state = _pending_fixture(tmp_path, owner)
    before = state.model_dump_json()
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _pending_manual(state, [
            {"adjustment_type": "move_card", "target_card_instance_id": "old", "to_zone": "hand"},
            {"adjustment_type": "move_card", "target_card_instance_id": "old", "to_zone": "member_left"},
        ]))
    assert state.model_dump_json() == before == repo.get_state(state.match_id).model_dump_json()
    _verify_sql(repo, state)


@pytest.mark.parametrize("owner", OWNERS)
@pytest.mark.parametrize("clear_attached", [False, True])
@pytest.mark.parametrize("destination", ["hand", "waiting_room", "member_center"])
def test_attached_member_departure_independent_of_modifier_policy(tmp_path, owner, clear_attached, destination):
    state = _fixture(owner)
    state.attached_member_departure_policy = "clear_target_modifiers_v1" if clear_attached else None
    repo = MatchRepository(tmp_path / "original.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    state = _play(repo, state, "entrant", "left").state
    state = _manual(repo, state, adjustment_type="move_card", target_card_instance_id="old", to_zone="hand").state
    state = _manual(repo, state, adjustment_type="attach_card_under_member", target_card_instance_id="old", target_slot="left").state
    state = _manual(repo, state, adjustment_type="move_attached_card", target_card_instance_id="old", to_zone=destination).state
    assert state.fixed_draw_entry_frequency.stage_generations["old"] == (1 if destination == "member_center" else 2)
    if destination == "waiting_room":
        state = _manual(repo, state, adjustment_type="move_card", target_card_instance_id="old", to_zone="hand").state
    if destination != "member_center":
        state = _play(repo, state, "old", "center").state
    result = _play(repo, state, "next", "right")
    assert len(_triggers(result)) == 1
    assert result.state.effect_usage[-1].source_stage_generation == (1 if destination == "member_center" else 2)
    _verify_sql(repo, result.state)


@pytest.mark.parametrize("frequency", ["once_per_live", "twice_per_turn", None])
def test_other_frequency_contracts_are_not_migrated(frequency):
    from loveca.simulation.engine import _fixed_draw_entry_generation

    state = _fixture("player_1")
    effect = state.effect_definitions[ACTUAL].model_copy(update={"frequency_limit": frequency})
    assert _fixed_draw_entry_generation(state, effect, "old") is None


def test_missing_legacy_usage_generation_is_conservative():
    from loveca.simulation.engine import _effect_usage_limit_reached
    from loveca.simulation.models import EffectUsage

    state = _fixture("player_1")
    state.effect_usage.append(EffectUsage(effect_id=ACTUAL, source_card_instance_id="old", turn_number=state.turn_number))
    assert _effect_usage_limit_reached(state, state.effect_definitions[ACTUAL], "old", source_stage_generation=2)
