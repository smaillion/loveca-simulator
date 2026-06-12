from __future__ import annotations

import json
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
SAMPLE_DECK = PROJECT_ROOT / "examples" / "decks" / "sample-deck.json"


def test_match_api_create_act_resume_and_replay(tmp_path):
    client = _client(tmp_path)
    deck = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))

    response = client.post(
        "/api/matches",
        json={
            "player_1": {"name": "Player A", "deck": deck},
            "player_2": {"name": "Player B", "deck": deck},
            "seed": 106,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    match_id = payload["state"]["match_id"]
    assert payload["state"]["revision"] == 0
    assert payload["legal_actions"][0]["action_type"] == "choose_first_player"

    action_response = client.post(
        f"/api/matches/{match_id}/actions",
        json={
            "action_type": "choose_first_player",
            "expected_revision": 0,
            "payload": {"first_player_id": "player_1"},
        },
    )
    assert action_response.status_code == 200
    assert action_response.json()["state"]["revision"] == 1

    resumed = client.get(f"/api/matches/{match_id}")
    assert resumed.status_code == 200
    assert resumed.json()["state"]["phase"] == "setup_mulligan_first"
    assert resumed.json()["events"]

    replay = client.get(f"/api/matches/{match_id}/replay")
    assert replay.status_code == 200
    assert replay.json()["final_state"]["revision"] == 1


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
            "action_type": "choose_first_player",
            "expected_revision": 9,
            "payload": {"first_player_id": "player_1"},
        },
    )

    assert response.status_code == 409
    assert client.get(f"/api/matches/{match_id}").json()["state"]["revision"] == 0


def test_uncached_card_image_returns_404(tmp_path):
    client = _client(tmp_path)

    response = client.get("/api/card-images/not-cached")

    assert response.status_code == 404


def _client(tmp_path: Path) -> TestClient:
    card_database = tmp_path / "cards.sqlite3"
    import_normalized_cards(card_database, SAMPLE_CARDS, NORMALIZATION)
    app = create_app(
        ApiSettings(
            card_database_path=card_database,
            runtime_database_path=tmp_path / "matches.sqlite3",
            image_cache_dir=tmp_path / "images",
            web_dist_dir=tmp_path / "missing-dist",
            allowed_deck_root=PROJECT_ROOT,
        )
    )
    return TestClient(app)
