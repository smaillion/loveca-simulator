"""Mirrored Simple AI v0 versus v1 benchmark with replay-safe reports."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from loveca.simulation.models import ActionResult, GameEvent
from loveca.simulation.service import MatchService
from tools.ai_sandbox.blackbox_playtest import build_decks


@dataclass
class PolicyMatchResult:
    match_index: int
    pair_index: int
    mirror: int
    seed: int
    player_1_deck: str
    player_2_deck: str
    v1_player_id: str
    status: str
    turn_number: int
    winner_player_ids: list[str]
    v1_points: float
    v0_actions: int
    v1_actions: int
    v0_reasons: dict[str, int]
    v1_reasons: dict[str, int]
    v0_decision_ms: list[float]
    v1_decision_ms: list[float]
    v0_live_checks: int
    v1_live_checks: int
    v0_live_successes: int
    v1_live_successes: int
    v0_energy_spent: int
    v1_energy_spent: int
    v0_effect_decisions: int
    v1_effect_decisions: int
    v0_effect_choices: dict[str, int]
    v1_effect_choices: dict[str, int]
    skipped_effects: int
    blocker: str | None
    blocker_detail: dict[str, Any]
    replay_ok: bool


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("data/loveca.sqlite3"))
    parser.add_argument("--decks", type=int, default=20)
    parser.add_argument("--pairs", type=int, default=50)
    parser.add_argument(
        "--pair-start",
        type=int,
        default=1,
        help="One-based benchmark pair index used for targeted seed reruns.",
    )
    parser.add_argument("--max-actions", type=int, default=600)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("logs/simple_ai_policy_benchmark"),
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    progress_path = args.output / "simple-ai-policy-progress.jsonl"
    progress_path.write_text("", encoding="utf-8")
    decks = build_decks(args.database, args.decks)
    results = run_mirrored_benchmark(
        args.database,
        decks,
        pairs=args.pairs,
        max_actions=args.max_actions,
        pair_start=args.pair_start,
        progress_path=progress_path,
    )
    write_benchmark_report(args.output, results)
    summary = summarize_benchmark(results)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if benchmark_passed(summary) else 1


def run_mirrored_benchmark(
    database: Path,
    decks: list[object],
    *,
    pairs: int,
    max_actions: int,
    pair_start: int = 1,
    progress_path: Path | None = None,
) -> list[PolicyMatchResult]:
    if pair_start < 1:
        raise ValueError("pair_start must be at least 1")
    results: list[PolicyMatchResult] = []
    with tempfile.TemporaryDirectory(prefix="loveca-ai-policy-benchmark-") as tmp:
        service = MatchService(database, Path(tmp) / "matches.sqlite3")
        match_index = 0
        for local_pair_index in range(pairs):
            pair_index = pair_start - 1 + local_pair_index
            deck_a = decks[pair_index % len(decks)]
            deck_b = decks[(pair_index * 7 + 3) % len(decks)]
            seed = 770000 + pair_index
            variants = (
                (deck_a, deck_b, "player_1"),
                (deck_b, deck_a, "player_2"),
                (deck_a, deck_b, "player_2"),
                (deck_b, deck_a, "player_1"),
            )
            for mirror, (first_deck, second_deck, v1_player_id) in enumerate(variants):
                match_index += 1
                versions = {
                    "player_1": "simple_ai_v1"
                    if v1_player_id == "player_1"
                    else "simple_ai_v0",
                    "player_2": "simple_ai_v1"
                    if v1_player_id == "player_2"
                    else "simple_ai_v0",
                }
                result = service.create_match(
                    first_name="Simple AI",
                    first_deck=first_deck,
                    second_name="Simple AI",
                    second_deck=second_deck,
                    seed=seed,
                    match_id=f"ai-policy-{pair_index + 1:03d}-{mirror}",
                    controllers={"player_1": "simple_ai", "player_2": "simple_ai"},
                    controller_policy_versions=versions,
                )
                result = _continue_match(service, result, max_actions=max_actions)
                match_result = _summarize_match(
                    service,
                    result,
                    match_index=match_index,
                    pair_index=pair_index + 1,
                    mirror=mirror,
                    seed=seed,
                    first_deck=first_deck.name or "(unnamed)",
                    second_deck=second_deck.name or "(unnamed)",
                    v1_player_id=v1_player_id,
                )
                results.append(match_result)
                if progress_path is not None:
                    with progress_path.open("a", encoding="utf-8") as handle:
                        handle.write(
                            json.dumps(asdict(match_result), ensure_ascii=False) + "\n"
                        )
    return results


def _continue_match(
    service: MatchService,
    result: ActionResult,
    *,
    max_actions: int,
) -> ActionResult:
    current = result
    while current.state.phase != "complete":
        events = service.repository.list_events(current.state.match_id)
        actions = sum(event.event_type == "ai_action_selected" for event in events)
        if actions >= max_actions:
            break
        previous_revision = current.state.revision
        current = service.advance_ai(
            current.state.match_id,
            current,
            max_ai_actions=min(256, max_actions - actions),
        )
        if current.state.revision == previous_revision:
            break
    return current


def _summarize_match(
    service: MatchService,
    result: ActionResult,
    *,
    match_index: int,
    pair_index: int,
    mirror: int,
    seed: int,
    first_deck: str,
    second_deck: str,
    v1_player_id: str,
) -> PolicyMatchResult:
    state = result.state
    events = service.repository.list_events(state.match_id)
    policy_actions = Counter(
        str(event.data.get("policy_version", "simple_ai_v0"))
        for event in events
        if event.event_type == "ai_action_selected"
    )
    policy_reasons: dict[str, Counter[str]] = {
        "simple_ai_v0": Counter(),
        "simple_ai_v1": Counter(),
    }
    for event in events:
        if event.event_type != "ai_action_selected":
            continue
        version = str(event.data.get("policy_version", "simple_ai_v0"))
        if version in policy_reasons:
            policy_reasons[version][str(event.data.get("reason", "unknown"))] += 1
    invocation_effect_ids = {
        str(event.data["invocation_id"]): str(event.data["effect_id"])
        for event in events
        if isinstance(event.data.get("invocation_id"), str)
        and isinstance(event.data.get("effect_id"), str)
    }
    policy_effect_choices: dict[str, Counter[str]] = {
        "simple_ai_v0": Counter(),
        "simple_ai_v1": Counter(),
    }
    for event in events:
        if event.event_type != "ai_action_selected":
            continue
        version = str(event.data.get("policy_version", "simple_ai_v0"))
        effect_id = event.data.get("effect_id")
        invocation_id = event.data.get("invocation_id")
        if not isinstance(effect_id, str) and isinstance(invocation_id, str):
            effect_id = invocation_effect_ids.get(invocation_id)
        if version in policy_effect_choices and isinstance(effect_id, str):
            policy_effect_choices[version][effect_id] += 1
    policy_durations: dict[str, list[float]] = {
        "simple_ai_v0": [],
        "simple_ai_v1": [],
    }
    for event in events:
        if event.event_type != "ai_action_selected":
            continue
        version = str(event.data.get("policy_version", "simple_ai_v0"))
        duration = event.data.get("duration_ms")
        if version in policy_durations and isinstance(duration, (int, float)):
            policy_durations[version].append(float(duration))
    skipped = sum(event.event_type == "effect_skipped_due_to_error" for event in events)
    v0_player_id = next(player_id for player_id in state.players if player_id != v1_player_id)
    v0_metrics = _player_policy_metrics(events, v0_player_id)
    v1_metrics = _player_policy_metrics(events, v1_player_id)
    winner_ids = list(state.game_result.winner_player_ids) if state.game_result else []
    if state.game_result and state.game_result.outcome == "draw":
        v1_points = 0.5
    else:
        v1_points = 1.0 if v1_player_id in winner_ids else 0.0
    blocker = None
    blocker_detail: dict[str, Any] = {}
    if state.phase != "complete":
        blocked = next(
            (event for event in reversed(events) if event.event_type == "ai_blocked"),
            None,
        )
        blocker = str(blocked.data.get("reason")) if blocked else "incomplete"
        blocker_detail = dict(blocked.data) if blocked else {}
    replay_ok = True
    try:
        service.repository.replay(state.match_id)
    except Exception:  # noqa: BLE001 - benchmark records the failure as data.
        replay_ok = False
    return PolicyMatchResult(
        match_index=match_index,
        pair_index=pair_index,
        mirror=mirror,
        seed=seed,
        player_1_deck=first_deck,
        player_2_deck=second_deck,
        v1_player_id=v1_player_id,
        status="completed" if state.phase == "complete" else "blocked",
        turn_number=state.turn_number,
        winner_player_ids=winner_ids,
        v1_points=v1_points,
        v0_actions=policy_actions["simple_ai_v0"],
        v1_actions=policy_actions["simple_ai_v1"],
        v0_reasons=dict(policy_reasons["simple_ai_v0"].most_common()),
        v1_reasons=dict(policy_reasons["simple_ai_v1"].most_common()),
        v0_decision_ms=policy_durations["simple_ai_v0"],
        v1_decision_ms=policy_durations["simple_ai_v1"],
        v0_live_checks=v0_metrics["live_checks"],
        v1_live_checks=v1_metrics["live_checks"],
        v0_live_successes=v0_metrics["live_successes"],
        v1_live_successes=v1_metrics["live_successes"],
        v0_energy_spent=v0_metrics["energy_spent"],
        v1_energy_spent=v1_metrics["energy_spent"],
        v0_effect_decisions=v0_metrics["effect_decisions"],
        v1_effect_decisions=v1_metrics["effect_decisions"],
        v0_effect_choices=dict(policy_effect_choices["simple_ai_v0"].most_common()),
        v1_effect_choices=dict(policy_effect_choices["simple_ai_v1"].most_common()),
        skipped_effects=skipped,
        blocker=blocker,
        blocker_detail=blocker_detail,
        replay_ok=replay_ok,
    )


def _player_policy_metrics(events: list[GameEvent], player_id: str) -> dict[str, int]:
    live_checks = 0
    live_successes = 0
    energy_spent = 0
    effect_decisions = 0
    for event in events:
        if event.player_id != player_id:
            continue
        event_type = event.event_type
        data = event.data
        if event_type == "live_requirements_resolved":
            live_checks += 1
            live_successes += bool(data.get("satisfied"))
        elif event_type == "member_played":
            payment_cost = data.get("payment_cost", 0)
            if isinstance(payment_cost, int) and not isinstance(payment_cost, bool):
                energy_spent += payment_cost
        elif event_type == "effect_cost_paid":
            energy_ids = data.get("energy_instance_ids", [])
            if isinstance(energy_ids, list):
                energy_spent += len(energy_ids)
        if event_type in {"effect_resolved", "effect_auto_resolved", "effect_declined"}:
            effect_decisions += 1
    return {
        "live_checks": live_checks,
        "live_successes": live_successes,
        "energy_spent": energy_spent,
        "effect_decisions": effect_decisions,
    }


def summarize_benchmark(results: list[PolicyMatchResult]) -> dict[str, object]:
    turns = sorted(item.turn_number for item in results)
    v0_durations = sorted(
        duration for item in results for duration in item.v0_decision_ms
    )
    v1_durations = sorted(
        duration for item in results for duration in item.v1_decision_ms
    )
    completed = sum(item.status == "completed" for item in results)
    total = len(results)
    v0_live_checks = sum(item.v0_live_checks for item in results)
    v1_live_checks = sum(item.v1_live_checks for item in results)
    v0_live_successes = sum(item.v0_live_successes for item in results)
    v1_live_successes = sum(item.v1_live_successes for item in results)
    v0_effect_choices: Counter[str] = Counter()
    v1_effect_choices: Counter[str] = Counter()
    for item in results:
        v0_effect_choices.update(item.v0_effect_choices)
        v1_effect_choices.update(item.v1_effect_choices)
    return {
        "schema_version": "simple_ai_policy_benchmark_v0.1",
        "matches": total,
        "completed": completed,
        "blocked": total - completed,
        "v1_points_rate": round(
            sum(item.v1_points for item in results) / total if total else 0.0,
            4,
        ),
        "average_turns": round(sum(turns) / len(turns), 3) if turns else 0.0,
        "p95_turns": turns[max(0, math.ceil(len(turns) * 0.95) - 1)] if turns else 0,
        "v0_decision_p95_ms": _percentile(v0_durations, 0.95),
        "v1_decision_p95_ms": _percentile(v1_durations, 0.95),
        "v1_decision_max_ms": round(max(v1_durations), 3) if v1_durations else 0.0,
        "v0_live_success_rate": round(
            v0_live_successes / v0_live_checks if v0_live_checks else 0.0,
            4,
        ),
        "v1_live_success_rate": round(
            v1_live_successes / v1_live_checks if v1_live_checks else 0.0,
            4,
        ),
        "v0_energy_spent": sum(item.v0_energy_spent for item in results),
        "v1_energy_spent": sum(item.v1_energy_spent for item in results),
        "v0_effect_decisions": sum(item.v0_effect_decisions for item in results),
        "v1_effect_decisions": sum(item.v1_effect_decisions for item in results),
        "v0_top_effect_choices": dict(v0_effect_choices.most_common(20)),
        "v1_top_effect_choices": dict(v1_effect_choices.most_common(20)),
        "illegal_actions": sum(item.blocker == "ai_illegal_action" for item in results),
        "replay_errors": sum(not item.replay_ok for item in results),
        "skipped_effects": sum(item.skipped_effects for item in results),
        "blockers": dict(Counter(item.blocker or "none" for item in results)),
    }


def benchmark_passed(summary: dict[str, object]) -> bool:
    return bool(
        summary.get("completed") == summary.get("matches")
        and summary.get("illegal_actions") == 0
        and summary.get("replay_errors") == 0
        and float(summary.get("v1_points_rate", 0)) >= 0.55
        and float(summary.get("average_turns", 999)) <= 10.7
        and int(summary.get("p95_turns", 999)) <= 20
        and float(summary.get("v1_decision_p95_ms", 999)) <= 250
    )


def write_benchmark_report(output: Path, results: list[PolicyMatchResult]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    summary = summarize_benchmark(results)
    (output / "simple-ai-policy-summary.json").write_text(
        json.dumps(
            {"summary": summary, "matches": [asdict(item) for item in results]},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Simple AI v0 / v1 镜像对战报告",
        "",
        f"- 对局数: {summary['matches']}",
        f"- 完成: {summary['completed']}",
        f"- v1 比赛积分率: {float(summary['v1_points_rate']):.2%}",
        f"- 平均回合: {summary['average_turns']}",
        f"- P95 回合: {summary['p95_turns']}",
        f"- v1 单次决策 P95: {summary['v1_decision_p95_ms']} ms",
        f"- v1 单次决策最大值: {summary['v1_decision_max_ms']} ms",
        f"- v0 / v1 Live 成功率: {float(summary['v0_live_success_rate']):.2%} / "
        f"{float(summary['v1_live_success_rate']):.2%}",
        f"- v0 / v1 Energy 使用: {summary['v0_energy_spent']} / "
        f"{summary['v1_energy_spent']}",
        f"- v0 / v1 技能处理: {summary['v0_effect_decisions']} / "
        f"{summary['v1_effect_decisions']}",
        f"- v1 常用技能: {summary['v1_top_effect_choices']}",
        f"- 非法操作: {summary['illegal_actions']}",
        f"- Replay 错误: {summary['replay_errors']}",
        f"- 技能跳过: {summary['skipped_effects']}",
        f"- 验收: {'PASS' if benchmark_passed(summary) else 'REVIEW'}",
        "",
        "| # | Pair | Mirror | v1 位置 | 回合 | 胜者 | 状态 |",
        "|---:|---:|---:|---|---:|---|---|",
    ]
    for item in results:
        lines.append(
            f"| {item.match_index} | {item.pair_index} | {item.mirror} | "
            f"{item.v1_player_id} | {item.turn_number} | "
            f"{', '.join(item.winner_player_ids) or '-'} | {item.status} |"
        )
    (output / "simple-ai-policy-report.zh-CN.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    index = max(0, math.ceil(len(values) * percentile) - 1)
    return round(values[index], 3)


if __name__ == "__main__":
    raise SystemExit(main())
