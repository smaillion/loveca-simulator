import json
import pytest

from loveca.simulation.effects import load_effect_registry
from loveca.simulation.engine import apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest
from loveca.simulation.online import match_state_hash
from loveca.simulation.ready_history import current_qualified_effect_readied_members
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.webapp import _match_state_payload
from test_honoka_departed_scope_audit import _actual_state, EFFECT as OLD
from test_printemps_producer_coverage import _play_for, EFFECT as NEW
from test_printemps_ready_history_boundary import _manual, _repo, _replay


def _state(owner, control=False):
    state = _actual_state(owner, control=control)
    state.member_ready_coverage_policy = "qualified_source_v1"
    state.effect_definitions[NEW] = next(e for e in load_effect_registry().effects if e.effect_id == NEW)
    target = state.cards["wrong-target"].model_copy(deep=True)
    target.instance_id = "printemps-target"
    target.card.unit_keys = ["printemps"]
    state.cards[target.instance_id] = target
    state.players[owner].member_area["center"] = target.instance_id
    return state


def _play(state):
    action = _play_for(state)
    action.payload.update(slot="left", use_baton_touch=True, energy_instance_ids=[])
    return action


def _resolve(state, effect_id, accepted=True):
    inv = next(i for i in state.pending_effects if i.effect_id == effect_id)
    payload = {"invocation_id": inv.invocation_id}
    if effect_id == OLD:
        payload["accepted"] = accepted
        if accepted:
            payload["selected_card_instance_ids"] = ["wrong-target"]
    else:
        payload["selected_card_instance_ids"] = ["printemps-target"]
    return ActionRequest(action_type="resolve_effect", player_id=inv.player_id,
                         expected_revision=state.revision, payload=payload)


def _query(state, owner):
    return current_qualified_effect_readied_members(state, owner, source_owner_id=owner,
        effect_player_id=owner, unit_key="printemps", work_key="love_live")


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("order", [(OLD, NEW), (NEW, OLD)])
@pytest.mark.parametrize("accept_old", [True, False])
def test_real_baton_formal_old_new_ready_and_qualified_unknown_sql(tmp_path, owner, order, accept_old):
    state = _state(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play(state)).state
    assert {i.effect_id for i in current.pending_effects} >= {OLD, NEW}
    for effect_id in order:
        current = repo.apply(state.match_id, _resolve(current, effect_id, accept_old)).state
    assert current.cards["printemps-target"].orientation == "active"
    assert current.cards["wrong-target"].orientation == ("active" if accept_old else "wait")
    assert [e.source.effect_id for e in current.member_ready_history.events] == [NEW]
    assert _query(current, owner) == (None if accept_old else ["printemps-target"])
    assert len(current.member_ready_qualified_coverage.unknown_changes) == int(accept_old)
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("movement", ["hand", "main_deck", "return"])
def test_formal_departed_source_hidden_or_return_keeps_unknown_sql(tmp_path, owner, movement):
    state = _state(owner, control=True)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play(state)).state
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "good-target",
                "to_zone": "hand" if movement == "return" else movement}]
    if movement == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"})
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "good-target", "to_zone": "member_left"})
    current = repo.apply(state.match_id, _manual(current, "CONTROL", changes)).state
    current = repo.apply(state.match_id, _resolve(current, NEW)).state
    current = repo.apply(state.match_id, _resolve(current, OLD)).state
    assert _query(current, owner) is None
    assert current.member_ready_qualified_coverage.unknown_changes[0].source is None
    assert [event.source.effect_id for event in current.member_ready_history.events] == [NEW]
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("movement", ["hand", "return"])
@pytest.mark.parametrize("accept_old", [True, False])
def test_formal_recorded_target_departure_does_not_clear_unknown_sql(tmp_path, owner, movement, accept_old):
    state = _state(owner, control=True)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play(state)).state
    current = repo.apply(state.match_id, _resolve(current, NEW)).state
    current = repo.apply(state.match_id, _resolve(current, OLD, accept_old)).state
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "printemps-target", "to_zone": "hand"}]
    if movement == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "printemps-target", "to_zone": "member_center"})
    current = repo.apply(state.match_id, _manual(current, "CONTROL", changes)).state
    assert _query(current, owner) == (None if accept_old else [])
    assert current.member_ready_history.events[0].target_instance_id == "printemps-target"
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_mixed_formal_pending_actions_and_player_privacy(owner, policy):
    initial = _state(owner, control=True)
    entered = apply_action(initial, _play(initial))
    moved = apply_action(entered.state, _manual(entered.state, "CONTROL", [
        {"adjustment_type": "move_card", "target_card_instance_id": "good-target", "to_zone": "main_deck"}]))
    state = moved.state
    before = match_state_hash(state)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    assert match_state_hash(state) == before
    apply_action(state, decision.action)
    changed = state.model_copy(deep=True)
    for player in changed.players.values():
        for key in list(player.main_deck + (player.hand if player.player_id != owner else [])):
            item = changed.cards.pop(key)
            replacement = "HIDDEN-" + key
            item.instance_id = replacement
            item.card.name_ja = item.card.card_code = "HIDDEN"
            item.card.unit_keys, item.card.work_keys, item.card.blade = ["bibi"], ["hasunosora"], 99
            changed.cards[replacement] = item
            player.main_deck = [replacement if i == key else i for i in player.main_deck]
            player.hand = [replacement if i == key else i for i in player.hand]
            for inv in changed.pending_effects:
                if inv.source_card_instance_id == key:
                    inv.source_card_instance_id = replacement
    changed_before = match_state_hash(changed)
    other = controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner})
    assert isinstance(other, SimpleAIDecision) and other.action == decision.action
    assert match_state_hash(state) == before and match_state_hash(changed) == changed_before
    apply_action(changed, other.action)
    for viewer in ("player_1", "player_2"):
        payload = _match_state_payload(state, events=[*entered.events, *moved.events], legal_actions=generate_legal_actions(state), player_id=viewer)
        serialized = str(payload)
        assert "ready_source_lki_v1" not in serialized
        assert "member_ready_qualified_coverage" not in serialized
        for player in state.players.values():
            assert not any(key in payload["state"]["cards"] for key in player.main_deck)
            if player.player_id != viewer:
                assert not any(key in payload["state"]["cards"] for key in player.hand)
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    for builder in (build_api_play_context, build_agent_context):
        context = json.dumps(builder(state, generate_legal_actions(state)))
        assert "ready_source_lki_v1" not in context and "member_ready_qualified_coverage" not in context
