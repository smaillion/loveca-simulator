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
SAMPLE_DECK = PROJECT_ROOT / "tests" / "fixtures" / "legal-deck.json"


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
    assert payload["state"]["players"]["player_1"]["member_area_attachments"] == {
        "left": [],
        "center": [],
        "right": [],
    }
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

    review_response = client.get("/api/catalog/review-candidates")
    assert review_response.status_code == 200
    review_payload = review_response.json()
    assert "items" in review_payload

    facets_response = client.get("/api/catalog/facets")
    assert facets_response.status_code == 200
    facets_payload = facets_response.json()
    assert "works" in facets_payload
    assert "units" in facets_payload


def _client(tmp_path: Path) -> TestClient:
    card_database = tmp_path / "cards.sqlite3"
    import_normalized_cards(card_database, SAMPLE_CARDS, NORMALIZATION)
    app = create_app(
        ApiSettings(
            card_database_path=card_database,
            runtime_database_path=tmp_path / "matches.sqlite3",
            image_cache_dir=tmp_path / "images",
            web_dist_dir=tmp_path / "missing-dist",
            deck_library_root=tmp_path / "decks",
            allowed_deck_root=PROJECT_ROOT,
        )
    )
    return TestClient(app)
