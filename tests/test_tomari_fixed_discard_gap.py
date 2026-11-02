import json

import pytest

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.online import match_state_hash
from loveca.webapp import _match_state_payload
from test_printemps_ready_history_boundary import _repo, _replay, _resolve
from test_tomari_all_hand_discard_scope import EFFECT, _actual, _play_for

PROBE = "UNREGISTERED-TOMARI-FIXED-COST:1"


def _probe(owner, count=3, short=False):
    state = _actual(owner, count, short)
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id=PROBE, card_code="UNREGISTERED-TOMARI-FIXED-COST",
               execution_mode="prompt_then_resolve", simulation_support="test_validated_executable",
               review_status="test_validated", cost=[{"action_type": "discard_from_hand"}],
               cost_choice={"choice_type": "card_from_zone", "zone": "hand", "target_player": "self",
                            "minimum": 1, "maximum": 3},
               actions=[{"action_type": "draw_card", "amount": 6}])
    state.effect_definitions = {PROBE: EffectDefinition.model_validate(raw)}
    state.cards["source-live"].card.card_code = "UNREGISTERED-TOMARI-FIXED-COST"
    state.cards["source-live"].card.effect_ids = [PROBE]
    return state


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("chosen", [1, 3])
def test_fixed_cost_accepts_partial_and_full_within_bound_sql(tmp_path, owner, chosen):
    state = _probe(owner, 3)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    selected = list(current.players[owner].hand[:chosen])
    remaining = set(current.players[owner].hand) - set(selected)
    result = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True,
                                                 selected_card_instance_ids=selected))
    assert all(i in result.state.players[owner].waiting_room for i in selected)
    assert remaining <= set(result.state.players[owner].hand)
    draws = [e for e in result.events if e.event_type == "cards_drawn"]
    assert len(draws) == 1 and len(draws[0].data["instance_ids"]) == 6
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("selection", ["too_many", "duplicate", "unknown", "empty"])
def test_fixed_cost_rejects_invalid_selection_atomically_sql(tmp_path, owner, selection):
    state = _probe(owner, 4)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    hand = list(current.players[owner].hand)
    ids = {"too_many": hand, "duplicate": [hand[0], hand[0]], "unknown": ["not-in-hand"], "empty": []}[selection]
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=ids))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_short_deck_probe_draws_available_cards_after_cost_refresh_sql(tmp_path, owner):
    state = _probe(owner, 3, short=True)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    chosen = list(current.players[owner].hand)
    result = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=chosen))
    assert any(e.event_type == "deck_refreshed" for e in result.events)
    draws = [e for e in result.events if e.event_type == "cards_drawn"]
    assert len(draws) == 1 and len(draws[0].data["instance_ids"]) == 4
    assert set(chosen) <= set(result.state.players[owner].hand)
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_empty_hand_has_no_selectable_payment_sql(tmp_path, owner):
    state = _probe(owner, 0)
    repo = _repo(state, tmp_path)
    result = repo.apply(state.match_id, _play_for(state, owner))
    assert not result.state.pending_effects
    event = next(e for e in result.events if e.event_type == "effect_not_activatable")
    assert event.data["effect_id"] == PROBE and event.data["reason"] == "cost_choice_candidates_unavailable"
    assert not any(e.event_type in {"effect_cost_paid", "cards_drawn"} for e in result.events)
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_and_hidden_opponent_invariance(owner, policy):
    state = _probe(owner, 4)
    current = apply_action(state, _play_for(state, owner)).state
    before = match_state_hash(current)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    decision = controller.choose_action(current, generate_legal_actions(current), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    selected = decision.action.payload["selected_card_instance_ids"]
    assert len(selected) == (3 if policy == "simple_ai_v0" else 1)
    changed = current.model_copy(deep=True)
    opponent = "player_2" if owner == "player_1" else "player_1"
    player = changed.players[opponent]
    for key in list(player.main_deck + player.hand):
        item = changed.cards.pop(key)
        replacement = "hidden-" + key
        item.instance_id = replacement
        item.card.name_ja = item.card.card_code = "HIDDEN"
        item.card.blade = 99
        changed.cards[replacement] = item
        player.main_deck = [replacement if i == key else i for i in player.main_deck]
        player.hand = [replacement if i == key else i for i in player.hand]
    changed_before = match_state_hash(changed)
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner}) == decision
    assert match_state_hash(changed) == changed_before and match_state_hash(current) == before
    resolved = apply_action(current, decision.action).state
    assert set(current.players[owner].hand) - set(selected) <= set(resolved.players[owner].hand)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_real_onplay_events_and_constructed_provider_privacy(owner):
    state = _probe(owner, 3)
    triggered = apply_action(state, _play_for(state, owner))
    current = triggered.state
    for viewer in ("player_1", "player_2"):
        payload = _match_state_payload(current, events=triggered.events,
                                       legal_actions=generate_legal_actions(current), player_id=viewer)
        for player in current.players.values():
            assert all(i not in payload["state"]["cards"] for i in player.main_deck)
            if player.player_id != viewer:
                assert all(i not in payload["state"]["cards"] for i in player.hand)
                assert all(i not in json.dumps(payload) for i in player.hand)
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    opponent = "player_2" if owner == "player_1" else "player_1"
    for builder in (build_api_play_context, build_agent_context):
        serialized = json.dumps(builder(current, generate_legal_actions(current)))
        assert all(i not in serialized for i in current.players[opponent].hand + current.players[opponent].main_deck)
