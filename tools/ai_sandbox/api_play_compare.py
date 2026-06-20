"""Compare deterministic sandbox play with API Play policy.

This harness runs the same generated deck pool through two semantic sandbox
passes:

* deterministic: existing scripted ordinary-action policy
* api: semantic provider chooses ordinary LegalActions, with configurable
  fallback

The output is a review artifact for Phase 5.  It does not change effect
registry coverage and does not treat API Play success as rules validation.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from tools.ai_sandbox.blackbox_playtest import build_decks, summarize_deck
from tools.ai_sandbox.semantic_playtest import (
    ApiPlayAttempt,
    SemanticAgentProvider,
    SemanticAttempt,
    SemanticMatchSummary,
    provider_from_environment,
    require_real_semantic_provider,
    run_semantic_matches,
)

COMPARISON_SCHEMA_VERSION = "api_play_comparison_v0.1"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare deterministic semantic sandbox play with API Play."
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("logs/api_play_compare"))
    parser.add_argument("--decks", type=int, default=30)
    parser.add_argument("--matches", type=int, default=20)
    parser.add_argument("--max-actions", type=int, default=320)
    parser.add_argument(
        "--manual-fallback",
        choices=("block", "skip"),
        default="block",
    )
    parser.add_argument(
        "--play-fallback",
        choices=("deterministic", "block"),
        default="deterministic",
    )
    parser.add_argument(
        "--agent-provider",
        choices=("mock", "openai_compatible"),
        default=None,
    )
    parser.add_argument(
        "--require-real-provider",
        action="store_true",
        help=(
            "Fail fast when the selected semantic provider is mock. "
            "Use this for real API Play comparison runs."
        ),
    )
    parser.add_argument(
        "--api-context-samples",
        type=int,
        default=5,
        help="Maximum number of API Play model-input contexts to preserve in the JSON report.",
    )
    args = parser.parse_args()

    report = run_api_play_comparison(
        database=args.database,
        provider_factory=lambda: provider_from_environment(args.agent_provider),
        deck_count=args.decks,
        match_count=args.matches,
        max_actions=args.max_actions,
        manual_fallback=args.manual_fallback,
        play_fallback=args.play_fallback,
        require_real_provider=args.require_real_provider,
        api_context_sample_limit=max(0, args.api_context_samples),
    )
    write_comparison_outputs(args.output, report)
    print(f"Wrote API Play comparison report to {args.output / 'api-play-comparison.md'}")
    return 0


def run_api_play_comparison(
    *,
    database: Path,
    provider_factory: Callable[[], SemanticAgentProvider],
    deck_count: int,
    match_count: int,
    max_actions: int,
    manual_fallback: str,
    play_fallback: str,
    require_real_provider: bool = False,
    api_context_sample_limit: int = 5,
) -> dict[str, Any]:
    deterministic_provider = provider_factory()
    if require_real_provider:
        require_real_semantic_provider(deterministic_provider)
    api_provider = provider_factory()
    if require_real_provider:
        require_real_semantic_provider(api_provider)

    decks = build_decks(database, deck_count)
    deck_summaries = [summarize_deck(database, deck) for deck in decks]

    deterministic_matches, deterministic_attempts, deterministic_api_attempts = (
        run_semantic_matches(
            database,
            decks,
            provider=deterministic_provider,
            match_count=match_count,
            max_actions=max_actions,
            manual_fallback=manual_fallback,
            play_policy="deterministic",
            play_fallback=play_fallback,
            api_context_sample_limit=0,
        )
    )
    api_matches, api_attempts, api_play_attempts = run_semantic_matches(
        database,
        decks,
        provider=api_provider,
        match_count=match_count,
        max_actions=max_actions,
        manual_fallback=manual_fallback,
        play_policy="api",
        play_fallback=play_fallback,
        api_context_sample_limit=max(0, api_context_sample_limit),
    )

    deterministic_summary = summarize_policy_run(
        deterministic_matches,
        deterministic_attempts,
        deterministic_api_attempts,
    )
    api_summary = summarize_policy_run(api_matches, api_attempts, api_play_attempts)
    report = {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "database": str(database),
        "deck_count": deck_count,
        "match_count": match_count,
        "max_actions": max_actions,
        "manual_fallback": manual_fallback,
        "play_fallback": play_fallback,
        "api_context_sample_limit": max(0, api_context_sample_limit),
        "providers": {
            "deterministic": deterministic_provider.provider_name,
            "api": api_provider.provider_name,
        },
        "deck_summaries": [asdict(item) for item in deck_summaries],
        "runs": {
            "deterministic": {
                "summary": deterministic_summary,
                "match_summaries": [asdict(item) for item in deterministic_matches],
                "semantic_attempts": [asdict(item) for item in deterministic_attempts],
                "api_play_attempts": [
                    asdict(item) for item in deterministic_api_attempts
                ],
            },
            "api": {
                "summary": api_summary,
                "match_summaries": [asdict(item) for item in api_matches],
                "semantic_attempts": [asdict(item) for item in api_attempts],
                "api_play_attempts": [asdict(item) for item in api_play_attempts],
            },
        },
        "deltas": comparison_deltas(deterministic_summary, api_summary),
    }
    report["actionable_findings"] = build_actionable_findings(report)
    return report


def summarize_policy_run(
    matches: list[SemanticMatchSummary],
    semantic_attempts: list[SemanticAttempt],
    api_play_attempts: list[ApiPlayAttempt],
) -> dict[str, Any]:
    attempted = len(matches)
    completed = sum(item.status == "completed" for item in matches)
    action_counts = [item.action_count for item in matches]
    blockers = Counter(item.blocker or "none" for item in matches)
    semantic_statuses = Counter(item.status for item in semantic_attempts)
    api_statuses = Counter(item.status for item in api_play_attempts)
    api_baseline_matches = sum(item.matches_deterministic_baseline is True for item in api_play_attempts)
    api_baseline_divergences = sum(item.matches_deterministic_baseline is False for item in api_play_attempts)
    api_context_samples = sum(item.context_sample is not None for item in api_play_attempts)
    schema_gaps = Counter(
        item.schema_gap for item in [*semantic_attempts, *api_play_attempts] if item.schema_gap
    )
    return {
        "matches_attempted": attempted,
        "matches_completed": completed,
        "completion_rate": completed / attempted if attempted else 0.0,
        "blockers": dict(sorted(blockers.items())),
        "total_actions": sum(action_counts),
        "average_actions": (sum(action_counts) / attempted) if attempted else 0.0,
        "max_actions": max(action_counts, default=0),
        "manual_effect_count": sum(item.manual_effect_count for item in matches),
        "agent_success_count": sum(item.agent_success_count for item in matches),
        "agent_failure_count": sum(item.agent_failure_count for item in matches),
        "api_play_count": sum(item.api_play_count for item in matches),
        "api_play_failure_count": sum(item.api_play_failure_count for item in matches),
        "deterministic_fallback_count": sum(
            item.deterministic_fallback_count for item in matches
        ),
        "semantic_attempt_statuses": dict(sorted(semantic_statuses.items())),
        "api_play_attempt_statuses": dict(sorted(api_statuses.items())),
        "api_play_baseline_match_count": api_baseline_matches,
        "api_play_baseline_divergence_count": api_baseline_divergences,
        "api_play_context_sample_count": api_context_samples,
        "schema_gaps": dict(schema_gaps.most_common(20)),
    }


def comparison_deltas(
    deterministic: dict[str, Any],
    api: dict[str, Any],
) -> dict[str, Any]:
    return {
        "completed_delta": api["matches_completed"] - deterministic["matches_completed"],
        "completion_rate_delta": api["completion_rate"] - deterministic["completion_rate"],
        "average_actions_delta": api["average_actions"] - deterministic["average_actions"],
        "max_actions_delta": api["max_actions"] - deterministic["max_actions"],
        "manual_effect_delta": api["manual_effect_count"] - deterministic["manual_effect_count"],
        "blocker_delta": _counter_delta(deterministic["blockers"], api["blockers"]),
    }


def build_actionable_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn comparison statistics into next-step recommendations."""

    deterministic = report["runs"]["deterministic"]["summary"]
    api = report["runs"]["api"]["summary"]
    providers = report.get("providers", {})
    deltas = report.get("deltas", {})
    match_count = int(report.get("match_count") or api.get("matches_attempted") or 0)
    findings: list[dict[str, Any]] = []

    def add(
        severity: str,
        finding: str,
        detail: str,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        findings.append(
            {
                "severity": severity,
                "finding": finding,
                "detail": detail,
                "evidence": evidence or {},
            }
        )

    if providers.get("api") == "mock":
        add(
            "info",
            "api_provider_is_mock",
            "API Play is using the mock provider, so ordinary actions are expected to fall back unless scripted decisions are supplied.",
            {"provider": providers.get("api")},
        )

    api_failures = int(api.get("api_play_failure_count") or 0)
    fallback_count = int(api.get("deterministic_fallback_count") or 0)
    if api_failures and fallback_count >= api_failures:
        add(
            "warning",
            "api_play_fell_back_to_deterministic",
            "Every failed API Play decision used deterministic fallback; use a real provider or improve the API Play prompt before judging play quality.",
            {
                "api_play_failure_count": api_failures,
                "deterministic_fallback_count": fallback_count,
            },
        )

    completed_delta = int(deltas.get("completed_delta") or 0)
    if completed_delta < 0:
        add(
            "warning",
            "api_policy_regressed_completion",
            "API Play completed fewer matches than the deterministic policy on the same deck pool.",
            {
                "deterministic_completed": deterministic.get("matches_completed"),
                "api_completed": api.get("matches_completed"),
                "completed_delta": completed_delta,
            },
        )
    elif completed_delta > 0:
        add(
            "info",
            "api_policy_improved_completion",
            "API Play completed more matches than the deterministic policy; inspect the selected actions before using this as a new sandbox baseline.",
            {
                "deterministic_completed": deterministic.get("matches_completed"),
                "api_completed": api.get("matches_completed"),
                "completed_delta": completed_delta,
            },
        )
    elif match_count and int(api.get("matches_completed") or 0) < match_count:
        add(
            "info",
            "same_completion_blockers_remain",
            "API Play did not change completion count; prioritize the shared blocker list or schema gaps.",
            {
                "matches_completed": api.get("matches_completed"),
                "match_count": match_count,
            },
        )

    schema_gaps = api.get("schema_gaps") or {}
    top_gap = _top_counter_item(schema_gaps)
    if top_gap:
        gap, count = top_gap
        add(
            "warning",
            "api_play_schema_gap",
            "API Play reported schema gaps; these are candidates for prompt/schema changes before new rule automation.",
            {"top_schema_gap": gap, "count": count},
        )

    baseline_divergences = int(api.get("api_play_baseline_divergence_count") or 0)
    if baseline_divergences:
        add(
            "info",
            "api_play_diverged_from_baseline",
            "API Play selected legal actions different from the deterministic baseline; inspect these attempts to decide whether the strategy is better or just noisy.",
            {"api_play_baseline_divergence_count": baseline_divergences},
        )

    unresolved_statuses = {
        status: count
        for status, count in (api.get("api_play_attempt_statuses") or {}).items()
        if status != "api_play_selected"
    }
    top_status = _top_counter_item(unresolved_statuses)
    if top_status:
        status, count = top_status
        add(
            "warning",
            "api_play_unresolved_decisions",
            "API Play returned non-selected decisions; inspect attempts before using API Play as the default sandbox policy.",
            {"top_status": status, "count": count},
        )

    deterministic_blocker = _top_counter_item(
        deterministic.get("blockers") or {},
        exclude={"none"},
    )
    if deterministic_blocker:
        blocker, count = deterministic_blocker
        add(
            "info",
            "deterministic_blockers_observed",
            "The deterministic baseline still has blockers; compare whether API Play changes these before adding new registry entries.",
            {"top_blocker": blocker, "count": count},
        )

    if not findings:
        add(
            "info",
            "no_actionable_difference",
            "No actionable difference was found between deterministic and API Play runs.",
        )
    return findings


def write_comparison_outputs(output: Path, report: dict[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    report.setdefault("actionable_findings", build_actionable_findings(report))
    context_samples = extract_api_play_context_samples(report)
    (output / "api-play-comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_context_sample_outputs(output, context_samples)
    lines = [
        "# API Play Comparison Report",
        "",
        "## Scope",
        "",
        "* Deterministic run uses the existing scripted ordinary-action policy.",
        "* API run asks the configured semantic provider to choose ordinary LegalActions.",
        "* Manual-resolution effects still use the semantic manual flow.",
        "* This report is a playtest-strategy signal, not effect-registry coverage.",
        "",
        "## Configuration",
        "",
        f"* Decks: `{report['deck_count']}`",
        f"* Matches: `{report['match_count']}`",
        f"* Max actions: `{report['max_actions']}`",
        f"* Manual fallback: `{report['manual_fallback']}`",
        f"* API Play fallback: `{report['play_fallback']}`",
        f"* API context sample limit: `{report.get('api_context_sample_limit', 0)}`",
        f"* Providers: `{report['providers']}`",
        f"* Context sample review pack: `{len(context_samples)}` sample(s)",
        "",
        "## Summary",
        "",
        "| Policy | Completed | Completion | Avg Actions | Max Actions | Manual | API OK | API Fail | Fallback | Baseline Match | Baseline Diff | Contexts | Blockers |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for policy in ("deterministic", "api"):
        summary = report["runs"][policy]["summary"]
        lines.append(
            "| "
            + " | ".join(
                [
                    policy,
                    str(summary["matches_completed"]),
                    f"{summary['completion_rate']:.1%}",
                    f"{summary['average_actions']:.1f}",
                    str(summary["max_actions"]),
                    str(summary["manual_effect_count"]),
                    str(summary["api_play_count"]),
                    str(summary["api_play_failure_count"]),
                    str(summary["deterministic_fallback_count"]),
                    str(summary.get("api_play_baseline_match_count", 0)),
                    str(summary.get("api_play_baseline_divergence_count", 0)),
                    str(summary.get("api_play_context_sample_count", 0)),
                    _markdown_cell(summary["blockers"]),
                ]
            )
            + " |"
        )
    findings = report.get("actionable_findings") or []
    if findings:
        lines.extend(
            [
                "",
                "## Actionable Findings",
                "",
                "| Severity | Finding | Detail | Evidence |",
                "|---|---|---|---|",
            ]
        )
        for finding in findings:
            evidence = json.dumps(finding.get("evidence", {}), ensure_ascii=False)
            lines.append(
                f"| {finding['severity']} | `{finding['finding']}` | {_markdown_cell(finding['detail'])} | {_markdown_cell(evidence)} |"
            )
    lines.extend(
        [
            "",
            "## Delta",
            "",
            "```json",
            json.dumps(report["deltas"], ensure_ascii=False, indent=2),
            "```",
        ]
    )
    api_gaps = report["runs"]["api"]["summary"]["schema_gaps"]
    if api_gaps:
        lines.extend(["", "## API Play Schema Gaps", ""])
        for gap, count in api_gaps.items():
            lines.append(f"* `{gap}`: {count}")
    if context_samples:
        lines.extend(
            [
                "",
                "## Context Review Pack",
                "",
                "* Machine-readable samples: `api-play-context-samples.jsonl`",
                "* Human-readable samples: `api-play-context-samples.md`",
            ]
        )
    (output / "api-play-comparison.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def extract_api_play_context_samples(report: dict[str, Any]) -> list[dict[str, Any]]:
    attempts = report.get("runs", {}).get("api", {}).get("api_play_attempts", [])
    samples: list[dict[str, Any]] = []
    if not isinstance(attempts, list):
        return samples
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        context = attempt.get("context_sample")
        if not isinstance(context, dict):
            continue
        samples.append(
            {
                "match_index": attempt.get("match_index"),
                "action_index": attempt.get("action_index"),
                "status": attempt.get("status"),
                "phase": attempt.get("phase"),
                "decision": {
                    "decision": attempt.get("decision"),
                    "action_type": attempt.get("action_type"),
                    "player_id": attempt.get("player_id"),
                    "payload": attempt.get("submitted_payload"),
                    "confidence": attempt.get("confidence"),
                    "reason": attempt.get("agent_reason"),
                    "schema_gap": attempt.get("schema_gap"),
                },
                "baseline": {
                    "action_type": attempt.get("baseline_action_type"),
                    "player_id": attempt.get("baseline_player_id"),
                    "matches": attempt.get("matches_deterministic_baseline"),
                },
                "legal_action_summary": context.get("legal_action_summary"),
                "strategy": context.get("strategy"),
                "context": context,
            }
        )
    return samples


def write_context_sample_outputs(output: Path, samples: list[dict[str, Any]]) -> None:
    jsonl = "\n".join(
        json.dumps(sample, ensure_ascii=False, sort_keys=True) for sample in samples
    )
    (output / "api-play-context-samples.jsonl").write_text(
        (jsonl + "\n") if jsonl else "",
        encoding="utf-8",
    )
    lines = [
        "# API Play Context Samples",
        "",
        "These samples are the exact model-input contexts captured from the API Play run.",
        "Use them to review prompt quality, legal action hints, and deterministic baseline guidance before treating API Play output as useful.",
        "",
        f"* Samples: {len(samples)}",
    ]
    for index, sample in enumerate(samples, start=1):
        decision = sample.get("decision", {})
        baseline = sample.get("baseline", {})
        strategy = sample.get("strategy", {}) or {}
        legal_summary = sample.get("legal_action_summary", {}) or {}
        lines.extend(
            [
                "",
                f"## Sample {index}",
                "",
                f"* Match/action: `{sample.get('match_index')}` / `{sample.get('action_index')}`",
                f"* Status: `{sample.get('status')}`",
                f"* Phase: `{sample.get('phase')}`",
                f"* Decision: `{decision.get('action_type')}` by `{decision.get('player_id')}`",
                f"* Baseline: `{baseline.get('action_type')}` by `{baseline.get('player_id')}`, match=`{baseline.get('matches')}`",
                f"* Legal actions: `{legal_summary}`",
                f"* Strategy guidance: {_markdown_cell(strategy.get('phase_guidance', ''))}",
                "",
                "```json",
                json.dumps(sample.get("context", {}), ensure_ascii=False, indent=2),
                "```",
            ]
        )
    (output / "api-play-context-samples.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _counter_delta(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    keys = set(left) | set(right)
    return {key: right.get(key, 0) - left.get(key, 0) for key in sorted(keys)}


def _top_counter_item(
    value: dict[str, int],
    *,
    exclude: set[str] | None = None,
) -> tuple[str, int] | None:
    exclude = exclude or set()
    candidates = [(key, count) for key, count in value.items() if key not in exclude and count]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[1], item[0]))


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


if __name__ == "__main__":
    raise SystemExit(main())
