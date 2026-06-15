from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from loveca.cards.importer import import_normalized_cards
from loveca.cards.official_importer import (
    _backfill_missing_names,
    _choose_gameplay_card_code,
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
