import hashlib
import json
from pathlib import Path

import pytest

from loveca.simulation.ai import SimpleAIController, SimpleAIPolicy
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, ManualModifier, MatchState
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload
from tools.ai_sandbox.live_judgment_audit import _build_state, _live_instance, judgment_action

FIELD = "victory_check_policy"
POLICY = "before_end_expiry_v1"
PDF_HASH = "c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485"
LEGACY_HASHES = {
    "player_1": ("7e04fa35fcacdd42574768221e76568b1858b0238806654a968407dcf2d227cb",
                 "5951e23275cf89cb228543e1b8f9a7bf84ba4fd302d8dd755707397047718f80"),
    "player_2": ("0f306ca40c5eb0e7ae66d5426c559c8cf0fcab2769568841e7b4b5933a30b9fb",
                 "4db08a54da4edd677938130807cfaa092450220f21d0ca412afe8f39a7974e19"),
}


def _state(owner="player_1", *, modern=True, terminal=True, choice=False):
    first = owner == "player_1"
    state = _build_state(first_live_score=2 if first else None,
                         second_live_score=None if first else 2,
                         first_success_count=2 if terminal and first else 0,
                         second_success_count=2 if terminal and not first else 0,
                         first_effect=None)
    state.match_id = "terminal-timing-" + owner
    if choice:
        state.cards["extra-live"] = _live_instance("extra-live", owner, 1)
        state.players[owner].live_area.append("extra-live")
    for player_id, player in state.players.items():
        player.manual_modifiers = [ManualModifier(
            modifier_id=player_id + duration, modifier_type="flag", duration=duration,
            created_turn=state.turn_number, flag="audit_duration_marker", value=True,
        ) for duration in ("live", "turn", "game")]
        hidden = player_id + "-hidden"
        state.cards[hidden] = _live_instance(hidden, player_id, 0)
        player.hand.append(hidden)
    raw = state.model_dump()
    if modern:
        raw[FIELD] = POLICY
    return MatchState.model_validate(raw)


def _durations(state):
    return {p: [m.duration for m in player.manual_modifiers] for p, player in state.players.items()}


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_prechange_legacy_state_and_event_hashes(owner):
    state = _state(owner, modern=False)
    result = apply_action(state, judgment_action(state))
    events_hash = hashlib.sha256(json.dumps([e.model_dump() for e in result.events],
                                            ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    assert (match_state_hash(result.state), events_hash) == LEGACY_HASHES[owner]


@pytest.mark.parametrize("modern", [False, True])
def test_constructed_simultaneous_threshold_draw_sql(tmp_path, modern):
    state = _state(modern=modern)
    for owner, player in state.players.items():
        for index in range(len(player.success_live_area), 3):
            key = owner + "-preexisting-success-" + str(index)
            state.cards[key] = _live_instance(key, owner, 1)
            player.success_live_area.append(key)
        player.live_area.clear()
        player.live_result.requirements_satisfied = False
    # This is a check-timing snapshot, not proof of a naturally reachable tied Live.
    for key in list(state.cards):
        if key.endswith("-current-live"):
            state.players[state.cards[key].owner_id].waiting_room.append(key)
    repo = MatchRepository(tmp_path / "draw.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repo.apply(state.match_id, judgment_action(state))
    assert result.state.game_result.outcome == "draw"
    assert result.state.game_result.winner_player_ids == [] and not result.legal_actions
    assert all(v == (["live", "turn", "game"] if modern else ["turn", "game"])
               for v in _durations(result.state).values())
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump()


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_nonterminal_behavior_identical_except_explicit_policy(owner):
    old = _state(owner, modern=False, terminal=False)
    new = _state(owner, modern=True, terminal=False)
    old_result = apply_action(old, judgment_action(old))
    new_result = apply_action(new, judgment_action(new))
    new_raw = new_result.state.model_dump()
    assert new_raw.pop(FIELD) == POLICY
    assert new_raw == old_result.state.model_dump()
    assert new_result.events == old_result.events
    assert new_result.legal_actions == old_result.legal_actions


@pytest.mark.parametrize("value", [True, 1, {}, "unknown"])
def test_unknown_policy_rejected(value):
    raw = _state(modern=False).model_dump()
    raw[FIELD] = value
    with pytest.raises(ValueError):
        MatchState.model_validate(raw)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("modern", [False, True])
@pytest.mark.parametrize("terminal", [False, True])
@pytest.mark.parametrize("choice", [False, True])
def test_native_judgment_and_sql_preserve_timing(tmp_path, owner, modern, terminal, choice):
    assert hashlib.sha256(Path("raw_doc/LoveLiveTCG_cr_1.06_260428.pdf").read_bytes()).hexdigest() == PDF_HASH
    initial = _state(owner, modern=modern, terminal=terminal, choice=choice)
    before = match_state_hash(initial)
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(initial, card_database_path=Path("data/loveca.sqlite3"))
    result = repo.apply(initial.match_id, judgment_action(initial))
    if choice:
        assert result.state.pending_choice.choice_type == "success_live"
        assert _durations(result.state) == _durations(initial)
        assert result.state.game_result is None
        result = repo.apply(initial.match_id, ActionRequest(action_type="resolve_live_requirements",
            player_id=owner, expected_revision=result.state.revision,
            payload={"success_live_instance_id": "extra-live"}))
    expected = ["live", "turn", "game"] if modern and terminal else ["turn", "game"]
    assert all(v == expected for v in _durations(result.state).values())
    assert result.state.phase == ("complete" if terminal else "turn_complete")
    assert (FIELD in result.state.model_dump()) is modern
    assert all(not p.live_area and not p.resolution_area for p in result.state.players.values())
    expired = [e for e in result.events if e.event_type == "manual_modifiers_expired"]
    assert bool(expired) is not (modern and terminal)
    if terminal:
        assert result.state.game_result.winner_player_ids == [owner]
        assert result.legal_actions == []
        frozen = match_state_hash(result.state)
        with pytest.raises(IllegalActionError, match="match is complete"):
            repo.apply(initial.match_id, ActionRequest(action_type="start_next_turn",
                                                       expected_revision=result.state.revision))
        assert match_state_hash(repo.get_state(initial.match_id)) == frozen
    else:
        result = repo.apply(initial.match_id, ActionRequest(action_type="start_next_turn",
                                                           expected_revision=result.state.revision))
        assert all(v == ["game"] for v in _durations(result.state).values())
    replay = repo.replay(initial.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump()
    assert match_state_hash(initial) == before


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("viewer", ["player_1", "player_2"])
def test_terminal_ai_and_player_projection_do_not_expose_hidden_cards(policy, viewer):
    result = apply_action(_state(), judgment_action(_state()))
    before = match_state_hash(result.state)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    assert controller.choose_action(result.state, result.legal_actions, controlled_player_ids={viewer}) is None
    payload = _match_state_payload(result.state, events=result.events,
                                  legal_actions=result.legal_actions, player_id=viewer)
    opponent = "player_2" if viewer == "player_1" else "player_1"
    assert opponent + "-hidden" not in payload["state"]["cards"]
    changed = result.state.model_copy(deep=True)
    card = changed.cards.pop(opponent + "-hidden")
    card.instance_id = "redacted-other"
    card.card.card_code = card.card.name_ja = "REDACTED"
    changed.cards[card.instance_id] = card
    changed.players[opponent].hand = [card.instance_id]
    changed_before = match_state_hash(changed)
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={viewer}) is None
    assert match_state_hash(result.state) == before and match_state_hash(changed) == changed_before


@pytest.mark.parametrize("hosted", [False, True])
def test_new_local_and_room_match_enable_policy(tmp_path, hosted):
    from test_webapp import SAMPLE_DECK, _client

    client = _client(tmp_path)
    deck = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))
    if hosted:
        created = client.post("/api/rooms", json={"player_name": "A", "deck": deck, "seed": 1})
        assert created.status_code == 200
        response = client.post(f"/api/rooms/{created.json()['room_code']}/join",
                               json={"player_name": "B", "deck": deck})
        assert response.status_code == 200
        raw = response.json()["match"]["state"]
    else:
        response = client.post("/api/matches", json={"player_1": {"name": "A", "deck": deck},
                                                    "player_2": {"name": "B", "deck": deck}, "seed": 1})
        assert response.status_code == 200
        raw = response.json()["state"]
    assert raw[FIELD] == POLICY
    raw[FIELD] = "unknown"
    with pytest.raises(ValueError):
        MatchState.model_validate(raw)
