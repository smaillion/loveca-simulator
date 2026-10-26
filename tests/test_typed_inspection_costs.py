from functools import lru_cache
from pathlib import Path

import pytest
from test_nijigasaki_inspection import _play, _resolve, _select
from test_nijigasaki_inspection import _state as niji_state

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, MatchState, SpecialBladeHeart
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

MUSE, LIVE_COST, WAIT_COST = "PL!-pb2-032", "PL!SP-bp7-018", "PL!-pb2-008"
CODES = (MUSE, LIVE_COST, WAIT_COST)
RULE_REFERENCE_IDS = ("5.7.1", "9.4.2", "9.6.3.1.4", "9.7.3.1.1", "10.2.2.2", "10.2.3", "11.4.2")


@lru_cache
def _candidate(code):
    return next(c for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
                if c.effect_id == code + ":1")


def _state(code, *, legacy=False):
    state = niji_state(code)
    for key in ("good-member", "good-live", "blade-heart", "tail"):
        state.cards[key].card.work_keys = ["love_live"]
    state.cards["wrong-work"].card.work_keys = ["nijigasaki"]
    state.cards["good-live"].card.required_hearts = {"heart01": 3, "heart0": 5}
    if code == LIVE_COST:
        state.cards["cost"].card.card_type = "live"
    state.players["player_1"].hand.append("deck-member-1")
    if legacy:
        effect = state.effect_definitions[code + ":1"]
        raw = effect.model_dump(mode="json")
        raw.update(choice=None, cost=[], cost_choice=None, execution_mode="manual_resolution",
                   simulation_support="manual_resolution", review_status="parsed_draft", is_optional=True,
                   actions=[{"action_type": "manual_resolution"}])
        state.effect_definitions[effect.effect_id] = EffectDefinition.model_validate(raw)
    return state


def _begin(code, **kwargs):
    state = _state(code, **kwargs)
    return apply_action(state, _play(state))


def _inspect(state, code):
    return apply_action(state, _resolve(state, **({} if code == WAIT_COST else {"selected_card_instance_ids": ["cost"]})))


@pytest.mark.parametrize("code", CODES)
def test_actual_onplay_starts_structured_cost_not_manual(code):
    result = _begin(code)
    assert result.state.pending_effects[0].effect_id == code + ":1"
    assert next(a for a in result.legal_actions if a.action_type == "resolve_effect").options["invocations"][0]["execution_mode"] == "prompt_then_resolve"


@pytest.mark.parametrize("code,revision,hash_value", [
    (MUSE, 1005, "28998d4467050b6c2aa570b4f85c107638917032b8c3a685ea8829039b317c22"),
    (LIVE_COST, 905, "c29d62301ccee25bdb6cd7dfde1cf21e78fdb10ae157f6100e169bede22a2df4"),
    (WAIT_COST, 981, "da519a6113a9c123c5adef02778b427fa9c3421b66301bf83ce1f19bdd088ee0")])
def test_exact_text_identity_and_choice_contract(code, revision, hash_value):
    effect = _state(code).effect_definitions[code + ":1"]
    assert effect == EffectDefinition.model_validate(_candidate(code).to_registry_entry())
    assert (effect.text_revision_id, effect.raw_text_hash) == (revision, hash_value)
    assert effect.is_optional == (code != MUSE)
    assert effect.choice.minimum == (1 if code == LIVE_COST else 0)
    assert effect.choice.maximum == 1
    assert effect.choice.reveal_selected_to_opponent == (code != LIVE_COST)
    assert effect.simulation_support == "test_validated_executable" and effect.review_status == "test_validated"


@pytest.mark.parametrize("code", CODES)
def test_cost_and_selected_zones_follow_real_card_text(code):
    state = _begin(code).state
    inspected = _inspect(state, code)
    count = 4 if code == WAIT_COST else 5
    assert inspected.state.pending_choice.options["inspected_card_instance_ids"] == state.players["player_1"].main_deck[:count]
    assert ("cost" in inspected.state.players["player_1"].waiting_room) == (code != WAIT_COST)
    assert inspected.state.cards["source-live"].orientation == ("wait" if code == WAIT_COST else "active")
    selected = "good-live" if code == WAIT_COST else "good-member"
    final = apply_action(inspected.state, _select(inspected.state, [selected]))
    player = final.state.players["player_1"]
    assert set(player.hand) == ({"deck-member-1", selected, "cost"} if code == WAIT_COST else {"deck-member-1", selected})
    assert set(player.waiting_room) == (set(state.players["player_1"].main_deck[:count]) - {selected}) | ({"cost"} if code != WAIT_COST else set())
    assert player.main_deck == state.players["player_1"].main_deck[count:]
    assert not final.state.pending_effects and final.state.pending_choice is None


def test_mandatory_discard_cannot_be_declined_but_keep_can_be_zero():
    state = _begin(MUSE).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, accepted=False))
    assert match_state_hash(state) == before
    inspected = _inspect(state, MUSE)
    final = apply_action(inspected.state, _select(inspected.state, []))
    assert final.state.players["player_1"].hand == ["deck-member-1"]
    assert "cost" in final.state.players["player_1"].waiting_room


@pytest.mark.parametrize("code", (LIVE_COST, WAIT_COST))
def test_optional_cost_decline_has_no_payment_or_look(code):
    state = _begin(code).state
    result = apply_action(state, _resolve(state, accepted=False))
    assert result.state.players["player_1"].hand == state.players["player_1"].hand
    assert result.state.players["player_1"].main_deck == state.players["player_1"].main_deck
    assert result.state.cards["source-live"].orientation == "active"
    assert not result.state.pending_effects and result.state.pending_choice is None


@pytest.mark.parametrize("code", (MUSE, LIVE_COST))
@pytest.mark.parametrize("ids", [[], ["source-live"], ["opponent-secret"], ["cost", "cost"]])
def test_bad_discard_cost_is_atomic_before_looking(code, ids):
    state = _begin(code).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, selected_card_instance_ids=ids))
    assert match_state_hash(state) == before and state.pending_choice is None


def test_live_card_cost_cannot_discard_member_in_own_hand():
    state = _begin(LIVE_COST).state
    options = next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect").options["invocations"][0]
    assert options["candidate_card_instance_ids"] == ["cost"]
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, selected_card_instance_ids=["deck-member-1"]))
    assert match_state_hash(state) == before


def test_self_wait_cost_cannot_be_paid_twice():
    state = _begin(WAIT_COST).state
    state.cards["source-live"].orientation = "wait"
    result = _inspect(state, WAIT_COST)
    assert not result.state.pending_effects and result.state.pending_choice is None
    assert result.state.cards["source-live"].orientation == "wait"
    assert result.state.players["player_1"].main_deck == state.players["player_1"].main_deck
    assert any(e.event_type == "effect_not_activatable" and e.data["reason"] == "inspection_source_not_active" for e in result.events)


@pytest.mark.parametrize("code", (MUSE, LIVE_COST))
def test_no_legal_hand_cost_does_not_stall_native_onplay(code):
    state = _state(code)
    state.players["player_1"].hand = ["source-live"] + (["deck-member-1"] if code == LIVE_COST else [])
    result = apply_action(state, _play(state))
    options = next(a for a in result.legal_actions if a.action_type == "resolve_effect").options["invocations"][0]
    assert options["cost_payment_unavailable_reason"] == "inspection_cost_candidates_unavailable"
    final = apply_action(result.state, _resolve(result.state))
    assert not final.state.pending_effects and final.state.pending_choice is None
    assert any(e.event_type == "effect_not_activatable" for e in final.events)
    assert not any(e.event_type in {"effect_cost_paid", "effect_inspection_started", "effect_skipped"} for e in final.events)


@pytest.mark.parametrize("code,ids", [(MUSE, ["good-live"]), (MUSE, ["wrong-work"]), (MUSE, ["blade-heart"]),
    (WAIT_COST, ["good-member"]), (WAIT_COST, ["wrong-work"]), (WAIT_COST, ["deck-live-1"]),
    (LIVE_COST, []), (LIVE_COST, ["good-member", "good-live"]), (LIVE_COST, ["cost"])])
def test_filtered_or_missing_keep_is_atomic(code, ids):
    state = _inspect(_begin(code).state, code).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _select(state, ids))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("kind", ["heart01", "heart02", "heart03", "heart04", "heart05", "heart06", "draw", "score", "all_color", "unknown"])
def test_muse_excludes_every_blade_heart_kind(kind):
    state = _begin(MUSE).state
    card = state.cards["blade-heart"].card
    card.blade_heart_color_slot = kind if kind.startswith("heart") else None
    card.special_blade_hearts = [] if kind.startswith("heart") else [SpecialBladeHeart(effect_type=kind, source_alt="AUDIT")]
    inspected = _inspect(state, MUSE)
    assert "blade-heart" not in inspected.state.pending_choice.options["candidate_card_instance_ids"]


@pytest.mark.parametrize("hearts,eligible", [({"heart01": 7}, False), ({"heart01": 8}, True),
    ({"heart01": 3, "heart0": 5}, True), ({"heart01": 3, "heart0": 4}, False)])
def test_wait_cost_search_counts_total_required_hearts(hearts, eligible):
    state = _begin(WAIT_COST).state
    state.cards["good-live"].card.required_hearts = hearts
    result = _inspect(state, WAIT_COST)
    assert ("good-live" in result.state.pending_choice.options["candidate_card_instance_ids"]) == eligible
    final = apply_action(result.state, _select(result.state, ["good-live"] if eligible else []))
    assert final.state.pending_choice is None and not final.state.pending_effects


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("legacy", (False, True))
def test_sql_replay_preserves_old_manual_and_typed_costs(tmp_path, code, legacy):
    state = _state(code, legacy=legacy)
    assert MatchState.model_validate_json(state.model_dump_json()) == state
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repository.apply(state.match_id, _play(state))
    if not legacy:
        result = repository.apply(state.match_id, _resolve(result.state, **({} if code == WAIT_COST else {"selected_card_instance_ids": ["cost"]})))
        result = repository.apply(state.match_id, _select(result.state, ["good-live" if code == WAIT_COST else "good-member"]))
    replay = repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")


@pytest.mark.parametrize("code", CODES)
def test_private_look_and_public_or_private_keep_are_distinct(code):
    inspected = _inspect(_begin(code).state, code)
    other = _match_state_payload(inspected.state, events=inspected.events, legal_actions=inspected.legal_actions, player_id="player_2")
    assert "good-member" not in other["state"]["cards"] and "good-live" not in other["state"]["cards"]
    target = "good-live" if code == WAIT_COST else "good-member"
    result = apply_action(inspected.state, _select(inspected.state, [target]))
    other = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id="player_2")
    revealed = [c["instance_id"] for e in other["events"] for c in e["data"].get("revealed_cards", [])]
    assert (target in revealed) == (code != LIVE_COST)
    if code == LIVE_COST:
        assert target not in other["state"]["cards"]


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_policies_resolve_typed_costs_without_hidden_dependency(code, policy):
    state = _begin(code).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    for _ in range(2):
        if not state.pending_effects and not state.pending_choice:
            break
        before = match_state_hash(state)
        decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
        assert isinstance(decision, SimpleAIDecision) and match_state_hash(state) == before
        changed = state.model_copy(deep=True)
        changed.cards["opponent-secret"].card.card_code = "AUDIT-CHANGED-PRIVATE"
        assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}).action == decision.action
        state = apply_action(state, decision.action).state
    assert not state.pending_effects and state.pending_choice is None


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_policies_finish_unpayable_cost_without_error_skip(code, policy):
    state = _state(code)
    if code != WAIT_COST:
        state.players["player_1"].hand = ["source-live"]
    state = apply_action(state, _play(state)).state
    if code == WAIT_COST:
        state.cards["source-live"].orientation = "wait"
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision)
    assert decision.action.action_type == "resolve_effect"
    result = apply_action(state, decision.action)
    assert not result.state.pending_effects and result.state.pending_choice is None
    assert not any(e.event_type in {"effect_cost_paid", "effect_skipped", "effect_inspection_started"} for e in result.events)


def _with_control(code):
    state = _state(code)
    effect = state.effect_definitions[code + ":1"]
    raw = effect.model_dump(mode="json")
    raw.update(effect_id="AUDIT-control:1", choice=None, cost=[], cost_choice=None,
               execution_mode="manual_resolution", simulation_support="manual_resolution",
               review_status="parsed_draft", is_optional=False, actions=[{"action_type": "manual_resolution"}])
    state.effect_definitions["AUDIT-control:1"] = EffectDefinition.model_validate(raw)
    state.cards["source-live"].card.effect_ids.append("AUDIT-control:1")
    state.effect_order_policy = "ap_nap_player_choice"
    return state


def _control(state, adjustments):
    control = next(i for i in state.pending_effects if i.effect_id == "AUDIT-control:1")
    return ActionRequest(action_type="manual_adjustment", player_id="player_1", expected_revision=state.revision,
        payload={"source_invocation_id": control.invocation_id, "source_effect_id": control.effect_id,
                 "source_card_instance_id": control.source_card_instance_id, "adjustments": adjustments})


def test_sql_source_departure_and_same_id_reentry_cannot_pay_old_wait_cost(tmp_path):
    state = _with_control(WAIT_COST)
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repository.apply(state.match_id, _play(state))
    moved = repository.apply(state.match_id, _control(played.state, [
        {"adjustment_type": "move_card", "target_player_id": "player_1", "target_card_instance_id": "source-live", "to_zone": zone}
        for zone in ("waiting_room", "member_right")]))
    assert moved.state.pending_effects[0].trigger_data["original_source_stage_object_departed"] is True
    result = repository.apply(state.match_id, _resolve(moved.state))
    assert result.state.cards["source-live"].orientation == "active"
    assert result.state.players["player_1"].member_area["right"] == "source-live"
    assert any(e.data.get("reason") == "inspection_source_object_unavailable" for e in result.events)
    assert result.state.pending_choice is None and not result.state.pending_effects
    replay = repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")


@pytest.mark.parametrize("code", (MUSE, LIVE_COST))
def test_other_pending_effect_can_provide_cost_before_resolution(tmp_path, code):
    state = _with_control(code)
    state.players["player_1"].hand = ["source-live"]
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repository.apply(state.match_id, _play(state))
    assert {i.effect_id for i in played.state.pending_effects} == {code + ":1", "AUDIT-control:1"}
    drawn = repository.apply(state.match_id, _control(played.state, [
        {"adjustment_type": "draw_card", "target_player_id": "player_1", "amount": 2}]))
    target = "good-live" if code == LIVE_COST else "good-member"
    inspected = repository.apply(state.match_id, _resolve(drawn.state, selected_card_instance_ids=[target]))
    assert inspected.state.pending_choice is not None
    kept = inspected.state.pending_choice.options["candidate_card_instance_ids"]
    result = repository.apply(state.match_id, _select(inspected.state, kept[:1] if code == LIVE_COST else []))
    assert not result.state.pending_effects and result.state.pending_choice is None
    assert target in result.state.players["player_1"].waiting_room
    replay = repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")


@pytest.mark.parametrize("defect", ["trigger", "timing", "cost_type", "cost_amount", "cost_target", "duration", "action", "condition"])
def test_cost_policy_rejects_unmodeled_semantics(defect):
    raw = _state(MUSE).effect_definitions[MUSE + ":1"].model_dump(mode="json")
    if defect == "trigger": raw["trigger"] = "live_started"
    elif defect == "timing": raw["timing"] = "live_start"
    elif defect == "cost_type": raw["cost"][0]["action_type"] = "pay_energy"
    elif defect == "cost_amount": raw["cost"][0]["amount"] = 2
    elif defect == "cost_target": raw["cost_choice"]["target_player"] = "opponent"
    elif defect == "duration": raw["duration"] = "live"
    elif defect == "condition": raw["condition"] = {"minimum_active_energy": 2}
    else: raw["actions"].append({"action_type": "draw_card", "amount": 1})
    with pytest.raises(ValueError, match="inspection cost policy"):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("code", CODES)
def test_new_policy_is_explicit_and_candidate_requires_complete_segment(code):
    from loveca.simulation.effect_candidates import _onplay_typed_cost_inspection
    effect = _state(code).effect_definitions[code + ":1"]
    assert effect.choice.cost_payment_policy == "triggered_inspection"
    raw = effect.model_dump(mode="json")
    raw["choice"].pop("cost_payment_policy")
    old = EffectDefinition.model_validate(raw)
    assert "cost_payment_policy" not in old.model_dump(mode="json")["choice"]
    row = {"card_code": code, "text_revision_id": effect.text_revision_id,
           "raw_text_hash": effect.raw_text_hash, "raw_effect_text_ja": effect.label_ja + "カードを1枚引く。"}
    assert _onplay_typed_cost_inspection(row) is None


@pytest.mark.parametrize("payload", [{"selected_card_instance_ids": None}, {"selected_card_instance_ids": {}},
    {"energy_instance_ids": ["missing"]}, {"selected_count": 0}, {"selected_card_instance_ids_by_group": {}}, {"to_slot": "right"}])
def test_unpayable_cost_rejects_malformed_selection_without_removing_pending(payload):
    state = _state(MUSE)
    state.players["player_1"].hand = ["source-live"]
    state = apply_action(state, _play(state)).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, **payload))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("code", CODES)
def test_refresh_follows_cost_and_keeps_existing_top_card(code):
    state = _begin(code).state
    state.players["player_1"].main_deck = ["good-member"]
    state.players["player_1"].waiting_room = ["good-live", "wrong-work", "blade-heart", "tail"]
    result = _inspect(state, code)
    inspected = result.state.pending_choice.options["inspected_card_instance_ids"]
    assert inspected[0] == "good-member" and len(inspected) == (4 if code == WAIT_COST else 5)
    events = [e.event_type for e in result.events]
    assert events.index("effect_cost_paid") < events.index("deck_refreshed") < events.index("effect_inspection_started")
    final = apply_action(result.state, _select(result.state, ["good-member"] if code == LIVE_COST else []))
    assert final.state.pending_choice is None and not final.state.pending_effects


@pytest.mark.parametrize("defect", ("missing_snapshot", "not_on_stage"))
def test_wait_cost_needs_original_source_on_stage(defect):
    state = _begin(WAIT_COST).state
    if defect == "missing_snapshot":
        state.pending_effects[0].trigger_data.pop("original_source_stage_object")
    else:
        state.players["player_1"].member_area["center"] = None
        state.players["player_1"].waiting_room.append("source-live")
    result = apply_action(state, _resolve(state))
    assert not result.state.pending_effects and result.state.pending_choice is None
    assert any(e.event_type == "effect_not_activatable" for e in result.events)
    assert not any(e.event_type in {"effect_cost_paid", "effect_inspection_started"} for e in result.events)
