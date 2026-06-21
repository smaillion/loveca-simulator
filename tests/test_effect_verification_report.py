from __future__ import annotations

import json
import sqlite3

from tools.ai_sandbox.effect_verification_report import (
    run_effect_verification_scenarios,
    write_effect_verification_report,
)


def test_effect_verification_report_covers_branch_fix_scenarios(tmp_path):
    database = tmp_path / "cards.sqlite3"
    _write_report_image_fixture(database)
    results = run_effect_verification_scenarios(database_path=database)

    assert {result.scenario_id for result in results} == {
        "baton_repeat_prevention",
        "pl_hs_bp2_026_live_start_score_modifier",
        "pl_hs_bp6_006_cost_reduction",
        "pl_hs_bp6_006_live_success_skip_ready",
        "pl_hs_bp6_014_with_target",
        "pl_hs_bp6_014_without_target",
        "pl_hs_sd1_005_same_name_baton_blocked",
    }
    assert all(result.status == "PASS" for result in results)

    write_effect_verification_report(tmp_path, results)

    markdown = (tmp_path / "effect-verification-report.md").read_text(encoding="utf-8")
    zh_markdown = (tmp_path / "effect-verification-report.zh-CN.md").read_text(
        encoding="utf-8"
    )
    summary = json.loads(
        (tmp_path / "effect-verification-summary.json").read_text(encoding="utf-8")
    )

    assert "PL!HS-bp6-014: 手札起動、Blade 対象なし" in markdown
    assert "PL!HS-bp6-006: みらくらぱーく！人数による登場 cost 軽減" in markdown
    assert "Baton Touch: 同一ターンの二重 Baton 防止" in markdown
    assert "PL!HS-sd1-005: 徒町小鈴からの Baton では登場時回収しない" in markdown
    assert "起動元が控室にある: OK" in markdown
    assert '<img src="https://example.test/hime.png"' in markdown
    assert '<img src="https://example.test/hime-bp6.png"' in markdown
    assert '<img src="https://example.test/kosuzu.png"' in markdown
    assert "PL!HS-bp6-014：从手牌发动，无 Blade 目标" in zh_markdown
    assert "PL!HS-bp6-006：按みらくらぱーく！人数降低登场 cost" in zh_markdown
    assert "Baton Touch：防止同一回合二次 Baton" in zh_markdown
    assert "发动源在控室: OK" in zh_markdown
    assert summary["schema_version"] == "effect_verification_report_v0.2"
    assert summary["passed"] == 7


def _write_report_image_fixture(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE gameplay_cards (
            id INTEGER PRIMARY KEY,
            card_code TEXT NOT NULL,
            canonical_name_ja TEXT NOT NULL
        );
        CREATE TABLE card_printings (
            id INTEGER PRIMARY KEY,
            card_id TEXT NOT NULL,
            gameplay_card_id INTEGER NOT NULL,
            image_url TEXT
        );
        """
    )
    cards = [
        (1, "PL!HS-bp6-014", "安養寺 姫芽", "PL!HS-bp6-014-R", "https://example.test/hime.png"),
        (2, "PL!HS-bp1-006", "藤島 慈", "PL!HS-bp1-006-R", "https://example.test/megumi.png"),
        (3, "PL!HS-bp1-007", "大沢 瑠璃乃", "PL!HS-bp1-007-R", "https://example.test/rurino.png"),
        (4, "PL!HS-bp6-006", "安養寺 姫芽", "PL!HS-bp6-006-R", "https://example.test/hime-bp6.png"),
        (5, "PL!HS-bp2-026", "みらくりえーしょん", "PL!HS-bp2-026-R", "https://example.test/miracreation.png"),
        (6, "PL!HS-sd1-005", "徒町 小鈴", "PL!HS-sd1-005-SD", "https://example.test/kosuzu.png"),
    ]
    for card_id, card_code, name_ja, printing_id, image_url in cards:
        connection.execute(
            "INSERT INTO gameplay_cards (id, card_code, canonical_name_ja) VALUES (?, ?, ?)",
            (card_id, card_code, name_ja),
        )
        connection.execute(
            "INSERT INTO card_printings (card_id, gameplay_card_id, image_url) VALUES (?, ?, ?)",
            (printing_id, card_id, image_url),
        )
    connection.commit()
    connection.close()
