from __future__ import annotations

import copy
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


def test_catalog_api_lists_cards_and_reviews(tmp_path):
    client = _client(tmp_path)

    response = client.get("/api/catalog/cards?limit=10")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert len(payload["items"]) <= 10
    first_card = payload["items"][0]
    assert first_card["card_code"]
    assert first_card["name_ja"]

    detail = client.get(f"/api/catalog/cards/{first_card['card_code']}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["card"]["card_code"] == first_card["card_code"]
    assert isinstance(detail_payload["printings"], list)
    assert isinstance(detail_payload["source_observations"], list)
    assert isinstance(detail_payload["text_revisions"], list)

    review = client.get("/api/catalog/review-candidates?limit=10")
    assert review.status_code == 200
    review_payload = review.json()
    assert "items" in review_payload
    assert review_payload["limit"] == 10

    facets = client.get("/api/catalog/facets")
    assert facets.status_code == 200
    facets_payload = facets.json()
    assert "works" in facets_payload
    assert "units" in facets_payload

    if facets_payload["works"]:
        filtered = client.get(
            f"/api/catalog/cards?work_key={facets_payload['works'][0]['work_key']}&limit=10"
        )
        assert filtered.status_code == 200
        assert filtered.json()["items"]


def test_catalog_search_matches_non_primary_printing_ids_and_dedupes_entities(tmp_path):
    (
        duplicate_fixture,
        duplicate_card_id,
        duplicate_card_code,
        original_card_id,
    ) = _build_duplicate_printing_fixture(
        tmp_path
    )
    client = _client(tmp_path, sample_cards=duplicate_fixture)

    response = client.get("/api/catalog/cards", params={"q": duplicate_card_id, "limit": 10})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["card_code"] == duplicate_card_code
    assert payload["items"][0]["printing_count"] == 2

    detail = client.get(f"/api/catalog/cards/{duplicate_card_code}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert len(detail_payload["printings"]) == 2
    assert sorted(printing["card_id"] for printing in detail_payload["printings"]) == sorted(
        [original_card_id, duplicate_card_id]
    )
    assert len(detail_payload["card"]["works"]) == len(
        {
            (item["work_key"], item["canonical_name_ja"], item["raw_label_ja"])
            for item in detail_payload["card"]["works"]
        }
    )
    assert len(detail_payload["card"]["units"]) == len(
        {
            (item["unit_key"], item["canonical_name_ja"], item["raw_label_ja"])
            for item in detail_payload["card"]["units"]
        }
    )


def test_catalog_api_lists_distinct_card_ids_as_distinct_rows(tmp_path):
    (
        duplicate_fixture,
        duplicate_card_id,
        duplicate_card_code,
        original_card_id,
    ) = _build_duplicate_printing_fixture(tmp_path)
    client = _client(tmp_path, sample_cards=duplicate_fixture)

    response = client.get("/api/catalog/cards", params={"limit": 10})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert [item["card_code"] for item in payload["items"]] == [
        duplicate_card_code,
        duplicate_card_code,
    ]
    assert sorted(item["card_id"] for item in payload["items"]) == sorted(
        [original_card_id, duplicate_card_id]
    )


def test_catalog_api_supports_member_and_live_attribute_filters(tmp_path):
    client = _client(tmp_path)

    all_cards = client.get("/api/catalog/cards?limit=100").json()["items"]
    member = next(
        item
        for item in all_cards
        if item["card_type"] == "member"
        and item["cost"] is not None
        and item["blade"] is not None
        and item["basic_heart_by_color"]
    )
    member_color = next(iter(member["basic_heart_by_color"].keys()))
    member_response = client.get(
        "/api/catalog/cards",
        params={
            "card_type": "member",
            "basic_heart_color": member_color,
            "member_cost_min": member["cost"],
            "member_cost_max": member["cost"],
            "member_blade_min": member["blade"],
            "member_blade_max": member["blade"],
            "limit": 100,
        },
    )
    assert member_response.status_code == 200
    member_payload = member_response.json()
    assert any(item["card_code"] == member["card_code"] for item in member_payload["items"])
    assert all(item["basic_heart_by_color"].get(member_color, 0) > 0 for item in member_payload["items"])

    live = next(
        item
        for item in all_cards
        if item["card_type"] == "live"
        and item["score"] is not None
        and item["required_heart_by_color"]
    )
    required_color = next(iter(live["required_heart_by_color"].keys()))
    required_amount = live["required_heart_by_color"][required_color]
    live_response = client.get(
        "/api/catalog/cards",
        params={
            "card_type": "live",
            "required_heart_color": required_color,
            "required_heart_min": required_amount,
            "required_heart_max": required_amount,
            "live_score_min": live["score"],
            "live_score_max": live["score"],
            "has_live_blade_heart": str(live["has_live_blade_heart"]).lower(),
            "limit": 100,
        },
    )
    assert live_response.status_code == 200
    live_payload = live_response.json()
    assert any(item["card_code"] == live["card_code"] for item in live_payload["items"])
    assert all(item["required_heart_by_color"].get(required_color, 0) >= required_amount for item in live_payload["items"])


def test_catalog_api_type_specific_filters_do_not_cross_eliminate_other_card_types(tmp_path):
    client = _client(tmp_path)

    all_cards = client.get("/api/catalog/cards?limit=200").json()["items"]
    member = next(
        item
        for item in all_cards
        if item["card_type"] == "member"
        and item["basic_heart_by_color"]
        and item["cost"] is not None
    )
    live = next(
        item
        for item in all_cards
        if item["card_type"] == "live"
        and item["required_heart_by_color"]
        and item["score"] is not None
    )
    member_color = next(iter(member["basic_heart_by_color"].keys()))
    live_color = next(iter(live["required_heart_by_color"].keys()))

    response = client.get(
        "/api/catalog/cards",
        params={
            "basic_heart_color": member_color,
            "member_cost_min": member["cost"],
            "member_cost_max": member["cost"],
            "required_heart_color": live_color,
            "live_score_min": live["score"],
            "live_score_max": live["score"],
            "limit": 200,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    card_types = {item["card_type"] for item in payload["items"]}
    assert "member" in card_types
    assert "live" in card_types


def _client(tmp_path: Path, sample_cards: Path = SAMPLE_CARDS) -> TestClient:
    database_path = tmp_path / "cards.sqlite3"
    import_normalized_cards(database_path, sample_cards, NORMALIZATION)
    app = create_app(
        ApiSettings(
            card_database_path=database_path,
            runtime_database_path=tmp_path / "matches.sqlite3",
            image_cache_dir=tmp_path / "images",
            web_dist_dir=tmp_path / "missing-dist",
            deck_library_root=tmp_path / "decks",
            allowed_deck_root=PROJECT_ROOT,
        )
    )
    return TestClient(app)


def _build_duplicate_printing_fixture(tmp_path: Path) -> tuple[Path, str, str, str]:
    records = json.loads(SAMPLE_CARDS.read_text(encoding="utf-8"))
    base_record = next(
        record
        for record in records
        if any(
            field.get("label") == "作品名"
            for field in (record.get("parse_notes", {}).get("unmapped_fields") or [])
            if isinstance(field, dict)
        )
        and any(
            field.get("label") == "参加ユニット"
            for field in (record.get("parse_notes", {}).get("unmapped_fields") or [])
            if isinstance(field, dict)
        )
    )
    duplicate = copy.deepcopy(base_record)
    duplicate["card_id"] = f"{base_record['card_code']}-QA2"
    duplicate["rarity"] = "QA+"
    duplicate["image_url"] = None
    duplicate["source_url"] = (
        "https://llofficial-cardgame.com/cardlist/searchresults/"
        f"?title={base_record['product_code']}&cardno={duplicate['card_id']}"
    )
    duplicate["printing_group_ids"] = [base_record["card_id"], duplicate["card_id"]]
    fixture_path = tmp_path / "duplicate-printing.json"
    fixture_path.write_text(
        json.dumps([base_record, duplicate], ensure_ascii=False),
        encoding="utf-8",
    )
    return (
        fixture_path,
        str(duplicate["card_id"]),
        str(base_record["card_code"]),
        str(base_record["card_id"]),
    )
