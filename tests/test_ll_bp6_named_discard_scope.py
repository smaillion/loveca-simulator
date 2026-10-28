from contextlib import closing
import hashlib
from pathlib import Path

import pytest

from loveca.db.bootstrap import connect_database
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effects import load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import CardDefinition, CardInstance
from loveca.simulation.online import match_state_hash
from loveca.webapp import _match_state_payload
from test_printemps_ready_history_boundary import _advance, _manual, _repo, _replay, _resolve, _state

CODE = "LL-bp6-001"
EFFECT = CODE + ":2"
HASH = "cf58746e81720b3db7a0dc378b36dd4b8fb60e88c63ab1a9d97ef0ebd5691331"


def _actual(owner, *, hand=False, duplicate=False):
    state = _state(owner=owner)
    effects = {e.effect_id: e for e in load_effect_registry().effects if e.card_code == CODE}
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        card = _load_definition(db, CODE, None, effects, {})
    for instance in state.cards.values():
        instance.card.effect_ids = []
    state.cards["source-live"].card = card
    state.effect_definitions = effects
    if duplicate:
        state.cards["target"].card = card.model_copy(deep=True)
    if hand:
        for index, name in enumerate(("南 ことり", "黒澤ダイヤ", "徒町小鈴", "南 ことり")):
            key = f"audit-hand-{index}"
            state.cards[key] = CardInstance(instance_id=key, owner_id=owner,
                card=CardDefinition(card_code=key, card_id=key, name_ja=name, card_type="member",
                                    basic_hearts={"heart01": 2}))
            state.players[owner].hand.append(key)
    return state


def test_actual_card_full_identity_and_two_manual_segments():
    state = _actual("player_1")
    card = state.cards["source-live"].card
    assert (card.name_ja, card.cost, card.blade, card.text_revision_id) == ("南 ことり&黒澤ダイヤ&徒町小鈴", 20, 7, 59)
    assert card.raw_text_hash == hashlib.sha256(card.raw_effect_text_ja.encode()).hexdigest() == HASH
    assert set(card.effect_ids) == {CODE + ":1", EFFECT}
    for effect in state.effect_definitions.values():
        assert effect.raw_text_hash == HASH and effect.text_revision_id == 59
    first = state.effect_definitions[CODE + ":1"]
    assert first.execution_mode == "prompt_then_resolve" and first.simulation_support == "test_validated_executable"
    assert [op.action_type for op in first.actions] == ["inspect_top_cards", "select_to_hand_from_inspected", "move_remaining_cards"]
    effect = state.effect_definitions[EFFECT]
    assert effect.simulation_support == effect.execution_mode == "manual_resolution"
    assert effect.is_optional and not effect.cost and effect.cost_choice is None
    assert [op.action_type for op in effect.actions] == ["manual_resolution"]


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("hand", [False, True])
def test_actual_optional_manual_decline_and_no_automatic_cost_sql(tmp_path, owner, hand):
    state = _actual(owner, hand=hand)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    assert [i.effect_id for i in current.pending_effects] == [EFFECT]
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _resolve(current, EFFECT, accepted=True, selected_card_instance_ids=[]))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    result = repo.apply(state.match_id, _resolve(current, EFFECT, accepted=False)).state
    assert result.players[owner].hand == current.players[owner].hand
    assert result.players[owner].waiting_room == current.players[owner].waiting_room
    assert not result.pending_effects
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_two_actual_sources_queue_separately_sql(tmp_path, owner):
    state = _actual(owner, hand=True, duplicate=True)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    invocations = [i for i in current.pending_effects if i.effect_id == EFFECT]
    assert len(invocations) == 2 and len({i.invocation_id for i in invocations}) == 2
    assert {i.source_card_instance_id for i in invocations} == {"source-live", "target"}
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("movement", ["hand", "main_deck", "return"])
def test_departed_source_keeps_manual_invocation_sql(tmp_path, owner, movement):
    state = _actual(owner, hand=True)
    control = _state(owner=owner, control=True).effect_definitions["CONTROL"]
    state.effect_definitions["CONTROL"] = control
    state.cards["live-1"].card.effect_ids.append("CONTROL")
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live",
                "to_zone": "hand" if movement == "return" else movement}]
    if movement == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_left"})
    current = repo.apply(state.match_id, _manual(current, "CONTROL", changes)).state
    invocation = next(i for i in current.pending_effects if i.effect_id == EFFECT)
    assert invocation.source_card_instance_id == "source-live" and invocation.player_id == owner
    result = repo.apply(state.match_id, _resolve(current, EFFECT, accepted=False)).state
    assert not result.pending_effects
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_decline_optional_manual_and_hide_opponent_hand(owner, policy):
    state = _actual(owner, hand=True)
    current = apply_action(state, _advance(state)).state
    before = match_state_hash(current)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    decision = controller.choose_action(current, generate_legal_actions(current), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    assert decision.action.payload.get("accepted") is False
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
    assert match_state_hash(changed) == changed_before
    for viewer in ("player_1", "player_2"):
        payload = _match_state_payload(current, events=[], legal_actions=generate_legal_actions(current), player_id=viewer)
        for player in current.players.values():
            assert all(i not in payload["state"]["cards"] for i in player.main_deck)
            if player.player_id != viewer:
                assert all(i not in payload["state"]["cards"] for i in player.hand)
    result = apply_action(current, decision.action).state
    assert result.players[owner].hand == current.players[owner].hand
    assert match_state_hash(current) == before
