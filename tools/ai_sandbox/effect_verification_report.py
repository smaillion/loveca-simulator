"""Human-readable effect scenario verification reports.

This tool is deterministic and local. It does not play a whole match; it runs
small effect-focused scenarios and writes Japanese / Chinese Markdown reports
with official card images when the local card DB is available.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
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
    _effective_member_play_cost,
    _queue_live_success_effects,
    _resolve_automatic_effects,
    _static_heart_bonus,
    _static_numeric_bonus,
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


@dataclass(frozen=True)
class RegistryContractScenario:
    effect_id: str
    family_ja: str
    family_zh: str
    trigger: str
    choice_type: str | None
    action_types: tuple[str, ...]


_PHASE5_V1_CONTRACTS = (
    RegistryContractScenario("PL!-bp5-014:1", "上から見る・選択", "查看牌堆顶并选择", "member_played", "inspect_top_select", ("inspect_top_cards", "select_to_hand_from_inspected", "move_remaining_cards")),
    RegistryContractScenario("PL!HS-sd1-002:1", "Live 開始時の上から見る", "Live 开始时查看牌堆顶", "live_started", "inspect_top_select", ("inspect_top_cards", "select_to_hand_from_inspected", "move_remaining_cards", "gain_heart", "gain_blade")),
    RegistryContractScenario("PL!S-bp2-005:1", "公開して手札へ", "公开后加入手牌", "member_played", "inspect_top_select", ("inspect_top_cards", "select_to_hand_from_inspected", "move_remaining_cards")),
    RegistryContractScenario("PL!S-bp6-005:1", "条件付き検索", "带条件检索", "member_played", "inspect_top_select", ("inspect_top_cards", "select_to_hand_from_inspected", "move_remaining_cards")),
    RegistryContractScenario("PL!SP-bp4-002:1", "必要 Heart 検索", "按所需 Heart 检索", "member_played", "inspect_top_select", ("inspect_top_cards", "select_to_hand_from_inspected", "move_remaining_cards")),
    RegistryContractScenario("PL!SP-sd1-009:1", "上から見る・残り控室", "查看牌堆顶并将其余送控室", "member_played", "inspect_top_select", ("inspect_top_cards", "select_to_hand_from_inspected", "move_remaining_cards")),
    RegistryContractScenario("PL!HS-bp2-009:1", "登場時 Heart", "登场时 Heart", "member_played", None, ("gain_heart",)),
    RegistryContractScenario("PL!HS-bp2-019:1", "分岐 required Heart", "分支式所需 Heart", "live_started", "choose_effect_branch", ("replace_required_hearts", "replace_required_hearts", "replace_required_hearts")),
    RegistryContractScenario("PL!HS-bp5-017:1", "Live score 補正", "Live 分数修正", "live_started", None, ("modify_score",)),
    RegistryContractScenario("PL!HS-sd1-008:2", "Member 対象 Heart", "选择 Member 获得 Heart", "live_started", "member_from_stage", ("gain_heart",)),
    RegistryContractScenario("PL!N-bp3-002:1", "選択 Member Heart", "选择 Member 的 Heart", "live_started", "member_from_stage", ("gain_heart",)),
    RegistryContractScenario("PL!N-bp4-010:2", "自動 Heart", "自动获得 Heart", "live_started", None, ("gain_heart",)),
    RegistryContractScenario("PL!N-pb1-039:1", "Stage 対象 Heart", "Stage 目标 Heart", "live_started", "member_from_stage", ("gain_heart",)),
    RegistryContractScenario("PL!S-bp5-005:1", "Heart 色選択", "选择 Heart 颜色", "live_started", "choose_color", ("gain_heart_to_stage_members",)),
    RegistryContractScenario("LL-bp5-002:2", "控室から回収", "从控室回收", "live_succeeded", "card_from_zone", ("return_from_waiting_room",)),
    RegistryContractScenario("PL!-pb1-006:1", "控室から山札上", "从控室放回牌堆顶", "member_played", "card_from_zone", ("move_selected_to_deck_top", "draw_card")),
    RegistryContractScenario("PL!HS-bp6-003:1", "条件付き Live 回収", "按条件回收 Live", "member_played", "card_from_zone", ("return_from_waiting_room",)),
    RegistryContractScenario("PL!HS-bp6-017:1", "複数グループ回収", "分组回收多张卡", "member_left_stage_to_waiting_room", "card_groups_from_zone", ("return_from_waiting_room",)),
    RegistryContractScenario("PL!HS-pb1-020:1", "Member と Live 回収", "分别回收 Member 与 Live", "member_played", "card_groups_from_zone", ("return_from_waiting_room",)),
    RegistryContractScenario("PL!N-bp1-008:1", "起動・低 cost 回収", "起动并回收低费用卡", "player_activation", "card_from_zone", ("return_from_waiting_room",)),
    RegistryContractScenario("PL!N-bp3-005:1", "手札 5 枚まで draw", "抽到 5 张手牌", "own_member_played", None, ("draw_until_hand_size",)),
    RegistryContractScenario("PL!N-bp4-011:2", "mill 後 Live 回収", "堆墓后回收 Live", "live_succeeded", "post_action_card_from_zone", ("mill_top_cards", "return_from_waiting_room")),
    RegistryContractScenario("PL!S-bp3-021:1", "Member 選択 Blade", "选择 Member 获得 Blade", "live_started", "member_from_stage", ("gain_blade",)),
    RegistryContractScenario("PL!S-bp5-003:1", "異なるグループ回収", "回收不同组合卡", "member_played", "card_from_zone", ("return_from_waiting_room",)),
    RegistryContractScenario("LL-bp2-001:2", "Baton 禁止", "禁止 Baton", "static_always", None, ("prevent_baton_replacement",)),
    RegistryContractScenario("PL!-bp4-020:1", "Position Change", "位置移动", "live_started", "member_from_stage", ("position_change_selected",)),
    RegistryContractScenario("PL!-pb1-017:1", "条件付き二段 discard", "条件式二段弃牌", "member_played", "post_action_card_from_zone", ("draw_card", "discard_from_hand")),
    RegistryContractScenario("PL!HS-bp5-003:1", "離場時 Position Change", "离场时位置移动", "member_left_stage_to_waiting_room", "member_from_stage", ("position_change_selected",)),
    RegistryContractScenario("PL!HS-pb1-001:1", "Energy 支払い・Active 化", "支付 Energy 并复原 Energy", "own_member_played", None, ("ready_energy",)),
    RegistryContractScenario("PL!HS-pb1-008:1", "両 Stage 一括 Wait", "双方 Stage 批量变 Wait", "member_played", None, ("apply_wait_to_stage_members",)),
    RegistryContractScenario("PL!HS-pb1-008:2", "相手 Active Phase 制限", "限制对手 Active Phase", "static_always", None, ("prevent_opponent_active_phase_ready",)),
    RegistryContractScenario("PL!N-bp4-023:1", "Member を Wait・draw discard", "Member 变 Wait 后抽弃", "member_played", "post_action_card_from_zone", ("draw_card", "discard_from_hand")),
    RegistryContractScenario("PL!N-bp5-005:1", "Baton 後 Energy・draw", "Baton 后复原 Energy 并抽牌", "member_left_stage_to_waiting_room", None, ("ready_energy", "draw_card")),
    RegistryContractScenario("PL!N-bp5-006:1", "自分の Active Phase 制限", "限制自身 Active Phase", "static_always", None, ("prevent_source_active_phase_ready",)),
    RegistryContractScenario("PL!N-pb1-001:1", "手札 cost・Live 回収", "弃手牌后回收 Live", "member_played", "card_from_zone", ("return_from_waiting_room",)),
    RegistryContractScenario("PL!S-bp5-001:1", "Baton 条件 draw", "满足 Baton 条件时抽牌", "member_played", None, ("draw_card",)),
    RegistryContractScenario("PL!S-bp6-001:1", "控室登場・相手 Wait", "从控室登场并令对手 Wait", "member_played", "member_from_stage", ("apply_wait_member",)),
    RegistryContractScenario("PL!S-sd1-006:1", "控室から登場", "从控室登场", "member_played", "deploy_member_from_waiting_room", ("deploy_selected_to_empty_stage",)),
    RegistryContractScenario("PL!SP-bp4-003:1", "Side 登場 draw discard", "侧区登场后抽弃", "member_played", "post_action_card_from_zone", ("draw_card", "discard_from_hand")),
)


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
    dynamic_results = [
        _verify_pl_hs_bp6_014_with_target(effect, visuals),
        _verify_pl_hs_bp6_014_without_target(effect, visuals),
        _verify_pl_hs_bp2_026_live_start_score_modifier(visuals),
        _verify_pl_hs_bp6_006_cost_reduction(visuals),
        _verify_pl_hs_bp6_006_live_success_skip_ready(visuals),
        _verify_baton_repeat_prevention(visuals),
        _verify_pl_hs_sd1_005_same_name_baton_blocked(visuals),
        *_v1_1_dynamic_scenarios(effects, database_path),
    ]
    return [
        *dynamic_results,
        *_registry_contract_scenarios(effects, database_path),
    ]


def _v1_1_dynamic_scenarios(
    effects: dict[str, EffectDefinition],
    database_path: Path,
) -> list[ScenarioResult]:
    cases = (
        (
            "v1_1_static_live_state",
            "静的 Heart・score・登場 cost を実状態から評価",
            "根据实际状态计算常时 Heart、分数与登场费用",
            "PL!N-pb1-008:1",
            _run_v1_1_static_live_state,
        ),
        (
            "v1_1_reveal_until_live",
            "Live が出るまで公開して手札へ",
            "公开到出现 Live 并加入手牌",
            "PL!N-bp1-011:1",
            _run_v1_1_reveal_until_live,
        ),
        (
            "v1_1_variable_discard_draw",
            "選んだ枚数 +1 を draw",
            "抽取所选弃牌数量加一",
            "PL!HS-pb1-003:1",
            _run_v1_1_variable_discard_draw,
        ),
        (
            "v1_1_waiting_live_to_bottom",
            "控室の Live をデッキ下へ",
            "将控室 Live 放到牌堆底",
            "PL!S-bp2-008:1",
            _run_v1_1_waiting_live_to_bottom,
        ),
        (
            "v1_1_attach_waiting_member",
            "控室 Member を自身の下へ置く",
            "将控室 Member 放到自身下方",
            "PL!N-PR-026:1",
            _run_v1_1_attach_waiting_member,
        ),
        (
            "v1_1_energy_score_per_four",
            "支払った Energy 4 枚ごとに score +1",
            "每支付 4 张 Energy 获得分数加一",
            "PL!SP-bp5-025:1",
            _run_v1_1_energy_score_per_four,
        ),
        (
            "v1_1_repeat_mill_blade",
            "繰り返し mill と Blade 加算",
            "重复堆墓并增加 Blade",
            "PL!SP-bp5-009:1",
            _run_v1_1_repeat_mill_blade,
        ),
        (
            "v1_1_post_mill_fourth",
            "mill 後に Live を上から 4 枚目へ",
            "堆墓后将 Live 放到牌堆顶第四张",
            "PL!N-bp5-021:1",
            _run_v1_1_post_mill_fourth,
        ),
        (
            "v1_1_reveal_hand_then_conceal",
            "手札公開 cost を score 化して再び非公開",
            "公开手牌作为成本并计分后重新隐藏",
            "PL!SP-bp1-003:1",
            _run_v1_1_reveal_hand_then_conceal,
        ),
        (
            "v1_1_member_comparison",
            "相手 Member との数値一致を評価",
            "比较对手 Member 数值并结算",
            "PL!N-bp3-011:1",
            _run_v1_1_member_comparison,
        ),
        (
            "v1_1_printemps_ready_score",
            "Printemps を Active にして score 加算",
            "复原 Printemps 并增加分数",
            "PL!-pb1-028:1",
            _run_v1_1_printemps_ready_score,
        ),
        (
            "v1_1_same_name_discard_target",
            "捨てた同名 Member だけを対象化",
            "仅选择与弃置卡同名的 Member",
            "PL!HS-bp2-007:2",
            _run_v1_1_same_name_discard_target,
        ),
        (
            "v1_1_inspect_retain_score",
            "上から見る・順番保持・score 加算",
            "查看牌堆顶、保留顺序并增加分数",
            "PL!N-bp3-028:1",
            _run_v1_1_inspect_retain_score,
        ),
        (
            "v1_1_position_change_unit_filter",
            "指定 unit の Area へ Position Change",
            "仅向指定组合所在区域进行位置移动",
            "PL!S-bp5-111:1",
            _run_v1_1_position_change_unit_filter,
        ),
    )
    visuals = _load_visuals_for_effect_ids(
        database_path,
        [effect_id for _, _, _, effect_id, _ in cases],
    )
    results: list[ScenarioResult] = []
    for scenario_id, title_ja, title_zh, effect_id, runner in cases:
        effect = effects.get(effect_id)
        visual = visuals.get(
            effect_id,
            _fallback_visual(
                "検証対象",
                "验证对象",
                effect_id.rsplit(":", 1)[0],
                effect_id.rsplit(":", 1)[0],
            ),
        )
        if effect is None:
            results.append(
                _exception_result(
                    scenario_id,
                    title_ja,
                    title_zh,
                    effect_id,
                    ["固定状態を構築し、effect を実行する。"],
                    ["构建固定状态并执行技能。"],
                    ["すべての状態遷移チェックが成功する。"],
                    ["所有状态转换检查均应成功。"],
                    [visual],
                    KeyError(f"missing effect: {effect_id}"),
                )
            )
            continue
        try:
            checks = runner(effect)
        except Exception as exc:  # report tools must preserve a readable failure
            results.append(
                _exception_result(
                    scenario_id,
                    title_ja,
                    title_zh,
                    effect_id,
                    ["固定状態を構築し、Legal Action 経由で effect を実行する。"],
                    ["构建固定状态，通过 Legal Action 执行技能。"],
                    ["Zone、modifier、公開情報が公式テキストどおり変化する。"],
                    ["区域、修正值与公开信息按官方文本变化。"],
                    [visual],
                    exc,
                )
            )
            continue
        results.append(
            ScenarioResult(
                scenario_id=scenario_id,
                title_ja=title_ja,
                title_zh=title_zh,
                status="PASS" if all(checks.values()) else "FAIL",
                effect_id=effect_id,
                steps_ja=[
                    "固定した公開・非公開 Zone と card instance を構築する。",
                    "Legal Action と同じ ActionRequest で effect を解決する。",
                    "解決後の Zone、orientation、modifier、event を照合する。",
                ],
                steps_zh=[
                    "构建固定的公开/非公开区域与卡牌实例。",
                    "使用与 Legal Action 相同的 ActionRequest 结算技能。",
                    "核对结算后的区域、状态、修正值与事件。",
                ],
                expected_ja=["各チェックがすべて OK になる。"],
                expected_zh=["每一项检查都应为 OK。"],
                actual_ja=_format_v1_1_checks(checks, "ja"),
                actual_zh=_format_v1_1_checks(checks, "zh"),
                visuals=[visual],
                notes_ja=[f"公式日本語テキスト: {effect.label_ja}"],
                notes_zh=[f"官方日文效果文本：{effect.label_ja}"],
            )
        )
    return results


def _run_v1_1_static_live_state(effect: EffectDefinition) -> dict[str, bool]:
    definitions = {effect.effect_id: effect}
    for effect_id in ("PL!-bp5-003:1", "PL!-bp5-111:1", "PL!HS-bp1-003:1"):
        definition = _load_effect_definition(effect_id)
        definitions[effect_id] = definition
    source = _v1_1_member(
        "source",
        "Source",
        cost=4,
        work_keys=["hasunosora"],
        unit_keys=["a_rise"],
        effect_ids=list(definitions),
        card_code="PL!N-pb1-008",
    )
    left = _v1_1_member(
        "left",
        "Left",
        work_keys=["hasunosora", "nijigasaki"],
        unit_keys=["a_rise"],
        orientation="wait",
    )
    right = _v1_1_member(
        "right",
        "Right",
        work_keys=["hasunosora"],
        unit_keys=["a_rise"],
    )
    state = _v1_1_state(
        definitions,
        [source, left, right],
        member_area={"left": "left", "center": None, "right": "right"},
        hand=["source"],
    )
    reduced_cost = _effective_member_play_cost(state, "player_1", "source") == 2
    state.players["player_1"].hand = []
    state.players["player_1"].member_area["center"] = "source"
    return {
        "effective_cost_reduced": reduced_cost,
        "static_heart_uses_live_state": _static_heart_bonus(
            state, "player_1", "source"
        )
        == Counter({"heart03": 1, "heart05": 2}),
        "static_score_uses_live_state": _static_numeric_bonus(
            state, "player_1", "source", "modify_score"
        )
        == 1,
    }


def _run_v1_1_reveal_until_live(effect: EffectDefinition) -> dict[str, bool]:
    cards = [
        _v1_1_member("source", "Source", effect_ids=[effect.effect_id]),
        _v1_1_member("discard", "Discard"),
        _v1_1_member("top-1", "Top 1"),
        _v1_1_member("top-2", "Top 2"),
        _v1_1_live("matched", "Matched Live"),
    ]
    state = _v1_1_pending_state(
        effect,
        cards,
        hand=["discard"],
        main_deck=["top-1", "top-2", "matched"],
    )
    result = _v1_1_resolve(state, selected_card_instance_ids=["discard"])
    player = result.state.players["player_1"]
    return {
        "matched_live_added_to_hand": player.hand == ["matched"],
        "cost_and_nonmatches_to_waiting": player.waiting_room
        == ["discard", "top-1", "top-2"],
        "public_reveal_event_recorded": any(
            event.event_type == "effect_top_cards_revealed_until_match"
            for event in result.events
        ),
    }


def _run_v1_1_variable_discard_draw(effect: EffectDefinition) -> dict[str, bool]:
    costs = [
        _v1_1_member("cost-1", "Cost 1", unit_keys=["miracra_park"]),
        _v1_1_member("cost-2", "Cost 2", unit_keys=["miracra_park"]),
    ]
    draws = [_v1_1_member(f"draw-{index}", f"Draw {index}") for index in range(3)]
    state = _v1_1_pending_state(
        effect,
        [_v1_1_member("source", "Source", effect_ids=[effect.effect_id]), *costs, *draws],
        hand=["cost-1", "cost-2"],
        main_deck=["draw-0", "draw-1", "draw-2"],
    )
    result = _v1_1_resolve(
        state,
        selected_card_instance_ids=["cost-1", "cost-2"],
    )
    player = result.state.players["player_1"]
    return {
        "selected_hand_cards_discarded": player.waiting_room == ["cost-1", "cost-2"],
        "selected_count_plus_one_drawn": player.hand == ["draw-0", "draw-1", "draw-2"],
    }


def _run_v1_1_waiting_live_to_bottom(effect: EffectDefinition) -> dict[str, bool]:
    state = _v1_1_pending_state(
        effect,
        [
            _v1_1_member("source", "Source", effect_ids=[effect.effect_id]),
            _v1_1_live("waiting-live", "Waiting Live"),
            _v1_1_member("deck-card", "Deck Card"),
        ],
        waiting_room=["waiting-live"],
        main_deck=["deck-card"],
    )
    result = _v1_1_resolve(state, selected_card_instance_ids=["waiting-live"])
    player = result.state.players["player_1"]
    return {
        "selected_live_removed_from_waiting": player.waiting_room == [],
        "selected_live_appended_to_deck_bottom": player.main_deck
        == ["deck-card", "waiting-live"],
    }


def _run_v1_1_attach_waiting_member(effect: EffectDefinition) -> dict[str, bool]:
    state = _v1_1_pending_state(
        effect,
        [
            _v1_1_member("source", "Source", effect_ids=[effect.effect_id]),
            _v1_1_member("target", "Target", cost=9, work_keys=["nijigasaki"]),
        ],
        waiting_room=["target"],
    )
    result = _v1_1_resolve(state, selected_card_instance_ids=["target"])
    player = result.state.players["player_1"]
    return {
        "attached_member_removed_from_waiting": player.waiting_room == [],
        "member_attached_under_source": player.member_area_attachments["center"]
        == ["target"],
    }


def _run_v1_1_energy_score_per_four(effect: EffectDefinition) -> dict[str, bool]:
    energies = [_v1_1_energy(f"energy-{index}") for index in range(4)]
    state = _v1_1_pending_state(
        effect,
        [_v1_1_live("source", "Source Live", effect_ids=[effect.effect_id]), *energies],
        source_zone="live_area",
        energy_area=[card.instance_id for card in energies],
    )
    result = _v1_1_resolve(
        state,
        selected_count=4,
        energy_instance_ids=[card.instance_id for card in energies],
    )
    modifiers = result.state.players["player_1"].manual_modifiers
    return {
        "selected_energy_becomes_wait": all(
            result.state.cards[card.instance_id].orientation == "wait" for card in energies
        ),
        "score_added_per_four_energy": [
            modifier.amount for modifier in modifiers if modifier.modifier_type == "score"
        ]
        == [1],
    }


def _run_v1_1_repeat_mill_blade(effect: EffectDefinition) -> dict[str, bool]:
    state = _v1_1_pending_state(
        effect,
        [
            _v1_1_member("source", "Source", effect_ids=[effect.effect_id]),
            _v1_1_member("top-1", "Top 1"),
            _v1_1_live("top-live", "Top Live"),
            _v1_1_member("top-3", "Top 3"),
        ],
        main_deck=["top-1", "top-live", "top-3"],
    )
    result = _v1_1_resolve(state, selected_count=3)
    player = result.state.players["player_1"]
    return {
        "selected_count_cards_milled": player.waiting_room
        == ["top-1", "top-live", "top-3"],
        "source_waits_when_live_milled": result.state.cards["source"].orientation == "wait",
        "blade_matches_milled_count": [
            modifier.amount
            for modifier in player.manual_modifiers
            if modifier.modifier_type == "blade"
        ]
        == [3],
    }


def _run_v1_1_post_mill_fourth(effect: EffectDefinition) -> dict[str, bool]:
    deck_cards = [_v1_1_member(f"deck-{index}", f"Deck {index}") for index in range(5)]
    state = _v1_1_pending_state(
        effect,
        [
            _v1_1_member("source", "Source", effect_ids=[effect.effect_id]),
            _v1_1_member("milled-member", "Milled Member"),
            _v1_1_live("selected-live", "Selected Live"),
            *deck_cards,
        ],
        main_deck=[
            "milled-member",
            "selected-live",
            "deck-0",
            "deck-1",
            "deck-2",
            "deck-3",
            "deck-4",
        ],
    )
    first = _v1_1_resolve(state)
    initial_mill = first.state.players["player_1"].waiting_room == [
        "milled-member",
        "selected-live",
    ]
    second = _v1_1_resolve(
        first.state,
        selected_card_instance_ids=["selected-live"],
    )
    return {
        "first_stage_mills_two": initial_mill,
        "selected_live_is_fourth_from_top": second.state.players["player_1"].main_deck
        == ["deck-0", "deck-1", "deck-2", "selected-live", "deck-3", "deck-4"],
    }


def _run_v1_1_reveal_hand_then_conceal(effect: EffectDefinition) -> dict[str, bool]:
    state = _v1_1_state(
        {effect.effect_id: effect},
        [
            _v1_1_member("source", "Source", effect_ids=[effect.effect_id]),
            _v1_1_member("cost-4", "Cost 4", cost=4),
            _v1_1_member("cost-6", "Cost 6", cost=6),
        ],
        member_area={"left": None, "center": "source", "right": None},
        hand=["cost-4", "cost-6"],
    )
    result = apply_action(
        state,
        ActionRequest(
            action_type="activate_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "effect_id": effect.effect_id,
                "source_card_instance_id": "source",
                "selected_card_instance_ids": ["cost-4", "cost-6"],
            },
        ),
    )
    player = result.state.players["player_1"]
    return {
        "revealed_hand_is_concealed_after_resolution": all(
            not result.state.cards[instance_id].face_up for instance_id in ("cost-4", "cost-6")
        ),
        "revealed_cost_sum_modifies_score": [
            modifier.amount
            for modifier in player.manual_modifiers
            if modifier.modifier_type == "score"
        ]
        == [1],
    }


def _run_v1_1_member_comparison(effect: EffectDefinition) -> dict[str, bool]:
    source = _v1_1_member("source", "Source", cost=4, effect_ids=[effect.effect_id])
    source.card.basic_hearts = {"heart04": 1}
    source.card.blade = 2
    opponent = _v1_1_member("opponent", "Opponent", cost=4)
    opponent.owner_id = "player_2"
    opponent.card.basic_hearts = {"heart04": 2}
    opponent.card.blade = 2
    state = _v1_1_pending_state(effect, [source, opponent])
    state.players["player_2"].member_area["left"] = "opponent"
    result = _v1_1_resolve(state, selected_card_instance_ids=["opponent"])
    return {
        "matching_attributes_grant_three_blade": [
            modifier.amount
            for modifier in result.state.players["player_1"].manual_modifiers
            if modifier.modifier_type == "blade"
        ]
        == [3]
    }


def _run_v1_1_printemps_ready_score(effect: EffectDefinition) -> dict[str, bool]:
    members = [
        _v1_1_member(
            f"member-{index}",
            f"Member {index}",
            unit_keys=["printemps"],
            orientation="wait",
        )
        for index in range(3)
    ]
    state = _v1_1_pending_state(
        effect,
        [_v1_1_live("source", "Source Live", effect_ids=[effect.effect_id]), *members],
        source_zone="live_area",
    )
    state.players["player_1"].member_area = {
        "left": "member-0",
        "center": "member-1",
        "right": "member-2",
    }
    result = _v1_1_resolve(state)
    player = result.state.players["player_1"]
    return {
        "all_printemps_members_ready": all(
            result.state.cards[f"member-{index}"].orientation == "active"
            for index in range(3)
        ),
        "ready_count_modifies_score": [
            modifier.amount
            for modifier in player.manual_modifiers
            if modifier.modifier_type == "score"
        ]
        == [1],
    }


def _run_v1_1_same_name_discard_target(effect: EffectDefinition) -> dict[str, bool]:
    state = _v1_1_pending_state(
        effect,
        [
            _v1_1_member("source", "Source", effect_ids=[effect.effect_id]),
            _v1_1_member("target", "Shared Name"),
            _v1_1_member("discarded", "Shared Name"),
        ],
        hand=["discarded"],
    )
    state.players["player_1"].member_area["left"] = "target"
    first = _v1_1_resolve(state, selected_card_instance_ids=["discarded"])
    second = _v1_1_resolve(first.state, selected_card_instance_ids=["target"])
    modifiers = second.state.players["player_1"].manual_modifiers
    return {
        "selected_cost_card_discarded": second.state.players["player_1"].waiting_room
        == ["discarded"],
        "same_name_target_gets_heart_and_blade": any(
            modifier.modifier_type == "heart"
            and modifier.target_card_instance_id == "target"
            for modifier in modifiers
        )
        and any(
            modifier.modifier_type == "blade"
            and modifier.target_card_instance_id == "target"
            for modifier in modifiers
        ),
    }


def _run_v1_1_inspect_retain_score(effect: EffectDefinition) -> dict[str, bool]:
    state = _v1_1_pending_state(
        effect,
        [
            _v1_1_live("source", "Source", effect_ids=[effect.effect_id]),
            _v1_1_live("first", "First"),
            _v1_1_member("second", "Second"),
            _v1_1_member("stage-1", "Stage 1", work_keys=["nijigasaki"]),
            _v1_1_member("stage-2", "Stage 2", work_keys=["nijigasaki"]),
        ],
        source_zone="live_area",
        main_deck=["first", "second"],
    )
    state.players["player_1"].member_area = {
        "left": "stage-1",
        "center": "stage-2",
        "right": None,
    }
    inspected = _v1_1_resolve(state)
    resolved = apply_action(
        inspected.state,
        ActionRequest(
            action_type="resolve_effect_choice",
            expected_revision=inspected.state.revision,
            player_id="player_1",
            payload={
                "invocation_id": "invocation",
                "selected_card_instance_ids": ["first"],
                "ordered_card_instance_ids": ["first"],
            },
        ),
    )
    player = resolved.state.players["player_1"]
    return {
        "selected_live_retained_on_top": player.main_deck[0] == "first",
        "unselected_card_moves_to_waiting": player.waiting_room == ["second"],
        "score_and_reveal_event_recorded": any(
            modifier.modifier_type == "score" and modifier.amount == 1
            for modifier in player.manual_modifiers
        )
        and any(
            event.event_type == "effect_top_card_revealed_in_place"
            for event in resolved.events
        ),
    }


def _run_v1_1_position_change_unit_filter(effect: EffectDefinition) -> dict[str, bool]:
    state = _v1_1_state(
        {effect.effect_id: effect},
        [
            _v1_1_member("source", "Source", effect_ids=[effect.effect_id]),
            _v1_1_member("aqours", "Aqours", unit_keys=["aqours"]),
            _v1_1_member("other", "Other", unit_keys=["other"]),
            _v1_1_energy("energy"),
        ],
        member_area={"left": "aqours", "center": "source", "right": "other"},
    )
    state.players["player_1"].energy_area = ["energy"]
    activated = apply_action(
        state,
        ActionRequest(
            action_type="activate_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "effect_id": effect.effect_id,
                "source_card_instance_id": "source",
                "energy_instance_ids": ["energy"],
            },
        ),
    )
    invocation_id = activated.state.pending_effects[0].invocation_id
    resolved = apply_action(
        activated.state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=activated.state.revision,
            player_id="player_1",
            payload={
                "invocation_id": invocation_id,
                "accepted": True,
                "selected_position_slot": "left",
            },
        ),
    )
    return {
        "position_change_targets_required_unit_area": resolved.state.players[
            "player_1"
        ].member_area
        == {"left": "source", "center": "aqours", "right": "other"},
        "position_change_energy_cost_paid": resolved.state.cards["energy"].orientation
        == "wait",
    }


def _load_effect_definition(effect_id: str) -> EffectDefinition:
    registry = load_effect_registry(DEFAULT_EFFECT_REGISTRY)
    return next(effect for effect in registry.effects if effect.effect_id == effect_id)


def _v1_1_state(
    definitions: dict[str, EffectDefinition],
    cards: list[CardInstance],
    *,
    member_area: dict[str, str | None] | None = None,
    hand: list[str] | None = None,
) -> MatchState:
    return MatchState(
        match_id="effect-verification-v1-1",
        seed=23,
        phase="first_main",
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="Player 1",
                member_area=member_area
                or {"left": None, "center": None, "right": None},
                hand=list(hand or []),
            ),
            "player_2": PlayerState(player_id="player_2", name="Player 2"),
        },
        cards={card.instance_id: card for card in cards},
        effect_definitions=definitions,
    )


def _v1_1_pending_state(
    effect: EffectDefinition,
    cards: list[CardInstance],
    *,
    hand: list[str] | None = None,
    main_deck: list[str] | None = None,
    waiting_room: list[str] | None = None,
    energy_area: list[str] | None = None,
    source_zone: str = "stage",
) -> MatchState:
    member_area = {"left": None, "center": None, "right": None}
    live_area: list[str] = []
    if source_zone == "stage":
        member_area["center"] = "source"
    else:
        live_area = ["source"]
    state = _v1_1_state(
        {effect.effect_id: effect},
        cards,
        member_area=member_area,
        hand=hand,
    )
    player = state.players["player_1"]
    player.main_deck = list(main_deck or [])
    player.waiting_room = list(waiting_room or [])
    player.energy_area = list(energy_area or [])
    player.live_area = live_area
    state.pending_effects = [
        EffectInvocation(
            invocation_id="invocation",
            effect_id=effect.effect_id,
            source_card_instance_id="source",
            player_id="player_1",
            trigger_event=effect.trigger,
        )
    ]
    return state


def _v1_1_resolve(state: MatchState, **payload: object):
    return apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "invocation", "accepted": True, **payload},
        ),
    )


def _v1_1_member(
    instance_id: str,
    name_ja: str,
    *,
    cost: int = 1,
    work_keys: list[str] | None = None,
    unit_keys: list[str] | None = None,
    effect_ids: list[str] | None = None,
    orientation: str = "active",
    card_code: str | None = None,
) -> CardInstance:
    return CardInstance(
        instance_id=instance_id,
        owner_id="player_1",
        orientation=orientation,
        card=CardDefinition(
            card_code=card_code or instance_id,
            card_id=instance_id,
            name_ja=name_ja,
            card_type="member",
            cost=cost,
            work_keys=list(work_keys or []),
            unit_keys=list(unit_keys or []),
            effect_ids=list(effect_ids or []),
        ),
    )


def _v1_1_live(
    instance_id: str,
    name_ja: str,
    *,
    effect_ids: list[str] | None = None,
) -> CardInstance:
    return CardInstance(
        instance_id=instance_id,
        owner_id="player_1",
        card=CardDefinition(
            card_code=instance_id,
            card_id=instance_id,
            name_ja=name_ja,
            card_type="live",
            score=1,
            effect_ids=list(effect_ids or []),
        ),
    )


def _v1_1_energy(instance_id: str) -> CardInstance:
    return CardInstance(
        instance_id=instance_id,
        owner_id="player_1",
        orientation="active",
        card=CardDefinition(
            card_code=instance_id,
            card_id=instance_id,
            name_ja="Energy",
            card_type="energy",
        ),
    )


def _load_visuals_for_effect_ids(
    database_path: Path,
    effect_ids: list[str],
) -> dict[str, CardVisual]:
    if not database_path.exists():
        return {}
    visuals: dict[str, CardVisual] = {}
    try:
        with sqlite3.connect(database_path) as connection:
            connection.row_factory = sqlite3.Row
            for effect_id in effect_ids:
                card_code = effect_id.rsplit(":", 1)[0]
                visual = _visual_by_card_code(
                    connection,
                    card_code,
                    role_ja="検証対象",
                    role_zh="验证对象",
                )
                if visual is not None:
                    visuals[effect_id] = visual
    except sqlite3.Error:
        return {}
    return visuals


_V1_1_CHECK_LABELS: dict[str, tuple[str, str]] = {
    "effective_cost_reduced": ("実効登場 cost を状態から算出", "根据状态计算实际登场费用"),
    "static_heart_uses_live_state": ("静的 Heart が現在状態を反映", "常时 Heart 反映当前状态"),
    "static_score_uses_live_state": ("静的 score が現在状態を反映", "常时分数反映当前状态"),
    "matched_live_added_to_hand": ("最初の Live を手札へ", "第一张 Live 加入手牌"),
    "cost_and_nonmatches_to_waiting": ("cost と非該当カードを控室へ", "成本与不匹配卡进入控室"),
    "public_reveal_event_recorded": ("公開 event を記録", "记录公开事件"),
    "selected_hand_cards_discarded": ("選択した手札を控室へ", "所选手牌进入控室"),
    "selected_count_plus_one_drawn": ("選択枚数 +1 を draw", "抽取所选数量加一"),
    "selected_live_removed_from_waiting": ("選択 Live を控室から除外", "所选 Live 离开控室"),
    "selected_live_appended_to_deck_bottom": ("選択 Live をデッキ下へ", "所选 Live 放到牌堆底"),
    "attached_member_removed_from_waiting": ("附属 Member を控室から除外", "附属 Member 离开控室"),
    "member_attached_under_source": ("自身の下に Member を附属", "Member 附属在自身下方"),
    "selected_energy_becomes_wait": ("選択 Energy が Wait", "所选 Energy 变为 Wait"),
    "score_added_per_four_energy": ("Energy 4 枚ごとに score +1", "每 4 张 Energy 分数加一"),
    "selected_count_cards_milled": ("指定枚数を控室へ", "指定数量送入控室"),
    "source_waits_when_live_milled": ("Live が出たため自身が Wait", "出现 Live 后自身变为 Wait"),
    "blade_matches_milled_count": ("mill 枚数分 Blade 加算", "按堆墓数量增加 Blade"),
    "first_stage_mills_two": ("第一段で上 2 枚を控室へ", "第一段将顶 2 张送入控室"),
    "selected_live_is_fourth_from_top": ("選択 Live が上から 4 枚目", "所选 Live 位于牌堆顶第四张"),
    "revealed_hand_is_concealed_after_resolution": ("解決後に手札を再び非公開", "结算后手牌重新隐藏"),
    "revealed_cost_sum_modifies_score": ("公開 cost 合計で score 加算", "按公开卡费用合计增加分数"),
    "matching_attributes_grant_three_blade": ("一致した 3 属性で Blade +3", "三个匹配属性使 Blade 加三"),
    "all_printemps_members_ready": ("Printemps 全員を Active", "所有 Printemps 变为 Active"),
    "ready_count_modifies_score": ("Active 化枚数で score 加算", "按复原数量增加分数"),
    "selected_cost_card_discarded": ("選択 cost カードを控室へ", "所选成本卡进入控室"),
    "same_name_target_gets_heart_and_blade": ("同名対象に Heart と Blade", "同名目标获得 Heart 与 Blade"),
    "selected_live_retained_on_top": ("選択 Live をデッキ上に保持", "所选 Live 保留在牌堆顶"),
    "unselected_card_moves_to_waiting": ("非選択カードを控室へ", "未选卡进入控室"),
    "score_and_reveal_event_recorded": ("score と公開 event を記録", "记录分数与公开事件"),
    "position_change_targets_required_unit_area": ("指定 unit の Area と入れ替え", "与指定组合所在区域交换"),
    "position_change_energy_cost_paid": ("Position Change の Energy cost を支払い", "支付位置移动的 Energy 成本"),
}


def _format_v1_1_checks(checks: dict[str, bool], language: ReportLanguage) -> list[str]:
    index = 0 if language == "ja" else 1
    return [
        f"{_V1_1_CHECK_LABELS.get(name, (name, name))[index]}: {'OK' if passed else 'NG'}"
        for name, passed in checks.items()
    ]


def _registry_contract_scenarios(
    effects: dict[str, EffectDefinition],
    database_path: Path,
) -> list[ScenarioResult]:
    visual_by_code: dict[str, CardVisual] = {}
    if database_path.exists():
        try:
            with sqlite3.connect(database_path) as connection:
                connection.row_factory = sqlite3.Row
                for spec in _PHASE5_V1_CONTRACTS:
                    card_code = spec.effect_id.rsplit(":", 1)[0]
                    visual = _visual_by_card_code(
                        connection,
                        card_code,
                        role_ja="検証対象",
                        role_zh="验证对象",
                    )
                    if visual is not None:
                        visual_by_code[card_code] = visual
        except sqlite3.Error:
            visual_by_code = {}

    results: list[ScenarioResult] = []
    for spec in _PHASE5_V1_CONTRACTS:
        effect = effects.get(spec.effect_id)
        card_code = spec.effect_id.rsplit(":", 1)[0]
        visual = visual_by_code.get(
            card_code,
            _fallback_visual("検証対象", "验证对象", card_code, card_code),
        )
        actual_actions = (
            tuple(operation.action_type for operation in effect.actions)
            if effect is not None
            else ()
        )
        actual_choice = (
            effect.choice.choice_type
            if effect is not None and effect.choice is not None
            else None
        )
        checks = {
            "effect_exists": effect is not None,
            "test_validated_executable": bool(
                effect
                and effect.simulation_support == "test_validated_executable"
                and effect.review_status == "test_validated"
            ),
            "trigger_matches": bool(effect and effect.trigger == spec.trigger),
            "choice_shape_matches": actual_choice == spec.choice_type,
            "action_family_matches": actual_actions == spec.action_types,
        }
        expected_actions = ", ".join(spec.action_types)
        actual_trigger = effect.trigger if effect is not None else "missing"
        actual_label = effect.label_ja if effect is not None else "missing"
        status = "PASS" if all(checks.values()) else "FAIL"
        results.append(
            ScenarioResult(
                scenario_id=f"registry_contract_{spec.effect_id.replace(':', '_')}",
                title_ja=f"{card_code}: {spec.family_ja}",
                title_zh=f"{card_code}：{spec.family_zh}",
                status=status,
                effect_id=spec.effect_id,
                steps_ja=[
                    "現在の effect registry から対象 effect を読み込む。",
                    "trigger、choice、operation とレビュー状態を固定契約と比較する。",
                ],
                steps_zh=[
                    "从当前 effect registry 读取目标 effect。",
                    "将 trigger、choice、operation 和审核状态与固定契约比较。",
                ],
                expected_ja=[
                    f"trigger は `{spec.trigger}`。",
                    f"choice は `{spec.choice_type or 'none'}`。",
                    f"operations は `{expected_actions}`。",
                    "support は `test_validated_executable`、review は `test_validated`。",
                ],
                expected_zh=[
                    f"trigger 为 `{spec.trigger}`。",
                    f"choice 为 `{spec.choice_type or 'none'}`。",
                    f"operations 为 `{expected_actions}`。",
                    "support 为 `test_validated_executable`，review 为 `test_validated`。",
                ],
                actual_ja=[
                    f"effect 登録: {'OK' if checks['effect_exists'] else 'NG'}",
                    f"support / review: {'OK' if checks['test_validated_executable'] else 'NG'}",
                    f"trigger: `{actual_trigger}` ({'OK' if checks['trigger_matches'] else 'NG'})",
                    f"choice: `{actual_choice or 'none'}` ({'OK' if checks['choice_shape_matches'] else 'NG'})",
                    f"operations: `{', '.join(actual_actions)}` ({'OK' if checks['action_family_matches'] else 'NG'})",
                ],
                actual_zh=[
                    f"effect 登记：{'OK' if checks['effect_exists'] else 'NG'}",
                    f"support / review：{'OK' if checks['test_validated_executable'] else 'NG'}",
                    f"trigger：`{actual_trigger}`（{'OK' if checks['trigger_matches'] else 'NG'}）",
                    f"choice：`{actual_choice or 'none'}`（{'OK' if checks['choice_shape_matches'] else 'NG'}）",
                    f"operations：`{', '.join(actual_actions)}`（{'OK' if checks['action_family_matches'] else 'NG'}）",
                ],
                visuals=[visual],
                notes_ja=[f"公式日本語テキスト: {actual_label}"],
                notes_zh=[f"官方日文效果文本：{actual_label}"],
            )
        )
    return results


def write_effect_verification_report(
    output_dir: Path,
    results: list[ScenarioResult],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "effect-verification-summary.json").write_text(
        json.dumps(
            {
                "schema_version": "effect_verification_report_v0.4",
                "total": len(results),
                "passed": sum(1 for result in results if result.status == "PASS"),
                "failed": sum(1 for result in results if result.status != "PASS"),
                "dynamic_state_transition_scenarios": sum(
                    1 for result in results if not result.scenario_id.startswith("registry_contract_")
                ),
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
