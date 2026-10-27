import json
from functools import lru_cache
from pathlib import Path

import pytest
from test_nijigasaki_inspection import _play, _resolve, _select
from test_nijigasaki_inspection import _state as base_state
from test_typed_inspection_costs import _control, _with_control

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

LIVE, HEART, MUSE, LILY = "PL!-bp3-010", "PL!-bp5-014", "PL!-bp6-004", "PL!-pb1-016"
PRIVATE = ("PL!-sd1-011", "PL!-sd1-012")
CODES = (LIVE, HEART, MUSE, LILY, *PRIVATE)
RULE_REFERENCE_IDS = ("5.7.1", "9.4.2", "9.6.3.1.4", "9.7.3.1.1", "9.7.3.2", "10.2.2.2", "10.2.3")
EXPECTED = {
    LIVE: {"good-live"}, HEART: {"good-member", "wrong-work"},
    MUSE: {"good-member", "blade-heart", "tail"}, LILY: {"good-member", "good-live", "blade-heart"},
    **{code: {"good-member", "good-live", "wrong-work"} for code in PRIVATE},
}


def _state(code):
    state = base_state(code)
    for key in ("good-member", "good-live", "blade-heart", "tail"):
        state.cards[key].card.work_keys = ["love_live"]
    for key in ("good-member", "good-live", "blade-heart"):
        state.cards[key].card.unit_keys = ["lily_white"]
    state.cards["wrong-work"].card.unit_keys = ["other-unit"]
    state.cards["tail"].card.unit_keys = ["other-unit"]
    for key, hearts in (("good-member", {"heart05": 1}), ("wrong-work", {"heart06": 1}),
                        ("blade-heart", {"heart01": 1}), ("tail", {"heart06": 1})):
        state.cards[key].card.basic_hearts = hearts
    state.cards["good-live"].card.required_hearts = {"heart05": 5}
    return state


def _begin(code):
    state = _state(code)
    return apply_action(state, _play(state)).state


def _inspect(state):
    return apply_action(state, _resolve(state, selected_card_instance_ids=["cost"]))


@lru_cache
def _candidates():
    return {c.effect_id: c for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)}


@pytest.mark.parametrize("code", CODES)
def test_no_hand_cost_can_cancel_without_looking(code):
    state = _state(code)
    state.players["player_1"].hand = ["source-live"]
    state = apply_action(state, _play(state)).state
    options = next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect").options["invocations"][0]
    assert options["cost_payment_unavailable_reason"] == "inspection_cost_candidates_unavailable"
    result = apply_action(state, _resolve(state))
    assert result.state.pending_choice is None and not result.state.pending_effects
    assert result.state.players["player_1"].main_deck == state.players["player_1"].main_deck
    assert not any(e.event_type in {"effect_cost_paid", "effect_inspection_started", "effect_skipped"} for e in result.events)


@pytest.mark.parametrize("code,revision,hash_value", [
    (LIVE, 452, "60028b483e5ee5bf112e85a554d46661a7bdf871d13b0abec7b261cde0e5071f"),
    (HEART, 161, "687f32f7dd1e49c2a7178142a0f4ae3c81b154dec7a114188c65d8552320538d"),
    (MUSE, 6, "3e774983ae9ec2074682b4892f74c2d940924cf91b839adce316eebb07b91e45"),
    (LILY, 431, "7fcbeb06314fd0b103d8cac61304eaab7274cfbb1f22162877be2dbb0df114d5"),
    (PRIVATE[0], 518, "92d61785879b4127c6eb0800e33fa07a18aa33cbf19b4cf1cbf98f76a906700c"),
    (PRIVATE[1], 519, "92d61785879b4127c6eb0800e33fa07a18aa33cbf19b4cf1cbf98f76a906700c"),
])
def test_exact_candidate_and_original_identity(code, revision, hash_value):
    effect = _state(code).effect_definitions[code + ":1"]
    assert (effect.text_revision_id, effect.raw_text_hash) == (revision, hash_value)
    assert EffectDefinition.model_validate(_candidates()[effect.effect_id].to_registry_entry()) == effect
    assert effect.choice.cost_payment_policy == "triggered_inspection"
    assert effect.simulation_support == "test_validated_executable" and effect.review_status == "test_validated"


@pytest.mark.parametrize("code", CODES)
def test_real_onplay_pays_once_and_uses_actual_card_filters(code):
    state = _begin(code)
    result = _inspect(state)
    choice = result.state.pending_choice.options
    amount = state.effect_definitions[code + ":1"].choice.amount
    assert choice["inspected_card_instance_ids"] == state.players["player_1"].main_deck[:amount]
    assert set(choice["candidate_card_instance_ids"]) == EXPECTED[code]
    assert "cost" in result.state.players["player_1"].waiting_room
    assert sum(e.event_type == "effect_cost_paid" for e in result.events) == 1
    target = "good-live" if code == LIVE else "good-member"
    final = apply_action(result.state, _select(result.state, [target]))
    assert target in final.state.players["player_1"].hand
    assert not final.state.pending_effects and final.state.pending_choice is None
    assert not any(e.event_type == "effect_cost_paid" for e in final.events)


@pytest.mark.parametrize("code", CODES)
def test_optional_payment_is_distinct_from_post_payment_keep_requirement(code):
    state = _begin(code)
    declined = apply_action(state, _resolve(state, accepted=False))
    assert declined.state.players["player_1"].main_deck == state.players["player_1"].main_deck
    assert "cost" in declined.state.players["player_1"].hand
    inspected = _inspect(state).state
    before = match_state_hash(inspected)
    if code in PRIVATE:
        with pytest.raises(IllegalActionError):
            apply_action(inspected, _select(inspected, []))
        assert match_state_hash(inspected) == before
    else:
        final = apply_action(inspected, _select(inspected, []))
        assert final.state.players["player_1"].hand == []
        assert final.state.pending_choice is None and not final.state.pending_effects


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("ids", ([], ["source-live"], ["opponent-secret"], ["cost", "cost"]))
def test_bad_cost_is_atomic_and_cannot_use_opponents_resources(code, ids):
    state = _begin(code)
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, selected_card_instance_ids=ids))
    assert match_state_hash(state) == before and state.pending_choice is None


@pytest.mark.parametrize("code", CODES)
def test_private_look_and_explicit_public_keep_are_not_conflated(code):
    result = _inspect(_begin(code))
    other = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id="player_2")
    assert "good-member" not in json.dumps(other)
    target = "good-live" if code == LIVE else "good-member"
    final = apply_action(result.state, _select(result.state, [target]))
    other = _match_state_payload(final.state, events=final.events, legal_actions=final.legal_actions, player_id="player_2")
    public = [c["instance_id"] for e in other["events"] for c in e["data"].get("revealed_cards", [])]
    assert (target in public) == (code not in PRIVATE)
    if code in PRIVATE:
        assert target not in json.dumps(other)


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("policy", ("simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"))
def test_four_ai_policies_handle_native_actions_without_hidden_dependency(code, policy):
    state = _begin(code)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    for _ in range(2):
        if not state.pending_choice and not state.pending_effects:
            break
        before = match_state_hash(state)
        decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
        assert isinstance(decision, SimpleAIDecision) and match_state_hash(state) == before
        changed = state.model_copy(deep=True)
        changed.cards["opponent-secret"].card.card_code = "AUDIT-other-private"
        assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}).action == decision.action
        result = apply_action(state, decision.action)
        assert not any(e.event_type == "effect_skipped" for e in result.events)
        state = result.state
    assert not state.pending_effects and state.pending_choice is None


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("legacy", (False, True))
def test_sql_replay_keeps_paid_cost_and_old_snapshot_shape(tmp_path, code, legacy):
    state = _state(code)
    if legacy:
        raw = state.effect_definitions[code + ":1"].model_dump(mode="json")
        raw["choice"].pop("cost_payment_policy")
        state.effect_definitions[code + ":1"] = EffectDefinition.model_validate(raw)
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state))
    inspected = repo.apply(state.match_id, _resolve(played.state, selected_card_instance_ids=["cost"]))
    target = "good-live" if code == LIVE else "good-member"
    final = repo.apply(state.match_id, _select(inspected.state, [target]))
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("code", CODES)
def test_another_pending_effect_can_supply_hand_cost_before_selection(tmp_path, code):
    state = _with_control(code)
    state.players["player_1"].hand = ["source-live"]
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state))
    assert len(played.state.pending_effects) == 2
    drawn = repo.apply(state.match_id, _control(played.state, [
        {"adjustment_type": "draw_card", "target_player_id": "player_1", "amount": 1}]))
    inspected = repo.apply(state.match_id, _resolve(drawn.state, selected_card_instance_ids=["good-member"]))
    choice = inspected.state.pending_choice.options
    ids = choice["candidate_card_instance_ids"][:choice["minimum"]]
    final = repo.apply(state.match_id, _select(inspected.state, ids))
    assert final.state.pending_choice is None and not final.state.pending_effects
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("policy", ("simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"))
def test_four_policies_end_unpayable_cost_without_error_skip(code, policy):
    state = _state(code)
    state.players["player_1"].hand = ["source-live"]
    state = apply_action(state, _play(state)).state
    decision = SimpleAIController(SimpleAIPolicy(policy_version=policy)).choose_action(
        state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision) and decision.action.action_type == "resolve_effect"
    result = apply_action(state, decision.action)
    assert result.state.pending_choice is None and not result.state.pending_effects
    assert not any(e.event_type in {"effect_cost_paid", "effect_inspection_started", "effect_skipped"} for e in result.events)


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("ids", (["cost"], ["opponent-secret"], ["good-member", "good-member"]))
def test_bad_inspected_selection_is_atomic(code, ids):
    state = _inspect(_begin(code)).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _select(state, ids))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("kind", ("member", "live"))
def test_single_hand_cost_is_not_incorrectly_live_or_member_restricted(code, kind):
    state = _state(code)
    state.cards["cost"].card.card_type = kind
    state = apply_action(state, _play(state)).state
    result = _inspect(state)
    assert result.state.pending_choice is not None and "cost" in result.state.players["player_1"].waiting_room


@pytest.mark.parametrize("code", CODES)
def test_refresh_happens_after_discard_and_keeps_previous_top(code):
    state = _state(code)
    state.players["player_1"].main_deck = ["good-member"]
    state.players["player_1"].waiting_room = ["good-live", "wrong-work", "blade-heart", "tail", "deck-live-1"]
    state = apply_action(state, _play(state)).state
    result = _inspect(state)
    events = [e.event_type for e in result.events]
    assert events.index("effect_cost_paid") < events.index("deck_refreshed") < events.index("effect_inspection_started")
    choice = result.state.pending_choice.options
    assert choice["inspected_card_instance_ids"][0] == "good-member"
    assert len(choice["inspected_card_instance_ids"]) == state.effect_definitions[code + ":1"].choice.amount
    final = apply_action(result.state, _select(result.state, choice["candidate_card_instance_ids"][:choice["minimum"]]))
    assert final.state.pending_choice is None and not final.state.pending_effects
    assert not any(e.event_type == "effect_cost_paid" for e in final.events)


@pytest.mark.parametrize("code", PRIVATE)
def test_private_must_keep_one_even_when_only_discarded_cost_can_be_refreshed(code):
    state = _state(code)
    state.players["player_1"].main_deck = []
    state = apply_action(state, _play(state)).state
    inspected = _inspect(state)
    assert inspected.state.pending_choice.options["inspected_card_instance_ids"] == ["cost"]
    final = apply_action(inspected.state, _select(inspected.state, ["cost"]))
    assert final.state.players["player_1"].hand == ["cost"]
    assert final.state.pending_choice is None and not final.state.pending_effects


def test_heart_filter_uses_member_heart_not_blade_heart_or_live_required_heart():
    state = _state(HEART)
    state.cards["blade-heart"].card.basic_hearts = {}
    state.cards["blade-heart"].card.blade_heart_color_slot = "heart05"
    state = apply_action(state, _play(state)).state
    result = _inspect(state)
    assert set(result.state.pending_choice.options["candidate_card_instance_ids"]) == {"good-member", "wrong-work"}


@pytest.mark.parametrize("code", CODES)
def test_new_cost_policy_rejects_appended_unverified_text_and_unreviewed_card(code):
    from loveca.simulation.effect_candidates import _onplay_audited_discard_inspection
    effect = _state(code).effect_definitions[code + ":1"]
    row = {"card_code": code, "text_revision_id": effect.text_revision_id,
           "raw_text_hash": effect.raw_text_hash, "raw_effect_text_ja": effect.label_ja}
    assert _onplay_audited_discard_inspection(row) is not None
    assert _onplay_audited_discard_inspection({**row, "raw_effect_text_ja": effect.label_ja + "カードを1枚引く。"}) is None
    assert _onplay_audited_discard_inspection({**row, "card_code": "AUDIT-not-reviewed"}) is None


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("legacy", (False, True))
def test_sql_unpayable_old_snapshot_still_requires_decline_instead_of_new_cancel(tmp_path, code, legacy):
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
    result = repo.apply(state.match_id, _resolve(state, accepted=not legacy))
    assert result.state.pending_choice is None and not result.state.pending_effects
    assert result.state.players["player_1"].main_deck == state.players["player_1"].main_deck
    assert not any(e.event_type in {"effect_cost_paid", "effect_inspection_started", "effect_skipped"} for e in result.events)
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")
