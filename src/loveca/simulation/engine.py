"""Deterministic first-turn rules engine for the visual debugger."""

from __future__ import annotations

import hashlib
import random
from collections import Counter
from typing import Any

from loveca.simulation.models import (
    ActionRequest,
    ActionResult,
    GameResult,
    GameEvent,
    LegalAction,
    LivePerformanceResult,
    EffectInvocation,
    EffectUsage,
    ManualModifier,
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
        raise IllegalActionError("the match is complete")
    if state.pending_effects and action.action_type not in {
        "resolve_effect",
        "manual_adjustment",
        "resolve_manual_inspection",
    }:
        raise IllegalActionError("a pending card effect must be resolved first")

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
        "start_next_turn": _start_next_turn,
        "activate_effect": _activate_effect,
        "resolve_effect": _resolve_effect,
        "resolve_manual_inspection": _resolve_manual_inspection,
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
    if (
        state.pending_choice is not None
        and state.pending_choice.choice_type == "manual_card_selection"
    ):
        return [
            LegalAction(
                action_type="resolve_manual_inspection",
                player_id=state.pending_choice.player_id,
                label_zh="提交牌堆检查结果",
                label_ja="確認したカードの処理を確定",
                options=state.pending_choice.options,
            )
        ]
    if state.pending_effects:
        return _pending_effect_legal_actions(state)
    if state.phase == "turn_complete":
        return [
            LegalAction(
                action_type="start_next_turn",
                player_id=state.next_first_player_id,
                label_zh="开始下一回合",
                label_ja="次のターンを開始",
                options={
                    "turn_number": state.turn_number + 1,
                    "first_player_id": state.next_first_player_id,
                },
            )
        ]
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
        elif state.pending_choice.choice_type in {
            "live_requirements",
            "success_live",
        }:
            actions.append(
                LegalAction(
                    action_type="resolve_live_requirements",
                    player_id=state.pending_choice.player_id,
                    label_zh="提交 Live 判定选择",
                    label_ja="ライブ判定の選択を確定",
                    options=state.pending_choice.options,
                )
            )
        else:
            actions.append(
                LegalAction(
                    action_type="resolve_manual_inspection",
                    player_id=state.pending_choice.player_id,
                    label_zh="提交牌堆检查结果",
                    label_ja="確認したカードの処理を確定",
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
        active_energy = [
            instance_id
            for instance_id in player.energy_area
            if state.cards[instance_id].orientation == "active"
        ]
        placements = _legal_member_placements(
            state,
            player.player_id,
            len(active_energy),
        )
        if placements:
            actions.append(
                LegalAction(
                    action_type="play_member",
                    player_id=player.player_id,
                    label_zh="登场 Member",
                    label_ja="メンバーをプレイ",
                    options={
                        "placements": placements,
                        "active_energy_instance_ids": active_energy,
                    },
                )
            )
        activations = _legal_effect_activations(state, player.player_id)
        if activations:
            actions.append(
                LegalAction(
                    action_type="activate_effect",
                    player_id=player.player_id,
                    label_zh="发动技能",
                    label_ja="能力を起動",
                    options={"activations": activations},
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
                    "inspect_top_cards",
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
        for instance_id in selected:
            state.cards[instance_id].face_up = False
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
        if state.players[player_id].live_area:
            live_sources = [
                instance_id
                for instance_id in state.players[player_id].member_area.values()
                if instance_id is not None
            ]
            live_sources.extend(state.players[player_id].live_area)
            _queue_triggered_effects(
                state,
                "live_started",
                events,
                source_instance_ids=live_sources,
                trigger_data={
                    "turn_number": state.turn_number,
                    "performance_player_id": player_id,
                },
            )
            _resolve_automatic_effects(state, events)
        next_phase = (
            "yell_first" if state.phase == "performance_first" else "yell_second"
        )
        if state.pending_effects:
            return
        state.phase = next_phase
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
    use_baton_touch = action.payload.get("use_baton_touch", False)
    if instance_id not in player.hand:
        raise IllegalActionError("the selected Member is not in hand")
    card = state.cards[instance_id]
    if card.card.card_type != "member":
        raise IllegalActionError("only Member cards can be played")
    if slot not in player.member_area:
        raise IllegalActionError("the selected Member Area slot is invalid")
    if slot in player.member_areas_entered_this_turn:
        raise IllegalActionError(
            "the selected Member Area received a Member from outside the Stage this turn"
        )
    if not isinstance(use_baton_touch, bool):
        raise IllegalActionError("use_baton_touch must be a boolean")
    replaced_instance_id = player.member_area[slot]
    cost = card.card.cost or 0
    payment_cost = cost
    replaced_cost = 0
    if use_baton_touch:
        if replaced_instance_id is None:
            raise IllegalActionError("Baton Touch requires a Member in the selected area")
        if cost <= 0:
            raise IllegalActionError(
                "Baton Touch requires at least one unpaid Energy cost"
            )
        replaced_cost = state.cards[replaced_instance_id].card.cost or 0
        payment_cost = max(0, cost - replaced_cost)
    if (
        not isinstance(energy_ids, list)
        or len(energy_ids) != payment_cost
        or len(energy_ids) != len(set(energy_ids))
    ):
        raise IllegalActionError(
            f"playing this Member requires exactly {payment_cost} Energy"
        )
    for energy_id in energy_ids:
        if energy_id not in player.energy_area:
            raise IllegalActionError("payment Energy must be in the Energy Area")
        if state.cards[energy_id].orientation != "active":
            raise IllegalActionError("payment Energy must be Active")
    for energy_id in energy_ids:
        state.cards[energy_id].orientation = "wait"
    if use_baton_touch and replaced_instance_id is not None:
        player.member_area[slot] = None
        player.waiting_room.append(replaced_instance_id)
        events.append(
            GameEvent(
                event_type="baton_touch_performed",
                player_id=player_id,
                data={
                    "replaced_card_instance_id": replaced_instance_id,
                    "replaced_member_cost": replaced_cost,
                    "new_member_cost": cost,
                    "payment_cost": payment_cost,
                    "slot": slot,
                },
                source="player",
            )
        )
    player.hand.remove(instance_id)
    player.member_area[slot] = instance_id
    if slot not in player.member_areas_entered_this_turn:
        player.member_areas_entered_this_turn.append(slot)
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
                "payment_cost": payment_cost,
                "baton_touch": use_baton_touch,
                "replaced_card_instance_id": replaced_instance_id,
            },
            source="player",
        )
    )
    if replaced_instance_id is not None and not use_baton_touch:
        player.waiting_room.append(replaced_instance_id)
        events.append(
            GameEvent(
                event_type="duplicate_member_resolved",
                player_id=player_id,
                data={
                    "kept_card_instance_id": instance_id,
                    "moved_to_waiting_room_instance_id": replaced_instance_id,
                    "slot": slot,
                },
            )
        )
    if use_baton_touch and replaced_instance_id is not None:
        _queue_triggered_effects(
            state,
            "baton_touch_performed",
            events,
            source_instance_ids=[replaced_instance_id],
            trigger_data={
                "replacement_card_instance_id": instance_id,
                "replaced_card_instance_id": replaced_instance_id,
            },
        )
    _queue_triggered_effects(
        state,
        "member_played",
        events,
        source_instance_ids=[instance_id],
        trigger_data={"card_instance_id": instance_id, "slot": slot},
    )
    _resolve_automatic_effects(state, events)


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
    _draw(
        state,
        player.player_id,
        len(selected),
        events,
        reason="live_set_replacement",
    )
    events.append(
        GameEvent(
            event_type="live_cards_set",
            player_id=player.player_id,
            data={
                "count": len(selected),
                "replacement_draw_count": len(selected),
            },
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
        _record_success_live_move(state, player.player_id)
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
    source_invocation_id = action.payload.get("source_invocation_id")
    source_effect_id = action.payload.get("source_effect_id")
    if state.pending_effects and source_invocation_id is None:
        raise IllegalActionError(
            "pending effects require a source_invocation_id for manual adjustment"
        )
    if source_invocation_id is not None:
        invocation = _find_pending_invocation(state, source_invocation_id)
        if source_effect_id != invocation.effect_id:
            raise IllegalActionError("manual adjustment source effect does not match")
        effect = state.effect_definitions.get(invocation.effect_id)
        if effect is None or effect.simulation_support != "manual_resolution":
            raise IllegalActionError("pending effect does not allow manual resolution")
        if action.payload.get("source_card_instance_id") != invocation.source_card_instance_id:
            raise IllegalActionError("manual adjustment source card does not match")
    adjustments = action.payload.get("adjustments")
    if not isinstance(adjustments, list) or not adjustments:
        raise IllegalActionError("manual_adjustment requires at least one adjustment")
    inspection_count = sum(
        isinstance(item, dict)
        and item.get("adjustment_type") == "inspect_top_cards"
        for item in adjustments
    )
    if inspection_count and (inspection_count != 1 or len(adjustments) != 1):
        raise IllegalActionError(
            "inspect_top_cards must be the only manual adjustment entry"
        )
    if action.payload.get("requires_confirmation") and not action.payload.get(
        "confirmed_by"
    ):
        raise IllegalActionError("confirmed_by is required for confirmed adjustments")
    action_key = action.action_id or f"revision-{state.revision}"
    starts_inspection = False
    for adjustment_index, adjustment in enumerate(adjustments):
        if not isinstance(adjustment, dict):
            raise IllegalActionError("manual adjustment entries must be objects")
        resolved_adjustment = dict(adjustment)
        if resolved_adjustment.get("adjustment_type") == "inspect_top_cards":
            resolved_adjustment.setdefault(
                "source_invocation_id", source_invocation_id
            )
            resolved_adjustment.setdefault("source_effect_id", source_effect_id)
            resolved_adjustment.setdefault(
                "source_card_instance_id",
                action.payload.get("source_card_instance_id"),
            )
        _apply_manual_entry(
            state,
            resolved_adjustment,
            events,
            modifier_id=f"{action_key}:{adjustment_index}",
        )
        starts_inspection = starts_inspection or (
            adjustment.get("adjustment_type") == "inspect_top_cards"
        )
    events.append(
        GameEvent(
            event_type="manual_adjustment_applied",
            player_id=action.player_id,
            data={
                "reason": action.payload.get("reason"),
                "adjustments": adjustments,
                "confirmed_by": action.payload.get("confirmed_by"),
                "source_effect_id": source_effect_id,
                "source_card_instance_id": action.payload.get(
                    "source_card_instance_id"
                ),
                "source_invocation_id": source_invocation_id,
            },
            source="manual",
        )
    )
    if source_invocation_id is not None and not starts_inspection:
        invocation = _find_pending_invocation(state, source_invocation_id)
        _record_effect_usage(state, invocation)
        state.pending_effects.remove(invocation)
        events.append(
            GameEvent(
                event_type="effect_manually_resolved",
                player_id=invocation.player_id,
                data={
                    "invocation_id": invocation.invocation_id,
                    "effect_id": invocation.effect_id,
                    "source_card_instance_id": invocation.source_card_instance_id,
                },
                source="manual",
            )
        )
        _resolve_automatic_effects(state, events)
        _continue_after_effect_queue(state, events)


def _resolve_manual_inspection(
    state: MatchState,
    action: ActionRequest,
    events: list[GameEvent],
) -> None:
    pending = state.pending_choice
    if (
        pending is None
        or pending.choice_type != "manual_card_selection"
        or action.player_id != pending.player_id
    ):
        raise IllegalActionError("there is no matching manual card inspection")
    inspected = list(pending.options.get("inspected_card_instance_ids", []))
    selected = action.payload.get("selected_card_instance_ids", [])
    if (
        not isinstance(selected, list)
        or any(not isinstance(item, str) for item in selected)
        or len(selected) != len(set(selected))
        or any(item not in inspected for item in selected)
    ):
        raise IllegalActionError("manual inspection selection is invalid")
    minimum = int(pending.options.get("minimum", 0))
    maximum = int(pending.options.get("maximum", 1))
    if len(selected) < minimum or len(selected) > maximum:
        raise IllegalActionError(
            f"manual inspection requires {minimum} to {maximum} selected cards"
        )
    player = state.players[pending.player_id]
    if any(item not in player.resolution_area for item in inspected):
        raise IllegalActionError("inspected cards must remain in Resolution Area")
    for instance_id in inspected:
        player.resolution_area.remove(instance_id)
        if instance_id in selected:
            player.hand.append(instance_id)
            state.cards[instance_id].face_up = True
        else:
            player.waiting_room.append(instance_id)
            state.cards[instance_id].face_up = True
    source_invocation_id = pending.options.get("source_invocation_id")
    source_effect_id = pending.options.get("source_effect_id")
    source_card_instance_id = pending.options.get("source_card_instance_id")
    state.pending_choice = None
    if source_invocation_id is not None:
        invocation = _find_pending_invocation(state, source_invocation_id)
        if (
            invocation.effect_id != source_effect_id
            or invocation.source_card_instance_id != source_card_instance_id
        ):
            raise IllegalActionError("manual inspection source does not match")
        _record_effect_usage(state, invocation)
        state.pending_effects.remove(invocation)
    events.append(
        GameEvent(
            event_type="manual_card_inspection_resolved",
            player_id=player.player_id,
            data={
                "inspected_card_instance_ids": inspected,
                "selected_card_instance_ids": selected,
                "moved_to_waiting_room_instance_ids": [
                    item for item in inspected if item not in selected
                ],
                "reveal_selected_to_opponent": bool(
                    pending.options.get("reveal_selected_to_opponent")
                ),
                "source_effect_id": source_effect_id,
                "source_card_instance_id": source_card_instance_id,
            },
            source="manual",
        )
    )
    _resolve_automatic_effects(state, events)
    _continue_after_effect_queue(state, events)


def _pending_effect_legal_actions(state: MatchState) -> list[LegalAction]:
    owner_id = state.pending_effects[0].player_id
    owned = [
        invocation
        for invocation in state.pending_effects
        if invocation.player_id == owner_id
    ]
    invocations: list[dict[str, Any]] = []
    has_manual = False
    for invocation in owned:
        effect = state.effect_definitions[invocation.effect_id]
        options = _effect_resolution_options(state, invocation)
        invocations.append(
            {
                "invocation_id": invocation.invocation_id,
                "effect_id": effect.effect_id,
                "source_card_instance_id": invocation.source_card_instance_id,
                "label_ja": effect.label_ja,
                "is_optional": effect.is_optional,
                "simulation_support": effect.simulation_support,
                "review_status": effect.review_status,
                "choice": effect.choice.model_dump() if effect.choice else None,
                **options,
            }
        )
        has_manual = has_manual or effect.simulation_support == "manual_resolution"
    actions = [
        LegalAction(
            action_type="resolve_effect",
            player_id=owner_id,
            label_zh="处理待结算技能",
            label_ja="待機中の能力を解決",
            options={"invocations": invocations},
        )
    ]
    if has_manual:
        actions.append(
            LegalAction(
                action_type="manual_adjustment",
                player_id=owner_id,
                label_zh="人工处理技能",
                label_ja="能力を手動解決",
                options={
                    "source_invocations": [
                        item
                        for item in invocations
                        if item["simulation_support"] == "manual_resolution"
                    ]
                },
            )
        )
    return actions


def _legal_effect_activations(
    state: MatchState,
    player_id: str,
) -> list[dict[str, Any]]:
    player = state.players[player_id]
    activations: list[dict[str, Any]] = []
    for instance_id in player.member_area.values():
        if instance_id is None:
            continue
        instance = state.cards[instance_id]
        for effect_id in instance.card.effect_ids:
            effect = state.effect_definitions.get(effect_id)
            if effect is None or effect.effect_type != "activated":
                continue
            if effect.timing != "activated_main":
                continue
            if _effect_used_this_turn(state, effect_id, instance_id):
                continue
            if effect.condition.get("source_orientation") == "active":
                if instance.orientation != "active":
                    continue
            activations.append(
                {
                    "effect_id": effect_id,
                    "source_card_instance_id": instance_id,
                    "label_ja": effect.label_ja,
                    "frequency_limit": effect.frequency_limit,
                    "simulation_support": effect.simulation_support,
                }
            )
    return activations


def _activate_effect(
    state: MatchState,
    action: ActionRequest,
    events: list[GameEvent],
) -> None:
    player_id = state.active_player_id or ""
    if state.phase not in {"first_main", "second_main"}:
        raise IllegalActionError("activated effects are only available in Main Phase")
    if action.player_id != player_id:
        raise IllegalActionError("only the active player may activate an effect")
    effect_id = action.payload.get("effect_id")
    source_id = action.payload.get("source_card_instance_id")
    legal = {
        (entry["effect_id"], entry["source_card_instance_id"])
        for entry in _legal_effect_activations(state, player_id)
    }
    if (effect_id, source_id) not in legal:
        raise IllegalActionError("the selected activated effect is not legal")
    effect = state.effect_definitions[str(effect_id)]
    invocation = EffectInvocation(
        invocation_id=_new_invocation_id(state, effect.effect_id, str(source_id)),
        effect_id=effect.effect_id,
        source_card_instance_id=str(source_id),
        player_id=player_id,
        trigger_event="player_activation",
        resolution_stage="after_cost",
    )
    _execute_operations(
        state,
        invocation,
        effect.cost,
        events,
        selected_ids=[],
    )
    for operation in effect.actions:
        if operation.action_type in {"discard_from_hand"}:
            continue
        _execute_operations(
            state,
            invocation,
            [operation],
            events,
            selected_ids=[],
        )
    state.pending_effects.append(invocation)
    events.append(
        GameEvent(
            event_type="effect_activated",
            player_id=player_id,
            data={
                "invocation_id": invocation.invocation_id,
                "effect_id": effect.effect_id,
                "source_card_instance_id": source_id,
            },
            source="player",
        )
    )


def _resolve_effect(
    state: MatchState,
    action: ActionRequest,
    events: list[GameEvent],
) -> None:
    invocation_id = action.payload.get("invocation_id")
    invocation = _find_pending_invocation(state, invocation_id)
    if action.player_id != invocation.player_id:
        raise IllegalActionError("only the effect owner may resolve this effect")
    if invocation.player_id != state.pending_effects[0].player_id:
        raise IllegalActionError("another player's effects must resolve first")
    effect = state.effect_definitions[invocation.effect_id]
    accepted = action.payload.get("accepted", True)
    if not isinstance(accepted, bool):
        raise IllegalActionError("effect accepted must be a boolean")
    if not accepted:
        if not effect.is_optional:
            raise IllegalActionError("this effect is not optional")
        state.pending_effects.remove(invocation)
        _record_effect_usage(state, invocation)
        events.append(
            GameEvent(
                event_type="effect_declined",
                player_id=invocation.player_id,
                data={
                    "invocation_id": invocation.invocation_id,
                    "effect_id": invocation.effect_id,
                    "source_card_instance_id": invocation.source_card_instance_id,
                },
                source="player",
            )
        )
        _resolve_automatic_effects(state, events)
        _continue_after_effect_queue(state, events)
        return
    if effect.simulation_support == "manual_resolution":
        raise IllegalActionError(
            "manual_resolution effects require a ManualAdjustmentAction"
        )

    selected_ids = action.payload.get("selected_card_instance_ids", [])
    if not isinstance(selected_ids, list) or any(
        not isinstance(item, str) for item in selected_ids
    ):
        raise IllegalActionError("effect card selections must be a list of IDs")
    candidates = _effect_choice_candidates(state, invocation)
    if effect.choice is not None:
        if (
            len(selected_ids) < effect.choice.minimum
            or len(selected_ids) > effect.choice.maximum
            or len(selected_ids) != len(set(selected_ids))
            or any(item not in candidates for item in selected_ids)
        ):
            raise IllegalActionError("effect card selection is not legal")
    elif selected_ids:
        raise IllegalActionError("this effect does not accept card selections")

    if invocation.resolution_stage == "initial":
        _execute_operations(
            state,
            invocation,
            effect.cost,
            events,
            selected_ids=selected_ids,
            energy_ids=action.payload.get("energy_instance_ids", []),
        )
        operations = effect.actions
    else:
        operations = [
            operation
            for operation in effect.actions
            if operation.action_type == "discard_from_hand"
        ]
    _execute_operations(
        state,
        invocation,
        operations,
        events,
        selected_ids=selected_ids,
    )
    state.pending_effects.remove(invocation)
    _record_effect_usage(state, invocation)
    events.append(
        GameEvent(
            event_type="effect_resolved",
            player_id=invocation.player_id,
            data={
                "invocation_id": invocation.invocation_id,
                "effect_id": invocation.effect_id,
                "source_card_instance_id": invocation.source_card_instance_id,
                "selected_card_instance_ids": selected_ids,
            },
            source="player",
        )
    )
    _resolve_automatic_effects(state, events)
    _continue_after_effect_queue(state, events)


def _queue_triggered_effects(
    state: MatchState,
    trigger: str,
    events: list[GameEvent],
    *,
    source_instance_ids: list[str],
    trigger_data: dict[str, Any],
) -> None:
    for source_id in source_instance_ids:
        source = state.cards[source_id]
        for effect_id in source.card.effect_ids:
            effect = state.effect_definitions.get(effect_id)
            if effect is None or effect.trigger != trigger:
                continue
            if effect.frequency_limit in {"once_per_turn", "once_per_live"} and (
                _effect_used_this_turn(state, effect_id, source_id)
            ):
                continue
            invocation = EffectInvocation(
                invocation_id=_new_invocation_id(state, effect_id, source_id),
                effect_id=effect_id,
                source_card_instance_id=source_id,
                player_id=source.owner_id,
                trigger_event=trigger,
                trigger_data=trigger_data,
            )
            if not _effect_condition_met(state, invocation):
                events.append(
                    GameEvent(
                        event_type="effect_not_triggered",
                        player_id=source.owner_id,
                        data={
                            "effect_id": effect_id,
                            "source_card_instance_id": source_id,
                            "reason": "condition_or_target_unavailable",
                        },
                    )
                )
                continue
            state.pending_effects.append(invocation)
            events.append(
                GameEvent(
                    event_type="effect_triggered",
                    player_id=source.owner_id,
                    data={
                        "invocation_id": invocation.invocation_id,
                        "effect_id": effect_id,
                        "source_card_instance_id": source_id,
                        "trigger": trigger,
                    },
                )
            )


def _effect_condition_met(
    state: MatchState,
    invocation: EffectInvocation,
) -> bool:
    effect = state.effect_definitions[invocation.effect_id]
    player = state.players[invocation.player_id]
    minimum_energy = effect.condition.get("minimum_active_energy")
    if isinstance(minimum_energy, int):
        active = sum(
            state.cards[item].orientation == "active" for item in player.energy_area
        )
        if active < minimum_energy:
            return False
    replacement_id = invocation.trigger_data.get("replacement_card_instance_id")
    minimum_cost = effect.condition.get("replacement_member_minimum_cost")
    if isinstance(minimum_cost, int):
        if not isinstance(replacement_id, str):
            return False
        if (state.cards[replacement_id].card.cost or 0) < minimum_cost:
            return False
    work_key = effect.condition.get("replacement_member_work_key")
    if isinstance(work_key, str):
        if not isinstance(replacement_id, str):
            return False
        if work_key not in state.cards[replacement_id].card.work_keys:
            return False
    if effect.choice is not None and effect.choice.minimum > 0:
        return len(_effect_choice_candidates(state, invocation)) >= effect.choice.minimum
    if (
        effect.choice is not None
        and effect.choice.maximum > 0
        and effect.choice.zone == "stage"
        and not _effect_choice_candidates(state, invocation)
    ):
        return False
    return True


def _effect_resolution_options(
    state: MatchState,
    invocation: EffectInvocation,
) -> dict[str, Any]:
    effect = state.effect_definitions[invocation.effect_id]
    options: dict[str, Any] = {
        "candidate_card_instance_ids": _effect_choice_candidates(state, invocation)
    }
    pay_amount = sum(
        operation.amount or 0
        for operation in effect.cost
        if operation.action_type == "pay_energy"
    )
    if pay_amount:
        player = state.players[invocation.player_id]
        options["energy_instance_ids"] = [
            item
            for item in player.energy_area
            if state.cards[item].orientation == "active"
        ]
        options["energy_required"] = pay_amount
    return options


def _effect_choice_candidates(
    state: MatchState,
    invocation: EffectInvocation,
) -> list[str]:
    effect = state.effect_definitions[invocation.effect_id]
    if effect.choice is None:
        return []
    player = state.players[invocation.player_id]
    if effect.choice.zone == "waiting_room":
        candidates = list(player.waiting_room)
    elif effect.choice.zone == "hand":
        candidates = list(player.hand)
    elif effect.choice.zone == "stage":
        candidates = [
            item for item in player.member_area.values() if item is not None
        ]
    else:
        return []
    if effect.choice.card_type:
        candidates = [
            item
            for item in candidates
            if state.cards[item].card.card_type == effect.choice.card_type
        ]
    if effect.choice.orientation:
        candidates = [
            item
            for item in candidates
            if state.cards[item].orientation == effect.choice.orientation
        ]
    return candidates


def _execute_operations(
    state: MatchState,
    invocation: EffectInvocation,
    operations: list[Any],
    events: list[GameEvent],
    *,
    selected_ids: list[str],
    energy_ids: Any = None,
) -> None:
    player = state.players[invocation.player_id]
    for operation in operations:
        operation_type = operation.action_type
        if operation_type == "apply_wait":
            state.cards[invocation.source_card_instance_id].orientation = "wait"
        elif operation_type == "draw_card":
            _draw(
                state,
                invocation.player_id,
                operation.amount or 0,
                events,
                reason=f"effect:{invocation.effect_id}",
            )
        elif operation_type == "discard_from_hand":
            for instance_id in selected_ids:
                if instance_id not in player.hand:
                    raise IllegalActionError("effect discard target must be in hand")
                player.hand.remove(instance_id)
                player.waiting_room.append(instance_id)
        elif operation_type == "return_from_waiting_room":
            for instance_id in selected_ids:
                if instance_id not in player.waiting_room:
                    raise IllegalActionError("effect return target must be in Waiting Room")
                player.waiting_room.remove(instance_id)
                player.hand.append(instance_id)
                state.cards[instance_id].face_up = True
        elif operation_type == "ready_member":
            for instance_id in selected_ids:
                state.cards[instance_id].orientation = "active"
        elif operation_type == "pay_energy":
            required = operation.amount or 0
            if (
                not isinstance(energy_ids, list)
                or len(energy_ids) != required
                or len(energy_ids) != len(set(energy_ids))
            ):
                raise IllegalActionError(
                    f"effect requires exactly {required} Active Energy"
                )
            for instance_id in energy_ids:
                if (
                    instance_id not in player.energy_area
                    or state.cards[instance_id].orientation != "active"
                ):
                    raise IllegalActionError("effect payment requires Active Energy")
                state.cards[instance_id].orientation = "wait"
        elif operation_type == "gain_blade":
            player.manual_modifiers.append(
                ManualModifier(
                    modifier_id=f"effect:{invocation.invocation_id}:blade",
                    modifier_type="blade",
                    duration="live",
                    created_turn=state.turn_number,
                    amount=operation.amount or 0,
                    target_card_instance_id=invocation.source_card_instance_id,
                )
            )
        elif operation_type == "ready_energy":
            waiting = [
                item
                for item in player.energy_area
                if state.cards[item].orientation == "wait"
            ]
            for instance_id in waiting[: operation.amount or 0]:
                state.cards[instance_id].orientation = "active"
        elif operation_type == "manual_resolution":
            raise IllegalActionError("manual effect operations cannot auto-resolve")
        else:
            raise IllegalActionError(f"unsupported effect operation: {operation_type}")


def _resolve_automatic_effects(
    state: MatchState,
    events: list[GameEvent],
) -> None:
    while state.pending_effects:
        invocation = state.pending_effects[0]
        effect = state.effect_definitions[invocation.effect_id]
        if (
            effect.is_optional
            or effect.choice is not None
            or effect.cost
            or effect.simulation_support == "manual_resolution"
        ):
            return
        _execute_operations(
            state,
            invocation,
            effect.actions,
            events,
            selected_ids=[],
        )
        state.pending_effects.pop(0)
        _record_effect_usage(state, invocation)
        events.append(
            GameEvent(
                event_type="effect_auto_resolved",
                player_id=invocation.player_id,
                data={
                    "invocation_id": invocation.invocation_id,
                    "effect_id": invocation.effect_id,
                    "source_card_instance_id": invocation.source_card_instance_id,
                },
            )
        )


def _continue_after_effect_queue(
    state: MatchState,
    events: list[GameEvent],
) -> None:
    if state.pending_effects:
        return
    if state.phase == "performance_first":
        state.phase = "yell_first"
    elif state.phase == "performance_second":
        state.phase = "yell_second"
    else:
        return
    events.append(
        GameEvent(
            event_type="phase_changed",
            player_id=state.active_player_id,
            data={"phase": state.phase},
        )
    )


def _find_pending_invocation(
    state: MatchState,
    invocation_id: Any,
) -> EffectInvocation:
    if not isinstance(invocation_id, str):
        raise IllegalActionError("source_invocation_id is required")
    for invocation in state.pending_effects:
        if invocation.invocation_id == invocation_id:
            return invocation
    raise IllegalActionError("pending effect invocation was not found")


def _record_effect_usage(
    state: MatchState,
    invocation: EffectInvocation,
) -> None:
    state.effect_usage.append(
        EffectUsage(
            effect_id=invocation.effect_id,
            source_card_instance_id=invocation.source_card_instance_id,
            turn_number=state.turn_number,
        )
    )


def _effect_used_this_turn(
    state: MatchState,
    effect_id: str,
    source_instance_id: str,
) -> bool:
    return any(
        usage.effect_id == effect_id
        and usage.source_card_instance_id == source_instance_id
        and usage.turn_number == state.turn_number
        for usage in state.effect_usage
    )


def _new_invocation_id(
    state: MatchState,
    effect_id: str,
    source_instance_id: str,
) -> str:
    ordinal = (
        sum(
            invocation.effect_id == effect_id
            and invocation.source_card_instance_id == source_instance_id
            for invocation in state.pending_effects
        )
        + sum(
            usage.effect_id == effect_id
            and usage.source_card_instance_id == source_instance_id
            for usage in state.effect_usage
        )
        + 1
    )
    digest = hashlib.sha256(
        (
            f"{state.match_id}:{state.turn_number}:{state.revision}:"
            f"{effect_id}:{source_instance_id}:{ordinal}"
        ).encode()
    ).hexdigest()
    return f"effect-{digest[:20]}"


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

    blade_count = _modifier_total(player, "blade")
    member_hearts: Counter[str] = Counter()
    for instance_id in player.member_area.values():
        if instance_id is None:
            continue
        member = state.cards[instance_id]
        member_hearts.update(member.card.basic_hearts)
        if member.orientation == "active":
            blade_count += member.card.blade or 0
            blade_count += _target_modifier_total(player, "blade", instance_id)

    revealed: list[str] = []
    yell_hearts: Counter[str] = Counter()
    all_color_hearts = 0
    draw_count = 0
    score_bonus = 0
    special_results: list[dict[str, Any]] = []
    for _ in range(max(0, blade_count)):
        instance_id = _take_main_deck_card(state, player_id, events)
        if instance_id is None:
            break
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

    manual_hearts = _heart_modifiers(player)
    hearts = Counter(member_hearts)
    hearts.update(manual_hearts)
    hearts.update(yell_hearts)
    player.live_result = LivePerformanceResult(
        blade_count=blade_count,
        revealed_instance_ids=revealed,
        member_hearts=dict(sorted(member_hearts.items())),
        manual_hearts=dict(sorted(manual_hearts.items())),
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
                "manual_hearts": dict(manual_hearts),
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
        player.live_result.score_bonus += _modifier_total(player, "score")
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
    player_id = state.active_player_id
    if player_id:
        _expire_modifiers(state, player_id, "live", events)
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
    state.success_live_moved_player_ids = []
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


def _start_next_turn(
    state: MatchState,
    action: ActionRequest,
    events: list[GameEvent],
) -> None:
    if state.phase != "turn_complete":
        raise IllegalActionError("the next turn can only start after turn completion")
    next_first = state.next_first_player_id
    if next_first not in state.players:
        raise IllegalActionError("next first player is not available")
    next_second = next(
        player_id for player_id in state.players if player_id != next_first
    )
    for player_id in state.players:
        _expire_modifiers(state, player_id, "turn", events)
        state.players[player_id].live_result = LivePerformanceResult()
        state.players[player_id].member_areas_entered_this_turn = []
    state.turn_number += 1
    state.first_player_id = next_first
    state.second_player_id = next_second
    state.next_first_player_id = None
    state.success_live_moved_player_ids = []
    state.live_winner_ids = []
    state.live_judgment_summary = None
    state.pending_choice = None
    state.completed_reason = None
    state.phase = "first_active"
    state.active_player_id = next_first
    events.append(
        GameEvent(
            event_type="turn_started",
            player_id=next_first,
            data={
                "turn_number": state.turn_number,
                "first_player_id": next_first,
                "second_player_id": next_second,
            },
            source="player",
        )
    )


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
            _record_success_live_move(state, player_id)
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
    _complete_live_judgment(state, events)


def _complete_live_judgment(
    state: MatchState,
    events: list[GameEvent],
) -> None:
    for player in state.players.values():
        for zone in (player.live_area, player.resolution_area):
            for instance_id in list(zone):
                zone.remove(instance_id)
                player.waiting_room.append(instance_id)
    state.pending_choice = None
    state.active_player_id = None
    success_counts = {
        player_id: len(player.success_live_area)
        for player_id, player in state.players.items()
    }
    threshold_players = [
        player_id for player_id, count in success_counts.items() if count >= 3
    ]
    if len(threshold_players) == 2:
        state.game_result = GameResult(
            outcome="draw",
            winner_player_ids=[],
            final_turn=state.turn_number,
        )
    elif len(threshold_players) == 1:
        state.game_result = GameResult(
            outcome="win",
            winner_player_ids=threshold_players,
            final_turn=state.turn_number,
        )

    if state.game_result is not None:
        state.phase = "complete"
        state.completed_reason = "success_live_threshold"
        state.next_first_player_id = None
        events.append(
            GameEvent(
                event_type="match_completed",
                data={
                    "game_result": state.game_result.model_dump(),
                    "success_live_counts": success_counts,
                },
            )
        )
    else:
        moved = state.success_live_moved_player_ids
        state.next_first_player_id = (
            moved[0] if len(moved) == 1 else state.first_player_id
        )
        state.phase = "turn_complete"
        state.completed_reason = None
        events.append(
            GameEvent(
                event_type="turn_completed",
                data={
                    "turn_number": state.turn_number,
                    "next_first_player_id": state.next_first_player_id,
                    "success_live_moved_player_ids": list(moved),
                    "success_live_counts": success_counts,
                },
            )
        )
    events.append(
        GameEvent(
            event_type="live_judgment_completed",
            data={
                "winner_ids": state.live_winner_ids,
                "success_live_moved_player_ids": list(
                    state.success_live_moved_player_ids
                ),
            },
        )
    )


def _apply_manual_entry(
    state: MatchState,
    adjustment: dict[str, Any],
    events: list[GameEvent],
    *,
    modifier_id: str,
) -> None:
    adjustment_type = adjustment.get("adjustment_type")
    player_id = adjustment.get("target_player_id")
    if player_id not in state.players:
        raise IllegalActionError("manual adjustment target_player_id is invalid")
    player = state.players[player_id]
    if adjustment_type == "draw_card":
        amount = _positive_amount(adjustment)
        _draw(state, player_id, amount, events, reason="manual")
    elif adjustment_type == "inspect_top_cards":
        if state.pending_choice is not None:
            raise IllegalActionError("another choice is already pending")
        amount = _positive_amount(adjustment)
        minimum = adjustment.get("minimum", 0)
        maximum = adjustment.get("maximum", 1)
        if (
            not isinstance(minimum, int)
            or isinstance(minimum, bool)
            or not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or minimum < 0
            or maximum < minimum
            or maximum > amount
        ):
            raise IllegalActionError("manual inspection selection range is invalid")
        inspected: list[str] = []
        for _ in range(amount):
            instance_id = _take_main_deck_card(state, player_id, events)
            if instance_id is None:
                break
            player.resolution_area.append(instance_id)
            state.cards[instance_id].face_up = True
            inspected.append(instance_id)
        state.pending_choice = PendingChoice(
            choice_type="manual_card_selection",
            player_id=player_id,
            message_ja="確認したカードから条件を満たすカードを選んでください。",
            message_zh="请从检查的卡牌中选择符合条件、加入手牌的卡。",
            options={
                "inspected_card_instance_ids": inspected,
                "minimum": min(minimum, len(inspected)),
                "maximum": min(maximum, len(inspected)),
                "reveal_selected_to_opponent": bool(
                    adjustment.get("reveal_selected_to_opponent", False)
                ),
                "source_invocation_id": adjustment.get("source_invocation_id"),
                "source_effect_id": adjustment.get("source_effect_id"),
                "source_card_instance_id": adjustment.get(
                    "source_card_instance_id"
                ),
            },
        )
        events.append(
            GameEvent(
                event_type="manual_card_inspection_started",
                player_id=player_id,
                data={
                    "inspected_card_instance_ids": inspected,
                    "minimum": minimum,
                    "maximum": maximum,
                    "reveal_selected_to_opponent": bool(
                        adjustment.get("reveal_selected_to_opponent", False)
                    ),
                },
                source="manual",
            )
        )
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
    elif adjustment_type in {"modify_score", "modify_blade", "modify_heart"}:
        duration = _modifier_duration(adjustment)
        color = adjustment.get("color_slot")
        if adjustment_type == "modify_heart" and not isinstance(color, str):
            raise IllegalActionError("modify_heart requires color_slot")
        player.manual_modifiers.append(
            ManualModifier(
                modifier_id=modifier_id,
                modifier_type=adjustment_type.removeprefix("modify_"),
                duration=duration,
                created_turn=state.turn_number,
                amount=_integer_amount(adjustment),
                color_slot=color if adjustment_type == "modify_heart" else None,
            )
        )
    elif adjustment_type in {"set_flag", "clear_flag"}:
        flag = adjustment.get("flag")
        if not isinstance(flag, str) or not flag:
            raise IllegalActionError("flag adjustment requires a flag name")
        if adjustment_type == "set_flag":
            player.manual_modifiers.append(
                ManualModifier(
                    modifier_id=modifier_id,
                    modifier_type="flag",
                    duration=_modifier_duration(adjustment),
                    created_turn=state.turn_number,
                    flag=flag,
                    value=adjustment.get("value", True),
                )
            )
        else:
            player.manual_modifiers = [
                modifier
                for modifier in player.manual_modifiers
                if not (
                    modifier.modifier_type == "flag" and modifier.flag == flag
                )
            ]
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
    was_on_stage = instance_id in player.member_area.values()
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
        if to_zone in {"main_deck", "energy_deck"}:
            state.cards[instance_id].face_up = False
        return
    if to_zone in {"member_left", "member_center", "member_right"}:
        slot = str(to_zone).removeprefix("member_")
        if player.member_area[slot] is not None:
            raise IllegalActionError("manual move Member Area slot is occupied")
        player.member_area[slot] = instance_id
        if not was_on_stage and slot not in player.member_areas_entered_this_turn:
            player.member_areas_entered_this_turn.append(slot)
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
        instance_id = _take_main_deck_card(state, player_id, events)
        if instance_id is None:
            break
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


def _take_main_deck_card(
    state: MatchState,
    player_id: str,
    events: list[GameEvent],
) -> str | None:
    player = state.players[player_id]
    if not player.main_deck:
        _refresh_main_deck(state, player_id, events)
    if not player.main_deck:
        return None
    return player.main_deck.pop(0)


def _refresh_main_deck(
    state: MatchState,
    player_id: str,
    events: list[GameEvent],
) -> None:
    player = state.players[player_id]
    if player.main_deck or not player.waiting_room:
        return
    moved = list(player.waiting_room)
    player.waiting_room.clear()
    for instance_id in moved:
        state.cards[instance_id].face_up = False
    player.refresh_count += 1
    player.main_deck = _deterministic_shuffle(
        moved,
        state.seed,
        f"refresh:{player_id}:{player.refresh_count}",
    )
    events.append(
        GameEvent(
            event_type="deck_refreshed",
            player_id=player_id,
            data={
                "instance_ids": moved,
                "count": len(moved),
                "refresh_count": player.refresh_count,
            },
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


def _legal_member_placements(
    state: MatchState,
    player_id: str,
    active_energy_count: int,
) -> list[dict[str, Any]]:
    player = state.players[player_id]
    placements: list[dict[str, Any]] = []
    for instance_id in player.hand:
        definition = state.cards[instance_id].card
        if definition.card_type != "member":
            continue
        new_cost = definition.cost or 0
        for slot, current_instance_id in player.member_area.items():
            if slot in player.member_areas_entered_this_turn:
                continue
            if new_cost <= active_energy_count:
                replaced_cost = (
                    state.cards[current_instance_id].card.cost or 0
                    if current_instance_id is not None
                    else 0
                )
                placements.append(
                    {
                        "card_instance_id": instance_id,
                        "slot": slot,
                        "payment_cost": new_cost,
                        "use_baton_touch": False,
                        "replaced_card_instance_id": current_instance_id,
                        "replaced_member_cost": replaced_cost,
                    }
                )
            if current_instance_id is None or new_cost <= 0:
                continue
            replaced_cost = state.cards[current_instance_id].card.cost or 0
            payment_cost = max(0, new_cost - replaced_cost)
            if payment_cost <= active_energy_count:
                placements.append(
                    {
                        "card_instance_id": instance_id,
                        "slot": slot,
                        "payment_cost": payment_cost,
                        "use_baton_touch": True,
                        "replaced_card_instance_id": current_instance_id,
                        "replaced_member_cost": replaced_cost,
                    }
                )
    return placements


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


def _modifier_duration(adjustment: dict[str, Any]) -> str:
    duration = adjustment.get("duration")
    if duration not in {"live", "turn", "game"}:
        raise IllegalActionError(
            "persistent manual adjustment requires duration live, turn, or game"
        )
    return duration


def _modifier_total(player: Any, modifier_type: str) -> int:
    return sum(
        modifier.amount or 0
        for modifier in player.manual_modifiers
        if modifier.modifier_type == modifier_type
        and modifier.target_card_instance_id is None
    )


def _target_modifier_total(
    player: Any,
    modifier_type: str,
    target_card_instance_id: str,
) -> int:
    return sum(
        modifier.amount or 0
        for modifier in player.manual_modifiers
        if modifier.modifier_type == modifier_type
        and modifier.target_card_instance_id == target_card_instance_id
    )


def _heart_modifiers(player: Any) -> Counter[str]:
    hearts: Counter[str] = Counter()
    for modifier in player.manual_modifiers:
        if modifier.modifier_type == "heart" and modifier.color_slot:
            hearts[modifier.color_slot] += modifier.amount or 0
    return hearts


def _expire_modifiers(
    state: MatchState,
    player_id: str,
    duration: str,
    events: list[GameEvent],
) -> None:
    player = state.players[player_id]
    expired = [
        modifier.modifier_id
        for modifier in player.manual_modifiers
        if modifier.duration == duration
    ]
    if not expired:
        return
    player.manual_modifiers = [
        modifier
        for modifier in player.manual_modifiers
        if modifier.duration != duration
    ]
    events.append(
        GameEvent(
            event_type="manual_modifiers_expired",
            player_id=player_id,
            data={"duration": duration, "modifier_ids": expired},
            source="system",
        )
    )


def _record_success_live_move(state: MatchState, player_id: str) -> None:
    if player_id not in state.success_live_moved_player_ids:
        state.success_live_moved_player_ids.append(player_id)
