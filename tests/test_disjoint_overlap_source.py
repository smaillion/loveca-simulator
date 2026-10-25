import json
from contextlib import closing
from functools import lru_cache
from pathlib import Path

import pytest
from test_attachment_promotion import _trigger
from test_occupied_effect_deployment import ROOT, _request
from test_occupied_effect_deployment import _state as base_state

from loveca.db.bootstrap import connect_database
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effects import EffectDefinition, EffectOperation, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import MatchState
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

POLICY = "ignore_disjoint_source_triggers"
RULE_REFERENCE_IDS = ("9.7.2", "10.1.2", "10.4.1", "11.4.2")
ACTUAL_CARDS = (
    "PL!N-pb1-013", "PL!N-pb1-015", "PL!N-pb1-017", "PL!N-pb1-023",
    "PL!HS-bp6-014", "PL!-PR-020",
)


@lru_cache
def _actual(card_code):
    effects = {e.effect_id: e for e in load_effect_registry().effects if e.card_code == card_code}
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        card = _load_definition(connection, card_code, None, effects, {})
    assert effects
    assert all(e.raw_text_hash == card.raw_text_hash and e.text_revision_id == card.text_revision_id
               for e in effects.values())
    return card, effects


def _state(card_code=ACTUAL_CARDS[0], *, modern=True):
    state = base_state()
    state.member_overlap_policy = "capture_fixed_draw_and_energy_entry_observers"
    card, effects = _actual(card_code)
    state.cards["old"].card = card.model_copy(deep=True)
    state.effect_definitions.update({k: e.model_copy(deep=True) for k, e in effects.items()})
    if modern:
        raw = state.effect_definitions[ROOT].model_dump(mode="json")
        raw["actions"][0]["overlap_observer_policy"] = POLICY
        state.effect_definitions[ROOT] = EffectDefinition.model_validate(raw)
    return state


def _options(state):
    return next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect").options["invocations"][0]


@pytest.mark.parametrize("card_code", ACTUAL_CARDS)
def test_real_outgoing_cards_do_not_retrigger_unrelated_abilities(card_code):
    state = _state(card_code)
    assert _options(state)["position_change_slots_by_candidate"]["target"] == ["right"]
    before = state.model_dump(mode="json")
    result = apply_action(state, _request(state))
    player = result.state.players["player_1"]
    assert player.member_area["right"] == "target"
    assert "old" in player.waiting_room
    assert "attached-member" in player.waiting_room
    assert "energy-3" in player.energy_deck
    assert not player.manual_modifiers
    assert len(player.hand) == len(state.players["player_1"].hand) + 2
    outgoing_ids = set(_actual(card_code)[1])
    assert not any(e.event_type in {"effect_triggered", "effect_not_activatable", "effect_resolved"}
                   and e.data.get("effect_id") in outgoing_ids for e in result.events)
    assert state.model_dump(mode="json") == before
    assert not result.state.pending_effects


@pytest.mark.parametrize("card_code", ACTUAL_CARDS)
def test_legacy_operation_keeps_its_conservative_slot_exclusion(card_code):
    state = _state(card_code, modern=False)
    options = _options(state)
    assert "right" not in options["position_change_slots_by_candidate"].get("target", [])
    assert options["deployment_unsupported_slots"]["right"] == "outgoing_effect_requires_overlap_timing_review"
    assert "overlap_observer_policy" not in state.effect_definitions[ROOT].actions[0].model_dump()
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _request(state))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("trigger,kind", [
    ("own_member_played", "triggered"),
    ("static_always", "static"),
    ("member_left_stage_to_waiting_room", "triggered"),
    ("member_played|own_member_played", "triggered"),
    ("unknown_timing", "triggered"),
])
def test_true_observers_static_combined_and_unknown_timings_remain_blocked(trigger, kind):
    state = _state()
    effect = _trigger("audit-risk:1", trigger)
    effect.effect_type = kind
    effect.condition = {"total_stage_member_count_at_least": 4}
    state.effect_definitions[effect.effect_id] = effect
    state.cards["old"].card.effect_ids = [effect.effect_id]
    state.cards["old"].card.raw_effect_text_ja = effect.label_ja
    before = match_state_hash(state)
    assert "right" not in _options(state)["position_change_slots_by_candidate"].get("target", [])
    with pytest.raises(IllegalActionError):
        apply_action(state, _request(state))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("trigger,kind", [
    ("member_played", "triggered"), ("live_started", "triggered"),
    ("live_succeeded", "triggered"), ("player_activation", "activated"),
])
def test_disjoint_timing_does_not_evaluate_or_trigger_its_cost_and_stage_condition(trigger, kind):
    state = _state()
    effect = _trigger("audit-unrelated:1", trigger)
    effect.effect_type = kind
    effect.condition = {"total_stage_member_count_at_least": 99}
    effect.cost = [EffectOperation(action_type="pay_energy", amount=99)]
    state.effect_definitions[effect.effect_id] = effect
    state.cards["old"].card.effect_ids = [effect.effect_id]
    state.cards["old"].card.raw_effect_text_ja = effect.label_ja
    result = apply_action(state, _request(state))
    assert result.state.players["player_1"].member_area["right"] == "target"
    assert not any(e.data.get("effect_id") == effect.effect_id for e in result.events)
    assert sum(result.state.cards[i].orientation == "wait" for i in result.state.players["player_1"].energy_area) == 2


@pytest.mark.parametrize("trigger,kind", [
    ("member_played", "static"), ("player_activation", "triggered"),
    ("live_started|member_played", "triggered"),
])
def test_misclassified_or_combined_timing_is_not_guessed(trigger, kind):
    state = _state()
    effect = _trigger("audit-unrelated:1", trigger)
    effect.effect_type = kind
    effect.effect_index = 2
    state.effect_definitions[effect.effect_id] = effect
    state.cards["old"].card.effect_ids.append(effect.effect_id)
    state.cards["old"].card.raw_effect_text_ja += effect.label_ja
    assert "right" not in _options(state)["position_change_slots_by_candidate"].get("target", [])


def test_known_disjoint_ability_does_not_hide_an_unknown_second_ability():
    state = _state()
    state.cards["old"].card.effect_ids.append("unknown-second:1")
    assert "right" not in _options(state)["position_change_slots_by_candidate"].get("target", [])


def test_plain_member_without_ability_text_needs_no_registry_binding():
    state = _state()
    source = state.cards["old"].card
    source.effect_ids = []
    source.raw_effect_text_ja = None
    source.ability_bucket = "none"
    source.effect_registry_status = "unregistered"
    assert apply_action(state, _request(state)).state.players["player_1"].member_area["right"] == "target"


@pytest.mark.parametrize("gap", ["missing_segment", "unregistered", "hash_errors", "unknown_definition"])
def test_partial_or_invalid_source_binding_is_not_mistaken_for_complete(gap):
    state = _state()
    source = state.cards["old"].card
    if gap == "missing_segment":
        source.raw_effect_text_ja += "\n【常時】監査用の未登録能力。"
    elif gap == "unregistered":
        source.effect_registry_status = "unregistered"
    elif gap == "hash_errors":
        source.effect_registry_errors = ["raw_text_hash mismatch"]
    else:
        source.effect_ids.append("missing:2")
    options = _options(state)
    assert options["deployment_unsupported_slots"]["right"] == "outgoing_source_text_requires_overlap_timing_review"
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _request(state))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("location", ["attached", "incoming", "other_member", "missing"])
def test_new_policy_does_not_ignore_other_overlap_gaps(location):
    state = _state()
    effect = _trigger("audit-risk:1", "own_member_played")
    effect.condition = {"total_stage_member_count_at_least": 4}
    state.effect_definitions[effect.effect_id] = effect
    if location == "attached":
        state.cards["attached-member"].card.effect_ids = list(_actual(ACTUAL_CARDS[0])[1])
    elif location == "incoming":
        state.effect_definitions["audit-onplay:1"].condition = effect.condition
    elif location == "other_member":
        state.cards["source-live"].card.effect_ids = [effect.effect_id]
    else:
        state.cards["old"].card.effect_ids = ["not-in-snapshot:1"]
    before = match_state_hash(state)
    assert "right" not in _options(state)["position_change_slots_by_candidate"].get("target", [])
    with pytest.raises(IllegalActionError):
        apply_action(state, _request(state))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("card_code", ACTUAL_CARDS)
def test_real_cards_sql_replay_and_hidden_views(tmp_path, card_code):
    state = _state(card_code)
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repository.apply(state.match_id, _request(state))
    replay = repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")
    assert replay["metadata"]["final_state_hash"] == match_state_hash(result.state)
    assert replay["events"] == [e.model_dump(mode="json") for e in result.events]
    for actor, hidden in (("player_1", "opponent-private"), ("player_2", "live-1")):
        payload = _match_state_payload(result.state, events=result.events,
                                       legal_actions=result.legal_actions, player_id=actor)
        assert hidden not in payload["state"]["cards"]
        assert f'"{hidden}"' not in json.dumps(payload["events"])


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_ai_chooses_newly_legal_slot_without_reading_hidden_hand(policy):
    state = _state()
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision)
    assert decision.action.payload["to_slot"] == "right"
    assert apply_action(state, decision.action).state.players["player_1"].member_area["right"] == "target"
    hidden_changed = state.model_copy(deep=True)
    hidden_changed.cards["opponent-private"].card.card_code = "PRIVATE-CHANGED"
    assert controller.choose_action(hidden_changed, generate_legal_actions(hidden_changed),
                                    controlled_player_ids={"player_1"}).action == decision.action


@pytest.mark.parametrize("action_type", ["draw_card", "gain_blade", "deploy_selected_to_empty_stage", "pay_energy"])
def test_policy_cannot_be_used_on_other_operations(action_type):
    with pytest.raises(ValueError, match="overlap observer policy"):
        EffectOperation(action_type=action_type, amount=1, overlap_observer_policy=POLICY)


def test_observer_policy_cannot_be_applied_as_a_deployment_cost():
    raw = _state().effect_definitions[ROOT].model_dump(mode="json")
    raw["cost"] = [raw["actions"][0]]
    with pytest.raises(ValueError, match="overlap observer policy cannot be used as a cost"):
        EffectDefinition.model_validate(raw)


def test_legacy_operation_serialization_and_all_six_deployment_registrations_unchanged():
    operation = EffectOperation(action_type="draw_card", amount=1)
    assert "overlap_observer_policy" not in operation.model_dump(mode="json")
    state = _state()
    restored = MatchState.model_validate_json(state.model_dump_json())
    assert match_state_hash(restored) == match_state_hash(state)
    registry = load_effect_registry()
    ids = {"PL!-PR-015:1", "PL!SP-PR-020:1", *(f"{card}:1" for card in ACTUAL_CARDS[:4])}
    entries = [e for e in registry.effects if e.effect_id in ids]
    assert len(entries) == 6
    assert all(e.simulation_support == "manual_resolution" for e in entries)
