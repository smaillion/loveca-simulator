from contextlib import closing
import hashlib
import json
from pathlib import Path

import pytest

from loveca.db.bootstrap import connect_database
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import CardInstance
from loveca.simulation.online import match_state_hash
from loveca.webapp import _match_state_payload
from test_mirakura_front_position_boundary import _swap_roles
from test_nijigasaki_inspection import _play, _state as _base_state
from test_printemps_ready_history_boundary import _repo, _replay, _resolve

CODE = "PL!S-bp7-001"
EFFECT = CODE + ":1"
PROBE = "UNREGISTERED-CHIKA-COST10:1"
HASH = "932460c1650e7cf0f88ea1ef59805b4161e7a2d5993477d10c231b7fba92edaa"


def _actual(owner, *, high_cost=True, waiting=True):
    state = _base_state(CODE)
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        card = _load_definition(db, "PL!S-bp6-011", None, {}, {})
        candidate = _load_definition(db, "PL!S-bp6-002", None, {}, {})
    card.effect_ids = []
    candidate.effect_ids = []
    state.cards["cost"].card = card if high_cost else state.cards["source-live"].card.model_copy(update={"cost": 9, "effect_ids": []}, deep=True)
    if waiting:
        state.cards["waiting-high"] = CardInstance(instance_id="waiting-high", owner_id="player_1", card=candidate, face_up=True)
        state.players["player_1"].waiting_room.append("waiting-high")
    return _swap_roles(state) if owner == "player_2" else state


def _probe(owner, **kwargs):
    state = _actual(owner, **kwargs)
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id=PROBE, card_code="UNREGISTERED-CHIKA-COST10", execution_mode="prompt_then_resolve",
               simulation_support="test_validated_executable", review_status="test_validated",
               cost=[{"action_type": "discard_from_hand"}],
               cost_choice={"choice_type": "card_from_zone", "zone": "hand", "target_player": "self", "minimum": 1, "maximum": 1},
               choice={"choice_type": "card_from_zone", "zone": "waiting_room", "target_player": "self",
                       "card_type": "member", "minimum_cost": 10, "minimum": 1, "maximum": 1},
               actions=[{"action_type": "return_from_waiting_room"}], duration=None)
    state.effect_definitions = {PROBE: EffectDefinition.model_validate(raw)}
    state.cards["source-live"].card.card_code = "UNREGISTERED-CHIKA-COST10"
    state.cards["source-live"].card.effect_ids = [PROBE]
    return state


def _play_for(state, owner):
    action = _play(state)
    action.player_id = owner
    action.payload["energy_instance_ids"] = state.players[owner].energy_area
    return action


def test_real_identity_and_manual_boundary():
    state = _actual("player_1")
    card = state.cards["source-live"].card
    assert (card.name_ja, card.cost, card.blade, card.text_revision_id) == ("高海千歌", 9, 3, 846)
    assert hashlib.sha256(card.raw_effect_text_ja.encode()).hexdigest() == card.raw_text_hash == HASH
    effect = state.effect_definitions[EFFECT]
    assert effect.execution_mode == effect.simulation_support == "manual_resolution"
    assert effect.is_optional and not effect.cost and effect.choice is None
    assert state.cards["cost"].card.cost == 11 and state.cards["waiting-high"].card.cost == 17


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_actual_manual_acceptance_rejected_and_decline_is_atomic_sql(tmp_path, owner):
    state = _actual(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _resolve(current, EFFECT, accepted=True, selected_card_instance_ids=["cost"]))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    prior = current.players[owner].model_dump(mode="json")
    result = repo.apply(state.match_id, _resolve(current, EFFECT, accepted=False))
    assert result.state.players[owner].model_dump(mode="json") == prior
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("selected", ["cost", "waiting-high"])
def test_probe_paid_card_is_a_post_cost_candidate_sql(tmp_path, owner, selected):
    state = _probe(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    paid = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=["cost"]))
    assert paid.state.pending_effects[0].resolution_stage == "after_cost"
    option = next(a for a in paid.legal_actions if a.action_type == "resolve_effect").options["invocations"][0]
    assert set(option["candidate_card_instance_ids"]) == {"cost", "waiting-high"}
    result = repo.apply(state.match_id, _resolve(paid.state, PROBE, selected_card_instance_ids=[selected]))
    assert selected in result.state.players[owner].hand
    assert selected not in result.state.players[owner].waiting_room
    assert not result.state.players[owner].manual_modifiers
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_probe_no_qualifying_post_cost_target_does_not_invent_card_sql(tmp_path, owner):
    state = _probe(owner, high_cost=False, waiting=False)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    paid = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=["cost"]))
    option = next(a for a in paid.legal_actions if a.action_type == "resolve_effect").options["invocations"][0]
    assert option["candidate_card_instance_ids"] == []
    result = repo.apply(state.match_id, _resolve(paid.state, PROBE, selected_card_instance_ids=[]))
    assert "cost" in result.state.players[owner].waiting_room
    assert not result.state.pending_effects
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("target", ["unknown", "opponent-secret"])
def test_probe_invalid_post_cost_target_is_atomic_sql(tmp_path, owner, target):
    state = _probe(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    current = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=["cost"])).state
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _resolve(current, PROBE, selected_card_instance_ids=[target]))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_probe_ai_first_step_and_hidden_opponent_invariance(owner, policy):
    state = _probe(owner)
    current = apply_action(state, _play_for(state, owner)).state
    before = match_state_hash(current)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    decision = controller.choose_action(current, generate_legal_actions(current), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
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
    first = apply_action(current, decision.action).state
    if policy == "simple_ai_v0":
        assert first.pending_effects[0].resolution_stage == "after_cost"
        second = controller.choose_action(first, generate_legal_actions(first), controlled_player_ids={owner})
        assert isinstance(second, SimpleAIDecision)
        assert second.action.payload["selected_card_instance_ids"] == ["waiting-high"]
        result = apply_action(first, second.action).state
        assert "waiting-high" in result.players[owner].hand and not result.pending_effects
    else:
        assert decision.action.payload.get("accepted") is False
        assert not first.pending_effects and "cost" in first.players[owner].hand


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_recent_payment_and_recovery_events_keep_opponent_hand_private(owner):
    state = _probe(owner)
    played = apply_action(state, _play_for(state, owner))
    paid = apply_action(played.state, _resolve(played.state, PROBE, accepted=True, selected_card_instance_ids=["cost"]))
    result = apply_action(paid.state, _resolve(paid.state, PROBE, selected_card_instance_ids=["cost"]))
    current, events = result.state, played.events + paid.events + result.events
    opponent = "player_2" if owner == "player_1" else "player_1"
    for viewer in ("player_1", "player_2"):
        payload = _match_state_payload(current, events=events, legal_actions=generate_legal_actions(current), player_id=viewer)
        for player in current.players.values():
            assert all(i not in payload["state"]["cards"] for i in player.main_deck)
            if player.player_id != viewer:
                assert all(i not in payload["state"]["cards"] for i in player.hand)
    payload = _match_state_payload(current, events=events, legal_actions=generate_legal_actions(current), player_id=opponent)
    assert "cost" not in payload["state"]["cards"]
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    for builder in (build_api_play_context, build_agent_context):
        serialized = json.dumps(builder(current, generate_legal_actions(current)))
        assert all(i not in serialized for i in current.players[opponent].hand + current.players[opponent].main_deck)
