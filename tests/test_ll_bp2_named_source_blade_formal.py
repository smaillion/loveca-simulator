import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from loveca.simulation.effect_candidates import _live_start_ll_bp2_named_source_blade
import loveca.simulation.effect_candidates as candidate_module
from loveca.simulation.effects import EffectDefinition, LL_BP2_FULL_TEXT, LL_BP2_NAMED_BLADE_TEXT, load_effect_registry
from loveca.simulation.engine import generate_legal_actions
from loveca.simulation.models import ActionRequest
from test_ll_bp2_composite_name_cost_audit import _actual, CODE, EFFECT, HASH
from test_private_named_unlimited_discard_probe import _probe as _named_probe, PROBE
from test_printemps_ready_history_boundary import _advance, _manual, _repo, _replay, _resolve
import test_paid_named_source_blade_probe as prior


def test_formal_identity_and_new_snapshot():
    state = _actual("player_1")
    card = state.cards["source-live"].card
    effect = next(e for e in load_effect_registry().effects if e.effect_id == EFFECT)
    assert card.text_revision_id == 592
    assert hashlib.sha256(card.raw_effect_text_ja.encode()).hexdigest() == card.raw_text_hash == HASH
    assert effect.card_code == CODE and effect.raw_text_hash == HASH and effect.text_revision_id == 592
    assert effect.cost_choice.selection_policy == "private_partial_names_unlimited_discard_v1"
    assert effect.actions[0].action_type == "gain_source_blade_for_paid_named_v1"


def _formal(owner, control=False):
    state = _named_probe(owner, control=control)
    state.effect_definitions.pop(PROBE)
    state.effect_definitions[EFFECT] = next(e for e in load_effect_registry().effects if e.effect_id == EFFECT)
    state.cards["source-live"].card.card_code = CODE
    state.cards["source-live"].card.effect_ids = [EFFECT]
    return state


@pytest.mark.parametrize("field,value", [("card_code", "OTHER"), ("effect_id", "OTHER:3"),
    ("effect_index", 2), ("text_revision_id", 593), ("raw_text_hash", "0" * 64),
    ("label_ja", LL_BP2_NAMED_BLADE_TEXT + " ")])
def test_formal_snapshot_identity_is_strict(field, value):
    raw = next(e for e in load_effect_registry().effects if e.effect_id == EFFECT).model_dump(mode="json")
    raw[field] = value
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("field,value", [("card_code", "OTHER"), ("text_revision_id", 593),
    ("raw_text_hash", "0" * 64), ("raw_effect_text_ja", LL_BP2_FULL_TEXT + " ")])
def test_candidate_requires_exact_full_text_and_revision(field, value):
    row = {"card_code": CODE, "text_revision_id": 592, "raw_text_hash": HASH, "raw_effect_text_ja": LL_BP2_FULL_TEXT}
    assert _live_start_ll_bp2_named_source_blade(row).effect_id == EFFECT
    row[field] = value
    assert _live_start_ll_bp2_named_source_blade(row) is None


def test_changed_full_text_cannot_fall_back_to_generic_third_effect(monkeypatch):
    row = {"card_code": CODE, "text_revision_id": 592, "raw_text_hash": HASH, "raw_effect_text_ja": LL_BP2_FULL_TEXT}
    exact = _live_start_ll_bp2_named_source_blade(row)
    row["raw_effect_text_ja"] += " "
    generic_third = replace(exact, pattern_id="generic")
    generic_second = replace(exact, effect_id=CODE + ":2", effect_index=2, pattern_id="generic")
    monkeypatch.setattr(candidate_module, "_effect_text_rows", lambda _: [row])
    monkeypatch.setattr(candidate_module, "_PATTERNS", (lambda _: generic_third, lambda _: generic_second))
    monkeypatch.setattr(candidate_module, "_manual_timing_candidates", lambda _: [])
    candidates = candidate_module.discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
    assert [candidate.effect_id for candidate in candidates] == [CODE + ":2"]


@pytest.fixture
def formal_prior(monkeypatch):
    monkeypatch.setattr(prior, "_blade_probe", _formal)
    monkeypatch.setattr(prior, "PROBE", EFFECT)


@pytest.mark.usefixtures("formal_prior")
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("count", [0, 1, 4, 6])
def test_formal_dynamic_paid_count_sql(tmp_path, owner, count):
    prior.test_paid_actual_count_controls_source_blade_sql(tmp_path, owner, count)


@pytest.mark.usefixtures("formal_prior")
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("destination", ["hand", "main_deck", "return"])
def test_formal_original_source_departure_sql(tmp_path, owner, destination):
    prior.test_departed_source_never_receives_old_blade_sql(tmp_path, owner, destination)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_formal_empty_candidates_can_resolve_zero_sql(tmp_path, owner):
    state = _formal(owner)
    for key in state.players[owner].hand:
        state.cards[key].card.name_ja = "UNRELATED"
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    legal = next(a for a in generate_legal_actions(current) if a.action_type == "resolve_effect")
    invocation = next(i for i in legal.options["invocations"] if i["effect_id"] == EFFECT)
    assert invocation["candidate_card_instance_ids"] == [] and invocation["card_selection_maximum"] == 0
    result = repo.apply(state.match_id, _resolve(current, EFFECT, accepted=True, selected_card_instance_ids=[]))
    assert not any(m.value == {"policy": "paid_named_blade_v1"} for m in result.state.players[owner].manual_modifiers)
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_formal_departed_source_can_be_paid_as_new_hand_card_sql(tmp_path, owner):
    state = _formal(owner, control=True)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    current = repo.apply(state.match_id, _manual(current, "CONTROL", [
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"},
    ])).state
    result = repo.apply(state.match_id, _resolve(current, EFFECT, accepted=True, selected_card_instance_ids=["source-live"]))
    assert "source-live" in result.state.players[owner].waiting_room
    assert not any(m.value == {"policy": "paid_named_blade_v1"} for m in result.state.players[owner].manual_modifiers)
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("first", ["source-live", "target"])
def test_formal_two_sources_keep_independent_payment_binding_sql(tmp_path, owner, first):
    state = _formal(owner)
    state.cards["target"].card = state.cards["source-live"].card.model_copy(deep=True)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    invocations = [i for i in current.pending_effects if i.effect_id == EFFECT]
    assert {i.source_card_instance_id for i in invocations} == {"source-live", "target"}
    selected = next(i for i in invocations if i.source_card_instance_id == first)
    action = ActionRequest(action_type="resolve_effect", player_id=owner, expected_revision=current.revision,
        payload={"invocation_id": selected.invocation_id, "accepted": True, "selected_card_instance_ids": ["single-hand"]})
    current = repo.apply(state.match_id, action).state
    marks = [m for m in current.players[owner].manual_modifiers if m.value == {"policy": "paid_named_blade_v1"}]
    assert len(marks) == 1 and marks[0].target_card_instance_id == first and marks[0].amount == 1
    remaining = next(i for i in current.pending_effects if i.effect_id == EFFECT)
    current = repo.apply(state.match_id, ActionRequest(action_type="resolve_effect", player_id=owner,
        expected_revision=current.revision, payload={"invocation_id": remaining.invocation_id, "accepted": False})).state
    _replay(repo, current)


@pytest.mark.usefixtures("formal_prior")
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", [None, "clear_departed_card_modifiers"])
def test_formal_earned_blade_departure_sql(tmp_path, owner, policy):
    prior.test_earned_blade_is_cleared_on_departure_and_return_sql(tmp_path, owner, policy)


@pytest.mark.usefixtures("formal_prior")
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_formal_stage_position_and_live_end_sql(tmp_path, owner):
    (tmp_path / "position").mkdir()
    (tmp_path / "live").mkdir()
    prior.test_stage_position_change_keeps_original_source_sql(tmp_path / "position", owner)
    prior.test_actual_live_end_expires_blade_sql(tmp_path / "live", owner)


@pytest.mark.usefixtures("formal_prior")
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("payload", [{"selected_branch": "fake"}, {"energy_instance_ids": ["fake"]},
    {"accepted": False, "selected_card_instance_ids": ["single-hand"]},
    {"accepted": True, "selected_card_instance_ids": ["single-hand", "single-hand"]},
    {"accepted": True, "selected_card_instance_ids": ["unrelated-hand"]}])
def test_formal_invalid_cost_atomic_sql(tmp_path, owner, payload):
    prior.test_client_input_is_rejected_atomically_sql(tmp_path, owner, payload)


@pytest.mark.usefixtures("formal_prior")
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_formal_decline_wrong_actor_sql(tmp_path, owner):
    prior.test_decline_and_wrong_actor_do_not_pay_sql(tmp_path, owner)


@pytest.mark.usefixtures("formal_prior")
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("tampering", ["forged_cost", "source", "turn", "stage", "after_cost"])
def test_formal_forged_source_and_payment(owner, tampering):
    prior.test_forged_proofs_and_source_are_rejected_atomically(owner, tampering)


@pytest.mark.usefixtures("formal_prior")
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("hide_source", [False, True])
def test_formal_ai_and_hidden_identity(owner, policy, hide_source):
    prior.test_ai_actual_decision_and_hidden_information(owner, policy, hide_source)
