import json
from pathlib import Path

import pytest
from test_nijigasaki_inspection import _play, _resolve, _state
from test_typed_inspection_costs import _control, _with_control

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

REORDER = ("PL!-bp3-014", "PL!-bp3-017", "PL!-bp3-018", "PL!N-bp3-022", "PL!N-bp4-016", "PL!S-bp6-018")
WAIT = (*REORDER, "PL!SP-bp4-002")
DISCARD = ("PL!N-sd2-012", "PL!N-sd2-014", "PL!N-bp7-018")
CODES = (*WAIT, *DISCARD)
RULE_REFERENCE_IDS = ("4.1.4", "5.7.1", "9.4.2", "9.7.3.1.1", "9.7.3.2", "10.2.2.2", "10.2.3")


def _choose(state, ids):
    return ActionRequest(action_type="resolve_effect_choice", player_id="player_1", expected_revision=state.revision,
        payload={"selected_card_instance_ids": ids, "ordered_card_instance_ids": ids})


@pytest.mark.parametrize("code", WAIT)
def test_already_wait_source_cannot_pay_and_inspect(code):
    state = _state(code)
    state = apply_action(state, _play(state)).state
    state.cards["source-live"].orientation = "wait"
    result = apply_action(state, _resolve(state))
    assert result.state.pending_choice is None and not result.state.pending_effects
    assert result.state.players["player_1"].main_deck == state.players["player_1"].main_deck
    assert any(e.data.get("reason") == "inspection_source_not_active" for e in result.events)
    assert not any(e.event_type in {"effect_cost_paid", "effect_inspection_started", "effect_skipped"} for e in result.events)


@pytest.mark.parametrize("code", DISCARD)
def test_empty_hand_cost_has_explicit_cancel_not_stall(code):
    state = _state(code)
    state.players["player_1"].hand = ["source-live"]
    state = apply_action(state, _play(state)).state
    options = next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect").options["invocations"][0]
    assert options["cost_payment_unavailable_reason"] == "inspection_cost_candidates_unavailable"
    result = apply_action(state, _resolve(state))
    assert result.state.pending_choice is None and not result.state.pending_effects
    assert not any(e.event_type in {"effect_cost_paid", "effect_inspection_started", "effect_skipped"} for e in result.events)


@pytest.mark.parametrize("code", REORDER)
@pytest.mark.parametrize("keep", (0, 1, 2))
def test_real_source_wait_once_then_keep_zero_one_or_two_in_order(code, keep):
    state = _state(code)
    state = apply_action(state, _play(state)).state
    inspected = apply_action(state, _resolve(state))
    assert inspected.state.cards["source-live"].orientation == "wait"
    assert sum(e.event_type == "effect_cost_paid" for e in inspected.events) == 1
    ids = list(reversed(state.players["player_1"].main_deck[:keep]))
    result = apply_action(inspected.state, _choose(inspected.state, ids))
    player = result.state.players["player_1"]
    assert player.main_deck == ids + state.players["player_1"].main_deck[2:]
    assert set(player.waiting_room) == set(state.players["player_1"].main_deck[:2]) - set(ids)
    assert player.hand == state.players["player_1"].hand
    assert result.state.pending_choice is None and not result.state.pending_effects
    assert not any(e.event_type == "effect_cost_paid" for e in result.events)
    other = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id="player_2")
    for key in ids:
        assert key not in json.dumps(other)


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("policy", ("simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"))
def test_ai_can_finish_each_native_cost_without_hidden_hand_dependency(code, policy):
    state = _state(code)
    state = apply_action(state, _play(state)).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    for _ in range(2):
        if not state.pending_choice and not state.pending_effects:
            break
        before = match_state_hash(state)
        decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
        assert isinstance(decision, SimpleAIDecision) and match_state_hash(state) == before
        changed = state.model_copy(deep=True)
        changed.cards["opponent-secret"].card.card_code = "AUDIT-hidden-different"
        assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}).action == decision.action
        result = apply_action(state, decision.action)
        assert not any(e.event_type == "effect_skipped" for e in result.events)
        state = result.state
    assert not state.pending_effects and state.pending_choice is None


@pytest.mark.parametrize("code", WAIT)
def test_sql_departure_reentry_does_not_reuse_original_source(tmp_path, code):
    state = _with_control(code)
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state))
    moved = repo.apply(state.match_id, _control(played.state, [
        {"adjustment_type": "move_card", "target_player_id": "player_1", "target_card_instance_id": "source-live", "to_zone": zone}
        for zone in ("waiting_room", "member_right")]))
    result = repo.apply(state.match_id, _resolve(moved.state))
    assert result.state.pending_choice is None and not result.state.pending_effects
    assert result.state.cards["source-live"].orientation == "active"
    assert any(e.data.get("reason") == "inspection_source_object_unavailable" for e in result.events)
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")


@pytest.mark.parametrize("code", DISCARD)
def test_sql_another_pending_effect_can_restore_hand_cost(tmp_path, code):
    state = _with_control(code)
    state.players["player_1"].hand = ["source-live"]
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state))
    assert len(played.state.pending_effects) == 2
    drawn = repo.apply(state.match_id, _control(played.state, [
        {"adjustment_type": "draw_card", "target_player_id": "player_1", "amount": 1}]))
    inspected = repo.apply(state.match_id, _resolve(drawn.state, selected_card_instance_ids=["good-member"]))
    result = repo.apply(state.match_id, _choose(inspected.state, []))
    assert "good-member" in result.state.players["player_1"].waiting_room
    assert result.state.pending_choice is None and not result.state.pending_effects
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")


@pytest.mark.parametrize("ids", (["good-member", "good-member"], ["cost"], ["opponent-secret"]))
def test_reorder_invalid_selection_is_atomic(ids):
    state = _state(REORDER[0])
    state = apply_action(state, _play(state)).state
    state = apply_action(state, _resolve(state)).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _choose(state, ids))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("code", CODES)
def test_old_executable_snapshot_shape_does_not_inherit_new_policy(code):
    effect = _state(code).effect_definitions[code + ":1"]
    raw = effect.model_dump(mode="json")
    assert raw["choice"].pop("cost_payment_policy") in {"triggered_inspection", "triggered_inspection_reorder"}
    legacy = EffectDefinition.model_validate(raw)
    assert "cost_payment_policy" not in legacy.model_dump(mode="json")["choice"]
    assert EffectDefinition.model_validate_json(legacy.model_dump_json()) == legacy


def test_all_ten_registry_entries_match_exact_text_candidates():
    from loveca.simulation.effect_candidates import _onplay_wait_inspect2_reorder
    candidates = {c.effect_id: c for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)}
    for code in CODES:
        effect = _state(code).effect_definitions[code + ":1"]
        assert EffectDefinition.model_validate(candidates[effect.effect_id].to_registry_entry()) == effect
        if code in REORDER:
            row = {"card_code": code, "text_revision_id": effect.text_revision_id,
                   "raw_text_hash": effect.raw_text_hash, "raw_effect_text_ja": effect.label_ja + "カードを1枚引く。"}
            assert _onplay_wait_inspect2_reorder(row) is None
    assert _state("PL!N-sd2-009").effect_definitions["PL!N-sd2-009:1"].choice.cost_payment_policy is None


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("policy", ("simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"))
def test_four_ai_policies_finish_unpayable_old_inspections(code, policy):
    state = _state(code)
    if code in DISCARD:
        state.players["player_1"].hand = ["source-live"]
    state = apply_action(state, _play(state)).state
    if code in WAIT:
        state.cards["source-live"].orientation = "wait"
    decision = SimpleAIController(SimpleAIPolicy(policy_version=policy)).choose_action(
        state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision) and decision.action.action_type == "resolve_effect"
    result = apply_action(state, decision.action)
    assert result.state.pending_choice is None and not result.state.pending_effects
    assert not any(e.event_type in {"effect_cost_paid", "effect_inspection_started", "effect_skipped"} for e in result.events)


@pytest.mark.parametrize("code", CODES)
def test_sql_paid_cost_and_final_choice_replay(tmp_path, code):
    state = _state(code)
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state))
    inspected = repo.apply(state.match_id, _resolve(played.state,
        **({"selected_card_instance_ids": ["cost"]} if code in DISCARD else {})))
    ids = ["good-live", "good-member"] if code in REORDER else []
    result = repo.apply(state.match_id, _choose(inspected.state, ids))
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")


@pytest.mark.parametrize("legacy", (False, True))
def test_old_unpolicied_executable_sql_retains_historical_wait_behavior(tmp_path, legacy):
    code = REORDER[0]
    state = _state(code)
    if legacy:
        raw = state.effect_definitions[code + ":1"].model_dump(mode="json")
        raw["choice"].pop("cost_payment_policy")
        state.effect_definitions[code + ":1"] = EffectDefinition.model_validate(raw)
    state = apply_action(state, _play(state)).state
    state.cards["source-live"].orientation = "wait"
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repo.apply(state.match_id, _resolve(state))
    assert (result.state.pending_choice is not None) == legacy
    if legacy:
        result = repo.apply(state.match_id, _choose(result.state, []))
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")


@pytest.mark.parametrize("defect", ("discard_cost", "public", "hand", "amount", "filter", "extra_action"))
def test_reorder_policy_rejects_other_semantic_shapes(defect):
    raw = _state(REORDER[0]).effect_definitions[REORDER[0] + ":1"].model_dump(mode="json")
    if defect == "discard_cost": raw["cost"][0]["action_type"] = "discard_from_hand"
    elif defect == "public": raw["choice"]["reveal_selected_to_opponent"] = True
    elif defect == "hand": raw["choice"]["selected_destination"] = "hand"
    elif defect == "amount": raw["choice"]["amount"] = 3
    elif defect == "filter": raw["choice"]["card_type"] = "member"
    else: raw["actions"].append({"action_type": "draw_card", "amount": 1})
    with pytest.raises(ValueError, match="inspection cost policy"):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("code", WAIT)
def test_stage_internal_position_change_preserves_payable_source(tmp_path, code):
    state = _with_control(code)
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state))
    moved = repo.apply(state.match_id, _control(played.state, [
        {"adjustment_type": "position_change", "target_player_id": "player_1", "from_slot": "center", "to_slot": "left"}]))
    inspected = repo.apply(state.match_id, _resolve(moved.state))
    assert inspected.state.pending_choice is not None
    assert inspected.state.cards["source-live"].orientation == "wait"
    result = repo.apply(state.match_id, _choose(inspected.state, []))
    assert result.state.players["player_1"].member_area["left"] == "source-live"
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")


@pytest.mark.parametrize("code", REORDER)
def test_reorder_refresh_under_remaining_top_follows_wait_cost(code):
    state = _state(code)
    state.players["player_1"].main_deck = ["good-member"]
    state.players["player_1"].waiting_room = ["good-live", "tail"]
    state = apply_action(state, _play(state)).state
    result = apply_action(state, _resolve(state))
    assert result.state.pending_choice.options["inspected_card_instance_ids"][0] == "good-member"
    assert len(result.state.pending_choice.options["inspected_card_instance_ids"]) == 2
    events = [e.event_type for e in result.events]
    assert events.index("effect_cost_paid") < events.index("deck_refreshed") < events.index("effect_inspection_started")


@pytest.mark.parametrize("work,hearts,eligible", [("love_live_superstar", 7, False), ("love_live_superstar", 8, True), ("nijigasaki", 8, False)])
def test_liella_keep_requires_actual_work_and_total_heart(work, hearts, eligible):
    state = _state("PL!SP-bp4-002")
    state.cards["good-live"].card.work_keys = [work]
    state.cards["good-live"].card.required_hearts = {"heart01": 3, "heart0": hearts - 3}
    state = apply_action(state, _play(state)).state
    inspected = apply_action(state, _resolve(state))
    assert ("good-live" in inspected.state.pending_choice.options["candidate_card_instance_ids"]) == eligible
    result = apply_action(inspected.state, _choose(inspected.state, ["good-live"] if eligible else []))
    other = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id="player_2")
    revealed = [c["instance_id"] for e in other["events"] for c in e["data"].get("revealed_cards", [])]
    assert ("good-live" in revealed) == eligible
