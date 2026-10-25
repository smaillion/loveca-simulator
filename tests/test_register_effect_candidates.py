from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.ai_sandbox.register_effect_candidates import (
    CandidateRegistrationError,
    main,
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


@pytest.mark.parametrize("add_new", [False, True])
def test_cli_preserves_raw_untouched_entries_without_materializing_defaults(
    tmp_path, monkeypatch, add_new
):
    registry = tmp_path / "registry.json"
    candidates = tmp_path / "candidates.json"
    original = {
        k: v for k, v in _candidate().items() if k not in {"already_registered", "pattern_id"}
    }
    payload = {
        "registry_version": "effect-registry.v0",
        "rule_version": "1.06",
        "effects": [original],
    }
    registry.write_text(json.dumps(payload), encoding="utf-8")
    new = dict(
        _candidate(), effect_id="TEST-M-002:1", card_code="TEST-M-002", raw_text_hash="b" * 64
    )
    candidates.write_text(json.dumps([new] if add_new else []), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "register_effect_candidates",
            "--registry",
            str(registry),
            "--candidates",
            str(candidates),
            "--approve",
        ],
    )
    assert main() == 0
    saved = json.loads(registry.read_text(encoding="utf-8"))
    assert saved["effects"][0] == original
    assert len(saved["effects"]) == 1 + int(add_new)
    if not add_new:
        assert saved == payload


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
