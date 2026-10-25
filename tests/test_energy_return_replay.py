import json
import sqlite3
from pathlib import Path

import pytest
from test_effect_execution import _minimal_effect_state

from loveca.simulation.effects import load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, CardDefinition, CardInstance, MatchState

ACTIVATED = "PL!SP-bp5-111:2"
BRANCH = "PL!SP-pb2-010:1"
RULE_REFERENCE_IDS = ("4.3.2", "4.7.3", "4.9.2", "9.6.2.3")


def _state(effect_id=ACTIVATED):
    effect = next(e for e in load_effect_registry().effects if e.effect_id == effect_id)
    state = _minimal_effect_state(effect)
    state.pending_effects = []
    state.phase = "first_main" if effect_id == ACTIVATED else "performance_first"
    player = state.players["player_1"]
    state.cards["source-live"].card = CardDefinition(
        card_code=effect.card_code,
        card_id=effect.card_code,
        name_ja=effect.card_code,
        card_type="member",
        cost=9,
        blade=1,
        basic_hearts={"heart01": 1},
        effect_ids=[effect_id],
        raw_effect_text_ja=effect.label_ja,
        text_revision_id=effect.text_revision_id,
        raw_text_hash=effect.raw_text_hash,
    )
    player.member_area["center"] = "source-live"
    if effect_id == ACTIVATED:
        player.live_area = []
        player.waiting_room = ["live-1"]
    for index in range(4):
        key = f"energy-{index}"
        state.cards[key] = CardInstance(
            instance_id=key,
            owner_id="player_1",
            card=CardDefinition(
                card_code="ENERGY", card_id="ENERGY", name_ja="エネルギー", card_type="energy"
            ),
            orientation="wait" if index == 1 else "active",
            face_up=index != 3,
        )
    player.energy_area = ["energy-0", "energy-1", "energy-2"]
    player.energy_deck = ["energy-3"]
    return state


def _action(state, action_type, **payload):
    return ActionRequest(
        action_type=action_type,
        player_id="player_1",
        expected_revision=state.revision,
        payload=payload,
    )


def _activate(state):
    return _action(
        state, "activate_effect", effect_id=ACTIVATED, source_card_instance_id="source-live"
    )


def _cost(state, ids=None):
    return _action(
        state,
        "resolve_effect",
        invocation_id=state.pending_effects[0].invocation_id,
        accepted=True,
        selected_card_instance_ids=ids or ["energy-0", "energy-1"],
    )


def _recover(state):
    return _action(
        state,
        "resolve_effect",
        invocation_id=state.pending_effects[0].invocation_id,
        accepted=True,
        selected_card_instance_ids=["live-1"],
    )


def test_actual_activated_energy_cost_and_live_recovery_are_serializable():
    initial = _state()
    state = apply_action(initial, _activate(initial)).state
    assert state.pending_effects[0].resolution_stage == "initial"
    result = apply_action(state, _cost(state))
    state = result.state
    assert state.players["player_1"].energy_area == ["energy-2"]
    assert state.players["player_1"].energy_deck == ["energy-3", "energy-0", "energy-1"]
    assert all(state.cards[i].face_up is False for i in ["energy-0", "energy-1"])
    assert state.pending_effects[0].resolution_stage == "after_cost"
    state = MatchState.model_validate_json(state.model_dump_json())
    result = apply_action(state, _recover(state))
    assert "live-1" in result.state.players["player_1"].hand
    assert "live-1" not in result.state.players["player_1"].waiting_room
    assert not result.state.pending_effects
    assert len([e for e in result.events if e.event_type == "effect_cost_paid"]) == 0
    assert result.state.players["player_1"].energy_area == ["energy-2"]
    assert MatchState.model_validate_json(result.state.model_dump_json()) == result.state
    assert (
        sum(
            result.state.cards[i].orientation == "active"
            for i in result.state.players["player_1"].energy_area
        )
        == 1
    )
    assert not any(
        ACTIVATED in str(a.options)
        for a in generate_legal_actions(result.state)
        if a.action_type == "activate_effect"
    )


@pytest.mark.parametrize("orientation", ["active", "wait"])
def test_real_live_start_trigger_return_energy_branch_round_trips(orientation):
    state = _state(BRANCH)
    state.cards["energy-0"].orientation = orientation
    started = apply_action(state, _action(state, "advance_phase"))
    state = started.state
    assert [e.effect_id for e in state.pending_effects] == [BRANCH]
    assert any(
        e.event_type == "effect_triggered" and e.data["effect_id"] == BRANCH for e in started.events
    )
    state = apply_action(
        state,
        _action(
            state,
            "resolve_effect",
            invocation_id=state.pending_effects[0].invocation_id,
            accepted=True,
            selected_branch="return_energy",
        ),
    ).state
    result = apply_action(
        state,
        _action(
            state,
            "resolve_effect",
            invocation_id=state.pending_effects[0].invocation_id,
            accepted=True,
            selected_branch="return_energy",
            selected_card_instance_ids=["energy-0"],
        ),
    )
    assert result.state.players["player_1"].energy_area == ["energy-1", "energy-2"]
    assert result.state.players["player_1"].energy_deck == ["energy-3", "energy-0"]
    assert result.state.cards["energy-0"].face_up is False
    assert MatchState.model_validate_json(result.state.model_dump_json()) == result.state


@pytest.mark.parametrize("effect_id", [ACTIVATED, BRANCH])
def test_actual_runtime_replay_survives_energy_return(tmp_path, effect_id):
    from loveca.simulation.runtime import MatchRepository

    state = _state(effect_id)
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    if effect_id == ACTIVATED:
        state = repository.apply(state.match_id, _activate(state)).state
        state = repository.apply(state.match_id, _cost(state)).state
        state = repository.get_state(state.match_id)
        result = repository.apply(state.match_id, _recover(state))
    else:
        state = repository.apply(state.match_id, _action(state, "advance_phase")).state
        state = repository.apply(
            state.match_id,
            _action(
                state,
                "resolve_effect",
                invocation_id=state.pending_effects[0].invocation_id,
                accepted=True,
                selected_branch="return_energy",
            ),
        ).state
        result = repository.apply(
            state.match_id,
            _action(
                state,
                "resolve_effect",
                invocation_id=state.pending_effects[0].invocation_id,
                accepted=True,
                selected_branch="return_energy",
                selected_card_instance_ids=["energy-0"],
            ),
        )
    replay = repository.replay(state.match_id)
    assert replay["final_state"] == result.state.model_dump(mode="json")
    assert json.loads(json.dumps(replay["final_state"])) == result.state.model_dump(mode="json")


def _branch_state(state, branch="return_energy"):
    state = apply_action(state, _action(state, "advance_phase")).state
    return apply_action(
        state,
        _action(
            state,
            "resolve_effect",
            invocation_id=state.pending_effects[0].invocation_id,
            accepted=True,
            selected_branch=branch,
        ),
    ).state


def test_discard_instead_branch_does_not_change_energy():
    state = _state(BRANCH)
    player = state.players["player_1"]
    player.main_deck.remove("deck-member-1")
    player.hand = ["deck-member-1"]
    state = _branch_state(state, "discard_hand")
    result = apply_action(
        state,
        _action(
            state,
            "resolve_effect",
            invocation_id=state.pending_effects[0].invocation_id,
            selected_branch="discard_hand",
            accepted=True,
            selected_card_instance_ids=["deck-member-1"],
        ),
    )
    assert result.state.players["player_1"].energy_area == ["energy-0", "energy-1", "energy-2"]
    assert result.state.players["player_1"].energy_deck == ["energy-3"]
    assert "deck-member-1" in result.state.players["player_1"].waiting_room
    assert result.state.cards["energy-1"].orientation == "wait"
    assert MatchState.model_validate_json(result.state.model_dump_json()) == result.state


@pytest.mark.parametrize(
    "ids",
    [["energy-0"], ["energy-0", "energy-0"], ["energy-0", "energy-3"], ["live-1", "energy-0"]],
)
def test_invalid_activated_cost_is_atomic(ids):
    state = _state()
    state = apply_action(state, _activate(state)).state
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalActionError):
        apply_action(state, _cost(state, ids))
    assert state.model_dump(mode="json") == before


def test_cost_can_be_paid_with_two_wait_energy():
    state = _state()
    state.cards["energy-0"].orientation = "wait"
    state = apply_action(state, _activate(state)).state
    result = apply_action(state, _cost(state))
    assert result.state.players["player_1"].energy_area == ["energy-2"]
    assert MatchState.model_validate_json(result.state.model_dump_json()) == result.state


@pytest.mark.parametrize("ids", [["energy-0", "energy-1"], ["energy-3"], ["live-1"]])
def test_invalid_branch_energy_is_atomic(ids):
    state = _branch_state(_state(BRANCH))
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalActionError):
        apply_action(
            state,
            _action(
                state,
                "resolve_effect",
                invocation_id=state.pending_effects[0].invocation_id,
                selected_branch="return_energy",
                accepted=True,
                selected_card_instance_ids=ids,
            ),
        )
    assert state.model_dump(mode="json") == before


def _break_snapshot(repository, match_id, column="current_state_json"):
    assert column in {"current_state_json", "initial_state_json"}
    with sqlite3.connect(repository.path) as connection:
        raw = json.loads(
            connection.execute(
                f"SELECT {column} FROM matches WHERE match_id=?", (match_id,)
            ).fetchone()[0]
        )
        raw["cards"]["energy-3"]["orientation"] = None
        raw["cards"]["deck-live-1"]["card"]["name_ja"] = {"private": "DO_NOT_LEAK_PRIVATE_DATA"}
        text = json.dumps(raw, ensure_ascii=False)
        connection.execute(f"UPDATE matches SET {column}=? WHERE match_id=?", (text, match_id))
    return text


@pytest.mark.parametrize("column", ["initial_state_json", "current_state_json"])
def test_corrupt_legacy_snapshots_are_not_silently_rewritten_or_replayed(tmp_path, column):
    from loveca.simulation.runtime import InvalidMatchSnapshotError, MatchRepository

    state = _state()
    repository = MatchRepository(tmp_path / "legacy.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    saved = _break_snapshot(repository, state.match_id, column)
    with pytest.raises(InvalidMatchSnapshotError, match="invalid_match_snapshot") as exc:
        repository.replay(state.match_id)
    assert "DO_NOT_LEAK" not in str(exc.value)
    if column == "current_state_json":
        with pytest.raises(InvalidMatchSnapshotError):
            repository.get_state(state.match_id)
        with pytest.raises(InvalidMatchSnapshotError):
            repository.apply(state.match_id, _activate(state))
    with sqlite3.connect(repository.path) as connection:
        assert (
            connection.execute(
                f"SELECT {column} FROM matches WHERE match_id=?", (state.match_id,)
            ).fetchone()[0]
            == saved
        )
        assert connection.execute("SELECT COUNT(*) FROM match_actions").fetchone()[0] == 0


def test_private_match_invalid_snapshot_api_does_not_leak_or_bypass_auth(tmp_path):
    from test_webapp import _client

    client = _client(tmp_path, public_match_endpoints=False)
    repository = client.app.state.match_service.repository
    state = _state()
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    token = repository.issue_match_token(state.match_id)
    saved = _break_snapshot(repository, state.match_id)
    for suffix in ["", "/legal-actions", "/replay"]:
        url = f"/api/matches/{state.match_id}{suffix}"
        assert client.get(url).status_code == 403
        response = client.get(url, headers={"X-LoveCA-Match-Token": token})
        assert response.status_code == 409
        assert response.json()["code"] == "invalid_match_snapshot"
        assert "DO_NOT_LEAK" not in response.text and token not in response.text
    response = client.post(
        f"/api/matches/{state.match_id}/actions",
        json=_activate(state).model_dump(),
        headers={"X-LoveCA-Match-Token": token},
    )
    assert response.status_code == 409 and response.json()["code"] == "invalid_match_snapshot"
    with sqlite3.connect(repository.path) as connection:
        assert connection.execute("SELECT current_state_json FROM matches").fetchone()[0] == saved
        assert connection.execute("SELECT COUNT(*) FROM match_actions").fetchone()[0] == 0


def test_private_match_api_can_resume_after_real_energy_cost_and_export_replay(tmp_path):
    from test_webapp import _client

    client = _client(tmp_path, public_match_endpoints=False)
    repository = client.app.state.match_service.repository
    state = _state()
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    token = repository.issue_match_token(state.match_id)
    headers = {"X-LoveCA-Match-Token": token}
    for stage in ["activate", "cost", "recover"]:
        action = {"activate": _activate, "cost": _cost, "recover": _recover}[stage](state)
        response = client.post(
            f"/api/matches/{state.match_id}/actions", json=action.model_dump(), headers=headers
        )
        assert response.status_code == 200
        state = MatchState.model_validate(response.json()["state"])
        resumed = client.get(f"/api/matches/{state.match_id}", headers=headers)
        assert resumed.status_code == 200 and resumed.json()["state"]["revision"] == state.revision
    replay = client.get(f"/api/matches/{state.match_id}/replay", headers=headers)
    assert replay.status_code == 200
    assert replay.json()["final_state"] == state.model_dump(mode="json")


def test_hosted_corrupt_match_has_safe_http_and_sse_errors_for_both_players(tmp_path):
    from test_webapp import SAMPLE_DECK, _client

    client = _client(tmp_path)
    deck = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))
    created = client.post(
        "/api/rooms", json={"player_name": "Host", "deck": deck, "seed": 1}
    ).json()
    code, host_token = created["room_code"], created["player_token"]
    joined = client.post(
        f"/api/rooms/{code}/join", json={"player_name": "Guest", "deck": deck}
    ).json()
    guest_token, match_id = joined["player_token"], joined["match_id"]
    repository = client.app.state.match_service.repository
    with sqlite3.connect(repository.path) as connection:
        raw = json.loads(
            connection.execute(
                "SELECT current_state_json FROM matches WHERE match_id=?", (match_id,)
            ).fetchone()[0]
        )
        energy_id = raw["players"]["player_1"]["energy_deck"][0]
        raw["cards"][energy_id]["orientation"] = None
        saved = json.dumps(raw)
        connection.execute(
            "UPDATE matches SET current_state_json=? WHERE match_id=?", (saved, match_id)
        )
    assert client.get(f"/api/rooms/{code}").json()["match"] is None
    assert client.get(f"/api/rooms/{code}/stream?player_token=wrong&once=true").status_code == 403
    for token in [host_token, guest_token]:
        for suffix in ["", "/replay"]:
            response = client.get(f"/api/rooms/{code}{suffix}?player_token={token}")
            assert response.status_code == 409
            assert response.json()["code"] == "invalid_match_snapshot"
            assert token not in response.text and energy_id not in response.text
        stream = client.get(f"/api/rooms/{code}/stream?player_token={token}&once=true")
        assert stream.status_code == 200
        assert "event: room_error" in stream.text and "invalid_match_snapshot" in stream.text
        assert "event: room_update" not in stream.text and energy_id not in stream.text
    action = {
        "action_type": "submit_mulligan",
        "player_id": "player_1",
        "expected_revision": raw["revision"],
        "payload": {"card_instance_ids": []},
    }
    response = client.post(
        f"/api/rooms/{code}/actions", json={"player_token": host_token, "action": action}
    )
    assert response.status_code == 409 and response.json()["code"] == "invalid_match_snapshot"
    with sqlite3.connect(repository.path) as connection:
        assert (
            connection.execute(
                "SELECT current_state_json FROM matches WHERE match_id=?", (match_id,)
            ).fetchone()[0]
            == saved
        )


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1"])
@pytest.mark.parametrize("effect_id", [ACTIVATED, BRANCH])
def test_three_ai_policies_finish_real_skill_without_invalid_intermediate_state(policy, effect_id):
    from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy

    state = _state(effect_id)
    state.cards["opponent-private"] = state.cards["source-live"].model_copy(
        update={"instance_id": "opponent-private", "owner_id": "player_2"}, deep=True
    )
    state.players["player_2"].hand = ["opponent-private"]
    start = _activate(state) if effect_id == ACTIVATED else _action(state, "advance_phase")
    state = apply_action(state, start).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    for _ in range(5):
        if not state.pending_effects:
            break
        decision = controller.choose_action(
            state, generate_legal_actions(state), controlled_player_ids={"player_1"}
        )
        assert isinstance(decision, SimpleAIDecision)
        assert decision.action.action_type == "resolve_effect"
        changed = state.model_copy(deep=True)
        changed.cards["opponent-private"].card.name_ja = "非公開カード変更"
        changed.cards["opponent-private"].card.card_code = "PRIVATE-CHANGED"
        other = controller.choose_action(
            changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}
        )
        assert other.action == decision.action
        result = apply_action(state, decision.action)
        assert not any(e.event_type == "effect_skipped_due_to_error" for e in result.events)
        state = MatchState.model_validate_json(result.state.model_dump_json())
    assert not state.pending_effects
    assert len(state.players["player_1"].energy_area) == (1 if effect_id == ACTIVATED else 2)


def test_registry_binding_and_old_snapshot_shape_are_unchanged(tmp_path):
    from loveca.simulation.effect_candidates import discover_effect_candidates
    from loveca.simulation.online import match_state_hash, sha256_json
    from loveca.simulation.runtime import MatchRepository

    expected = {
        ACTIVATED: (247, "f69337d2929c4dfb13861b26d321b9ccc7ed88319d81023215cb69e28c6db712"),
        BRANCH: (806, "74c4b94cf6684d2e76e3c83d609aaa214d98facf67ba0b1aebbe7b6ba2b2aa63"),
    }
    candidates = {
        c.effect_id: c
        for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
    }
    for effect_id, (revision, raw_hash) in expected.items():
        state = _state(effect_id)
        effect = state.effect_definitions[effect_id]
        assert (effect.text_revision_id, effect.raw_text_hash) == (revision, raw_hash)
        assert (
            effect.review_status == "test_validated"
            and effect.simulation_support == "test_validated_executable"
        )
        assert candidates[effect_id].actions == [
            op.model_dump(exclude_none=True) for op in effect.actions
        ]
        assert candidates[effect_id].cost == [
            op.model_dump(exclude_none=True) for op in effect.cost
        ]
        raw = state.model_dump(mode="json")
        assert match_state_hash(MatchState.model_validate(raw)) == sha256_json(raw)
        assert not any(
            op.get("energy_return_policy") for op in raw["effect_definitions"][effect_id]["actions"]
        )
    repository = MatchRepository(tmp_path / "unaffected-legacy.sqlite3")
    state = _state()
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    replay = repository.replay(state.match_id)
    assert (
        replay["metadata"]["initial_state_hash"]
        == replay["metadata"]["final_state_hash"]
        == match_state_hash(state)
    )
