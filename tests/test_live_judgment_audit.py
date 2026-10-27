from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from loveca.simulation.models import MatchState
from loveca.simulation.runtime import MatchRepository
from tools.ai_sandbox import live_judgment_audit as audit
from tools.ai_sandbox.live_judgment_audit import (
    run_live_judgment_boundary_matrix,
)

SCENARIOS = run_live_judgment_boundary_matrix()


def test_live_judgment_boundary_matrix_passes_implementation_regressions() -> None:
    results = run_live_judgment_boundary_matrix()

    assert len(results) == 20
    assert len({item.scenario_id for item in results}) == 20
    assert all(item.passed for item in results)


@pytest.mark.parametrize("case", SCENARIOS, ids=lambda case: case.scenario_id)
def test_live_boundary_real_action_and_sqlite_replay(tmp_path, case) -> None:
    state = audit._build_state(**case.inputs)
    before = state.model_dump_json()
    repository = MatchRepository(tmp_path / "boundary.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repository.apply(state.match_id, audit.judgment_action(state))
    assert state.model_dump_json() == before
    assert result.state.revision == state.revision + 1
    observed = audit.judgment_outcome(result.state, result.events)
    assert {key: observed[key] for key in case.expected} == case.expected
    assert observed == case.actual
    assert MatchState.model_validate_json(result.state.model_dump_json()) == result.state
    replay = repository.replay(state.match_id)
    assert replay["final_state"] == result.state.model_dump()
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert len(replay["actions"]) == 1


def test_matrix_keeps_pdf_ambiguity_and_synthetic_evidence_explicit() -> None:
    assert len([case for case in SCENARIOS if case.review_notes]) == 4
    assert (
        len([case for case in SCENARIOS if case.evidence_kind == "synthetic_effect_fixture"]) == 4
    )
    assert all(
        audit.MATCH_POINT_REVIEW in case.review_notes for case in SCENARIOS if case.review_notes
    )
    pdf = Path(__file__).resolve().parents[1] / "raw_doc/LoveLiveTCG_cr_1.06_260428.pdf"
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == audit.RULE_PDF_SHA256
    serialized = audit.serialize_live_judgment_boundary_matrix()
    assert all(case["rule_pdf_sha256"] == audit.RULE_PDF_SHA256 for case in serialized)
    assert all(len(case.expected) == 17 for case in SCENARIOS)


def test_wrong_observed_score_cannot_pass_matrix(monkeypatch) -> None:
    original = audit.judgment_outcome

    def wrong_score(state, events):
        actual = original(state, events)
        actual["scores"] = {"player_1": 999, "player_2": 999}
        return actual

    monkeypatch.setattr(audit, "judgment_outcome", wrong_score)
    assert not any(case.passed for case in run_live_judgment_boundary_matrix())


def test_readable_report_discloses_review_and_fixture_scope() -> None:
    from tools.ai_sandbox.ai_rules_acceptance import _render_live_judgment_boundaries

    report = audit.render_boundary_report(SCENARIOS)
    assert "20/20" in report
    assert "规则区域措辞待复核：4项" in report
    assert "合成技能fixture：4项" in report
    assert "成功Live区实际卡牌" in report
    assert all(case.title_zh in report for case in SCENARIOS)
    ai_report = _render_live_judgment_boundaries(
        SimpleNamespace(
            live_judgment_boundaries=SCENARIOS,
            rulebook=SimpleNamespace(source_path="local-pdf", sha256=audit.RULE_PDF_SHA256),
        )
    )
    assert "区域措辞待复核" in ai_report
    assert "合成技能fixture" in ai_report
    assert "不擅改现有引擎" in ai_report


def test_boundary_report_cli_writes_auditable_json_and_chinese(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["live_judgment_audit", "--output", str(tmp_path)])
    assert audit.main() == 0
    data = json.loads((tmp_path / "live-boundaries.json").read_text(encoding="utf-8"))
    assert len(data) == 20
    assert sum(bool(case["review_notes"]) for case in data) == 4
    assert all(
        case["expected"]["success_live_ids"] == case["actual"]["success_live_ids"] for case in data
    )
    assert "20/20" in (tmp_path / "Live判定回归.zh-CN.md").read_text(encoding="utf-8")


def test_boundary_report_cli_fails_for_failed_regression(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["live_judgment_audit", "--output", str(tmp_path)])
    monkeypatch.setattr(
        audit, "run_live_judgment_boundary_matrix", lambda: [replace(SCENARIOS[0], passed=False)]
    )
    assert audit.main() == 1


def test_match_point_tie_keeps_winner_and_placement_semantics_separate() -> None:
    results = {item.scenario_id: item for item in run_live_judgment_boundary_matrix()}

    one_match_point = results["equal_score_one_match_point"].actual
    assert one_match_point["winner_ids"] == ["player_1", "player_2"]
    assert one_match_point["eligible_player_ids"] == ["player_2"]
    assert one_match_point["prevented_player_ids"] == ["player_1"]
    assert one_match_point["game_result"] is None

    both_match_point = results["equal_score_both_match_point"].actual
    assert both_match_point["winner_ids"] == ["player_1", "player_2"]
    assert both_match_point["eligible_player_ids"] == []
    assert both_match_point["moved_player_ids"] == []
    assert both_match_point["game_result"] is None


def test_live_success_effects_resolve_before_score_comparison() -> None:
    result = next(
        item
        for item in run_live_judgment_boundary_matrix()
        if item.scenario_id == "live_success_score_before_comparison"
    )

    assert result.actual["scores"] == {"player_1": 3, "player_2": 2}
    assert result.actual["winner_ids"] == ["player_1"]
    assert result.actual["event_types"].index("effect_auto_resolved") < result.actual[
        "event_types"
    ].index("live_judgment_started")
