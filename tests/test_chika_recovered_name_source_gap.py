from contextlib import closing
import json
from pathlib import Path

import pytest

from loveca.db.bootstrap import connect_database
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import apply_action, generate_legal_actions
from loveca.simulation.online import match_state_hash
from loveca.webapp import _match_state_payload
from test_chika_cost10_post_discard_scope import PROBE, _play_for, _probe as _base_probe
from test_printemps_ready_history_boundary import _manual, _repo, _replay, _resolve


def _probe(owner, cost_named=True, recovered_named=True, control=False, selected_bonus=False):
    state = _base_probe(owner)
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        named = _load_definition(db, "PL!S-bp6-011", None, {}, {})
        unrelated = _load_definition(db, "PL!-bp6-005", None, {}, {})
    named.effect_ids = []
    unrelated.effect_ids = []
    state.cards["cost"].card = (named if cost_named else unrelated).model_copy(deep=True)
    state.cards["waiting-high"].card = (named if recovered_named else unrelated).model_copy(deep=True)
    raw = state.effect_definitions[PROBE].model_dump(mode="json")
    raw["actions"] = [{"action_type": "return_from_waiting_room"},
        {"action_type": "gain_blade", "amount": 2, "target": "selected" if selected_bonus else None,
         "value": {"condition": {"cost_selected_card_name_ja_any": ["桜内梨子", "渡辺 曜"]}}}]
    raw["duration"] = "live"
    state.effect_definitions[PROBE] = EffectDefinition.model_validate(raw)
    if control:
        ctrl = raw.copy()
        ctrl.update(effect_id="CONTROL", cost=[], cost_choice=None, choice=None,
                    actions=[{"action_type": "manual_resolution"}], execution_mode="manual_resolution",
                    simulation_support="manual_resolution", is_optional=False)
        state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(ctrl)
        state.cards["source-live"].card.effect_ids.append("CONTROL")
    return state


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("cost_named,recovered_named", [(False, False), (False, True), (True, False), (True, True)])
def test_old_source_blade_operation_is_omitted_after_post_cost_choice_sql(tmp_path, owner, cost_named, recovered_named):
    state = _probe(owner, cost_named, recovered_named)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    paid = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=["cost"]))
    result = repo.apply(state.match_id, _resolve(paid.state, PROBE, selected_card_instance_ids=["waiting-high"]))
    modifiers = [m for m in result.state.players[owner].manual_modifiers if m.modifier_type == "blade"]
    assert not modifiers
    assert "waiting-high" in result.state.players[owner].hand
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("cost_named,recovered_named", [(False, False), (False, True), (True, False), (True, True)])
def test_old_cost_name_condition_reads_cost_not_recovered_card_sql(tmp_path, owner, cost_named, recovered_named):
    state = _probe(owner, cost_named, recovered_named, selected_bonus=True)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    paid = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=["cost"]))
    result = repo.apply(state.match_id, _resolve(paid.state, PROBE, selected_card_instance_ids=["waiting-high"]))
    modifiers = [m for m in result.state.players[owner].manual_modifiers if m.modifier_type == "blade"]
    assert len(modifiers) == int(cost_named)
    if modifiers:
        assert (modifiers[0].amount, modifiers[0].target_card_instance_id) == (2, "waiting-high")
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("return_source", [False, True])
def test_old_blade_modifier_follows_reused_source_id_after_departure_sql(tmp_path, owner, return_source):
    state = _probe(owner, control=True)
    raw = state.effect_definitions[PROBE].model_dump(mode="json")
    raw.update(cost=[], cost_choice=None, choice=None, actions=[{"action_type": "gain_blade", "amount": 2}])
    state.effect_definitions[PROBE] = EffectDefinition.model_validate(raw)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"}]
    if return_source:
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_center"})
    current = repo.apply(state.match_id, _manual(current, "CONTROL", changes)).state
    result = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True))
    modifiers = [m for m in result.state.players[owner].manual_modifiers if m.modifier_type == "blade"]
    assert len(modifiers) == 1 and modifiers[0].target_card_instance_id == "source-live"
    assert ("source-live" in result.state.players[owner].member_area.values()) == return_source
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_choice_and_opponent_hidden_identity_invariance(owner, policy):
    state = _probe(owner, cost_named=True, recovered_named=False)
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
    changed_first = apply_action(changed, decision.action).state
    assert decision.action.payload["selected_card_instance_ids"] == ["cost"]
    assert first.pending_effects and changed_first.pending_effects
    first_before, changed_first_before = match_state_hash(first), match_state_hash(changed_first)
    second = controller.choose_action(first, generate_legal_actions(first), controlled_player_ids={owner})
    assert isinstance(second, SimpleAIDecision)
    assert controller.choose_action(changed_first, generate_legal_actions(changed_first), controlled_player_ids={owner}) == second
    assert match_state_hash(first) == first_before and match_state_hash(changed_first) == changed_first_before
    assert second.action.payload["selected_card_instance_ids"] == (["waiting-high"] if policy == "simple_ai_v0" else ["cost"])
    result = apply_action(first, second.action).state
    assert not result.pending_effects and not result.players[owner].manual_modifiers


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_recent_recovery_events_do_not_authorize_hidden_card_map(owner):
    state = _probe(owner)
    played = apply_action(state, _play_for(state, owner))
    paid = apply_action(played.state, _resolve(played.state, PROBE, accepted=True, selected_card_instance_ids=["cost"]))
    result = apply_action(paid.state, _resolve(paid.state, PROBE, selected_card_instance_ids=["cost"]))
    current, events = result.state, played.events + paid.events + result.events
    opponent = "player_2" if owner == "player_1" else "player_1"
    payload = _match_state_payload(current, events=events, legal_actions=generate_legal_actions(current), player_id=opponent)
    assert "cost" not in payload["state"]["cards"]
    assert all(i not in payload["state"]["cards"] for i in current.players[owner].hand)
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    for builder in (build_api_play_context, build_agent_context):
        serialized = json.dumps(builder(current, generate_legal_actions(current)))
        assert all(i not in serialized for i in current.players[opponent].hand + current.players[opponent].main_deck)
