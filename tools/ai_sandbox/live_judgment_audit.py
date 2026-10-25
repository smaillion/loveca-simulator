"""Implementation regression matrix for post-Heart Live judgment.

The matrix intentionally uses the production judgment path while comparing its
observable result with explicit expectations based on comprehensive rules
8.4.2-8.4.13 and 1.2.1.1-1.2.1.2. Rule-text ambiguities remain review notes.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import apply_action, generate_legal_actions
from loveca.simulation.models import (
    ActionRequest,
    CardDefinition,
    CardInstance,
    GameEvent,
    LivePerformanceResult,
    MatchState,
    PlayerState,
)

RULE_PDF_SHA256 = "c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485"
MATCH_POINT_REVIEW = (
    "PDF 8.4.7.1 的原图写作ライブ置き場；现有实现检查成功Live区2张。"
    "本项仅固定既有Match Point回归，区域解释仍需官方勘误/人工复核。"
)


@dataclass(frozen=True)
class LiveJudgmentBoundaryResult:
    scenario_id: str
    title_zh: str
    rule_refs: tuple[str, ...]
    expected: dict[str, Any]
    actual: dict[str, Any]
    passed: bool
    inputs: dict[str, Any]
    evidence_kind: str
    review_notes: tuple[str, ...]
    rule_pdf_sha256: str = RULE_PDF_SHA256


def run_live_judgment_boundary_matrix() -> list[LiveJudgmentBoundaryResult]:
    scenarios = [
        _scenario(
            "neither_successful",
            "双方均没有成功 Live",
            first_live_score=None,
            second_live_score=None,
            expected={
                "successful_player_ids": [],
                "winner_ids": [],
                "eligible_player_ids": [],
                "moved_player_ids": [],
                "next_first_player_id": "player_1",
            },
        ),
        _scenario(
            "only_one_successful",
            "仅一方有成功 Live 时不比较另一方分数",
            first_live_score=0,
            second_live_score=None,
            expected={
                "successful_player_ids": ["player_1"],
                "winner_ids": ["player_1"],
                "eligible_player_ids": ["player_1"],
                "moved_player_ids": ["player_1"],
                "next_first_player_id": "player_1",
            },
        ),
        _scenario(
            "higher_score",
            "双方成功时由较高总分玩家获胜",
            first_live_score=3,
            second_live_score=2,
            expected={
                "successful_player_ids": ["player_1", "player_2"],
                "winner_ids": ["player_1"],
                "eligible_player_ids": ["player_1"],
                "moved_player_ids": ["player_1"],
                "next_first_player_id": "player_1",
            },
        ),
        _scenario(
            "equal_score_no_match_point",
            "普通同分时双方均胜利并各移动一张",
            first_live_score=2,
            second_live_score=2,
            expected={
                "successful_player_ids": ["player_1", "player_2"],
                "winner_ids": ["player_1", "player_2"],
                "eligible_player_ids": ["player_1", "player_2"],
                "prevented_player_ids": [],
                "moved_player_ids": ["player_1", "player_2"],
                "next_first_player_id": "player_1",
            },
        ),
        _scenario(
            "equal_score_one_match_point",
            "单边 Match Point 同分时双方胜利但仅另一方移动",
            first_live_score=2,
            second_live_score=2,
            first_success_count=2,
            expected={
                "winner_ids": ["player_1", "player_2"],
                "eligible_player_ids": ["player_2"],
                "prevented_player_ids": ["player_1"],
                "moved_player_ids": ["player_2"],
                "next_first_player_id": "player_2",
                "game_result": None,
            },
        ),
        _scenario(
            "equal_score_both_match_point",
            "双方 Match Point 同分时双方胜利但均不移动",
            first_live_score=2,
            second_live_score=2,
            first_success_count=2,
            second_success_count=2,
            expected={
                "winner_ids": ["player_1", "player_2"],
                "eligible_player_ids": [],
                "prevented_player_ids": ["player_1", "player_2"],
                "moved_player_ids": [],
                "next_first_player_id": "player_1",
                "game_result": None,
            },
        ),
        _scenario(
            "higher_score_at_match_point",
            "双方 Match Point 但分数不同时高分方移动并获胜",
            first_live_score=3,
            second_live_score=2,
            first_success_count=2,
            second_success_count=2,
            expected={
                "winner_ids": ["player_1"],
                "eligible_player_ids": ["player_1"],
                "prevented_player_ids": [],
                "moved_player_ids": ["player_1"],
                "game_result": {
                    "outcome": "win",
                    "winner_player_ids": ["player_1"],
                },
            },
        ),
        _scenario(
            "live_success_score_before_comparison",
            "Live 成功时加分在胜者比较前结算",
            first_live_score=1,
            second_live_score=2,
            first_effect="score_plus_two",
            expected={
                "winner_ids": ["player_1"],
                "eligible_player_ids": ["player_1"],
                "scores": {"player_1": 3, "player_2": 2},
            },
        ),
        _scenario(
            "only_second_successful",
            "仅后攻成功时后攻移动并成为下回合先攻",
            first_live_score=None,
            second_live_score=1,
            expected={
                "winner_ids": ["player_2"],
                "eligible_player_ids": ["player_2"],
                "moved_player_ids": ["player_2"],
                "next_first_player_id": "player_2",
            },
        ),
        _scenario(
            "second_player_higher_score",
            "双方成功时后攻较高分获胜",
            first_live_score=1,
            second_live_score=3,
            expected={
                "winner_ids": ["player_2"],
                "eligible_player_ids": ["player_2"],
                "moved_player_ids": ["player_2"],
                "next_first_player_id": "player_2",
            },
        ),
        _scenario(
            "equal_zero_score",
            "双方0分成功Live仍为同分而非无人成功",
            first_live_score=0,
            second_live_score=0,
            expected={
                "winner_ids": ["player_1", "player_2"],
                "eligible_player_ids": ["player_1", "player_2"],
                "moved_player_ids": ["player_1", "player_2"],
            },
        ),
        _scenario(
            "equal_score_second_at_match_point",
            "后攻单边Match Point同分只先攻移动",
            first_live_score=2,
            second_live_score=2,
            second_success_count=2,
            expected={
                "winner_ids": ["player_1", "player_2"],
                "eligible_player_ids": ["player_1"],
                "prevented_player_ids": ["player_2"],
                "moved_player_ids": ["player_1"],
                "next_first_player_id": "player_1",
            },
        ),
        _scenario(
            "first_reaches_three_against_non_match_point",
            "先攻2对1成功Live时高分到3张获胜",
            first_live_score=3,
            second_live_score=2,
            first_success_count=2,
            second_success_count=1,
            expected={
                "winner_ids": ["player_1"],
                "eligible_player_ids": ["player_1"],
                "moved_player_ids": ["player_1"],
                "game_result": {"outcome": "win", "winner_player_ids": ["player_1"]},
            },
        ),
        _scenario(
            "second_reaches_three_against_non_match_point",
            "后攻1对2成功Live时高分到3张获胜",
            first_live_score=1,
            second_live_score=3,
            first_success_count=1,
            second_success_count=2,
            expected={
                "winner_ids": ["player_2"],
                "eligible_player_ids": ["player_2"],
                "moved_player_ids": ["player_2"],
                "game_result": {"outcome": "win", "winner_player_ids": ["player_2"]},
            },
        ),
        _scenario(
            "match_point_player_loses",
            "先攻Match Point低分不获胜",
            first_live_score=1,
            second_live_score=2,
            first_success_count=2,
            expected={
                "winner_ids": ["player_2"],
                "eligible_player_ids": ["player_2"],
                "moved_player_ids": ["player_2"],
                "next_first_player_id": "player_2",
            },
        ),
        _scenario(
            "second_match_point_player_loses",
            "后攻Match Point低分不获胜",
            first_live_score=2,
            second_live_score=1,
            second_success_count=2,
            expected={
                "winner_ids": ["player_1"],
                "eligible_player_ids": ["player_1"],
                "moved_player_ids": ["player_1"],
            },
        ),
        _scenario(
            "match_point_without_successful_live",
            "已有2张成功Live但本轮无人成功不提前获胜",
            first_live_score=None,
            second_live_score=None,
            first_success_count=2,
            expected={"winner_ids": [], "eligible_player_ids": [], "moved_player_ids": []},
        ),
        _scenario(
            "live_success_score_creates_equal_result",
            "成功时加分把落后改为双方同分",
            first_live_score=1,
            second_live_score=3,
            first_effect="score_plus_two",
            expected={
                "winner_ids": ["player_1", "player_2"],
                "eligible_player_ids": ["player_1", "player_2"],
                "moved_player_ids": ["player_1", "player_2"],
                "scores": {"player_1": 3, "player_2": 3},
            },
        ),
        _scenario(
            "score_bonus_equal_at_match_point",
            "成功时加分追平后仍应用Match Point移动限制",
            first_live_score=1,
            second_live_score=3,
            first_success_count=2,
            first_effect="score_plus_two",
            expected={
                "winner_ids": ["player_1", "player_2"],
                "eligible_player_ids": ["player_2"],
                "prevented_player_ids": ["player_1"],
                "moved_player_ids": ["player_2"],
                "next_first_player_id": "player_2",
                "scores": {"player_1": 3, "player_2": 3},
            },
        ),
        _scenario(
            "card_effect_blocks_equal_placement",
            "卡牌效果可在同分时阻止双方移动成功 Live",
            first_live_score=2,
            second_live_score=2,
            first_effect="block_equal_placement",
            expected={
                "winner_ids": ["player_1", "player_2"],
                "eligible_player_ids": [],
                "prevented_player_ids": ["player_1", "player_2"],
                "moved_player_ids": [],
            },
        ),
    ]
    return scenarios


def serialize_live_judgment_boundary_matrix() -> list[dict[str, Any]]:
    return [asdict(item) for item in run_live_judgment_boundary_matrix()]


def _scenario(
    scenario_id: str,
    title_zh: str,
    *,
    first_live_score: int | None,
    second_live_score: int | None,
    first_success_count: int = 0,
    second_success_count: int = 0,
    first_effect: str | None = None,
    expected: dict[str, Any],
) -> LiveJudgmentBoundaryResult:
    inputs = dict(
        first_live_score=first_live_score,
        second_live_score=second_live_score,
        first_success_count=first_success_count,
        second_success_count=second_success_count,
        first_effect=first_effect,
    )
    state = _build_state(**inputs)
    action = judgment_action(state)
    result = apply_action(state, action)
    state, events = result.state, result.events
    actual = judgment_outcome(state, events)
    # Complete the oracle from fixture inputs and explicit movement expectations,
    # never from the observed engine result.
    expected = {
        "successful_player_ids": [
            p
            for p, score in (("player_1", first_live_score), ("player_2", second_live_score))
            if score is not None
        ],
        "prevented_player_ids": [],
        "game_result": None,
        "scores": {
            "player_1": (first_live_score or 0) + (2 if first_effect == "score_plus_two" else 0),
            "player_2": second_live_score or 0,
        },
        **expected,
    }
    expected.setdefault("moved_player_ids", list(expected["eligible_player_ids"]))
    moved = expected["moved_player_ids"]
    expected.setdefault(
        "next_first_player_id",
        None if expected["game_result"] else (moved[0] if len(moved) == 1 else "player_1"),
    )
    expected["phase"] = "complete" if expected["game_result"] else "turn_complete"
    expected["pending_effect_count"] = 0
    expected["pending_choice"] = None
    expected["modifier_count"] = 0
    expected["success_counts"] = {
        "player_1": first_success_count + ("player_1" in moved),
        "player_2": second_success_count + ("player_2" in moved),
    }
    expected["success_live_ids"] = {
        p: [f"{p}-success-{i}" for i in range(count)]
        + ([f"{p}-current-live"] if p in moved else [])
        for p, count in (("player_1", first_success_count), ("player_2", second_success_count))
    }
    expected["live_areas"] = {"player_1": [], "player_2": []}
    expected["resolution_areas"] = {"player_1": [], "player_2": []}
    expected["waiting_rooms"] = {
        p: sorted(
            [f"{p}-yell"] + ([f"{p}-current-live"] if score is not None and p not in moved else [])
        )
        for p, score in (("player_1", first_live_score), ("player_2", second_live_score))
    }
    needs_review = len(expected["winner_ids"]) == 2 and 2 in (
        first_success_count,
        second_success_count,
    )
    return LiveJudgmentBoundaryResult(
        scenario_id=scenario_id,
        title_zh=title_zh,
        rule_refs=(
            "8.4.2",
            "8.4.4",
            "8.4.5",
            "8.4.6",
            "8.4.7",
            "8.4.7.1",
            "8.4.8",
            "8.4.13",
            "1.2.1.1",
            "1.2.1.2",
        ),
        expected=expected,
        actual=actual,
        passed=all(actual[key] == value for key, value in expected.items()),
        inputs=inputs,
        evidence_kind="synthetic_effect_fixture" if first_effect else "core_score_transition",
        review_notes=(MATCH_POINT_REVIEW,) if needs_review else (),
    )


def judgment_action(state: MatchState) -> ActionRequest:
    legal = next(a for a in generate_legal_actions(state) if a.action_type == "advance_phase")
    return ActionRequest(
        action_type=legal.action_type,
        player_id=legal.player_id,
        expected_revision=state.revision,
        payload={},
    )


def judgment_outcome(state: MatchState, events: list[GameEvent]) -> dict[str, Any]:
    summary = state.live_judgment_summary or {}
    return {
        "successful_player_ids": list(state.live_success_player_ids),
        "winner_ids": list(state.live_winner_ids),
        "eligible_player_ids": list(state.live_placement_eligible_player_ids),
        "prevented_player_ids": list(state.live_placement_prevented_player_ids),
        "moved_player_ids": list(state.success_live_moved_player_ids),
        "next_first_player_id": state.next_first_player_id,
        "scores": {
            player_id: int(detail.get("total_score", 0))
            for player_id, detail in summary.get("players", {}).items()
        },
        "game_result": (
            {
                "outcome": state.game_result.outcome,
                "winner_player_ids": list(state.game_result.winner_player_ids),
            }
            if state.game_result
            else None
        ),
        "event_types": [event.event_type for event in events],
        "phase": state.phase,
        "pending_effect_count": len(state.pending_effects),
        "pending_choice": state.pending_choice,
        "modifier_count": sum(len(p.manual_modifiers) for p in state.players.values()),
        "success_counts": {p: len(s.success_live_area) for p, s in state.players.items()},
        "success_live_ids": {p: list(s.success_live_area) for p, s in state.players.items()},
        "live_areas": {p: list(s.live_area) for p, s in state.players.items()},
        "resolution_areas": {p: list(s.resolution_area) for p, s in state.players.items()},
        "waiting_rooms": {p: sorted(s.waiting_room) for p, s in state.players.items()},
    }


def _build_state(
    *,
    first_live_score: int | None,
    second_live_score: int | None,
    first_success_count: int,
    second_success_count: int,
    first_effect: str | None,
) -> MatchState:
    effect = _effect_definition(first_effect) if first_effect else None
    cards: dict[str, CardInstance] = {}
    players: dict[str, PlayerState] = {}
    for player_id, live_score, success_count in (
        ("player_1", first_live_score, first_success_count),
        ("player_2", second_live_score, second_success_count),
    ):
        success_ids = []
        for index in range(success_count):
            instance_id = f"{player_id}-success-{index}"
            cards[instance_id] = _live_instance(instance_id, player_id, 1)
            success_ids.append(instance_id)
        live_ids = []
        if live_score is not None:
            instance_id = f"{player_id}-current-live"
            card = _live_instance(instance_id, player_id, live_score)
            if player_id == "player_1" and effect is not None:
                card.card.effect_ids = [effect.effect_id]
                card.card.effect_registry_status = "supported"
            cards[instance_id] = card
            live_ids.append(instance_id)
        players[player_id] = PlayerState(
            player_id=player_id,
            name=player_id,
            live_area=live_ids,
            success_live_area=success_ids,
            resolution_area=[f"{player_id}-yell"],
            live_result=LivePerformanceResult(
                requirements_satisfied=bool(live_ids),
                base_score=live_score or 0,
                total_score=live_score or 0,
            ),
        )
        cards[f"{player_id}-yell"] = _live_instance(f"{player_id}-yell", player_id, 0)
    return MatchState(
        match_id="live-boundary-audit",
        seed=1,
        phase="live_judgment",
        first_player_id="player_1",
        second_player_id="player_2",
        players=players,
        cards=cards,
        effect_definitions={effect.effect_id: effect} if effect else {},
    )


def _live_instance(
    instance_id: str,
    player_id: str,
    score: int,
) -> CardInstance:
    return CardInstance(
        instance_id=instance_id,
        owner_id=player_id,
        card=CardDefinition(
            card_code=instance_id,
            card_id=instance_id,
            name_ja=instance_id,
            card_type="live",
            score=score,
        ),
    )


def _effect_definition(kind: str) -> EffectDefinition:
    action = (
        {"action_type": "modify_score", "amount": 2}
        if kind == "score_plus_two"
        else {"action_type": "prevent_equal_score_success_live_placement"}
    )
    condition = {} if kind == "score_plus_two" else {"live_score_relation": "equal_to_opponent"}
    return EffectDefinition.model_validate(
        {
            "effect_id": f"audit-{kind}:1",
            "card_code": "AUDIT-LIVE",
            "text_revision_id": 1,
            "raw_text_hash": "a" * 64,
            "effect_index": 1,
            "label_ja": f"【ライブ成功時】{kind}",
            "effect_type": "triggered",
            "timing": "live_success",
            "trigger": "live_succeeded",
            "execution_mode": "auto_resolve",
            "frequency_limit": "once_per_live",
            "is_optional": False,
            "condition": condition,
            "cost": [],
            "choice": None,
            "actions": [action],
            "duration": "live",
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "Comprehensive rules ver. 1.06 audit fixture",
        }
    )


def render_boundary_report(results: list[LiveJudgmentBoundaryResult]) -> str:
    fixture_count = sum(case.evidence_kind == "synthetic_effect_fixture" for case in results)
    fields = {
        "successful_player_ids": "达成Live成功的玩家",
        "winner_ids": "Performance胜者",
        "eligible_player_ids": "允许移动成功Live",
        "prevented_player_ids": "禁止移动成功Live",
        "moved_player_ids": "实际移动成功Live",
        "next_first_player_id": "下回合先攻",
        "scores": "有效总分",
        "game_result": "最终胜负",
        "phase": "结束阶段",
        "pending_effect_count": "待处理技能数",
        "pending_choice": "待选择内容",
        "modifier_count": "残留临时补正数",
        "success_counts": "成功Live总张数",
        "success_live_ids": "成功Live区实际卡牌",
        "live_areas": "Live区剩余卡牌",
        "resolution_areas": "应援公开区剩余卡牌",
        "waiting_rooms": "控室实际卡牌",
    }
    lines = [
        "# Live得分与移动资格：实现回归报告",
        "",
        f"- 实现回归：{sum(r.passed for r in results)}/{len(results)}。",
        f"- 规则区域措辞待复核：{sum(bool(r.review_notes) for r in results)}项（不是规则已认证）。",
        f"- 合成技能fixture：{fixture_count}项，不计入卡牌支持数。",
        f"- 本地官方综合规则ver.1.06，SHA-256：`{RULE_PDF_SHA256}`。",
        "",
        "范围：从已完成Heart需求判定的状态开始，经原生合法Action执行得分比较、移动、清理和胜负。",
        "不验证Heart分配、Yell生成、完整结束阶段检查循环；SQLite Replay另由逐项测试验证。",
        "",
        MATCH_POINT_REVIEW,
        "",
        "下表的先攻/后攻仅表示本轮初始顺序；对局结束后不存在下回合先攻。",
        "",
    ]
    for case in results:
        scores = (case.inputs["first_live_score"], case.inputs["second_live_score"])
        lines.extend(
            [
                f"## {case.title_zh}",
                "",
                f"- 场景：`{case.scenario_id}`。",
                f"- 初始本轮Live分数（无表示没有成功Live）：先攻{scores[0]} / 后攻{scores[1]}。",
                f"- 初始成功Live张数：先攻{case.inputs['first_success_count']} / "
                f"后攻{case.inputs['second_success_count']}。",
                f"- 规则引用：{', '.join(case.rule_refs)}。",
                "- 证据："
                f"{'合成技能状态转换' if case.inputs['first_effect'] else '核心得分状态转换'}；"
                f"实现{'通过' if case.passed else '失败'}。",
            ]
        )
        if case.inputs["first_effect"]:
            lines.append(f"- 合成技能：{case.inputs['first_effect']}（非真实卡牌登记验证）。")
        lines.extend(f"- 待复核：{note}" for note in case.review_notes)
        lines.extend(["", "| 检查项 | 期望 | 实际 |", "| --- | --- | --- |"])
        for key, expected in case.expected.items():
            values = [
                json.dumps(v, ensure_ascii=False)
                .replace("player_1", "先攻")
                .replace("player_2", "后攻")
                for v in (expected, case.actual[key])
            ]
            lines.append(f"| {fields[key]} | {values[0]} | {values[1]} |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Live得分与移动资格回归；不等同官方裁定认证")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = run_live_judgment_boundary_matrix()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "live-boundaries.json").write_text(
        json.dumps([asdict(case) for case in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.output / "Live判定回归.zh-CN.md").write_text(
        render_boundary_report(results), encoding="utf-8"
    )
    print(
        f"Live实现回归 {sum(case.passed for case in results)}/{len(results)}；"
        f"规则措辞待复核 {sum(bool(case.review_notes) for case in results)}；报告 {args.output}"
    )
    return 0 if all(case.passed for case in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
