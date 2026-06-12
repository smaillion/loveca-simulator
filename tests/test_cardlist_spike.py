from __future__ import annotations

from pathlib import Path

from tools.importer_spike.cardlist_sample import (
    CROSS_PRODUCT_CODES,
    CROSS_PRODUCT_KIND_QUOTAS,
    CROSS_PRODUCT_SAMPLE_SIZE,
    PARSER_VERSION,
    OfficialSiteSession,
    allocate_sample_counts,
    derive_card_code,
    extract_related_printing_ids,
    extract_special_blade_hearts,
    inspect_html,
    make_product_card_kind_search_url,
    normalize_card,
    prepare_cross_product_output_dirs,
    read_card_list_url,
    select_distinct_card_codes,
    write_cross_product_report,
    write_field_coverage,
)


def test_read_card_list_url_uses_manifest_card_list_entry(tmp_path: Path):
    manifest = tmp_path / "source-manifest.yaml"
    manifest.write_text(
        """
sources:
  official_root:
    url: "https://example.invalid/"
  card_list:
    url: "https://llofficial-cardgame.com/cardlist/"
    type: "card_database"
""".strip(),
        encoding="utf-8",
    )

    assert read_card_list_url(manifest) == "https://llofficial-cardgame.com/cardlist/"


def test_sample_allocation_is_stratified_and_exact():
    assert allocate_sample_counts(12) == {"M": 5, "L": 5, "E": 2}
    for limit in range(10, 31):
        counts = allocate_sample_counts(limit)
        assert sum(counts.values()) == limit
        assert all(count > 0 for count in counts.values())


def test_cross_product_matrix_is_fixed_at_thirty_cards():
    assert CROSS_PRODUCT_CODES == ("BP01", "BP03", "BP06", "PLSD01", "HSSD01", "PR")
    assert CROSS_PRODUCT_KIND_QUOTAS == (
        ("M", "member", 2),
        ("L", "live", 2),
        ("E", "energy", 1),
    )
    assert CROSS_PRODUCT_SAMPLE_SIZE == 30


def test_product_card_kind_search_url_contains_both_filters():
    url = make_product_card_kind_search_url(
        "https://llofficial-cardgame.com/cardlist/",
        "BP01",
        "L",
    )

    assert url == (
        "https://llofficial-cardgame.com/cardlist/searchresults/"
        "?title=BP01&card_kind=L"
    )


def test_card_code_deduplication_preserves_full_printing_id():
    candidates = [
        {"card_id": "PL!-bp6-001-R＋"},
        {"card_id": "PL!-bp6-001-P"},
        {"card_id": "PL!-bp6-002-R"},
        {"card_id": "PL!-bp6-E01-SECE"},
    ]

    selected = select_distinct_card_codes(candidates, quota=3)

    assert [card["card_id"] for card in selected] == [
        "PL!-bp6-001-R＋",
        "PL!-bp6-002-R",
        "PL!-bp6-E01-SECE",
    ]
    assert [card["card_code"] for card in selected] == [
        "PL!-bp6-001",
        "PL!-bp6-002",
        "PL!-bp6-E01",
    ]
    assert derive_card_code("LL-E-001-SD") == "LL-E-001"


def test_related_printing_ids_are_preserved():
    content = """
    <div onclick="relatedCard('PL!-bp6-001-P', 'card_detail_1');"></div>
    <div onclick="relatedCard('PL!-bp6-001-SEC', 'card_detail_2');"></div>
    """

    assert extract_related_printing_ids(content) == [
        "PL!-bp6-001-P",
        "PL!-bp6-001-SEC",
    ]


def test_cross_product_output_cleanup_does_not_touch_baseline(tmp_path: Path):
    baseline_json = tmp_path / "normalized" / "cards-sample.json"
    baseline_report = tmp_path / "reports" / "importer-spike-report.md"
    baseline_json.parent.mkdir(parents=True)
    baseline_report.parent.mkdir(parents=True)
    baseline_json.write_text("baseline-json", encoding="utf-8")
    baseline_report.write_text("baseline-report", encoding="utf-8")
    cross_raw = tmp_path / "raw" / "cross-product"
    cross_raw.mkdir(parents=True)
    (cross_raw / "old.html").write_text("old", encoding="utf-8")

    prepare_cross_product_output_dirs(tmp_path)

    assert baseline_json.read_text(encoding="utf-8") == "baseline-json"
    assert baseline_report.read_text(encoding="utf-8") == "baseline-report"
    assert list(cross_raw.iterdir()) == []


def test_official_session_rejects_other_domains_without_requesting():
    session = OfficialSiteSession("llofficial-cardgame.com", delay=1.0)

    result = session.fetch("https://unofficial.example/cardlist/")

    assert result.error == "refused non-official or non-HTTPS URL"


def test_inspect_html_keeps_same_domain_discoveries():
    content = """
    <a href="/cardlist/card-detail/?cardno=TEST-001">card</a>
    <a href="/cardlist/?paged=2">next</a>
    <script src="/wp-json/cardlist/index.json"></script>
    <img src="/wordpress/wp-content/uploads/card.png">
    <a href="https://unofficial.example/cards">external</a>
    """

    result = inspect_html(
        "https://llofficial-cardgame.com/cardlist/",
        content,
        "llofficial-cardgame.com",
    )

    assert result["detail_page_urls"] == [
        "https://llofficial-cardgame.com/cardlist/card-detail/?cardno=TEST-001"
    ]
    assert result["pagination_urls"] == ["https://llofficial-cardgame.com/cardlist/?paged=2"]
    assert result["same_domain_api_candidates"] == [
        "https://llofficial-cardgame.com/wp-json/cardlist/index.json"
    ]


def test_member_detail_parses_typed_attributes_and_raw_effect_text():
    content = """
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

    card = normalize_card(
        "https://llofficial-cardgame.com/cardlist/searchresults/?cardno=TEST-M-001",
        content,
        "2026-06-06T00:00:00+00:00",
    )

    assert card["card_id"] == "TEST-M-001"
    assert card["name"] == "テストメンバー"
    assert card["card_type"] == "メンバー"
    assert card["product"] == "テスト商品"
    assert card["rarity"] == "R"
    assert card["member_attributes"] == {
        "cost": 2,
        "heart_by_color": {
            "heart01": 1,
            "heart02": None,
            "heart03": None,
            "heart04": None,
            "heart05": None,
            "heart06": 2,
        },
        "blade": 1,
        "blade_heart_color": "heart06",
    }
    assert card["live_attributes"] is None
    assert card["raw_effect_text"] == "【自動】登場した時、1枚引く。"
    assert card["parser_version"] == PARSER_VERSION
    assert card["parse_notes"]["detail_method"] == "POST"
    assert card["parse_notes"]["unmapped_fields"] == [
        {"label": "作品名", "raw_text": "ラブライブ！"}
    ]


def test_live_detail_parses_required_hearts_without_blade():
    content = """
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

    card = normalize_card(
        "https://llofficial-cardgame.com/cardlist/searchresults/?cardno=TEST-L-001",
        content,
        "2026-06-06T00:00:00+00:00",
    )

    assert card["member_attributes"] is None
    assert card["live_attributes"] == {
        "required_heart_by_color": {
            "heart0": 6,
            "heart01": 3,
            "heart02": None,
            "heart03": None,
            "heart04": None,
            "heart05": None,
            "heart06": 3,
        },
        "score": 7,
        "blade_heart_color": "heart0",
        "special_blade_hearts": [
            {
                "effect_type": "all_color",
                "value": 1,
                "resolution_timing": "live_success_judgment",
                "source_alt": "ALL1",
                "source_field": "ブレードハート",
            },
            {
                "effect_type": "score",
                "value": 1,
                "resolution_timing": "live_judgment",
                "source_alt": "スコア1",
                "source_field": "特殊ハート",
            }
        ],
    }
    assert "blade" not in card["live_attributes"]
    assert card["parse_notes"]["unmapped_fields"] == []


def test_energy_detail_has_no_type_specific_attributes():
    content = """
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

    card = normalize_card(
        "https://llofficial-cardgame.com/cardlist/searchresults/?cardno=TEST-E-001",
        content,
        "2026-06-06T00:00:00+00:00",
    )

    assert card["card_type"] == "エネルギー"
    assert card["member_attributes"] is None
    assert card["live_attributes"] is None
    assert card["raw_effect_text"] is None
    assert "energy_attributes" not in card


def test_special_blade_heart_icons_preserve_known_and_unknown_alts():
    field_html = """
    <img src="/icon/draw.png" alt="ドロー1"/>
    <img src="/icon/all.png" alt="ALL1"/>
    <img src="/icon/future.png" alt="未確認2"/>
    """

    assert extract_special_blade_hearts(field_html) == [
        {
            "effect_type": "draw",
            "value": 1,
            "resolution_timing": "after_yell",
            "source_alt": "ドロー1",
            "source_field": "特殊ハート",
        },
        {
            "effect_type": "all_color",
            "value": 1,
            "resolution_timing": "live_success_judgment",
            "source_alt": "ALL1",
            "source_field": "特殊ハート",
        },
        {
            "effect_type": "unknown",
            "value": None,
            "resolution_timing": None,
            "source_alt": "未確認2",
            "source_field": "特殊ハート",
        },
    ]


def test_field_coverage_report_has_required_columns(tmp_path: Path):
    output = tmp_path / "coverage.md"
    write_field_coverage(output, [])

    text = output.read_text(encoding="utf-8")

    assert "| field | extracted_count | missing_count | confidence | notes |" in text


def test_cross_product_report_marks_missing_bucket_as_partial(tmp_path: Path):
    output = tmp_path / "cross-product.md"
    write_cross_product_report(
        output,
        card_list_url="https://llofficial-cardgame.com/cardlist/",
        inspected_pages=[],
        raw_files=[],
        cards=[],
        bucket_results=[
            {
                "product_code": "BP01",
                "card_kind": "M",
                "kind_name": "member",
                "requested": 2,
                "selected": 1,
                "successful": 0,
                "pagination_used": True,
                "search_error": None,
            }
        ],
        requested_count=30,
        access_limited=False,
    )

    text = output.read_text(encoding="utf-8")
    assert "* Status: `partial_sample`" in text
    assert "| `BP01` | `member` | 2 | 1 | 0 | 0 | 0 | `true` | - |" in text
    assert "| `draw` | `ドローn` | 0 | - | `not_observed` |" in text
