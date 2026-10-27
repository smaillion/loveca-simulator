from pathlib import Path

import pytest

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, CardDefinition, CardInstance
from test_effect_execution import _minimal_effect_state

FIXED = ("PL!-bp6-003:2", "PL!HS-bp5-002:2", "PL!HS-bp5-022:1",
         "PL!HS-bp6-016:1", "PL!S-sd1-006:1", "PL!SP-bp4-004:2")
DEFERRED = ("PL!N-pb1-013:1", "PL!N-pb1-015:1", "PL!N-pb1-017:1", "PL!N-pb1-023:1")


def _state(effect_id):
    effect = next(e.model_copy(deep=True) for e in load_effect_registry().effects if e.effect_id == effect_id)
    state = _minimal_effect_state(effect)
    state.phase = "first_main"
    player = state.players["player_1"]
    player.live_area = []
    member = CardDefinition(card_code="TARGET", card_id="TARGET", name_ja="登場先メンバー",
                            card_type="member", cost=2, blade=1, basic_hearts={"heart01": 1},
                            work_keys=["love_live", "hasunosora", "love_live_superstar"],
                            unit_keys=["aqours", "edel_note"])
    state.cards["target"] = CardInstance(instance_id="target", owner_id="player_1", card=member, orientation="wait", face_up=False)
    state.cards["source-live"].card = member.model_copy(update={"card_code": effect.card_code, "cost": 9}, deep=True)
    player.member_area["center"] = "source-live"
    player.waiting_room = ["target"]
    player.hand = ["live-1"]
    if effect_id == "PL!HS-bp5-022:1":
        state.cards["stage-guard"] = state.cards["source-live"].model_copy(update={"instance_id": "stage-guard"}, deep=True)
        player.member_area["center"] = "stage-guard"
        state.cards["source-live"].card = CardDefinition(
            card_code=effect.card_code, card_id=effect.card_code, name_ja="Edel Note Live",
            card_type="live", score=1, required_hearts={"heart06": 2},
        )
        player.live_area = ["source-live"]
    for i in range(4):
        key = f"energy-{i}"
        state.cards[key] = CardInstance(instance_id=key, owner_id="player_1", card=CardDefinition(
            card_code="E", card_id="E", name_ja="E", card_type="energy"))
        player.energy_area.append(key)
    if effect.choice.zone == "source_attachments":
        player.waiting_room = []
        player.member_area_attachments["center"] = ["target"]
    if effect_id == "PL!SP-bp4-004:2":
        state.cards["other"] = state.cards["source-live"].model_copy(update={"instance_id": "other"}, deep=True)
        player.member_area["left"] = "other"
        player.member_areas_baton_entered_this_turn = ["left", "center"]
        state.pending_effects[0].trigger_data.update(used_baton_touch=True, replacement_card_instance_id="other")
    return state


def _resolve(state, **payload):
    return apply_action(state, ActionRequest(action_type="resolve_effect", expected_revision=state.revision,
        player_id="player_1", payload={"invocation_id": state.pending_effects[0].invocation_id, "accepted": True, **payload}))


def _ready(state):
    effect = state.effect_definitions[state.pending_effects[0].effect_id]
    if effect.choice.choice_type == "choose_effect_branch":
        return _resolve(state, selected_branch="deploy_edel", energy_instance_ids=["energy-0", "energy-1"]).state
    if effect.cost_choice:
        return _resolve(state, selected_card_instance_ids=["live-1"]).state
    if effect.choice.choice_type == "post_action_card_from_zone":
        before = list(state.players["player_1"].main_deck)
        result = _resolve(state)
        assert state.players["player_1"].main_deck == before
        assert result.state.players["player_1"].hand[-2:] == before[:2]
        return result.state
    return state


@pytest.mark.parametrize("effect_id", FIXED)
def test_real_empty_deployment_active_legal_slot_costs_and_replay(effect_id):
    initial = _state(effect_id)
    state = _ready(initial)
    options = next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect").options["invocations"][0]
    assert options["deployment_choice"] is True
    assert "target" in options["candidate_card_instance_ids"]
    assert "right" in options["position_change_slots_by_candidate"]["target"]
    assert "center" not in options["available_slots"]
    before = state.model_dump(mode="json")
    for slot in ["center", "invalid", None]:
        with pytest.raises(IllegalActionError):
            _resolve(state, selected_card_instance_ids=["target"], to_slot=slot)
        assert state.model_dump(mode="json") == before
    energy = options.get("energy_instance_ids", [])[:options.get("energy_required", 0)]
    payload = {"selected_card_instance_ids": ["target"], "to_slot": "right", "energy_instance_ids": energy}
    result = _resolve(state, **payload)
    player = result.state.players["player_1"]
    assert player.member_area["right"] == "target"
    assert result.state.cards["target"].orientation == "active"
    assert result.state.cards["target"].face_up is True
    assert "target" not in player.waiting_room
    assert "target" not in player.member_area_attachments["center"]
    external_entry = effect_id != "PL!-bp6-003:2"
    assert player.member_entered_count_this_turn == int(external_entry)
    assert ("right" in player.member_areas_entered_this_turn) is external_entry
    assert not result.state.pending_effects
    assert not any(e.event_type == "baton_touch" for e in result.events)
    assert all(result.state.cards[e].orientation == "wait" for e in energy)
    assert _resolve(type(state).model_validate_json(state.model_dump_json()), **payload).state == result.state
    deployed = next(e for e in result.events if e.event_type.startswith((
        "effect_member_deployed", "effect_member_promoted"
    )))
    assert deployed.data["orientation"] == "active"


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1"])
@pytest.mark.parametrize("effect_id", FIXED)
def test_three_ai_policies_and_script_submit_legal_deployment_slots(policy, effect_id):
    from tools.ai_sandbox.blackbox_playtest import choose_action
    state = _ready(_state(effect_id))
    decision = SimpleAIController(SimpleAIPolicy(policy_version=policy)).choose_action(
        state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision)
    assert decision.action.payload.get("accepted") is not False
    assert decision.action.payload["to_slot"] in ["left", "right"]
    result = apply_action(state, decision.action)
    assert "target" in result.state.players["player_1"].member_area.values()
    action_type, player_id, payload = choose_action(state, generate_legal_actions(state), manual_policy="block")
    scripted = apply_action(state, ActionRequest(action_type=action_type, expected_revision=state.revision, player_id=player_id, payload=payload))
    assert "target" in scripted.state.players["player_1"].member_area.values()


def test_candidate_registry_contract_and_unrestricted_entries_stay_manual():
    from tools.ai_sandbox.effect_gap_report import classify_unresolved_reason
    registry = {e.effect_id: e for e in load_effect_registry().effects}
    candidates = {e.effect_id: e for e in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)}
    for effect_id in FIXED:
        assert candidates[effect_id].simulation_support == "test_validated_executable"
        assert all(op.orientation == "active" for op in registry[effect_id].actions if op.action_type == "deploy_selected_to_empty_stage")
        assert candidates[effect_id].actions == [op.model_dump(exclude_none=True) for op in registry[effect_id].actions]
    for effect_id in DEFERRED:
        assert registry[effect_id].simulation_support == candidates[effect_id].simulation_support == "manual_resolution"
        assert not registry[effect_id].cost and registry[effect_id].choice is None
        assert classify_unresolved_reason("member_played", "on_play", registry[effect_id].label_ja) == "occupied_stage_deployment_and_current_member_entry_history_not_modeled"


@pytest.mark.parametrize("effect_id,amount", [("PL!HS-bp5-002:2", 2), ("PL!HS-bp6-016:1", 4)])
def test_real_activated_entry_pays_once_then_exposes_deployment_position(effect_id, amount):
    state = _state(effect_id)
    state.pending_effects = []
    state.cards["source-live"].card.effect_ids = [effect_id]
    request = ActionRequest(action_type="activate_effect", expected_revision=state.revision, player_id="player_1",
                            payload={"effect_id": effect_id, "source_card_instance_id": "source-live",
                                     "energy_instance_ids": [f"energy-{i}" for i in range(amount)]})
    activated = apply_action(state, request).state
    assert activated.pending_effects[0].resolution_stage == "after_cost"
    result = _resolve(activated, selected_card_instance_ids=["target"], to_slot="right")
    assert result.state.players["player_1"].member_area["right"] == "target"
    assert sum(result.state.cards[e].orientation == "wait" for e in activated.players["player_1"].energy_area) == amount
    assert not any(e.event_type == "effect_cost_paid" for e in result.events)


def test_edel_note_cost_threshold_is_checked_before_paying():
    state = _state("PL!HS-bp5-022:1")
    state.cards["stage-guard"].card.cost = 8
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalActionError):
        _resolve(state, selected_branch="deploy_edel", energy_instance_ids=["energy-0", "energy-1"])
    assert state.model_dump(mode="json") == before


def test_old_snapshot_missing_orientation_keeps_legacy_wait():
    state = _state(FIXED[0])
    effect = state.effect_definitions[FIXED[0]].model_dump()
    effect["actions"][0].pop("orientation")
    state.effect_definitions[FIXED[0]] = EffectDefinition.model_validate(effect)
    restored = type(state).model_validate_json(state.model_dump_json())
    result = _resolve(restored, selected_card_instance_ids=["target"], to_slot="right")
    assert result.state.cards["target"].orientation == "wait"


def test_branch_with_full_stage_hides_deployment_but_keeps_other_branch():
    state = _state("PL!HS-bp5-022:1")
    player = state.players["player_1"]
    for slot in ["left", "right"]:
        key = f"occupied-{slot}"
        state.cards[key] = state.cards["stage-guard"].model_copy(update={"instance_id": key}, deep=True)
        player.member_area[slot] = key
    options = next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect").options["invocations"][0]
    assert options["available_branch_ids"] == ["reduce_heart06"]
    assert "deployment_choice" not in options
    result = _resolve(state, selected_branch="reduce_heart06", energy_instance_ids=["energy-0", "energy-1"])
    assert not result.state.pending_effects
    from loveca.simulation.engine import _effective_required_hearts
    player = result.state.players["player_1"]
    assert _effective_required_hearts(player, "source-live", {"heart06": 2}) == {"heart06": 1}
    assert player.manual_modifiers[-1].target_card_instance_id == "source-live"


@pytest.mark.parametrize("effect_id", ["PL!S-sd1-006:1", "PL!HS-bp5-022:1"])
def test_no_target_after_cost_resolves_possible_part_and_logs_reason(effect_id):
    state = _ready(_state(effect_id))
    state.cards["target"].card.cost = 99
    options = next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect").options["invocations"][0]
    assert options["card_selection_minimum"] == 0
    result = _resolve(state)
    assert not result.state.pending_effects
    assert "target" in result.state.players["player_1"].waiting_room
    assert any(e.event_type == "effect_operation_not_applied" for e in result.events)


def test_draw_then_deployment_with_full_stage_still_draws_and_finishes():
    state = _state("PL!SP-bp4-004:2")
    state.cards["occupied"] = state.cards["source-live"].model_copy(update={"instance_id": "occupied"}, deep=True)
    state.players["player_1"].member_area["right"] = "occupied"
    result = _resolve(state)
    assert len(result.state.players["player_1"].hand) == 3
    assert not result.state.pending_effects
    assert "target" in result.state.players["player_1"].waiting_room


@pytest.mark.parametrize("ids", [["target", "target"], ["source-live"], ["does-not-exist"]])
def test_invalid_deployment_ids_do_not_pay_energy_or_change_revision(ids):
    state = _state("PL!HS-bp5-002:2")
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalActionError):
        _resolve(state, selected_card_instance_ids=ids, to_slot="right", energy_instance_ids=["energy-0", "energy-1"])
    assert state.model_dump(mode="json") == before


def test_deployment_target_onplay_is_queued_without_revealing_owner_hand():
    from loveca.webapp import _match_state_payload
    # A Waiting Room entry is external; promotion from an attachment is not.
    state = _state("PL!HS-bp5-002:2")
    effect = state.effect_definitions["PL!HS-bp5-002:2"].model_copy(update={
        "effect_id": "test-new-onplay:1", "trigger": "member_played", "timing": "on_play",
        "choice": None, "actions": [], "condition": {}, "is_optional": True,
    }, deep=True)
    state.effect_definitions[effect.effect_id] = effect
    state.cards["target"].card.effect_ids = [effect.effect_id]
    result = _resolve(state, selected_card_instance_ids=["target"], to_slot="right",
                      energy_instance_ids=["energy-0", "energy-1"])
    assert result.state.pending_effects[0].effect_id == effect.effect_id
    assert result.state.pending_effects[0].trigger_data["used_baton_touch"] is False
    payload = _match_state_payload(result.state, events=[], legal_actions=generate_legal_actions(result.state), player_id="player_2")
    assert "target" in payload["state"]["cards"]
    assert "live-1" not in payload["state"]["cards"]
