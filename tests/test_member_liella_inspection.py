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
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

IDENTITIES = (
    ("PL!S-bp3-004", 462, "04e69b1ae768c27e4d713ccb379107cea5ad1656a8f70cb9c66947a47f6e5e31", 5, 4),
    ("PL!S-bp3-009", 467, "ce74f742958bfe6bba61e1f4e2bf3c11b7beaacb7886054e986cc4b0203e23ef", 9, 6),
    ("PL!SP-bp1-005", 644, "efde6769811f6991ccbc525e43fdfaeea6caf74dfa1613993189158522dc86ca", 2, 5),
    ("PL!SP-bp2-007", 561, "f525dfb8215b650736858c9e15a1da22035a97deccbfb7fc8de1bfb409725a4a", 5, 5),
    ("PL!SP-pb2-017", 813, "f525dfb8215b650736858c9e15a1da22035a97deccbfb7fc8de1bfb409725a4a", 7, 5),
)
CODES = tuple(row[0] for row in IDENTITIES)
ANY_CARD = "PL!SP-bp1-005"
UNFILTERED_MEMBER = "PL!S-bp3-004"
AQOURS = "PL!S-bp3-009"
EXPECTED = {
    UNFILTERED_MEMBER: {"good-member", "wrong-work", "blade-heart"},
    AQOURS: {"good-member", "blade-heart", "tail", "deck-live-1"},
    ANY_CARD: {"good-member", "good-live", "blade-heart", "tail"},
    "PL!SP-bp2-007": {"good-member", "blade-heart", "tail"},
    "PL!SP-pb2-017": {"good-member", "blade-heart", "tail"},
}
RULE_REFERENCE_IDS = ("5.7.1", "9.4.2", "9.7.3.1.1", "9.7.3.2", "10.2.2.2", "10.2.3")


def _state(code, *, empty=False):
    state = _base_state(code)
    work = "love_live_sunshine" if code in {UNFILTERED_MEMBER, AQOURS} else "love_live_superstar"
    for key in state.players["player_1"].main_deck:
        state.cards[key].card.work_keys = [work]
        state.cards[key].card.unit_keys = ["other-unit"]
    state.cards["wrong-work"].card.work_keys = ["nijigasaki"]
    state.cards["deck-live-1"].card.card_type = "member"
    if empty:
        state.players["player_1"].hand = ["source-live"]
    return state


def _begin(code, *, empty=False):
    state = _state(code, empty=empty)
    return apply_action(state, _play(state)).state


def _inspect(state):
    return apply_action(state, _resolve(state, selected_card_instance_ids=["cost"]))


@pytest.mark.parametrize("code,revision,raw_hash,fee,amount", IDENTITIES)
def test_exact_card_segment_fee_and_candidate_contract(code, revision, raw_hash, fee, amount):
    state = _state(code)
    effect = state.effect_definitions[code + ":1"]
    assert state.cards["source-live"].card.cost == fee
    assert (effect.text_revision_id, effect.raw_text_hash) == (revision, raw_hash)
    assert effect == EffectDefinition.model_validate(_candidates()[effect.effect_id].to_registry_entry())
    assert effect.choice.cost_payment_policy == "triggered_inspection"
    assert effect.choice.amount == amount and effect.choice.minimum == 0 and effect.choice.maximum == 1
    assert effect.choice.card_type == (None if code == ANY_CARD else "member")
    assert effect.choice.work_key == (None if code == UNFILTERED_MEMBER else "love_live_sunshine" if code == AQOURS else "love_live_superstar")
    assert effect.choice.unit_key is None and effect.choice.reveal_selected_to_opponent is True
    assert effect.review_status == "test_validated" and effect.simulation_support == "test_validated_executable"
    row = {"card_code": code, "text_revision_id": revision, "raw_text_hash": raw_hash, "raw_effect_text_ja": effect.label_ja}
    assert _onplay_audited_discard_inspection({**row, "raw_effect_text_ja": effect.label_ja + "カードを1枚引く。"}) is None
    assert _onplay_audited_discard_inspection({**row, "card_code": "AUDIT-unknown"}) is None


@pytest.mark.parametrize("code", CODES)
def test_empty_cost_is_explicit_and_cannot_peek(code):
    state = _begin(code, empty=True)
    option = next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect").options["invocations"][0]
    assert option["cost_payment_unavailable_reason"] == "inspection_cost_candidates_unavailable"
    result = apply_action(state, _resolve(state))
    assert result.state.pending_choice is None and not result.state.pending_effects
    assert result.state.players["player_1"].main_deck == state.players["player_1"].main_deck
    assert not any(e.event_type in {"effect_cost_paid", "effect_inspection_started", "effect_skipped"} for e in result.events)


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("cost_type", ("member", "live"))
@pytest.mark.parametrize("keep", (False, True))
def test_real_fee_and_hand_cost_once_with_zero_or_one_keep(code, cost_type, keep):
    state = _state(code)
    state.cards["cost"].card.card_type = cost_type
    state = apply_action(state, _play(state)).state
    assert all(state.cards[key].orientation == "wait" for key in state.players["player_1"].energy_area)
    inspected = _inspect(state)
    choice = inspected.state.pending_choice.options
    assert set(choice["candidate_card_instance_ids"]) == EXPECTED[code]
    amount = next(row[4] for row in IDENTITIES if row[0] == code)
    assert choice["inspected_card_instance_ids"] == state.players["player_1"].main_deck[:amount]
    assert "cost" in inspected.state.players["player_1"].waiting_room
    assert sum(e.event_type == "effect_cost_paid" for e in inspected.events) == 1
    final = apply_action(inspected.state, _select(inspected.state, ["good-member"] if keep else []))
    assert final.state.players["player_1"].hand == (["good-member"] if keep else [])
    assert final.state.pending_choice is None and not final.state.pending_effects
    assert not any(e.event_type == "effect_cost_paid" for e in final.events)


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("target", ("good-member", "good-live", "wrong-work", "blade-heart", "tail", "deck-live-1"))
def test_each_type_work_and_inspection_boundary_is_enforced(code, target):
    state = _inspect(_begin(code)).state
    before = match_state_hash(state)
    if target in EXPECTED[code]:
        result = apply_action(state, _select(state, [target]))
        assert result.state.players["player_1"].hand == [target]
    else:
        with pytest.raises(IllegalActionError):
            apply_action(state, _select(state, [target]))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("ids", ([], ["opponent-secret"], ["source-live"], ["cost", "cost"]))
def test_invalid_hand_cost_is_atomic(code, ids):
    state = _begin(code)
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, selected_card_instance_ids=ids))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("code", CODES)
def test_optional_decline_and_empty_filtered_candidates(code):
    state = _begin(code)
    declined = apply_action(state, _resolve(state, accepted=False))
    assert declined.state.players["player_1"].hand == ["cost"]
    assert declined.state.players["player_1"].main_deck == state.players["player_1"].main_deck
    for key in state.players["player_1"].main_deck:
        state.cards[key].card.card_type = "live"
        state.cards[key].card.work_keys = ["nijigasaki"]
    inspected = _inspect(state)
    assert inspected.state.pending_choice.options["candidate_card_instance_ids"] == []
    final = apply_action(inspected.state, _select(inspected.state, []))
    assert final.state.pending_choice is None and not final.state.pending_effects


@pytest.mark.parametrize("code", CODES)
def test_private_inspection_then_public_keep(code):
    inspected = _inspect(_begin(code))
    other = _match_state_payload(inspected.state, events=inspected.events, legal_actions=inspected.legal_actions, player_id="player_2")
    assert "good-member" not in json.dumps(other) and "good-live" not in json.dumps(other)
    target = "good-live" if code == ANY_CARD else "good-member"
    final = apply_action(inspected.state, _select(inspected.state, [target]))
    other = _match_state_payload(final.state, events=final.events, legal_actions=final.legal_actions, player_id="player_2")
    assert target in [c["instance_id"] for e in other["events"] for c in e["data"].get("revealed_cards", [])]


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("legacy", (False, True))
@pytest.mark.parametrize("empty", (False, True))
def test_sql_replay_old_and_new_cost_policy(tmp_path, code, legacy, empty):
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
        final = repo.apply(state.match_id, _select(inspected.state, ["good-member"]))
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("code", CODES)
def test_another_pending_draw_can_fund_inspection(tmp_path, code):
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
    final = repo.apply(state.match_id, _select(inspected.state, []))
    assert not final.state.pending_effects and final.state.pending_choice is None
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("empty", (False, True))
@pytest.mark.parametrize("policy", ("simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"))
def test_four_ai_policies_finish_without_private_dependency_or_error_skip(code, empty, policy):
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
def test_refresh_preserves_top_and_follows_fee_payment(code, only_cost):
    state = _state(code)
    state.players["player_1"].main_deck = [] if only_cost else ["good-member"]
    state.players["player_1"].waiting_room = [] if only_cost else ["good-live", "wrong-work", "blade-heart", "tail", "deck-live-1"]
    inspected = _inspect(apply_action(state, _play(state)).state)
    events = [e.event_type for e in inspected.events]
    assert events.index("effect_cost_paid") < events.index("deck_refreshed") < events.index("effect_inspection_started")
    assert inspected.state.pending_choice.options["inspected_card_instance_ids"][0] == ("cost" if only_cost else "good-member")
    final = apply_action(inspected.state, _select(inspected.state, []))
    assert final.state.pending_choice is None and not final.state.pending_effects
