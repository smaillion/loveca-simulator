from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from loveca.simulation.effect_candidates import discover_effect_candidates
from tools.ai_sandbox.effect_registry_integrity import audit_effect_registry


DUAL_TEXT = (
    "【登場】/【ライブ開始時】カードを1枚引く。"
    " 【自動】カードを1枚引く。"
)


def test_integrity_accepts_dual_timing_alias_bound_to_shared_body(tmp_path: Path):
    database = tmp_path / "cards.sqlite3"
    registry = tmp_path / "registry.json"
    _write_database(database, [(1, "a" * 64, DUAL_TEXT)])
    _write_registry(
        registry,
        [
            _effect(
                effect_index=1,
                text_revision_id=1,
                raw_text_hash="a" * 64,
                label="【登場】/【ライブ開始時】カードを1枚引く。",
                timing="on_play",
                trigger="member_played",
                frequency="none",
            ),
            _effect(
                effect_index=2,
                text_revision_id=1,
                raw_text_hash="a" * 64,
                label="【ライブ開始時】カードを1枚引く。",
                timing="live_start",
                trigger="live_started",
                frequency="once_per_live",
            ),
            _effect(
                effect_index=3,
                text_revision_id=1,
                raw_text_hash="a" * 64,
                label="【自動】カードを1枚引く。",
                timing="auto_triggered_event",
                trigger="auto_triggered_event",
                frequency="none",
            ),
        ],
    )

    result = audit_effect_registry(database, registry)

    assert result.error_count == 0
    assert result.registry_effect_count == 3


def test_integrity_reports_mojibake_and_label_drift(tmp_path: Path):
    database = tmp_path / "cards.sqlite3"
    registry = tmp_path / "registry.json"
    _write_database(database, [(1, "a" * 64, "【登場】カードを1枚引く。")])
    payload = _effect(
        effect_index=1,
        text_revision_id=1,
        raw_text_hash="a" * 64,
        label="????????",
        timing="on_play",
        trigger="member_played",
        frequency="none",
    )
    _write_registry(registry, [payload])

    result = audit_effect_registry(database, registry)

    assert {issue.code for issue in result.issues} >= {
        "label_mismatch",
        "mojibake_label",
    }


def test_candidate_discovery_prefers_registered_text_revision(tmp_path: Path):
    database = tmp_path / "cards.sqlite3"
    registry = tmp_path / "registry.json"
    _write_database(
        database,
        [
            (1, "a" * 64, "【登場】古いテキスト。"),
            (2, "b" * 64, "【登場】新しいテキスト。"),
        ],
    )
    _write_registry(
        registry,
        [
            _effect(
                effect_index=1,
                text_revision_id=2,
                raw_text_hash="b" * 64,
                label="【登場】新しいテキスト。",
                timing="on_play",
                trigger="member_played",
                frequency="none",
            )
        ],
    )

    candidates = discover_effect_candidates(
        database,
        registry_path=registry,
        include_registered=True,
    )

    assert len(candidates) == 1
    assert candidates[0].text_revision_id == 2
    assert candidates[0].label_ja == "【登場】新しいテキスト。"


def _write_database(
    path: Path,
    revisions: list[tuple[int, str, str]],
) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE gameplay_cards (
                id INTEGER PRIMARY KEY,
                card_code TEXT NOT NULL,
                card_type TEXT NOT NULL
            );
            CREATE TABLE card_text_revisions (
                id INTEGER PRIMARY KEY,
                gameplay_card_id INTEGER NOT NULL,
                raw_text_hash TEXT NOT NULL,
                raw_effect_text_ja TEXT NOT NULL
            );
            INSERT INTO gameplay_cards (id, card_code, card_type)
            VALUES (1, 'TEST-001', 'member');
            """
        )
        connection.executemany(
            """
            INSERT INTO card_text_revisions (
                id, gameplay_card_id, raw_text_hash, raw_effect_text_ja
            ) VALUES (?, 1, ?, ?)
            """,
            revisions,
        )


def _write_registry(path: Path, effects: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {
                "registry_version": "effect-registry.v0",
                "rule_version": "1.06",
                "effects": effects,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _effect(
    *,
    effect_index: int,
    text_revision_id: int,
    raw_text_hash: str,
    label: str,
    timing: str,
    trigger: str,
    frequency: str,
) -> dict[str, object]:
    return {
        "effect_id": f"TEST-001:{effect_index}",
        "card_code": "TEST-001",
        "text_revision_id": text_revision_id,
        "raw_text_hash": raw_text_hash,
        "effect_index": effect_index,
        "label_ja": label,
        "effect_type": "triggered",
        "timing": timing,
        "trigger": trigger,
        "execution_mode": "manual_resolution",
        "frequency_limit": frequency,
        "is_optional": False,
        "condition": {},
        "cost": [],
        "choice": None,
        "actions": [{"action_type": "manual_resolution"}],
        "duration": None,
        "simulation_support": "manual_resolution",
        "review_status": "parsed_draft",
        "source_reference": "test",
        "cost_choice": None,
        "follow_up_choice": None,
    }
