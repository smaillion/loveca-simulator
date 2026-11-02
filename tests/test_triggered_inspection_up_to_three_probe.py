import json
import pytest
from pydantic import ValidationError

from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import apply_action, generate_legal_actions, IllegalActionError
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.online import match_state_hash
from loveca.webapp import _match_state_payload
from test_multi_keep_inspection_audit import _state, CODE
from test_mirakura_front_position_boundary import _swap_roles
from test_nijigasaki_inspection import _play, _resolve, _select
from test_printemps_ready_history_boundary import _manual, _repo, _replay

POLICY = "triggered_inspection_up_to_three_v1"


def _raw():
    raw = _state(legacy=True).effect_definitions[CODE + ":1"].model_dump(mode="json")
    raw["effect_id"] = "UNREGISTERED-MULTI-KEEP:1"
    raw["card_code"] = "UNREGISTERED-MULTI-KEEP"
    raw["choice"]["cost_payment_policy"] = POLICY
    return raw


def test_old_single_selection_policy_still_rejects_three():
    raw = _raw()
    raw["choice"]["cost_payment_policy"] = "triggered_inspection"
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


def test_new_explicit_probe_shape_is_accepted():
    effect = EffectDefinition.model_validate(_raw())
    assert effect.choice.cost_payment_policy == POLICY


@pytest.mark.parametrize("field,value", [("amount", 6), ("maximum", 2), ("minimum", 1),
    ("card_type", "live"), ("heart_color_slots_any", ["heart02"]),
    ("reveal_selected_to_opponent", False), ("selected_destination", "main_deck"),
    ("requires_order", True), ("work_key", "love_live")])
def test_probe_rejects_other_choice_shapes(field, value):
    raw = _raw(); raw["choice"][field] = value
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("field,value", [("is_optional", False), ("condition", {"unknown": True}),
    ("frequency_limit", "once_per_turn"), ("duration", "game"), ("timing", "live_start")])
def test_probe_rejects_other_parent_shapes(field, value):
    raw = _raw(); raw[field] = value
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


def _probe(owner, empty=False):
    state = _state(legacy=True, empty=empty)
    effect = EffectDefinition.model_validate(_raw())
    state.effect_definitions.pop(CODE + ":1")
    state.effect_definitions[effect.effect_id] = effect
    state.cards["source-live"].card.effect_ids = [effect.effect_id]
    state.cards["source-live"].card.card_code = "UNREGISTERED-MULTI-KEEP"
    state.cards["source-live"].card.name_ja = "UNREGISTERED"
    return _swap_roles(state) if owner == "player_2" else state


def _for(request, owner):
    request.player_id = owner
    return request


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_probe_actual_discard_and_private_selection_sql(tmp_path, owner, count):
    state = _probe(owner)
    play = _for(_play(state), owner); play.payload["energy_instance_ids"] = state.players[owner].energy_area
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, play).state
    result = repo.apply(state.match_id, _for(_resolve(current, selected_card_instance_ids=["cost"]), owner))
    assert sum(e.event_type == "effect_cost_paid" for e in result.events) == 1
    assert set(result.state.pending_choice.options["candidate_card_instance_ids"]) == {"good-member", "wrong-work", "tail"}
    opponent = "player_2" if owner == "player_1" else "player_1"
    payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=opponent)
    assert not any(key in json.dumps(payload) for key in result.state.pending_choice.options["inspected_card_instance_ids"])
    picked = ["good-member", "wrong-work", "tail"][:count]
    final = repo.apply(state.match_id, _for(_select(result.state, picked), owner)).state
    assert set(final.players[owner].hand) == set(picked)
    assert set(final.players[owner].waiting_room) == {"cost", *state.players[owner].main_deck} - set(picked)
    _replay(repo, final)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("accepted", [True, False])
def test_unpayable_optional_probe_is_not_paid_and_can_decline_sql(tmp_path, owner, accepted):
    state = _probe(owner, empty=True)
    play = _for(_play(state), owner); play.payload["energy_instance_ids"] = state.players[owner].energy_area
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, play).state
    options = next(a for a in generate_legal_actions(current) if a.action_type == "resolve_effect").options
    assert options["invocations"][0]["cost_payment_unavailable_reason"] == "inspection_cost_candidates_unavailable"
    declined = repo.apply(state.match_id, _for(_resolve(current, accepted=accepted), owner))
    assert not any(e.event_type in {"effect_cost_paid", "effect_inspection_started"} for e in declined.events)
    assert declined.state.pending_choice is None and not declined.state.pending_effects
    _replay(repo, declined.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("ids", [["good-member", "good-member"], ["good-member", "wrong-work", "tail", "blade-heart"], ["good-live"], ["opponent-secret"]])
def test_probe_invalid_selection_is_atomic_sql(tmp_path, owner, ids):
    state = _probe(owner)
    play = _for(_play(state), owner); play.payload["energy_instance_ids"] = state.players[owner].energy_area
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, play).state
    current = repo.apply(state.match_id, _for(_resolve(current, selected_card_instance_ids=["cost"]), owner)).state
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _for(_select(current, ids), owner))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_probe_short_deck_refresh_after_cost_sql(tmp_path, owner):
    state = _probe(owner)
    player = state.players[owner]
    player.main_deck = ["good-member"]
    player.waiting_room = ["wrong-work", "tail", "blade-heart", "good-live", "deck-live-1", "extra"]
    play = _for(_play(state), owner); play.payload["energy_instance_ids"] = player.energy_area
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, play).state
    inspected = repo.apply(state.match_id, _for(_resolve(current, selected_card_instance_ids=["cost"]), owner))
    kinds = [e.event_type for e in inspected.events]
    assert kinds.index("effect_cost_paid") < kinds.index("deck_refreshed") < kinds.index("effect_inspection_started")
    assert len(inspected.state.pending_choice.options["inspected_card_instance_ids"]) == 7
    final = repo.apply(state.match_id, _for(_select(inspected.state, []), owner)).state
    _replay(repo, final)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("zone", ["hand", "main_deck"])
def test_probe_source_after_entry_can_leave_without_exposing_private_cards_sql(tmp_path, owner, zone):
    state = _probe(owner)
    raw = state.effect_definitions["UNREGISTERED-MULTI-KEEP:1"].model_dump(mode="json")
    raw.update(effect_id="CONTROL", cost=[], cost_choice=None, choice=None, actions=[{"action_type": "manual_resolution"}],
               execution_mode="manual_resolution", simulation_support="manual_resolution", is_optional=False)
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    state.cards["source-live"].card.effect_ids.append("CONTROL")
    play = _for(_play(state), owner); play.payload["energy_instance_ids"] = state.players[owner].energy_area
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, play).state
    current = repo.apply(state.match_id, _manual(current, "CONTROL", [{"adjustment_type": "move_card",
        "target_card_instance_id": "source-live", "to_zone": zone}])).state
    inspected = repo.apply(state.match_id, _for(_resolve(current, selected_card_instance_ids=["cost"]), owner))
    opponent = "player_2" if owner == "player_1" else "player_1"
    payload = _match_state_payload(inspected.state, events=inspected.events, legal_actions=inspected.legal_actions, player_id=opponent)
    assert "source-live" not in payload["state"]["cards"]
    assert not any(i in json.dumps(payload) for i in inspected.state.pending_choice.options["inspected_card_instance_ids"])
    final = repo.apply(state.match_id, _for(_select(inspected.state, []), owner)).state
    _replay(repo, final)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_probe_four_ai_hidden_opponent_invariance(owner, policy):
    state = _probe(owner)
    play = _for(_play(state), owner); play.payload["energy_instance_ids"] = state.players[owner].energy_area
    state = apply_action(state, play).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    first = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(first, SimpleAIDecision)
    state = apply_action(state, first.action).state
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    changed = state.model_copy(deep=True); opponent = "player_2" if owner == "player_1" else "player_1"
    item = changed.cards.pop("opponent-secret"); item.instance_id = "hidden-replacement"
    item.card.card_code = item.card.name_ja = "HIDDEN"
    item.card.unit_keys, item.card.work_keys, item.card.blade = ["bibi"], ["hasunosora"], 99
    changed.cards[item.instance_id] = item
    changed.players[opponent].hand = [item.instance_id if i == "opponent-secret" else i for i in changed.players[opponent].hand]
    changed_before = match_state_hash(changed)
    other = controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision) and isinstance(other, SimpleAIDecision) and decision.action == other.action
    assert match_state_hash(state) == before and match_state_hash(changed) == changed_before
    apply_action(state, decision.action); apply_action(changed, other.action)
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    for builder in (build_api_play_context, build_agent_context):
        assert "opponent-secret" not in json.dumps(builder(state, generate_legal_actions(state)))
