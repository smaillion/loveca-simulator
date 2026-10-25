import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_webapp import SAMPLE_DECK, _client

from loveca.simulation import rulesets, service as service_module
from loveca.simulation.rooms import ROOM_RULESET_KEY_PREFIX, RoomRepository, RoomStateError
from loveca.webapp import create_app


def _deck():
    return json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))


def _create(client, **kwargs):
    response = client.post("/api/rooms", json={"player_name": "A", "deck": _deck(), "seed": 1, **kwargs})
    assert response.status_code == 200
    return response.json()


def _join(client, room):
    return client.post(f"/api/rooms/{room['room_code']}/join", json={"player_name": "B", "deck": _deck()})


def _dump(tmp_path):
    with sqlite3.connect(tmp_path / "matches.sqlite3") as connection:
        return list(connection.iterdump())


def _update_identity(tmp_path, room, changes):
    with sqlite3.connect(tmp_path / "matches.sqlite3") as connection:
        key = ROOM_RULESET_KEY_PREFIX + room["room_code"]
        raw = json.loads(connection.execute("SELECT value FROM runtime_metadata WHERE key = ?", (key,)).fetchone()[0])
        raw.update(changes)
        connection.execute("UPDATE runtime_metadata SET value = ? WHERE key = ?", (json.dumps(raw), key))


@pytest.mark.parametrize("ruleset_id", ["", "unknown-profile"])
def test_unknown_room_profile_rejected_without_persistence(tmp_path, ruleset_id):
    client = _client(tmp_path)
    with sqlite3.connect(tmp_path / "matches.sqlite3") as connection:
        before = list(connection.iterdump())
    response = client.post("/api/rooms", json={
        "player_name": "A", "deck": _deck(), "ruleset_id": ruleset_id,
    })
    assert response.status_code == 400
    assert "unknown ruleset_id" in response.json()["detail"]
    with sqlite3.connect(tmp_path / "matches.sqlite3") as connection:
        assert list(connection.iterdump()) == before


@pytest.mark.parametrize("explicit", [False, True])
def test_room_pins_ruleset_without_changing_decks_or_sqlite_schema(tmp_path, explicit):
    client = _client(tmp_path)
    with sqlite3.connect(tmp_path / "matches.sqlite3") as connection:
        schema = connection.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
    profile, fingerprint = rulesets.current_ruleset_identity()
    room = _create(client, **({"ruleset_id": profile.ruleset_id} if explicit else {}))
    identity = room["ruleset_identity"]
    assert identity == {"ruleset_id": profile.ruleset_id, "rule_version": profile.rule_version,
                        "ruleset_fingerprint": fingerprint, "ruling_pack_version": profile.ruling_pack_version}
    with sqlite3.connect(tmp_path / "matches.sqlite3") as connection:
        assert connection.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall() == schema
        saved = connection.execute("SELECT host_deck_json FROM hosted_rooms WHERE room_code = ?", (room["room_code"],)).fetchone()[0]
        assert json.loads(saved) == _deck()
        metadata = connection.execute("SELECT value FROM runtime_metadata WHERE key = ?", (ROOM_RULESET_KEY_PREFIX + room["room_code"],)).fetchone()[0]
        assert json.loads(metadata) == identity
        assert len(metadata.encode("utf-8")) < 1024
    assert client.get(f"/api/rooms/{room['room_code']}").json()["match"] is None
    joined = _join(client, room)
    assert joined.status_code == 200
    state = joined.json()["match"]["state"]
    assert all(state[key] == value for key, value in identity.items())
    actor = state["first_player_id"]
    token = room["player_token"] if actor == "player_1" else joined.json()["player_token"]
    acted = client.post(f"/api/rooms/{room['room_code']}/actions", json={
        "player_token": token,
        "action": {"action_type": "submit_mulligan", "expected_revision": state["revision"],
                   "player_id": actor, "payload": {"card_instance_ids": []}},
    })
    assert acted.status_code == 200
    assert all(acted.json()["state"][key] == value for key, value in identity.items())
    for token, player, other in ((room["player_token"], "player_1", "player_2"),
                                 (joined.json()["player_token"], "player_2", "player_1")):
        payload = client.get(f"/api/rooms/{room['room_code']}", params={"player_token": token}).json()
        assert payload["ruleset_identity"] == identity
        view = payload["match"]["state"]
        assert set(view["players"][player]["hand"]).issubset(view["cards"])
        assert set(view["players"][other]["hand"]).isdisjoint(view["cards"])
    replay = client.get(f"/api/rooms/{room['room_code']}/replay", params={"player_token": room["player_token"]}).json()
    assert all(replay["metadata"][key] == value for key, value in identity.items())
    assert replay["metadata"]["ruleset_identity_verified"] is True


def test_new_api_instance_restores_waiting_identity_from_sqlite(tmp_path):
    first = _client(tmp_path)
    room = _create(first)
    restored = TestClient(create_app(first.app.state.settings))
    polled = restored.get(f"/api/rooms/{room['room_code']}").json()
    assert polled["ruleset_identity"] == room["ruleset_identity"]
    assert polled["status"] == "waiting_for_guest"
    joined = _join(restored, room)
    assert joined.status_code == 200
    assert joined.json()["ruleset_identity"] == room["ruleset_identity"]
    first_view = first.get(f"/api/rooms/{room['room_code']}", params={"player_token": room["player_token"]}).json()
    assert first_view["status"] == "active"
    assert first_view["match"]["state"]["ruleset_fingerprint"] == room["ruleset_identity"]["ruleset_fingerprint"]


@pytest.mark.parametrize("field,value", [
    ("ruleset_id", "unknown-profile"), ("rule_version", "1.07"),
    ("ruleset_fingerprint", "0" * 64), ("ruling_pack_version", "future-pack"),
])
def test_different_pinned_identity_rejects_join_without_creating_a_match(tmp_path, field, value):
    client = _client(tmp_path)
    room = _create(client)
    _update_identity(tmp_path, room, {field: value})
    before = _dump(tmp_path)
    rejected = _join(client, room)
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "ruleset_mismatch"
    assert _dump(tmp_path) == before


@pytest.mark.parametrize("change", ["fingerprint", "profile_id", "engine_version"])
def test_server_ruleset_change_does_not_rebind_a_waiting_room(tmp_path, monkeypatch, change):
    client = _client(tmp_path)
    room = _create(client)
    registry = rulesets.load_ruleset_registry()
    profile = rulesets.get_ruleset_profile(registry=registry)
    if change == "fingerprint":
        profile = profile.model_copy(update={"ruling_pack_version": "future-pack"})
    elif change == "profile_id":
        profile = profile.model_copy(update={"ruleset_id": "next-profile"})
        registry = registry.model_copy(update={"current_ruleset_id": profile.ruleset_id})
    else:
        profile = profile.model_copy(update={"rule_version": "1.07"})
    registry = registry.model_copy(update={"profiles": (profile,)})
    monkeypatch.setattr(service_module, "load_ruleset_registry", lambda: registry)
    monkeypatch.setattr(rulesets, "load_ruleset_registry", lambda: registry)
    polled = client.get(f"/api/rooms/{room['room_code']}").json()
    assert polled["ruleset_identity"] == room["ruleset_identity"]
    before = _dump(tmp_path)
    rejected = _join(client, room)
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "ruleset_mismatch"
    assert _dump(tmp_path) == before


def test_legacy_waiting_room_keeps_old_join_behavior_without_backfilling_metadata(tmp_path):
    client = _client(tmp_path)
    room = _create(client)
    key = ROOM_RULESET_KEY_PREFIX + room["room_code"]
    with sqlite3.connect(tmp_path / "matches.sqlite3") as connection:
        connection.execute("DELETE FROM runtime_metadata WHERE key = ?", (key,))
    assert client.get(f"/api/rooms/{room['room_code']}").json()["ruleset_identity"] is None
    joined = _join(client, room)
    assert joined.status_code == 200
    assert joined.json()["ruleset_identity"] is None
    assert joined.json()["match"]["state"]["ruleset_fingerprint"] == room["ruleset_identity"]["ruleset_fingerprint"]
    with sqlite3.connect(tmp_path / "matches.sqlite3") as connection:
        assert connection.execute("SELECT value FROM runtime_metadata WHERE key = ?", (key,)).fetchone() is None


@pytest.mark.parametrize("raw", ["not-json", "{}", '{"ruleset_id":"broken"}', '{"extra":"forbidden"}'])
def test_corrupt_metadata_is_reported_without_mutating_room_or_match(tmp_path, raw):
    client = _client(tmp_path)
    room = _create(client)
    with sqlite3.connect(tmp_path / "matches.sqlite3") as connection:
        connection.execute("UPDATE runtime_metadata SET value = ? WHERE key = ?", (raw, ROOM_RULESET_KEY_PREFIX + room["room_code"]))
    before = _dump(tmp_path)
    response = _join(client, room)
    assert response.status_code == 400
    assert "invalid_room_ruleset_metadata" in response.json()["detail"]
    assert _dump(tmp_path) == before


@pytest.mark.parametrize("status", ["active", "expired"])
def test_join_preflight_does_not_create_orphan_matches_for_nonwaiting_room(tmp_path, status):
    client = _client(tmp_path)
    room = _create(client)
    if status == "active":
        assert _join(client, room).status_code == 200
    else:
        assert client.post(f"/api/rooms/{room['room_code']}/leave", json={"player_token": room["player_token"]}).status_code == 200
    before = _dump(tmp_path)
    assert _join(client, room).status_code == 400
    assert _dump(tmp_path) == before


def test_cleanup_removes_only_deleted_room_metadata_and_retains_grace(tmp_path):
    client = _client(tmp_path)
    room = _create(client)
    key = ROOM_RULESET_KEY_PREFIX + room["room_code"]
    with sqlite3.connect(tmp_path / "matches.sqlite3") as connection:
        connection.executemany("INSERT INTO runtime_metadata (key, value) VALUES (?, ?)", [
            (ROOM_RULESET_KEY_PREFIX + "ORPHAN", "{}"), ("hostedXroomYruleset:unrelated", "keep"),
        ])
    client.post(f"/api/rooms/{room['room_code']}/leave", json={"player_token": room["player_token"]})
    assert client.post("/api/rooms/cleanup").json()["deleted_count"] == 0
    with sqlite3.connect(tmp_path / "matches.sqlite3") as connection:
        assert connection.execute("SELECT value FROM runtime_metadata WHERE key = ?", (key,)).fetchone()
        assert connection.execute("SELECT value FROM runtime_metadata WHERE key = ?", (ROOM_RULESET_KEY_PREFIX + "ORPHAN",)).fetchone() is None
        connection.execute("UPDATE hosted_rooms SET closed_at = '2000-01-01T00:00:00+00:00' WHERE room_code = ?", (room["room_code"],))
    assert client.post("/api/rooms/cleanup").json()["deleted_count"] == 1
    with sqlite3.connect(tmp_path / "matches.sqlite3") as connection:
        assert connection.execute("SELECT value FROM runtime_metadata WHERE key = ?", (key,)).fetchone() is None
        assert connection.execute("SELECT value FROM runtime_metadata WHERE key = 'schema_version'").fetchone()
        assert connection.execute("SELECT value FROM runtime_metadata WHERE key = 'hostedXroomYruleset:unrelated'").fetchone()[0] == "keep"


def test_room_and_metadata_insert_roll_back_together(tmp_path):
    client = _client(tmp_path)
    with sqlite3.connect(tmp_path / "matches.sqlite3") as connection:
        connection.execute("""CREATE TRIGGER fail_room_ruleset BEFORE INSERT ON runtime_metadata
            WHEN substr(NEW.key, 1, 20) = 'hosted_room_ruleset:'
            BEGIN SELECT RAISE(ABORT, 'controlled metadata failure'); END""")
    before = _dump(tmp_path)
    response = client.post("/api/rooms", json={"player_name": "A", "deck": _deck()})
    assert response.status_code == 400
    assert _dump(tmp_path) == before


def test_legacy_standalone_room_repository_does_not_need_new_schema(tmp_path):
    repository = RoomRepository(tmp_path / "rooms-only.sqlite3")
    room = repository.create_room(host_name="A", host_deck=_deck(), seed=1, ttl_hours=24)
    assert repository.get_room(room.room_code).ruleset_identity is None
    assert repository.cleanup_expired(delete_grace_hours=1).deleted_count == 0
    with sqlite3.connect(repository.path) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name = 'runtime_metadata'").fetchone() is None


def test_new_binding_on_nonstandard_room_only_database_fails_before_insert(tmp_path):
    repository = RoomRepository(tmp_path / "rooms-only.sqlite3")
    profile, fingerprint = rulesets.current_ruleset_identity()
    identity = rulesets.RulesetIdentity(
        ruleset_id=profile.ruleset_id, rule_version=profile.rule_version,
        ruleset_fingerprint=fingerprint, ruling_pack_version=profile.ruling_pack_version,
    )
    with pytest.raises(RoomStateError, match="standard runtime database"):
        repository.create_room(host_name="A", host_deck=_deck(), seed=1, ttl_hours=24, ruleset_identity=identity)
    with sqlite3.connect(repository.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM hosted_rooms").fetchone()[0] == 0
        assert connection.execute("SELECT name FROM sqlite_master WHERE name = 'runtime_metadata'").fetchone() is None
