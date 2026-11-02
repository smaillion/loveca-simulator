import hashlib
import json

import pytest

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.engine import apply_action, generate_legal_actions
from loveca.simulation.online import match_state_hash
from loveca.webapp import _match_state_payload
from test_mirakura_front_position_boundary import _swap_roles
from test_multi_keep_inspection_audit import CODE, _state as _legacy_state
from test_nijigasaki_inspection import _play, _resolve, _select
from test_printemps_ready_history_boundary import _repo, _replay


def _state(owner):
    state = _legacy_state(legacy=True)
    return _swap_roles(state) if owner == "player_2" else state


def _action(request, owner):
    request.player_id = owner
    return request


def test_q124_identity_and_historical_formal_manual_snapshot():
    state = _legacy_state()
    card = state.cards["source-live"].card
    assert card.raw_text_hash == hashlib.sha256(card.raw_effect_text_ja.encode()).hexdigest()
    assert (card.text_revision_id, card.raw_text_hash) == (548, "1d864314344a8d252f580ccee32897f33b3926a9ee9ff37cc5ca64439197da93")
    assert state.effect_definitions[CODE + ":1"].simulation_support == "manual_resolution"


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_legacy_snapshot_actual_cost_and_private_multi_keep_sql(tmp_path, owner, count):
    state = _state(owner)
    play = _action(_play(state), owner)
    play.payload["energy_instance_ids"] = state.players[owner].energy_area
    repo = _repo(state, tmp_path)
    played = repo.apply(state.match_id, play).state
    inspected = repo.apply(state.match_id, _action(_resolve(played, selected_card_instance_ids=["cost"]), owner))
    assert sum(e.event_type == "effect_cost_paid" for e in inspected.events) == 1
    choices = inspected.state.pending_choice.options
    opponent = "player_2" if owner == "player_1" else "player_1"
    view = _match_state_payload(inspected.state, events=inspected.events,
        legal_actions=inspected.legal_actions, player_id=opponent)
    assert not any(card in json.dumps(view) for card in choices["inspected_card_instance_ids"])
    assert set(choices["candidate_card_instance_ids"]) == {"good-member", "wrong-work", "tail"}
    assert "blade-heart" not in choices["candidate_card_instance_ids"]
    picked = ["good-member", "wrong-work", "tail"][:count]
    result = repo.apply(state.match_id, _action(_select(inspected.state, picked), owner))
    final = result.state
    assert set(final.players[owner].hand) == set(picked)
    assert set(final.players[owner].waiting_room) == {"cost", *state.players[owner].main_deck} - set(picked)
    resolved = next(e for e in result.events if e.event_type == "effect_resolved")
    assert {card["instance_id"] for card in resolved.data["revealed_cards"]} == set(picked)
    _replay(repo, final)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_legacy_cost_and_choice_opponent_hidden_invariance_sql(tmp_path, owner, policy):
    state = _state(owner)
    action = _action(_play(state), owner)
    action.payload["energy_instance_ids"] = state.players[owner].energy_area
    repo = _repo(state, tmp_path)
    played = repo.apply(state.match_id, action).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(played)
    first = controller.choose_action(played, generate_legal_actions(played), controlled_player_ids={owner})
    assert isinstance(first, SimpleAIDecision)
    assert match_state_hash(played) == before
    inspected = repo.apply(state.match_id, first.action).state
    before = match_state_hash(inspected)
    choice = controller.choose_action(inspected, generate_legal_actions(inspected), controlled_player_ids={owner})
    changed = inspected.model_copy(deep=True)
    opponent = "player_2" if owner == "player_1" else "player_1"
    item = changed.cards.pop("opponent-secret")
    item.instance_id = "hidden-replacement"
    item.card.card_code = item.card.name_ja = "HIDDEN"
    item.card.unit_keys, item.card.work_keys, item.card.blade = ["bibi"], ["hasunosora"], 99
    changed.cards[item.instance_id] = item
    changed.players[opponent].hand = [item.instance_id if x == "opponent-secret" else x for x in changed.players[opponent].hand]
    changed_before = match_state_hash(changed)
    other = controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner})
    assert isinstance(choice, SimpleAIDecision) and isinstance(other, SimpleAIDecision)
    assert choice.action == other.action
    assert match_state_hash(inspected) == before and match_state_hash(changed) == changed_before
    final = repo.apply(state.match_id, choice.action).state
    apply_action(changed, other.action)
    _replay(repo, final)
    for viewer in ("player_1", "player_2"):
        payload = _match_state_payload(inspected, events=[], legal_actions=generate_legal_actions(inspected), player_id=viewer)
        if viewer != owner:
            assert not any(key in json.dumps(payload) for key in inspected.pending_choice.options["inspected_card_instance_ids"])
        else:
            assert "opponent-secret" not in payload["state"]["cards"]
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    for builder in (build_api_play_context, build_agent_context):
        assert "opponent-secret" not in json.dumps(builder(inspected, generate_legal_actions(inspected)))
