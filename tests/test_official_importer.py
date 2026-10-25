from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from loveca.cards.importer import import_normalized_cards
from loveca.cards.official_importer import (
    OfficialCardSourceError,
    _api_live_blade_hearts,
    _backfill_missing_names,
    _choose_gameplay_card_code,
    _discover_api_product_codes,
    _discover_api_config,
    crawl_official_card_catalog,
)

PROJECT_ROOT = Path(__file__).parents[1]
NORMALIZATION_PATH = PROJECT_ROOT / "data_sources" / "card-entity-normalization.json"


class FakeResponse:
    def __init__(self, url: str, body: str, *, content_type: str = "text/html") -> None:
        self.url = url
        self.status = 200
        self.body = body
        self.content_type = content_type
        self.fetched_at = "2026-06-14T00:00:00+00:00"
        self.error = None


class FakeSession:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, str] | None, str | None, bool]] = []

    def fetch(
        self,
        url: str,
        *,
        form_data: dict[str, str] | None = None,
        referer: str | None = None,
        ajax: bool = False,
    ) -> FakeResponse:
        self.requests.append((url, form_data, referer, ajax))
        if url.endswith("/cardlist/"):
            return FakeResponse(url, _card_list_html())
        if "title=BP01&card_kind=M" in url and "page=2" not in url:
            return FakeResponse(url, _member_search_html())
        if "title=BP01&card_kind=L" in url and "page=2" not in url:
            return FakeResponse(url, _live_search_html())
        if "title=BP01&card_kind=E" in url and "page=2" not in url:
            return FakeResponse(url, _energy_search_html())
        if "page=2" in url:
            return FakeResponse(url, "")
        if form_data and form_data.get("cardno") == "TEST-M-001":
            return FakeResponse(url, _member_detail_html())
        if form_data and form_data.get("cardno") == "TEST-L-001":
            return FakeResponse(url, _live_detail_html())
        if form_data and form_data.get("cardno") == "TEST-E-001":
            return FakeResponse(url, _energy_detail_html())
        return FakeResponse(url, "NG")


def test_crawl_official_card_catalog_writes_normalized_artifacts(tmp_path: Path):
    session = FakeSession()
    output_root = tmp_path / "official"

    result = crawl_official_card_catalog(
        session=session,
        card_list_url="https://llofficial-cardgame.com/cardlist/",
        output_root=output_root,
    )

    assert result.card_list_url == "https://llofficial-cardgame.com/cardlist/"
    assert result.discovered_product_codes == ("BP01",)
    assert len(result.cards) == 3
    assert result.normalized_path.exists()
    assert result.importer_report_path.exists()
    assert result.field_coverage_path.exists()

    payload = json.loads(result.normalized_path.read_text(encoding="utf-8"))
    assert {card["card_id"] for card in payload} == {
        "TEST-M-001",
        "TEST-L-001",
        "TEST-E-001",
    }
    assert {card["card_code"] for card in payload} == {
        "TEST-M-001",
        "TEST-L-001",
        "TEST-E-001",
    }
    assert all("import_source" in card["parse_notes"] for card in payload)

    database_path = tmp_path / "cards.sqlite3"
    summary = import_normalized_cards(database_path, result.normalized_path, NORMALIZATION_PATH)
    assert summary.records_imported == 3

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM gameplay_cards").fetchone()[0] == 3


def test_backfill_missing_names_uses_same_card_code_name():
    cards = [
        {
            "card_id": "PL!-bp3-029-PE",
            "card_code": "PL!-bp3-029",
            "name": "矢澤にこ",
            "parse_notes": {},
        },
        {
            "card_id": "PL!-bp3-029-PE＋",
            "card_code": "PL!-bp3-029",
            "name": None,
            "parse_notes": {},
        },
    ]

    enriched = _backfill_missing_names(cards)

    assert enriched[1]["name"] == "矢澤にこ"
    assert enriched[1]["parse_notes"]["name_backfilled_from_card_code"] == "PL!-bp3-029"


def test_energy_cards_with_suffix_use_full_card_id_as_gameplay_code():
    seen_gameplay_codes: dict[str, tuple[str, str]] = {}

    first = _choose_gameplay_card_code(
        card_id="PL!SP-bp1-032-PE",
        derived_card_code="PL!SP-bp1-032",
        name="ARASHI CHISATO",
        card_type="エネルギー",
        seen_gameplay_codes=seen_gameplay_codes,
    )
    second = _choose_gameplay_card_code(
        card_id="PL!SP-bp1-032-PE＋",
        derived_card_code="PL!SP-bp1-032",
        name="ARASHI CHISATO",
        card_type="エネルギー",
        seen_gameplay_codes=seen_gameplay_codes,
    )

    assert first == "PL!SP-bp1-032-PE"
    assert second == "PL!SP-bp1-032-PE+"


def test_json_api_full_blade_alias_preserves_existing_all_color_semantics():
    color, specials = _api_live_blade_hearts("[全ブレード]")

    assert color == "heart0"
    assert specials == [
        {
            "effect_type": "all_color",
            "value": 1,
            "resolution_timing": "live_success_judgment",
            "source_alt": "ALL1",
            "source_field": "ブレードハート",
        }
    ]


def test_crawl_official_json_api_normalizes_all_card_types(tmp_path: Path):
    result = crawl_official_card_catalog(
        session=FakeApiSession(),
        card_list_url="https://llofficial-cardgame.com/cardlist/",
        output_root=tmp_path / "official-api",
        card_set_codes=("BP07",),
        import_mode="incremental-set",
    )

    assert result.discovered_product_codes == ("BP07",)
    assert len(result.cards) == 3
    cards = {card["card_type"]: card for card in result.cards}

    member = cards["メンバー"]
    assert member["card_id"] == "TEST-M-001-R+"
    assert member["card_code"] == "TEST-M-001"
    assert member["member_attributes"] == {
        "cost": 9,
        "heart_by_color": {
            "heart01": None,
            "heart02": 1,
            "heart03": None,
            "heart04": 1,
            "heart05": 1,
            "heart06": None,
        },
        "blade": 3,
        "blade_heart_color": "heart02",
    }
    assert member["raw_effect_text"] == "【登場】カードを1枚引く。"
    assert member["parse_notes"]["unmapped_fields"] == [
        {"label": "作品名", "raw_text": "Aqours"},
        {"label": "参加ユニット", "raw_text": "CYaRon！"},
    ]

    live = cards["ライブ"]
    assert live["live_attributes"]["score"] == 8
    assert live["live_attributes"]["required_heart_by_color"]["heart0"] == 10
    assert live["live_attributes"]["blade_heart_color"] is None
    assert live["live_attributes"]["special_blade_hearts"] == [
        {
            "effect_type": "unknown",
            "value": 2,
            "resolution_timing": None,
            "source_alt": "無2",
            "source_field": "ブレードハート",
        }
    ]
    assert live["related_printing_ids"] == ["TEST-L-001-SECL+"]

    energy = cards["エネルギー"]
    assert energy["card_code"] == "TEST-E-001-PE+"
    assert energy["member_attributes"] is None
    assert energy["live_attributes"] is None
    assert all(card["parser_version"] == "cardlist_api_v0.1" for card in result.cards)


def test_json_api_zero_card_result_fails_closed(tmp_path: Path):
    output_root = tmp_path / "official-empty"

    with pytest.raises(OfficialCardSourceError, match="zero card records"):
        crawl_official_card_catalog(
            session=FakeEmptyApiSession(),
            card_list_url="https://llofficial-cardgame.com/cardlist/",
            output_root=output_root,
            card_set_codes=("BP07",),
            import_mode="incremental-set",
        )

    report = (output_root / "reports" / "importer-report.md").read_text(
        encoding="utf-8"
    )
    assert "* Status: `failed`" in report
    assert "website contract may have changed" in report


def test_json_api_product_discovery_ignores_non_product_filters(tmp_path: Path):
    session = FakeProductApiSession()
    card_list_url = "https://llofficial-cardgame.com/cardlist/"
    api_config = _discover_api_config(card_list_url, _api_card_list_html())
    assert api_config is not None

    inspected_pages: list[dict[str, object]] = []
    raw_files: list[str] = []
    product_codes = _discover_api_product_codes(
        session=session,
        card_list_url=card_list_url,
        api_config=api_config,
        inspected_pages=inspected_pages,
        output_raw_dir=tmp_path,
        raw_files=raw_files,
    )

    assert product_codes == ["CLLS01", "PBLL02"]
    assert "A-RISE" not in product_codes
    assert inspected_pages[0]["page_type"] == "api_products"
    assert raw_files == [str(tmp_path / "products-api.json")]


class FakeApiSession:
    def fetch(
        self,
        url: str,
        *,
        form_data: dict[str, str] | None = None,
        referer: str | None = None,
        ajax: bool = False,
    ) -> FakeResponse:
        del form_data, referer, ajax
        if url.endswith("/cardlist/"):
            return FakeResponse(url, _api_card_list_html())
        if "/list?" in url:
            query = dict(
                item.split("=", 1)
                for item in url.split("?", 1)[1].split("&")
            )
            kind = query["card_kind"]
            item = _api_list_item(kind)
            return FakeResponse(
                url,
                json.dumps({"page": 1, "per_page": 100, "total": 1, "items": [item]}),
                content_type="application/json",
            )
        if "/detail?" in url:
            api_id = int(url.rsplit("=", 1)[1])
            item = _api_list_item({101: "M", 102: "L", 103: "E"}[api_id])
            if api_id == 101:
                item |= {
                    "work_title": "Aqours",
                    "unit_name": "CYaRon！",
                    "blade_heart": "赤",
                    "expansion_name": "",
                }
            elif api_id == 102:
                item |= {"blade_heart": "8", "expansion_name": ""}
            else:
                item |= {"blade_heart": "-", "expansion_name": ""}
            related = (
                [
                    {
                        "id": 202,
                        "card_number": "TEST-L-001-SECL＋",
                        "card_name": "テストライブ",
                    }
                ]
                if api_id == 102
                else []
            )
            return FakeResponse(
                url,
                json.dumps(
                    {
                        "card": item,
                        "expansion": {
                            "id": "BP07",
                            "name": "ブースターパック MELLOW MOMENT",
                        },
                        "relationCards": related,
                    }
                ),
                content_type="application/json",
            )
        raise AssertionError(f"unexpected URL: {url}")


class FakeEmptyApiSession(FakeApiSession):
    def fetch(
        self,
        url: str,
        *,
        form_data: dict[str, str] | None = None,
        referer: str | None = None,
        ajax: bool = False,
    ) -> FakeResponse:
        if url.endswith("/cardlist/"):
            return FakeResponse(url, _api_card_list_html())
        if "/list?" in url:
            return FakeResponse(
                url,
                json.dumps({"page": 1, "per_page": 100, "total": 0, "items": []}),
                content_type="application/json",
            )
        raise AssertionError(f"unexpected URL: {url}")


class FakeProductApiSession(FakeApiSession):
    def fetch(
        self,
        url: str,
        *,
        form_data: dict[str, str] | None = None,
        referer: str | None = None,
        ajax: bool = False,
    ) -> FakeResponse:
        del form_data, referer, ajax
        if url.endswith("/products"):
            return FakeResponse(
                url,
                json.dumps(
                    {
                        "products": [
                            {
                                "year": "2026",
                                "items": [
                                    {"code": "CLLS01"},
                                    {"code": "PBLL02"},
                                ],
                            }
                        ],
                        "filters": [{"title": "A-RISE"}],
                    }
                ),
                content_type="application/json",
            )
        raise AssertionError(f"unexpected URL: {url}")


def _api_card_list_html() -> str:
    return """
    <main
      data-api-base="https://llofficial-cardgame.com/manage/card-list-user"
      data-image-base="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/"
    >
      <select><option value="BP07">BP07</option></select>
    </main>
    """


def _api_list_item(card_kind: str) -> dict[str, object]:
    common: dict[str, object] = {
        "expansion": "BP07",
        "expansion_name": "ブースターパック MELLOW MOMENT",
        "rare": "R",
        "heart0": "0",
        "heart01": "0",
        "heart02": "0",
        "heart03": "0",
        "heart04": "0",
        "heart05": "0",
        "heart06": "0",
        "text": "【登場】カードを1枚引く。",
        "text_html": (
            '<img src="/texticon/toujyou.png" alt="登場" />カードを1枚引く。'
        ),
    }
    if card_kind == "M":
        return common | {
            "id": 101,
            "picture": "BP07/TEST-M-001-R2.png",
            "card_number": "TEST-M-001-R＋",
            "card_name": "テストメンバー",
            "card_kind": "メンバー",
            "cost": "9",
            "heart02": "1",
            "heart04": "1",
            "heart05": "1",
            "attack": "3",
        }
    if card_kind == "L":
        return common | {
            "id": 102,
            "picture": "BP07/TEST-L-001-L.png",
            "card_number": "TEST-L-001-L",
            "card_name": "テストライブ",
            "card_kind": "ライブ",
            "rare": "L",
            "cost": "-",
            "heart0": "10",
            "heart02": "3",
            "heart04": "3",
            "heart05": "3",
            "attack": "無2",
        }
    return common | {
        "id": 103,
        "picture": "BP07/TEST-E-001-PE2.png",
        "card_number": "TEST-E-001-PE＋",
        "card_name": "テストエネルギー",
        "card_kind": "エネルギー",
        "rare": "PE+",
        "cost": "-",
        "attack": "-",
        "text": "",
        "text_html": "",
    }


def _card_list_html() -> str:
    return """
    <html>
      <body>
        <a href="/cardlist/searchresults/?title=BP01&card_kind=M">M</a>
        <a href="/cardlist/searchresults/?title=BP01&card_kind=L">L</a>
        <a href="/cardlist/searchresults/?title=BP01&card_kind=E">E</a>
        <select><option value="BP01">BP01</option></select>
      </body>
    </html>
    """


def _member_search_html() -> str:
    return """
    <div class="card" card="TEST-M-001">
      <img src="/img/member.png" alt="テストメンバー" />
    </div>
    """


def _live_search_html() -> str:
    return """
    <div class="card" card="TEST-L-001">
      <img src="/img/live.png" alt="テストライブ" />
    </div>
    """


def _energy_search_html() -> str:
    return """
    <div class="card" card="TEST-E-001">
      <img src="/img/energy.png" alt="テストエネルギー" />
    </div>
    """


def _member_detail_html() -> str:
    return """
    <div class="cardlist-Item cardlist-Info">
      <div class="info-Image">
        <div class="image"><img src="/wordpress/wp-content/images/cardlist/BP06/TEST-M-001.png"
          alt="テストメンバー"/></div>
      </div>
      <p class="info-Heading">テストメンバー</p>
      <dl class="info-Dl">
        <div class="dl-Item"><dt><span>収録商品</span></dt><dd>テスト商品</dd></div>
        <div class="dl-Item"><dt><span>カードタイプ</span></dt><dd>メンバー</dd></div>
        <div class="dl-Item"><dt><span>作品名</span></dt><dd>ラブライブ！</dd></div>
        <div class="dl-Item"><dt><span>コスト</span></dt><dd>2</dd></div>
        <div class="dl-Item"><dt><span>基本ハート</span></dt><dd>
          <span class="icon heart01">1</span><span class="icon heart06">2</span>
        </dd></div>
        <div class="dl-Item"><dt><span>ブレードハート</span></dt>
          <dd><span class="icon b_heart06"></span></dd></div>
        <div class="dl-Item"><dt><span>ブレード</span></dt><dd>1</dd></div>
        <div class="dl-Item"><dt><span>レアリティ</span></dt><dd>R</dd></div>
        <div class="dl-Item"><dt><span>カード番号</span></dt><dd>TEST-M-001</dd></div>
      </dl>
      <p class="info-Text"><img src="/icon/auto.png" alt="自動" />登場した時、1枚引く。</p>
    </div>
    """


def _live_detail_html() -> str:
    return """
    <div class="cardlist-Item cardlist-Info">
      <div class="info-Image"><div class="image">
        <img src="/wordpress/wp-content/images/cardlist/BP06/TEST-L-001.png"
          alt="テストライブ"/>
      </div></div>
      <p class="info-Heading">テストライブ</p>
      <dl class="info-Dl">
        <div class="dl-Item"><dt><span>収録商品</span></dt><dd>テスト商品</dd></div>
        <div class="dl-Item"><dt><span>カードタイプ</span></dt><dd>ライブ</dd></div>
        <div class="dl-Item"><dt><span>スコア</span></dt><dd>7</dd></div>
        <div class="dl-Item"><dt><span>必要ハート</span></dt><dd>
          <span class="icon heart01">3</span>
          <span class="icon heart06">3</span>
          <span class="icon heart0">6</span>
        </dd></div>
        <div class="dl-Item"><dt><span>ブレードハート</span></dt>
          <dd><img src="/icon/all.png" alt="ALL1"/></dd></div>
        <div class="dl-Item"><dt><span>特殊ハート</span></dt>
          <dd><img src="/icon/score.png" alt="スコア1"/></dd></div>
        <div class="dl-Item"><dt><span>レアリティ</span></dt><dd>L</dd></div>
        <div class="dl-Item"><dt><span>カード番号</span></dt><dd>TEST-L-001</dd></div>
      </dl>
      <p class="info-Text"><img src="/icon/start.png" alt="ライブ開始時" />スコアを＋1する。</p>
    </div>
    """


def _energy_detail_html() -> str:
    return """
    <div class="cardlist-Item cardlist-Info">
      <div class="info-Image"><div class="image">
        <img src="/wordpress/wp-content/images/cardlist/BP06/TEST-E-001.png"
          alt="テストエネルギー"/>
      </div></div>
      <p class="info-Heading">テストエネルギー</p>
      <dl class="info-Dl">
        <div class="dl-Item"><dt><span>収録商品</span></dt><dd>テスト商品</dd></div>
        <div class="dl-Item"><dt><span>カードタイプ</span></dt><dd>エネルギー</dd></div>
        <div class="dl-Item"><dt><span>レアリティ</span></dt><dd>E</dd></div>
        <div class="dl-Item"><dt><span>カード番号</span></dt><dd>TEST-E-001</dd></div>
      </dl>
    </div>
    """
