import json
from functools import lru_cache
from pathlib import Path

import pytest
from test_nijigasaki_inspection import _play, _resolve, _select
from test_nijigasaki_inspection import _state as _base_state
from test_typed_inspection_costs import _control, _with_control

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effect_candidates import (
    _onplay_audited_discard_inspection,
    discover_effect_candidates,
)
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

IDENTITIES = (
    ("PL!HS-bp1-009", 661, "f507dbdac8360a1e33e47e7736379a5d334ed63fee63fbdf11b38f8d9692c830", "miracra_park"),
    ("PL!HS-pb1-018", 133, "7663788b56e98803d22ddd5924263de43961263683696c3753c102197a8d9556", "dollchestra"),
    ("PL!N-bp3-012", 485, "5b693b9e1ba36e9d8fc384d2df76c9c80cabff63865642310c6ff5e96080745c", None),
    ("PL!SP-pb1-015", 615, "302a1051b830917f68d0aee3f8be153266ea6974394c91004aa81f0bca897b88", "catchu"),
    ("PL!SP-pb1-016", 616, "111a18c9c8c204a67570cb154f515eaee59d48a32d61fe89372a9853934fab00", "kaleidoscore"),
    ("PL!SP-pb1-017", 617, "9def73c9c8dd54a99b9520c9e552fc48ebcba47ce8954a8f0624c7ea74243be9", "5yncri5e"),
)
CODES = tuple(item[0] for item in IDENTITIES)
RULE_REFERENCE_IDS = ("5.7.1", "9.4.2", "9.7.3.1.1", "9.7.3.2", "10.2.2.2", "10.2.3")


def _state(code, *, empty=False):
    state = _base_state(code)
    unit = next(item[3] for item in IDENTITIES if item[0] == code)
    work = "nijigasaki" if unit is None else "hasunosora" if code.startswith("PL!HS") else "love_live_superstar"
    for key in ("good-member", "good-live", "wrong-work", "blade-heart", "tail"):
        state.cards[key].card.work_keys = [work]
        state.cards[key].card.unit_keys = [unit or "a_zu_na"]
    state.cards["wrong-work"].card.work_keys = ["love_live"]
    state.cards["wrong-work"].card.unit_keys = ["other"]
    state.cards["blade-heart"].card.unit_keys = ["other"]
    state.cards["tail"].card.unit_keys = ["other", unit or "qu4rtz"]
    if empty:
        state.players["player_1"].hand = ["source-live"]
    return state


def _begin(code, *, empty=False):
    state = _state(code, empty=empty)
    return apply_action(state, _play(state)).state


def _inspect(state):
    return apply_action(state, _resolve(state, selected_card_instance_ids=["cost"]))


@lru_cache
def _candidates():
    return {c.effect_id: c for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)}


@pytest.mark.parametrize("code,revision,raw_hash,unit", IDENTITIES)
def test_exact_identity_and_work_unit_contract(code, revision, raw_hash, unit):
    state = _state(code)
    effect = state.effect_definitions[code + ":1"]
    assert state.cards["source-live"].card.cost == 4
    assert (effect.text_revision_id, effect.raw_text_hash) == (revision, raw_hash)
    assert effect == EffectDefinition.model_validate(_candidates()[effect.effect_id].to_registry_entry())
    assert effect.choice.cost_payment_policy == "triggered_inspection"
    assert effect.choice.unit_key == unit
    assert effect.choice.work_key == ("nijigasaki" if unit is None else None)
    assert effect.choice.card_type is None and effect.choice.minimum == 0
    assert effect.choice.amount == (4 if unit is None else 5)
    assert effect.review_status == "test_validated"
    row = {"card_code": code, "text_revision_id": revision, "raw_text_hash": raw_hash, "raw_effect_text_ja": effect.label_ja}
    assert _onplay_audited_discard_inspection({**row, "raw_effect_text_ja": effect.label_ja + "カードを1枚引く。"}) is None
    assert _onplay_audited_discard_inspection({**row, "card_code": "AUDIT-unknown"}) is None


@pytest.mark.parametrize("code", CODES)
def test_unpayable_cost_ends_without_looking_or_error_skip(code):
    state = _begin(code, empty=True)
    option = next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect").options["invocations"][0]
    assert option["cost_payment_unavailable_reason"] == "inspection_cost_candidates_unavailable"
    result = apply_action(state, _resolve(state))
    assert not result.state.pending_effects and result.state.pending_choice is None
    assert result.state.players["player_1"].main_deck == state.players["player_1"].main_deck
    assert not any(e.event_type in {"effect_cost_paid", "effect_inspection_started", "effect_skipped"} for e in result.events)


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("target", ("good-member", "good-live", "tail", None))
@pytest.mark.parametrize("cost_type", ("member", "live"))
def test_native_fee_filters_member_and_live_and_public_keep(code, target, cost_type):
    state = _state(code)
    state.cards["cost"].card.card_type = cost_type
    played = apply_action(state, _play(state)).state
    assert all(played.cards[key].orientation == "wait" for key in played.players["player_1"].energy_area)
    inspected = _inspect(played)
    choice = inspected.state.pending_choice.options
    expected = {"good-member", "good-live", "blade-heart"} if code == "PL!N-bp3-012" else {"good-member", "good-live", "tail"}
    assert set(choice["candidate_card_instance_ids"]) == expected
    assert choice["inspected_card_instance_ids"] == state.players["player_1"].main_deck[:4 if code == "PL!N-bp3-012" else 5]
    assert sum(e.event_type == "effect_cost_paid" for e in inspected.events) == 1
    other = _match_state_payload(inspected.state, events=inspected.events, legal_actions=inspected.legal_actions, player_id="player_2")
    assert "good-member" not in json.dumps(other) and "good-live" not in json.dumps(other)
    selected = "blade-heart" if target == "tail" and code == "PL!N-bp3-012" else target
    final = apply_action(inspected.state, _select(inspected.state, [selected] if selected else []))
    assert final.state.players["player_1"].hand == ([selected] if selected else [])
    assert not final.state.pending_effects and final.state.pending_choice is None
    assert "cost" in final.state.players["player_1"].waiting_room
    assert not any(e.event_type == "effect_cost_paid" for e in final.events)
    other = _match_state_payload(final.state, events=final.events, legal_actions=final.legal_actions, player_id="player_2")
    revealed = [c["instance_id"] for e in other["events"] for c in e["data"].get("revealed_cards", [])]
    assert (selected in revealed) if selected else not revealed


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("ids", ([], ["opponent-secret"], ["source-live"], ["cost", "cost"]))
def test_invalid_cost_is_atomic(code, ids):
    state = _begin(code)
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, selected_card_instance_ids=ids))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("ids", (["wrong-work"], ["cost"], ["good-live", "good-live"]))
def test_invalid_keep_is_atomic(code, ids):
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
        state.cards[key].card.work_keys, state.cards[key].card.unit_keys = ["other"], ["other"]
    inspected = _inspect(state)
    assert inspected.state.pending_choice.options["candidate_card_instance_ids"] == []
    final = apply_action(inspected.state, _select(inspected.state, []))
    assert final.state.pending_choice is None and not final.state.pending_effects


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("legacy", (False, True))
@pytest.mark.parametrize("empty", (False, True))
def test_sql_replay_old_and_new_snapshot(tmp_path, code, legacy, empty):
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
def test_pending_draw_can_supply_cost_before_selection(tmp_path, code):
    state = _state(code, empty=True)
    controlled = _with_control(code)
    state.effect_definitions["AUDIT-control:1"] = controlled.effect_definitions["AUDIT-control:1"]
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
        if not state.pending_choice and not state.pending_effects:
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
def test_refresh_after_payment_and_only_actual_candidates(code):
    state = _state(code)
    state.players["player_1"].main_deck = ["good-member"]
    state.players["player_1"].waiting_room = ["good-live", "wrong-work", "blade-heart", "tail", "deck-live-1"]
    inspected = _inspect(apply_action(state, _play(state)).state)
    events = [e.event_type for e in inspected.events]
    assert events.index("effect_cost_paid") < events.index("deck_refreshed") < events.index("effect_inspection_started")
    assert inspected.state.pending_choice.options["inspected_card_instance_ids"][0] == "good-member"
    final = apply_action(inspected.state, _select(inspected.state, []))
    assert not final.state.pending_effects and final.state.pending_choice is None
