from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.ai_sandbox.register_effect_candidates import (
    CandidateRegistrationError,
    merge_candidates,
)


def test_merge_candidates_adds_valid_effect_without_mutating_source(tmp_path: Path):
    registry_path = tmp_path / "registry.json"
    candidates_path = tmp_path / "candidates.json"
    registry_path.write_text(
        json.dumps(
            {
                "registry_version": "effect-registry.v0",
                "rule_version": "1.06",
                "effects": [],
            }
        ),
        encoding="utf-8",
    )
    candidates_path.write_text(
        json.dumps([_candidate()]),
        encoding="utf-8",
    )

    merged, added = merge_candidates(registry_path, candidates_path)

    assert [effect.effect_id for effect in added] == ["TEST-M-001:1"]
    assert [effect.effect_id for effect in merged.effects] == ["TEST-M-001:1"]
    assert json.loads(registry_path.read_text(encoding="utf-8"))["effects"] == []


def test_merge_candidates_rejects_existing_identity(tmp_path: Path):
    registry_path = tmp_path / "registry.json"
    candidates_path = tmp_path / "candidates.json"
    candidate = _candidate()
    registry_path.write_text(
        json.dumps(
            {
                "registry_version": "effect-registry.v0",
                "rule_version": "1.06",
                "effects": [
                    {
                        key: value
                        for key, value in candidate.items()
                        if key not in {"already_registered", "pattern_id"}
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    candidates_path.write_text(
        json.dumps([candidate]),
        encoding="utf-8",
    )

    with pytest.raises(CandidateRegistrationError, match="overwrite"):
        merge_candidates(registry_path, candidates_path)


def test_merge_candidates_can_promote_identity_matching_manual(tmp_path: Path):
    registry_path = tmp_path / "registry.json"
    candidates_path = tmp_path / "candidates.json"
    candidate = _candidate()
    manual = {
        key: value
        for key, value in candidate.items()
        if key not in {"already_registered", "pattern_id"}
    }
    manual.update(
        {
            "actions": [{"action_type": "manual_resolution"}],
            "execution_mode": "manual_resolution",
            "review_status": "parsed_draft",
            "simulation_support": "manual_resolution",
        }
    )
    registry_path.write_text(
        json.dumps(
            {
                "registry_version": "effect-registry.v0",
                "rule_version": "1.06",
                "effects": [manual],
            }
        ),
        encoding="utf-8",
    )
    candidate["already_registered"] = True
    candidates_path.write_text(json.dumps([candidate]), encoding="utf-8")

    merged, changed = merge_candidates(
        registry_path,
        candidates_path,
        replace_matching_manual=True,
    )

    assert [effect.effect_id for effect in changed] == ["TEST-M-001:1"]
    assert merged.effects[0].simulation_support == "test_validated_executable"


def test_merge_candidates_rejects_manual_replacement_with_changed_revision(tmp_path: Path):
    registry_path = tmp_path / "registry.json"
    candidates_path = tmp_path / "candidates.json"
    candidate = _candidate()
    manual = {
        key: value
        for key, value in candidate.items()
        if key not in {"already_registered", "pattern_id"}
    }
    manual.update(
        {
            "actions": [{"action_type": "manual_resolution"}],
            "execution_mode": "manual_resolution",
            "review_status": "parsed_draft",
            "simulation_support": "manual_resolution",
        }
    )
    registry_path.write_text(
        json.dumps(
            {
                "registry_version": "effect-registry.v0",
                "rule_version": "1.06",
                "effects": [manual],
            }
        ),
        encoding="utf-8",
    )
    candidate["already_registered"] = True
    candidate["text_revision_id"] = 2
    candidates_path.write_text(json.dumps([candidate]), encoding="utf-8")

    with pytest.raises(CandidateRegistrationError, match="overwrite"):
        merge_candidates(
            registry_path,
            candidates_path,
            replace_matching_manual=True,
        )


def _candidate() -> dict[str, object]:
    return {
        "effect_id": "TEST-M-001:1",
        "card_code": "TEST-M-001",
        "text_revision_id": 1,
        "raw_text_hash": "a" * 64,
        "effect_index": 1,
        "label_ja": "【登場】カードを1枚引く。",
        "effect_type": "triggered",
        "timing": "on_play",
        "trigger": "member_played",
        "execution_mode": "auto_resolve",
        "frequency_limit": "none",
        "is_optional": False,
        "condition": {},
        "cost": [],
        "cost_choice": None,
        "choice": None,
        "follow_up_choice": None,
        "actions": [{"action_type": "draw_card", "amount": 1}],
        "duration": None,
        "simulation_support": "test_validated_executable",
        "review_status": "test_validated",
        "source_reference": "Official card text; test fixture",
        "pattern_id": "test",
        "already_registered": False,
    }
