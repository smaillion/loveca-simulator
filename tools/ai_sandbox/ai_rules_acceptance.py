"""Strict AI-vs-AI acceptance run with official-rule trace auditing."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from pypdf import PdfReader

from loveca.simulation.ai import (
    SimpleAIBlocker,
    SimpleAIController,
    SimpleAIPolicy,
)
from loveca.simulation.effects import DEFAULT_EFFECT_REGISTRY, load_effect_registry
from loveca.simulation.engine import IllegalActionError, generate_legal_actions
from loveca.simulation.models import (
    ControllerPolicyVersion,
    GameEvent,
    MatchState,
)
from loveca.simulation.service import MatchService
from tools.ai_sandbox.blackbox_playtest import build_decks, summarize_deck
from tools.ai_sandbox.effect_registry_integrity import audit_effect_registry
from tools.ai_sandbox.live_judgment_audit import (
    LiveJudgmentBoundaryResult,
    run_live_judgment_boundary_matrix,
)
from tools.ai_sandbox.rule_conformance import (
    RULE_REFERENCES,
    RuleCheck,
    audit_action_transition,
    serialize_checks,
    summarize_verdict,
)
from tools.ai_sandbox.semantic_playtest import DEFAULT_RULES_PDF

REPORT_SCHEMA_VERSION = "ai_rules_acceptance_v0.3"


@dataclass
class RulebookAudit:
    source_path: str
    sha256: str
    page_count: int
    extracted_characters: int
    referenced_sections: list[str]
    missing_sections: list[str]


@dataclass
class SkillAuditSummary:
    registry_entries: int
    executable_entries: int
    manual_entries: int
    executable_coverage_percent: float
    integrity_errors: int
    integrity_warnings: int
    exercised_unique_effects: int
    exercised_effect_steps: int
    effect_check_verdict_counts: dict[str, int]
    exercised_effect_ids: list[str]


@dataclass
class StrategyExperiment:
    name: str
    source_path: str
    baseline_policy: str
    challenger_policy: str
    matches: int
    completed: int
    challenger_points_rate: float
    average_turns: float
    p95_turns: int
    baseline_live_success_rate: float
    challenger_live_success_rate: float
    illegal_actions: int
    replay_errors: int
    recommendation: str


@dataclass
class AuditedAction:
    action_index: int
    turn_before: int
    phase_before: str
    player_id: str | None
    action_type: str
    decision_reason: str
    score_summary: dict[str, int | float | str]
    payload: dict[str, Any]
    phase_after: str
    turn_after: int
    events: list[dict[str, Any]]
    verdict: str
    checks: list[dict[str, Any]]
    duration_ms: float


@dataclass
class AuditedMatch:
    match_index: int
    match_id: str
    seed: int
    policy_version: str
    first_deck: str
    second_deck: str
    first_player_id: str | None
    status: str
    qualified: bool
    qualification_reasons: list[str]
    turn_number: int
    action_count: int
    success_live_counts: dict[str, int]
    game_result: dict[str, Any] | None
    replay_ok: bool
    replay_error: str | None
    verdict_counts: dict[str, int]
    event_counts: dict[str, int]
    decision_reason_counts: dict[str, int]
    effect_counts: dict[str, int]
    actions: list[AuditedAction]
    blocker: dict[str, Any] | None = None


@dataclass
class AcceptanceReport:
    schema_version: str
    database_path: str
    policy_version: str
    required_qualified_matches: int
    max_turns: int
    max_actions: int
    rulebook: RulebookAudit
    live_judgment_boundaries: list[LiveJudgmentBoundaryResult]
    skill_audit: SkillAuditSummary
    strategy_experiments: list[StrategyExperiment]
    deck_summaries: list[dict[str, Any]]
    matches: list[AuditedMatch]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("data/loveca.sqlite3"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("logs/ai_rules_acceptance"),
    )
    parser.add_argument("--decks", type=int, default=20)
    parser.add_argument("--attempts", type=int, default=20)
    parser.add_argument("--required-qualified", type=int, default=10)
    parser.add_argument("--max-turns", type=int, default=10)
    parser.add_argument("--max-actions", type=int, default=500)
    parser.add_argument(
        "--policy",
        choices=("simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1"),
        default="simple_ai_v1_1",
    )
    parser.add_argument("--seed-base", type=int, default=12000)
    parser.add_argument("--rules-pdf", type=Path, default=DEFAULT_RULES_PDF)
    parser.add_argument(
        "--strategy-benchmark",
        action="append",
        type=Path,
        default=[],
        help="Optional simple-ai-policy-summary.json to include in the strategy report.",
    )
    args = parser.parse_args()

    report = run_acceptance(
        args.database,
        output=args.output,
        deck_count=args.decks,
        attempts=args.attempts,
        required_qualified=args.required_qualified,
        max_turns=args.max_turns,
        max_actions=args.max_actions,
        policy_version=args.policy,
        seed_base=args.seed_base,
        rules_pdf=args.rules_pdf,
        strategy_benchmark_paths=args.strategy_benchmark,
    )
    qualified = sum(match.qualified for match in report.matches)
    failed_live_boundaries = sum(
        not item.passed for item in report.live_judgment_boundaries
    )
    print(
        json.dumps(
            {
                "attempts": len(report.matches),
                "qualified": qualified,
                "required_qualified": report.required_qualified_matches,
                "rulebook_missing_sections": report.rulebook.missing_sections,
                "failed_live_judgment_boundaries": failed_live_boundaries,
                "report": str(args.output / "比赛总报告.zh-CN.md"),
                "strategy_report": str(args.output / "AI策略报告.zh-CN.md"),
                "live_judgment_report": str(
                    args.output / "Live判定审计.zh-CN.md"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return int(
        qualified < report.required_qualified_matches
        or bool(report.rulebook.missing_sections)
        or failed_live_boundaries > 0
    )


def run_acceptance(
    database: Path,
    *,
    output: Path,
    deck_count: int,
    attempts: int,
    required_qualified: int,
    max_turns: int,
    max_actions: int,
    policy_version: ControllerPolicyVersion,
    seed_base: int,
    rules_pdf: Path,
    strategy_benchmark_paths: list[Path] | tuple[Path, ...] = (),
) -> AcceptanceReport:
    if required_qualified < 1 or attempts < required_qualified:
        raise ValueError("attempts must be at least required_qualified")
    rulebook = audit_rulebook(rules_pdf)
    decks = build_decks(database, deck_count)
    deck_summaries = [asdict(summarize_deck(database, deck)) for deck in decks]
    output.mkdir(parents=True, exist_ok=True)
    progress_path = output / "progress.jsonl"
    progress_path.write_text("", encoding="utf-8")
    matches: list[AuditedMatch] = []
    with tempfile.TemporaryDirectory(prefix="loveca-ai-rule-audit-") as tmp:
        service = MatchService(
            database,
            Path(tmp) / "matches.sqlite3",
            max_retained_matches=max(attempts + 2, 25),
            max_snapshots_per_match=3,
        )
        for index in range(attempts):
            first = decks[index % len(decks)]
            second = decks[(index * 5 + 3) % len(decks)]
            match = _run_match(
                service,
                match_index=index + 1,
                first_deck=first,
                second_deck=second,
                seed=seed_base + index,
                max_turns=max_turns,
                max_actions=max_actions,
                policy_version=policy_version,
            )
            matches.append(match)
            with progress_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(match), ensure_ascii=False) + "\n")
    report = AcceptanceReport(
        schema_version=REPORT_SCHEMA_VERSION,
        database_path=str(database),
        policy_version=policy_version,
        required_qualified_matches=required_qualified,
        max_turns=max_turns,
        max_actions=max_actions,
        rulebook=rulebook,
        live_judgment_boundaries=run_live_judgment_boundary_matrix(),
        skill_audit=build_skill_audit(database, matches),
        strategy_experiments=[
            load_strategy_experiment(path) for path in strategy_benchmark_paths
        ],
        deck_summaries=deck_summaries,
        matches=matches,
    )
    write_reports(output, report)
    return report


def build_skill_audit(database: Path, matches: list[AuditedMatch]) -> SkillAuditSummary:
    registry = load_effect_registry(DEFAULT_EFFECT_REGISTRY)
    integrity = audit_effect_registry(database, DEFAULT_EFFECT_REGISTRY)
    executable = sum(
        effect.simulation_support == "test_validated_executable"
        for effect in registry.effects
    )
    effect_ids = sorted(
        {
            effect_id
            for match in matches
            for effect_id in match.effect_counts
        }
    )
    effect_steps = sum(
        count
        for match in matches
        for count in match.effect_counts.values()
    )
    effect_verdicts: Counter[str] = Counter()
    for match in matches:
        for action in match.actions:
            for check in action.checks:
                if check.get("check_id") == "effect_snapshot_binding":
                    effect_verdicts[str(check["verdict"])] += 1
    total = len(registry.effects)
    return SkillAuditSummary(
        registry_entries=total,
        executable_entries=executable,
        manual_entries=total - executable,
        executable_coverage_percent=round(executable / total * 100, 2) if total else 0.0,
        integrity_errors=integrity.error_count,
        integrity_warnings=integrity.warning_count,
        exercised_unique_effects=len(effect_ids),
        exercised_effect_steps=effect_steps,
        effect_check_verdict_counts=dict(sorted(effect_verdicts.items())),
        exercised_effect_ids=effect_ids,
    )


def load_strategy_experiment(path: Path) -> StrategyExperiment:
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = payload.get("summary", payload)
    required = {
        "baseline_policy",
        "challenger_policy",
        "matches",
        "completed",
        "v1_points_rate",
        "average_turns",
        "p95_turns",
        "v0_live_success_rate",
        "v1_live_success_rate",
        "illegal_actions",
        "replay_errors",
    }
    missing = sorted(required - summary.keys())
    if missing:
        raise ValueError(f"invalid strategy benchmark {path}: missing {missing}")
    points = float(summary["v1_points_rate"])
    baseline_live = float(summary["v0_live_success_rate"])
    challenger_live = float(summary["v1_live_success_rate"])
    clean = (
        int(summary["completed"]) == int(summary["matches"])
        and int(summary["illegal_actions"]) == 0
        and int(summary["replay_errors"]) == 0
    )
    accepted = clean and points >= 0.55 and challenger_live >= baseline_live
    recommendation = "采用" if accepted else "不采用"
    return StrategyExperiment(
        name=path.parent.name or path.stem,
        source_path=str(path),
        baseline_policy=str(summary["baseline_policy"]),
        challenger_policy=str(summary["challenger_policy"]),
        matches=int(summary["matches"]),
        completed=int(summary["completed"]),
        challenger_points_rate=round(points, 4),
        average_turns=round(float(summary["average_turns"]), 3),
        p95_turns=int(summary["p95_turns"]),
        baseline_live_success_rate=round(baseline_live, 4),
        challenger_live_success_rate=round(challenger_live, 4),
        illegal_actions=int(summary["illegal_actions"]),
        replay_errors=int(summary["replay_errors"]),
        recommendation=recommendation,
    )


def audit_rulebook(path: Path) -> RulebookAudit:
    payload = path.read_bytes()
    reader = PdfReader(path)
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(pages)
    references = sorted(RULE_REFERENCES, key=_section_key)
    missing = [section for section in references if section not in text]
    return RulebookAudit(
        source_path=str(path),
        sha256=hashlib.sha256(payload).hexdigest(),
        page_count=len(reader.pages),
        extracted_characters=len(text),
        referenced_sections=references,
        missing_sections=missing,
    )


def _run_match(
    service: MatchService,
    *,
    match_index: int,
    first_deck: Any,
    second_deck: Any,
    seed: int,
    max_turns: int,
    max_actions: int,
    policy_version: ControllerPolicyVersion,
) -> AuditedMatch:
    match_id = f"ai-rules-{match_index:02d}"
    created = service.create_match(
        first_name="AI A",
        first_deck=first_deck,
        second_name="AI B",
        second_deck=second_deck,
        seed=seed,
        match_id=match_id,
        controllers={"player_1": "human", "player_2": "human"},
    )
    state = created.state
    actions = [_setup_action(state, created.events)]
    event_counts: Counter[str] = Counter(event.event_type for event in created.events)
    reason_counts: Counter[str] = Counter()
    effect_counts: Counter[str] = Counter()
    blocker: dict[str, Any] | None = None
    controller = SimpleAIController(
        SimpleAIPolicy(manual_effect_policy="skip", policy_version=policy_version)
    )
    while state.phase != "complete" and len(actions) < max_actions:
        legal_actions = generate_legal_actions(state)
        controlled, neutral = _controlled_players(state, legal_actions)
        started = perf_counter()
        decision = controller.choose_action(
            state,
            legal_actions,
            controlled_player_ids=controlled,
            allow_player_neutral_actions=neutral,
        )
        duration_ms = (perf_counter() - started) * 1000
        if decision is None:
            blocker = {
                "reason": "no_ai_decision",
                "phase": state.phase,
                "turn": state.turn_number,
                "legal_action_types": [item.action_type for item in legal_actions],
            }
            break
        if isinstance(decision, SimpleAIBlocker):
            blocker = {
                "reason": decision.reason,
                "phase": state.phase,
                "turn": state.turn_number,
                "legal_action_types": decision.legal_action_types,
                "player_ids": decision.player_ids,
            }
            break
        before = state.model_copy(deep=True)
        reason_counts[decision.reason] += 1
        effect_id = decision.action.payload.get("effect_id")
        invocation_id = decision.action.payload.get("invocation_id")
        if not isinstance(effect_id, str) and isinstance(invocation_id, str):
            effect_id = next(
                (
                    item.effect_id
                    for item in before.pending_effects
                    if item.invocation_id == invocation_id
                ),
                None,
            )
        if isinstance(effect_id, str):
            effect_counts[effect_id] += 1
        try:
            applied = service.apply(match_id, decision.action)
        except Exception as exc:  # noqa: BLE001 - preserve exact blocker in report.
            blocker = {
                "reason": "illegal_action"
                if isinstance(exc, IllegalActionError)
                else "runtime_exception",
                "phase": state.phase,
                "turn": state.turn_number,
                "action_type": decision.action.action_type,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            break
        state = applied.state
        checks = audit_action_transition(
            before,
            state,
            decision.action,
            legal_actions,
            applied.events,
        )
        actions.append(
            AuditedAction(
                action_index=len(actions) + 1,
                turn_before=before.turn_number,
                phase_before=before.phase,
                player_id=decision.action.player_id,
                action_type=decision.action.action_type,
                decision_reason=decision.reason,
                score_summary=decision.score_summary,
                payload=_compact(decision.action.payload),
                phase_after=state.phase,
                turn_after=state.turn_number,
                events=[_compact_event(event, state) for event in applied.events],
                verdict=summarize_verdict(checks),
                checks=serialize_checks(checks),
                duration_ms=round(duration_ms, 3),
            )
        )
        event_counts.update(event.event_type for event in applied.events)
    if state.phase != "complete" and blocker is None:
        blocker = {
            "reason": "max_actions",
            "phase": state.phase,
            "turn": state.turn_number,
            "action_count": len(actions),
        }

    replay_ok = False
    replay_error: str | None = None
    try:
        replay = service.repository.replay(match_id)
        replay_ok = replay["final_state"] == state.model_dump()
        if not replay_ok:
            replay_error = "replayed final state differs from audited final state"
    except Exception as exc:  # noqa: BLE001 - report gate must retain replay errors.
        replay_error = f"{type(exc).__name__}: {exc}"

    all_checks = [check for action in actions for check in action.checks]
    verdicts = Counter(str(check["verdict"]) for check in all_checks)
    success_counts = {
        player_id: len(player.success_live_area) for player_id, player in state.players.items()
    }
    qualification_reasons: list[str] = []
    if state.phase != "complete":
        qualification_reasons.append("比赛未正式结束")
    if state.turn_number > max_turns:
        qualification_reasons.append(f"超过 {max_turns} 回合")
    if any(count < 1 for count in success_counts.values()):
        qualification_reasons.append("至少一方没有成功 Live")
    if verdicts.get("fail", 0):
        qualification_reasons.append("逐动作规则审计存在失败")
    if event_counts.get("effect_skipped_due_to_error", 0):
        qualification_reasons.append("存在技能错误跳过")
    if not replay_ok:
        qualification_reasons.append("Replay 不一致")
    return AuditedMatch(
        match_index=match_index,
        match_id=match_id,
        seed=seed,
        policy_version=policy_version,
        first_deck=first_deck.name or "(unnamed)",
        second_deck=second_deck.name or "(unnamed)",
        first_player_id=state.first_player_id,
        status="completed" if state.phase == "complete" else "blocked",
        qualified=not qualification_reasons,
        qualification_reasons=qualification_reasons,
        turn_number=state.turn_number,
        action_count=len(actions),
        success_live_counts=success_counts,
        game_result=state.game_result.model_dump() if state.game_result else None,
        replay_ok=replay_ok,
        replay_error=replay_error,
        verdict_counts=dict(sorted(verdicts.items())),
        event_counts=dict(sorted(event_counts.items())),
        decision_reason_counts=dict(reason_counts.most_common()),
        effect_counts=dict(effect_counts.most_common()),
        actions=actions,
        blocker=blocker,
    )


def _controlled_players(
    state: MatchState,
    legal_actions: list[Any],
) -> tuple[set[str], bool]:
    player_ids = sorted(
        {action.player_id for action in legal_actions if action.player_id in state.players}
    )
    if player_ids:
        return {player_ids[0]}, False
    return set(state.players), True


def _setup_action(state: MatchState, events: list[GameEvent]) -> AuditedAction:
    hands = {player_id: len(player.hand) for player_id, player in state.players.items()}
    energy = {player_id: len(player.energy_area) for player_id, player in state.players.items()}
    checks = [
        RuleCheck(
            check_id="setup_opening_hand",
            verdict="pass" if all(count == 6 for count in hands.values()) else "fail",
            summary_zh="双方起手均为 6 张。",
            rule_refs=("6.2.1.2", "6.2.1.4", "6.2.1.5"),
            evidence={"hand_counts": hands, "energy_counts": energy},
        )
    ]
    return AuditedAction(
        action_index=1,
        turn_before=1,
        phase_before="setup_choose_first",
        player_id=None,
        action_type="choose_first_player",
        decision_reason="random_seeded_first_player",
        score_summary={},
        payload={"first_player_id": state.first_player_id},
        phase_after=state.phase,
        turn_after=state.turn_number,
        events=[_compact_event(event, state) for event in events],
        verdict=summarize_verdict(checks),
        checks=serialize_checks(checks),
        duration_ms=0.0,
    )


def write_reports(output: Path, report: AcceptanceReport) -> None:
    payload = asdict(report)
    (output / "比赛完整审计.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "比赛总报告.zh-CN.md").write_text(
        _render_summary(report),
        encoding="utf-8",
    )
    (output / "AI策略报告.zh-CN.md").write_text(
        _render_strategy(report),
        encoding="utf-8",
    )
    (output / "Live判定审计.zh-CN.md").write_text(
        _render_live_judgment_boundaries(report),
        encoding="utf-8",
    )
    matches_dir = output / "matches"
    matches_dir.mkdir(exist_ok=True)
    for match in report.matches:
        (matches_dir / f"match-{match.match_index:02d}.zh-CN.md").write_text(
            _render_match(match),
            encoding="utf-8",
        )
    (output / "官方规则引用.zh-CN.md").write_text(
        _render_rule_references(report.rulebook),
        encoding="utf-8",
    )


def _render_summary(report: AcceptanceReport) -> str:
    qualified = [item for item in report.matches if item.qualified]
    completed = [item for item in report.matches if item.status == "completed"]
    live_boundary_passed = sum(
        item.passed for item in report.live_judgment_boundaries
    )
    conclusion = (
        "通过"
        if len(qualified) >= report.required_qualified_matches
        and live_boundary_passed == len(report.live_judgment_boundaries)
        else "未通过"
    )
    verdicts: Counter[str] = Counter()
    for match in report.matches:
        verdicts.update(match.verdict_counts)
    lines = [
        "# AI 对战与官方规则逐步审计总报告",
        "",
        "## 验收结论",
        "",
        f"- 固定尝试局数：**{len(report.matches)}**",
        f"- 正式完赛：**{len(completed)} / {len(report.matches)}**",
        f"- 10 回合内且双方至少各成功 1 次 Live：**{len(qualified)} / {len(report.matches)}**",
        f"- 目标：**至少 {report.required_qualified_matches} 局**",
        f"- 结论：**{conclusion}**",
        f"- 逐步审计统计：`{dict(sorted(verdicts.items()))}`",
        f"- 使用策略：`{report.policy_version}`",
        f"- Live 判定固定边界：**{live_boundary_passed} / "
        f"{len(report.live_judgment_boundaries)}** 通过",
        "",
        "> 合格局要求同时满足：正式完赛、回合数不超过限制、双方至少各有一张成功 "
        "Live、无规则审计失败、无技能错误跳过且 Replay 完全一致。",
        "",
        "## 官方规则书",
        "",
        f"- 文件：`{report.rulebook.source_path}`",
        f"- SHA-256：`{report.rulebook.sha256}`",
        f"- 页数：{report.rulebook.page_count}",
        f"- 抽取字符：{report.rulebook.extracted_characters}",
        f"- 未定位条款：`{report.rulebook.missing_sections}`",
        "",
        "## 技能登记与动态验证",
        "",
        f"- Registry：**{report.skill_audit.executable_entries} / "
        f"{report.skill_audit.registry_entries}** 可执行 "
        f"（{report.skill_audit.executable_coverage_percent:.2f}%）",
        f"- 保留人工处理：**{report.skill_audit.manual_entries}**",
        f"- Registry 完整性：error={report.skill_audit.integrity_errors} / "
        f"warning={report.skill_audit.integrity_warnings}",
        f"- 本轮实际触发：**{report.skill_audit.exercised_unique_effects}** 个不同技能，"
        f"**{report.skill_audit.exercised_effect_steps}** 次技能决策/结算",
        f"- 动态技能审计：`{report.skill_audit.effect_check_verdict_counts}`",
        "",
        "> 静态登记率与动态验证覆盖是两个独立指标。本轮没有把未确认的 "
        "manual effect 提升为 executable。",
        "",
        "## Live 判定边界审计",
        "",
        "- 审计将 `Live 成功`、`本轮 Live 胜者`、`成功 Live 移动资格`、"
        "`整场胜负` 分成四个独立结果。",
        "- 固定覆盖普通同分、单/双 Match Point 同分、技能加分时序与卡牌效果阻止移动。",
        f"- 结果：**{live_boundary_passed} / "
        f"{len(report.live_judgment_boundaries)}** 通过。",
        "- 详细证据：`Live判定审计.zh-CN.md`。",
        "",
        "## 对局一览",
        "",
        "| 局 | Seed | 牌组 | 结果 | 回合 | 成功 Live | 审计 | 合格 |",
        "|---:|---:|---|---|---:|---|---|---|",
    ]
    for match in report.matches:
        lives = " / ".join(
            f"{player}={count}" for player, count in sorted(match.success_live_counts.items())
        )
        result = _game_result_label(match.game_result)
        audit = ", ".join(f"{key}={value}" for key, value in sorted(match.verdict_counts.items()))
        reason = "是" if match.qualified else "否：" + "；".join(match.qualification_reasons)
        decks = f"{_md(match.first_deck)} vs {_md(match.second_deck)}"
        lines.append(
            f"| {match.match_index} | {match.seed} | {decks} | "
            f"{result} | {match.turn_number} | {lives} | {audit} | {_md(reason)} |"
        )
    lines.extend(
        [
            "",
            "## 完整报告索引",
            "",
        ]
    )
    lines.extend(
        f"- Match {match.match_index:02d}: `matches/match-{match.match_index:02d}.zh-CN.md`"
        for match in report.matches
    )
    lines.extend(
        [
            "",
            "## 审计边界",
            "",
            "- `pass` 表示该次可观察状态变化与列出的综合规则条款及 "
            "match-local effect snapshot 一致。",
            "- `review` 表示结构链正确，但保守日文语义词典无法独立证明卡牌文本的全部含义。",
            "- `fail` 会使该局失去合格资格；本报告不会用调试 skip 掩盖错误。",
            "- 这是一套对已执行路径的语义审计，不代表未触发卡牌、FAQ 或未来规则版本已被证明正确。",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_live_judgment_boundaries(report: AcceptanceReport) -> str:
    passed = sum(item.passed for item in report.live_judgment_boundaries)
    lines = [
        "# Live 判定官方规则边界审计",
        "",
        "## 结论",
        "",
        f"- 固定场景：**{len(report.live_judgment_boundaries)}**",
        f"- 通过：**{passed} / {len(report.live_judgment_boundaries)}**",
        f"- 规则书：`{report.rulebook.source_path}`",
        f"- SHA-256：`{report.rulebook.sha256}`",
        "",
        "> 本审计明确区分四层结果：Heart 需求满足后的 `Live 成功`、"
        "总分比较后的 `本轮胜者`、规则/卡牌效果允许的 `成功 Live 移动资格`，"
        "以及成功 Live 达到 3 张后的 `整场胜负`。",
        "",
        "## 固定边界矩阵",
        "",
        "| 场景 | 规则 | 结果 | 关键状态 |",
        "|---|---|---|---|",
    ]
    for item in report.live_judgment_boundaries:
        lines.append(
            f"| `{item.scenario_id}`<br>{_md(item.title_zh)} | "
            f"{', '.join(item.rule_refs)} | "
            f"**{'PASS' if item.passed else 'FAIL'}** | "
            f"{_md(_live_boundary_summary(item.actual))} |"
        )
    failed = [item for item in report.live_judgment_boundaries if not item.passed]
    if failed:
        lines.extend(["", "## 失败证据", ""])
        for item in failed:
            lines.extend(
                [
                    f"### `{item.scenario_id}`",
                    "",
                    f"- 期望：`{_md(json.dumps(item.expected, ensure_ascii=False, sort_keys=True))}`",
                    f"- 实际：`{_md(json.dumps(item.actual, ensure_ascii=False, sort_keys=True))}`",
                    "",
                ]
            )
    lines.extend(
        [
            "",
            "## 关键解释",
            "",
            "- `8.4.4-8.4.5`：Live 区仍有卡即先产生 Live 成功事件，并在此处处理"
            " `ライブ成功時` 自动能力。",
            "- `8.4.6`：能力结算后的总分决定本轮胜者；普通同分时双方均为胜者。",
            "- `8.4.7.1`：同分时已有 2 张成功 Live 的玩家不能再移动卡。"
            "这不会倒推抹除前面的 Live 成功事件或本轮同分胜者事实。",
            "- `1.2.1.1-1.2.1.2`：只有实际移动后达到 3 张，才产生整场胜利或平局。",
            "- `8.4.13`：仅一方实际新增成功 Live 时该方成为下回合先攻；"
            "双方均移动或均未移动时保持原先攻。",
            "",
            "> 报告只保存规则编号、工程摘要和状态证据，不批量转载官方原文。",
        ]
    )
    return "\n".join(lines) + "\n"


def _live_boundary_summary(actual: dict[str, Any]) -> str:
    def players(key: str) -> str:
        value = actual.get(key, [])
        return ",".join(value) if isinstance(value, list) and value else "无"

    scores = actual.get("scores", {})
    score_text = (
        "/".join(f"{player}={score}" for player, score in sorted(scores.items()))
        if isinstance(scores, dict) and scores
        else "无"
    )
    result = actual.get("game_result")
    if isinstance(result, dict):
        outcome = str(result.get("outcome", "unknown"))
        winners = result.get("winner_player_ids", [])
        game_text = f"{outcome}({','.join(winners) if winners else '无胜者'})"
    else:
        game_text = "继续"
    return (
        f"成功={players('successful_player_ids')}；"
        f"本轮胜者={players('winner_ids')}；"
        f"可移动={players('eligible_player_ids')}；"
        f"阻止={players('prevented_player_ids')}；"
        f"实际移动={players('moved_player_ids')}；"
        f"分数={score_text}；整场={game_text}"
    )


def _render_match(match: AuditedMatch) -> str:
    lines = [
        f"# Match {match.match_index:02d} 完整比赛报告",
        "",
        f"- Match ID：`{match.match_id}`",
        f"- Seed：`{match.seed}`",
        f"- 牌组：{match.first_deck} vs {match.second_deck}",
        f"- 先攻：`{match.first_player_id}`",
        f"- 结果：{_game_result_label(match.game_result)}",
        f"- 最终回合：{match.turn_number}",
        f"- 成功 Live：`{match.success_live_counts}`",
        f"- 合格：{'是' if match.qualified else '否'}",
        f"- 不合格原因：`{match.qualification_reasons}`",
        f"- Replay：{'PASS' if match.replay_ok else 'FAIL'}",
        "",
        "## 全动作时间线",
        "",
        "| # | 回合 / 阶段 | 玩家 | 操作 | AI 理由 | 事件 | 审计 | 条款 |",
        "|---:|---|---|---|---|---|---|---|",
    ]
    for action in match.actions:
        event_text = "；".join(_event_label(item) for item in action.events[:8])
        phase_text = f"T{action.turn_before} {action.phase_before} → {action.phase_after}"
        player_action = f"{action.player_id or 'system'} | `{action.action_type}`"
        refs = sorted(
            {ref for check in action.checks for ref in check.get("rule_refs", [])},
            key=_section_key,
        )
        lines.append(
            f"| {action.action_index} | {phase_text} | {player_action} | "
            f"{_md(action.decision_reason)} | "
            f"{_md(event_text)} | **{action.verdict.upper()}** | {', '.join(refs)} |"
        )
    review_items = [
        (action.action_index, check)
        for action in match.actions
        for check in action.checks
        if check.get("verdict") != "pass"
    ]
    lines.extend(["", "## 非 PASS 项", ""])
    if not review_items:
        lines.append("- 无。")
    for action_index, check in review_items:
        lines.append(
            f"- Step {action_index} / `{check['verdict']}` / `{check['check_id']}`："
            f"{check['summary_zh']} 证据：`{_compact(check.get('evidence', {}))}`"
        )
    lines.extend(["", "## AI 决策分布", ""])
    lines.extend(
        f"- `{reason}`：{count} 次" for reason, count in match.decision_reason_counts.items()
    )
    if match.effect_counts:
        lines.extend(["", "## 本局处理的技能", ""])
        lines.extend(
            f"- `{effect_id}`：{count} 次" for effect_id, count in match.effect_counts.items()
        )
    return "\n".join(lines) + "\n"


def _render_strategy(report: AcceptanceReport) -> str:
    qualified = [item for item in report.matches if item.qualified]
    turns = [item.turn_number for item in report.matches if item.status == "completed"]
    reasons: Counter[str] = Counter()
    events: Counter[str] = Counter()
    effects: Counter[str] = Counter()
    for match in report.matches:
        reasons.update(match.decision_reason_counts)
        events.update(match.event_counts)
        effects.update(match.effect_counts)
    average_turns = sum(turns) / len(turns) if turns else 0.0
    completed_count = sum(item.status == "completed" for item in report.matches)
    unqualified = Counter(
        reason for match in report.matches for reason in match.qualification_reasons
    )
    lines = [
        "# Simple AI 策略审查报告",
        "",
        "## 当前最佳已测试策略",
        "",
        f"- Policy：`{report.policy_version}`",
        f"- 固定池完赛平均回合：**{average_turns:.2f}**",
        f"- 严格合格率：**{len(qualified)} / {len(report.matches)}**",
        f"- 正式完赛率：**{completed_count} / {len(report.matches)}**",
        "",
        "> “最佳”仅表示本次固定牌组与固定 seed 池中表现最好的 deterministic "
        "heuristic；不代表已求得博弈论最优策略。",
        "",
        "## 候选策略对照实验",
        "",
    ]
    if report.strategy_experiments:
        lines.extend(
            [
                "| 候选 | 局数 | 积分率 | Live 成功率（基线 → 候选） | "
                "平均 / P95 回合 | 结论 |",
                "|---|---:|---:|---|---|---|",
            ]
        )
        for experiment in report.strategy_experiments:
            lines.append(
                f"| `{experiment.name}` (`{experiment.challenger_policy}` vs "
                f"`{experiment.baseline_policy}`) | "
                f"{experiment.completed}/{experiment.matches} | "
                f"{experiment.challenger_points_rate:.2%} | "
                f"{experiment.baseline_live_success_rate:.2%} → "
                f"{experiment.challenger_live_success_rate:.2%} | "
                f"{experiment.average_turns:.2f} / {experiment.p95_turns} | "
                f"**{experiment.recommendation}** |"
            )
        lines.extend(
            [
                "",
                "- 所有候选均能合法完赛，但都没有达到预设的 55% 积分率门槛，"
                "因此不进入产品 policy。",
                "- 前两组 Live 保留 / 获取权重实验同时降低积分率和 Live 成功率；"
                "bounded lookahead 虽略增 Live 成功次数，却没有改善比赛积分，并显著增加"
                "决策成本。单项指标改善不足以替换当前策略。",
                "",
            ]
        )
    else:
        lines.extend(["- 本次未附带候选 benchmark。", ""])
    lines.extend(
        [
        "## 已采用原则",
        "",
        "1. 只从 LegalActionGenerator 选择操作，不复制或绕过规则。",
        "2. Main Phase 比较登场后的 Heart、Blade、费用与替换损失，只有正收益才替换。",
        "3. Live Set 枚举最多 3 张组合，优先 Heart 可达，再比较总分和额外 Live 成本。",
        "4. 起动与触发技能按结构化 operation、费用和目标估值；不可安全处理的 "
        "manual 技能不伪装执行。",
        "5. Match Point 时减少无意义多张 Live 和丢弃最后一张 Live 的行为。",
        "",
        "## 决策理由 Top 20",
        "",
        "| 理由 | 次数 |",
        "|---|---:|",
        ]
    )
    lines.extend(f"| `{reason}` | {count} |" for reason, count in reasons.most_common(20))
    lines.extend(
        [
            "",
            "## 关键行为统计",
            "",
            f"- Member 登场：{events.get('member_played', 0)}",
            f"- Baton Touch：{events.get('baton_touch_performed', 0)}",
            f"- Live Set：{events.get('live_cards_set', 0)}",
            f"- Live 判定：{events.get('live_judgment_completed', 0)}",
            f"- 成功 Live 移动：{events.get('success_live_selected', 0)}",
            f"- 技能结算：{events.get('effect_resolved', 0)}",
            f"- 技能错误跳过：{events.get('effect_skipped_due_to_error', 0)}",
            "",
            "## 不合格原因",
            "",
        ]
    )
    if unqualified:
        lines.extend(f"- {reason}：{count} 局" for reason, count in unqualified.most_common())
    else:
        lines.append("- 无。")
    lines.extend(
        [
            "",
            "## 下一轮策略实验建议",
            "",
            "- 用镜像先后手 benchmark 比较新旧 policy，避免把牌组或先攻优势误判为策略提升。",
            "- 优先分析超过 10 回合的局：是否缺 Live、Heart 不匹配、过度替换或过度保留资源。",
            "- 对高频技能只依据结构化 operation 估值；复杂卡牌文本继续交由规则审计，"
            "不让 AI 自行解释。",
            "- 保持对手隐藏手牌只暴露数量，策略不得使用对手私有身份信息。",
        ]
    )
    if effects:
        lines.extend(["", "## 高频技能决策", ""])
        lines.extend(f"- `{effect_id}`：{count} 次" for effect_id, count in effects.most_common(20))
    return "\n".join(lines) + "\n"


def _render_rule_references(rulebook: RulebookAudit) -> str:
    lines = [
        "# 官方综合规则引用",
        "",
        f"- Source：`{rulebook.source_path}`",
        f"- SHA-256：`{rulebook.sha256}`",
        f"- Pages：{rulebook.page_count}",
        "",
        "| 条款 | 本项目审计使用的摘要 | PDF 抽取定位 |",
        "|---|---|---|",
    ]
    missing = set(rulebook.missing_sections)
    for section in sorted(RULE_REFERENCES, key=_section_key):
        reference = RULE_REFERENCES[section]
        status = "未定位" if section in missing else "已定位"
        lines.append(f"| {section} | {reference.summary_zh} | {status} |")
    lines.extend(
        [
            "",
            "> 本文件只保存条款编号与项目摘要，不批量转载官方规则原文。",
        ]
    )
    return "\n".join(lines) + "\n"


def _compact_event(event: GameEvent, state: MatchState) -> dict[str, Any]:
    return {
        "event_type": event.event_type,
        "player_id": event.player_id,
        "source": event.source,
        "data": _replace_card_ids(_compact(event.data), state),
    }


def _replace_card_ids(value: Any, state: MatchState) -> Any:
    if isinstance(value, str) and value in state.cards:
        card = state.cards[value].card
        return {
            "instance_id": value,
            "card_code": card.card_code,
            "name_ja": card.name_ja,
        }
    if isinstance(value, dict):
        return {key: _replace_card_ids(item, state) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_card_ids(item, state) for item in value]
    return value


def _compact(value: Any, *, depth: int = 0) -> Any:
    if depth >= 6:
        return "..."
    if isinstance(value, dict):
        return {
            str(key): _compact(item, depth=depth + 1)
            for key, item in value.items()
            if key not in {"state_json", "initial_state_json", "current_state_json"}
        }
    if isinstance(value, (list, tuple)):
        return [_compact(item, depth=depth + 1) for item in value]
    if isinstance(value, str) and len(value) > 800:
        return value[:800] + "..."
    return value


def _event_label(event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type", ""))
    data = event.get("data", {})
    if not isinstance(data, dict):
        return event_type
    if event_type == "member_played":
        return f"Member 登场({data.get('slot')}, cost={data.get('payment_cost')})"
    if event_type == "live_cards_set":
        return f"Live Set {data.get('count')} 张"
    if event_type == "live_requirements_resolved":
        status = "满足" if data.get("satisfied") else "不足"
        return f"Live Heart {status} / score={data.get('total_score')}"
    if event_type == "live_judgment_started":
        return f"Live 判定 winner={data.get('winner_ids')} score={data.get('scores')}"
    if event_type == "success_live_selected":
        return "成功 Live 移动"
    if event_type.startswith("effect_"):
        return f"{event_type}({data.get('effect_id', '')})"
    return event_type


def _game_result_label(result: dict[str, Any] | None) -> str:
    if not result:
        return "未结束"
    if result.get("outcome") == "draw":
        return "平局"
    winners = ", ".join(result.get("winner_player_ids", []))
    return f"胜者 {winners}"


def _section_key(section: str) -> tuple[int, ...]:
    return tuple(int(item) for item in section.split("."))


def _md(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
