"""Per-action conformance checks for deterministic AI playtests.

The checks in this module are intentionally narrower than a proof of the full
ruleset. They verify observable state transitions against the official
comprehensive rules and keep any card-text judgement that cannot be established
from the match-local effect snapshot visible as a review item.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from loveca.simulation.models import (
    ActionRequest,
    GameEvent,
    LegalAction,
    MatchState,
)

AuditVerdict = Literal["pass", "review", "fail"]


@dataclass(frozen=True)
class RuleReference:
    section: str
    summary_zh: str


@dataclass(frozen=True)
class RuleCheck:
    check_id: str
    verdict: AuditVerdict
    summary_zh: str
    rule_refs: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)


RULE_REFERENCES: dict[str, RuleReference] = {
    "1.2.1.1": RuleReference("1.2.1.1", "仅一方成功 Live 达到 3 张时，该玩家获胜。"),
    "1.2.1.2": RuleReference("1.2.1.2", "双方同时成功 Live 达到 3 张时，比赛为平局。"),
    "1.3.1": RuleReference("1.3.1", "卡牌文本与综合规则冲突时，以卡牌文本为准。"),
    "1.3.2": RuleReference("1.3.2", "无法完成全部处理时，执行能够完成的部分。"),
    "4.6": RuleReference("4.6", "Live 区是公开区域，但设置期间卡牌暂时背面放置。"),
    "4.11": RuleReference("4.11", "手牌是非公开区域，对手不能确认卡牌身份。"),
    "4.12": RuleReference("4.12", "控室是公开区域。"),
    "5.6": RuleReference("5.6", "抽牌从主牌库顶移动到手牌。"),
    "5.7": RuleReference("5.7", "查看牌库顶不会擅自改变卡牌区域。"),
    "5.9": RuleReference("5.9", "支付 Energy 时将指定数量 Active Energy 变为 Wait。"),
    "6.2.1.2": RuleReference("6.2.1.2", "对局开始时洗切主牌库。"),
    "6.2.1.4": RuleReference("6.2.1.4", "随机决定取得先后手选择权的玩家。"),
    "6.2.1.5": RuleReference("6.2.1.5", "双方起手各抽 6 张。"),
    "6.2.1.6": RuleReference("6.2.1.6", "依先后手顺序调度并补回相同张数。"),
    "6.2.1.7": RuleReference("6.2.1.7", "双方初始放置 3 张 Energy。"),
    "7.3.3": RuleReference("7.3.3", "通常阶段依 Active、Energy、Draw、Main 顺序进行。"),
    "7.4": RuleReference("7.4", "Active Phase 将己方 Wait 的 Member 与 Energy 变为 Active。"),
    "7.5": RuleReference("7.5", "Energy Phase 从 Energy Deck 顶补充 1 张 Energy。"),
    "7.6": RuleReference("7.6", "Draw Phase 抽 1 张卡。"),
    "7.7": RuleReference("7.7", "Main Phase 可登场 Member、发动起动能力或结束阶段。"),
    "8.2": RuleReference("8.2", "双方依序设置至多 3 张卡并补抽相同张数。"),
    "8.3.4": RuleReference("8.3.4", "公开 Live 区卡牌，非 Live 卡进入控室。"),
    "8.3.8": RuleReference("8.3.8", "Live 开始时能力在规定时点触发。"),
    "8.3.10": RuleReference("8.3.10", "应援次数为 Active Member 的 Blade 合计。"),
    "8.3.11": RuleReference("8.3.11", "按应援次数从牌库顶公开卡牌到 Resolution Area。"),
    "8.3.12": RuleReference("8.3.12", "处理特殊 Blade Heart 的抽牌、分数等效果。"),
    "8.3.14": RuleReference("8.3.14", "可用 Heart 为 Member Heart 与应援 Heart 的合计。"),
    "8.3.15": RuleReference("8.3.15", "逐张满足 Live 所需 Heart，任意色可代替指定颜色。"),
    "8.3.16": RuleReference("8.3.16", "任一 Live 需求不满足时，本方 Live 全部进入控室。"),
    "8.4.2": RuleReference("8.4.2", "Live 总分为 Live 分数与特殊应援分数的合计。"),
    "8.4.3": RuleReference("8.4.3", "比分时先判断双方 Live 区是否仍有卡，再比较总分。"),
    "8.4.4": RuleReference("8.4.4", "Live 区仍有 Live 卡的玩家视为 Live 成功。"),
    "8.4.5": RuleReference("8.4.5", "Live 成功后先处理检查时点和自动能力。"),
    "8.4.6": RuleReference("8.4.6", "比较双方总分；满足条件的同分可由双方同时胜出。"),
    "8.4.7": RuleReference("8.4.7", "胜者从 Live 区选 1 张放入成功 Live 区。"),
    "8.4.7.1": RuleReference("8.4.7.1", "同分时已有 2 张成功 Live 的玩家不能再放置。"),
    "8.4.8": RuleReference("8.4.8", "结算后其余 Live 与应援卡进入控室。"),
    "8.4.10": RuleReference("8.4.10", "触发本回合尚未触发的回合结束自动能力。"),
    "8.4.11": RuleReference("8.4.11", "Live 或回合持续效果在对应边界失效。"),
    "8.4.12": RuleReference("8.4.12", "结算新产生的回合结束能力后再次检查。"),
    "8.4.13": RuleReference("8.4.13", "仅一方新增成功 Live 时该方成为下回合先攻，否则先攻不变。"),
    "9.1": RuleReference("9.1", "能力按起动、自动、常时等类型处理。"),
    "9.4": RuleReference("9.4", "支付能力费用后再处理效果。"),
    "9.5": RuleReference("9.5", "能力只能在合法时点发动和结算。"),
    "9.6.2": RuleReference("9.6.2", "Member 登场和能力处理必须按规则顺序完成。"),
    "9.6.2.1.2": RuleReference("9.6.2.1.2", "本回合已有 Member 进入的区域不能再次指定。"),
    "9.6.2.3.2": RuleReference("9.6.2.3.2", "Baton Touch 以原 Member cost 抵扣登场 Energy。"),
    "9.6.3": RuleReference("9.6.3", "必选数量必须满足；至多 N 张可以选择 0 张。"),
}


ACTION_RULE_REFS: dict[str, tuple[str, ...]] = {
    "choose_first_player": ("6.2.1.2", "6.2.1.4", "6.2.1.5"),
    "submit_mulligan": ("6.2.1.6", "6.2.1.7"),
    "advance_phase": ("7.3.3", "7.4", "7.5", "7.6", "8.3.4", "8.3.10"),
    "play_member": ("7.7", "5.9", "9.6.2", "9.6.2.1.2", "9.6.2.3.2"),
    "end_main_phase": ("7.7", "7.3.3"),
    "set_live_cards": ("4.6", "8.2"),
    "resolve_live_requirements": ("8.3.14", "8.3.15", "8.3.16", "8.4.7"),
    "activate_effect": ("1.3.1", "9.1", "9.4", "9.5"),
    "resolve_effect": ("1.3.1", "1.3.2", "9.4", "9.5", "9.6.3"),
    "resolve_effect_choice": ("1.3.1", "1.3.2", "9.6.3"),
    "skip_effect": ("1.3.1",),
    "manual_adjustment": ("1.3.1",),
    "resolve_manual_inspection": ("1.3.1", "5.7"),
    "start_next_turn": ("8.4.11", "8.4.13", "7.3.3"),
}


def audit_action_transition(
    before: MatchState,
    after: MatchState,
    action: ActionRequest,
    legal_actions: list[LegalAction],
    events: list[GameEvent],
) -> list[RuleCheck]:
    """Audit one accepted action without mutating either state."""

    checks = [
        _legal_action_check(action, legal_actions),
        _revision_check(before, after),
        _zone_integrity_check(after),
        _action_semantics_check(before, after, action, events),
    ]
    if action.action_type in {
        "activate_effect",
        "resolve_effect",
        "resolve_effect_choice",
        "skip_effect",
    }:
        checks.append(_effect_semantics_check(before, after, action, events))
    checks.extend(_event_conformance_checks(before, after, events))
    return checks


def action_rule_refs(action_type: str) -> tuple[str, ...]:
    return ACTION_RULE_REFS.get(action_type, ("1.3.1",))


def summarize_verdict(checks: list[RuleCheck]) -> AuditVerdict:
    if any(check.verdict == "fail" for check in checks):
        return "fail"
    if any(check.verdict == "review" for check in checks):
        return "review"
    return "pass"


def serialize_checks(checks: list[RuleCheck]) -> list[dict[str, Any]]:
    return [asdict(check) for check in checks]


def _legal_action_check(
    action: ActionRequest,
    legal_actions: list[LegalAction],
) -> RuleCheck:
    matches = [
        item
        for item in legal_actions
        if item.action_type == action.action_type and item.player_id == action.player_id
    ]
    return RuleCheck(
        check_id="legal_action_generator",
        verdict="pass" if matches else "fail",
        summary_zh=(
            "AI 选择来自 LegalActionGenerator。"
            if matches
            else "AI 提交了 LegalActionGenerator 未提供的操作。"
        ),
        rule_refs=action_rule_refs(action.action_type),
        evidence={
            "action_type": action.action_type,
            "player_id": action.player_id,
            "legal_action_types": [item.action_type for item in legal_actions],
        },
    )


def _revision_check(before: MatchState, after: MatchState) -> RuleCheck:
    expected = before.revision + 1
    return RuleCheck(
        check_id="revision_progression",
        verdict="pass" if after.revision == expected else "fail",
        summary_zh=(
            "Action 原子提交且 revision 递增 1。"
            if after.revision == expected
            else "Action 后 revision 未按预期递增。"
        ),
        evidence={
            "before_revision": before.revision,
            "after_revision": after.revision,
            "expected_revision": expected,
        },
    )


def _zone_integrity_check(state: MatchState) -> RuleCheck:
    memberships: dict[str, list[str]] = defaultdict(list)
    ownership_errors: list[str] = []
    for player_id, player in state.players.items():
        zones: dict[str, list[str]] = {
            "main_deck": player.main_deck,
            "energy_deck": player.energy_deck,
            "hand": player.hand,
            "energy_area": player.energy_area,
            "live_area": player.live_area,
            "waiting_room": player.waiting_room,
            "resolution_area": player.resolution_area,
            "success_live_area": player.success_live_area,
        }
        for slot, instance_id in player.member_area.items():
            if instance_id is not None:
                zones[f"member_area:{slot}"] = [instance_id]
        for slot, instance_ids in player.member_area_attachments.items():
            zones[f"member_attachment:{slot}"] = instance_ids
        for zone_name, instance_ids in zones.items():
            for instance_id in instance_ids:
                memberships[instance_id].append(f"{player_id}:{zone_name}")
                card = state.cards.get(instance_id)
                if card is None or card.owner_id != player_id:
                    ownership_errors.append(instance_id)
    duplicates = {
        instance_id: zones for instance_id, zones in memberships.items() if len(zones) != 1
    }
    missing = sorted(set(state.cards) - set(memberships))
    unexpected = sorted(set(memberships) - set(state.cards))
    ok = not duplicates and not missing and not unexpected and not ownership_errors
    return RuleCheck(
        check_id="zone_integrity",
        verdict="pass" if ok else "fail",
        summary_zh=(
            "所有 CardInstance 均唯一存在于所属玩家的一个区域。"
            if ok
            else "检测到卡牌重复、丢失或跨玩家区域错误。"
        ),
        rule_refs=("4.6", "4.11", "4.12"),
        evidence={
            "card_count": len(state.cards),
            "duplicates": duplicates,
            "missing": missing,
            "unexpected": unexpected,
            "ownership_errors": sorted(set(ownership_errors)),
        },
    )


def _action_semantics_check(
    before: MatchState,
    after: MatchState,
    action: ActionRequest,
    events: list[GameEvent],
) -> RuleCheck:
    action_type = action.action_type
    refs = action_rule_refs(action_type)
    ok = True
    evidence: dict[str, Any] = {
        "phase_before": before.phase,
        "phase_after": after.phase,
        "event_types": [event.event_type for event in events],
    }
    summary = "Action 的可观察状态变化符合对应流程。"

    if action_type == "submit_mulligan" and action.player_id:
        before_hand = len(before.players[action.player_id].hand)
        after_hand = len(after.players[action.player_id].hand)
        replaced = len(action.payload.get("card_instance_ids", []))
        event = _event(events, "mulligan_completed", action.player_id)
        ok = before_hand == after_hand and event is not None
        evidence.update(
            before_hand=before_hand,
            after_hand=after_hand,
            selected_count=replaced,
            event_replaced_count=event.data.get("replaced_count") if event else None,
        )
        if after.phase == "first_active":
            energy_counts = {
                player_id: len(player.energy_area) for player_id, player in after.players.items()
            }
            ok = ok and all(count == 3 for count in energy_counts.values())
            evidence["initial_energy_counts"] = energy_counts
    elif action_type == "play_member" and action.player_id:
        instance_id = action.payload.get("card_instance_id")
        slot = action.payload.get("slot")
        payment_ids = list(action.payload.get("energy_instance_ids", []))
        played = _event(events, "member_played", action.player_id)
        ok = (
            isinstance(instance_id, str)
            and slot in {"left", "center", "right"}
            and after.players[action.player_id].member_area.get(slot) == instance_id
            and instance_id not in after.players[action.player_id].hand
            and played is not None
            and all(after.cards[item].orientation == "wait" for item in payment_ids)
        )
        evidence.update(
            card_instance_id=instance_id,
            slot=slot,
            payment_count=len(payment_ids),
            baton_touch=bool(action.payload.get("use_baton_touch")),
        )
    elif action_type == "set_live_cards" and action.player_id:
        selected = list(action.payload.get("card_instance_ids", []))
        set_event = _event(events, "live_cards_set", action.player_id)
        draw_event = _event(events, "cards_drawn", action.player_id, reason="live_set_replacement")
        drawn = list(draw_event.data.get("instance_ids", [])) if draw_event else []
        ok = (
            len(selected) <= 3
            and set(selected).issubset(after.players[action.player_id].live_area)
            and all(not after.cards[item].face_up for item in selected)
            and len(drawn) == len(selected)
            and set_event is not None
        )
        evidence.update(selected_count=len(selected), replacement_draw_count=len(drawn))
    elif action_type == "resolve_live_requirements":
        resolved = _event(events, "live_requirements_resolved", action.player_id)
        selected = _event(events, "success_live_selected", action.player_id)
        ok = resolved is not None or selected is not None
        evidence.update(
            resolution_event=resolved.event_type if resolved else None,
            success_selection_event=selected.event_type if selected else None,
        )
    elif action_type == "start_next_turn":
        moved = list(before.success_live_moved_player_ids)
        expected_first = moved[0] if len(moved) == 1 else before.first_player_id
        ok = (
            after.turn_number == before.turn_number + 1
            and after.first_player_id == expected_first
            and after.phase == "first_active"
        )
        evidence.update(
            success_live_moved_player_ids=moved,
            expected_first_player_id=expected_first,
            actual_first_player_id=after.first_player_id,
        )
    elif action_type == "skip_effect":
        ok = False
        summary = "该步骤通过调试跳过未完整处理技能，不能判定为规则一致。"

    return RuleCheck(
        check_id=f"action_semantics:{action_type}",
        verdict="pass" if ok else "fail",
        summary_zh=summary if ok else summary.replace("符合", "不符合"),
        rule_refs=refs,
        evidence=evidence,
    )


def _effect_semantics_check(
    before: MatchState,
    after: MatchState,
    action: ActionRequest,
    events: list[GameEvent],
) -> RuleCheck:
    effect_id = action.payload.get("effect_id")
    invocation_id = action.payload.get("invocation_id")
    invocation = next(
        (
            item
            for item in before.pending_effects
            if invocation_id and item.invocation_id == invocation_id
        ),
        None,
    )
    if effect_id is None and invocation is not None:
        effect_id = invocation.effect_id
    effect = before.effect_definitions.get(effect_id) if isinstance(effect_id, str) else None
    if action.action_type == "activate_effect" and effect is None:
        effect = after.effect_definitions.get(effect_id) if isinstance(effect_id, str) else None
    if effect is None:
        return RuleCheck(
            check_id="effect_snapshot_binding",
            verdict="fail",
            summary_zh="操作引用的技能不在本局 effect definition 快照中。",
            rule_refs=("1.3.1", "9.5"),
            evidence={"effect_id": effect_id, "invocation_id": invocation_id},
        )
    source_id = (
        invocation.source_card_instance_id
        if invocation is not None
        else action.payload.get("source_card_instance_id")
    )
    source = before.cards.get(source_id) if isinstance(source_id, str) else None
    binding_ok = bool(
        source
        and effect.effect_id in source.card.effect_ids
        and source.card.raw_text_hash == effect.raw_text_hash
    )
    trigger_ok = invocation is None or invocation.trigger_event == effect.trigger
    operation_types = {item.action_type for item in (*effect.cost, *effect.actions)}
    semantic = _semantic_operation_alignment(effect.label_ja, operation_types)
    resolved_or_pending = (
        action.action_type == "activate_effect"
        or any(
            event.event_type
            in {
                "effect_resolved",
                "effect_declined",
                "effect_inspection_started",
                "effect_cost_paid",
            }
            for event in events
        )
        or any(item.effect_id == effect.effect_id for item in after.pending_effects)
        or after.pending_choice is not None
    )
    declined = (
        action.action_type == "resolve_effect"
        and action.payload.get("accepted") is False
        and any(event.event_type == "effect_declined" for event in events)
    )
    support_ok = effect.simulation_support == "test_validated_executable" or declined
    if not binding_ok or not trigger_ok or not resolved_or_pending or not support_ok:
        verdict: AuditVerdict = "fail"
    elif declined:
        verdict = "pass"
    elif semantic is None:
        verdict = "review"
    else:
        verdict = "pass" if semantic else "fail"
    summary = {
        "pass": "技能与本局快照、触发时点及日文语义关键词一致。",
        "review": "技能结构链有效，但日文文本未命中保守语义词典，需要人工复核。",
        "fail": "技能绑定、触发时点或日文语义映射存在不一致。",
    }[verdict]
    return RuleCheck(
        check_id="effect_snapshot_binding",
        verdict=verdict,
        summary_zh=summary,
        rule_refs=("1.3.1", "1.3.2", "9.1", "9.4", "9.5"),
        evidence={
            "effect_id": effect.effect_id,
            "source_card_code": source.card.card_code if source else None,
            "label_ja": effect.label_ja,
            "trigger": effect.trigger,
            "invocation_trigger": invocation.trigger_event if invocation else None,
            "operation_types": sorted(operation_types),
            "simulation_support": effect.simulation_support,
            "hash_binding_ok": binding_ok,
            "support_ok": support_ok,
            "declined_optional_effect": declined,
            "semantic_alignment": semantic,
        },
    )


def _semantic_operation_alignment(
    label_ja: str,
    operation_types: set[str],
) -> bool | None:
    expectations: list[set[str]] = []
    if "カードを引" in label_ja or "枚引" in label_ja:
        expectations.append(
            {
                "draw_card",
                "draw_card_per_stage_member",
                "draw_until_hand_size",
                "grant_live_success_draw",
                "draw_if_milled_all_card_type",
                "draw_if_milled_any_card_type",
                "draw_if_selected_card_type",
                "draw_if_selected_none_card_type",
                "draw_if_selected_without_blade_heart",
            }
        )
    if "エネルギーデッキから" in label_ja and "置く" in label_ja:
        expectations.append({"place_energy_from_deck"})
    if "【ブレード】を得" in label_ja:
        expectations.append(
            {
                "gain_blade",
                "gain_blade_to_stage_members",
                "gain_blade_if_milled_all_card_type",
                "gain_blade_if_milled_any_card_type",
            }
        )
    if "スコアを＋" in label_ja or "合計スコアを＋" in label_ja:
        expectations.append({"modify_score", "grant_live_success_draw"})
    if "デッキの上から" in label_ja and "見る" in label_ja:
        expectations.append({"inspect_top_cards"})
    if "デッキの上からカードを" in label_ja and "枚控え室に置く" in label_ja:
        expectations.append({"mill_top_cards"})
    if "控え室から" in label_ja and "手札に加え" in label_ja:
        expectations.append({"return_from_waiting_room", "move_selected_to_hand"})
    if "控え室から" in label_ja and "デッキの一番上から" in label_ja:
        expectations.append({"move_selected_to_deck_position"})
    if "控え室" in label_ja and "好きな順番でデッキの上に置く" in label_ja:
        expectations.append({"move_selected_to_deck_top"})
    if "ステージから控え室に置く" in label_ja:
        expectations.append({"source_to_waiting_room"})
    if "公開" in label_ja:
        expectations.append(
            {
                "reveal_cards",
                "reveal_top_cards",
                "reveal_top_in_place",
                "reveal_selected_cards",
                "reveal_top_matching_to_hand_else_deck_top",
                "reveal_top_matching_to_hand_else_waiting",
                "reveal_until_matching_to_hand_else_waiting",
                "reveal_top_to_hand",
                "select_to_hand_from_inspected",
            }
        )
    if "アクティブにする" in label_ja:
        expectations.append({"ready_member", "ready_energy"})
    if "ウェイトにする" in label_ja:
        expectations.append(
            {"apply_wait", "apply_wait_member", "apply_wait_energy", "apply_wait_to_stage_members"}
        )
    if "ポジションチェンジ" in label_ja:
        expectations.append({"position_change_source", "position_change_selected"})
    if "元々持つハートは選んだハートになる" in label_ja:
        expectations.append({"replace_member_base_hearts"})
    if (
        "ハート】を得" in label_ja
        or "ハートを得" in label_ja
        or "【heart01】を得" in label_ja
        or "【heart02】を得" in label_ja
        or "【heart03】を得" in label_ja
        or "【heart04】を得" in label_ja
        or "【heart05】を得" in label_ja
        or "【heart06】を得" in label_ja
    ):
        expectations.append(
            {
                "gain_heart",
                "gain_heart_to_stage_members",
                "gain_heart_if_milled_all_have_heart",
                "gain_heart_from_selected_card_colors",
                "replace_member_base_hearts",
                "modify_required_heart",
                "replace_required_hearts",
                "replace_yell_blade_hearts",
            }
        )
    if not expectations:
        return None
    return all(bool(expected & operation_types) for expected in expectations)


def _event_conformance_checks(
    before: MatchState,
    after: MatchState,
    events: list[GameEvent],
) -> list[RuleCheck]:
    checks: list[RuleCheck] = []
    for event in events:
        if event.event_type == "live_requirements_resolved":
            allocations = list(event.data.get("allocations", []))
            allocation_ok = all(
                bool(item.get("satisfied")) == (not bool(item.get("missing_hearts")))
                for item in allocations
            )
            overall = bool(event.data.get("satisfied"))
            if allocations:
                allocation_ok = allocation_ok and overall == all(
                    bool(item.get("satisfied")) for item in allocations
                )
            checks.append(
                RuleCheck(
                    check_id="live_heart_allocation",
                    verdict="pass" if allocation_ok else "fail",
                    summary_zh=(
                        "Live 所需 Heart、缺口和整体成功结果一致。"
                        if allocation_ok
                        else "Live Heart 分配明细与整体判定不一致。"
                    ),
                    rule_refs=("8.3.14", "8.3.15", "8.3.16"),
                    evidence={
                        "player_id": event.player_id,
                        "satisfied": overall,
                        "allocations": allocations,
                    },
                )
            )
        elif event.event_type == "live_success_determined":
            expected = [
                player_id
                for player_id in (before.first_player_id, before.second_player_id)
                if player_id is not None and before.players[player_id].live_area
            ]
            for requirement_event in events:
                if requirement_event.event_type != "live_requirements_resolved":
                    continue
                resolved_player_id = requirement_event.player_id
                if resolved_player_id not in before.players:
                    continue
                if requirement_event.data.get("satisfied"):
                    if resolved_player_id not in expected:
                        expected.append(resolved_player_id)
                elif resolved_player_id in expected:
                    expected.remove(resolved_player_id)
            ordered_players = [
                player_id
                for player_id in (before.first_player_id, before.second_player_id)
                if player_id in expected
            ]
            actual = list(event.data.get("successful_player_ids", []))
            checks.append(
                RuleCheck(
                    check_id="live_success_before_score_comparison",
                    verdict="pass" if actual == ordered_players else "fail",
                    summary_zh=(
                        "在比较总分前，按 Live 区是否仍有卡确定 Live 成功玩家。"
                        if actual == expected
                        else "Live 成功玩家与 Heart 判定后的 Live 区不一致。"
                    ),
                    rule_refs=("8.4.4", "8.4.5"),
                    evidence={
                        "expected_successful_player_ids": ordered_players,
                        "actual_successful_player_ids": actual,
                    },
                )
            )
        elif event.event_type == "live_judgment_started":
            snapshot = event.data.get("players", {})
            successful = list(event.data.get("successful_player_ids", []))
            expected_basis, expected_winners = _expected_live_judgment(
                before.first_player_id or "",
                before.second_player_id or "",
                successful,
                event.data.get("scores", {}),
            )
            actual_basis = event.data.get("basis")
            actual_winners = list(event.data.get("winner_ids", []))
            checks.extend(
                _live_judgment_detail_checks(
                    after,
                    snapshot=snapshot,
                    successful_player_ids=successful,
                    expected_basis=expected_basis,
                    actual_basis=actual_basis,
                    expected_winner_ids=expected_winners,
                    actual_winner_ids=actual_winners,
                    actual_eligible_player_ids=list(
                        event.data.get("placement_eligible_player_ids", [])
                    ),
                    actual_prevented_player_ids=list(
                        event.data.get("placement_prevented_player_ids", [])
                    ),
                    scores=event.data.get("scores", {}),
                )
            )
        elif event.event_type == "success_live_selected":
            instance_id = event.data.get("card_instance_id")
            player_id = event.player_id or ""
            moved = after.success_live_moved_instance_ids.get(player_id, [])
            ok = (
                isinstance(instance_id, str)
                and instance_id in after.players[player_id].success_live_area
                and instance_id in moved
                and player_id in after.live_placement_eligible_player_ids
            )
            checks.append(
                RuleCheck(
                    check_id="success_live_card_selection",
                    verdict="pass" if ok else "fail",
                    summary_zh=(
                        "有移动资格的胜者恰好选择一张 Live 移入成功 Live 区。"
                        if ok
                        else "成功 Live 的选择或移动资格不一致。"
                    ),
                    rule_refs=("8.4.7", "8.4.7.1"),
                    evidence={
                        "player_id": player_id,
                        "card_instance_id": instance_id,
                        "eligible_player_ids": after.live_placement_eligible_player_ids,
                        "moved_instance_ids": moved,
                    },
                )
            )
        elif event.event_type == "live_judgment_completed":
            moved = list(event.data.get("success_live_moved_player_ids", []))
            eligible = list(event.data.get("placement_eligible_player_ids", []))
            cleaned = all(
                not player.live_area and not player.resolution_area
                for player in after.players.values()
            )
            movement_ok = moved == eligible
            checks.append(
                RuleCheck(
                    check_id="live_judgment_cleanup_and_placement",
                    verdict="pass" if movement_ok and cleaned else "fail",
                    summary_zh=(
                        "成功 Live 移动资格、实际移动及 Live/应援清理一致。"
                        if movement_ok and cleaned
                        else "成功 Live 移动或 Live 结束区域清理不一致。"
                    ),
                    rule_refs=("8.4.7", "8.4.7.1", "8.4.8"),
                    evidence={
                        "eligible_player_ids": eligible,
                        "moved_player_ids": moved,
                        "live_and_resolution_areas_empty": cleaned,
                    },
                )
            )
        elif event.event_type == "turn_completed":
            moved = list(event.data.get("success_live_moved_player_ids", []))
            expected_first = moved[0] if len(moved) == 1 else before.first_player_id
            actual_first = event.data.get("next_first_player_id")
            checks.append(
                RuleCheck(
                    check_id="next_turn_first_player",
                    verdict="pass" if actual_first == expected_first else "fail",
                    summary_zh=(
                        "仅一方移动成功 Live 时该方取得先攻，否则原先攻保持。"
                        if actual_first == expected_first
                        else "下一回合先攻与成功 Live 移动结果不一致。"
                    ),
                    rule_refs=("8.4.13",),
                    evidence={
                        "moved_player_ids": moved,
                        "expected_first_player_id": expected_first,
                        "actual_first_player_id": actual_first,
                    },
                )
            )
        elif event.event_type == "match_completed":
            counts = {
                player_id: len(player.success_live_area)
                for player_id, player in after.players.items()
            }
            threshold = sorted(player_id for player_id, count in counts.items() if count >= 3)
            result = after.game_result
            ok = bool(result) and (
                (
                    len(threshold) == 1
                    and result.outcome == "win"
                    and result.winner_player_ids == threshold
                )
                or (
                    len(threshold) == 2
                    and result.outcome == "draw"
                    and not result.winner_player_ids
                )
            )
            checks.append(
                RuleCheck(
                    check_id="match_result",
                    verdict="pass" if ok else "fail",
                    summary_zh=(
                        "正式胜负与成功 Live 3 张阈值一致。"
                        if ok
                        else "正式胜负与成功 Live 阈值不一致。"
                    ),
                    rule_refs=("1.2.1.1", "1.2.1.2"),
                    evidence={
                        "success_live_counts": counts,
                        "game_result": result.model_dump() if result else None,
                    },
                )
            )
    return checks


def _expected_live_winners(state: MatchState) -> list[str]:
    first_id = state.first_player_id or ""
    second_id = state.second_player_id or ""
    first = state.players[first_id]
    second = state.players[second_id]
    if not first.live_area and not second.live_area:
        return []
    if first.live_area and not second.live_area:
        return [first_id]
    if second.live_area and not first.live_area:
        return [second_id]
    if first.live_result.total_score > second.live_result.total_score:
        return [first_id]
    if second.live_result.total_score > first.live_result.total_score:
        return [second_id]
    return [first_id, second_id]


def _expected_live_judgment(
    first_id: str,
    second_id: str,
    successful_player_ids: list[str],
    scores: Any,
) -> tuple[str, list[str]]:
    successful = set(successful_player_ids)
    if not successful:
        return "no_successful_live", []
    if successful == {first_id}:
        return "only_one_player_has_successful_live", [first_id]
    if successful == {second_id}:
        return "only_one_player_has_successful_live", [second_id]
    score_map = scores if isinstance(scores, dict) else {}
    first_score = int(score_map.get(first_id, 0))
    second_score = int(score_map.get(second_id, 0))
    if first_score > second_score:
        return "higher_total_score", [first_id]
    if second_score > first_score:
        return "higher_total_score", [second_id]
    return "equal_total_score", [first_id, second_id]


def _live_judgment_detail_checks(
    state: MatchState,
    *,
    snapshot: Any,
    successful_player_ids: list[str],
    expected_basis: str,
    actual_basis: Any,
    expected_winner_ids: list[str],
    actual_winner_ids: list[str],
    actual_eligible_player_ids: list[str],
    actual_prevented_player_ids: list[str],
    scores: Any,
) -> list[RuleCheck]:
    player_snapshot = snapshot if isinstance(snapshot, dict) else {}
    score_map = scores if isinstance(scores, dict) else {}
    score_errors: dict[str, Any] = {}
    for player_id, raw in player_snapshot.items():
        detail = raw if isinstance(raw, dict) else {}
        base_score = int(detail.get("base_score", 0))
        score_bonus = int(detail.get("score_bonus", 0))
        total_score = int(detail.get("total_score", 0))
        event_score = int(score_map.get(player_id, 0))
        if base_score + score_bonus != total_score or event_score != total_score:
            score_errors[player_id] = {
                "base_score": base_score,
                "score_bonus": score_bonus,
                "total_score": total_score,
                "event_score": event_score,
            }
    expected_rule_prevented = [
        player_id
        for player_id in expected_winner_ids
        if len(expected_winner_ids) == 2
        and int(player_snapshot.get(player_id, {}).get("success_live_count_before", 0))
        >= 2
    ]
    expected_effect_prevented = [
        player_id
        for player_id in expected_winner_ids
        if player_id in state.effect_blocked_live_placement_player_ids
    ]
    expected_prevented = list(
        dict.fromkeys([*expected_rule_prevented, *expected_effect_prevented])
    )
    expected_eligible = [
        player_id
        for player_id in expected_winner_ids
        if player_id not in expected_prevented
    ]
    return [
        RuleCheck(
            check_id="live_score_components",
            verdict="pass" if not score_errors else "fail",
            summary_zh=(
                "各玩家 Live 总分等于基础分与应援/技能加分之和。"
                if not score_errors
                else "Live 总分的基础分、加分或事件快照不一致。"
            ),
            rule_refs=("8.4.2", "8.4.2.1"),
            evidence={"successful_player_ids": successful_player_ids, "errors": score_errors},
        ),
        RuleCheck(
            check_id="live_judgment_basis_and_winners",
            verdict=(
                "pass"
                if actual_basis == expected_basis
                and actual_winner_ids == expected_winner_ids
                else "fail"
            ),
            summary_zh=(
                "Live 存在性、总分和同分胜者判定符合官方顺序。"
                if actual_basis == expected_basis
                and actual_winner_ids == expected_winner_ids
                else "Live 判定基准或胜者与官方规则不一致。"
            ),
            rule_refs=("8.4.3", "8.4.6"),
            evidence={
                "expected_basis": expected_basis,
                "actual_basis": actual_basis,
                "expected_winner_ids": expected_winner_ids,
                "actual_winner_ids": actual_winner_ids,
                "scores": score_map,
            },
        ),
        RuleCheck(
            check_id="success_live_placement_eligibility",
            verdict=(
                "pass"
                if actual_prevented_player_ids == expected_prevented
                and actual_eligible_player_ids == expected_eligible
                else "fail"
            ),
            summary_zh=(
                "Live 胜利与成功 Live 移动资格已分离，Match Point 例外正确。"
                if actual_prevented_player_ids == expected_prevented
                and actual_eligible_player_ids == expected_eligible
                else "成功 Live 移动资格未正确应用 Match Point 或卡牌效果。"
            ),
            rule_refs=("8.4.7", "8.4.7.1", "1.3.1"),
            evidence={
                "expected_eligible_player_ids": expected_eligible,
                "actual_eligible_player_ids": actual_eligible_player_ids,
                "expected_prevented_player_ids": expected_prevented,
                "actual_prevented_player_ids": actual_prevented_player_ids,
            },
        ),
    ]


def _event(
    events: list[GameEvent],
    event_type: str,
    player_id: str | None = None,
    **data: object,
) -> GameEvent | None:
    return next(
        (
            event
            for event in events
            if event.event_type == event_type
            and (player_id is None or event.player_id == player_id)
            and all(event.data.get(key) == value for key, value in data.items())
        ),
        None,
    )


def verdict_counts(checks: list[RuleCheck]) -> dict[str, int]:
    return dict(Counter(check.verdict for check in checks))
