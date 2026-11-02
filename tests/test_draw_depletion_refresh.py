import hashlib
import json
from pathlib import Path

import pytest

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.engine import apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, MatchState, PlayerState
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload
from tools.ai_sandbox.live_judgment_audit import _live_instance

FIELD = "draw_refresh_policy"
POLICY = "after_each_draw_v1"
PDF_HASH = "c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485"
LEGACY_HASHES = {
    "player_1": ("3957db54a57a611fc0621fa28cd6b543e8f4f3bccb33f17419b2d0bd1e1c7797",
                 "bbfc51ed2e67a768d5db7f6b16cd46c9043a6bc58828b0bf2360c496496ed055"),
    "player_2": ("e6660217bb1c0473f37b41fcb0fe078751b96de50724ce3d292b4ddcc8d5dd8a",
                 "8a7249e24f0fd40df7bade5051b43c21af27f7567d68eb946286a1ee50411c73"),
}


def _state(owner="player_1", *, modern=True, waiting=3, count=1, live_set=False):
    players = {key: PlayerState(player_id=key, name=key) for key in ("player_1", "player_2")}
    cards = {}
    for key, player in players.items():
        for zone, amount in (("main_deck", count), ("waiting_room", waiting), ("hand", 3)):
            for index in range(amount):
                item = f"{key}-{zone}-{index}"
                cards[item] = _live_instance(item, key, 0)
                cards[item].face_up = zone != "main_deck"
                getattr(player, zone).append(item)
    phase = ("live_set_first" if owner == "player_1" else "live_set_second") if live_set else (
        "first_draw" if owner == "player_1" else "second_draw")
    raw = MatchState(match_id="draw-depletion-" + owner, seed=808, phase=phase,
                     first_player_id="player_1", second_player_id="player_2",
                     active_player_id=owner, players=players, cards=cards).model_dump()
    if modern:
        raw[FIELD] = POLICY
    return MatchState.model_validate(raw)


def _action(state, *, live_set=False):
    owner = state.active_player_id
    return ActionRequest(action_type="set_live_cards" if live_set else "advance_phase",
                         expected_revision=state.revision, player_id=owner,
                         payload={"card_instance_ids": state.players[owner].hand[:3]} if live_set else {})


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_last_draw_refreshes_without_waiting_for_another_draw(owner):
    # CR 1.06 10.2.1/10.2.2.1: refresh immediately, even midway through a process.
    assert hashlib.sha256(Path("raw_doc/LoveLiveTCG_cr_1.06_260428.pdf").read_bytes()).hexdigest() == PDF_HASH
    state = _state(owner)
    result = apply_action(state, _action(state))
    assert result.state.players[owner].refresh_count == 1
    assert not result.state.players[owner].waiting_room
    assert set(result.state.players[owner].main_deck) == set(state.players[owner].waiting_room)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_prechange_legacy_draw_state_and_event_hashes(owner):
    state = _state(owner, modern=False)
    result = apply_action(state, _action(state))
    event_hash = hashlib.sha256(json.dumps([e.model_dump() for e in result.events],
                                          ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    assert (match_state_hash(result.state), event_hash) == LEGACY_HASHES[owner]
    assert FIELD not in result.state.model_dump()


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("modern", [False, True])
@pytest.mark.parametrize("case", ["last", "empty_waiting", "both_empty", "not_empty", "cross_and_exhaust"])
def test_draw_refresh_sql_boundaries_and_private_projection(tmp_path, owner, modern, case):
    waiting = 0 if case in {"empty_waiting", "both_empty"} else (2 if case == "cross_and_exhaust" else 3)
    count = 0 if case == "both_empty" else (2 if case == "not_empty" else 1)
    live_set = case == "cross_and_exhaust"
    state = _state(owner, modern=modern, waiting=waiting, count=count, live_set=live_set)
    before = match_state_hash(state)
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repo.apply(state.match_id, _action(state, live_set=live_set))
    player = result.state.players[owner]
    expected_refresh = 1 if live_set or (modern and case == "last") else 0
    assert player.refresh_count == expected_refresh
    assert player.refreshed_this_turn is bool(expected_refresh)
    refreshed = [e for e in result.events if e.event_type == "deck_refreshed"]
    assert len(refreshed) == expected_refresh
    drawn = [item for e in result.events if e.event_type == "cards_drawn" for item in e.data["instance_ids"]]
    assert len(drawn) == (3 if live_set else (0 if case == "both_empty" else 1))
    if count:
        assert drawn[0] == state.players[owner].main_deck[0]
    if expected_refresh:
        assert not player.waiting_room
        assert set(refreshed[0].data["instance_ids"]) == set(state.players[owner].waiting_room)
        assert all(not result.state.cards[item].face_up for item in player.main_deck)
        assert set(drawn + player.main_deck) == set(state.players[owner].main_deck + state.players[owner].waiting_room)
    else:
        assert player.waiting_room == state.players[owner].waiting_room
        assert player.main_deck == state.players[owner].main_deck[len(drawn):]
    assert set(drawn) <= set(player.hand)
    other = next(key for key in state.players if key != owner)
    assert result.state.players[other].model_dump() == state.players[other].model_dump()
    assert result.state.phase == (("live_set_second" if owner == "player_1" else "performance_first")
                                  if live_set else ("first_main" if owner == "player_1" else "second_main"))
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump()
    for viewer in state.players:
        opponent = next(key for key in state.players if key != viewer)
        hidden = (result.state.players[opponent].hand + result.state.players[opponent].main_deck
                  + result.state.players[opponent].live_area + result.state.players[viewer].main_deck)
        payload = _match_state_payload(result.state, events=result.events,
                                       legal_actions=result.legal_actions, player_id=viewer)
        encoded = json.dumps(payload)
        assert all(json.dumps(item) not in encoded for item in hidden)
        assert all(item in payload["state"]["cards"] for item in result.state.players[viewer].hand)
        assert all(item in payload["state"]["cards"] for p in result.state.players.values() for item in p.waiting_room)
    assert match_state_hash(state) == before
    assert repo.get_state(state.match_id).model_dump() == result.state.model_dump()


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_policies_execute_refresh_without_hidden_information(tmp_path, owner, policy):
    state = _state(owner)
    before = match_state_hash(state)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    assert decision.action.action_type == "advance_phase"
    altered = state.model_copy(deep=True)
    other = next(key for key in state.players if key != owner)
    for item in altered.players[other].hand + altered.players[other].main_deck:
        altered.cards[item].card = altered.cards[item].card.model_copy(update={"name_ja": "UNSEEN", "score": 999})
    altered_before = match_state_hash(altered)
    alternative = controller.choose_action(altered, generate_legal_actions(altered), controlled_player_ids={owner})
    assert isinstance(alternative, SimpleAIDecision)
    assert alternative.action.model_dump() == decision.action.model_dump()
    assert match_state_hash(altered) == altered_before and match_state_hash(state) == before
    repo = MatchRepository(tmp_path / "ai.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repo.apply(state.match_id, decision.action)
    assert result.state.players[owner].refresh_count == 1
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump()


@pytest.mark.parametrize("value", [True, 1, {}, "unknown"])
def test_unknown_draw_refresh_policy_rejected(value):
    raw = _state(modern=False).model_dump()
    raw[FIELD] = value
    with pytest.raises(ValueError):
        MatchState.model_validate(raw)


@pytest.mark.parametrize("hosted", [False, True])
def test_new_local_and_room_match_enable_draw_refresh(tmp_path, hosted):
    from test_webapp import SAMPLE_DECK, _client

    client = _client(tmp_path)
    deck = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))
    if hosted:
        room = client.post("/api/rooms", json={"player_name": "A", "deck": deck, "seed": 1})
        assert room.status_code == 200
        response = client.post(f"/api/rooms/{room.json()['room_code']}/join", json={"player_name": "B", "deck": deck})
        assert response.status_code == 200
        raw = response.json()["match"]["state"]
    else:
        response = client.post("/api/matches", json={"player_1": {"name": "A", "deck": deck},
                                                    "player_2": {"name": "B", "deck": deck}, "seed": 1})
        assert response.status_code == 200
        raw = response.json()["state"]
    assert raw[FIELD] == POLICY
