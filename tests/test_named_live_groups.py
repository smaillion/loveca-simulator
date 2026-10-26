from contextlib import closing
from functools import lru_cache
from pathlib import Path

import pytest
from test_named_live_blade import _begin
from test_named_live_blade import _state as single_state

from loveca.db.bootstrap import connect_database
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effects import load_effect_registry
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.models import ActionRequest, MatchState
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!SP-bp1-024"
EFFECT = CODE + ":1"
RULE_REFERENCE_IDS = ("9.6.3", "9.6.3.1", "9.6.3.1.3", "9.7.2", "11.5.2")


@lru_cache
def _candidate():
    return next(c for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
                if c.effect_id == EFFECT)


def _state(*, names=("澁谷かのん", "澁谷かのん", "唐 可可"), legacy=False):
    effect = next(e for e in load_effect_registry().effects if e.effect_id == EFFECT)
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        card = _load_definition(connection, CODE, None, {EFFECT: effect}, {})
    state = single_state(copies=0)
    if legacy:
        raw = effect.model_dump(mode="json")
        raw.update(choice=None, execution_mode="auto_resolve", actions=[
            {"action_type": action, "amount": 1, "color_slot": color,
             "value": {"name_ja": name, "maximum": 1}}
            for name, color in [("澁谷かのん", "heart05"), ("唐 可可", "heart01")]
            for action, color in [("gain_heart_to_stage_members", color), ("gain_blade_to_stage_members", None)]])
        effect = EffectDefinition.model_validate(raw)
    state.effect_definitions = {EFFECT: effect}
    state.cards["source-live"].card = card
    for index, name in enumerate(names):
        state.cards[f"member-{index}"].card.name_ja = name
    return state


def _resolve(state, groups):
    return ActionRequest(action_type="resolve_effect", player_id="player_1", expected_revision=state.revision,
                        payload={"invocation_id": state.pending_effects[0].invocation_id,
                                 "selected_card_instance_ids_by_group": groups})


def _options(result):
    return next(a for a in result.legal_actions if a.action_type == "resolve_effect").options["invocations"][0]


def test_actual_card_does_not_automatically_pick_the_first_same_name_copy():
    result = _begin(_state())
    assert len(result.state.pending_effects) == 1
    assert not result.state.players["player_1"].manual_modifiers


def test_exact_candidate_registry_revision_hash_and_group_contract():
    candidate = _candidate()
    effect = next(e for e in load_effect_registry().effects if e.effect_id == EFFECT)
    assert effect == EffectDefinition.model_validate(candidate.to_registry_entry())
    assert effect.text_revision_id == 836
    assert effect.raw_text_hash == "b7216c82672134b14428b0acad44ae4c1acc7fd3b6bd87e7c08d6e370e5cf498"
    assert effect.execution_mode == "prompt_then_resolve" and effect.duration == "live"
    assert effect.simulation_support == "test_validated_executable" and effect.review_status == "test_validated"
    assert effect.choice.selection_policy == "public_named_groups_as_much_as_possible"
    assert [g.name_ja_any for g in effect.choice.selection_groups] == [["澁谷かのん"], ["唐 可可"]]


@pytest.mark.parametrize("orientation", ["active", "wait"])
@pytest.mark.parametrize("kanon", ["member-0", "member-1"])
def test_two_groups_apply_heart_and_blade_to_exactly_the_same_chosen_targets(orientation, kanon):
    state = _state()
    state.cards[kanon].orientation = orientation
    started = _begin(state)
    groups = _options(started)["choice_groups"]
    assert [g["candidate_card_instance_ids"] for g in groups] == [["member-0", "member-1"], ["member-2"]]
    result = apply_action(started.state, _resolve(started.state, {"kanon": [kanon], "keke": ["member-2"]}))
    modifiers = result.state.players["player_1"].manual_modifiers
    assert len(modifiers) == 4
    assert {(m.modifier_type, m.target_card_instance_id, m.color_slot, m.amount, m.duration) for m in modifiers} == {
        ("heart", kanon, "heart05", 1, "live"), ("blade", kanon, None, 1, "live"),
        ("heart", "member-2", "heart01", 1, "live"), ("blade", "member-2", None, 1, "live")}
    assert result.state.cards[kanon].orientation == orientation
    assert not result.state.pending_effects and result.state.phase == "yell_first"


@pytest.mark.parametrize("names,selection,count", [
    (("澁谷かのん", "別名", "別名"), {"kanon": ["member-0"]}, 2),
    (("別名", "唐可可", "唐 可可"), {"keke": ["member-2"]}, 2),
    (("別名", "別名", "別名"), {}, 0),
])
def test_missing_named_group_does_not_cancel_the_other_group(names, selection, count):
    started = _begin(_state(names=names))
    assert started.state.pending_effects
    for group in _options(started)["choice_groups"]:
        expected = int(bool(group["candidate_card_instance_ids"]))
        assert group["minimum"] == group["maximum"] == expected
    result = apply_action(started.state, _resolve(started.state, selection))
    assert len(result.state.players["player_1"].manual_modifiers) == count
    assert not result.state.pending_effects
    assert any(e.data.get("reason") == "no_legal_stage_member_at_resolution" for e in result.events)


@pytest.mark.parametrize("groups", [None, {}, {"unknown": []}, {"kanon": ["member-2"], "keke": ["member-0"]},
    {"kanon": ["member-0", "member-1"], "keke": ["member-2"]},
    {"kanon": ["member-0", "member-0"], "keke": ["member-2"]},
    *[{"kanon": [target], "keke": ["member-2"]} for target in ["held", "attached", "opponent-member", "missing"]],
    {"kanon": "member-0", "keke": ["member-2"]}])
def test_invalid_groups_are_rejected_without_mutation(groups):
    state = _begin(_state()).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, groups))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("arrives", [False, True])
def test_target_presence_is_recalculated_at_resolution(arrives):
    state = _begin(_state(names=("別名" if arrives else "澁谷かのん", "別名", "唐 可可"))).state
    # Controlled snapshot after another ordered ability's Stage movement.
    if arrives:
        state.cards["held"].card.name_ja = "澁谷かのん"
        state.players["player_1"].hand.remove("held")
        state.players["player_1"].member_area["left"] = "held"
        kanon = ["held"]
    else:
        state.players["player_1"].member_area["left"] = None
        state.players["player_1"].waiting_room.append("member-0")
        kanon = []
    result = apply_action(state, _resolve(state, {"kanon": kanon, "keke": ["member-2"]}))
    assert len(result.state.players["player_1"].manual_modifiers) == (4 if arrives else 2)


def test_source_departure_does_not_cancel_and_live_end_clears_both_bonuses():
    state = _begin(_state()).state
    state.players["player_1"].live_area.remove("source-live")
    state.players["player_1"].waiting_room.append("source-live")
    result = apply_action(state, _resolve(state, {"kanon": ["member-1"], "keke": ["member-2"]}))
    assert len(result.state.players["player_1"].manual_modifiers) == 4
    state = result.state
    state.phase, state.active_player_id = "live_judgment", None
    result = apply_action(state, ActionRequest(action_type="advance_phase", expected_revision=state.revision))
    assert not result.state.players["player_1"].manual_modifiers


def test_selected_target_departure_clears_both_modifiers_not_the_other_group():
    state = _begin(_state()).state
    state = apply_action(state, _resolve(state, {"kanon": ["member-1"], "keke": ["member-2"]})).state
    result = apply_action(state, ActionRequest(action_type="manual_adjustment", player_id="player_1",
        expected_revision=state.revision, payload={"adjustments": [{"adjustment_type": "move_card",
            "target_player_id": "player_1", "target_card_instance_id": "member-1", "to_zone": zone}
            for zone in ["waiting_room", "member_center"]]}))
    assert [m.target_card_instance_id for m in result.state.players["player_1"].manual_modifiers] == ["member-2", "member-2"]


@pytest.mark.parametrize("legacy,names", [(False, ("澁谷かのん", "澁谷かのん", "唐 可可")),
    (False, ("別名", "別名", "唐 可可")), (False, ("別名", "別名", "別名")),
    (True, ("澁谷かのん", "澁谷かのん", "唐 可可"))])
def test_sql_replay_and_old_auto_snapshot_are_preserved(tmp_path, legacy, names):
    state = _state(names=names, legacy=legacy)
    assert MatchState.model_validate_json(state.model_dump_json()) == state
    if legacy:
        assert "selection_policy" not in state.effect_definitions[EFFECT].model_dump_json()
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repository.apply(state.match_id, ActionRequest(action_type="advance_phase", player_id="player_1", expected_revision=0))
    if legacy:
        assert not result.state.pending_effects
        assert [m.target_card_instance_id for m in result.state.players["player_1"].manual_modifiers] == ["member-0", "member-0", "member-2", "member-2"]
    else:
        choices = {g["group_id"]: g["candidate_card_instance_ids"][-1:] for g in _options(result)["choice_groups"]}
        result = repository.apply(state.match_id, _resolve(result.state, choices))
    replay = repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")
    for viewer, secret in [("player_1", "opponent-secret"), ("player_2", "held")]:
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        assert secret not in payload["state"]["cards"]


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("names", [("澁谷かのん", "澁谷かのん", "唐 可可"), ("別名", "別名", "唐 可可"), ("別名", "別名", "別名")])
def test_four_ai_policies_use_group_options_and_ignore_opponent_private_identity(policy, names):
    state = _begin(_state(names=names)).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision) and decision.action.action_type == "resolve_effect"
    changed = state.model_copy(deep=True)
    changed.cards["opponent-secret"].card.name_ja = "澁谷かのん"
    changed.cards["opponent-secret"].card.card_code = "PRIVATE-CHANGED"
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}).action == decision.action
    assert not apply_action(state, decision.action).state.pending_effects


@pytest.mark.parametrize("defect", ["cost", "optional", "wrong_trigger", "missing_operation", "bad_group", "duplicate_name", "exclusion", "wrong_zone"])
def test_group_policy_rejects_unmodeled_semantics(defect):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    if defect == "cost": raw["cost"] = [{"action_type": "pay_energy", "amount": 1}]
    elif defect == "optional": raw["is_optional"] = True
    elif defect == "wrong_trigger": raw["trigger"] = "member_played"
    elif defect == "missing_operation": raw["actions"].pop()
    elif defect == "bad_group": raw["actions"][0]["value"] = {"target_group_id": "missing"}
    elif defect == "duplicate_name": raw["choice"]["selection_groups"][1]["name_ja_any"] = ["澁谷 かのん"]
    elif defect == "exclusion": raw["choice"]["selection_groups"][1]["exclude_group_ids"] = ["kanon"]
    else: raw["choice"]["selection_groups"][0]["zone"] = "hand"
    with pytest.raises(ValueError, match="public named groups"):
        EffectDefinition.model_validate(raw)
