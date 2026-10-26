from pathlib import Path

import pytest
from test_nijigasaki_inspection import _play, _resolve, _select
from test_nijigasaki_inspection import _state as _base_state
from test_work_unit_inspection import _candidates

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effect_candidates import (
    MULTI_KEEP_ICON_SCOPE_REASON,
    MULTI_KEEP_ICON_SCOPE_TEXT,
    _onplay_multi_keep_icon_scope_manual,
)
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload
from tools.ai_sandbox.effect_gap_report import classify_unresolved_reason, suggest_next_step

CODE = "PL!S-bp2-005"
RULE_REFERENCE_IDS = ("2.1.3", "2.7.1", "2.9.1", "5.7.1", "9.4.2", "9.7.3.2", "10.2.2.2", "10.2.3")


def _state(*, legacy=False, empty=False):
    state = _base_state(CODE)
    if legacy:
        raw = state.effect_definitions[CODE + ":1"].model_dump(mode="json")
        raw.update(execution_mode="prompt_then_resolve", simulation_support="test_validated_executable",
                   review_status="test_validated", source_reference="Official card text; comprehensive rules ver. 1.06 restricted executor pattern",
                   cost=[{"action_type": "discard_from_hand"}],
                   cost_choice={"choice_type": "card_from_zone", "zone": "hand", "minimum": 1, "maximum": 1},
                   choice={"choice_type": "inspect_top_select", "amount": 7, "card_type": "member",
                           "heart_color_slots_any": ["heart02", "heart04", "heart05"], "minimum": 0, "maximum": 3,
                           "selected_destination": "hand", "unselected_destination": "waiting_room", "reveal_selected_to_opponent": True},
                   actions=[{"action_type": "inspect_top_cards", "amount": 7},
                            {"action_type": "select_to_hand_from_inspected"}, {"action_type": "move_remaining_cards"}])
        state.effect_definitions[CODE + ":1"] = EffectDefinition.model_validate(raw)
    for key, color in (("good-member", "heart02"), ("wrong-work", "heart04"), ("tail", "heart05"), ("blade-heart", "heart01")):
        state.cards[key].card.basic_hearts = {color: 1}
    state.cards["blade-heart"].card.blade_heart_color_slot = "heart02"
    state.cards["good-live"].card.required_hearts = {"heart04": 3}
    extra = state.cards["good-member"].model_copy(deep=True)
    extra.instance_id, extra.card.card_code, extra.card.name_ja = "extra", "AUDIT-extra", "AUDIT-extra"
    extra.card.basic_hearts = {"heart06": 1}
    state.cards["extra"] = extra
    state.players["player_1"].main_deck = ["good-member", "wrong-work", "tail", "blade-heart", "good-live", "deck-live-1", "extra"]
    if empty:
        state.players["player_1"].hand = ["source-live"]
    return state


def test_exact_identity_is_explicitly_manual_with_a_structured_gap_reason():
    state = _state()
    effect = state.effect_definitions[CODE + ":1"]
    assert (effect.text_revision_id, effect.raw_text_hash) == (548, "1d864314344a8d252f580ccee32897f33b3926a9ee9ff37cc5ca64439197da93")
    assert state.cards["source-live"].card.cost == 13
    assert effect.label_ja == MULTI_KEEP_ICON_SCOPE_TEXT
    assert effect == EffectDefinition.model_validate(_candidates()[effect.effect_id].to_registry_entry())
    assert effect.execution_mode == effect.simulation_support == "manual_resolution"
    assert effect.review_status == "parsed_draft" and not effect.cost and effect.choice is None
    assert MULTI_KEEP_ICON_SCOPE_REASON in effect.source_reference
    assert classify_unresolved_reason(effect.trigger, effect.timing, effect.label_ja) == MULTI_KEEP_ICON_SCOPE_REASON
    assert suggest_next_step(effect.trigger, effect.timing, effect.label_ja).startswith("review_printed_icon_scope")
    row = {"card_code": CODE, "text_revision_id": 548, "raw_text_hash": effect.raw_text_hash, "raw_effect_text_ja": effect.label_ja}
    assert _onplay_multi_keep_icon_scope_manual({**row, "raw_effect_text_ja": effect.label_ja + "カードを1枚引く。"}) is None
    assert _onplay_multi_keep_icon_scope_manual({**row, "card_code": "AUDIT-unknown"}) is None


@pytest.mark.parametrize("empty", (False, True))
def test_new_manual_guard_is_atomic_and_does_not_pay_or_inspect(empty):
    state = _state(empty=empty)
    state = apply_action(state, _play(state)).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state))
    assert match_state_hash(state) == before
    options = next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect").options["invocations"][0]
    assert options["simulation_support"] == "manual_resolution" and options["label_ja"] == MULTI_KEEP_ICON_SCOPE_TEXT
    assert not options.get("inspection_choice")
    assert any(a.action_type == "manual_adjustment" for a in generate_legal_actions(state))
    result = apply_action(state, _resolve(state, accepted=False))
    assert result.state.pending_choice is None and not result.state.pending_effects
    assert result.state.players["player_1"].hand == state.players["player_1"].hand
    assert result.state.players["player_1"].main_deck == state.players["player_1"].main_deck
    assert not any(e.event_type in {"effect_cost_paid", "effect_inspection_started", "effect_skipped"} for e in result.events)


@pytest.mark.parametrize("keep", (0, 1, 2, 3))
def test_legacy_zero_to_three_is_historical_behavior_not_new_rule_approval(tmp_path, keep):
    state = _state(legacy=True)
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state))
    inspected = repo.apply(state.match_id, _resolve(played.state, selected_card_instance_ids=["cost"]))
    choice = inspected.state.pending_choice.options
    assert choice["inspected_card_instance_ids"] == state.players["player_1"].main_deck
    assert set(choice["candidate_card_instance_ids"]) == {"good-member", "wrong-work", "tail"}
    assert "blade-heart" not in choice["candidate_card_instance_ids"]
    assert sum(e.event_type == "effect_cost_paid" for e in inspected.events) == 1
    target = ["good-member", "wrong-work", "tail"][:keep]
    final = repo.apply(state.match_id, _select(inspected.state, target))
    assert final.state.players["player_1"].hand == target
    assert set(final.state.players["player_1"].waiting_room) == {"cost", *state.players["player_1"].main_deck} - set(target)
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("ids", (["good-member", "wrong-work", "tail", "blade-heart"], ["good-member", "good-member"], ["good-live"], ["opponent-secret"]))
def test_legacy_invalid_selection_is_atomic(ids):
    state = _state(legacy=True)
    state = apply_action(state, _play(state)).state
    state = apply_action(state, _resolve(state, selected_card_instance_ids=["cost"])).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _select(state, ids))
    assert match_state_hash(state) == before


def test_legacy_unpayable_and_refresh_order_are_preserved():
    state = _state(legacy=True, empty=True)
    state = apply_action(state, _play(state)).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state))
    assert match_state_hash(state) == before
    state = _state(legacy=True)
    state.players["player_1"].main_deck = ["good-member"]
    state.players["player_1"].waiting_room = ["wrong-work", "tail", "blade-heart", "good-live", "deck-live-1", "extra"]
    state = apply_action(state, _play(state)).state
    inspected = apply_action(state, _resolve(state, selected_card_instance_ids=["cost"]))
    kinds = [e.event_type for e in inspected.events]
    assert kinds.index("effect_cost_paid") < kinds.index("deck_refreshed") < kinds.index("effect_inspection_started")
    assert inspected.state.pending_choice.options["inspected_card_instance_ids"][0] == "good-member"


@pytest.mark.parametrize("empty", (False, True))
@pytest.mark.parametrize("policy", ("simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"))
def test_four_policies_explicitly_decline_optional_manual_without_hidden_dependency(tmp_path, empty, policy):
    state = _state(empty=empty)
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    state = repo.apply(state.match_id, _play(state)).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision) and match_state_hash(state) == before
    assert decision.reason == "decline_optional_manual_effect" and decision.action.payload["accepted"] is False
    changed = state.model_copy(deep=True)
    changed.cards["opponent-secret"].card.card_code = "AUDIT-hidden-changed"
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}).action == decision.action
    result = repo.apply(state.match_id, decision.action)
    assert result.state.players["player_1"].main_deck == state.players["player_1"].main_deck
    assert result.state.players["player_1"].hand == state.players["player_1"].hand
    assert not result.state.pending_effects and result.state.pending_choice is None
    assert any(e.event_type == "ai_action_selected" and e.data["reason"] == "decline_optional_manual_effect" for e in result.events)
    assert not any(e.event_type in {"effect_cost_paid", "effect_inspection_started", "effect_skipped"} for e in result.events)
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")


def test_manual_control_is_explicit_replayable_and_opponent_hand_stays_private(tmp_path):
    state = _state()
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    state = repo.apply(state.match_id, _play(state)).state
    invocation = state.pending_effects[0]
    action = ActionRequest(action_type="manual_adjustment", player_id="player_1", expected_revision=state.revision,
        payload={"source_invocation_id": invocation.invocation_id, "source_effect_id": invocation.effect_id,
                 "source_card_instance_id": invocation.source_card_instance_id, "reason": "AUDIT acknowledges unresolved card; no effect execution",
                 "adjustments": [{"adjustment_type": "set_flag", "target_player_id": "player_1", "flag": "audit_unresolved_acknowledged", "duration": "turn"}]})
    result = repo.apply(state.match_id, action)
    assert not result.state.pending_effects and result.state.pending_choice is None
    assert result.state.players["player_1"].main_deck == state.players["player_1"].main_deck
    other = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id="player_2")
    assert "opponent-secret" in other["state"]["cards"]
    own = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id="player_1")
    assert "opponent-secret" not in own["state"]["cards"]
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")
