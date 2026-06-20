from __future__ import annotations

import json

import pytest

from tools.ai_sandbox.api_play_compare import (
    build_actionable_findings,
    comparison_deltas,
    extract_api_play_context_samples,
    run_api_play_comparison,
    summarize_policy_run,
    write_comparison_outputs,
)
from tools.ai_sandbox.semantic_playtest import (
    ApiPlayAttempt,
    MockSemanticAgentProvider,
    SemanticAgentError,
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
            context_sample={"mode": "api_play"},
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
    assert summary["api_play_context_sample_count"] == 1
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
        "api_play_context_sample_count": 0,
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


def test_api_play_comparison_real_provider_preflight_rejects_mock(tmp_path):
    with pytest.raises(SemanticAgentError, match="requires a real semantic provider"):
        run_api_play_comparison(
            database=tmp_path / "missing.sqlite3",
            provider_factory=MockSemanticAgentProvider,
            deck_count=1,
            match_count=1,
            max_actions=1,
            manual_fallback="skip",
            play_fallback="deterministic",
            require_real_provider=True,
        )


def test_extract_api_play_context_samples_for_prompt_review():
    report = {
        "runs": {
            "api": {
                "api_play_attempts": [
                    {
                        "match_index": 1,
                        "action_index": 2,
                        "status": "api_play_selected",
                        "phase": "first_main",
                        "decision": "submit_action",
                        "action_type": "play_member",
                        "player_id": "player_1",
                        "submitted_payload": {"slot": "center"},
                        "confidence": "medium",
                        "agent_reason": "play a member",
                        "baseline_action_type": "end_main_phase",
                        "baseline_player_id": "player_1",
                        "matches_deterministic_baseline": False,
                        "context_sample": {
                            "mode": "api_play",
                            "legal_action_summary": {"count": 2},
                            "strategy": {"phase_guidance": "play useful Members"},
                        },
                    },
                    {"match_index": 1, "action_index": 3},
                ]
            }
        }
    }

    samples = extract_api_play_context_samples(report)

    assert len(samples) == 1
    assert samples[0]["decision"]["action_type"] == "play_member"
    assert samples[0]["baseline"]["action_type"] == "end_main_phase"
    assert samples[0]["legal_action_summary"] == {"count": 2}
    assert samples[0]["context"]["mode"] == "api_play"


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
        "api_play_context_sample_count": 1,
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
        "api_context_sample_limit": 5,
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
                "api_play_attempts": [
                    {
                        "match_index": 1,
                        "action_index": 1,
                        "status": "api_play_selected",
                        "phase": "first_main",
                        "decision": "submit_action",
                        "action_type": "advance_phase",
                        "player_id": "player_1",
                        "submitted_payload": {},
                        "confidence": "high",
                        "agent_reason": "advance",
                        "baseline_action_type": "advance_phase",
                        "baseline_player_id": "player_1",
                        "matches_deterministic_baseline": True,
                        "context_sample": {
                            "mode": "api_play",
                            "legal_action_summary": {"count": 1},
                            "strategy": {"phase_guidance": "advance"},
                        },
                    }
                ],
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
    assert payload["api_context_sample_limit"] == 5
    samples_jsonl = tmp_path / "api-play-context-samples.jsonl"
    samples_markdown = tmp_path / "api-play-context-samples.md"
    assert samples_jsonl.exists()
    assert samples_markdown.exists()
    sample_payload = json.loads(samples_jsonl.read_text(encoding="utf-8").splitlines()[0])
    assert sample_payload["context"]["mode"] == "api_play"
    assert "API Play Comparison Report" in markdown
    assert "Actionable Findings" in markdown
    assert "API context sample limit" in markdown
    assert "Context Review Pack" in markdown
    assert "api_provider_is_mock" in markdown
    assert "mock_provider:api_play" in markdown
    assert "API Play Context Samples" in samples_markdown.read_text(encoding="utf-8")
