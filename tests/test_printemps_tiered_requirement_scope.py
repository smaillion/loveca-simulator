from contextlib import closing
import hashlib
from pathlib import Path

import pytest

from loveca.db.bootstrap import connect_database
from loveca.simulation.ai import SimpleAIBlocker, SimpleAIController, SimpleAIPolicy
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effects import load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.online import match_state_hash
from loveca.webapp import _match_state_payload
from test_printemps_four_producer_coverage_audit import _qualified
from test_printemps_ready_history_boundary import READY, _advance, _repo, _replay, _resolve
from test_waowao_ready_score_audit import _fixture

CODE = "PL!-pb2-040"
EFFECT = CODE + ":1"
HASH = "b08dffc1f37cdba354b9aeb096fe7b42b54e63571ca48601135834fbd39143ba"


def _actual(owner, waits):
    state = _fixture(owner, waits)
    effect = next(e for e in load_effect_registry().effects if e.effect_id == EFFECT)
    state.effect_definitions[EFFECT] = effect
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        card = _load_definition(db, CODE, None, state.effect_definitions, {})
    state.cards["other-live"].card = card
    state.cards["source-live"].card.effect_ids = []
    state.member_ready_coverage_policy = "qualified_source_v1"
    return state


def test_identity_and_manual_boundary():
    state = _actual("player_1", 0)
    card = state.cards["other-live"].card
    effect = state.effect_definitions[EFFECT]
    assert (card.name_ja, card.score, card.text_revision_id, card.raw_text_hash) == ("Love marginal", 7, 1019, HASH)
    assert hashlib.sha256(card.raw_effect_text_ja.encode()).hexdigest() == HASH
    assert card.unit_keys == ["printemps"] and card.work_keys == ["love_live"]
    assert effect.raw_text_hash == HASH and effect.text_revision_id == 1019
    assert effect.execution_mode == effect.simulation_support == "manual_resolution"
    assert [a.action_type for a in effect.actions] == ["manual_resolution"]


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("waits", [0, 1, 2, 3])
def test_real_live_trigger_and_qualified_readies_remain_manual_sql(tmp_path, owner, waits):
    state = _actual(owner, waits)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    assert {i.effect_id for i in current.pending_effects} == {READY, EFFECT}
    current = repo.apply(state.match_id, _resolve(current, READY)).state
    assert len(_qualified(current, owner)) == waits
    assert [i.effect_id for i in current.pending_effects] == [EFFECT]
    assert not any(m.target_card_instance_id == "other-live" for m in current.players[owner].manual_modifiers)
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_manual_ai_and_private_views(owner, policy):
    state = _actual(owner, 0)
    current = apply_action(state, _advance(state)).state
    current = apply_action(current, _resolve(current, READY)).state
    before = match_state_hash(current)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    decision = controller.choose_action(current, generate_legal_actions(current), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIBlocker) and decision.reason == "no_safe_ai_action"
    changed = current.model_copy(deep=True)
    for player in changed.players.values():
        for key in list(player.main_deck + (player.hand if player.player_id != owner else [])):
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
    assert match_state_hash(current) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_structured_manual_bypass_is_atomic(owner):
    state = _actual(owner, 0)
    current = apply_action(state, _advance(state)).state
    current = apply_action(current, _resolve(current, READY)).state
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        apply_action(current, _resolve(current, EFFECT, accepted=True))
    assert match_state_hash(current) == before
