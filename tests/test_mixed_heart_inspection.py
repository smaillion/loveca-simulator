import json
from pathlib import Path

import pytest
from test_nijigasaki_inspection import _play, _resolve, _select
from test_nijigasaki_inspection import _state as _base_state
from test_typed_inspection_costs import _control, _with_control
from test_work_unit_inspection import _candidates

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effect_candidates import _onplay_audited_discard_inspection
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ManualModifier, SpecialBladeHeart
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

IDENTITIES = (
    ("PL!S-pb1-013", 533, "4d92cee4ab0ad03cba3670835bb4efa69a33af036e525e32a743f38f11abb535", "heart04"),
    ("PL!S-pb1-014", 534, "e417043e8f92e6ca8920ee7507cd4e01cb579326bbe09b6624293009928ba2d9", "heart02"),
    ("PL!S-pb1-015", 535, "c2a45736031a7dcb8807277fdb22b18a2472f0ca9bd7e7ffcba7f1d2a8331eca", "heart05"),
)
CODES = tuple(row[0] for row in IDENTITIES)
RULE_REFERENCE_IDS = ("2.7.1", "2.9.1", "2.11.1", "4.1.4", "5.7.1", "9.3.4", "9.4.2", "9.7.3.2", "10.2.2.2", "10.2.3")


def _color(code):
    return next(row[3] for row in IDENTITIES if row[0] == code)


def _state(code, *, empty=False):
    state = _base_state(code)
    color = _color(code)
    state.cards["good-member"].card.basic_hearts = {color: 2}
    state.cards["good-member"].card.work_keys = ["love_live"]
    state.cards["good-live"].card.required_hearts = {color: 2}
    state.cards["good-live"].card.work_keys = ["love_live_superstar"]
    state.cards["wrong-work"].card.basic_hearts = {"heart01": 3}
    state.cards["blade-heart"].card.basic_hearts = {color: 1}
    state.cards["blade-heart"].card.blade_heart_color_slot = color
    state.cards["blade-heart"].card.special_blade_hearts = [SpecialBladeHeart(effect_type="all_color", source_alt="ALL", value=3)]
    state.cards["tail"].card.basic_hearts = {color: 3}
    if empty:
        state.players["player_1"].hand = ["source-live"]
    return state


def _begin(code, *, empty=False):
    state = _state(code, empty=empty)
    return apply_action(state, _play(state)).state


def _inspect(state):
    return apply_action(state, _resolve(state, selected_card_instance_ids=["cost"]))


@pytest.mark.parametrize("code,revision,raw_hash,color", IDENTITIES)
def test_exact_segment_real_fee_and_mixed_filter_contract(code, revision, raw_hash, color):
    state = _state(code)
    effect = state.effect_definitions[code + ":1"]
    assert state.cards["source-live"].card.cost == 4
    assert (effect.text_revision_id, effect.raw_text_hash) == (revision, raw_hash)
    assert effect == EffectDefinition.model_validate(_candidates()[effect.effect_id].to_registry_entry())
    assert effect.choice.cost_payment_policy == "triggered_inspection"
    assert effect.choice.amount == 4 and effect.choice.minimum == 0 and effect.choice.maximum == 1
    assert effect.choice.heart_color_slot == color and effect.choice.minimum_heart_count == 2
    assert effect.choice.card_type is None and effect.choice.work_key is None and effect.choice.unit_key is None
    assert effect.review_status == "test_validated" and effect.simulation_support == "test_validated_executable"
    row = {"card_code": code, "text_revision_id": revision, "raw_text_hash": raw_hash, "raw_effect_text_ja": effect.label_ja}
    assert _onplay_audited_discard_inspection({**row, "raw_effect_text_ja": effect.label_ja + "カードを1枚引く。"}) is None
    assert _onplay_audited_discard_inspection({**row, "card_code": "AUDIT-unknown"}) is None


@pytest.mark.parametrize("code", CODES)
def test_unpayable_cost_ends_without_inspecting_or_skip(code):
    state = _begin(code, empty=True)
    option = next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect").options["invocations"][0]
    assert option["cost_payment_unavailable_reason"] == "inspection_cost_candidates_unavailable"
    result = apply_action(state, _resolve(state))
    assert not result.state.pending_effects and result.state.pending_choice is None
    assert result.state.players["player_1"].main_deck == state.players["player_1"].main_deck
    assert not any(e.event_type in {"effect_cost_paid", "effect_inspection_started", "effect_skipped"} for e in result.events)


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("card_type", ("member", "live"))
@pytest.mark.parametrize("count", (0, 1, 2, 3))
@pytest.mark.parametrize("variant", ("native", "wrong_color", "wrong_field"))
def test_heart_threshold_uses_only_the_named_card_information(code, card_type, count, variant):
    state = _state(code)
    color = _color(code)
    probe = state.cards["good-member"].card
    probe.card_type = card_type
    probe.basic_hearts, probe.required_hearts = {}, {}
    field = "basic_hearts" if card_type == "member" else "required_hearts"
    if variant == "wrong_field":
        field = "required_hearts" if card_type == "member" else "basic_hearts"
    setattr(probe, field, {"heart01" if variant == "wrong_color" else color: count})
    probe.blade_heart_color_slot = color
    probe.special_blade_hearts = [SpecialBladeHeart(effect_type="all_color", source_alt="ALL", value=99)]
    state.players["player_1"].manual_modifiers = [
        ManualModifier(modifier_id="AUDIT-global-heart", modifier_type="heart", duration="turn", created_turn=1, amount=99, color_slot=color),
        ManualModifier(modifier_id="AUDIT-live-requirement", modifier_type="required_heart", duration="turn", created_turn=1, amount=-99, color_slot=color),
    ]
    inspected = _inspect(apply_action(state, _play(state)).state)
    candidates = inspected.state.pending_choice.options["candidate_card_instance_ids"]
    expected = variant == "native" and count >= 2
    assert ("good-member" in candidates) == expected
    assert "good-live" in candidates and "blade-heart" not in candidates and "tail" not in candidates
    before = match_state_hash(inspected.state)
    if expected:
        final = apply_action(inspected.state, _select(inspected.state, ["good-member"]))
        assert final.state.players["player_1"].hand == ["good-member"]
    else:
        with pytest.raises(IllegalActionError):
            apply_action(inspected.state, _select(inspected.state, ["good-member"]))
    assert match_state_hash(inspected.state) == before


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("cost_type", ("member", "live"))
@pytest.mark.parametrize("target", ("good-member", "good-live", None))
def test_native_fee_payment_private_look_and_public_zero_or_one_keep(code, cost_type, target):
    state = _state(code)
    state.cards["cost"].card.card_type = cost_type
    state = apply_action(state, _play(state)).state
    assert all(state.cards[key].orientation == "wait" for key in state.players["player_1"].energy_area)
    inspected = _inspect(state)
    choice = inspected.state.pending_choice.options
    assert choice["inspected_card_instance_ids"] == state.players["player_1"].main_deck[:4]
    assert set(choice["candidate_card_instance_ids"]) == {"good-member", "good-live"}
    assert "cost" in inspected.state.players["player_1"].waiting_room
    assert sum(e.event_type == "effect_cost_paid" for e in inspected.events) == 1
    other = _match_state_payload(inspected.state, events=inspected.events, legal_actions=inspected.legal_actions, player_id="player_2")
    assert "good-member" not in json.dumps(other) and "good-live" not in json.dumps(other)
    final = apply_action(inspected.state, _select(inspected.state, [target] if target else []))
    assert final.state.players["player_1"].hand == ([target] if target else [])
    assert not final.state.pending_effects and final.state.pending_choice is None
    assert not any(e.event_type == "effect_cost_paid" for e in final.events)
    other = _match_state_payload(final.state, events=final.events, legal_actions=final.legal_actions, player_id="player_2")
    revealed = [c["instance_id"] for e in other["events"] for c in e["data"].get("revealed_cards", [])]
    assert target in revealed if target else not revealed


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("ids", ([], ["opponent-secret"], ["source-live"], ["cost", "cost"]))
def test_invalid_cost_is_atomic(code, ids):
    state = _begin(code)
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, selected_card_instance_ids=ids))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("ids", (["tail"], ["blade-heart"], ["good-live", "good-live"]))
def test_invalid_or_uninspected_keep_is_atomic(code, ids):
    state = _inspect(_begin(code)).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _select(state, ids))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("code", CODES)
def test_optional_cost_decline_and_no_matching_card(code):
    state = _begin(code)
    declined = apply_action(state, _resolve(state, accepted=False))
    assert declined.state.players["player_1"].hand == ["cost"]
    assert declined.state.players["player_1"].main_deck == state.players["player_1"].main_deck
    for key in state.players["player_1"].main_deck:
        state.cards[key].card.basic_hearts, state.cards[key].card.required_hearts = {}, {}
    inspected = _inspect(state)
    assert inspected.state.pending_choice.options["candidate_card_instance_ids"] == []
    final = apply_action(inspected.state, _select(inspected.state, []))
    assert not final.state.pending_effects and final.state.pending_choice is None


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("legacy", (False, True))
@pytest.mark.parametrize("empty", (False, True))
def test_sql_replay_preserves_old_and_new_cost_policy(tmp_path, code, legacy, empty):
    state = _state(code, empty=empty)
    if legacy:
        raw = state.effect_definitions[code + ":1"].model_dump(mode="json")
        raw["choice"].pop("cost_payment_policy")
        state.effect_definitions[code + ":1"] = EffectDefinition.model_validate(raw)
        assert "cost_payment_policy" not in state.effect_definitions[code + ":1"].model_dump(mode="json")["choice"]
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state))
    if empty:
        if legacy:
            with pytest.raises(IllegalActionError):
                repo.apply(state.match_id, _resolve(played.state))
            assert match_state_hash(repo.get_state(state.match_id)) == match_state_hash(played.state)
        final = repo.apply(state.match_id, _resolve(played.state, accepted=not legacy))
    else:
        inspected = repo.apply(state.match_id, _resolve(played.state, selected_card_instance_ids=["cost"]))
        final = repo.apply(state.match_id, _select(inspected.state, ["good-live"]))
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("code", CODES)
def test_pending_draw_can_fund_the_cost(tmp_path, code):
    state = _state(code, empty=True)
    state.effect_definitions["AUDIT-control:1"] = _with_control(code).effect_definitions["AUDIT-control:1"]
    state.cards["source-live"].card.effect_ids.append("AUDIT-control:1")
    state.effect_order_policy = "ap_nap_player_choice"
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state))
    assert len(played.state.pending_effects) == 2
    drawn = repo.apply(state.match_id, _control(played.state, [{"adjustment_type": "draw_card", "target_player_id": "player_1", "amount": 1}]))
    inspected = repo.apply(state.match_id, _resolve(drawn.state, selected_card_instance_ids=["good-member"]))
    final = repo.apply(state.match_id, _select(inspected.state, ["good-live"]))
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("empty", (False, True))
@pytest.mark.parametrize("policy", ("simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"))
def test_four_ai_policies_are_legal_private_and_non_mutating(code, empty, policy):
    state = _begin(code, empty=empty)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    for _ in range(2):
        if not state.pending_effects and not state.pending_choice:
            break
        before = match_state_hash(state)
        decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
        assert isinstance(decision, SimpleAIDecision) and match_state_hash(state) == before
        changed = state.model_copy(deep=True)
        changed.cards["opponent-secret"].card.card_code = "AUDIT-private-changed"
        assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}).action == decision.action
        result = apply_action(state, decision.action)
        assert not any(e.event_type == "effect_skipped" for e in result.events)
        state = result.state
    assert not state.pending_effects and state.pending_choice is None


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("only_cost", (False, True))
def test_refresh_happens_after_cost_and_preserves_existing_top(code, only_cost):
    state = _state(code)
    state.players["player_1"].main_deck = [] if only_cost else ["good-member"]
    state.players["player_1"].waiting_room = [] if only_cost else ["good-live", "wrong-work", "blade-heart", "tail", "deck-live-1"]
    inspected = _inspect(apply_action(state, _play(state)).state)
    events = [e.event_type for e in inspected.events]
    assert events.index("effect_cost_paid") < events.index("deck_refreshed") < events.index("effect_inspection_started")
    assert inspected.state.pending_choice.options["inspected_card_instance_ids"][0] == ("cost" if only_cost else "good-member")
    final = apply_action(inspected.state, _select(inspected.state, []))
    assert not final.state.pending_effects and final.state.pending_choice is None
