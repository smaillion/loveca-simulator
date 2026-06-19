from __future__ import annotations

import json

from tools.ai_sandbox.api_play_compare import (
    build_actionable_findings,
    comparison_deltas,
    summarize_policy_run,
    write_comparison_outputs,
)
from tools.ai_sandbox.semantic_playtest import (
    ApiPlayAttempt,
    SemanticMatchSummary,
)


def test_summarize_policy_run_counts_completion_and_api_play_statuses():
    matches = [
        SemanticMatchSummary(
            match_index=1,
            first_deck="A",
            second_deck="B",
            status="completed",
            final_phase="complete",
            turn_number=5,
            action_count=100,
            api_play_count=80,
            api_play_failure_count=3,
            deterministic_fallback_count=3,
        ),
        SemanticMatchSummary(
            match_index=2,
            first_deck="C",
            second_deck="D",
            status="blocked",
            final_phase="first_main",
            turn_number=2,
            action_count=20,
            manual_effect_count=1,
            blocker="api_play_unresolved",
            api_play_failure_count=1,
        ),
    ]
    attempts = [
        ApiPlayAttempt(
            match_index=1,
            action_index=1,
            status="api_play_selected",
            phase="first_main",
            legal_action_types=["advance_phase"],
            agent_reason="advance",
            decision="submit_action",
            action_type="advance_phase",
            player_id="player_1",
            confidence="high",
            baseline_action_type="advance_phase",
            baseline_player_id="player_1",
            matches_deterministic_baseline=True,
        ),
        ApiPlayAttempt(
            match_index=2,
            action_index=3,
            status="api_play_unresolved",
            phase="first_main",
            legal_action_types=["play_member"],
            agent_reason="cannot choose",
            decision="cannot_resolve",
            action_type=None,
            player_id=None,
            confidence="low",
            schema_gap="needs_strategy",
            baseline_action_type="play_member",
            baseline_player_id="player_1",
            matches_deterministic_baseline=False,
        ),
    ]

    summary = summarize_policy_run(matches, [], attempts)

    assert summary["matches_attempted"] == 2
    assert summary["matches_completed"] == 1
    assert summary["completion_rate"] == 0.5
    assert summary["average_actions"] == 60
    assert summary["blockers"] == {"api_play_unresolved": 1, "none": 1}
    assert summary["api_play_count"] == 80
    assert summary["api_play_failure_count"] == 4
    assert summary["api_play_attempt_statuses"] == {
        "api_play_selected": 1,
        "api_play_unresolved": 1,
    }
    assert summary["api_play_baseline_match_count"] == 1
    assert summary["api_play_baseline_divergence_count"] == 1
    assert summary["schema_gaps"] == {"needs_strategy": 1}


def test_build_actionable_findings_flags_mock_fallback_and_regression():
    deterministic = {
        "matches_attempted": 2,
        "matches_completed": 2,
        "completion_rate": 1.0,
        "blockers": {"none": 2},
        "total_actions": 120,
        "average_actions": 60.0,
        "max_actions": 80,
        "manual_effect_count": 0,
        "agent_success_count": 0,
        "agent_failure_count": 0,
        "api_play_count": 0,
        "api_play_failure_count": 0,
        "deterministic_fallback_count": 0,
        "semantic_attempt_statuses": {},
        "api_play_attempt_statuses": {},
        "api_play_baseline_match_count": 0,
        "api_play_baseline_divergence_count": 0,
        "schema_gaps": {},
    }
    api = {
        **deterministic,
        "matches_completed": 1,
        "completion_rate": 0.5,
        "blockers": {"api_play_unresolved": 1, "none": 1},
        "api_play_failure_count": 2,
        "deterministic_fallback_count": 2,
        "api_play_attempt_statuses": {"api_play_cannot_resolve": 2},
        "api_play_baseline_match_count": 0,
        "api_play_baseline_divergence_count": 0,
        "schema_gaps": {"mock_provider:api_play": 2},
    }
    report = {
        "match_count": 2,
        "providers": {"deterministic": "mock", "api": "mock"},
        "runs": {
            "deterministic": {"summary": deterministic},
            "api": {"summary": api},
        },
        "deltas": comparison_deltas(deterministic, api),
    }

    findings = build_actionable_findings(report)
    finding_names = {item["finding"] for item in findings}

    assert "api_provider_is_mock" in finding_names
    assert "api_play_fell_back_to_deterministic" in finding_names
    assert "api_policy_regressed_completion" in finding_names
    assert "api_play_schema_gap" in finding_names


def test_comparison_outputs_write_machine_and_human_reports(tmp_path):
    deterministic = {
        "matches_attempted": 2,
        "matches_completed": 2,
        "completion_rate": 1.0,
        "blockers": {"none": 2},
        "total_actions": 120,
        "average_actions": 60.0,
        "max_actions": 80,
        "manual_effect_count": 0,
        "agent_success_count": 0,
        "agent_failure_count": 0,
        "api_play_count": 0,
        "api_play_failure_count": 0,
        "deterministic_fallback_count": 0,
        "semantic_attempt_statuses": {},
        "api_play_attempt_statuses": {},
        "api_play_baseline_match_count": 0,
        "api_play_baseline_divergence_count": 0,
        "schema_gaps": {},
    }
    api = {
        **deterministic,
        "matches_completed": 1,
        "completion_rate": 0.5,
        "blockers": {"api_play_unresolved": 1, "none": 1},
        "average_actions": 70.0,
        "max_actions": 100,
        "api_play_count": 30,
        "api_play_failure_count": 2,
        "deterministic_fallback_count": 2,
        "schema_gaps": {"mock_provider:api_play": 2},
    }
    report = {
        "schema_version": "api_play_comparison_v0.1",
        "database": "data/loveca.sqlite3",
        "deck_count": 2,
        "match_count": 2,
        "max_actions": 320,
        "manual_fallback": "block",
        "play_fallback": "deterministic",
        "providers": {"deterministic": "mock", "api": "mock"},
        "deck_summaries": [],
        "runs": {
            "deterministic": {
                "summary": deterministic,
                "match_summaries": [],
                "semantic_attempts": [],
                "api_play_attempts": [],
            },
            "api": {
                "summary": api,
                "match_summaries": [],
                "semantic_attempts": [],
                "api_play_attempts": [],
            },
        },
        "deltas": comparison_deltas(deterministic, api),
    }

    write_comparison_outputs(tmp_path, report)

    payload = json.loads(
        (tmp_path / "api-play-comparison.json").read_text(encoding="utf-8")
    )
    markdown = (tmp_path / "api-play-comparison.md").read_text(encoding="utf-8")
    assert payload["schema_version"] == "api_play_comparison_v0.1"
    assert payload["deltas"]["completed_delta"] == -1
    assert payload["actionable_findings"]
    assert "API Play Comparison Report" in markdown
    assert "Actionable Findings" in markdown
    assert "api_provider_is_mock" in markdown
    assert "mock_provider:api_play" in markdown
