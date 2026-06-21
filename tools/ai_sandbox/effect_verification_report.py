"""Human-readable effect scenario verification reports.

This tool is deterministic and local. It does not play a whole match; it runs
small effect-focused scenarios and writes Japanese / Chinese Markdown reports
with official card images when the local card DB is available.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from loveca.simulation.effects import (
    DEFAULT_EFFECT_REGISTRY,
    EffectDefinition,
    load_effect_registry,
)
from loveca.simulation.engine import (
    IllegalActionError,
    _queue_live_success_effects,
    _resolve_automatic_effects,
    apply_action,
    generate_legal_actions,
)
from loveca.simulation.models import (
    ActionRequest,
    CardDefinition,
    CardInstance,
    EffectInvocation,
    GameEvent,
    MatchState,
    PlayerState,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "loveca.sqlite3"
DEFAULT_OUTPUT = PROJECT_ROOT / "logs" / "effect_verification"
ReportLanguage = Literal["ja", "zh"]


@dataclass
class CardVisual:
    role_ja: str
    role_zh: str
    card_code: str
    name_ja: str
    card_id: str | None = None
    image_url: str | None = None


@dataclass
class ScenarioResult:
    scenario_id: str
    title_ja: str
    title_zh: str
    status: str
    effect_id: str
    steps_ja: list[str]
    steps_zh: list[str]
    expected_ja: list[str]
    expected_zh: list[str]
    actual_ja: list[str]
    actual_zh: list[str]
    visuals: list[CardVisual] = field(default_factory=list)
    notes_ja: list[str] = field(default_factory=list)
    notes_zh: list[str] = field(default_factory=list)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_EFFECT_REGISTRY,
        help="Effect registry JSON path.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help="Local card database used only to attach official card image URLs.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Directory for Markdown and JSON reports.",
    )
    args = parser.parse_args()

    results = run_effect_verification_scenarios(args.registry, args.database)
    write_effect_verification_report(args.output, results)
    print(
        "Wrote effect verification reports to "
        f"{args.output / 'effect-verification-report.md'}"
    )
    return 0 if all(result.status == "PASS" for result in results) else 1


def run_effect_verification_scenarios(
    registry_path: Path = DEFAULT_EFFECT_REGISTRY,
    database_path: Path = DEFAULT_DATABASE,
) -> list[ScenarioResult]:
    registry = load_effect_registry(registry_path)
    effects = {effect.effect_id: effect for effect in registry.effects}
    visuals = _load_report_visuals(database_path)
    effect = effects["PL!HS-bp6-014:1"]
    return [
        _verify_pl_hs_bp6_014_with_target(effect, visuals),
        _verify_pl_hs_bp6_014_without_target(effect, visuals),
        _verify_pl_hs_bp2_026_live_start_score_modifier(visuals),
        _verify_pl_hs_bp6_006_cost_reduction(visuals),
        _verify_pl_hs_bp6_006_live_success_skip_ready(visuals),
        _verify_baton_repeat_prevention(visuals),
        _verify_pl_hs_sd1_005_same_name_baton_blocked(visuals),
    ]


def write_effect_verification_report(
    output_dir: Path,
    results: list[ScenarioResult],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "effect-verification-summary.json").write_text(
        json.dumps(
            {
                "schema_version": "effect_verification_report_v0.2",
                "total": len(results),
                "passed": sum(1 for result in results if result.status == "PASS"),
                "failed": sum(1 for result in results if result.status != "PASS"),
                "results": [asdict(result) for result in results],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    ja_report = _render_markdown(results, "ja")
    zh_report = _render_markdown(results, "zh")
    (output_dir / "effect-verification-report.md").write_text(
        ja_report,
        encoding="utf-8",
    )
    (output_dir / "effect-verification-report.ja.md").write_text(
        ja_report,
        encoding="utf-8",
    )
    (output_dir / "effect-verification-report.zh-CN.md").write_text(
        zh_report,
        encoding="utf-8",
    )


def _render_markdown(results: list[ScenarioResult], language: ReportLanguage) -> str:
    if language == "ja":
        title = "Effect 検証レポート"
        intro = [
            "このレポートは、固定シナリオで effect の処理結果を人間が確認しやすくするためのものです。",
            "registry coverage や公式ルールレビューの代替ではありません。",
        ]
        headers = ("シナリオ", "Effect", "結果")
    else:
        title = "技能验证报告"
        intro = [
            "这个报告使用固定场景验证 effect 的处理结果，目的是让人工复核更容易。",
            "它不是 registry 覆盖率指标，也不能替代官方规则审查。",
        ]
        headers = ("场景", "Effect", "结果")
    lines = [
        f"# {title}",
        "",
        *intro,
        "",
        f"| {headers[0]} | {headers[1]} | {headers[2]} |",
        "| --- | --- | --- |",
    ]
    for result in results:
        scenario_title = result.title_ja if language == "ja" else result.title_zh
        lines.append(
            f"| {_markdown_cell(scenario_title)} | `{result.effect_id}` | **{result.status}** |"
        )
    for result in results:
        lines.extend(_render_scenario(result, language))
    return "\n".join(lines) + "\n"


def _render_scenario(
    result: ScenarioResult,
    language: ReportLanguage,
) -> list[str]:
    title = result.title_ja if language == "ja" else result.title_zh
    steps = result.steps_ja if language == "ja" else result.steps_zh
    expected = result.expected_ja if language == "ja" else result.expected_zh
    actual = result.actual_ja if language == "ja" else result.actual_zh
    notes = result.notes_ja if language == "ja" else result.notes_zh
    if language == "ja":
        labels = {
            "scenario_id": "シナリオ ID",
            "result": "結果",
            "cards": "確認対象カード",
            "steps": "操作手順",
            "expected": "期待結果",
            "actual": "実測結果",
            "notes": "補足",
        }
    else:
        labels = {
            "scenario_id": "场景 ID",
            "result": "结果",
            "cards": "确认对象卡牌",
            "steps": "操作步骤",
            "expected": "期望结果",
            "actual": "实际结果",
            "notes": "补充",
        }
    lines = [
        "",
        f"## {title}",
        "",
        f"* {labels['scenario_id']}: `{result.scenario_id}`",
        f"* Effect: `{result.effect_id}`",
        f"* {labels['result']}: **{result.status}**",
        "",
        f"### {labels['cards']}",
        "",
    ]
    if result.visuals:
        lines.extend(_render_visual_table(result.visuals, language))
    else:
        lines.append("_No card images available from local database._")
    lines.extend(["", f"### {labels['steps']}"])
    lines.extend(f"{index}. {step}" for index, step in enumerate(steps, start=1))
    lines.extend(["", f"### {labels['expected']}"])
    lines.extend(f"* {item}" for item in expected)
    lines.extend(["", f"### {labels['actual']}"])
    lines.extend(f"* {item}" for item in actual)
    if notes:
        lines.extend(["", f"### {labels['notes']}"])
        lines.extend(f"* {item}" for item in notes)
    return lines


def _render_visual_table(
    visuals: list[CardVisual],
    language: ReportLanguage,
) -> list[str]:
    role_label = "役割" if language == "ja" else "角色"
    card_label = "カード" if language == "ja" else "卡牌"
    image_label = "画像" if language == "ja" else "图片"
    lines = [
        f"| {role_label} | {card_label} | {image_label} |",
        "| --- | --- | --- |",
    ]
    for visual in visuals:
        role = visual.role_ja if language == "ja" else visual.role_zh
        card_bits = [
            visual.name_ja,
            f"`{visual.card_code}`",
        ]
        if visual.card_id:
            card_bits.append(f"`{visual.card_id}`")
        image = (
            f'<img src="{visual.image_url}" alt="{visual.name_ja}" width="150">'
            if visual.image_url
            else "画像なし" if language == "ja" else "无图片"
        )
        lines.append(
            f"| {_markdown_cell(role)} | {'<br>'.join(card_bits)} | {image} |"
        )
    return lines


def _verify_pl_hs_bp6_014_with_target(
    effect: EffectDefinition,
    visuals: dict[str, CardVisual],
) -> ScenarioResult:
    steps_ja = [
        "メインフェイズ中、`PL!HS-bp6-014` を手札に置く。",
        "自分の Stage に「藤島 慈」を置く。",
        "手札から起動能力を発動する。",
        "後続選択で「藤島 慈」を対象に選ぶ。",
    ]
    steps_zh = [
        "在主阶段，把 `PL!HS-bp6-014` 放在手牌。",
        "把「藤島 慈」放在自己的 Stage。",
        "从手牌发动该起动能力。",
        "在后续选择中选择「藤島 慈」作为目标。",
    ]
    expected_ja = [
        "`PL!HS-bp6-014` はコストとして手札から控室へ移動する。",
        "カードを 1 枚引く。",
        "選択した「藤島 慈」は Live 終了時まで Blade +1 を得る。",
        "pending effect は残らない。",
    ]
    expected_zh = [
        "`PL!HS-bp6-014` 作为成本从手牌进入控室。",
        "抽 1 张牌。",
        "选择的「藤島 慈」到 Live 结束前获得 Blade +1。",
        "不会留下 pending effect。",
    ]
    visual_list = [
        visuals["source"],
        visuals.get("megumi", _fallback_visual("対象", "目标", "TEST-MEGUMI", "藤島 慈")),
    ]
    try:
        state = _pl_hs_bp6_014_state(effect, include_named_target=True)
        state = _activate_pl_hs_bp6_014(state)
        invocation = state.pending_effects[0]
        state = _apply(
            state,
            "resolve_effect",
            player_id="player_1",
            payload={
                "invocation_id": invocation.invocation_id,
                "selected_card_instance_ids": ["megumi"],
            },
        )
        player = state.players["player_1"]
        checks = {
            "source_in_waiting_room": "hand-source" in player.waiting_room,
            "source_removed_from_hand": "hand-source" not in player.hand,
            "drawn_card_in_hand": "draw-card" in player.hand,
            "blade_modifier": any(
                modifier.modifier_type == "blade"
                and modifier.amount == 1
                and modifier.target_card_instance_id == "megumi"
                for modifier in player.manual_modifiers
            ),
            "pending_effects_cleared": not state.pending_effects,
        }
        status = "PASS" if all(checks.values()) else "FAIL"
        return ScenarioResult(
            scenario_id="pl_hs_bp6_014_with_target",
            title_ja="PL!HS-bp6-014: 手札起動、Blade 対象あり",
            title_zh="PL!HS-bp6-014：从手牌发动，有 Blade 目标",
            status=status,
            effect_id=effect.effect_id,
            steps_ja=steps_ja,
            steps_zh=steps_zh,
            expected_ja=expected_ja,
            expected_zh=expected_zh,
            actual_ja=_format_checks(checks, "ja")
            + [
                "実行後: 手札に `ドローカード`、控室に `安養寺 姫芽`。",
                "実行後: 「藤島 慈」に Live duration の Blade +1 modifier。",
            ],
            actual_zh=_format_checks(checks, "zh")
            + [
                "执行后：手牌有 `ドローカード`，控室有 `安養寺 姫芽`。",
                "执行后：「藤島 慈」获得持续到 Live 结束的 Blade +1 modifier。",
            ],
            visuals=visual_list,
        )
    except Exception as exc:  # pragma: no cover - failure is rendered in report
        return _exception_result(
            "pl_hs_bp6_014_with_target",
            "PL!HS-bp6-014: 手札起動、Blade 対象あり",
            "PL!HS-bp6-014：从手牌发动，有 Blade 目标",
            effect.effect_id,
            steps_ja,
            steps_zh,
            expected_ja,
            expected_zh,
            visual_list,
            exc,
        )


def _verify_pl_hs_bp6_014_without_target(
    effect: EffectDefinition,
    visuals: dict[str, CardVisual],
) -> ScenarioResult:
    steps_ja = [
        "メインフェイズ中、`PL!HS-bp6-014` を手札に置く。",
        "Stage には「藤島 慈」も「大沢瑠璃乃」も置かない。",
        "手札から起動能力を発動する。",
        "後続選択で対象 0 枚として解決する。",
    ]
    steps_zh = [
        "在主阶段，把 `PL!HS-bp6-014` 放在手牌。",
        "Stage 上不放「藤島 慈」或「大沢瑠璃乃」。",
        "从手牌发动该起动能力。",
        "在后续选择中以 0 个目标结算。",
    ]
    expected_ja = [
        "「藤島 慈」/「大沢瑠璃乃」が Stage にいないことは起動条件ではない。",
        "`PL!HS-bp6-014` は手札から控室へ移動する。",
        "カードを 1 枚引く。",
        "合法対象がないため Blade modifier は作られない。",
        "pending effect は残らない。",
    ]
    expected_zh = [
        "场上没有「藤島 慈」/「大沢瑠璃乃」不是发动条件。",
        "`PL!HS-bp6-014` 从手牌进入控室。",
        "抽 1 张牌。",
        "因为没有合法目标，不生成 Blade modifier。",
        "不会留下 pending effect。",
    ]
    visual_list = [visuals["source"]]
    try:
        state = _pl_hs_bp6_014_state(effect, include_named_target=False)
        legal_activations = [
            entry
            for action in generate_legal_actions(state)
            if action.action_type == "activate_effect"
            for entry in action.options["activations"]
        ]
        state = _activate_pl_hs_bp6_014(state)
        invocation = state.pending_effects[0]
        options = generate_legal_actions(state)[0].options["invocations"][0]
        state = _apply(
            state,
            "resolve_effect",
            player_id="player_1",
            payload={
                "invocation_id": invocation.invocation_id,
                "selected_card_instance_ids": [],
            },
        )
        player = state.players["player_1"]
        checks = {
            "activation_available_without_target": any(
                entry["effect_id"] == effect.effect_id for entry in legal_activations
            ),
            "choice_minimum_is_zero": options.get("card_selection_minimum") == 0,
            "no_candidate_targets": options.get("candidate_card_instance_ids") == [],
            "source_in_waiting_room": "hand-source" in player.waiting_room,
            "source_removed_from_hand": "hand-source" not in player.hand,
            "drawn_card_in_hand": "draw-card" in player.hand,
            "no_blade_modifier": not player.manual_modifiers,
            "pending_effects_cleared": not state.pending_effects,
        }
        status = "PASS" if all(checks.values()) else "FAIL"
        return ScenarioResult(
            scenario_id="pl_hs_bp6_014_without_target",
            title_ja="PL!HS-bp6-014: 手札起動、Blade 対象なし",
            title_zh="PL!HS-bp6-014：从手牌发动，无 Blade 目标",
            status=status,
            effect_id=effect.effect_id,
            steps_ja=steps_ja,
            steps_zh=steps_zh,
            expected_ja=expected_ja,
            expected_zh=expected_zh,
            actual_ja=_format_checks(checks, "ja")
            + [
                "実行後: 手札に `ドローカード`、控室に `安養寺 姫芽`。",
                "実行後: 対象がないため Blade modifier は 0 件。",
            ],
            actual_zh=_format_checks(checks, "zh")
            + [
                "执行后：手牌有 `ドローカード`，控室有 `安養寺 姫芽`。",
                "执行后：没有目标，因此 Blade modifier 为 0 件。",
            ],
            visuals=visual_list,
        )
    except Exception as exc:  # pragma: no cover - failure is rendered in report
        return _exception_result(
            "pl_hs_bp6_014_without_target",
            "PL!HS-bp6-014: 手札起動、Blade 対象なし",
            "PL!HS-bp6-014：从手牌发动，无 Blade 目标",
            effect.effect_id,
            steps_ja,
            steps_zh,
            expected_ja,
            expected_zh,
            visual_list,
            exc,
        )


def _verify_pl_hs_bp2_026_live_start_score_modifier(
    visuals: dict[str, CardVisual],
) -> ScenarioResult:
    effect = EffectDefinition(
        effect_id="verify-pl-hs-bp2-026:1",
        card_code="PL!HS-bp2-026",
        text_revision_id=1,
        raw_text_hash="m" * 64,
        effect_index=1,
        label_ja=(
            "【ライブ開始時】自分のステージの左に「安養寺姫芽」、中央に"
            "「藤島慈」、右に「大沢瑠璃乃」がいる場合、このカードのスコアを＋２する。"
        ),
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "own_stage_slot_names": {
                "left": "安養寺 姫芽",
                "center": "藤島 慈",
                "right": "大沢 瑠璃乃",
            }
        },
        cost=[],
        choice=None,
        actions=[{"action_type": "modify_score", "amount": 2}],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="verification scenario",
    )
    steps_ja = [
        "左に「安養寺姫芽」、中央に「藤島慈」、右に「大沢瑠璃乃」を置く。",
        "`PL!HS-bp2-026` の Live 開始時 effect を解決する。",
        "名前の空白有無に関係なく条件が一致するか確認する。",
    ]
    steps_zh = [
        "左侧放「安養寺姫芽」，中央放「藤島慈」，右侧放「大沢瑠璃乃」。",
        "结算 `PL!HS-bp2-026` 的 Live 开始时效果。",
        "确认名字中有没有空格都能正确匹配条件。",
    ]
    expected_ja = [
        "Stage の位置条件が成立する。",
        "本 Live 中、この Live カードの score +2 modifier が作られる。",
    ]
    expected_zh = [
        "Stage 的位置条件成立。",
        "本次 Live 中，该 Live 卡生成 score +2 modifier。",
    ]
    visual_list = [
        visuals["miracreation"],
        visuals["hime_bp6"],
        visuals["megumi"],
        visuals["rurino"],
    ]
    try:
        state = _minimal_pending_effect_state(effect)
        for slot, name_ja in {
            "left": "安養寺姫芽",
            "center": "藤島慈",
            "right": "大沢瑠璃乃",
        }.items():
            instance_id = f"stage-{slot}"
            state.cards[instance_id] = CardInstance(
                instance_id=instance_id,
                owner_id="player_1",
                card=CardDefinition(
                    card_code=f"VERIFY-{slot}",
                    card_id=f"VERIFY-{slot}",
                    name_ja=name_ja,
                    card_type="member",
                ),
            )
            state.players["player_1"].member_area[slot] = instance_id
        state = _apply(
            state,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )
        checks = {
            "score_modifier_created": any(
                modifier.modifier_type == "score"
                and modifier.amount == 2
                and modifier.duration == "live"
                for modifier in state.players["player_1"].manual_modifiers
            ),
            "pending_effects_cleared": not state.pending_effects,
        }
        return _scenario_result(
            scenario_id="pl_hs_bp2_026_live_start_score_modifier",
            title_ja="PL!HS-bp2-026: Live 開始時 score +2",
            title_zh="PL!HS-bp2-026：Live 开始时 score +2",
            status="PASS" if all(checks.values()) else "FAIL",
            effect_id="PL!HS-bp2-026:1",
            steps_ja=steps_ja,
            steps_zh=steps_zh,
            expected_ja=expected_ja,
            expected_zh=expected_zh,
            actual_ja=_format_checks(checks, "ja")
            + ["実行後: Live duration の score +2 modifier を確認。"],
            actual_zh=_format_checks(checks, "zh")
            + ["执行后：确认生成持续到 Live 结束的 score +2 modifier。"],
            visuals=visual_list,
        )
    except Exception as exc:  # pragma: no cover
        return _exception_result(
            "pl_hs_bp2_026_live_start_score_modifier",
            "PL!HS-bp2-026: Live 開始時 score +2",
            "PL!HS-bp2-026：Live 开始时 score +2",
            "PL!HS-bp2-026:1",
            steps_ja,
            steps_zh,
            expected_ja,
            expected_zh,
            visual_list,
            exc,
        )


def _verify_pl_hs_bp6_006_cost_reduction(
    visuals: dict[str, CardVisual],
) -> ScenarioResult:
    effect = _hime_cost_reduction_effect()
    steps_ja = [
        "Stage に『みらくらぱーく！』メンバーを 3 人置く。",
        "手札の `PL!HS-bp6-006` の登場候補を確認する。",
        "印刷 cost 20 が 3 人 × 2 で 14 になるか確認する。",
        "14 枚の Active Energy を支払って登場する。",
    ]
    steps_zh = [
        "Stage 上放 3 名『みらくらぱーく！』Member。",
        "确认手牌中 `PL!HS-bp6-006` 的登场候选。",
        "确认印刷 cost 20 因 3 人 × 2 降为 14。",
        "支付 14 张 Active Energy 登场。",
    ]
    expected_ja = [
        "登場候補の printed cost は 20。",
        "登場候補の effective cost は 14。",
        "14 枚の Energy が Wait になり、`PL!HS-bp6-006` が Stage に出る。",
    ]
    expected_zh = [
        "登场候选中的印刷 cost 为 20。",
        "登场候选中的实际 cost 为 14。",
        "14 张 Energy 变为 Wait，`PL!HS-bp6-006` 登场。",
    ]
    visual_list = [visuals["hime_bp6"], visuals["megumi"], visuals["rurino"]]
    try:
        state = _hime_cost_state(effect)
        play_action = next(
            action for action in generate_legal_actions(state)
            if action.action_type == "play_member"
        )
        placement = next(
            item for item in play_action.options["placements"]
            if item["card_instance_id"] == "hime-hand"
            and item["slot"] == "center"
            and not item["use_baton_touch"]
        )
        state = _apply(
            state,
            "play_member",
            player_id="player_1",
            payload={
                "card_instance_id": "hime-hand",
                "slot": "center",
                "use_baton_touch": False,
                "energy_instance_ids": [f"energy-{index}" for index in range(14)],
            },
        )
        waited_energy = sum(
            state.cards[f"energy-{index}"].orientation == "wait"
            for index in range(14)
        )
        checks = {
            "printed_cost_is_20": placement["printed_member_cost"] == 20,
            "effective_cost_is_14": placement["new_member_cost"] == 14,
            "payment_cost_is_14": placement["payment_cost"] == 14,
            "hime_entered_stage": state.players["player_1"].member_area["center"] == "hime-hand",
            "fourteen_energy_wait": waited_energy == 14,
        }
        return _scenario_result(
            scenario_id="pl_hs_bp6_006_cost_reduction",
            title_ja="PL!HS-bp6-006: みらくらぱーく！人数による登場 cost 軽減",
            title_zh="PL!HS-bp6-006：按みらくらぱーく！人数降低登场 cost",
            status="PASS" if all(checks.values()) else "FAIL",
            effect_id="PL!HS-bp6-006:1",
            steps_ja=steps_ja,
            steps_zh=steps_zh,
            expected_ja=expected_ja,
            expected_zh=expected_zh,
            actual_ja=_format_checks(checks, "ja")
            + ["実行後: effective cost 14 として登場。"],
            actual_zh=_format_checks(checks, "zh")
            + ["执行后：按实际 cost 14 登场。"],
            visuals=visual_list,
        )
    except Exception as exc:  # pragma: no cover
        return _exception_result(
            "pl_hs_bp6_006_cost_reduction",
            "PL!HS-bp6-006: みらくらぱーく！人数による登場 cost 軽減",
            "PL!HS-bp6-006：按みらくらぱーく！人数降低登场 cost",
            "PL!HS-bp6-006:1",
            steps_ja,
            steps_zh,
            expected_ja,
            expected_zh,
            visual_list,
            exc,
        )


def _verify_pl_hs_bp6_006_live_success_skip_ready(
    visuals: dict[str, CardVisual],
) -> ScenarioResult:
    effect = _hime_live_success_effect()
    steps_ja = [
        "`PL!HS-bp6-006` が Stage にいて Live 成功済みとして扱う。",
        "Live 成功時 effect を queue して自動解決する。",
        "次の Active Phase に進め、Active に戻らないことを確認する。",
    ]
    steps_zh = [
        "让 `PL!HS-bp6-006` 在 Stage 上，并视为 Live 成功。",
        "排入并自动结算 Live 成功时效果。",
        "进入下一次 Active Phase，确认不会变回 Active。",
    ]
    expected_ja = [
        "`PL!HS-bp6-006` は Wait になる。",
        "次の Active Phase では Active に戻らない。",
        "skip flag は消費される。",
    ]
    expected_zh = [
        "`PL!HS-bp6-006` 变为 Wait。",
        "下一次 Active Phase 不会变回 Active。",
        "skip flag 被消费。",
    ]
    visual_list = [visuals["hime_bp6"]]
    try:
        state = _hime_live_success_state(effect)
        events: list[GameEvent] = []
        _queue_live_success_effects(state, events)
        _resolve_automatic_effects(state, events)
        waited_after_success = state.cards["hime-stage"].orientation == "wait"
        flag_created = any(
            modifier.modifier_type == "flag"
            and modifier.flag == "skip_next_active_phase_ready"
            for modifier in state.players["player_1"].manual_modifiers
        )
        state.phase = "first_active"
        ready_result = apply_action(
            state,
            ActionRequest(
                action_type="advance_phase",
                expected_revision=state.revision,
                player_id="player_1",
                payload={},
            ),
        )
        result_state = ready_result.state
        skipped_event = next(
            event for event in ready_result.events if event.event_type == "cards_readied"
        )
        checks = {
            "source_wait_after_live_success": waited_after_success,
            "skip_ready_flag_created": flag_created,
            "source_still_wait_after_active_phase": result_state.cards["hime-stage"].orientation == "wait",
            "skip_ready_flag_consumed": not result_state.players["player_1"].manual_modifiers,
            "ready_event_lists_skipped_source": skipped_event.data.get("skipped_instance_ids") == ["hime-stage"],
        }
        return _scenario_result(
            scenario_id="pl_hs_bp6_006_live_success_skip_ready",
            title_ja="PL!HS-bp6-006: Live 成功時 Wait と次 Active Phase の復帰禁止",
            title_zh="PL!HS-bp6-006：Live 成功时 Wait，下一次 Active Phase 不复原",
            status="PASS" if all(checks.values()) else "FAIL",
            effect_id="PL!HS-bp6-006:3",
            steps_ja=steps_ja,
            steps_zh=steps_zh,
            expected_ja=expected_ja,
            expected_zh=expected_zh,
            actual_ja=_format_checks(checks, "ja"),
            actual_zh=_format_checks(checks, "zh"),
            visuals=visual_list,
        )
    except Exception as exc:  # pragma: no cover
        return _exception_result(
            "pl_hs_bp6_006_live_success_skip_ready",
            "PL!HS-bp6-006: Live 成功時 Wait と次 Active Phase の復帰禁止",
            "PL!HS-bp6-006：Live 成功时 Wait，下一次 Active Phase 不复原",
            "PL!HS-bp6-006:3",
            steps_ja,
            steps_zh,
            expected_ja,
            expected_zh,
            visual_list,
            exc,
        )


def _verify_baton_repeat_prevention(
    visuals: dict[str, CardVisual],
) -> ScenarioResult:
    steps_ja = [
        "Member A から Member B へ Baton Touch する。",
        "Manual position change で Member B を別エリアへ移動する。",
        "同じターン中に Member B からさらに Baton Touch できないことを確認する。",
    ]
    steps_zh = [
        "从 Member A Baton Touch 到 Member B。",
        "用手动 position change 把 Member B 移到其他区域。",
        "确认同一回合内不能再从 Member B 继续 Baton Touch。",
    ]
    expected_ja = [
        "Baton Touch で登場した Member の instance ID が turn history に残る。",
        "移動後もその Member を再度 Baton Touch 元にする候補は出ない。",
        "強行 payload を送っても IllegalActionError になる。",
    ]
    expected_zh = [
        "通过 Baton Touch 登场的 Member instance ID 会留在本回合历史中。",
        "移动后也不会出现以该 Member 为来源的二次 Baton Touch 候选。",
        "即使强行提交 payload，也会被 IllegalActionError 拒绝。",
    ]
    visual_list = [visuals["hime_bp6"]]
    try:
        state = _baton_repeat_state()
        state = _apply(
            state,
            "play_member",
            player_id="player_1",
            payload={
                "card_instance_id": "first-baton",
                "slot": "center",
                "use_baton_touch": True,
                "energy_instance_ids": ["energy-0"],
            },
        )
        state = _apply(
            state,
            "manual_adjustment",
            player_id="player_1",
            payload={
                "reason": "verification position change",
                "adjustments": [
                    {
                        "adjustment_type": "position_change",
                        "target_player_id": "player_1",
                        "from_slot": "center",
                        "to_slot": "left",
                    }
                ],
            },
        )
        placements = next(
            (
                action.options["placements"]
                for action in generate_legal_actions(state)
                if action.action_type == "play_member"
            ),
            [],
        )
        illegal_rejected = False
        try:
            _apply(
                state,
                "play_member",
                player_id="player_1",
                payload={
                    "card_instance_id": "second-baton",
                    "slot": "left",
                    "use_baton_touch": True,
                    "energy_instance_ids": ["energy-1"],
                },
            )
        except IllegalActionError:
            illegal_rejected = True
        checks = {
            "baton_entered_instance_tracked": state.players["player_1"].member_instance_ids_baton_entered_this_turn == ["first-baton"],
            "repeat_baton_not_in_legal_options": not any(
                item["slot"] == "left" and item["use_baton_touch"]
                for item in placements
            ),
            "forced_repeat_baton_rejected": illegal_rejected,
        }
        return _scenario_result(
            scenario_id="baton_repeat_prevention",
            title_ja="Baton Touch: 同一ターンの二重 Baton 防止",
            title_zh="Baton Touch：防止同一回合二次 Baton",
            status="PASS" if all(checks.values()) else "FAIL",
            effect_id="core-rule:baton-repeat",
            steps_ja=steps_ja,
            steps_zh=steps_zh,
            expected_ja=expected_ja,
            expected_zh=expected_zh,
            actual_ja=_format_checks(checks, "ja"),
            actual_zh=_format_checks(checks, "zh"),
            visuals=visual_list,
        )
    except Exception as exc:  # pragma: no cover
        return _exception_result(
            "baton_repeat_prevention",
            "Baton Touch: 同一ターンの二重 Baton 防止",
            "Baton Touch：防止同一回合二次 Baton",
            "core-rule:baton-repeat",
            steps_ja,
            steps_zh,
            expected_ja,
            expected_zh,
            visual_list,
            exc,
        )


def _verify_pl_hs_sd1_005_same_name_baton_blocked(
    visuals: dict[str, CardVisual],
) -> ScenarioResult:
    effect = _kosuzu_baton_return_live_effect()
    steps_ja = [
        "`PL!HS-sd1-005` が Baton Touch で登場したとみなす。",
        "入れ替え元が「徒町小鈴」ではない場合は控室の Live を回収できることを確認する。",
        "入れ替え元が「徒町 小鈴」の場合は、名前の空白差があっても effect が失効することを確認する。",
    ]
    steps_zh = [
        "把 `PL!HS-sd1-005` 视为通过 Baton Touch 登场。",
        "确认替换来源不是「徒町小鈴」时可以从控室回收 Live。",
        "确认替换来源为「徒町 小鈴」时，即使名字空格不同，效果也会失效。",
    ]
    expected_ja = [
        "非「徒町小鈴」からの Baton では Live 回収が成功する。",
        "「徒町 小鈴」からの Baton では `replacement_member_name_forbidden` で解決できない。",
    ]
    expected_zh = [
        "从非「徒町小鈴」来源 Baton 时，Live 回收成功。",
        "从「徒町 小鈴」来源 Baton 时，以 `replacement_member_name_forbidden` 阻止结算。",
    ]
    visual_list = [visuals["kosuzu_sd1"]]
    try:
        allowed = _kosuzu_baton_state(effect, replacement_name="村野さやか")
        allowed = _apply(
            allowed,
            "resolve_effect",
            player_id="player_1",
            payload={
                "invocation_id": "inv-1",
                "selected_card_instance_ids": ["waiting-live"],
            },
        )
        forbidden = _kosuzu_baton_state(effect, replacement_name="徒町 小鈴")
        forbidden_rejected = False
        try:
            _apply(
                forbidden,
                "resolve_effect",
                player_id="player_1",
                payload={
                    "invocation_id": "inv-1",
                    "selected_card_instance_ids": ["waiting-live"],
                },
            )
        except IllegalActionError as exc:
            forbidden_rejected = "replacement_member_name_forbidden" in str(exc)
        checks = {
            "allowed_baton_returns_live": "waiting-live" in allowed.players["player_1"].hand,
            "same_name_baton_rejected": forbidden_rejected,
        }
        return _scenario_result(
            scenario_id="pl_hs_sd1_005_same_name_baton_blocked",
            title_ja="PL!HS-sd1-005: 徒町小鈴からの Baton では登場時回収しない",
            title_zh="PL!HS-sd1-005：从徒町小鈴 Baton 时不触发登场回收",
            status="PASS" if all(checks.values()) else "FAIL",
            effect_id="PL!HS-sd1-005:1",
            steps_ja=steps_ja,
            steps_zh=steps_zh,
            expected_ja=expected_ja,
            expected_zh=expected_zh,
            actual_ja=_format_checks(checks, "ja"),
            actual_zh=_format_checks(checks, "zh"),
            visuals=visual_list,
        )
    except Exception as exc:  # pragma: no cover
        return _exception_result(
            "pl_hs_sd1_005_same_name_baton_blocked",
            "PL!HS-sd1-005: 徒町小鈴からの Baton では登場時回収しない",
            "PL!HS-sd1-005：从徒町小鈴 Baton 时不触发登场回收",
            "PL!HS-sd1-005:1",
            steps_ja,
            steps_zh,
            expected_ja,
            expected_zh,
            visual_list,
            exc,
        )


def _pl_hs_bp6_014_state(
    effect: EffectDefinition,
    *,
    include_named_target: bool,
) -> MatchState:
    source = CardDefinition(
        card_code="PL!HS-bp6-014",
        card_id="PL!HS-bp6-014",
        name_ja="安養寺 姫芽",
        card_type="member",
        effect_ids=[effect.effect_id],
    )
    draw_card = CardDefinition(
        card_code="TEST-DRAW",
        card_id="TEST-DRAW",
        name_ja="ドローカード",
        card_type="member",
    )
    other_member = CardDefinition(
        card_code="TEST-OTHER",
        card_id="TEST-OTHER",
        name_ja="乙宗 梢",
        card_type="member",
        blade=1,
        basic_hearts={"heart01": 1},
    )
    cards = {
        "hand-source": CardInstance(
            instance_id="hand-source",
            owner_id="player_1",
            card=source,
        ),
        "draw-card": CardInstance(
            instance_id="draw-card",
            owner_id="player_1",
            card=draw_card,
            face_up=False,
        ),
        "other-member": CardInstance(
            instance_id="other-member",
            owner_id="player_1",
            card=other_member,
        ),
    }
    member_area = {"left": None, "center": "other-member", "right": None}
    if include_named_target:
        megumi = other_member.model_copy(
            update={
                "card_code": "TEST-MEGUMI",
                "card_id": "TEST-MEGUMI",
                "name_ja": "藤島 慈",
            }
        )
        cards["megumi"] = CardInstance(
            instance_id="megumi",
            owner_id="player_1",
            card=megumi,
        )
        member_area["left"] = "megumi"
    return MatchState(
        match_id="effect-verification",
        seed=1,
        phase="first_main",
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="Player 1",
                main_deck=["draw-card"],
                hand=["hand-source"],
                member_area=member_area,
            ),
            "player_2": PlayerState(player_id="player_2", name="Player 2"),
        },
        cards=cards,
        effect_definitions={effect.effect_id: effect},
    )


def _minimal_pending_effect_state(effect: EffectDefinition) -> MatchState:
    member = CardDefinition(
        card_code="VERIFY-MEMBER",
        card_id="VERIFY-MEMBER",
        name_ja="検証メンバー",
        card_type="member",
        blade=1,
        basic_hearts={"heart01": 1},
    )
    live = CardDefinition(
        card_code="VERIFY-LIVE",
        card_id="VERIFY-LIVE",
        name_ja="検証ライブ",
        card_type="live",
        score=1,
    )
    return MatchState(
        match_id="effect-verification",
        seed=1,
        phase="first_main",
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="Player 1",
                live_area=["source-live"],
            ),
            "player_2": PlayerState(player_id="player_2", name="Player 2"),
        },
        cards={
            "source-live": CardInstance(
                instance_id="source-live",
                owner_id="player_1",
                card=live,
            ),
            "member": CardInstance(
                instance_id="member",
                owner_id="player_1",
                card=member,
            ),
        },
        effect_definitions={effect.effect_id: effect},
        pending_effects=[
            EffectInvocation(
                invocation_id="inv-1",
                effect_id=effect.effect_id,
                source_card_instance_id="source-live",
                player_id="player_1",
                trigger_event=effect.trigger,
            )
        ],
    )


def _hime_cost_reduction_effect() -> EffectDefinition:
    return EffectDefinition(
        effect_id="verify-hime-cost:1",
        card_code="PL!HS-bp6-006",
        text_revision_id=43,
        raw_text_hash="a" * 64,
        effect_index=1,
        label_ja=(
            "【常時】手札にあるこのメンバーカードのコストは、"
            "自分のステージにいる『みらくらぱーく！』のメンバー1人につき、"
            "2少なくなる。"
        ),
        effect_type="static",
        trigger="static_always",
        timing="static_always",
        execution_mode="auto_resolve",
        frequency_limit="none",
        is_optional=False,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="verification scenario",
        actions=[
            {
                "action_type": "reduce_play_cost",
                "amount_source": "own_stage_member_unit_count",
                "multiplier": 2,
                "value": {"unit_key": "miracra_park"},
            }
        ],
    )


def _hime_cost_state(effect: EffectDefinition) -> MatchState:
    hime = CardDefinition(
        card_code="PL!HS-bp6-006",
        card_id="PL!HS-bp6-006",
        name_ja="安養寺姫芽",
        card_type="member",
        cost=20,
        unit_keys=["miracra_park"],
        effect_ids=[effect.effect_id],
    )
    miracra = CardDefinition(
        card_code="VERIFY-MIRACRA",
        card_id="VERIFY-MIRACRA",
        name_ja="みらくらぱーく！検証メンバー",
        card_type="member",
        cost=2,
        unit_keys=["miracra_park"],
    )
    energy = CardDefinition(
        card_code="VERIFY-ENERGY",
        card_id="VERIFY-ENERGY",
        name_ja="エネルギー",
        card_type="energy",
    )
    cards: dict[str, CardInstance] = {
        "hime-hand": CardInstance(
            instance_id="hime-hand",
            owner_id="player_1",
            card=hime,
        )
    }
    for slot in ("left", "center", "right"):
        cards[f"stage-{slot}"] = CardInstance(
            instance_id=f"stage-{slot}",
            owner_id="player_1",
            card=miracra.model_copy(
                update={
                    "card_code": f"VERIFY-MIRACRA-{slot}",
                    "card_id": f"VERIFY-MIRACRA-{slot}",
                }
            ),
        )
    for index in range(14):
        cards[f"energy-{index}"] = CardInstance(
            instance_id=f"energy-{index}",
            owner_id="player_1",
            card=energy,
            orientation="active",
        )
    return MatchState(
        match_id="hime-cost",
        seed=1,
        phase="first_main",
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="Player 1",
                hand=["hime-hand"],
                member_area={
                    "left": "stage-left",
                    "center": "stage-center",
                    "right": "stage-right",
                },
                energy_area=[f"energy-{index}" for index in range(14)],
            ),
            "player_2": PlayerState(player_id="player_2", name="Player 2"),
        },
        cards=cards,
        effect_definitions={effect.effect_id: effect},
    )


def _hime_live_success_effect() -> EffectDefinition:
    return EffectDefinition(
        effect_id="verify-hime-live-success:3",
        card_code="PL!HS-bp6-006",
        text_revision_id=43,
        raw_text_hash="a" * 64,
        effect_index=3,
        label_ja="【ライブ成功時】このメンバーをウェイトにし、次のターンのアクティブフェイズにアクティブしない。",
        effect_type="triggered",
        trigger="live_succeeded",
        timing="live_success",
        execution_mode="auto_resolve",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        is_optional=False,
        source_reference="verification scenario",
        duration="game",
        frequency_limit="once_per_live",
        actions=[
            {"action_type": "apply_wait_member", "target": "source"},
            {
                "action_type": "set_flag",
                "target": "source",
                "flag": "skip_next_active_phase_ready",
                "value": {"reason": "PL!HS-bp6-006 live success"},
            },
        ],
    )


def _hime_live_success_state(effect: EffectDefinition) -> MatchState:
    hime = CardDefinition(
        card_code="PL!HS-bp6-006",
        card_id="PL!HS-bp6-006",
        name_ja="安養寺姫芽",
        card_type="member",
        effect_ids=[effect.effect_id],
    )
    live = CardDefinition(
        card_code="VERIFY-LIVE",
        card_id="VERIFY-LIVE",
        name_ja="成功ライブ",
        card_type="live",
        score=1,
    )
    return MatchState(
        match_id="hime-live-success",
        seed=1,
        phase="live_judgment",
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="Player 1",
                member_area={"left": None, "center": "hime-stage", "right": None},
                success_live_area=["successful-live"],
            ),
            "player_2": PlayerState(player_id="player_2", name="Player 2"),
        },
        cards={
            "hime-stage": CardInstance(
                instance_id="hime-stage",
                owner_id="player_1",
                card=hime,
                orientation="active",
            ),
            "successful-live": CardInstance(
                instance_id="successful-live",
                owner_id="player_1",
                card=live,
            ),
        },
        effect_definitions={effect.effect_id: effect},
        success_live_moved_instance_ids={"player_1": ["successful-live"]},
    )


def _baton_repeat_state() -> MatchState:
    member = CardDefinition(
        card_code="VERIFY-MEMBER",
        card_id="VERIFY-MEMBER",
        name_ja="元メンバー",
        card_type="member",
        cost=1,
    )
    first_baton = CardDefinition(
        card_code="VERIFY-FIRST-BATON",
        card_id="VERIFY-FIRST-BATON",
        name_ja="一度目バトン",
        card_type="member",
        cost=2,
    )
    second_baton = CardDefinition(
        card_code="VERIFY-SECOND-BATON",
        card_id="VERIFY-SECOND-BATON",
        name_ja="二度目バトン",
        card_type="member",
        cost=3,
    )
    energy = CardDefinition(
        card_code="VERIFY-ENERGY",
        card_id="VERIFY-ENERGY",
        name_ja="エネルギー",
        card_type="energy",
    )
    cards = {
        "old-member": CardInstance(
            instance_id="old-member",
            owner_id="player_1",
            card=member,
        ),
        "first-baton": CardInstance(
            instance_id="first-baton",
            owner_id="player_1",
            card=first_baton,
        ),
        "second-baton": CardInstance(
            instance_id="second-baton",
            owner_id="player_1",
            card=second_baton,
        ),
    }
    for index in range(3):
        cards[f"energy-{index}"] = CardInstance(
            instance_id=f"energy-{index}",
            owner_id="player_1",
            card=energy,
            orientation="active",
        )
    return MatchState(
        match_id="baton-repeat",
        seed=1,
        phase="first_main",
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="Player 1",
                hand=["first-baton", "second-baton"],
                member_area={"left": None, "center": "old-member", "right": None},
                energy_area=["energy-0", "energy-1", "energy-2"],
            ),
            "player_2": PlayerState(player_id="player_2", name="Player 2"),
        },
        cards=cards,
    )


def _kosuzu_baton_return_live_effect() -> EffectDefinition:
    return EffectDefinition(
        effect_id="verify-kosuzu-baton:1",
        card_code="PL!HS-sd1-005",
        text_revision_id=1,
        raw_text_hash="b" * 64,
        effect_index=1,
        label_ja=(
            "【登場】「徒町小鈴」以外の『蓮ノ空』のメンバーから"
            "バトンタッチして登場した場合、自分の控え室からライブカードを1枚手札に加える。"
        ),
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        execution_mode="prompt_then_resolve",
        frequency_limit="none",
        is_optional=False,
        condition={
            "requires_baton_touch": True,
            "replacement_member_work_key": "hasunosora",
            "replacement_member_name_ja_not": "徒町小鈴",
        },
        cost=[],
        choice={
            "choice_type": "card_from_zone",
            "zone": "waiting_room",
            "card_type": "live",
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "return_from_waiting_room"}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="verification scenario",
    )


def _kosuzu_baton_state(
    effect: EffectDefinition,
    *,
    replacement_name: str,
) -> MatchState:
    kosuzu = CardDefinition(
        card_code="PL!HS-sd1-005",
        card_id="PL!HS-sd1-005",
        name_ja="徒町 小鈴",
        card_type="member",
        effect_ids=[effect.effect_id],
        work_keys=["hasunosora"],
    )
    replacement = CardDefinition(
        card_code="VERIFY-REPLACED",
        card_id="VERIFY-REPLACED",
        name_ja=replacement_name,
        card_type="member",
        work_keys=["hasunosora"],
    )
    live = CardDefinition(
        card_code="VERIFY-LIVE",
        card_id="VERIFY-LIVE",
        name_ja="回収対象ライブ",
        card_type="live",
    )
    return MatchState(
        match_id="kosuzu-baton",
        seed=1,
        phase="first_main",
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="Player 1",
                waiting_room=["replaced-member", "waiting-live"],
            ),
            "player_2": PlayerState(player_id="player_2", name="Player 2"),
        },
        cards={
            "kosuzu-source": CardInstance(
                instance_id="kosuzu-source",
                owner_id="player_1",
                card=kosuzu,
            ),
            "replaced-member": CardInstance(
                instance_id="replaced-member",
                owner_id="player_1",
                card=replacement,
            ),
            "waiting-live": CardInstance(
                instance_id="waiting-live",
                owner_id="player_1",
                card=live,
            ),
        },
        effect_definitions={effect.effect_id: effect},
        pending_effects=[
            EffectInvocation(
                invocation_id="inv-1",
                effect_id=effect.effect_id,
                source_card_instance_id="kosuzu-source",
                player_id="player_1",
                trigger_event=effect.trigger,
                trigger_data={
                    "used_baton_touch": True,
                    "replacement_card_instance_id": "replaced-member",
                },
            )
        ],
    )


def _activate_pl_hs_bp6_014(state: MatchState) -> MatchState:
    return _apply(
        state,
        "activate_effect",
        player_id="player_1",
        payload={
            "effect_id": "PL!HS-bp6-014:1",
            "source_card_instance_id": "hand-source",
        },
    )


def _apply(
    state: MatchState,
    action_type: str,
    *,
    player_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> MatchState:
    return apply_action(
        state,
        ActionRequest(
            action_type=action_type,
            expected_revision=state.revision,
            player_id=player_id,
            payload=payload or {},
        ),
    ).state


def _load_report_visuals(database_path: Path) -> dict[str, CardVisual]:
    fallback = {
        "source": _fallback_visual("起動元", "发动源", "PL!HS-bp6-014", "安養寺 姫芽"),
        "megumi": _fallback_visual("Blade 対象", "Blade 目标", "TEST-MEGUMI", "藤島 慈"),
        "rurino": _fallback_visual("Blade 対象", "Blade 目标", "TEST-RURINO", "大沢瑠璃乃"),
        "hime_bp6": _fallback_visual("検証対象", "验证对象", "PL!HS-bp6-006", "安養寺 姫芽"),
        "miracreation": _fallback_visual("検証対象", "验证对象", "PL!HS-bp2-026", "みらくりえーしょん"),
        "kosuzu_sd1": _fallback_visual("検証対象", "验证对象", "PL!HS-sd1-005", "徒町 小鈴"),
    }
    if not database_path.exists():
        return fallback
    try:
        with sqlite3.connect(database_path) as connection:
            connection.row_factory = sqlite3.Row
            source = _visual_by_card_code(
                connection,
                "PL!HS-bp6-014",
                role_ja="起動元",
                role_zh="发动源",
            )
            megumi = _visual_by_name(
                connection,
                "藤島 慈",
                role_ja="Blade 対象",
                role_zh="Blade 目标",
            )
            rurino = _visual_by_name(
                connection,
                "大沢瑠璃乃",
                role_ja="Blade 対象",
                role_zh="Blade 目标",
            )
            hime_bp6 = _visual_by_card_code(
                connection,
                "PL!HS-bp6-006",
                role_ja="検証対象",
                role_zh="验证对象",
            )
            miracreation = _visual_by_card_code(
                connection,
                "PL!HS-bp2-026",
                role_ja="検証対象",
                role_zh="验证对象",
            )
            kosuzu_sd1 = _visual_by_card_code(
                connection,
                "PL!HS-sd1-005",
                role_ja="検証対象",
                role_zh="验证对象",
            )
    except sqlite3.Error:
        return fallback
    return {
        "source": source or fallback["source"],
        "megumi": megumi or fallback["megumi"],
        "rurino": rurino or fallback["rurino"],
        "hime_bp6": hime_bp6 or fallback["hime_bp6"],
        "miracreation": miracreation or fallback["miracreation"],
        "kosuzu_sd1": kosuzu_sd1 or fallback["kosuzu_sd1"],
    }


def _visual_by_card_code(
    connection: sqlite3.Connection,
    card_code: str,
    *,
    role_ja: str,
    role_zh: str,
) -> CardVisual | None:
    row = connection.execute(
        """
        SELECT gc.card_code, gc.canonical_name_ja AS name_ja,
               cp.card_id, cp.image_url
          FROM gameplay_cards AS gc
          JOIN card_printings AS cp ON cp.gameplay_card_id = gc.id
         WHERE gc.card_code = ?
         ORDER BY cp.card_id
         LIMIT 1
        """,
        (card_code,),
    ).fetchone()
    if row is None:
        return None
    return CardVisual(
        role_ja=role_ja,
        role_zh=role_zh,
        card_code=str(row["card_code"]),
        name_ja=str(row["name_ja"]),
        card_id=str(row["card_id"]) if row["card_id"] is not None else None,
        image_url=str(row["image_url"]) if row["image_url"] is not None else None,
    )


def _visual_by_name(
    connection: sqlite3.Connection,
    name_ja: str,
    *,
    role_ja: str,
    role_zh: str,
) -> CardVisual | None:
    row = connection.execute(
        """
        SELECT gc.card_code, gc.canonical_name_ja AS name_ja,
               cp.card_id, cp.image_url
          FROM gameplay_cards AS gc
          JOIN card_printings AS cp ON cp.gameplay_card_id = gc.id
         WHERE replace(gc.canonical_name_ja, ' ', '') = replace(?, ' ', '')
         ORDER BY gc.card_code, cp.card_id
         LIMIT 1
        """,
        (name_ja,),
    ).fetchone()
    if row is None:
        return None
    return CardVisual(
        role_ja=role_ja,
        role_zh=role_zh,
        card_code=str(row["card_code"]),
        name_ja=str(row["name_ja"]),
        card_id=str(row["card_id"]) if row["card_id"] is not None else None,
        image_url=str(row["image_url"]) if row["image_url"] is not None else None,
    )


def _fallback_visual(
    role_ja: str,
    role_zh: str,
    card_code: str,
    name_ja: str,
) -> CardVisual:
    return CardVisual(
        role_ja=role_ja,
        role_zh=role_zh,
        card_code=card_code,
        name_ja=name_ja,
    )


def _exception_result(
    scenario_id: str,
    title_ja: str,
    title_zh: str,
    effect_id: str,
    steps_ja: list[str],
    steps_zh: list[str],
    expected_ja: list[str],
    expected_zh: list[str],
    visuals: list[CardVisual],
    exc: Exception,
) -> ScenarioResult:
    actual_ja = [f"例外発生: `{type(exc).__name__}: {exc}`"]
    actual_zh = [f"发生异常：`{type(exc).__name__}: {exc}`"]
    return ScenarioResult(
        scenario_id=scenario_id,
        title_ja=title_ja,
        title_zh=title_zh,
        status="FAIL",
        effect_id=effect_id,
        steps_ja=steps_ja,
        steps_zh=steps_zh,
        expected_ja=expected_ja,
        expected_zh=expected_zh,
        actual_ja=actual_ja,
        actual_zh=actual_zh,
        visuals=visuals,
    )


def _scenario_result(
    *,
    scenario_id: str,
    title_ja: str,
    title_zh: str,
    status: str,
    effect_id: str,
    steps_ja: list[str],
    steps_zh: list[str],
    expected_ja: list[str],
    expected_zh: list[str],
    actual_ja: list[str],
    actual_zh: list[str],
    visuals: list[CardVisual],
) -> ScenarioResult:
    return ScenarioResult(
        scenario_id=scenario_id,
        title_ja=title_ja,
        title_zh=title_zh,
        status=status,
        effect_id=effect_id,
        steps_ja=steps_ja,
        steps_zh=steps_zh,
        expected_ja=expected_ja,
        expected_zh=expected_zh,
        actual_ja=actual_ja,
        actual_zh=actual_zh,
        visuals=visuals,
    )


_CHECK_LABELS: dict[str, tuple[str, str]] = {
    "source_in_waiting_room": ("起動元が控室にある", "发动源在控室"),
    "source_removed_from_hand": ("起動元が手札から消えている", "发动源已从手牌移除"),
    "drawn_card_in_hand": ("抽牌したカードが手札にある", "抽到的牌在手牌"),
    "blade_modifier": ("対象に Blade +1 modifier がある", "目标有 Blade +1 modifier"),
    "pending_effects_cleared": ("pending effect が残っていない", "没有残留 pending effect"),
    "activation_available_without_target": ("対象なしでも起動候補が出る", "无目标时仍出现发动候选"),
    "choice_minimum_is_zero": ("選択下限が 0", "选择下限为 0"),
    "no_candidate_targets": ("合法対象候補が 0 件", "合法目标候选为 0 件"),
    "no_blade_modifier": ("Blade modifier が作られていない", "没有生成 Blade modifier"),
    "score_modifier_created": ("score +2 modifier が作られている", "生成了 score +2 modifier"),
    "printed_cost_is_20": ("印刷 cost が 20", "印刷 cost 为 20"),
    "effective_cost_is_14": ("実効 cost が 14", "实际 cost 为 14"),
    "payment_cost_is_14": ("支払い cost が 14", "支付 cost 为 14"),
    "hime_entered_stage": ("安養寺姫芽が Stage に登場", "安養寺姫芽登场到 Stage"),
    "fourteen_energy_wait": ("14 枚の Energy が Wait", "14 张 Energy 变为 Wait"),
    "source_wait_after_live_success": ("Live 成功後に対象 Member が Wait", "Live 成功后目标 Member 变为 Wait"),
    "skip_ready_flag_created": ("次 Active Phase 復帰禁止 flag が作られた", "生成了下一次 Active Phase 不复原 flag"),
    "source_still_wait_after_active_phase": ("Active Phase 後も Wait のまま", "Active Phase 后仍保持 Wait"),
    "skip_ready_flag_consumed": ("復帰禁止 flag が消費された", "不复原 flag 已被消费"),
    "ready_event_lists_skipped_source": ("ready event に skipped 対象が記録された", "ready event 记录了 skipped 对象"),
    "baton_entered_instance_tracked": ("Baton 登場 instance が履歴に残る", "Baton 登场 instance 被记录在历史中"),
    "repeat_baton_not_in_legal_options": ("二重 Baton 候補が legal actions に出ない", "二次 Baton 不出现在 legal actions 中"),
    "forced_repeat_baton_rejected": ("強制送信した二重 Baton が拒否される", "强行提交二次 Baton 被拒绝"),
    "allowed_baton_returns_live": ("許可される Baton では Live 回収が成功", "允许的 Baton 可以成功回收 Live"),
    "same_name_baton_rejected": ("徒町小鈴からの Baton は拒否される", "从徒町小鈴 Baton 会被拒绝"),
}


def _format_checks(checks: dict[str, bool], language: ReportLanguage) -> list[str]:
    index = 0 if language == "ja" else 1
    return [
        f"{_CHECK_LABELS.get(name, (name, name))[index]}: {'OK' if passed else 'NG'}"
        for name, passed in checks.items()
    ]


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


if __name__ == "__main__":
    raise SystemExit(main())
