import hashlib
from contextlib import closing
from pathlib import Path

import pytest

from loveca.db.bootstrap import connect_database
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effects import load_effect_registry
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.models import ActionRequest, CardDefinition, CardInstance
from loveca.simulation.online import match_state_hash
from test_printemps_producer_coverage import _play_for, _state
from test_printemps_ready_history_boundary import _manual, _repo, _replay
from test_ready_departed_source_probe import _state as _probe_state, PROBE
from test_bottom_one_aqours_requirement import _exclusive

EFFECT = "PL!-PR-001:1"
TEXT = "【自動】このメンバーがステージから控え室に置かれたとき、メンバー1人をアクティブにしてもよい。"
HASH = "15fa6ca29ca4e4bfab665dadebfe6bd076b833f84d99527392df394c43e80cfc"


def _actual_state(owner, control=False):
    state = _state(owner=owner, control=control)
    definitions = {effect.effect_id: effect for effect in load_effect_registry().effects}
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        card = _load_definition(db, "PL!-PR-001", None, definitions, {})
    assert card.raw_effect_text_ja == TEXT and card.text_revision_id == 712
    assert card.raw_text_hash == hashlib.sha256(TEXT.encode()).hexdigest() == HASH
    state.cards["good-target"].card = card
    state.effect_definitions[EFFECT] = definitions[EFFECT]
    opponent = "player_2" if owner == "player_1" else "player_1"
    for orientation, slot in [("wait", "center"), ("active", "right")]:
        key = "opponent-" + orientation
        state.cards[key] = CardInstance(instance_id=key, owner_id=opponent, orientation=orientation,
            card=CardDefinition(card_code="AUDIT-" + key, card_id="AUDIT-" + key, name_ja=key,
                card_type="member", cost=4, blade=1))
        state.players[opponent].member_area[slot] = key
    state.cards["wrong-target"].orientation = "wait"
    _exclusive(state)
    return state


@pytest.mark.parametrize("field,value", [("target_player", "opponent"), ("orientation", None)])
def test_departed_probe_does_not_certify_broader_scope(field, value):
    raw = _probe_state().effect_definitions[PROBE].model_dump(mode="json")
    raw["choice"][field] = value
    with pytest.raises(ValueError, match="optional own-Member choice"):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("source_orientation", ["wait", "active"])
@pytest.mark.parametrize("selection", ["own_wait", "own_active", "opponent_wait", "opponent_active", "decline"])
def test_actual_departure_legacy_scope_and_replay(tmp_path, owner, source_orientation, selection):
    state = _actual_state(owner)
    state.cards["good-target"].orientation = source_orientation
    if selection == "own_active":
        state.cards["wrong-target"].orientation = "active"
    play = _play_for(state)
    play.payload.update(slot="left", use_baton_touch=True, energy_instance_ids=[])
    repo = _repo(state, tmp_path)
    departed = repo.apply(state.match_id, play).state
    _exclusive(departed)
    invocation = next(i for i in departed.pending_effects if i.effect_id == EFFECT)
    assert "good-target" in departed.players[owner].waiting_room
    legal = generate_legal_actions(departed)
    options = next(a.options for a in legal if a.action_type == "resolve_effect")
    shown = next(i for i in options["invocations"] if i["effect_id"] == EFFECT)
    assert ("wrong-target" in shown["candidate_card_instance_ids"]) is (selection != "own_active")
    assert "opponent-wait" not in shown["candidate_card_instance_ids"]
    assert "opponent-active" not in shown["candidate_card_instance_ids"]
    payload = {"invocation_id": invocation.invocation_id, "accepted": selection != "decline"}
    if selection != "decline":
        payload["selected_card_instance_ids"] = ["wrong-target" if selection.startswith("own_") else selection.replace("_", "-")]
    request = ActionRequest(action_type="resolve_effect", player_id=owner, expected_revision=departed.revision, payload=payload)
    before = match_state_hash(departed)
    if selection.startswith("opponent") or selection == "own_active":
        with pytest.raises(IllegalActionError):
            repo.apply(state.match_id, request)
        assert match_state_hash(repo.get_state(state.match_id)) == before
        _replay(repo, departed)
    else:
        result = repo.apply(state.match_id, request).state
        assert result.cards["wrong-target"].orientation == ("active" if selection == "own_wait" else "wait")
        assert result.member_ready_history is None
        _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("movement", ["hand", "main_deck", "return"])
def test_actual_source_departure_and_later_hidden_move_sql(tmp_path, owner, movement):
    state = _actual_state(owner, control=True)
    play = _play_for(state)
    play.payload.update(slot="left", use_baton_touch=True, energy_instance_ids=[])
    repo = _repo(state, tmp_path)
    departed = repo.apply(state.match_id, play).state
    invocation = next(i for i in departed.pending_effects if i.effect_id == EFFECT)
    assert "ready_source_lki_v1" not in invocation.trigger_data
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "good-target",
                "to_zone": "hand" if movement == "return" else movement}]
    if movement == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "good-target", "to_zone": "member_center"})
    moved = repo.apply(state.match_id, _manual(departed, "CONTROL", changes)).state
    invocation = next(i for i in moved.pending_effects if i.effect_id == EFFECT)
    request = ActionRequest(action_type="resolve_effect", player_id=owner, expected_revision=moved.revision,
        payload={"invocation_id": invocation.invocation_id, "accepted": True, "selected_card_instance_ids": ["wrong-target"]})
    result = repo.apply(state.match_id, request).state
    assert result.cards["wrong-target"].orientation == "active" and result.member_ready_history is None
    _exclusive(result)
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_legacy_departed_selection_hidden_invariant(owner, policy):
    state = _actual_state(owner)
    play = _play_for(state)
    play.payload.update(slot="left", use_baton_touch=True, energy_instance_ids=[])
    state = apply_action(state, play).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    changed = state.model_copy(deep=True)
    for player in changed.players.values():
        for key in list(player.main_deck + (player.hand if player.player_id != owner else [])):
            item = changed.cards.pop(key)
            name = "HIDDEN-" + key
            item.instance_id = name
            item.card.name_ja = item.card.card_code = "HIDDEN"
            changed.cards[name] = item
            player.main_deck = [name if i == key else i for i in player.main_deck]
            player.hand = [name if i == key else i for i in player.hand]
    changed_before = match_state_hash(changed)
    changed_decision = controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner})
    assert isinstance(changed_decision, SimpleAIDecision) and changed_decision.action == decision.action
    assert match_state_hash(state) == before and match_state_hash(changed) == changed_before
    apply_action(state, decision.action)
    apply_action(changed, changed_decision.action)
