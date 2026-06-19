from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from loveca.cards.importer import import_normalized_cards
from loveca.webapp import ApiSettings, create_app

PROJECT_ROOT = Path(__file__).parents[1]
SAMPLE_CARDS = (
    PROJECT_ROOT
    / "data_samples"
    / "normalized"
    / "cards-cross-product-sample.json"
)
NORMALIZATION = PROJECT_ROOT / "data_sources" / "card-entity-normalization.json"
SAMPLE_DECK = PROJECT_ROOT / "tests" / "fixtures" / "legal-deck.json"


def test_match_api_create_act_resume_and_replay(tmp_path):
    client = _client(tmp_path)
    deck = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))

    response = client.post(
        "/api/matches",
        json={
            "player_1": {"name": "Player A", "deck": deck},
            "player_2": {"name": "Player B", "deck": deck},
            "seed": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    match_id = payload["state"]["match_id"]
    assert payload["state"]["revision"] == 1
    assert payload["state"]["phase"] == "setup_mulligan_first"
    assert payload["state"]["first_player_id"] == "player_1"
    assert payload["state"]["players"]["player_1"]["member_area_attachments"] == {
        "left": [],
        "center": [],
        "right": [],
    }
    assert payload["legal_actions"][0]["action_type"] == "submit_mulligan"

    action_response = client.post(
        f"/api/matches/{match_id}/actions",
        json={
            "action_type": "submit_mulligan",
            "expected_revision": 1,
            "player_id": "player_1",
            "payload": {"card_instance_ids": []},
        },
    )
    assert action_response.status_code == 200
    assert action_response.json()["state"]["revision"] == 2

    resumed = client.get(f"/api/matches/{match_id}")
    assert resumed.status_code == 200
    assert resumed.json()["state"]["phase"] == "setup_mulligan_second"
    assert resumed.json()["events"]

    replay = client.get(f"/api/matches/{match_id}/replay")
    assert replay.status_code == 200
    assert replay.json()["final_state"]["revision"] == 2


def test_hosted_room_api_create_join_act_and_replay(tmp_path):
    client = _client(tmp_path)
    deck = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))

    created = client.post(
        "/api/rooms",
        json={"player_name": "Host", "deck": deck, "seed": 1},
    )
    assert created.status_code == 200
    room_payload = created.json()
    room_code = room_payload["room_code"]
    host_token = room_payload["player_token"]
    assert room_payload["status"] == "waiting_for_guest"
    assert room_payload["player_id"] == "player_1"
    assert room_payload["match"] is None

    joined = client.post(
        f"/api/rooms/{room_code}/join",
        json={"player_name": "Guest", "deck": deck},
    )
    assert joined.status_code == 200
    joined_payload = joined.json()
    guest_token = joined_payload["player_token"]
    assert joined_payload["status"] == "active"
    assert joined_payload["player_id"] == "player_2"
    assert joined_payload["match"]["state"]["revision"] == 1
    assert all(
        action["player_id"] in {None, "player_1"}
        for action in joined_payload["match"]["legal_actions"]
    )

    hidden = client.get(f"/api/rooms/{room_code}")
    assert hidden.status_code == 200
    assert hidden.json()["match"] is None

    wrong_token = client.post(
        f"/api/rooms/{room_code}/actions",
        json={
            "player_token": "wrong",
            "action": {
                "action_type": "submit_mulligan",
                "expected_revision": 2,
                "player_id": "player_1",
                "payload": {"card_instance_ids": []},
            },
        },
    )
    assert wrong_token.status_code == 403

    acted = client.post(
        f"/api/rooms/{room_code}/actions",
        json={
            "player_token": host_token,
            "action": {
                "action_type": "submit_mulligan",
                "expected_revision": 1,
                "player_id": "player_1",
                "payload": {"card_instance_ids": []},
            },
        },
    )
    assert acted.status_code == 200
    assert acted.json()["state"]["revision"] == 2
    acted_state = acted.json()["state"]
    assert set(acted_state["players"]["player_1"]["hand"]).issubset(acted_state["cards"])
    assert set(acted_state["players"]["player_2"]["hand"]).isdisjoint(acted_state["cards"])

    host_poll = client.get(f"/api/rooms/{room_code}?player_token={host_token}")
    assert host_poll.status_code == 200
    host_state = host_poll.json()["match"]["state"]
    assert set(host_state["players"]["player_1"]["hand"]).issubset(host_state["cards"])
    assert set(host_state["players"]["player_2"]["hand"]).isdisjoint(host_state["cards"])

    opponent_action = client.post(
        f"/api/rooms/{room_code}/actions",
        json={
            "player_token": guest_token,
            "action": {
                "action_type": "submit_mulligan",
                "expected_revision": 1,
                "player_id": "player_1",
                "payload": {"card_instance_ids": []},
            },
        },
    )
    assert opponent_action.status_code == 403

    missing_player_id = client.post(
        f"/api/rooms/{room_code}/actions",
        json={
            "player_token": guest_token,
            "action": {
                "action_type": "submit_mulligan",
                "expected_revision": 2,
                "payload": {"card_instance_ids": []},
            },
        },
    )
    assert missing_player_id.status_code == 403

    polled = client.get(f"/api/rooms/{room_code}?player_token={guest_token}")
    assert polled.status_code == 200
    assert polled.json()["match"]["state"]["revision"] == 2
    guest_state = polled.json()["match"]["state"]
    host_hand = set(guest_state["players"]["player_1"]["hand"])
    guest_hand = set(guest_state["players"]["player_2"]["hand"])
    assert host_hand
    assert guest_hand
    assert host_hand.isdisjoint(guest_state["cards"])
    assert guest_hand.issubset(guest_state["cards"])
    assert all(
        action["player_id"] in {None, "player_2"}
        for action in polled.json()["match"]["legal_actions"]
    )

    replay = client.get(f"/api/rooms/{room_code}/replay?player_token={host_token}")
    assert replay.status_code == 200
    assert replay.json()["final_state"]["revision"] == 2


def test_match_history_paginates_without_purging_active_room_match(tmp_path):
    client = _client(tmp_path)
    deck = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))

    created = client.post(
        "/api/rooms",
        json={"player_name": "Host", "deck": deck, "seed": 106},
    )
    assert created.status_code == 200
    room_code = created.json()["room_code"]
    host_token = created.json()["player_token"]

    joined = client.post(
        f"/api/rooms/{room_code}/join",
        json={"player_name": "Guest", "deck": deck},
    )
    assert joined.status_code == 200
    room_match_id = joined.json()["match_id"]

    for index in range(30):
        response = client.post(
            "/api/matches",
            json={
                "player_1": {"name": f"A{index}", "deck": deck},
                "player_2": {"name": f"B{index}", "deck": deck},
                "seed": index,
            },
        )
        assert response.status_code == 200

    polled = client.get(f"/api/rooms/{room_code}?player_token={host_token}")
    assert polled.status_code == 200
    assert polled.json()["match_id"] == room_match_id
    assert polled.json()["match"]["state"]["match_id"] == room_match_id

    assert client.get(f"/api/matches/{room_match_id}").status_code == 404
    assert client.get(f"/api/matches/{room_match_id}/legal-actions").status_code == 404
    assert client.get(f"/api/matches/{room_match_id}/replay").status_code == 404
    blocked_action = client.post(
        f"/api/matches/{room_match_id}/actions",
        json={
            "action_type": "choose_first_player",
            "expected_revision": 0,
            "payload": {"first_player_id": "player_1"},
        },
    )
    assert blocked_action.status_code == 404

    first_page = client.get("/api/matches?page=1&per_page=10")
    assert first_page.status_code == 200
    payload = first_page.json()
    assert len(payload["items"]) == 10
    assert room_match_id not in {item["match_id"] for item in payload["items"]}
    assert payload["page"] == 1
    assert payload["per_page"] == 10
    assert payload["total"] == 25


def test_match_history_caps_results_at_25(tmp_path):
    runtime_path = tmp_path / "matches.sqlite3"
    client = _client(tmp_path)
    _insert_match_rows(runtime_path, 105)

    first_page = client.get("/api/matches?page=1&per_page=10")
    assert first_page.status_code == 200
    assert first_page.json()["total"] == 25
    assert len(first_page.json()["items"]) == 10

    last_page = client.get("/api/matches?page=3&per_page=10")
    assert last_page.status_code == 200
    assert len(last_page.json()["items"]) == 5

    overflow = client.get("/api/matches?page=4&per_page=10")
    assert overflow.status_code == 200
    assert overflow.json()["items"] == []


def test_public_match_endpoints_can_be_disabled_while_solo_matches_use_tokens(tmp_path):
    client = _client(tmp_path, public_match_endpoints=False)
    deck = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))

    assert client.get("/api/matches").status_code == 404
    created_match = client.post(
        "/api/matches",
        json={
            "player_1": {"name": "Player A", "deck": deck},
            "player_2": {"name": "Player B", "deck": deck},
            "seed": 1,
        },
    )
    assert created_match.status_code == 200
    payload = created_match.json()
    match_id = payload["state"]["match_id"]
    match_token = payload["match_token"]
    assert match_token

    assert client.get(f"/api/matches/{match_id}").status_code == 403
    restored = client.get(f"/api/matches/{match_id}?match_token={match_token}")
    assert restored.status_code == 200
    assert restored.json()["state"]["match_id"] == match_id

    next_action = payload["legal_actions"][0]
    action_request = {
        "action_type": next_action["action_type"],
        "expected_revision": payload["state"]["revision"],
        "player_id": next_action["player_id"],
        "payload": {"card_instance_ids": []},
    }
    rejected_action = client.post(
        f"/api/matches/{match_id}/actions",
        json=action_request,
    )
    assert rejected_action.status_code == 403
    accepted_action = client.post(
        f"/api/matches/{match_id}/actions?match_token={match_token}",
        json=action_request,
    )
    assert accepted_action.status_code == 200

    created = client.post(
        "/api/rooms",
        json={"player_name": "Host", "deck": deck, "seed": 106},
    )
    assert created.status_code == 200
    room_code = created.json()["room_code"]

    joined = client.post(
        f"/api/rooms/{room_code}/join",
        json={"player_name": "Guest", "deck": deck},
    )
    assert joined.status_code == 200
    assert joined.json()["match"]["state"]["match_id"]


def test_admin_runtime_storage_and_cleanup_requires_key(tmp_path):
    client = _client(tmp_path, admin_key="secret")
    runtime_path = tmp_path / "matches.sqlite3"
    _insert_match_rows(runtime_path, 3)
    with sqlite3.connect(runtime_path) as connection:
        for revision in range(6):
            connection.execute(
                """
                INSERT INTO match_snapshots (
                    match_id,
                    revision,
                    action_sequence,
                    state_json,
                    created_at
                )
                VALUES ('match-000', ?, ?, ?, '2026-06-15T00:00:00+00:00')
                """,
                (revision, revision, "{}" * (revision + 1)),
            )

    assert client.get("/api/admin/runtime/storage").status_code == 403
    storage = client.get(
        "/api/admin/runtime/storage",
        headers={"X-LoveCA-Admin-Key": "secret"},
    )
    assert storage.status_code == 200
    assert storage.json()["tables"]

    cleanup = client.post(
        "/api/admin/runtime/cleanup",
        headers={"X-LoveCA-Admin-Key": "secret"},
        json={
            "retain_matches": 25,
            "max_snapshots_per_match": 3,
            "vacuum": False,
        },
    )
    assert cleanup.status_code == 200
    payload = cleanup.json()
    assert payload["snapshot_deleted_count"] == 3
    assert payload["deleted_by_age"] == 0


def test_hosted_room_leave_expires_room_and_blocks_actions(tmp_path):
    client = _client(tmp_path)
    deck = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))
    created = client.post(
        "/api/rooms",
        json={"player_name": "Host", "deck": deck, "seed": 106},
    ).json()
    room_code = created["room_code"]
    host_token = created["player_token"]

    joined = client.post(
        f"/api/rooms/{room_code}/join",
        json={"player_name": "Guest", "deck": deck},
    )
    assert joined.status_code == 200

    wrong_token = client.post(
        f"/api/rooms/{room_code}/leave",
        json={"player_token": "wrong"},
    )
    assert wrong_token.status_code == 403
    assert _room_row(tmp_path, room_code)["status"] == "active"

    left = client.post(
        f"/api/rooms/{room_code}/leave",
        json={"player_token": host_token},
    )
    assert left.status_code == 200
    left_payload = left.json()
    assert left_payload["status"] == "expired"
    assert left_payload["close_reason"] == "player_left"
    assert left_payload["closed_at"]

    blocked = client.post(
        f"/api/rooms/{room_code}/actions",
        json={
            "player_token": host_token,
            "action": {
                "action_type": "choose_first_player",
                "expected_revision": 0,
                "payload": {"first_player_id": "player_1"},
            },
        },
    )
    assert blocked.status_code == 409


def test_hosted_room_polling_updates_presence_for_token_only(tmp_path):
    client = _client(tmp_path)
    deck = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))
    created = client.post(
        "/api/rooms",
        json={"player_name": "Host", "deck": deck, "seed": 106},
    ).json()
    room_code = created["room_code"]
    host_token = created["player_token"]
    client.post(
        f"/api/rooms/{room_code}/join",
        json={"player_name": "Guest", "deck": deck},
    )
    old_seen = "2000-01-01T00:00:00+00:00"
    with sqlite3.connect(tmp_path / "matches.sqlite3") as connection:
        connection.execute(
            """
            UPDATE hosted_rooms
            SET host_last_seen_at = ?, updated_at = ?, expires_at = ?
            WHERE room_code = ?
            """,
            (old_seen, old_seen, "2099-01-01T00:00:00+00:00", room_code),
        )

    hidden = client.get(f"/api/rooms/{room_code}")
    assert hidden.status_code == 200
    assert _room_row(tmp_path, room_code)["host_last_seen_at"] == old_seen

    polled = client.get(f"/api/rooms/{room_code}?player_token={host_token}")
    assert polled.status_code == 200
    row = _room_row(tmp_path, room_code)
    assert row["host_last_seen_at"] != old_seen
    assert row["updated_at"] != old_seen


def test_hosted_room_cleanup_expires_then_deletes_after_grace(tmp_path):
    client = _client(tmp_path)
    deck = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))
    created = client.post(
        "/api/rooms",
        json={"player_name": "Host", "deck": deck, "seed": 106},
    ).json()
    room_code = created["room_code"]
    old_time = "2000-01-01T00:00:00+00:00"
    with sqlite3.connect(tmp_path / "matches.sqlite3") as connection:
        connection.execute(
            """
            UPDATE hosted_rooms
            SET expires_at = ?
            WHERE room_code = ?
            """,
            (old_time, room_code),
        )

    expired = client.post("/api/rooms/cleanup")
    assert expired.status_code == 200
    assert expired.json()["expired_count"] == 1
    assert expired.json()["deleted_count"] == 0
    assert _room_row(tmp_path, room_code)["status"] == "expired"

    with sqlite3.connect(tmp_path / "matches.sqlite3") as connection:
        connection.execute(
            """
            UPDATE hosted_rooms
            SET closed_at = ?
            WHERE room_code = ?
            """,
            (old_time, room_code),
        )

    deleted = client.post("/api/rooms/cleanup")
    assert deleted.status_code == 200
    assert deleted.json()["deleted_count"] == 1
    with sqlite3.connect(tmp_path / "matches.sqlite3") as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM hosted_rooms WHERE room_code = ?",
                (room_code,),
            ).fetchone()
            is None
        )


def test_api_rejects_stale_revision_without_mutation(tmp_path):
    client = _client(tmp_path)
    deck_path = str(SAMPLE_DECK.relative_to(PROJECT_ROOT))
    created = client.post(
        "/api/matches",
        json={
            "player_1": {"name": "A", "deck_path": deck_path},
            "player_2": {"name": "B", "deck_path": deck_path},
            "seed": 1,
        },
    ).json()
    match_id = created["state"]["match_id"]

    response = client.post(
        f"/api/matches/{match_id}/actions",
        json={
            "action_type": "submit_mulligan",
            "expected_revision": 9,
            "player_id": "player_1",
            "payload": {"card_instance_ids": []},
        },
    )

    assert response.status_code == 409
    assert client.get(f"/api/matches/{match_id}").json()["state"]["revision"] == 1


def test_uncached_card_image_returns_404(tmp_path):
    client = _client(tmp_path)

    response = client.get("/api/card-images/not-cached")

    assert response.status_code == 404


def test_cors_allowed_origins_are_applied(tmp_path):
    app = create_app(
        ApiSettings(
            card_database_path=tmp_path / "cards.sqlite3",
            runtime_database_path=tmp_path / "matches.sqlite3",
            image_cache_dir=tmp_path / "images",
            web_dist_dir=tmp_path / "missing-dist",
            deck_library_root=tmp_path / "decks",
            allowed_deck_root=PROJECT_ROOT,
            allowed_origins=["https://smaillion.github.io"],
        )
    )
    client = TestClient(app)

    response = client.options(
        "/api/health",
        headers={
            "Origin": "https://smaillion.github.io",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://smaillion.github.io"


def test_health_includes_locked_database_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setenv("LOVECA_DEPLOY_GIT_SHA", "abc123")
    monkeypatch.setenv("LOVECA_DEPLOY_GIT_REF", "develop")
    monkeypatch.setenv("LOVECA_DEPLOY_GITHUB_RUN_ID", "987")
    monkeypatch.setenv("LOVECA_DEPLOY_IMAGE", "ghcr.io/example/loveca-api")
    monkeypatch.setenv("LOVECA_DEPLOY_IMAGE_TAG", "sha-abc123")
    client = _client(tmp_path)

    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["card_database_fingerprint"]
    assert payload["effect_registry_hash"]
    assert payload["deployment"] == {
        "git_sha": "abc123",
        "git_ref": "develop",
        "github_run_id": "987",
        "image": "ghcr.io/example/loveca-api",
        "image_tag": "sha-abc123",
    }


def test_backend_runtime_config_overrides_static_preview_config(tmp_path):
    card_database = tmp_path / "cards.sqlite3"
    import_normalized_cards(card_database, SAMPLE_CARDS, NORMALIZATION)
    web_dist = tmp_path / "dist"
    web_dist.mkdir()
    (web_dist / "runtime-config.json").write_text(
        (
            '{\n'
            '  "mode": "preview",\n'
            '  "browserPreview": true,\n'
            '  "apiBaseUrl": "",\n'
            '  "cardDatabaseFingerprint": "static-preview"\n'
            '}\n'
        ),
        encoding="utf-8",
    )
    (web_dist / "index.html").write_text("<!doctype html>", encoding="utf-8")

    app = create_app(
        ApiSettings(
            card_database_path=card_database,
            runtime_database_path=tmp_path / "matches.sqlite3",
            image_cache_dir=tmp_path / "images",
            web_dist_dir=web_dist,
            deck_library_root=tmp_path / "decks",
            allowed_deck_root=PROJECT_ROOT,
        )
    )
    client = TestClient(app)

    response = client.get("/runtime-config.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "release"
    assert payload["browserPreview"] is False
    assert payload["apiBaseUrl"] == ""
    assert payload["cardDatabaseFingerprint"]
    assert payload["cardDatabaseFingerprint"] != "static-preview"


def test_deck_library_api_round_trip(tmp_path):
    client = _client(tmp_path)
    deck = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))

    created = client.post(
        "/api/decks",
        json={"deck": deck, "name": "Library Deck"},
    )
    assert created.status_code == 200
    created_payload = created.json()
    deck_path = created_payload["path"]
    assert created_payload["deck"]["name"] == "Library Deck"

    listed = client.get("/api/decks")
    assert listed.status_code == 200
    assert listed.json()

    loaded = client.get(f"/api/decks/{deck_path}")
    assert loaded.status_code == 200
    assert loaded.json()["name"] == "Library Deck"

    renamed = client.post(
        f"/api/decks/{deck_path}/rename",
        json={"name": "Renamed Library Deck"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["deck"]["name"] == "Renamed Library Deck"

    deleted = client.delete(f"/api/decks/{renamed.json()['path']}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"


def test_deck_analyze_api(tmp_path):
    client = _client(tmp_path)
    sample_deck = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))

    analyze_response = client.post("/api/decks/analyze", json={"deck": sample_deck})
    assert analyze_response.status_code == 200
    analysis = analyze_response.json()
    assert "is_legal" in analysis
    assert "issues" in analysis


def test_deck_share_api_uploads_and_downloads_by_uuid(tmp_path):
    client = _client(tmp_path)
    sample_deck = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))

    uploaded = client.post("/api/deck-shares", json={"deck": sample_deck})
    assert uploaded.status_code == 200
    payload = uploaded.json()
    share_id = payload["share_id"]
    assert payload["deck"]["version"] == "decklist.v0"

    loaded = client.get(f"/api/deck-shares/{share_id}")
    assert loaded.status_code == 200
    assert loaded.json()["share_id"] == share_id
    assert loaded.json()["deck"] == payload["deck"]

    invalid = client.get("/api/deck-shares/not-a-uuid")
    assert invalid.status_code == 400


def test_catalog_api_exposes_card_review_data(tmp_path):
    client = _client(tmp_path)

    list_response = client.get("/api/catalog/cards?limit=5")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["items"]

    card_code = list_payload["items"][0]["card_code"]
    detail_response = client.get(f"/api/catalog/cards/{card_code}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["card"]["card_code"] == card_code
    assert "printings" in detail_payload
    assert "source_observations" in detail_payload
    assert "effect_registry_status" in detail_payload["card"]
    assert "effects" in detail_payload["card"]

    review_response = client.get("/api/catalog/review-candidates")
    assert review_response.status_code == 200
    review_payload = review_response.json()
    assert "items" in review_payload

    facets_response = client.get("/api/catalog/facets")
    assert facets_response.status_code == 200
    facets_payload = facets_response.json()
    assert "works" in facets_payload
    assert "units" in facets_payload


def _client(tmp_path: Path, **settings_overrides) -> TestClient:
    card_database = tmp_path / "cards.sqlite3"
    import_normalized_cards(card_database, SAMPLE_CARDS, NORMALIZATION)
    settings = {
        "card_database_path": card_database,
        "runtime_database_path": tmp_path / "matches.sqlite3",
        "image_cache_dir": tmp_path / "images",
        "web_dist_dir": tmp_path / "missing-dist",
        "deck_library_root": tmp_path / "decks",
        "allowed_deck_root": PROJECT_ROOT,
    }
    settings.update(settings_overrides)
    app = create_app(
        ApiSettings(**settings)
    )
    return TestClient(app)


def _insert_match_rows(runtime_path: Path, count: int) -> None:
    with sqlite3.connect(runtime_path) as connection:
        for index in range(count):
            timestamp = f"2026-06-15T{index // 60:02d}:{index % 60:02d}:00+00:00"
            connection.execute(
                """
                INSERT INTO matches (
                    match_id,
                    card_database_path,
                    rule_version,
                    seed,
                    status,
                    revision,
                    initial_state_json,
                    current_state_json,
                    created_at,
                    updated_at
                )
                VALUES (?, 'cards.sqlite3', 'test', ?, 'complete', 0, '{}', '{}', ?, ?)
                """,
                (f"match-{index:03d}", index, timestamp, timestamp),
            )


def _room_row(tmp_path: Path, room_code: str) -> sqlite3.Row:
    connection = sqlite3.connect(tmp_path / "matches.sqlite3")
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT * FROM hosted_rooms WHERE room_code = ?",
            (room_code,),
        ).fetchone()
        assert row is not None
        return row
    finally:
        connection.close()
