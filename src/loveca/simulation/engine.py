"""Deterministic first-turn rules engine for the visual debugger."""

from __future__ import annotations

import hashlib
import random
from collections import Counter
from typing import Any

from loveca.simulation.models import (
    ActionRequest,
    ActionResult,
    GameEvent,
    LegalAction,
    LivePerformanceResult,
    MatchState,
    PendingChoice,
)


class RuleEngineError(RuntimeError):
    """Base error for match rule failures."""


class IllegalActionError(RuleEngineError):
    """Raised when an action is not legal for the current state."""


class StaleRevisionError(RuleEngineError):
    """Raised when a client submits an action for an old state revision."""


def apply_action(state: MatchState, action: ActionRequest) -> ActionResult:
    if action.expected_revision != state.revision:
        raise StaleRevisionError(
            f"expected revision {action.expected_revision}, current revision is "
            f"{state.revision}"
        )
    if state.phase == "complete":
        raise IllegalActionError("the first-Live validation slice is complete")

    next_state = state.model_copy(deep=True)
    events: list[GameEvent] = []
    handlers = {
        "choose_first_player": _choose_first_player,
        "submit_mulligan": _submit_mulligan,
        "advance_phase": _advance_phase,
        "play_member": _play_member,
        "end_main_phase": _end_main_phase,
        "set_live_cards": _set_live_cards,
        "resolve_live_requirements": _resolve_live_requirements,
        "manual_adjustment": _manual_adjustment,
    }
    handlers[action.action_type](next_state, action, events)
    next_state.revision += 1
    return ActionResult(
        state=next_state,
        events=events,
        legal_actions=generate_legal_actions(next_state),
    )


def generate_legal_actions(state: MatchState) -> list[LegalAction]:
    if state.phase == "complete":
        return []
    actions: list[LegalAction] = []
    if state.phase == "setup_choose_first":
        actions.append(
            LegalAction(
                action_type="choose_first_player",
                label_zh="选择先攻玩家",
                label_ja="先攻プレイヤーを選ぶ",
                options={"player_ids": list(state.players)},
            )
        )
    elif state.pending_choice is not None:
        if state.pending_choice.choice_type == "mulligan":
            actions.append(
                LegalAction(
                    action_type="submit_mulligan",
                    player_id=state.pending_choice.player_id,
                    label_zh="提交调度选择",
                    label_ja="引き直しを確定",
                    options=state.pending_choice.options,
                )
            )
        else:
            actions.append(
                LegalAction(
                    action_type="resolve_live_requirements",
                    player_id=state.pending_choice.player_id,
                    label_zh="提交 Live 判定选择",
                    label_ja="ライブ判定の選択を確定",
                    options=state.pending_choice.options,
                )
            )
    elif state.phase.endswith(("_active", "_energy", "_draw")):
        actions.append(
            LegalAction(
                action_type="advance_phase",
                player_id=state.active_player_id,
                label_zh="执行并进入下一阶段",
                label_ja="処理して次のフェイズへ",
            )
        )
    elif state.phase in {
        "performance_first",
        "performance_second",
        "yell_first",
        "yell_second",
        "live_judgment",
    }:
        labels = {
            "performance_first": ("先攻 Live 公开", "先攻ライブを公開"),
            "performance_second": ("后攻 Live 公开", "後攻ライブを公開"),
            "yell_first": ("执行先攻应援", "先攻のエールを実行"),
            "yell_second": ("执行后攻应援", "後攻のエールを実行"),
            "live_judgment": ("执行 Live 胜负判定", "ライブ勝敗判定を実行"),
        }
        label_zh, label_ja = labels[state.phase]
        actions.append(
            LegalAction(
                action_type="advance_phase",
                player_id=state.active_player_id,
                label_zh=label_zh,
                label_ja=label_ja,
            )
        )
    elif state.phase.endswith("_main"):
        player = state.players[state.active_player_id or ""]
        empty_slots = [
            slot for slot, instance_id in player.member_area.items() if instance_id is None
        ]
        active_energy = [
            instance_id
            for instance_id in player.energy_area
            if state.cards[instance_id].orientation == "active"
        ]
        playable = [
            instance_id
            for instance_id in player.hand
            if state.cards[instance_id].card.card_type == "member"
            and (state.cards[instance_id].card.cost or 0) <= len(active_energy)
        ]
        if empty_slots and playable:
            actions.append(
                LegalAction(
                    action_type="play_member",
                    player_id=player.player_id,
                    label_zh="登场 Member",
                    label_ja="メンバーをプレイ",
                    options={
                        "card_instance_ids": playable,
                        "slots": empty_slots,
                        "active_energy_instance_ids": active_energy,
                    },
                )
            )
        actions.append(
            LegalAction(
                action_type="end_main_phase",
                player_id=player.player_id,
                label_zh="结束主要阶段",
                label_ja="メインフェイズを終了",
            )
        )
    elif state.phase in {"live_set_first", "live_set_second"}:
        player = state.players[state.active_player_id or ""]
        actions.append(
            LegalAction(
                action_type="set_live_cards",
                player_id=player.player_id,
                label_zh="设置 Live 卡",
                label_ja="ライブカードをセット",
                options={
                    "hand_instance_ids": list(player.hand),
                    "maximum": 3,
                },
            )
        )

    actions.append(
        LegalAction(
            action_type="manual_adjustment",
            player_id=state.active_player_id,
            label_zh="人工规则调整",
            label_ja="手動調整",
            options={
                "adjustment_types": [
                    "move_card",
                    "draw_card",
                    "discard_card",
                    "ready_energy",
                    "pay_energy",
                    "modify_score",
                    "modify_heart",
                    "modify_blade",
                    "set_flag",
                    "clear_flag",
                ]
            },
        )
    )
    return actions


def _choose_first_player(
    state: MatchState,
    action: ActionRequest,
    events: list[GameEvent],
) -> None:
    if state.phase != "setup_choose_first":
        raise IllegalActionError("first player can only be chosen during setup")
    first_player_id = action.payload.get("first_player_id")
    if first_player_id not in state.players:
        raise IllegalActionError("first_player_id must identify a match player")
    second_player_id = next(
        player_id for player_id in state.players if player_id != first_player_id
    )
    state.first_player_id = first_player_id
    state.second_player_id = second_player_id
    for player_id, player in state.players.items():
        player.main_deck = _deterministic_shuffle(
            player.main_deck,
            state.seed,
            f"initial-main:{player_id}",
        )
        _draw(state, player_id, 6, events, reason="opening_hand")
    state.phase = "setup_mulligan_first"
    state.active_player_id = first_player_id
    state.pending_choice = PendingChoice(
        choice_type="mulligan",
        player_id=first_player_id,
        message_ja="引き直すカードを選んでください。",
        message_zh="请选择需要调度的手牌。",
        options={"hand_instance_ids": list(state.players[first_player_id].hand)},
    )
    events.append(
        GameEvent(
            event_type="first_player_chosen",
            player_id=first_player_id,
            data={"second_player_id": second_player_id},
            source="player",
        )
    )


def _submit_mulligan(
    state: MatchState,
    action: ActionRequest,
    events: list[GameEvent],
) -> None:
    pending = state.pending_choice
    if pending is None or pending.choice_type != "mulligan":
        raise IllegalActionError("there is no pending mulligan")
    if action.player_id != pending.player_id:
        raise IllegalActionError("only the pending player may submit mulligan")
    player = state.players[pending.player_id]
    selected = action.payload.get("card_instance_ids", [])
    if not isinstance(selected, list) or len(selected) != len(set(selected)):
        raise IllegalActionError("mulligan card_instance_ids must be a unique list")
    if any(instance_id not in player.hand for instance_id in selected):
        raise IllegalActionError("mulligan may only select cards from the player's hand")

    for instance_id in selected:
        player.hand.remove(instance_id)
    _draw(state, player.player_id, len(selected), events, reason="mulligan_draw")
    if selected:
        player.main_deck.extend(selected)
        player.main_deck = _deterministic_shuffle(
            player.main_deck,
            state.seed,
            f"mulligan:{player.player_id}",
        )
    events.append(
        GameEvent(
            event_type="mulligan_completed",
            player_id=player.player_id,
            data={"replaced_count": len(selected)},
            source="player",
        )
    )

    if player.player_id == state.first_player_id:
        second_player_id = state.second_player_id or ""
        state.phase = "setup_mulligan_second"
        state.active_player_id = second_player_id
        state.pending_choice = PendingChoice(
            choice_type="mulligan",
            player_id=second_player_id,
            message_ja="引き直すカードを選んでください。",
            message_zh="请选择需要调度的手牌。",
            options={
                "hand_instance_ids": list(state.players[second_player_id].hand)
            },
        )
        return

    state.pending_choice = None
    for player_id in (state.first_player_id, state.second_player_id):
        _move_energy_to_area(state, player_id or "", 3, events, "initial_energy")
    state.phase = "first_active"
    state.active_player_id = state.first_player_id


def _advance_phase(
    state: MatchState,
    action: ActionRequest,
    events: list[GameEvent],
) -> None:
    if action.player_id not in {None, state.active_player_id}:
        raise IllegalActionError("advance_phase belongs to the active player")
    transitions = {
        "first_active": "first_energy",
        "first_energy": "first_draw",
        "first_draw": "first_main",
        "second_active": "second_energy",
        "second_energy": "second_draw",
        "second_draw": "second_main",
    }
    if state.phase in {"performance_first", "performance_second"}:
        player_id = state.active_player_id or ""
        _reveal_current_live_cards(state, events)
        state.phase = (
            "yell_first" if state.phase == "performance_first" else "yell_second"
        )
        events.append(
            GameEvent(
                event_type="phase_changed",
                player_id=player_id,
                data={"phase": state.phase},
            )
        )
        return
    if state.phase in {"yell_first", "yell_second"}:
        _run_current_yell(state, events)
        if state.pending_choice is None:
            _continue_after_yell(state, events)
        return
    if state.phase == "live_judgment":
        _begin_live_judgment(state, events)
        return
    next_phase = transitions.get(state.phase)
    if next_phase is None:
        raise IllegalActionError("advance_phase is not legal in the current phase")
    player_id = state.active_player_id or ""
    if state.phase.endswith("_active"):
        _ready_player_cards(state, player_id, events)
    elif state.phase.endswith("_energy"):
        _move_energy_to_area(state, player_id, 1, events, "energy_phase")
    elif state.phase.endswith("_draw"):
        _draw(state, player_id, 1, events, reason="draw_phase")
    state.phase = next_phase  # type: ignore[assignment]
    events.append(
        GameEvent(
            event_type="phase_changed",
            player_id=player_id,
            data={"phase": next_phase},
        )
    )


def _play_member(
    state: MatchState,
    action: ActionRequest,
    events: list[GameEvent],
) -> None:
    if state.phase not in {"first_main", "second_main"}:
        raise IllegalActionError("Members may only be played during a main phase")
    player_id = state.active_player_id or ""
    if action.player_id != player_id:
        raise IllegalActionError("only the active player may play a Member")
    player = state.players[player_id]
    instance_id = action.payload.get("card_instance_id")
    slot = action.payload.get("slot")
    energy_ids = action.payload.get("energy_instance_ids", [])
    if instance_id not in player.hand:
        raise IllegalActionError("the selected Member is not in hand")
    card = state.cards[instance_id]
    if card.card.card_type != "member":
        raise IllegalActionError("only Member cards can be played")
    if slot not in player.member_area or player.member_area[slot] is not None:
        raise IllegalActionError("the selected Member Area slot is not empty")
    cost = card.card.cost or 0
    if (
        not isinstance(energy_ids, list)
        or len(energy_ids) != cost
        or len(energy_ids) != len(set(energy_ids))
    ):
        raise IllegalActionError(f"playing this Member requires exactly {cost} Energy")
    for energy_id in energy_ids:
        if energy_id not in player.energy_area:
            raise IllegalActionError("payment Energy must be in the Energy Area")
        if state.cards[energy_id].orientation != "active":
            raise IllegalActionError("payment Energy must be Active")
    for energy_id in energy_ids:
        state.cards[energy_id].orientation = "wait"
    player.hand.remove(instance_id)
    player.member_area[slot] = instance_id
    card.face_up = True
    card.orientation = "active"
    events.append(
        GameEvent(
            event_type="member_played",
            player_id=player_id,
            data={
                "card_instance_id": instance_id,
                "slot": slot,
                "energy_instance_ids": energy_ids,
            },
            source="player",
        )
    )


def _end_main_phase(
    state: MatchState,
    action: ActionRequest,
    events: list[GameEvent],
) -> None:
    player_id = state.active_player_id
    if action.player_id != player_id:
        raise IllegalActionError("only the active player may end the main phase")
    if state.phase == "first_main":
        state.phase = "second_active"
        state.active_player_id = state.second_player_id
    elif state.phase == "second_main":
        state.phase = "live_set_first"
        state.active_player_id = state.first_player_id
    else:
        raise IllegalActionError("end_main_phase is not legal now")
    events.append(
        GameEvent(
            event_type="phase_changed",
            player_id=state.active_player_id,
            data={"phase": state.phase},
        )
    )


def _set_live_cards(
    state: MatchState,
    action: ActionRequest,
    events: list[GameEvent],
) -> None:
    expected_phase = (
        "live_set_first"
        if action.player_id == state.first_player_id
        else "live_set_second"
    )
    if state.phase != expected_phase or action.player_id != state.active_player_id:
        raise IllegalActionError("this player cannot set Live cards now")
    player = state.players[action.player_id or ""]
    selected = action.payload.get("card_instance_ids", [])
    if (
        not isinstance(selected, list)
        or len(selected) > 3
        or len(selected) != len(set(selected))
    ):
        raise IllegalActionError("Live set must contain zero to three unique cards")
    if any(instance_id not in player.hand for instance_id in selected):
        raise IllegalActionError("Live set cards must come from hand")
    for instance_id in selected:
        player.hand.remove(instance_id)
        player.live_area.append(instance_id)
        state.cards[instance_id].face_up = False
    events.append(
        GameEvent(
            event_type="live_cards_set",
            player_id=player.player_id,
            data={"count": len(selected)},
            source="player",
        )
    )
    if state.phase == "live_set_first":
        state.phase = "live_set_second"
        state.active_player_id = state.second_player_id
        return
    state.phase = "performance_first"
    state.active_player_id = state.first_player_id


def _resolve_live_requirements(
    state: MatchState,
    action: ActionRequest,
    events: list[GameEvent],
) -> None:
    pending = state.pending_choice
    if pending is None or action.player_id != pending.player_id:
        raise IllegalActionError("there is no matching pending Live choice")
    if pending.choice_type == "live_requirements":
        live_ids = pending.options["live_instance_ids"]
        order = action.payload.get("live_instance_ids", live_ids)
        if sorted(order) != sorted(live_ids):
            raise IllegalActionError("Live resolution order must include each Live once")
        _apply_live_requirements(state, pending.player_id, order, events)
        state.pending_choice = None
        _continue_after_yell(state, events)
        return
    if pending.choice_type == "success_live":
        choices = pending.options["card_instance_ids"]
        selected = action.payload.get("success_live_instance_id")
        if selected not in choices:
            raise IllegalActionError("success Live choice must select an offered card")
        player = state.players[pending.player_id]
        player.live_area.remove(selected)
        player.success_live_area.append(selected)
        events.append(
            GameEvent(
                event_type="success_live_selected",
                player_id=player.player_id,
                data={"card_instance_id": selected},
                source="player",
            )
        )
        remaining = list(pending.options.get("remaining_player_ids", []))
        state.pending_choice = None
        _finish_judgment_choices(state, remaining, events)
        return
    raise IllegalActionError("unsupported pending Live choice")


def _manual_adjustment(
    state: MatchState,
    action: ActionRequest,
    events: list[GameEvent],
) -> None:
    adjustments = action.payload.get("adjustments")
    if not isinstance(adjustments, list) or not adjustments:
        raise IllegalActionError("manual_adjustment requires at least one adjustment")
    if action.payload.get("requires_confirmation") and not action.payload.get(
        "confirmed_by"
    ):
        raise IllegalActionError("confirmed_by is required for confirmed adjustments")
    for adjustment in adjustments:
        if not isinstance(adjustment, dict):
            raise IllegalActionError("manual adjustment entries must be objects")
        _apply_manual_entry(state, adjustment)
    events.append(
        GameEvent(
            event_type="manual_adjustment_applied",
            player_id=action.player_id,
            data={
                "reason": action.payload.get("reason"),
                "adjustments": adjustments,
                "confirmed_by": action.payload.get("confirmed_by"),
            },
            source="manual",
        )
    )


def _reveal_current_live_cards(
    state: MatchState,
    events: list[GameEvent],
) -> None:
    player_id = state.active_player_id or ""
    player = state.players[player_id]
    player.live_result = LivePerformanceResult()
    revealed_live_ids: list[str] = []
    discarded_ids: list[str] = []
    for instance_id in list(player.live_area):
        card = state.cards[instance_id]
        card.face_up = True
        if card.card.card_type == "live":
            revealed_live_ids.append(instance_id)
        else:
            player.live_area.remove(instance_id)
            player.waiting_room.append(instance_id)
            discarded_ids.append(instance_id)
    events.append(
        GameEvent(
            event_type="live_cards_revealed",
            player_id=player_id,
            data={
                "live_instance_ids": revealed_live_ids,
                "non_live_discarded_instance_ids": discarded_ids,
            },
        )
    )
    if not player.live_area:
        player.live_result = LivePerformanceResult(requirements_satisfied=False)


def _run_current_yell(
    state: MatchState,
    events: list[GameEvent],
) -> None:
    player_id = state.active_player_id or ""
    player = state.players[player_id]
    if not player.live_area:
        events.append(GameEvent(event_type="yell_skipped", player_id=player_id))
        return

    blade_count = player.manual_blade_modifier
    member_hearts: Counter[str] = Counter()
    for instance_id in player.member_area.values():
        if instance_id is None:
            continue
        member = state.cards[instance_id]
        member_hearts.update(member.card.basic_hearts)
        if member.orientation == "active":
            blade_count += member.card.blade or 0

    revealed: list[str] = []
    yell_hearts: Counter[str] = Counter()
    all_color_hearts = 0
    draw_count = 0
    score_bonus = player.manual_score_modifier
    special_results: list[dict[str, Any]] = []
    for _ in range(max(0, blade_count)):
        if not player.main_deck:
            break
        instance_id = player.main_deck.pop(0)
        player.resolution_area.append(instance_id)
        state.cards[instance_id].face_up = True
        revealed.append(instance_id)
        definition = state.cards[instance_id].card
        if definition.blade_heart_color_slot:
            yell_hearts[definition.blade_heart_color_slot] += 1
        for special in definition.special_blade_hearts:
            value = special.value or 0
            special_results.append(
                {
                    "card_instance_id": instance_id,
                    "effect_type": special.effect_type,
                    "value": value,
                    "source_alt": special.source_alt,
                }
            )
            if special.effect_type == "all_color":
                all_color_hearts += value
            elif special.effect_type == "draw":
                draw_count += value
            elif special.effect_type == "score":
                score_bonus += value
    if draw_count:
        _draw(state, player_id, draw_count, events, reason="special_blade_heart_draw")

    hearts = Counter(member_hearts)
    hearts.update(player.manual_heart_modifiers)
    hearts.update(yell_hearts)
    player.live_result = LivePerformanceResult(
        blade_count=blade_count,
        revealed_instance_ids=revealed,
        member_hearts=dict(sorted(member_hearts.items())),
        manual_hearts=dict(sorted(player.manual_heart_modifiers.items())),
        yell_hearts=dict(sorted(yell_hearts.items())),
        available_hearts=dict(sorted(hearts.items())),
        all_color_hearts=all_color_hearts,
        special_blade_heart_results=special_results,
        draw_count=draw_count,
        score_bonus=score_bonus,
    )
    events.append(
        GameEvent(
            event_type="yell_completed",
            player_id=player_id,
            data={
                "blade_count": blade_count,
                "revealed_instance_ids": revealed,
                "member_hearts": dict(member_hearts),
                "manual_hearts": dict(player.manual_heart_modifiers),
                "yell_hearts": dict(yell_hearts),
                "live_owned_hearts": dict(hearts),
                "all_color_hearts": all_color_hearts,
                "draw_count": draw_count,
                "score_bonus": score_bonus,
                "special_blade_heart_results": special_results,
            },
        )
    )
    if len(player.live_area) > 1 or all_color_hearts > 0:
        state.pending_choice = PendingChoice(
            choice_type="live_requirements",
            player_id=player_id,
            message_ja="必要ハートを確認するライブの順番を選んでください。",
            message_zh="请选择 Live 所需 Heart 的判定顺序。",
            options={"live_instance_ids": list(player.live_area)},
        )
        return
    _apply_live_requirements(state, player_id, list(player.live_area), events)


def _apply_live_requirements(
    state: MatchState,
    player_id: str,
    live_ids: list[str],
    events: list[GameEvent],
) -> None:
    player = state.players[player_id]
    available = Counter(player.live_result.available_hearts)
    wild = player.live_result.all_color_hearts
    satisfied = True
    allocations: list[dict[str, Any]] = []
    for live_id in live_ids:
        requirements = state.cards[live_id].card.required_hearts
        consumed: Counter[str] = Counter()
        missing: Counter[str] = Counter()
        wild_used = 0
        for color, amount in sorted(requirements.items()):
            if color == "heart0":
                continue
            used = min(available[color], amount)
            available[color] -= used
            consumed[color] += used
            deficit = amount - used
            wild_for_color = min(wild, deficit)
            wild -= wild_for_color
            wild_used += wild_for_color
            deficit -= wild_for_color
            if deficit:
                missing[color] += deficit
                satisfied = False
                break
        generic = requirements.get("heart0", 0) if not missing else 0
        while generic:
            for color in sorted(available):
                used = min(available[color], generic)
                available[color] -= used
                consumed[color] += used
                generic -= used
                if generic == 0:
                    break
            if generic == 0:
                break
            wild_for_generic = min(wild, generic)
            wild -= wild_for_generic
            wild_used += wild_for_generic
            generic -= wild_for_generic
            if generic:
                missing["heart0"] += generic
                satisfied = False
                break
        allocations.append(
            {
                "live_instance_id": live_id,
                "required_hearts": dict(sorted(requirements.items())),
                "consumed_hearts": dict(sorted(consumed.items())),
                "all_color_hearts_used": wild_used,
                "missing_hearts": dict(sorted(missing.items())),
                "remaining_hearts": dict(
                    sorted(
                        (color, amount)
                        for color, amount in available.items()
                        if amount
                    )
                ),
                "remaining_all_color_hearts": wild,
                "satisfied": not missing,
            }
        )
        if missing:
            break
    player.live_result.live_allocations = allocations
    player.live_result.requirements_satisfied = satisfied
    if not satisfied:
        for instance_id in list(player.live_area):
            player.live_area.remove(instance_id)
            player.waiting_room.append(instance_id)
    else:
        player.live_result.base_score = sum(
            state.cards[instance_id].card.score or 0 for instance_id in player.live_area
        )
        player.live_result.total_score = (
            player.live_result.base_score + player.live_result.score_bonus
        )
    events.append(
        GameEvent(
            event_type="live_requirements_resolved",
            player_id=player_id,
            data={
                "ordered_live_instance_ids": live_ids,
                "satisfied": satisfied,
                "allocations": allocations,
                "base_score": player.live_result.base_score,
                "score_bonus": player.live_result.score_bonus,
                "total_score": player.live_result.total_score,
            },
            source="player",
        )
    )


def _continue_after_yell(
    state: MatchState,
    events: list[GameEvent],
) -> None:
    if state.phase == "yell_first":
        state.phase = "performance_second"
        state.active_player_id = state.second_player_id
        events.append(
            GameEvent(
                event_type="phase_changed",
                player_id=state.active_player_id,
                data={"phase": state.phase},
            )
        )
        return
    if state.phase == "yell_second":
        state.phase = "live_judgment"
        state.active_player_id = None
        events.append(
            GameEvent(
                event_type="phase_changed",
                data={"phase": state.phase},
            )
        )


def _begin_live_judgment(
    state: MatchState,
    events: list[GameEvent],
) -> None:
    first_id = state.first_player_id or ""
    second_id = state.second_player_id or ""
    first = state.players[first_id]
    second = state.players[second_id]
    if not first.live_area and not second.live_area:
        winners: list[str] = []
    elif first.live_area and not second.live_area:
        winners = [first_id]
    elif second.live_area and not first.live_area:
        winners = [second_id]
    elif first.live_result.total_score > second.live_result.total_score:
        winners = [first_id]
    elif second.live_result.total_score > first.live_result.total_score:
        winners = [second_id]
    else:
        winners = [first_id, second_id]
    state.live_winner_ids = winners
    if not first.live_area and not second.live_area:
        basis = "no_successful_live"
    elif bool(first.live_area) != bool(second.live_area):
        basis = "only_one_player_has_successful_live"
    elif first.live_result.total_score == second.live_result.total_score:
        basis = "equal_total_score"
    else:
        basis = "higher_total_score"
    state.live_judgment_summary = {
        "basis": basis,
        "winner_ids": winners,
        "players": {
            first_id: {
                "player_id": first_id,
                "successful_live_instance_ids": list(first.live_area),
                "requirements_satisfied": first.live_result.requirements_satisfied,
                "base_score": first.live_result.base_score,
                "score_bonus": first.live_result.score_bonus,
                "total_score": first.live_result.total_score,
            },
            second_id: {
                "player_id": second_id,
                "successful_live_instance_ids": list(second.live_area),
                "requirements_satisfied": second.live_result.requirements_satisfied,
                "base_score": second.live_result.base_score,
                "score_bonus": second.live_result.score_bonus,
                "total_score": second.live_result.total_score,
            },
        },
    }
    events.append(
        GameEvent(
            event_type="live_judgment_started",
            data={
                "basis": basis,
                "winner_ids": winners,
                "scores": {
                    first_id: first.live_result.total_score,
                    second_id: second.live_result.total_score,
                },
            },
        )
    )
    _finish_judgment_choices(state, list(winners), events)


def _finish_judgment_choices(
    state: MatchState,
    remaining_winners: list[str],
    events: list[GameEvent],
) -> None:
    while remaining_winners:
        player_id = remaining_winners.pop(0)
        player = state.players[player_id]
        if (
            len(state.live_winner_ids) == 2
            and len(player.live_area) == 2
        ):
            continue
        if len(player.live_area) == 1:
            selected = player.live_area.pop()
            player.success_live_area.append(selected)
            events.append(
                GameEvent(
                    event_type="success_live_selected",
                    player_id=player_id,
                    data={"card_instance_id": selected},
                )
            )
            continue
        if len(player.live_area) > 1:
            state.pending_choice = PendingChoice(
                choice_type="success_live",
                player_id=player_id,
                message_ja="成功ライブカード置き場に置くカードを選んでください。",
                message_zh="请选择移入成功 Live 区的卡。",
                options={
                    "card_instance_ids": list(player.live_area),
                    "remaining_player_ids": remaining_winners,
                },
            )
            state.active_player_id = player_id
            return
    _complete_first_live(state, events)


def _complete_first_live(
    state: MatchState,
    events: list[GameEvent],
) -> None:
    for player in state.players.values():
        for zone in (player.live_area, player.resolution_area):
            for instance_id in list(zone):
                zone.remove(instance_id)
                player.waiting_room.append(instance_id)
    state.pending_choice = None
    state.phase = "complete"
    state.active_player_id = None
    state.completed_reason = "live_judgment_completed"
    events.append(
        GameEvent(
            event_type="live_judgment_completed",
            data={"winner_ids": state.live_winner_ids},
        )
    )


def _apply_manual_entry(state: MatchState, adjustment: dict[str, Any]) -> None:
    adjustment_type = adjustment.get("adjustment_type")
    player_id = adjustment.get("target_player_id")
    if player_id not in state.players:
        raise IllegalActionError("manual adjustment target_player_id is invalid")
    player = state.players[player_id]
    if adjustment_type == "draw_card":
        amount = _positive_amount(adjustment)
        _draw(state, player_id, amount, [], reason="manual")
    elif adjustment_type == "discard_card":
        instance_id = adjustment.get("target_card_instance_id")
        if instance_id not in player.hand:
            raise IllegalActionError("manual discard target must be in hand")
        player.hand.remove(instance_id)
        player.waiting_room.append(instance_id)
    elif adjustment_type == "move_card":
        instance_id = adjustment.get("target_card_instance_id")
        to_zone = adjustment.get("to_zone")
        _manual_move_card(state, player_id, instance_id, to_zone)
    elif adjustment_type in {"ready_energy", "pay_energy"}:
        instance_id = adjustment.get("target_card_instance_id")
        if instance_id not in player.energy_area:
            raise IllegalActionError("manual Energy target must be in Energy Area")
        state.cards[instance_id].orientation = (
            "active" if adjustment_type == "ready_energy" else "wait"
        )
    elif adjustment_type == "modify_score":
        player.manual_score_modifier += _integer_amount(adjustment)
    elif adjustment_type == "modify_blade":
        player.manual_blade_modifier += _integer_amount(adjustment)
    elif adjustment_type == "modify_heart":
        color = adjustment.get("color_slot")
        if not isinstance(color, str):
            raise IllegalActionError("modify_heart requires color_slot")
        player.manual_heart_modifiers[color] = (
            player.manual_heart_modifiers.get(color, 0)
            + _integer_amount(adjustment)
        )
    elif adjustment_type in {"set_flag", "clear_flag"}:
        flag = adjustment.get("flag")
        if not isinstance(flag, str) or not flag:
            raise IllegalActionError("flag adjustment requires a flag name")
        if adjustment_type == "set_flag":
            player.flags[flag] = adjustment.get("value", True)
        else:
            player.flags.pop(flag, None)
    else:
        raise IllegalActionError(f"unsupported manual adjustment: {adjustment_type}")


def _manual_move_card(
    state: MatchState,
    player_id: str,
    instance_id: Any,
    to_zone: Any,
) -> None:
    if not isinstance(instance_id, str) or instance_id not in state.cards:
        raise IllegalActionError("manual move target card does not exist")
    if state.cards[instance_id].owner_id != player_id:
        raise IllegalActionError("manual move target must belong to target player")
    player = state.players[player_id]
    _remove_from_player_zones(player, instance_id)
    simple_zones = {
        "hand": player.hand,
        "main_deck": player.main_deck,
        "energy_deck": player.energy_deck,
        "energy_area": player.energy_area,
        "live_area": player.live_area,
        "waiting_room": player.waiting_room,
        "resolution_area": player.resolution_area,
        "success_live_area": player.success_live_area,
    }
    if to_zone in simple_zones:
        simple_zones[to_zone].append(instance_id)
        return
    if to_zone in {"member_left", "member_center", "member_right"}:
        slot = str(to_zone).removeprefix("member_")
        if player.member_area[slot] is not None:
            raise IllegalActionError("manual move Member Area slot is occupied")
        player.member_area[slot] = instance_id
        return
    raise IllegalActionError("manual move target zone is invalid")


def _remove_from_player_zones(player: Any, instance_id: str) -> None:
    for zone in (
        player.main_deck,
        player.energy_deck,
        player.hand,
        player.energy_area,
        player.live_area,
        player.waiting_room,
        player.resolution_area,
        player.success_live_area,
    ):
        if instance_id in zone:
            zone.remove(instance_id)
    for slot, current in player.member_area.items():
        if current == instance_id:
            player.member_area[slot] = None


def _draw(
    state: MatchState,
    player_id: str,
    amount: int,
    events: list[GameEvent],
    *,
    reason: str,
) -> None:
    player = state.players[player_id]
    drawn: list[str] = []
    for _ in range(amount):
        if not player.main_deck:
            break
        instance_id = player.main_deck.pop(0)
        player.hand.append(instance_id)
        state.cards[instance_id].face_up = True
        drawn.append(instance_id)
    if drawn:
        events.append(
            GameEvent(
                event_type="cards_drawn",
                player_id=player_id,
                data={"instance_ids": drawn, "reason": reason},
            )
        )


def _move_energy_to_area(
    state: MatchState,
    player_id: str,
    amount: int,
    events: list[GameEvent],
    reason: str,
) -> None:
    player = state.players[player_id]
    moved: list[str] = []
    for _ in range(amount):
        if not player.energy_deck:
            break
        instance_id = player.energy_deck.pop(0)
        player.energy_area.append(instance_id)
        state.cards[instance_id].face_up = True
        state.cards[instance_id].orientation = "active"
        moved.append(instance_id)
    events.append(
        GameEvent(
            event_type="energy_added",
            player_id=player_id,
            data={"instance_ids": moved, "reason": reason},
        )
    )


def _ready_player_cards(
    state: MatchState,
    player_id: str,
    events: list[GameEvent],
) -> None:
    player = state.players[player_id]
    ready_ids = [
        *player.energy_area,
        *[instance_id for instance_id in player.member_area.values() if instance_id],
    ]
    for instance_id in ready_ids:
        state.cards[instance_id].orientation = "active"
    events.append(
        GameEvent(
            event_type="cards_readied",
            player_id=player_id,
            data={"instance_ids": ready_ids},
        )
    )


def _deterministic_shuffle(items: list[str], seed: int, salt: str) -> list[str]:
    digest = hashlib.sha256(f"{seed}:{salt}".encode()).digest()
    derived_seed = int.from_bytes(digest[:8], "big")
    shuffled = list(items)
    random.Random(derived_seed).shuffle(shuffled)
    return shuffled


def _positive_amount(adjustment: dict[str, Any]) -> int:
    amount = adjustment.get("amount")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise IllegalActionError("manual adjustment amount must be positive")
    return amount


def _integer_amount(adjustment: dict[str, Any]) -> int:
    amount = adjustment.get("amount")
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise IllegalActionError("manual adjustment amount must be an integer")
    return amount
