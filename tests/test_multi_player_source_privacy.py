import json
import sqlite3
from pathlib import Path

import pytest
from test_multi_player_entry import EFFECT_ID, _state as entry_state
from test_moved_source_ready import _manual
from test_player_payload_privacy import _room
from test_webapp import _client

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, EffectInvocation
from loveca.simulation.online import match_state_hash
from loveca.simulation.rule_evaluation import build_ai_observation
from loveca.simulation.runtime import MatchRepository
from loveca.simulation.visibility import owner_manual_source_handles, redact_hidden_references
from loveca.webapp import _match_state_payload
from tools.ai_sandbox.semantic_playtest import build_agent_context, build_api_play_context

RULE_REFERENCE_IDS = ("4.1.2.2", "4.1.5.1", "4.8.2", "4.9.2", "4.11.2", "9.7.7")
KINDS = ("multi_player_deploy_waiting_member", "multi_player_draw_then_discard",
         "multi_player_discard_to_hand_size_then_draw", "multi_player_waiting_live_recovery")


def _action(state, kind, player=None, **payload):
    return ActionRequest(action_type=kind, player_id=player or state.pending_choice.player_id,
                         expected_revision=state.revision, payload=payload)


def _select(state):
    options = state.pending_choice.options
    ids = [key for key in options["candidate_card_instance_ids"] if key != "source-live"]
    if options["multi_player_choice_type"] == KINDS[0]:
        return _action(state, "resolve_effect_choice", selected_card_instance_id=ids[0], slot="right")
    return _action(state, "resolve_effect_choice", selected_card_instance_ids=ids[:options["minimum"]])


def _view(state, viewer, events=()):
    return _match_state_payload(state, events=list(events), legal_actions=generate_legal_actions(state), player_id=viewer)


def _choice_state(kind, owner, zone):
    state = entry_state()
    effect = next(e for e in load_effect_registry().effects if e.choice and e.choice.choice_type == kind)
    state.effect_definitions = {effect.effect_id: effect}
    for player_id, player in state.players.items():
        player.member_area = {"left": None, "center": None, "right": None}
        player.hand = []
        for i in range(5):
            key = f"{player_id}-hand-{i}"
            card = state.cards["target"].model_copy(deep=True)
            card.instance_id, card.owner_id, card.face_up = key, player_id, False
            card.card.effect_ids = []
            state.cards[key] = card
            player.hand.append(key)
    if kind == KINDS[3]:
        for key in ("target", "opponent-target"):
            state.cards[key].card.card_type = "live"
    state.cards["source-live"].owner_id = owner
    state.cards["source-live"].card.effect_ids = [effect.effect_id]
    # Keep a separate public Member for the existing Live-start condition.
    for player_id, player in state.players.items():
        key = player.hand[0]
        player.hand.remove(key)
        player.member_area["left"] = key
    if zone == "stage":
        state.players[owner].member_area["center"] = "source-live"
    else:
        getattr(state.players[owner], zone).append("source-live")
    state.pending_effects = [EffectInvocation(invocation_id="privacy-parent", effect_id=effect.effect_id,
        source_card_instance_id="source-live", player_id=owner, trigger_event=effect.trigger,
        trigger_data={"replacement_card_instance_id": "target"})]
    state.active_player_id = owner
    state.phase = "first_main" if owner == "player_1" else "second_main"
    state = apply_action(state, _action(state, "resolve_effect", owner, invocation_id="privacy-parent")).state
    assert state.pending_choice.player_id == owner
    return apply_action(state, _select(state)).state


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("zone", ["hand", "main_deck", "stage"])
def test_multiplayer_metadata_never_grants_card_map_visibility(kind, owner, zone):
    state = _choice_state(kind, owner, zone)
    viewer = "player_2" if owner == "player_1" else "player_1"
    assert state.pending_choice.player_id == viewer
    before = match_state_hash(state)
    actions = generate_legal_actions(state)
    raw_actions = [a.model_dump() for a in actions]
    payload = _view(state, viewer)
    visible = zone == "stage"
    assert ("source-live" in payload["state"]["cards"]) is visible
    assert ("source-live" in json.dumps(payload)) is visible
    assert ("source-live" in build_ai_observation(state, viewer, actions).cards) is visible
    for build in (build_api_play_context, build_agent_context):
        assert ("source-live" in json.dumps(build(state, actions))) is visible
    if zone == "hand":
        assert "source-live" in _view(state, owner)["state"]["cards"]
    assert [a.model_dump() for a in actions] == raw_actions
    assert match_state_hash(state) == before


def _native_initial(*, legacy=False, owner="player_1"):
    state = entry_state(legacy=legacy)
    state.pending_effects = []
    state.effect_order_policy = "ap_nap_player_choice"
    player = state.players["player_1"]
    player.member_area["center"] = None
    player.hand.append("source-live")
    source = state.cards["source-live"]
    source.card.effect_ids, source.card.cost = [EFFECT_ID], 0
    raw = state.effect_definitions[EFFECT_ID].model_dump(mode="json")
    raw.update(effect_id="CONTROL", trigger="own_member_played", choice=None,
               execution_mode="manual_resolution", simulation_support="manual_resolution",
               actions=[{"action_type": "manual_resolution"}])
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    observer = source.model_copy(deep=True)
    observer.instance_id, observer.card.effect_ids = "observer", ["CONTROL"]
    state.cards["observer"] = observer
    player.member_area["left"] = "observer"
    if owner == "player_2":
        swapped = {"player_1": "player_2", "player_2": "player_1"}
        state.players = {swapped[key]: value for key, value in state.players.items()}
        for key, value in state.players.items():
            value.player_id = key
        for card in state.cards.values():
            card.owner_id = swapped[card.owner_id]
        state.active_player_id, state.phase = owner, "second_main"
    return state


def _native_departure(repo, state, zone, *, resolve=True):
    owner = state.active_player_id
    state = repo.apply(state.match_id, _action(state, "play_member", owner,
        card_instance_id="source-live", slot="center", energy_instance_ids=[])).state
    assert {i.effect_id for i in state.pending_effects} == {EFFECT_ID, "CONTROL"}
    control = next(i for i in state.pending_effects if i.effect_id == "CONTROL")
    move = _manual(state, [{"adjustment_type": "move_card", "target_player_id": owner,
        "target_card_instance_id": "source-live", "to_zone": zone}], control)
    move.player_id = owner
    state = repo.apply(state.match_id, move).state
    if not resolve:
        return state
    invocation = next(i for i in state.pending_effects if i.effect_id == EFFECT_ID)
    return repo.apply(state.match_id, _action(state, "resolve_effect", owner,
        invocation_id=invocation.invocation_id)).state


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("zone", ["hand", "main_deck", "waiting_room"])
def test_native_source_departure_sql_replay_and_both_action_copies(tmp_path, legacy, owner, zone):
    state = _native_initial(legacy=legacy, owner=owner)
    repo = MatchRepository(tmp_path / "native.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    state = _native_departure(repo, state, zone)
    state = repo.apply(state.match_id, _select(state)).state
    before = match_state_hash(state)
    viewer = "player_2" if owner == "player_1" else "player_1"
    payload = _view(state, viewer, repo.list_events(state.match_id))
    assert ("source-live" in payload["state"]["cards"]) is (zone == "waiting_room")
    if zone != "waiting_room":
        assert "source-live" not in json.dumps(payload)
        assert {a["action_type"] for a in payload["legal_actions"]} >= {"resolve_effect_choice", "skip_effect"}
    assert match_state_hash(repo.get_state(state.match_id)) == before
    final = repo.apply(state.match_id, _select(state)).state
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == final.model_dump(mode="json")


@pytest.mark.parametrize("kind", KINDS)
def test_hidden_source_id_renaming_does_not_change_any_player_response(kind):
    state = _choice_state(kind, "player_1", "hand")
    raw = state.model_dump_json().replace('"source-live"', '"unrelated-secret-instance"')
    changed = type(state).model_validate_json(raw)
    assert _view(state, "player_2") == _view(changed, "player_2")
    for build in (build_api_play_context, build_agent_context):
        assert build(state, generate_legal_actions(state)) == build(changed, generate_legal_actions(changed))


@pytest.mark.parametrize("action_type", ["resolve_effect_choice", "skip_effect"])
def test_nested_non_candidate_references_cannot_grant_visibility(action_type):
    state = _choice_state(KINDS[0], "player_1", "main_deck")
    action = next(a.model_copy(deep=True) for a in generate_legal_actions(state) if a.action_type == action_type)
    action.options["diagnostics"] = {"source-live": ["source-live"]}
    before = action.model_dump()
    payload = _match_state_payload(state, events=[], legal_actions=[action], player_id="player_2")
    assert "source-live" not in json.dumps(payload)
    assert "source-live" not in build_ai_observation(state, "player_2", [action]).cards
    assert action.model_dump() == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_own_pending_manual_source_handle_survives_without_card_map_permission(tmp_path, owner):
    state = _native_initial(owner=owner)
    raw = state.effect_definitions[EFFECT_ID].model_dump(mode="json")
    raw.update(execution_mode="manual_resolution", simulation_support="manual_resolution",
               choice=None, actions=[{"action_type": "manual_resolution"}])
    state.effect_definitions[EFFECT_ID] = EffectDefinition.model_validate(raw)
    repo = MatchRepository(tmp_path / "manual.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    state = _native_departure(repo, state, "main_deck", resolve=False)
    opponent = "player_2" if owner == "player_1" else "player_1"
    payload = _view(state, owner)
    assert "source-live" not in payload["state"]["cards"]
    action = next(a for a in payload["legal_actions"] if a["action_type"] == "manual_adjustment")
    invocation = action["options"]["source_invocations"][0]
    assert invocation["source_card_instance_id"] == "source-live"
    context = build_agent_context(state, generate_legal_actions(state))
    assert context["manual_invocation"]["source_card_instance_id"] == "source-live"
    assert context["source_card"] is None
    assert "source-live" not in json.dumps(_view(state, opponent))
    submitted = _action(state, "manual_adjustment", owner,
        source_invocation_id=invocation["invocation_id"], source_effect_id=invocation["effect_id"],
        source_card_instance_id=invocation["source_card_instance_id"],
        adjustments=[{"adjustment_type": "set_flag", "target_player_id": owner,
                      "flag": "privacy-audit", "duration": "turn"}])
    final = repo.apply(state.match_id, submitted).state
    assert not final.pending_effects
    assert repo.replay(state.match_id)["final_state"] == final.model_dump(mode="json")


@pytest.mark.parametrize("change", [{"invocation_id": "forged"}, {"effect_id": "forged"}, {"invocation_id": []}])
def test_manual_handle_exception_requires_the_actual_owner_invocation(change):
    state = _native_initial()
    raw = state.effect_definitions[EFFECT_ID].model_dump(mode="json")
    raw.update(execution_mode="manual_resolution", simulation_support="manual_resolution",
               choice=None, actions=[{"action_type": "manual_resolution"}])
    state.effect_definitions[EFFECT_ID] = EffectDefinition.model_validate(raw)
    state.pending_effects = [EffectInvocation(invocation_id="real", effect_id=EFFECT_ID,
        source_card_instance_id="source-live", player_id="player_1", trigger_event="member_played")]
    value = {"invocation_id": "real", "effect_id": EFFECT_ID, "source_card_instance_id": "source-live", **change}
    result = redact_hidden_references(value, {"source-live"}, source_handles=owner_manual_source_handles(state, "player_1"))
    assert result["source_card_instance_id"] == "__hidden__"
    assert not owner_manual_source_handles(state, "player_2")


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("kind", KINDS)
def test_ai_and_provider_ignore_hidden_source_identity_without_mutation(policy, kind):
    state = _choice_state(kind, "player_1", "hand")
    actions = generate_legal_actions(state)
    changed = state.model_copy(deep=True)
    changed.cards["source-live"].card.name_ja = "SECRET-CHANGED"
    changed.cards["source-live"].card.card_code = "SECRET-CHANGED"
    changed.cards["source-live"].card.blade = 99
    before = match_state_hash(state)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    first = controller.choose_action(state, actions, controlled_player_ids={"player_2"})
    second = controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_2"})
    assert isinstance(first, SimpleAIDecision) and isinstance(second, SimpleAIDecision)
    assert first == second
    assert build_ai_observation(state, "player_2", actions) == build_ai_observation(changed, "player_2", actions)
    for build in (build_api_play_context, build_agent_context):
        assert build(state, actions) == build(changed, actions)
    assert _view(state, "player_2") == _view(changed, "player_2")
    assert match_state_hash(state) == before


def test_room_action_rest_reconnect_sse_and_raw_replay_preserve_boundary(tmp_path):
    client = _client(tmp_path)
    host, guest = _room(client)
    state = _native_initial()
    state.match_id = guest["match_id"]
    repo = client.app.state.match_service.repository
    with sqlite3.connect(tmp_path / "matches.sqlite3") as connection:
        for column in ("initial_state_json", "current_state_json"):
            connection.execute(f"UPDATE matches SET {column}=? WHERE match_id=?",
                               (state.model_dump_json(), state.match_id))
        connection.execute("DELETE FROM match_actions WHERE match_id=?", (state.match_id,))
        connection.execute("DELETE FROM match_events WHERE match_id=?", (state.match_id,))
        connection.execute("DELETE FROM match_snapshots WHERE match_id=?", (state.match_id,))
    state = _native_departure(repo, state, "hand")
    response = client.post(f"/api/rooms/{host['room_code']}/actions", json={
        "player_token": host["player_token"], "action": _select(state).model_dump(mode="json")})
    assert response.status_code == 200
    assert "source-live" in response.json()["state"]["cards"]
    url = f"/api/rooms/{host['room_code']}"
    for _ in range(2):
        payload = client.get(url, params={"player_token": guest["player_token"]}).json()["match"]
        assert "source-live" not in json.dumps(payload)
        assert payload["state"]["pending_choice"]["player_id"] == "player_2"
    signal = client.get(url + "/stream", params={"player_token": guest["player_token"], "once": True})
    assert signal.status_code == 200 and "source-live" not in signal.text
    current = repo.get_state(state.match_id)
    final = client.post(url + "/actions", json={"player_token": guest["player_token"],
        "action": _select(current).model_dump(mode="json")})
    assert final.status_code == 200
    assert repo.replay(state.match_id)["final_state"] == repo.get_state(state.match_id).model_dump(mode="json")
