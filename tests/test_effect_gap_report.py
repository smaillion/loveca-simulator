from __future__ import annotations

import json

from tools.ai_sandbox.effect_gap_report import (
    build_effect_gap_report,
    write_gap_outputs,
)


def test_effect_gap_report_groups_manual_patterns(tmp_path):
    registry_path = tmp_path / "effect-registry.v0.json"
    registry_path.write_text(
        json.dumps(
            {
                "registry_version": "effect_registry_v0",
                "rule_version": "test",
                "effects": [
                    {
                        "effect_id": "CARD-A:1",
                        "card_code": "CARD-A",
                        "text_revision_id": 1,
                        "raw_text_hash": "a" * 64,
                        "effect_index": 1,
                        "label_ja": "【登場】カードを1枚引く。",
                        "trigger": "member_played",
                        "timing": "on_play",
                        "effect_type": "triggered",
                        "execution_mode": "manual_resolution",
                        "is_optional": False,
                        "simulation_support": "manual_resolution",
                        "review_status": "manual_required",
                        "frequency_limit": "none",
                        "actions": [{"action_type": "manual_resolution"}],
                        "source_reference": "test fixture",
                    },
                    {
                        "effect_id": "CARD-B:1",
                        "card_code": "CARD-B",
                        "text_revision_id": 2,
                        "raw_text_hash": "b" * 64,
                        "effect_index": 1,
                        "label_ja": " 【登場】カードを1枚引く。 \n",
                        "trigger": "member_played",
                        "timing": "on_play",
                        "effect_type": "triggered",
                        "execution_mode": "manual_resolution",
                        "is_optional": False,
                        "simulation_support": "manual_resolution",
                        "review_status": "manual_required",
                        "frequency_limit": "none",
                        "actions": [{"action_type": "manual_resolution"}],
                        "source_reference": "test fixture",
                    },
                    {
                        "effect_id": "CARD-C:1",
                        "card_code": "CARD-C",
                        "text_revision_id": 3,
                        "raw_text_hash": "c" * 64,
                        "effect_index": 1,
                        "label_ja": "【登場】カードを1枚引く。",
                        "trigger": "member_played",
                        "timing": "on_play",
                        "effect_type": "triggered",
                        "execution_mode": "auto_resolve",
                        "is_optional": False,
                        "simulation_support": "test_validated_executable",
                        "review_status": "test_validated",
                        "frequency_limit": "none",
                        "actions": [{"action_type": "draw_card", "amount": 1}],
                        "source_reference": "test fixture",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_effect_gap_report(
        registry_path=registry_path,
        database_path=None,
        top=10,
    )

    assert report["total_effects"] == 3
    assert report["test_validated_executable"] == 1
    assert report["manual_resolution"] == 2
    assert report["rough_executable_coverage"] == 1 / 3
    assert report["manual_by_trigger"] == {"member_played": 2}
    assert report["manual_by_card_type"] == {"unknown": 2}

    [top_pattern] = report["top_manual_patterns"]
    assert top_pattern["count"] == 2
    assert top_pattern["trigger"] == "member_played"
    assert top_pattern["timing"] == "on_play"
    assert top_pattern["label_ja"] == "【登場】カードを1枚引く。"
    assert top_pattern["sample_effect_ids"] == ["CARD-A:1", "CARD-B:1"]
    assert top_pattern["sample_card_codes"] == ["CARD-A", "CARD-B"]
    assert top_pattern["suggested_next_step"] == "on_play_exact_text_executor_candidate"


def test_effect_gap_report_writes_json_and_markdown(tmp_path):
    report = {
        "schema_version": "effect_gap_report_v0.1",
        "registry_path": "registry.json",
        "database_path": None,
        "total_effects": 1,
        "test_validated_executable": 0,
        "manual_resolution": 1,
        "rough_executable_coverage": 0.0,
        "manual_by_trigger": {"member_played": 1},
        "manual_by_timing": {"on_play": 1},
        "manual_by_card_type": {"member": 1},
        "top_manual_patterns": [
            {
                "pattern_id": "abc123",
                "count": 1,
                "trigger": "member_played",
                "timing": "on_play",
                "effect_type": "triggered",
                "frequency_limit": "none",
                "label_ja": "A|B\nC",
                "card_types": {"member": 1},
                "sample_effect_ids": ["CARD-A:1"],
                "sample_card_codes": ["CARD-A"],
                "suggested_next_step": "on_play_exact_text_executor_candidate",
            }
        ],
    }

    output_dir = tmp_path / "gap-report"
    write_gap_outputs(output_dir, report)

    parsed = json.loads((output_dir / "effect-gap-report.json").read_text(encoding="utf-8"))
    markdown = (output_dir / "effect-gap-report.md").read_text(encoding="utf-8")
    assert parsed["schema_version"] == "effect_gap_report_v0.1"
    assert "# Effect Gap Report" in markdown
    assert "| Count | Pattern | Trigger | Timing | Types | Suggested next step | Samples | Label JA |" in markdown
    assert "A\\|B<br>C" in markdown
