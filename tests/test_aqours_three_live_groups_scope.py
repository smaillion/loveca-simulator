from contextlib import closing
import hashlib
import json
from pathlib import Path

import pytest

from loveca.db.bootstrap import connect_database
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effects import load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import CardInstance
from loveca.simulation.online import match_state_hash
from loveca.webapp import _match_state_payload
from test_printemps_ready_history_boundary import _advance, _repo, _replay, _resolve, _state

CODE = "PL!S-cl1-010"
EFFECT = CODE + ":1"
HASH = "1f1cbfef01ebacf84a625073c550b950ba14f914639c5371bd768c8a039bdfe6"


def _actual(owner, duplicate=False):
    state = _state(owner=owner)
    effects = {e.effect_id: e for e in load_effect_registry().effects if e.card_code == CODE}
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        card = _load_definition(db, CODE, None, effects, {})
        candidates = [_load_definition(db, code, None, {}, {})
                      for code in ("PL!S-pb1-021", "PL!S-bp5-020")]
    state.effect_definitions = effects
    state.cards["live-1"].card = card
    player = state.players[owner]
    for index, item in enumerate(candidates):
        key = f"public-overlap-{index}"
        state.cards[key] = CardInstance(instance_id=key, owner_id=owner, card=item, face_up=True)
        player.waiting_room.append(key)
    if duplicate:
        state.cards["live-copy"] = CardInstance(instance_id="live-copy", owner_id=owner,
                                                 card=card.model_copy(deep=True), face_up=True)
        player.live_area.append("live-copy")
    return state


def test_exact_identity_manual_and_real_overlap_attributes():
    state = _actual("player_1")
    card = state.cards["live-1"].card
    assert (card.text_revision_id, card.raw_text_hash) == (969, HASH)
    assert hashlib.sha256(card.raw_effect_text_ja.encode()).hexdigest() == HASH
    effect = state.effect_definitions[EFFECT]
    assert effect.simulation_support == effect.execution_mode == "manual_resolution"
    assert effect.is_optional and not effect.cost and effect.choice is None
    first, second = [state.cards[f"public-overlap-{i}"].card for i in range(2)]
    assert all(c.card_type == "live" and "love_live_sunshine" in c.work_keys for c in (first, second))
    assert first.required_hearts["heart0"] == second.required_hearts["heart0"] == 2
    assert any(h.effect_type == "score" for h in first.special_blade_hearts)
    assert any(h.effect_type == "all_color" for h in second.special_blade_hearts)


def test_current_catalog_attribute_inventory_is_not_a_qualification_ruling():
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        codes = [row["card_code"] for row in db.execute("SELECT card_code FROM gameplay_cards WHERE card_type='live'")]
        cards = [_load_definition(db, code, None, {}, {}) for code in codes]
    cards = [card for card in cards if "love_live_sunshine" in card.work_keys]
    score = [card for card in cards if any(h.effect_type == "score" for h in card.special_blade_hearts)]
    all_color = [card for card in cards if any(h.effect_type == "all_color" for h in card.special_blade_hearts)]
    zero_exact_two = [card for card in cards if card.required_hearts.get("heart0") == 2]
    print("catalog", len(cards), "score", len(score), "all_color", len(all_color),
          "heart0_exact_2", len(zero_exact_two))
    assert any(card.card_code == "PL!S-pb1-021" for card in score)
    assert any(card.card_code == "PL!S-bp5-020" for card in all_color)
    assert {"PL!S-pb1-021", "PL!S-bp5-020"} <= {card.card_code for card in zero_exact_two}


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("duplicate", [False, True])
def test_real_live_manual_decline_and_atomic_bypass_sql(tmp_path, owner, duplicate):
    state = _actual(owner, duplicate)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    invocations = [i for i in current.pending_effects if i.effect_id == EFFECT]
    assert len(invocations) == (2 if duplicate else 1)
    assert len({i.source_card_instance_id for i in invocations}) == len(invocations)
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _resolve(current, EFFECT, accepted=True,
                   selected_card_instance_ids=["public-overlap-0"]))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    waiting, deck = list(current.players[owner].waiting_room), list(current.players[owner].main_deck)
    while any(i.effect_id == EFFECT for i in current.pending_effects):
        current = repo.apply(state.match_id, _resolve(current, EFFECT, accepted=False)).state
    assert current.players[owner].waiting_room == waiting
    assert current.players[owner].main_deck == deck
    assert not current.players[owner].manual_modifiers
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_decline_and_hidden_opponent_identity_is_irrelevant(owner, policy):
    state = _actual(owner)
    current = apply_action(state, _advance(state)).state
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
    assert resolved.players[owner].waiting_room == current.players[owner].waiting_room


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_recent_events_player_and_constructed_provider_privacy(owner):
    state = _actual(owner)
    triggered = apply_action(state, _advance(state))
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
