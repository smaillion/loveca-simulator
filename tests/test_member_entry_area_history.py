import json
from itertools import permutations
from pathlib import Path

import pytest

from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, CardDefinition, CardInstance, EffectInvocation, MatchState
from test_cost_result_branch import _effect
from test_effect_execution import _minimal_effect_state

ENTRY_FIELD = "member_card_instance_ids_entered_stage_this_turn"
RULE_REFERENCE_IDS = ("4.5.5.3", "9.6.2.1.2.1", "9.6.2.4.2.1")


def _state(*, modern=True, baton=False):
    state = _minimal_effect_state(_effect())
    state.phase = "first_main"
    state.pending_effects = []
    player = state.players["player_1"]
    player.live_area = []
    for key, cost in [("entrant", 2), ("next", 2), ("old", 1), ("replaced", 1), ("attachment", 1)]:
        state.cards[key] = CardInstance(instance_id=key, owner_id="player_1", card=CardDefinition(
            card_code=key, card_id=key, name_ja=key, card_type="member", cost=cost, blade=1,
            basic_hearts={"heart01": 1}))
    player.hand = ["entrant", "next", "attachment"]
    player.member_area["center"] = "old"
    if baton:
        player.member_area["left"] = "replaced"
    for i in range(6):
        key = f"energy-{i}"
        state.cards[key] = CardInstance(instance_id=key, owner_id="player_1", card=CardDefinition(
            card_code="E", card_id="E", name_ja="E", card_type="energy"))
        player.energy_area.append(key)
    raw = state.model_dump(mode="json")
    if modern:
        for player_raw in raw["players"].values():
            player_raw[ENTRY_FIELD] = []
    return MatchState.model_validate(raw)


def _action(state, action_type, **payload):
    return ActionRequest(action_type=action_type, expected_revision=state.revision, player_id="player_1", payload=payload)


def _manual(state, **adjustment):
    return apply_action(state, _action(state, "manual_adjustment", reason="区域规则回归",
        adjustments=[{"target_player_id": "player_1", **adjustment}])).state


def _play(state, card_id="entrant", slot="left", baton=False):
    cost = state.cards[card_id].card.cost
    old = state.players["player_1"].member_area[slot]
    amount = max(0, cost - state.cards[old].card.cost) if baton else cost
    energies = [e for e in state.players["player_1"].energy_area if state.cards[e].orientation == "active"][:amount]
    return apply_action(state, _action(state, "play_member", card_instance_id=card_id, slot=slot,
        use_baton_touch=baton, energy_instance_ids=energies))


def _slots(state, card_id="next", *, baton=False):
    legal = next(a for a in generate_legal_actions(state) if a.action_type == "play_member")
    return {p["slot"] for p in legal.options["placements"] if p["card_instance_id"] == card_id and p["use_baton_touch"] is baton}


@pytest.mark.parametrize("baton", [False, True])
def test_entry_lock_follows_member_after_position_swap_not_the_old_area(baton):
    state = _play(_state(baton=baton), baton=baton).state
    moved = _manual(state, adjustment_type="position_change", from_slot="left", to_slot="center")
    assert _slots(moved) == {"left", "right"}
    assert _slots(moved, baton=True) == {"left"}
    before = moved.model_dump(mode="json")
    with pytest.raises(IllegalActionError):
        _play(moved, "next", "center")
    assert moved.model_dump(mode="json") == before
    final = _play(moved, "next", "left", baton=True).state
    assert final.players["player_1"].member_area["left"] == "next"
    assert "old" in final.players["player_1"].waiting_room
    assert final.players["player_1"].member_area["center"] == "entrant"


@pytest.mark.parametrize("assignments", list(permutations(["entrant", "old", None])))
def test_formation_change_tracks_current_card_and_keeps_history(assignments):
    state = _play(_state()).state
    before = state.model_dump(mode="json")
    slots = dict(zip(["left", "center", "right"], assignments))
    moved = _manual(state, adjustment_type="formation_change", slot_assignments=slots)
    blocked = next(slot for slot, card in slots.items() if card == "entrant")
    assert _slots(moved) == set(slots) - {blocked}
    assert getattr(moved.players["player_1"], ENTRY_FIELD) == ["entrant"]
    assert state.model_dump(mode="json") == before
    restored = MatchState.model_validate_json(moved.model_dump_json())
    assert _slots(restored) == _slots(moved)


@pytest.mark.parametrize("from_zone", ["hand", "waiting_room"])
@pytest.mark.parametrize("slot", ["left", "right"])
def test_manual_external_entry_is_recorded_but_manual_stage_move_is_not(from_zone, slot):
    state = _state()
    player = state.players["player_1"]
    if from_zone == "waiting_room":
        player.hand.remove("entrant")
        player.waiting_room.append("entrant")
    state = _manual(state, adjustment_type="move_card", target_card_instance_id="entrant", to_zone=f"member_{slot}")
    assert getattr(state.players["player_1"], ENTRY_FIELD) == ["entrant"]
    other = "right" if slot == "left" else "left"
    state = _manual(state, adjustment_type="move_card", target_card_instance_id="entrant", to_zone=f"member_{other}")
    assert getattr(state.players["player_1"], ENTRY_FIELD) == ["entrant"]
    assert _slots(state) == {"left", "center", "right"} - {other}


@pytest.mark.parametrize("fresh_attachment", [False, True])
def test_attachment_moves_with_group_and_only_external_member_card_blocks_area(fresh_attachment):
    state = _state()
    player = state.players["player_1"]
    if fresh_attachment:
        state = _manual(state, adjustment_type="attach_card_under_member", target_card_instance_id="attachment", target_slot="center")
    else:
        player.hand.remove("attachment")
        player.member_area_attachments["center"] = ["attachment"]
    before_ids = list(getattr(state.players["player_1"], ENTRY_FIELD))
    state = _manual(state, adjustment_type="position_change", from_slot="center", to_slot="left")
    assert state.players["player_1"].member_area_attachments["left"] == ["attachment"]
    assert getattr(state.players["player_1"], ENTRY_FIELD) == before_ids
    assert _slots(state) == ({"center", "right"} if fresh_attachment else {"left", "center", "right"})
    assert state.players["player_1"].member_entered_count_this_turn == 0


@pytest.mark.parametrize("fresh_attachment", [False, True])
def test_promoting_attached_card_within_stage_does_not_invent_an_external_entry(fresh_attachment):
    state = _state()
    player = state.players["player_1"]
    if fresh_attachment:
        state = _manual(state, adjustment_type="attach_card_under_member", target_card_instance_id="attachment", target_slot="center")
    else:
        player.hand.remove("attachment")
        player.member_area_attachments["center"] = ["attachment"]
    state = _manual(state, adjustment_type="move_attached_card", target_card_instance_id="attachment", to_zone="member_left")
    assert getattr(state.players["player_1"], ENTRY_FIELD) == (["attachment"] if fresh_attachment else [])
    assert "center" in _slots(state)
    assert ("left" not in _slots(state)) is fresh_attachment


@pytest.mark.parametrize("energy", [False, True])
@pytest.mark.parametrize("source_zone", ["hand", "waiting_room"])
def test_structured_attachment_cost_tracks_member_cards_not_energy(energy, source_zone):
    from loveca.simulation.effects import EffectDefinition
    state = _state()
    player = state.players["player_1"]
    key = "energy-0" if energy else "attachment"
    zone = "energy_area" if energy else source_zone
    if not energy and source_zone == "waiting_room":
        player.hand.remove(key)
        player.waiting_room.append(key)
    raw = _effect().model_dump()
    raw.update(effect_id="attach-history:1", trigger="member_played", timing="on_play", effect_type="triggered",
               cost=[{"action_type": "attach_selected_under_source", "value": {"source_zone": zone}}],
               cost_choice={"choice_type": "card_from_zone", "zone": zone, "minimum": 1, "maximum": 1},
               choice=None, actions=[], condition={}, is_optional=False)
    if zone == "waiting_room":
        raw.update(cost=[], cost_choice=None,
                   choice={"choice_type": "card_from_zone", "zone": zone, "minimum": 1, "maximum": 1},
                   actions=[{"action_type": "attach_selected_under_source", "value": {"source_zone": zone}}])
    effect = EffectDefinition.model_validate(raw)
    state.effect_definitions = {effect.effect_id: effect}
    state.pending_effects = [EffectInvocation(invocation_id="attach-inv", effect_id=effect.effect_id,
        source_card_instance_id="old", player_id="player_1", trigger_event="member_played")]
    result = apply_action(state, _action(state, "resolve_effect", invocation_id="attach-inv", selected_card_instance_ids=[key]))
    player = result.state.players["player_1"]
    assert getattr(player, ENTRY_FIELD) == ([] if energy else [key])
    assert player.member_area_attachments["center"] == [key]
    assert ("center" not in _slots(result.state)) is (not energy)


@pytest.mark.parametrize("effect_id", ["PL!HS-bp5-002:2", "PL!-bp6-003:2"])
def test_effect_deployment_records_waiting_room_entry_but_not_stage_transfer(effect_id):
    from test_empty_effect_deployment import _state as effect_state, _resolve
    state = effect_state(effect_id)
    player = state.players["player_1"]
    setattr(player, ENTRY_FIELD, [])
    energy = ["energy-0", "energy-1"] if effect_id.startswith("PL!HS") else []
    result = _resolve(state, selected_card_instance_ids=["target"], to_slot="right", energy_instance_ids=energy)
    assert getattr(result.state.players["player_1"], ENTRY_FIELD) == (["target"] if energy else [])
    assert result.state.players["player_1"].member_area["right"] == "target"
    from loveca.simulation.engine import _member_area_blocks_entry
    assert _member_area_blocks_entry(result.state.players["player_1"], "right") is bool(energy)


@pytest.mark.parametrize("modern", [False, True])
def test_next_turn_clears_history_without_implicitly_upgrading_legacy_snapshots(modern):
    state = _play(_state(modern=modern)).state
    state.phase = "turn_complete"
    state.next_first_player_id = "player_2"
    result = apply_action(state, ActionRequest(action_type="start_next_turn", player_id="player_2", expected_revision=state.revision))
    for player in result.state.players.values():
        assert getattr(player, ENTRY_FIELD) == ([] if modern else None)
        assert player.member_areas_entered_this_turn == []


def test_legacy_snapshot_omits_new_field_and_preserves_original_hash_and_area_behavior():
    from loveca.simulation.online import match_state_hash, sha256_json
    state = _state(modern=False)
    raw = state.model_dump(mode="json")
    assert all(ENTRY_FIELD not in player for player in raw["players"].values())
    restored = MatchState.model_validate_json(json.dumps(raw))
    assert match_state_hash(restored) == sha256_json(raw)
    moved = _manual(_play(restored).state, adjustment_type="position_change", from_slot="left", to_slot="center")
    assert _slots(moved) == {"center", "right"}
    assert all(ENTRY_FIELD not in player for player in moved.model_dump(mode="json")["players"].values())


def test_new_history_replays_every_step_with_identical_state_hashes():
    from loveca.simulation.online import match_state_hash
    initial = _state()
    actions = [
        _action(initial, "play_member", card_instance_id="entrant", slot="left", energy_instance_ids=["energy-0", "energy-1"]),
        ActionRequest(action_type="manual_adjustment", player_id="player_1", expected_revision=1, payload={
            "reason": "位置交换", "adjustments": [{"adjustment_type": "position_change", "target_player_id": "player_1", "from_slot": "left", "to_slot": "center"}]}),
        ActionRequest(action_type="play_member", player_id="player_1", expected_revision=2, payload={
            "card_instance_id": "next", "slot": "left", "use_baton_touch": True, "energy_instance_ids": ["energy-2"]}),
    ]
    state = initial
    hashes = []
    for action in actions:
        state = apply_action(state, action).state
        hashes.append(match_state_hash(state))
    replayed = MatchState.model_validate_json(initial.model_dump_json())
    for action, expected in zip(actions, hashes):
        replayed = apply_action(replayed, ActionRequest.model_validate_json(action.model_dump_json())).state
        assert match_state_hash(replayed) == expected
    assert replayed == state


def test_entry_bookkeeping_is_not_exposed_to_opponent_or_ai_observation():
    from loveca.webapp import _match_state_payload
    from loveca.simulation.rule_evaluation import build_ai_observation
    state = _play(_state()).state
    state = _manual(state, adjustment_type="move_card", target_card_instance_id="entrant", to_zone="hand")
    before = state.model_dump(mode="json")
    own = _match_state_payload(state, events=[], legal_actions=generate_legal_actions(state), player_id="player_1")
    other = _match_state_payload(state, events=[], legal_actions=generate_legal_actions(state), player_id="player_2")
    assert own["state"]["players"]["player_1"][ENTRY_FIELD] == ["entrant"]
    assert ENTRY_FIELD not in other["state"]["players"]["player_1"]
    assert "entrant" not in other["state"]["cards"]
    observation = build_ai_observation(state, "player_2", generate_legal_actions(state))
    assert observation.card("entrant") is None
    assert not hasattr(observation.players["player_1"], ENTRY_FIELD)
    assert state.model_dump(mode="json") == before


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1"])
def test_ai_consumes_new_legal_areas_without_hidden_hand_dependency(policy):
    from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
    state = _manual(_play(_state()).state, adjustment_type="position_change", from_slot="left", to_slot="center")
    state.cards["hidden"] = state.cards["next"].model_copy(update={"instance_id": "hidden", "owner_id": "player_2"}, deep=True)
    state.players["player_2"].hand = ["hidden"]
    state.cards["hidden"].face_up = False
    before = state.model_dump(mode="json")
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision)
    assert decision.action.action_type == "play_member"
    assert decision.action.payload["slot"] != "center"
    assert state.model_dump(mode="json") == before
    other_hidden = state.model_copy(deep=True)
    other_hidden.cards["hidden"].card.name_ja = "別の非公開カード"
    other_hidden.cards["hidden"].card.cost = 99
    assert controller.choose_action(other_hidden, generate_legal_actions(other_hidden), controlled_player_ids={"player_1"}).action == decision.action
    assert apply_action(state, decision.action).state.revision == state.revision + 1


def test_leaving_stage_unlocks_old_area_even_when_history_keeps_card_identity():
    state = _play(_state()).state
    state = _manual(state, adjustment_type="move_card", target_card_instance_id="entrant", to_zone="waiting_room")
    assert getattr(state.players["player_1"], ENTRY_FIELD) == ["entrant"]
    assert _slots(state) == {"left", "center", "right"}
    assert _play(state, "next", "left").state.players["player_1"].member_area["left"] == "next"


def test_failed_manual_batch_rolls_back_new_entry_identity_and_all_zone_changes():
    state = _state()
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalActionError):
        apply_action(state, _action(state, "manual_adjustment", reason="原子性检查", adjustments=[
            {"adjustment_type": "move_card", "target_player_id": "player_1", "target_card_instance_id": "entrant", "to_zone": "member_left"},
            {"adjustment_type": "move_card", "target_player_id": "player_1", "target_card_instance_id": "next", "to_zone": "member_left"},
        ]))
    assert state.model_dump(mode="json") == before
    assert getattr(state.players["player_1"], ENTRY_FIELD) == []


def test_original_match_creation_api_enables_history_and_runtime_replay_keeps_it(tmp_path):
    from test_webapp import _client, SAMPLE_DECK
    client = _client(tmp_path)
    deck = json.loads(Path(SAMPLE_DECK).read_text(encoding="utf-8"))
    response = client.post("/api/matches", json={
        "player_1": {"name": "A", "deck": deck}, "player_2": {"name": "B", "deck": deck}, "seed": 41,
    })
    assert response.status_code == 200
    payload = response.json()
    assert all(player[ENTRY_FIELD] == [] for player in payload["state"]["players"].values())
    match_id = payload["state"]["match_id"]
    replay = client.get(f"/api/matches/{match_id}/replay").json()
    assert all(player[ENTRY_FIELD] == [] for player in replay["initial_state"]["players"].values())
    assert replay["final_state"] == payload["state"]


def test_both_player_deployment_records_each_owners_member_identity():
    from loveca.simulation.effects import EffectDefinition
    state = _state()
    state.players["player_1"].hand.remove("entrant")
    state.players["player_1"].waiting_room.append("entrant")
    state.cards["opponent-target"] = state.cards["entrant"].model_copy(update={"instance_id": "opponent-target", "owner_id": "player_2"}, deep=True)
    state.players["player_2"].waiting_room = ["opponent-target"]
    raw = _effect().model_dump()
    raw.update(effect_id="multi-history:1", trigger="member_played", timing="on_play", effect_type="triggered",
               cost=[], cost_choice=None, condition={}, actions=[], is_optional=False,
               choice={"choice_type": "multi_player_deploy_waiting_member", "zone": "waiting_room", "card_type": "member",
                       "maximum_cost": 2, "minimum": 0, "maximum": 1})
    effect = EffectDefinition.model_validate(raw)
    state.effect_definitions = {effect.effect_id: effect}
    state.pending_effects = [EffectInvocation(invocation_id="multi-inv", effect_id=effect.effect_id,
        source_card_instance_id="old", player_id="player_1", trigger_event="member_played")]
    state = apply_action(state, _action(state, "resolve_effect", invocation_id="multi-inv")).state
    state = apply_action(state, _action(state, "resolve_effect_choice", selected_card_instance_id="entrant", slot="left")).state
    assert state.pending_choice.player_id == "player_2"
    state = apply_action(state, ActionRequest(action_type="resolve_effect_choice", player_id="player_2", expected_revision=state.revision,
        payload={"selected_card_instance_id": "opponent-target", "slot": "center"})).state
    assert getattr(state.players["player_1"], ENTRY_FIELD) == ["entrant"]
    assert getattr(state.players["player_2"], ENTRY_FIELD) == ["opponent-target"]
    assert not state.pending_choice and not state.pending_effects
    assert "left" not in _slots(state)


def test_baton_replaced_member_returning_from_waiting_room_as_attachment_is_external():
    from loveca.simulation.effects import EffectDefinition
    state = _play(_state(baton=True), baton=True).state
    raw = _effect().model_dump()
    raw.update(effect_id="baton-attach-history:1", trigger="member_played", timing="on_play", effect_type="triggered",
               cost=[], cost_choice=None, condition={}, choice=None,
               actions=[{"action_type": "attach_baton_replaced_member_under_source"}], is_optional=False)
    effect = EffectDefinition.model_validate(raw)
    state.effect_definitions = {effect.effect_id: effect}
    state.pending_effects = [EffectInvocation(invocation_id="baton-attach-inv", effect_id=effect.effect_id,
        source_card_instance_id="entrant", player_id="player_1", trigger_event="member_played",
        trigger_data={"replacement_card_instance_id": "replaced", "used_baton_touch": True})]
    state = apply_action(state, _action(state, "resolve_effect", invocation_id="baton-attach-inv")).state
    assert getattr(state.players["player_1"], ENTRY_FIELD) == ["entrant", "replaced"]
    assert state.players["player_1"].member_area_attachments["left"] == ["replaced"]


@pytest.mark.parametrize("modern", [False, True])
def test_runtime_replay_keeps_legacy_and_new_entry_modes_separate(tmp_path, modern):
    from loveca.simulation.runtime import MatchRepository
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    state = _state(modern=modern)
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    action = _action(state, "play_member", card_instance_id="entrant", slot="left", energy_instance_ids=["energy-0", "energy-1"])
    state = repository.apply(state.match_id, action).state
    action = _action(state, "manual_adjustment", reason="Replay 区域变更",
        adjustments=[{"adjustment_type": "position_change", "target_player_id": "player_1", "from_slot": "left", "to_slot": "center"}])
    state = repository.apply(state.match_id, action).state
    replay = repository.replay(state.match_id)
    assert replay["final_state"] == state.model_dump(mode="json")
    assert _slots(MatchState.model_validate(replay["final_state"])) == ({"left", "right"} if modern else {"center", "right"})
    if not modern:
        assert ENTRY_FIELD not in replay["initial_state"]["players"]["player_1"]
        assert ENTRY_FIELD not in replay["final_state"]["players"]["player_1"]
