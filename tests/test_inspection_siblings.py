import json
from functools import lru_cache
from pathlib import Path

import pytest
from test_adjacent_inspection_costs import _state
from test_nijigasaki_inspection import _play, _resolve, _select
from test_typed_inspection_costs import _control, _with_control

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

MEMBER = ("PL!-sd1-015", "PL!HS-bp2-010")
LIVE = ("PL!HS-bp1-011", "PL!HS-bp6-022")
PRIVATE = ("PL!N-pb1-028", "PL!N-pb1-035")
CODES = (*MEMBER, *LIVE, *PRIVATE)
RULE_REFERENCE_IDS = ("5.7.1", "9.4.2", "9.6.3.1.4", "9.7.3.1.1", "9.7.3.2", "10.2.2.2", "10.2.3")
IDENTITIES = (
    (MEMBER[0], 520, "42df0bd4feb4ca8d4de16eb9870d8de6cfcbacf8c4fb134c4bcc37e745d5e0b5"),
    (MEMBER[1], 583, "42df0bd4feb4ca8d4de16eb9870d8de6cfcbacf8c4fb134c4bcc37e745d5e0b5"),
    (LIVE[0], 663, "60028b483e5ee5bf112e85a554d46661a7bdf871d13b0abec7b261cde0e5071f"),
    (LIVE[1], 58, "60028b483e5ee5bf112e85a554d46661a7bdf871d13b0abec7b261cde0e5071f"),
    (PRIVATE[0], 332, "0798b4751a043d751d97d6af2ae1d6f6cc1be3cc1e2b9474478810847d3208c1"),
    (PRIVATE[1], 334, "0798b4751a043d751d97d6af2ae1d6f6cc1be3cc1e2b9474478810847d3208c1"),
)


def _begin(code, *, empty=False):
    state = _state(code)
    if empty:
        state.players["player_1"].hand = ["source-live"]
    return apply_action(state, _play(state)).state


def _inspect(state):
    return apply_action(state, _resolve(state, selected_card_instance_ids=["cost"]))


def _target(code):
    return "good-live" if code in LIVE else "good-member"


@lru_cache
def _candidates():
    return {c.effect_id: c for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)}


@pytest.mark.parametrize("code", CODES)
def test_empty_cost_can_end_without_inspection(code):
    state = _begin(code, empty=True)
    option = next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect").options["invocations"][0]
    assert option["cost_payment_unavailable_reason"] == "inspection_cost_candidates_unavailable"
    result = apply_action(state, _resolve(state))
    assert result.state.pending_choice is None and not result.state.pending_effects
    assert result.state.players["player_1"].main_deck == state.players["player_1"].main_deck
    assert not any(e.event_type in {"effect_cost_paid", "effect_inspection_started", "effect_skipped"} for e in result.events)


@pytest.mark.parametrize("code,revision,raw_hash", IDENTITIES)
def test_exact_candidate_identity_and_unverified_text_rejection(code, revision, raw_hash):
    from loveca.simulation.effect_candidates import _onplay_audited_discard_inspection
    effect = _state(code).effect_definitions[code + ":1"]
    assert (effect.text_revision_id, effect.raw_text_hash) == (revision, raw_hash)
    assert effect == EffectDefinition.model_validate(_candidates()[effect.effect_id].to_registry_entry())
    assert effect.choice.cost_payment_policy == "triggered_inspection"
    assert effect.review_status == "test_validated" and effect.simulation_support == "test_validated_executable"
    row = {"card_code": code, "text_revision_id": revision, "raw_text_hash": raw_hash, "raw_effect_text_ja": effect.label_ja}
    assert _onplay_audited_discard_inspection({**row, "raw_effect_text_ja": effect.label_ja + "カードを1枚引く。"}) is None
    assert _onplay_audited_discard_inspection({**row, "card_code": "AUDIT-unreviewed"}) is None


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("cost_type", ("member", "live"))
def test_actual_onplay_pays_any_hand_type_once_and_filters_correctly(code, cost_type):
    state = _state(code)
    state.cards["cost"].card.card_type = cost_type
    state = apply_action(state, _play(state)).state
    inspected = _inspect(state)
    choice = inspected.state.pending_choice.options
    expected = ({"good-member", "wrong-work", "blade-heart", "tail"} if code in MEMBER
                else {"good-live"} if code in LIVE else {"good-member", "good-live"})
    assert choice["inspected_card_instance_ids"] == state.players["player_1"].main_deck[:2 if code in PRIVATE else 5]
    assert set(choice["candidate_card_instance_ids"]) == expected
    assert "cost" in inspected.state.players["player_1"].waiting_room
    assert sum(e.event_type == "effect_cost_paid" for e in inspected.events) == 1
    final = apply_action(inspected.state, _select(inspected.state, [_target(code)]))
    assert final.state.players["player_1"].hand == [_target(code)]
    assert final.state.pending_choice is None and not final.state.pending_effects
    assert not any(e.event_type == "effect_cost_paid" for e in final.events)


@pytest.mark.parametrize("code", CODES)
def test_optional_cost_can_be_declined(code):
    state = _begin(code)
    result = apply_action(state, _resolve(state, accepted=False))
    assert result.state.players["player_1"].hand == ["cost"]
    assert result.state.players["player_1"].main_deck == state.players["player_1"].main_deck
    assert result.state.pending_choice is None and not result.state.pending_effects


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("ids", ([], ["opponent-secret"], ["source-live"], ["cost", "cost"]))
def test_invalid_cost_is_atomic(code, ids):
    state = _begin(code)
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, selected_card_instance_ids=ids))
    assert match_state_hash(state) == before and state.pending_choice is None


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("ids", (["opponent-secret"], ["cost"], ["good-live", "good-live"]))
def test_invalid_inspected_selection_is_atomic(code, ids):
    state = _inspect(_begin(code)).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _select(state, ids))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("code", CODES)
def test_private_two_requires_one_while_public_optional_can_keep_zero(code):
    state = _inspect(_begin(code)).state
    assert state.pending_choice.options["minimum"] == (1 if code in PRIVATE else 0)
    before = match_state_hash(state)
    if code in PRIVATE:
        with pytest.raises(IllegalActionError):
            apply_action(state, _select(state, []))
        assert match_state_hash(state) == before
    else:
        result = apply_action(state, _select(state, []))
        assert result.state.players["player_1"].hand == [] and result.state.pending_choice is None


@pytest.mark.parametrize("code", CODES)
def test_private_look_and_final_public_or_private_keep_have_distinct_visibility(code):
    inspected = _inspect(_begin(code))
    other = _match_state_payload(inspected.state, events=inspected.events, legal_actions=inspected.legal_actions, player_id="player_2")
    assert "good-member" not in json.dumps(other) and "good-live" not in json.dumps(other)
    final = apply_action(inspected.state, _select(inspected.state, [_target(code)]))
    other = _match_state_payload(final.state, events=final.events, legal_actions=final.legal_actions, player_id="player_2")
    revealed = [c["instance_id"] for e in other["events"] for c in e["data"].get("revealed_cards", [])]
    assert (_target(code) in revealed) == (code not in PRIVATE)
    if code in PRIVATE:
        assert _target(code) not in json.dumps(other)


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("legacy", (False, True))
@pytest.mark.parametrize("empty", (False, True))
def test_sql_replay_preserves_old_cost_and_cancel_semantics(tmp_path, code, legacy, empty):
    state = _state(code)
    if empty:
        state.players["player_1"].hand = ["source-live"]
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
        final = repo.apply(state.match_id, _select(inspected.state, [_target(code)]))
    assert final.state.pending_choice is None and not final.state.pending_effects
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("code", CODES)
def test_another_pending_invocation_can_fund_the_cost(tmp_path, code):
    state = _with_control(code)
    state.players["player_1"].hand = ["source-live"]
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state))
    assert len(played.state.pending_effects) == 2
    drawn = repo.apply(state.match_id, _control(played.state, [
        {"adjustment_type": "draw_card", "target_player_id": "player_1", "amount": 1}]))
    inspected = repo.apply(state.match_id, _resolve(drawn.state, selected_card_instance_ids=["good-member"]))
    final = repo.apply(state.match_id, _select(inspected.state, inspected.state.pending_choice.options["candidate_card_instance_ids"][:1]))
    assert final.state.pending_choice is None and not final.state.pending_effects
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("empty", (False, True))
@pytest.mark.parametrize("policy", ("simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"))
def test_four_policies_finish_without_hidden_hand_dependency_or_error_skip(code, empty, policy):
    state = _begin(code, empty=empty)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    for _ in range(2):
        if not state.pending_choice and not state.pending_effects:
            break
        before = match_state_hash(state)
        decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
        assert isinstance(decision, SimpleAIDecision) and match_state_hash(state) == before
        changed = state.model_copy(deep=True)
        changed.cards["opponent-secret"].card.card_code = "AUDIT-hidden-other"
        assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}).action == decision.action
        result = apply_action(state, decision.action)
        assert not any(e.event_type == "effect_skipped" for e in result.events)
        state = result.state
    assert state.pending_choice is None and not state.pending_effects


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("only_cost", (False, True))
def test_short_deck_refresh_follows_payment_without_paying_twice(code, only_cost):
    state = _state(code)
    state.players["player_1"].main_deck = [] if only_cost else ["good-member"]
    state.players["player_1"].waiting_room = [] if only_cost else ["good-live", "wrong-work", "blade-heart", "tail", "deck-live-1"]
    state = apply_action(state, _play(state)).state
    inspected = _inspect(state)
    events = [e.event_type for e in inspected.events]
    assert events.index("effect_cost_paid") < events.index("deck_refreshed") < events.index("effect_inspection_started")
    choice = inspected.state.pending_choice.options
    assert choice["inspected_card_instance_ids"][0] == ("cost" if only_cost else "good-member")
    assert len(choice["inspected_card_instance_ids"]) == (1 if only_cost else 2 if code in PRIVATE else 5)
    final = apply_action(inspected.state, _select(inspected.state, choice["candidate_card_instance_ids"][:choice["minimum"]]))
    assert final.state.pending_choice is None and not final.state.pending_effects
    assert not any(e.event_type == "effect_cost_paid" for e in final.events)
