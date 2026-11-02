import hashlib
import json
from pathlib import Path
from contextlib import closing

import pytest

from loveca.db.bootstrap import connect_database
from loveca.simulation.ai import SimpleAIBlocker, SimpleAIController, SimpleAIPolicy
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions, _source_trigger_disabled
from loveca.simulation.models import ActionRequest, CardDefinition, CardInstance
from loveca.simulation.online import match_state_hash
from loveca.webapp import _match_state_payload
from test_printemps_ready_history_boundary import _advance, _manual, _repo, _replay, _state as _base_state

CODE = "PL!-pb2-003"
EFFECT = CODE + ":1"
HASH = "46547652e34bdce62f0fabe50830721d17c6b93d1d1df63c784af214b45ecb83"
PROBE = "UNREGISTERED-OPPONENT-DISABLE:1"


def _state(owner, *, probe=False, target=True, control=False, duplicate=False):
    state = _base_state(owner=owner)
    definitions = {e.effect_id: e for e in load_effect_registry().effects}
    effect = definitions[EFFECT]
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        state.cards["source-live"].card = _load_definition(db, CODE, None, definitions, {})
    state.effect_definitions = {EFFECT: effect}
    for key, item in state.cards.items():
        if key != "source-live": item.card.effect_ids = []
    if probe:
        raw = effect.model_dump(mode="json")
        raw.update(effect_id=PROBE, card_code="UNREGISTERED-OPPONENT-DISABLE", execution_mode="prompt_then_resolve",
            simulation_support="test_validated_executable", review_status="test_validated",
            choice={"choice_type": "member_from_stage", "zone": "stage", "target_player": "opponent",
                    "card_type": "member", "minimum": 1, "maximum": 1},
            actions=[{"action_type": "disable_source_live_success_effects", "target": "selected"}])
        state.effect_definitions = {PROBE: EffectDefinition.model_validate(raw)}
        state.cards["source-live"].card.effect_ids = [PROBE]
        if duplicate:
            raw["effect_id"] = PROBE + "-SECOND"
            state.effect_definitions[raw["effect_id"]] = EffectDefinition.model_validate(raw)
            state.cards["source-live"].card.effect_ids.append(raw["effect_id"])
    if control:
        raw = effect.model_dump(mode="json")
        raw.update(effect_id="CONTROL", frequency_limit="none", label_ja="AUDIT CONTROL")
        state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
        state.cards["live-1"].card.effect_ids.append("CONTROL")
    if target:
        other = "player_2" if owner == "player_1" else "player_1"
        state.cards["opponent-member"] = CardInstance(instance_id="opponent-member", owner_id=other,
            card=CardDefinition(card_code="AUDIT-OPPONENT", card_id="AUDIT-OPPONENT", name_ja="AUDIT",
                                card_type="member", cost=1))
        state.players[other].member_area["center"] = "opponent-member"
    return state


def _resolve(state, effect_id, target=None):
    inv = next(i for i in state.pending_effects if i.effect_id == effect_id)
    payload = {"invocation_id": inv.invocation_id}
    if target is not None: payload["selected_card_instance_ids"] = [target]
    return ActionRequest(action_type="resolve_effect", player_id=inv.player_id,
                         expected_revision=state.revision, payload=payload)


def test_actual_card_exact_identity_and_source_only_primitive_scope():
    state = _state("player_1")
    card = state.cards["source-live"].card
    assert (card.card_code, card.cost, card.blade, card.text_revision_id) == (CODE, 9, 4, 976)
    assert hashlib.sha256(card.raw_effect_text_ja.encode()).hexdigest() == card.raw_text_hash == HASH
    assert state.effect_definitions[EFFECT].simulation_support == "manual_resolution"
    producers = [(e.effect_id, a.target) for e in load_effect_registry().effects for a in e.actions
                 if a.action_type == "disable_source_live_success_effects"]
    assert producers == [("PL!S-pb1-019:1", None)]


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("target", [True, False])
def test_formal_manual_live_start_is_not_auto_resolved_sql(tmp_path, owner, target):
    state = _state(owner, target=target); repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    inv = next(i for i in current.pending_effects if i.effect_id == EFFECT)
    assert inv.player_id == owner
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _resolve(current, EFFECT, "opponent-member" if target else None))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    assert not any(m.flag == "disabled_live_success_effects" for p in current.players.values() for m in p.manual_modifiers)
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_unregistered_selected_target_is_ignored_by_source_only_operation_sql(tmp_path, owner):
    state = _state(owner, probe=True); repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _resolve(current, PROBE, "opponent-member")).state
    opponent = "player_2" if owner == "player_1" else "player_1"
    assert _source_trigger_disabled(result, owner, "source-live", "live_succeeded")
    assert not _source_trigger_disabled(result, opponent, "opponent-member", "live_succeeded")
    flags = [m for p in result.players.values() for m in p.manual_modifiers if m.flag == "disabled_live_success_effects"]
    assert len(flags) == 1 and flags[0].target_card_instance_id == "source-live"
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_unregistered_duplicate_source_operation_only_adds_flags_sql(tmp_path, owner):
    state = _state(owner, probe=True, duplicate=True); repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    current = repo.apply(state.match_id, _resolve(current, PROBE, "opponent-member")).state
    result = repo.apply(state.match_id, _resolve(current, PROBE + "-SECOND", "opponent-member")).state
    flags = [m for m in result.players[owner].manual_modifiers if m.flag == "disabled_live_success_effects"]
    assert len(flags) == 2 and all(m.target_card_instance_id == "source-live" for m in flags)
    assert not _source_trigger_disabled(result, "player_2" if owner == "player_1" else "player_1", "opponent-member", "live_succeeded")
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("returned", [False, True])
def test_current_departure_policy_clears_source_only_flag_sql(tmp_path, owner, returned):
    state = _state(owner, probe=True, control=True); repo = _repo(state, tmp_path)
    assert state.stage_departure_policy == "clear_departed_card_modifiers"
    current = repo.apply(state.match_id, _advance(state)).state
    current = repo.apply(state.match_id, _resolve(current, PROBE, "opponent-member")).state
    assert _source_trigger_disabled(current, owner, "source-live", "live_succeeded")
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "hand"}]
    if returned:
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_left"})
    result = repo.apply(state.match_id, _manual(current, "CONTROL", changes)).state
    assert not _source_trigger_disabled(result, owner, "source-live", "live_succeeded")
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_formal_manual_blocker_and_hidden_privacy(owner, policy):
    state = _state(owner)
    result = apply_action(state, _advance(state)); current = result.state
    before = match_state_hash(current)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    decision = controller.choose_action(current, generate_legal_actions(current), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIBlocker) and decision.reason == "no_safe_ai_action"
    changed = current.model_copy(deep=True)
    opponent = "player_2" if owner == "player_1" else "player_1"
    for key in list(changed.players[opponent].hand + changed.players[opponent].main_deck):
        item = changed.cards.pop(key)
        replacement = "HIDDEN-" + key
        item.instance_id = replacement
        item.card.card_code = item.card.name_ja = "HIDDEN"
        item.card.unit_keys, item.card.work_keys, item.card.blade = ["bibi"], ["hasunosora"], 99
        changed.cards[replacement] = item
        changed.players[opponent].hand = [replacement if i == key else i for i in changed.players[opponent].hand]
        changed.players[opponent].main_deck = [replacement if i == key else i for i in changed.players[opponent].main_deck]
    changed_before = match_state_hash(changed)
    other = controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner})
    assert isinstance(other, SimpleAIBlocker) and other.reason == decision.reason
    assert match_state_hash(current) == before and match_state_hash(changed) == changed_before
    for viewer in ("player_1", "player_2"):
        payload = _match_state_payload(current, events=result.events, legal_actions=generate_legal_actions(current), player_id=viewer)
        for player in current.players.values():
            assert not any(key in payload["state"]["cards"] for key in player.main_deck)
            if player.player_id != viewer:
                assert not any(key in payload["state"]["cards"] for key in player.hand)
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    for builder in (build_api_play_context, build_agent_context):
        context = json.dumps(builder(current, generate_legal_actions(current)))
        assert all(key not in context for key in current.players[opponent].hand)
