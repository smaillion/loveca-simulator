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
    args = parser.parse_args()

    report = run_api_play_comparison(
        database=args.database,
        provider_factory=lambda: provider_from_environment(args.agent_provider),
        deck_count=args.decks,
        match_count=args.matches,
        max_actions=args.max_actions,
        manual_fallback=args.manual_fallback,
        play_fallback=args.play_fallback,
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
) -> dict[str, Any]:
    decks = build_decks(database, deck_count)
    deck_summaries = [summarize_deck(database, deck) for deck in decks]

    deterministic_provider = provider_factory()
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
        )
    )
    api_provider = provider_factory()
    api_matches, api_attempts, api_play_attempts = run_semantic_matches(
        database,
        decks,
        provider=api_provider,
        match_count=match_count,
        max_actions=max_actions,
        manual_fallback=manual_fallback,
        play_policy="api",
        play_fallback=play_fallback,
    )

    deterministic_summary = summarize_policy_run(
        deterministic_matches,
        deterministic_attempts,
        deterministic_api_attempts,
    )
    api_summary = summarize_policy_run(api_matches, api_attempts, api_play_attempts)
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "database": str(database),
        "deck_count": deck_count,
        "match_count": match_count,
        "max_actions": max_actions,
        "manual_fallback": manual_fallback,
        "play_fallback": play_fallback,
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


def write_comparison_outputs(output: Path, report: dict[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "api-play-comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
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
        f"* Providers: `{report['providers']}`",
        "",
        "## Summary",
        "",
        "| Policy | Completed | Completion | Avg Actions | Max Actions | Manual | API OK | API Fail | Fallback | Blockers |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
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
                    _markdown_cell(summary["blockers"]),
                ]
            )
            + " |"
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
    (output / "api-play-comparison.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _counter_delta(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    keys = set(left) | set(right)
    return {key: right.get(key, 0) - left.get(key, 0) for key in sorted(keys)}


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


if __name__ == "__main__":
    raise SystemExit(main())
