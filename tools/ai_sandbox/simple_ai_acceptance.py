"""Local Simple AI acceptance runner.

This is a product-facing smoke harness for Human-vs-Computer and AI-vs-AI
debug flows. It is intentionally separate from regular CI because the useful
20x20 run is too large for a default test gate.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from loveca.simulation.ai import SimpleAIController, choose_simple_ai_action
from loveca.simulation.engine import generate_legal_actions
from loveca.simulation.models import ActionRequest, ActionResult, GameEvent
from loveca.simulation.service import MatchService
from tools.ai_sandbox.blackbox_playtest import (
    build_decks,
    classify_blocker,
    describe_state,
    diagnose_max_actions,
)

Mode = Literal["human-vs-ai", "ai-vs-ai"]


@dataclass
class SimpleAIMatchReport:
    match_index: int
    mode: Mode
    first_deck: str
    second_deck: str
    status: str
    final_phase: str
    turn_number: int
    revision: int
    driven_human_actions: int
    ai_actions: int
    success_live_counts: dict[str, int]
    blocker: str | None = None
    blocker_detail: dict[str, Any] = field(default_factory=dict)
    event_counts: dict[str, int] = field(default_factory=dict)
    skipped_effects: list[dict[str, Any]] = field(default_factory=list)
    replay_serialization_ok: bool = False
    replay_error: str | None = None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("data/loveca.sqlite3"))
    parser.add_argument("--output", type=Path, default=Path("logs/simple_ai_acceptance"))
    parser.add_argument("--decks", type=int, default=10)
    parser.add_argument("--matches", type=int, default=10)
    parser.add_argument(
        "--match-start",
        type=int,
        default=1,
        help="One-based first match index for deterministic split or resumed runs.",
    )
    parser.add_argument("--max-actions", type=int, default=450)
    parser.add_argument(
        "--mode",
        choices=("human-vs-ai", "ai-vs-ai", "both"),
        default="both",
    )
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    progress_path = args.output / "simple-ai-progress.jsonl"
    progress_path.write_text("", encoding="utf-8")
    modes: list[Mode] = (
        ["human-vs-ai", "ai-vs-ai"] if args.mode == "both" else [args.mode]  # type: ignore[list-item]
    )
    decks = build_decks(args.database, args.decks)
    reports: list[SimpleAIMatchReport] = []
    for mode in modes:
        reports.extend(
            run_acceptance_matches(
                args.database,
                decks,
                mode=mode,
                match_count=args.matches,
                max_actions=args.max_actions,
                match_start=args.match_start,
                progress_path=progress_path,
            )
        )
    write_report(args.output, reports)
    print(f"Wrote Simple AI acceptance report to {args.output / 'simple-ai-report.md'}")
    return 0 if acceptance_passed(reports) else 1


def run_acceptance_matches(
    database: Path,
    decks: list[Any],
    *,
    mode: Mode,
    match_count: int,
    max_actions: int,
    match_start: int = 1,
    progress_path: Path | None = None,
) -> list[SimpleAIMatchReport]:
    if match_start < 1:
        raise ValueError("match_start must be at least 1")
    results: list[SimpleAIMatchReport] = []
    with tempfile.TemporaryDirectory(prefix="loveca-simple-ai-") as tmp:
        service = MatchService(database, Path(tmp) / "matches.sqlite3")
        for local_index in range(match_count):
            index = match_start - 1 + local_index
            first = decks[index % len(decks)]
            second = decks[(index * 5 + 3) % len(decks)]
            controllers = (
                {"player_1": "human", "player_2": "simple_ai"}
                if mode == "human-vs-ai"
                else {"player_1": "simple_ai", "player_2": "simple_ai"}
            )
            result = service.create_match(
                first_name="Human" if mode == "human-vs-ai" else "CPU A",
                first_deck=first,
                second_name="Computer" if mode == "human-vs-ai" else "CPU B",
                second_deck=second,
                seed=12000 + index,
                match_id=f"simple-ai-{mode}-{index + 1:02d}",
                controllers=controllers,  # type: ignore[arg-type]
            )
            if mode == "human-vs-ai":
                result = drive_human_side(service, result, max_actions=max_actions)
            else:
                result = continue_ai_vs_ai(service, result, max_actions=max_actions)
            report = summarize_match(
                service,
                index + 1,
                mode,
                first.name or "(unnamed)",
                second.name or "(unnamed)",
                result,
                max_actions=max_actions,
            )
            results.append(report)
            if progress_path is not None:
                with progress_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(asdict(report), ensure_ascii=False) + "\n")
    return results


def drive_human_side(
    service: MatchService,
    result: ActionResult,
    *,
    max_actions: int,
) -> ActionResult:
    driven_actions = 0
    current = result
    while current.state.phase != "complete" and driven_actions < max_actions:
        action = _choose_acceptance_driver_action(current)
        if action is None:
            break
        current = service.apply(current.state.match_id, action)
        driven_actions += 1
    return _append_driver_count(current, driven_actions)


def _choose_acceptance_driver_action(result: ActionResult) -> ActionRequest | None:
    """Drive only player_1 and player-neutral system actions.

    Human-vs-AI acceptance uses a deterministic driver to avoid requiring a
    person for long local runs. It must not directly operate player_2, but it
    does need to press player-neutral rule engine actions such as live judgment.
    """

    state = result.state
    available = [
        action
        for action in result.legal_actions
        if action.player_id in {"player_1", None}
    ]
    decision = choose_simple_ai_action(state, available, manual_policy="skip")
    if decision is None:
        return None
    action_type, player_id, payload, reason = decision
    if player_id not in {"player_1", None}:
        return None
    return ActionRequest(
        action_type=action_type,
        expected_revision=state.revision,
        player_id=player_id,
        payload={
            **payload,
            "acceptance_driver": {
                "controller": "simple_ai_acceptance_driver",
                "reason": reason,
            },
        },
    )


def continue_ai_vs_ai(
    service: MatchService,
    result: ActionResult,
    *,
    max_actions: int,
) -> ActionResult:
    current = result
    previous_revision = -1
    loops = 0
    while (
        current.state.phase != "complete"
        and current.state.revision != previous_revision
        and loops < 8
    ):
        previous_revision = current.state.revision
        current = service.advance_ai(
            current.state.match_id,
            current,
            max_ai_actions=max_actions,
        )
        loops += 1
    return current


def summarize_match(
    service: MatchService,
    match_index: int,
    mode: Mode,
    first_deck: str,
    second_deck: str,
    result: ActionResult,
    *,
    max_actions: int,
) -> SimpleAIMatchReport:
    state = result.state
    persisted_events = service.repository.list_events(state.match_id)
    event_counts: Counter[str] = Counter(event.event_type for event in persisted_events)
    skipped = [
        dict(event.data)
        for event in persisted_events
        if event.event_type == "effect_skipped_due_to_error"
    ]
    ai_actions = event_counts.get("ai_action_selected", 0)
    driven_human_actions = _driver_count(result.events)
    replay_serialization_ok = False
    replay_error: str | None = None
    try:
        service.repository.replay(state.match_id)
        replay_serialization_ok = True
    except Exception as exc:  # noqa: BLE001 - this report should capture any replay failure.
        replay_error = f"{type(exc).__name__}: {exc}"
    blocker: str | None = None
    blocker_detail: dict[str, Any] = {}
    if replay_error:
        blocker = "replay_serialization_error"
        blocker_detail = {"error": replay_error}
    if state.phase != "complete":
        ai_block = _latest_event(result.events, "ai_blocked")
        if ai_block is not None:
            blocker = str(ai_block.data.get("reason", "ai_blocked"))
            blocker_detail = dict(ai_block.data)
        elif driven_human_actions >= max_actions:
            legal = generate_legal_actions(state)
            diagnosis = diagnose_max_actions(state, legal)
            blocker = f"max_actions:{diagnosis['reason']}"
            blocker_detail = {
                **describe_state(state, legal),
                "max_action_diagnosis": diagnosis,
            }
        else:
            legal = generate_legal_actions(state)
            blocker = classify_blocker(state, legal)
            blocker_detail = describe_state(state, legal)
    return SimpleAIMatchReport(
        match_index=match_index,
        mode=mode,
        first_deck=first_deck,
        second_deck=second_deck,
        status="completed" if state.phase == "complete" else "blocked",
        final_phase=state.phase,
        turn_number=state.turn_number,
        revision=state.revision,
        driven_human_actions=driven_human_actions,
        ai_actions=ai_actions,
        success_live_counts={
            player_id: len(player.success_live_area)
            for player_id, player in state.players.items()
        },
        blocker=blocker,
        blocker_detail=blocker_detail,
        event_counts=dict(sorted(event_counts.items())),
        skipped_effects=skipped,
        replay_serialization_ok=replay_serialization_ok,
        replay_error=replay_error,
    )


def acceptance_passed(reports: list[SimpleAIMatchReport]) -> bool:
    if not reports:
        return False
    illegal = sum(1 for item in reports if item.blocker == "illegal_action")
    runtime_like = sum(
        1
        for item in reports
        if item.blocker and "exception" in item.blocker.lower()
    )
    replay_errors = sum(1 for item in reports if not item.replay_serialization_ok)
    explained = sum(
        1
        for item in reports
        if item.status == "completed" or item.blocker_detail
    )
    return (
        illegal == 0
        and runtime_like == 0
        and replay_errors == 0
        and explained >= int(len(reports) * 0.8)
    )


def write_report(output: Path, reports: list[SimpleAIMatchReport]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "simple-ai-summary.json").write_text(
        json.dumps([asdict(item) for item in reports], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    status_counts = Counter(item.status for item in reports)
    blocker_counts = Counter(item.blocker or "none" for item in reports)
    skipped_counts = Counter(
        skipped.get("effect_id", "(unknown)")
        for item in reports
        for skipped in item.skipped_effects
    )
    lines = [
        "# Simple AI Acceptance Report",
        "",
        "## Summary",
        "",
        f"* Matches: {len(reports)}",
        f"* Status: {dict(sorted(status_counts.items()))}",
        f"* Blockers: {dict(blocker_counts.most_common(20))}",
        f"* Skipped effects: {dict(skipped_counts.most_common(20))}",
        f"* Replay serialization errors: {sum(1 for item in reports if not item.replay_serialization_ok)}",
        f"* Acceptance gate: {'PASS' if acceptance_passed(reports) else 'REVIEW'}",
        "",
        "## Match Results",
        "",
        "| # | Mode | Status | Decks | Phase | Turn | Human actions | AI actions | Success Lives | Blocker |",
        "|---:|---|---|---|---|---:|---:|---:|---|---|",
    ]
    for item in reports:
        success = ", ".join(
            f"{player}:{count}" for player, count in sorted(item.success_live_counts.items())
        )
        lines.append(
            f"| {item.match_index} | {item.mode} | {item.status} | "
            f"{item.first_deck} vs {item.second_deck} | {item.final_phase} | "
            f"{item.turn_number} | {item.driven_human_actions} | {item.ai_actions} | "
            f"{success} | {_cell(item.blocker or '')} |"
        )
    if skipped_counts:
        lines.extend(["", "## Skipped Effects", "", "| Effect ID | Count |", "|---|---:|"])
        for effect_id, count in skipped_counts.most_common(50):
            lines.append(f"| {_cell(effect_id)} | {count} |")
    blocker_details = [item for item in reports if item.blocker_detail]
    if blocker_details:
        lines.extend(["", "## Blocker Details", ""])
        for item in blocker_details[:20]:
            lines.append(f"### Match {item.match_index} {item.mode}: {item.blocker}")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(item.blocker_detail, ensure_ascii=False, indent=2)[:4000])
            lines.append("```")
            lines.append("")
    (output / "simple-ai-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_driver_count(result: ActionResult, count: int) -> ActionResult:
    return ActionResult(
        state=result.state,
        legal_actions=result.legal_actions,
        events=[
            *result.events,
            GameEvent(
                event_type="simple_ai_acceptance_driver_summary",
                player_id="player_1",
                data={"driven_human_actions": count},
                source="system",
            ),
        ],
    )


def _driver_count(events: list[GameEvent]) -> int:
    summary = _latest_event(events, "simple_ai_acceptance_driver_summary")
    if summary is None:
        return 0
    value = summary.data.get("driven_human_actions")
    return int(value) if isinstance(value, int) else 0


def _latest_event(events: list[GameEvent], event_type: str) -> GameEvent | None:
    for event in reversed(events):
        if event.event_type == event_type:
            return event
    return None


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


if __name__ == "__main__":
    raise SystemExit(main())
