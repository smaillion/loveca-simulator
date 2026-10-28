from contextlib import closing
import hashlib
import json
from pathlib import Path

import pytest

from loveca.db.bootstrap import connect_database
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effects import load_effect_registry
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.engine import IllegalActionError, generate_legal_actions
from loveca.simulation.models import CardDefinition, CardInstance
from loveca.simulation.online import match_state_hash
from loveca.webapp import _match_state_payload
from test_printemps_ready_history_boundary import _advance, _repo, _replay, _resolve, _state

CODE = "LL-bp2-001"
EFFECT = CODE + ":3"
HASH = "dfe7ad5c2413211c958b11e6f7ef92a11245426e036193a2acc8cb9a48d236ba"


def _actual(owner):
    state = _state(owner=owner)
    effects = {e.effect_id: e for e in load_effect_registry().effects if e.card_code == CODE}
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        card = _load_definition(db, CODE, None, effects, {})
    for instance in state.cards.values():
        instance.card.effect_ids = []
    state.cards["source-live"].card = card.model_copy(deep=True)
    state.cards["source-live"].card.effect_ids = [EFFECT]
    state.effect_definitions = {EFFECT: effects[EFFECT]}
    state.cards["composite-hand"] = CardInstance(instance_id="composite-hand", owner_id=owner, card=card.model_copy(deep=True))
    state.cards["single-hand"] = CardInstance(instance_id="single-hand", owner_id=owner,
        card=CardDefinition(card_code="TEST-SINGLE", card_id="TEST-SINGLE", name_ja="渡辺 曜", card_type="member"))
    state.players[owner].hand.extend(["composite-hand", "single-hand"])
    return state


def test_formal_identity_includes_explicit_composite_hand_cost():
    state = _actual("player_1")
    card = state.cards["source-live"].card
    effect = state.effect_definitions[EFFECT]
    assert card.text_revision_id == 592
    assert card.raw_text_hash == hashlib.sha256(card.raw_effect_text_ja.encode()).hexdigest() == HASH
    assert "手札のこのカードもこの効果で控え室に置ける" in effect.label_ja
    assert effect.simulation_support == "test_validated_executable"


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_formal_existing_composite_cost_rejected_atomically_sql(tmp_path, owner):
    state = _actual(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    assert any(i.effect_id == EFFECT for i in current.pending_effects)
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _resolve(current, EFFECT, accepted=True, selected_card_instance_ids=["composite-hand"]))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_formal_single_name_cost_succeeds_sql(tmp_path, owner):
    state = _actual(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _resolve(current, EFFECT, accepted=True, selected_card_instance_ids=["single-hand"]))
    assert "single-hand" in result.state.players[owner].waiting_room
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_formal_four_matching_single_names_rejected_atomically_sql(tmp_path, owner):
    state = _actual(owner)
    for index in range(3):
        key = f"single-extra-{index}"
        state.cards[key] = state.cards["single-hand"].model_copy(deep=True)
        state.cards[key].instance_id = key
        state.players[owner].hand.append(key)
    assert state.effect_definitions[EFFECT].cost_choice.maximum == 3
    assert "好きな枚数" in state.effect_definitions[EFFECT].label_ja
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _resolve(current, EFFECT, accepted=True,
            selected_card_instance_ids=["single-hand", "single-extra-0", "single-extra-1", "single-extra-2"]))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("selection", [["single-hand", "single-hand"], ["unknown-card"]])
def test_formal_duplicate_or_unknown_cost_rejected_atomically_sql(tmp_path, owner, selection):
    state = _actual(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _resolve(current, EFFECT, accepted=True, selected_card_instance_ids=selection))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_formal_decline_preserves_hand_sql(tmp_path, owner):
    state = _actual(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _resolve(current, EFFECT, accepted=False)).state
    assert result.players[owner].hand == current.players[owner].hand
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_formal_ai_hidden_hand_and_player_projection(owner, policy):
    from loveca.simulation.engine import apply_action
    state = _actual(owner)
    current = apply_action(state, _advance(state)).state
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
    assert match_state_hash(current) == before and match_state_hash(changed) == changed_before
    view = _match_state_payload(current, events=[], legal_actions=generate_legal_actions(current), player_id=opponent)
    assert all(i not in view["state"]["cards"] for i in current.players[owner].hand)
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    for builder in (build_api_play_context, build_agent_context):
        serialized = json.dumps(builder(current, generate_legal_actions(current)))
        assert all(key not in serialized for key in current.players[opponent].main_deck + current.players[opponent].hand)
    apply_action(current, decision.action)
