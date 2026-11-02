from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_nijigasaki_inspection import _play, _resolve, _select
from test_nijigasaki_inspection import _state as _base_state

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

POLICY = "public_four_lily_white_live"
EFFECT = "PROTOTYPE-public-four:1"


def _state():
    state = _base_state("PL!-pb2-013")
    raw = state.effect_definitions["PL!-pb2-013:1"].model_dump(mode="json")
    raw.update(
        effect_id=EFFECT, card_code="PROTOTYPE-public-four", execution_mode="prompt_then_resolve",
        simulation_support="test_validated_executable", review_status="test_validated",
        choice={"choice_type": "inspect_top_select", "selection_policy": POLICY,
                "amount": 4, "card_type": "live", "unit_key": "lily_white",
                "minimum": 1, "maximum": 1, "selected_destination": "hand",
                "unselected_destination": "waiting_room", "reveal_selected_to_opponent": True},
        actions=[{"action_type": "reveal_cards", "amount": 4},
                 {"action_type": "select_to_hand_from_inspected"},
                 {"action_type": "move_remaining_cards"}],
    )
    effect = EffectDefinition.model_validate(raw)
    state.effect_definitions = {EFFECT: effect}
    state.cards["source-live"].card.effect_ids = [EFFECT]
    for item in state.players["player_1"].main_deck[:4]:
        state.cards[item].card.unit_keys = ["lily_white"]
    return state


def _played(state=None):
    state = state or _state()
    return apply_action(state, _play(state)).state


def _revealed(state=None):
    state = state or _played()
    return apply_action(state, _resolve(state))


def test_prototype_never_binds_or_promotes_the_official_card():
    effect = next(e for e in load_effect_registry().effects if e.effect_id == "PL!-pb2-013:1")
    assert effect.simulation_support == "manual_resolution"
    assert effect.text_revision_id == 986
    assert effect.raw_text_hash == "0a06fcfee9cde86a6c33f9b5369470994fac45e9a4fe236a94aae1e9e7531f86"
    assert not any(e.effect_id == EFFECT for e in load_effect_registry().effects)


def test_public_reveal_keeps_original_deck_zone_and_order_until_resolution():
    state = _played()
    original = list(state.players["player_1"].main_deck)
    result = _revealed(state)
    choice = result.state.pending_choice.options
    assert choice["inspected_card_instance_ids"] == original[:4]
    assert choice["candidate_card_instance_ids"] == ["good-live"]
    assert choice["minimum"] == choice["maximum"] == 1
    assert result.state.players["player_1"].main_deck == original
    assert result.state.players["player_1"].resolution_area == []
    assert not any(e.event_type == "effect_cost_paid" for e in result.events)
    for viewer in ("player_1", "player_2"):
        payload = _match_state_payload(result.state, events=result.events,
                                       legal_actions=result.legal_actions, player_id=viewer)
        assert set(original[:4]) <= payload["state"]["cards"].keys()
        assert "tail" not in payload["state"]["cards"]
        event = next(e for e in payload["events"] if e["event_type"] == "effect_public_reveal_started")
        assert len(event["data"]["revealed_cards"]) == 4
    final = apply_action(result.state, _select(result.state, ["good-live"]))
    assert final.state.players["player_1"].hand == ["cost", "good-live"]
    assert final.state.players["player_1"].main_deck == original[4:]
    assert set(final.state.players["player_1"].waiting_room) == set(original[:4]) - {"good-live"}


@pytest.mark.parametrize("index", range(4))
def test_false_condition_reveals_but_does_not_discard_or_reorder(index):
    state = _played()
    original = list(state.players["player_1"].main_deck)
    state.cards[original[index]].card.unit_keys = ["printemps"]
    result = _revealed(state)
    assert result.state.pending_choice.options["condition_met"] is False
    assert result.state.pending_choice.options["candidate_card_instance_ids"] == []
    final = apply_action(result.state, _select(result.state, []))
    assert final.state.players["player_1"].main_deck == original
    assert final.state.players["player_1"].waiting_room == []
    assert final.state.players["player_1"].hand == ["cost"]
    assert all(not final.state.cards[x].face_up for x in original[:4])


def test_same_unit_different_work_is_allowed_and_no_live_resolves_zero():
    state = _played()
    original = list(state.players["player_1"].main_deck)
    for item in original[:4]:
        state.cards[item].card.work_keys = ["unrelated_work"]
        state.cards[item].card.card_type = "member"
    revealed = _revealed(state).state
    assert revealed.pending_choice.options["condition_met"] is True
    assert revealed.pending_choice.options["maximum"] == 0
    final = apply_action(revealed, _select(revealed, []))
    assert set(final.state.players["player_1"].waiting_room) == set(original[:4])


@pytest.mark.parametrize("count", range(4))
@pytest.mark.parametrize("waiting", [False, True])
def test_unresolved_short_deck_fails_before_any_state_change_or_refresh(count, waiting):
    state = _played()
    state.players["player_1"].main_deck = state.players["player_1"].main_deck[:count]
    if waiting:
        state.players["player_1"].waiting_room = ["tail"]
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError, match="short-deck"):
        _revealed(state)
    assert match_state_hash(state) == before


@pytest.mark.parametrize("selected", [[], ["good-member"], ["tail"],
                                      ["good-live", "good-live"], ["opponent-secret"]])
def test_illegal_public_selection_is_atomic(selected):
    state = _revealed().state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _select(state, selected))
    assert match_state_hash(state) == before


def test_stale_prefix_is_rejected_and_native_manual_leave_return_is_not_allowed():
    state = _revealed().state
    before = match_state_hash(state)
    action = ActionRequest(action_type="manual_adjustment", player_id="player_1",
        expected_revision=state.revision, payload={"adjustments": [
            {"adjustment_type": "move_card", "target_player_id": "player_1",
             "target_card_instance_id": "good-live", "to_zone": zone}
            for zone in ["hand", "main_deck"]]})
    with pytest.raises(IllegalActionError, match="inspection"):
        apply_action(state, action)
    assert match_state_hash(state) == before
    stale = state.model_copy(deep=True)
    stale.players["player_1"].main_deck.reverse()
    with pytest.raises(IllegalActionError, match="original public-reveal"):
        apply_action(stale, _select(stale, ["good-live"]))


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("mixed", [False, True])
def test_four_ai_public_choice_hidden_identity_invariance(policy, mixed):
    base = _played()
    if mixed:
        base.cards[base.players["player_1"].main_deck[0]].card.unit_keys = []
    state = _revealed(base).state
    ai = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    legal = generate_legal_actions(state)
    decision = ai.choose_action(state, legal, controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision)
    changed = state.model_copy(deep=True)
    changed.cards["opponent-secret"].card = changed.cards["good-live"].card.model_copy(deep=True)
    assert ai.choose_action(changed, generate_legal_actions(changed),
                            controlled_player_ids={"player_1"}).action == decision.action
    final = apply_action(state, decision.action)
    assert final.state.pending_choice is None


@pytest.mark.parametrize("mixed", [False, True])
def test_sql_replay_of_prototype_public_snapshot(tmp_path, mixed):
    state = _state()
    if mixed:
        state.cards["good-member"].card.unit_keys = []
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repository.apply(state.match_id, _play(state)).state
    revealed = repository.apply(state.match_id, _resolve(played)).state
    final = repository.apply(state.match_id, _select(revealed, [] if mixed else ["good-live"]))
    replay = repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("changes", [{"amount": 3}, {"minimum": 0}, {"maximum": 2},
                                     {"unit_key": "printemps"}, {"card_type": "member"}])
def test_policy_rejects_widened_choices(changes):
    raw = deepcopy(_state().effect_definitions[EFFECT].model_dump(mode="json"))
    raw["choice"].update(changes)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("mixed", [False, True])
@pytest.mark.parametrize("waiting", [False, True])
def test_exact_four_refreshes_only_after_actual_movement(mixed, waiting):
    base = _played()
    base.players["player_1"].main_deck = base.players["player_1"].main_deck[:4]
    if waiting:
        base.players["player_1"].waiting_room = ["tail"]
    if mixed:
        base.cards["good-member"].card.unit_keys = []
    revealed = _revealed(base)
    assert revealed.state.players["player_1"].refresh_count == base.players["player_1"].refresh_count
    final = apply_action(revealed.state, _select(revealed.state, [] if mixed else ["good-live"]))
    player = final.state.players["player_1"]
    assert player.refresh_count == base.players["player_1"].refresh_count + int(not mixed)
    assert len(player.main_deck) == (4 if mixed else 3 + int(waiting))


def test_public_marker_cannot_expose_an_old_private_inspection():
    base = _base_state("PL!N-sd2-009")
    played = apply_action(base, _play(base)).state
    result = apply_action(played, _resolve(played))
    result.state.pending_choice.options["public_reveal_policy"] = POLICY
    inspected = result.state.pending_choice.options["inspected_card_instance_ids"]
    payload = _match_state_payload(result.state, events=result.events,
                                  legal_actions=result.legal_actions, player_id="player_2")
    assert not set(inspected).intersection(payload["state"]["cards"])


@pytest.mark.parametrize("changes", [
    {"is_optional": True}, {"duration": "live"}, {"condition": {"success_live_count_at_least": 1}},
    {"trigger": "player_activation"}, {"frequency_limit": "once_per_turn"},
])
def test_policy_rejects_other_execution_contracts(changes):
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(changes)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)
