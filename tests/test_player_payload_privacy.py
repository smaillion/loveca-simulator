import json
import sqlite3

import pytest
from test_activated_inspection import _activate, _finish, _state
from test_webapp import SAMPLE_DECK, _client

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import apply_action, generate_legal_actions
from loveca.simulation.models import GameEvent, PendingChoice
from loveca.simulation.online import match_state_hash
from loveca.webapp import _match_state_payload

RULE_REFERENCE_IDS = ("4.1.2.2", "4.1.5.1", "4.8.2", "4.9.2", "4.11.2", "5.7.1")


def _view(state, viewer="player_2", events=None):
    return _match_state_payload(
        state, events=events or [], legal_actions=generate_legal_actions(state), player_id=viewer
    )


@pytest.mark.parametrize("viewer", ["player_1", "player_2"])
def test_hidden_piles_only_expose_counts_and_no_card_or_skill_identity(viewer):
    state = _state()
    before = match_state_hash(state)
    secret = state.cards["top-0"]
    secret.card.name_ja = "PRIVATE-DECK-NAME"
    secret.card.card_code = "PRIVATE-DECK-CODE"
    secret.card.effect_ids = ["PRIVATE-DECK-CODE:1"]
    state.effect_definitions["PRIVATE-DECK-CODE:1"] = EffectDefinition.model_validate(
        {
            **next(iter(state.effect_definitions.values())).model_dump(),
            "effect_id": "PRIVATE-DECK-CODE:1",
            "card_code": "PRIVATE-DECK-CODE",
        }
    )
    before = match_state_hash(state)
    payload = _view(state, viewer)
    assert "PRIVATE-DECK" not in json.dumps(payload, ensure_ascii=False)
    for player_id, player in state.players.items():
        for zone in ("main_deck", "energy_deck"):
            ids = payload["state"]["players"][player_id][zone]
            assert len(ids) == len(getattr(player, zone))
            assert set(ids).isdisjoint(state.cards)
    assert payload["state"]["seed"] == 0
    assert match_state_hash(state) == before


@pytest.mark.parametrize("viewer", ["player_1", "player_2"])
def test_unknown_card_replacement_and_private_order_do_not_change_player_response(viewer):
    state = _state()
    before = _view(state, viewer)
    changed = state.model_copy(deep=True)
    changed.seed = 987654
    changed.players["player_1"].main_deck.reverse()
    for key in changed.players["player_1"].main_deck:
        changed.cards[key].card.name_ja = "NEW-UNKNOWN"
        changed.cards[key].card.card_code = "NEW-UNKNOWN-CODE"
    opponent = "player_2" if viewer == "player_1" else "player_1"
    for key in changed.players[opponent].hand:
        changed.cards[key].card.name_ja = "NEW-SECRET-HAND"
        changed.cards[key].card.effect_ids = []
    assert _view(changed, viewer) == before


def test_private_mulligan_and_opponent_hand_ids_cannot_link_history():
    state = _state()
    state.pending_choice = PendingChoice(
        choice_type="mulligan",
        player_id="player_1",
        options={"hand_instance_ids": ["held"]},
        message_ja="引き直し",
        message_zh="换牌",
    )
    event = GameEvent(
        event_type="cards_drawn", player_id="player_1", data={"instance_ids": ["held"]}
    )
    payload = _view(state, events=[event])
    assert payload["state"]["pending_choice"]["options"] == {}
    assert payload["state"]["players"]["player_1"]["hand"] == ["__hidden__/player_1/hand/0"]
    assert payload["events"][0]["data"]["instance_ids"] == ["__hidden__"]
    assert "held" not in json.dumps(payload)


@pytest.mark.parametrize("kind", ["manual_card_selection", "multi_player_effect_selection"])
def test_other_players_pending_choice_never_exposes_private_candidates(kind):
    state = _state()
    state.pending_choice = PendingChoice(
        choice_type=kind,
        player_id="player_1",
        options={"candidate_card_instance_ids": ["held"]},
        message_ja="選択",
        message_zh="选择",
    )
    assert _view(state)["state"]["pending_choice"]["options"] == {}
    assert _view(state, "player_1")["state"]["pending_choice"]["options"][
        "candidate_card_instance_ids"
    ] == ["held"]


@pytest.mark.parametrize("kind", ["effect_inspection_started", "manual_card_inspection_started"])
def test_private_inspection_history_hides_candidates_and_matching_counts(kind):
    state = _state()
    event = GameEvent(
        event_type=kind,
        player_id="player_1",
        data={
            "inspected_card_instance_ids": ["held"],
            "candidate_card_instance_ids": ["held"],
            "minimum": 1,
            "maximum": 1,
        },
    )
    data = _view(state, events=[event])["events"][0]["data"]
    assert not any(
        key in data
        for key in (
            "inspected_card_instance_ids",
            "candidate_card_instance_ids",
            "minimum",
            "maximum",
        )
    )
    assert event.data["minimum"] == 1


def test_public_reveal_is_not_a_permanent_card_map_permission():
    state = _state()
    event = GameEvent(
        event_type="effect_resolved",
        player_id="player_1",
        data={
            "reveal_selected_to_opponent": True,
            "revealed_cards": [{"instance_id": "top-0", "name_ja": "PREVIOUSLY-PUBLIC"}],
        },
    )
    payload = _view(state, events=[event])
    assert "top-0" not in payload["state"]["cards"]
    assert "top-0" not in payload["state"]["players"]["player_1"]["main_deck"]
    assert payload["events"][0]["data"]["revealed_cards"][0]["name_ja"] == "PREVIOUSLY-PUBLIC"


def test_face_up_live_and_attachments_stay_public_but_unzoned_cards_do_not():
    state = _state()
    player = state.players["player_1"]
    first, second = player.main_deck[:2]
    player.main_deck = player.main_deck[2:]
    player.live_area = [first]
    state.cards[first].face_up = True
    player.member_area_attachments["center"] = [second]
    state.cards["unused"] = state.cards[first].model_copy(
        update={"instance_id": "unused"}, deep=True
    )
    payload = _view(state)
    assert first in payload["state"]["cards"] and second in payload["state"]["cards"]
    assert payload["state"]["players"]["player_1"]["live_area"] == [first]
    assert "unused" not in payload["state"]["cards"]


def test_nested_private_debug_metadata_is_filtered_without_changing_history():
    state = _state()
    event = GameEvent(
        event_type="manual_adjustment_applied",
        player_id="player_1",
        data={
            "adjustments": [{"target_card_instance_id": "top-0", "details": {"top-1": ["top-2"]}}],
        },
    )
    before = event.model_dump()
    payload = _view(state, events=[event])
    assert not any(key in json.dumps(payload["events"]) for key in ("top-0", "top-1", "top-2"))
    assert event.model_dump() == before


def test_other_players_ai_blocker_does_not_reveal_private_action_payload():
    state = _state()
    event = GameEvent(
        event_type="ai_blocked",
        player_id="player_1",
        data={
            "reason": "ai_illegal_action",
            "action_payload": {"secret": "PRIVATE"},
            "pending_choice": {"private": "PRIVATE"},
            "error": "PRIVATE",
            "decision_reason": "PRIVATE",
        },
    )
    assert "PRIVATE" not in json.dumps(_view(state, events=[event]))
    assert "PRIVATE" in json.dumps(_view(state, "player_1", events=[event]))


def test_public_zones_and_explicit_reveal_remain_visible():
    state = _state()
    player = state.players["player_1"]
    key = player.main_deck.pop()
    player.waiting_room.append(key)
    event = GameEvent(
        event_type="effect_resolved",
        player_id="player_1",
        data={
            "inspected_card_instance_ids": ["held", key],
            "selected_card_instance_ids": ["held"],
            "reveal_selected_to_opponent": True,
            "revealed_cards": [{"instance_id": "held", "name_ja": "PUBLIC-REVEAL"}],
        },
    )
    payload = _view(state, events=[event])
    assert key in payload["state"]["cards"]
    assert "source-live" in payload["state"]["cards"]
    assert "energy-0" in payload["state"]["cards"]
    assert "held" not in payload["state"]["cards"]
    assert payload["events"][0]["data"]["revealed_cards"] == event.data["revealed_cards"]


def test_full_local_view_keeps_both_hands_and_runtime_seed_without_mutation():
    state = _state()
    event = GameEvent(
        event_type="cards_drawn", player_id="player_1", data={"instance_ids": ["held"]}
    )
    payload = _view(state, None, [event])
    assert payload["state"] == state.model_dump()
    assert payload["events"] == [event.model_dump()]
    for viewer, key in (("player_1", "held"), ("player_2", "opponent-secret")):
        assert key in _view(state, viewer)["state"]["cards"]


def test_real_inspection_and_reordered_history_do_not_expose_opponent_deck_order():
    state = _state()
    activated = apply_action(state, _activate(state))
    inspected = activated.state.pending_choice.options["inspected_card_instance_ids"]
    assert all(key in _view(activated.state, "player_1")["state"]["cards"] for key in inspected)
    first = apply_action(activated.state, _finish(activated.state, inspected))
    second = apply_action(activated.state, _finish(activated.state, list(reversed(inspected))))
    events_first, events_second = activated.events + first.events, activated.events + second.events
    assert _view(first.state, events=events_first) == _view(second.state, events=events_second)
    assert first.state.players["player_1"].main_deck != second.state.players["player_1"].main_deck


@pytest.mark.parametrize(
    "policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"]
)
def test_ai_decision_ignores_opponent_identity_and_own_hidden_order(policy):
    state = _state()
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    legal = generate_legal_actions(state)
    first = controller.choose_action(state, legal, controlled_player_ids={"player_1"})
    changed = state.model_copy(deep=True)
    changed.players["player_1"].main_deck.reverse()
    changed.cards["opponent-secret"].card.name_ja = "UNKNOWN-OPPONENT"
    changed.cards["opponent-secret"].card.card_code = "UNKNOWN-OPPONENT"
    second = controller.choose_action(
        changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}
    )
    assert isinstance(first, SimpleAIDecision) and isinstance(second, SimpleAIDecision)
    assert first.action == second.action
    assert first.reason == second.reason


def _room(client):
    deck = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))
    host = client.post("/api/rooms", json={"player_name": "Host", "deck": deck, "seed": 123}).json()
    guest = client.post(
        f"/api/rooms/{host['room_code']}/join", json={"player_name": "Guest", "deck": deck}
    ).json()
    return host, guest


def test_room_rest_actions_stream_reconnect_and_replay_use_same_privacy_boundary(tmp_path):
    client = _client(tmp_path)
    host, guest = _room(client)
    code = host["room_code"]
    match_id = guest["match_id"]
    repo = client.app.state.match_service.repository
    raw = repo.get_state(match_id)
    before = match_state_hash(raw)
    with sqlite3.connect(tmp_path / "matches.sqlite3") as connection:
        schema = connection.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    for token in (host["player_token"], guest["player_token"]):
        url = f"/api/rooms/{code}?player_token={token}"
        payload = client.get(url).json()["match"]
        assert client.get(url).json()["match"] == payload
        assert payload["state"]["seed"] == 0
        for player_id, player in raw.players.items():
            assert len(payload["state"]["players"][player_id]["main_deck"]) == len(player.main_deck)
            assert set(player.main_deck).isdisjoint(payload["state"]["cards"])
            assert set(player.energy_deck).isdisjoint(payload["state"]["cards"])
        streamed = client.get(
            f"/api/rooms/{code}/stream", params={"player_token": token, "once": True}
        )
        assert streamed.status_code == 200
        signal = json.loads(
            next(line[6:] for line in streamed.text.splitlines() if line.startswith("data: "))
        )
        assert set(signal) == {
            "room_code",
            "status",
            "player_id",
            "match_id",
            "revision",
            "closed_at",
            "close_reason",
        }
        assert (
            client.get(f"/api/rooms/{code}/replay", params={"player_token": token}).status_code
            == 409
        )
    assert match_state_hash(repo.get_state(match_id)) == before
    actor = raw.active_player_id
    token = host["player_token"] if actor == "player_1" else guest["player_token"]
    placeholder = f"__hidden__/{actor}/main_deck/0"
    rejected = client.post(
        f"/api/rooms/{code}/actions",
        json={
            "player_token": token,
            "action": {
                "action_type": "submit_mulligan",
                "player_id": actor,
                "expected_revision": raw.revision,
                "payload": {"card_instance_ids": [placeholder]},
            },
        },
    )
    assert rejected.status_code == 409
    assert match_state_hash(repo.get_state(match_id)) == before
    acted = client.post(
        f"/api/rooms/{code}/actions",
        json={
            "player_token": token,
            "action": {
                "action_type": "submit_mulligan",
                "player_id": actor,
                "expected_revision": raw.revision,
                "payload": {"card_instance_ids": []},
            },
        },
    )
    assert acted.status_code == 200
    assert acted.json()["state"]["seed"] == 0
    after = repo.get_state(match_id)
    assert set(after.players[actor].main_deck).isdisjoint(acted.json()["state"]["cards"])
    assert repo.replay(match_id)["final_state"] == after.model_dump()
    client.post(f"/api/rooms/{code}/leave", json={"player_token": token})
    exported = client.get(f"/api/rooms/{code}/replay", params={"player_token": token})
    assert exported.status_code == 200
    assert exported.json()["final_state"] == after.model_dump()
    with sqlite3.connect(tmp_path / "matches.sqlite3") as connection:
        assert (
            connection.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall() == schema
        )


def test_complete_online_match_can_export_unmodified_replay(tmp_path):
    client = _client(tmp_path)
    host, guest = _room(client)
    repo = client.app.state.match_service.repository
    state = repo.get_state(guest["match_id"])
    state.phase = "complete"
    # A controlled completed fixture tests endpoint policy, not victory adjudication.
    with sqlite3.connect(tmp_path / "matches.sqlite3") as connection:
        for column in ("initial_state_json", "current_state_json"):
            connection.execute(
                f"UPDATE matches SET {column}=? WHERE match_id=?",
                (state.model_dump_json(), state.match_id),
            )
        connection.execute("DELETE FROM match_actions WHERE match_id=?", (state.match_id,))
    response = client.get(
        f"/api/rooms/{host['room_code']}/replay", params={"player_token": host["player_token"]}
    )
    assert response.status_code == 200
    assert response.json() == repo.replay(state.match_id)
    assert response.json()["final_state"]["seed"] == 123
