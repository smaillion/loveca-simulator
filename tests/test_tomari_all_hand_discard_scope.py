import hashlib
import json

import pytest

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import CardInstance
from loveca.simulation.online import match_state_hash
from loveca.webapp import _match_state_payload
from test_mirakura_front_position_boundary import _swap_roles
from test_nijigasaki_inspection import _play, _state as _base_state
from test_printemps_ready_history_boundary import _repo, _replay, _resolve

CODE = "PL!SP-bp7-011"
EFFECT = CODE + ":1"
HASH = "b7059cac5ef0714461ff84dc7320429e4204db2a0550469eb016a44f325fef69"


def _actual(owner, count=1, short=False):
    state = _base_state(CODE)
    p = state.players["player_1"]
    p.hand = ["source-live"]
    for index in range(count):
        key = f"private-cost-{index}"
        state.cards[key] = CardInstance(instance_id=key, owner_id="player_1",
            card=state.cards["cost"].card.model_copy(deep=True), face_up=False)
        p.hand.append(key)
    if short:
        p.main_deck = p.main_deck[:1]
    if owner == "player_2":
        state = _swap_roles(state)
    return state


def _play_for(state, owner):
    action = _play(state)
    action.player_id = owner
    action.payload["energy_instance_ids"] = state.players[owner].energy_area
    return action


def test_exact_card_identity_and_manual_snapshot():
    state = _actual("player_1")
    card = state.cards["source-live"].card
    assert (card.name_ja, card.cost, card.blade, card.text_revision_id) == ("鬼塚冬毬", 9, 4, 898)
    assert hashlib.sha256(card.raw_effect_text_ja.encode()).hexdigest() == card.raw_text_hash == HASH
    effect = state.effect_definitions[EFFECT]
    assert effect.execution_mode == effect.simulation_support == "manual_resolution"
    assert effect.is_optional and not effect.cost and effect.choice is None


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("count,short", [(0, False), (1, False), (3, False), (3, True)])
def test_native_onplay_manual_rejects_automatic_acceptance_and_declines_sql(tmp_path, owner, count, short):
    state = _actual(owner, count, short)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    assert [i.effect_id for i in current.pending_effects] == [EFFECT]
    assert len(current.players[owner].hand) == count
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _resolve(current, EFFECT, accepted=True,
                   selected_card_instance_ids=list(current.players[owner].hand)))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    player_before = current.players[owner].model_dump(mode="json")
    result = repo.apply(state.match_id, _resolve(current, EFFECT, accepted=False))
    assert result.state.players[owner].model_dump(mode="json") == player_before
    assert not result.state.pending_effects
    assert not any(e.event_type in {"effect_cost_paid", "cards_drawn"} for e in result.events)
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_decline_and_hidden_opponent_identity_is_irrelevant(owner, policy):
    state = _actual(owner, 3)
    current = apply_action(state, _play_for(state, owner)).state
    before = match_state_hash(current)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    decision = controller.choose_action(current, generate_legal_actions(current), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision) and decision.action.payload.get("accepted") is False
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
    assert resolved.players[owner].hand == current.players[owner].hand


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_actual_onplay_events_and_constructed_provider_privacy(owner):
    state = _actual(owner, 3)
    triggered = apply_action(state, _play_for(state, owner))
    current = triggered.state
    for viewer in ("player_1", "player_2"):
        payload = _match_state_payload(current, events=triggered.events,
                                       legal_actions=generate_legal_actions(current), player_id=viewer)
        for player in current.players.values():
            assert all(i not in payload["state"]["cards"] for i in player.main_deck)
            if player.player_id != viewer:
                assert all(i not in payload["state"]["cards"] for i in player.hand)
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    opponent = "player_2" if owner == "player_1" else "player_1"
    for builder in (build_api_play_context, build_agent_context):
        serialized = json.dumps(builder(current, generate_legal_actions(current)))
        assert all(i not in serialized for i in current.players[opponent].hand + current.players[opponent].main_deck)
