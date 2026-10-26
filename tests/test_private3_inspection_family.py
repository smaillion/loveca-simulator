import json
from functools import lru_cache
from pathlib import Path

import pytest
from test_nijigasaki_inspection import _play, _resolve, _select, _state
from test_typed_inspection_costs import _control, _with_control

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

BASE_HASH = "92d61785879b4127c6eb0800e33fa07a18aa33cbf19b4cf1cbf98f76a906700c"
HS_PR_HASH = "3664d844a939ac7c720b5bf9d2625a4ba96cc0ee83e58e12b3f475a62a8c3d64"
S_PR_HASH = "1b85acb06e79966219950f6f9d06633aba33255b46e84a47602765ee32824e60"
IDENTITIES = (
    ("PL!-sd1-016", 521, BASE_HASH), ("PL!HS-PR-001", 778, HS_PR_HASH),
    ("PL!HS-PR-002", 779, HS_PR_HASH), ("PL!HS-PR-005", 780, HS_PR_HASH),
    ("PL!HS-cl1-007", 88, BASE_HASH), ("PL!HS-pb1-011", 127, BASE_HASH),
    ("PL!N-PR-004", 745, BASE_HASH), ("PL!N-PR-006", 747, BASE_HASH),
    ("PL!N-PR-013", 752, BASE_HASH), ("PL!N-bp1-007", 631, BASE_HASH),
    ("PL!N-bp1-010", 634, BASE_HASH), ("PL!N-sd1-002", 681, BASE_HASH),
    ("PL!N-sd1-003", 682, BASE_HASH), ("PL!S-PR-013", 726, S_PR_HASH),
    ("PL!S-PR-019", 728, S_PR_HASH),
)
CODES = tuple(row[0] for row in IDENTITIES)
RULE_REFERENCE_IDS = ("5.7.1", "9.4.2", "9.6.3.1.4", "9.7.3.1.1", "9.7.3.2", "10.2.2.2", "10.2.3")
LABEL = "【登場】手札を1枚控え室に置いてもよい：自分のデッキの上からカードを3枚見る。その中から1枚を手札に加え、残りを控え室に置く。"


def _begin(code, *, empty=False):
    state = _state(code)
    if empty:
        state.players["player_1"].hand = ["source-live"]
    return apply_action(state, _play(state)).state


def _inspect(state):
    return apply_action(state, _resolve(state, selected_card_instance_ids=["cost"]))


@lru_cache
def _candidates():
    return {c.effect_id: c for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)}


@pytest.mark.parametrize("code", CODES)
def test_no_cost_has_explicit_cancel_without_peeking(code):
    state = _begin(code, empty=True)
    options = next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect").options["invocations"][0]
    assert options["cost_payment_unavailable_reason"] == "inspection_cost_candidates_unavailable"
    result = apply_action(state, _resolve(state))
    assert not result.state.pending_effects and result.state.pending_choice is None
    assert result.state.players["player_1"].main_deck == state.players["player_1"].main_deck
    assert not any(e.event_type in {"effect_cost_paid", "effect_inspection_started", "effect_skipped"} for e in result.events)


@pytest.mark.parametrize("code,revision,raw_hash", IDENTITIES)
def test_exact_identity_full_segment_and_candidate_contract(code, revision, raw_hash):
    from loveca.simulation.effect_candidates import _onplay_audited_discard_inspection
    effect = _state(code).effect_definitions[code + ":1"]
    assert (effect.text_revision_id, effect.raw_text_hash, effect.label_ja) == (revision, raw_hash, LABEL)
    assert effect == EffectDefinition.model_validate(_candidates()[effect.effect_id].to_registry_entry())
    assert effect.review_status == "test_validated" and effect.simulation_support == "test_validated_executable"
    assert effect.choice.cost_payment_policy == "triggered_inspection"
    row = {"card_code": code, "text_revision_id": revision, "raw_text_hash": raw_hash, "raw_effect_text_ja": LABEL}
    assert _onplay_audited_discard_inspection({**row, "raw_effect_text_ja": LABEL + "カードを1枚引く。"}) is None
    assert _onplay_audited_discard_inspection({**row, "card_code": "AUDIT-not-reviewed"}) is None


@pytest.mark.parametrize("code", CODES)
def test_can_decline_optional_cost_without_discard_or_inspection(code):
    state = _begin(code)
    result = apply_action(state, _resolve(state, accepted=False))
    assert result.state.players["player_1"].hand == ["cost"]
    assert result.state.players["player_1"].main_deck == state.players["player_1"].main_deck
    assert result.state.pending_choice is None and not result.state.pending_effects


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("kind,target", (("member", "good-live"), ("live", "wrong-work")))
def test_real_source_cost_then_private_unfiltered_one_card(code, kind, target):
    state = _state(code)
    state.cards["cost"].card.card_type = kind
    state = apply_action(state, _play(state)).state
    inspected = _inspect(state)
    choice = inspected.state.pending_choice.options
    assert choice["inspected_card_instance_ids"] == ["good-member", "good-live", "wrong-work"]
    assert set(choice["candidate_card_instance_ids"]) == {"good-member", "good-live", "wrong-work"}
    assert choice["minimum"] == choice["maximum"] == 1
    assert choice["reveal_selected_to_opponent"] is False
    assert "cost" in inspected.state.players["player_1"].waiting_room
    final = apply_action(inspected.state, _select(inspected.state, [target]))
    assert final.state.players["player_1"].hand == [target]
    assert set(final.state.players["player_1"].waiting_room) == {"cost", "good-member", "good-live", "wrong-work"} - {target}
    assert not final.state.pending_effects and final.state.pending_choice is None
    assert not any(e.event_type == "effect_cost_paid" for e in final.events)


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("ids", ([], ["source-live"], ["opponent-secret"], ["cost", "cost"]))
def test_invalid_cost_is_atomic_and_uses_only_own_hand(code, ids):
    state = _begin(code)
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, selected_card_instance_ids=ids))
    assert match_state_hash(state) == before and state.pending_choice is None


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("ids", ([], ["good-member", "good-member"], ["opponent-secret"], ["tail"]))
def test_payment_does_not_allow_zero_or_invalid_private_keep(code, ids):
    state = _inspect(_begin(code)).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _select(state, ids))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("code", CODES)
def test_opponent_full_response_does_not_leak_private_look_or_keep(code):
    inspected = _inspect(_begin(code))
    other = _match_state_payload(inspected.state, events=inspected.events, legal_actions=inspected.legal_actions, player_id="player_2")
    assert "good-member" not in json.dumps(other) and "good-live" not in json.dumps(other)
    final = apply_action(inspected.state, _select(inspected.state, ["good-member"]))
    other = _match_state_payload(final.state, events=final.events, legal_actions=final.legal_actions, player_id="player_2")
    assert "good-member" not in json.dumps(other)
    assert not any(e["data"].get("revealed_cards") for e in other["events"])


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("legacy", (False, True))
def test_sql_replay_of_old_and_new_successful_inspection(tmp_path, code, legacy):
    state = _state(code)
    if legacy:
        raw = state.effect_definitions[code + ":1"].model_dump(mode="json")
        raw["choice"].pop("cost_payment_policy")
        state.effect_definitions[code + ":1"] = EffectDefinition.model_validate(raw)
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state))
    inspected = repo.apply(state.match_id, _resolve(played.state, selected_card_instance_ids=["cost"]))
    final = repo.apply(state.match_id, _select(inspected.state, ["good-live"]))
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("legacy", (False, True))
def test_sql_unpayable_old_decline_and_new_cancel_remain_distinct(tmp_path, code, legacy):
    state = _state(code)
    state.players["player_1"].hand = ["source-live"]
    if legacy:
        raw = state.effect_definitions[code + ":1"].model_dump(mode="json")
        raw["choice"].pop("cost_payment_policy")
        state.effect_definitions[code + ":1"] = EffectDefinition.model_validate(raw)
        assert "cost_payment_policy" not in state.effect_definitions[code + ":1"].model_dump(mode="json")["choice"]
    state = apply_action(state, _play(state)).state
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    if legacy:
        with pytest.raises(IllegalActionError):
            repo.apply(state.match_id, _resolve(state))
        assert match_state_hash(repo.get_state(state.match_id)) == match_state_hash(state)
    final = repo.apply(state.match_id, _resolve(state, accepted=not legacy))
    assert final.state.pending_choice is None and not final.state.pending_effects
    assert not any(e.event_type in {"effect_cost_paid", "effect_inspection_started", "effect_skipped"} for e in final.events)
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("code", CODES)
def test_other_pending_invocation_can_supply_cost_before_resolution(tmp_path, code):
    state = _with_control(code)
    state.players["player_1"].hand = ["source-live"]
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state))
    assert len(played.state.pending_effects) == 2
    drawn = repo.apply(state.match_id, _control(played.state, [
        {"adjustment_type": "draw_card", "target_player_id": "player_1", "amount": 1}]))
    inspected = repo.apply(state.match_id, _resolve(drawn.state, selected_card_instance_ids=["good-member"]))
    final = repo.apply(state.match_id, _select(inspected.state, ["good-live"]))
    assert "good-member" in final.state.players["player_1"].waiting_room
    assert final.state.pending_choice is None and not final.state.pending_effects
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("empty", (False, True))
@pytest.mark.parametrize("policy", ("simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"))
def test_four_ai_policies_finish_paid_or_unpayable_inspection(code, empty, policy):
    state = _begin(code, empty=empty)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    for _ in range(2):
        if not state.pending_effects and not state.pending_choice:
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
def test_refresh_follows_payment_and_preserves_remaining_top(code, only_cost):
    state = _state(code)
    state.players["player_1"].main_deck = [] if only_cost else ["good-member"]
    state.players["player_1"].waiting_room = [] if only_cost else ["good-live", "wrong-work", "tail"]
    state = apply_action(state, _play(state)).state
    result = _inspect(state)
    events = [e.event_type for e in result.events]
    assert events.index("effect_cost_paid") < events.index("deck_refreshed") < events.index("effect_inspection_started")
    choice = result.state.pending_choice.options
    assert choice["inspected_card_instance_ids"][0] == ("cost" if only_cost else "good-member")
    assert len(choice["inspected_card_instance_ids"]) == (1 if only_cost else 3)
    assert choice["minimum"] == choice["maximum"] == 1
    final = apply_action(result.state, _select(result.state, choice["candidate_card_instance_ids"][:1]))
    assert final.state.pending_choice is None and not final.state.pending_effects
    assert not any(e.event_type == "effect_cost_paid" for e in final.events)
