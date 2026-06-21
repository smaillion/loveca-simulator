"""Deterministic first-turn rules engine for the visual debugger."""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterable
from collections import Counter
from types import SimpleNamespace
from typing import Any

from loveca.simulation.models import (
    ActionRequest,
    ActionResult,
    EffectInvocation,
    EffectUsage,
    GameEvent,
    GameResult,
    LegalAction,
    LivePerformanceResult,
    ManualModifier,
    MatchState,
    PendingChoice,
    PlayerState,
)


class RuleEngineError(RuntimeError):
    """Base error for match rule failures."""


class IllegalActionError(RuleEngineError):
    """Raised when an action is not legal for the current state."""


class StaleRevisionError(RuleEngineError):
    """Raised when a client submits an action for an old state revision."""


_EXPIRABLE_STALE_TRIGGER_REASONS = {
    "stage_member_work_blade_count_too_high",
}


def _public_card_snapshot(state: MatchState, instance_id: str) -> dict[str, Any]:
    instance = state.cards[instance_id]
    card = instance.card
    return {
        "instance_id": instance_id,
        "owner_id": instance.owner_id,
        "card_code": card.card_code,
        "card_id": card.card_id,
        "name_ja": card.name_ja,
        "card_type": card.card_type,
        "image_url": card.image_url,
    }


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
        "resolve_effect_choice",
        "manual_adjustment",
        "skip_effect",
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
        "resolve_effect_choice": _resolve_effect_choice,
        "skip_effect": _skip_effect,
        "resolve_manual_inspection": _resolve_manual_inspection,
    }
    handlers[action.action_type](next_state, action, events)
    _validate_stage_state(next_state)
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
        and state.pending_choice.choice_type
        in {
            "manual_card_selection",
            "effect_inspection_selection",
            "multi_player_effect_selection",
        }
    ):
        action_type = (
            "resolve_effect_choice"
            if state.pending_choice.choice_type
            in {"effect_inspection_selection", "multi_player_effect_selection"}
            else "resolve_manual_inspection"
        )
        label_zh = (
            "提交技能检查结果"
            if action_type == "resolve_effect_choice"
            else "提交牌堆检查结果"
        )
        label_ja = (
            "能力による確認結果を確定"
            if action_type == "resolve_effect_choice"
            else "確認したカードの処理を確定"
        )
        actions = [
            LegalAction(
                action_type=action_type,
                player_id=state.pending_choice.player_id,
                label_zh=label_zh,
                label_ja=label_ja,
                options=state.pending_choice.options,
            )
        ]
        if action_type == "resolve_effect_choice":
            actions.append(_skip_effect_legal_action(state, state.pending_choice.player_id))
        return actions
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
            action_type = (
                "resolve_effect_choice"
                if state.pending_choice.choice_type
                in {"effect_inspection_selection", "multi_player_effect_selection"}
                else "resolve_manual_inspection"
            )
            label_zh = (
                "提交技能检查结果"
                if action_type == "resolve_effect_choice"
                else "提交牌堆检查结果"
            )
            label_ja = (
                "能力による確認結果を確定"
                if action_type == "resolve_effect_choice"
                else "確認したカードの処理を確定"
            )
            actions.append(
                LegalAction(
                    action_type=action_type,
                    player_id=state.pending_choice.player_id,
                    label_zh=label_zh,
                    label_ja=label_ja,
                    options=state.pending_choice.options,
                )
            )
            if action_type == "resolve_effect_choice":
                actions.append(_skip_effect_legal_action(state, state.pending_choice.player_id))
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
                    "move_member",
                    "attach_card_under_member",
                    "move_attached_card",
                    "position_change",
                    "formation_change",
                    "draw_card",
                    "inspect_top_cards",
                    "discard_card",
                    "return_from_waiting_room",
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
        events.append(
            GameEvent(
                event_type="deck_shuffled",
                player_id=player_id,
                data={
                    "zone": "main_deck",
                    "card_count": len(player.main_deck),
                    "reason": "match_setup",
                },
                source="system",
            )
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
            data={
                "second_player_id": second_player_id,
                "automatic": bool(action.payload.get("automatic", False)),
                "selection_method": action.payload.get("selection_method", "manual"),
            },
            source="system" if action.payload.get("automatic", False) else "player",
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
    cost = _effective_member_play_cost(state, player_id, instance_id)
    payment_cost = cost
    replaced_cost = 0
    if use_baton_touch:
        if replaced_instance_id is None:
            raise IllegalActionError("Baton Touch requires a Member in the selected area")
        if (
            slot in player.member_areas_baton_entered_this_turn
            or replaced_instance_id in player.member_instance_ids_baton_entered_this_turn
        ):
            raise IllegalActionError(
                "a Member played by Baton Touch this turn cannot Baton Touch again"
            )
        if cost <= 0:
            raise IllegalActionError(
                "Baton Touch requires at least one unpaid Energy cost"
            )
        _validate_baton_replacement_static_restrictions(
            state,
            player_id,
            replaced_instance_id,
            instance_id,
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
        _move_top_member_off_stage(
            state,
            player_id,
            slot,
            "waiting_room",
            events,
            reason="baton_touch",
        )
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
    player.member_entered_count_this_turn += 1
    if slot not in player.member_areas_entered_this_turn:
        player.member_areas_entered_this_turn.append(slot)
    if use_baton_touch and slot not in player.member_areas_baton_entered_this_turn:
        player.member_areas_baton_entered_this_turn.append(slot)
    if (
        use_baton_touch
        and instance_id not in player.member_instance_ids_baton_entered_this_turn
    ):
        player.member_instance_ids_baton_entered_this_turn.append(instance_id)
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
        _clean_stage_attachments(
            state,
            player_id,
            slot,
            events,
            reason="member_replaced",
        )
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
        trigger_data={
            "card_instance_id": instance_id,
            "slot": slot,
            "source_zone": "hand",
            "replacement_card_instance_id": replaced_instance_id,
            "used_baton_touch": use_baton_touch,
        },
    )
    own_stage_sources = [
        source_id for source_id in player.member_area.values() if source_id is not None
    ]
    _queue_triggered_effects(
        state,
        "own_member_played",
        events,
        source_instance_ids=own_stage_sources,
        trigger_data={
            "card_instance_id": instance_id,
            "slot": slot,
            "source_zone": "hand",
            "replacement_card_instance_id": replaced_instance_id,
            "used_baton_touch": use_baton_touch,
        },
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
        _record_success_live_move(state, player.player_id, selected)
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
    if (
        state.pending_choice is not None
        and state.pending_choice.choice_type == "effect_inspection_selection"
    ):
        raise IllegalActionError(
            "structured effect inspection must be resolved before manual adjustment"
        )
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
        effect = state.effect_definitions.get(invocation.effect_id)
        _record_effect_usage(state, invocation)
        state.pending_effects.remove(invocation)
        events.append(
            GameEvent(
                event_type="effect_manual_resolution_completed",
                player_id=invocation.player_id,
                data={
                    "invocation_id": invocation.invocation_id,
                    "effect_id": invocation.effect_id,
                    "source_card_instance_id": invocation.source_card_instance_id,
                    "trigger": effect.trigger if effect else None,
                    "timing": effect.timing if effect else None,
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
        effect = state.effect_definitions.get(invocation.effect_id)
        if (
            invocation.effect_id != source_effect_id
            or invocation.source_card_instance_id != source_card_instance_id
        ):
            raise IllegalActionError("manual inspection source does not match")
        _record_effect_usage(state, invocation)
        state.pending_effects.remove(invocation)
    reveal_selected = bool(pending.options.get("reveal_selected_to_opponent"))
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
                "reveal_selected_to_opponent": reveal_selected,
                "revealed_cards": [
                    _public_card_snapshot(state, instance_id)
                    for instance_id in selected
                ]
                if reveal_selected
                else [],
                "source_effect_id": source_effect_id,
                "source_card_instance_id": source_card_instance_id,
            },
            source="manual",
        )
    )
    _resolve_automatic_effects(state, events)
    if source_invocation_id is not None:
        events.append(
            GameEvent(
                event_type="effect_manual_resolution_completed",
                player_id=player.player_id,
                data={
                    "invocation_id": source_invocation_id,
                    "effect_id": source_effect_id,
                    "source_card_instance_id": source_card_instance_id,
                    "trigger": effect.trigger if effect else None,
                    "timing": effect.timing if effect else None,
                },
                source="manual",
            )
        )
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
                "trigger": effect.trigger,
                "timing": effect.timing,
                "execution_mode": effect.execution_mode,
                "is_optional": effect.is_optional,
                "simulation_support": effect.simulation_support,
                "review_status": effect.review_status,
                "cost_choice": (
                    effect.cost_choice.model_dump() if effect.cost_choice else None
                ),
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
            options={
                "invocations": invocations,
                "owner_player_id": owner_id,
                "waiting_player_ids": sorted(
                    {
                        invocation.player_id
                        for invocation in state.pending_effects
                        if invocation.player_id != owner_id
                    }
                ),
            },
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
    actions.append(_skip_effect_legal_action(state, owner_id))
    return actions


def _skip_effect_legal_action(state: MatchState, player_id: str | None) -> LegalAction:
    invocations = [
        {
            "invocation_id": invocation.invocation_id,
            "effect_id": invocation.effect_id,
            "source_card_instance_id": invocation.source_card_instance_id,
            "player_id": invocation.player_id,
            "label_ja": state.effect_definitions.get(invocation.effect_id).label_ja
            if invocation.effect_id in state.effect_definitions
            else "",
        }
        for invocation in state.pending_effects
    ]
    return LegalAction(
        action_type="skip_effect",
        player_id=player_id,
        label_zh="跳过技能并记录错误",
        label_ja="能力をスキップしてエラーを記録",
        options={
            "invocations": invocations,
            "pending_choice": (
                state.pending_choice.model_dump() if state.pending_choice else None
            ),
        },
    )


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
            if effect.condition.get("source_zone") == "hand":
                continue
            if effect.timing != "activated_main":
                continue
            if _effect_usage_limit_reached(state, effect, instance_id):
                continue
            if effect.condition.get("source_orientation") == "active":
                if instance.orientation != "active":
                    continue
            if not _activated_effect_required_choice_available(
                state, player_id, effect, instance_id
            ):
                continue
            activations.append(
                {
                    "effect_id": effect_id,
                    "source_card_instance_id": instance_id,
                    "label_ja": effect.label_ja,
                    "trigger": effect.trigger,
                    "timing": effect.timing,
                    "execution_mode": effect.execution_mode,
                    "frequency_limit": effect.frequency_limit,
                    "simulation_support": effect.simulation_support,
                }
            )
    for instance_id in player.hand:
        instance = state.cards[instance_id]
        for effect_id in instance.card.effect_ids:
            effect = state.effect_definitions.get(effect_id)
            if effect is None or effect.effect_type != "activated":
                continue
            if effect.condition.get("source_zone") != "hand":
                continue
            if effect.timing != "activated_main":
                continue
            if _effect_usage_limit_reached(state, effect, instance_id):
                continue
            if not _activated_effect_required_choice_available(
                state, player_id, effect, instance_id
            ):
                continue
            activations.append(
                {
                    "effect_id": effect_id,
                    "source_card_instance_id": instance_id,
                    "label_ja": effect.label_ja,
                    "trigger": effect.trigger,
                    "timing": effect.timing,
                    "execution_mode": effect.execution_mode,
                    "frequency_limit": effect.frequency_limit,
                    "simulation_support": effect.simulation_support,
                }
            )
    return activations


def _activated_effect_required_choice_available(
    state: MatchState,
    player_id: str,
    effect: Any,
    source_card_instance_id: str,
) -> bool:
    if effect.choice is None or not _effect_uses_card_choice(effect):
        return True
    if _effect_uses_post_action_card_choice(effect):
        return True
    choice_zone = _resolved_choice_zone(effect.choice)
    source_zone = effect.condition.get("source_zone")
    if _effect_uses_post_cost_card_choice(effect) and not (
        source_zone == "hand" and choice_zone == "stage"
    ):
        return True
    invocation = EffectInvocation(
        invocation_id="activation-check",
        effect_id=effect.effect_id,
        source_card_instance_id=source_card_instance_id,
        player_id=player_id,
        trigger_event="player_activation",
        resolution_stage=(
            "after_cost" if _effect_uses_post_cost_card_choice(effect) else "initial"
        ),
    )
    if not _choice_condition_met(state, invocation, effect.choice):
        return True
    minimum, _ = _effect_choice_bounds(state, invocation, effect.choice)
    if minimum <= 0:
        return True
    return (
        len(_effect_candidates_for_choice(state, invocation, effect.choice))
        >= minimum
    )


def _effect_uses_selected_count_amount(effect: Any) -> bool:
    return _operations_use_selected_count(effect.cost) or _operations_use_selected_count(
        effect.actions
    )


def _operations_use_selected_count(operations: list[Any]) -> bool:
    return any(operation.amount_source == "selected_count" for operation in operations)


def _activation_energy_ids(
    state: MatchState,
    player_id: str,
    effect: Any,
    requested_energy_ids: Any,
) -> list[str]:
    if requested_energy_ids is not None:
        return requested_energy_ids
    required = sum(
        operation.amount or 0
        for operation in effect.cost
        if operation.action_type == "pay_energy"
    )
    if required <= 0:
        return []
    player = state.players[player_id]
    return [
        instance_id
        for instance_id in player.energy_area
        if state.cards[instance_id].orientation == "active"
    ][:required]


def _activated_effect_needs_pending_resolution(
    state: MatchState,
    invocation: EffectInvocation,
) -> bool:
    effect = state.effect_definitions[invocation.effect_id]
    if effect.simulation_support == "manual_resolution":
        return True
    if (
        _effect_uses_inspection_choice(effect)
        or _effect_uses_multi_player_choice(effect)
        or _effect_uses_post_cost_card_choice(effect)
        or _effect_uses_branch_choice(effect)
        or _effect_accepts_color_choice(effect)
        or _effect_uses_count_choice(effect)
        or _effect_uses_position_change_choice(effect)
        or _effect_uses_deploy_to_empty_stage_choice(effect, invocation)
        or _effect_uses_follow_up_card_choice(effect, invocation)
        or _effect_uses_grouped_stage_member_choice(effect)
    ):
        return True
    if _effect_uses_post_action_card_choice(effect):
        return _post_action_choice_should_continue(state, invocation)
    if _effect_uses_card_choice(effect):
        return True
    return any(
        _operation_requires_selected_choice(operation) for operation in effect.actions
    )


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
    has_cost_selection_payload = "selected_card_instance_ids" in action.payload
    if effect.cost_choice is not None and not has_cost_selection_payload:
        invocation.resolution_stage = "initial"
        events.append(
            GameEvent(
                event_type="effect_activated",
                player_id=player_id,
                data={
                    "invocation_id": invocation.invocation_id,
                    "effect_id": effect.effect_id,
                    "source_card_instance_id": source_id,
                    "trigger": effect.trigger,
                    "timing": effect.timing,
                    "execution_mode": effect.execution_mode,
                    "energy_instance_ids": [],
                },
                source="player",
            )
        )
        state.pending_effects.append(invocation)
        return
    selected_ids = action.payload.get("selected_card_instance_ids", [])
    if effect.cost_choice is not None:
        if not isinstance(selected_ids, list) or any(
            not isinstance(item, str) for item in selected_ids
        ):
            raise IllegalActionError("effect cost card selections must be a list of IDs")
        cost_candidates = _effect_cost_choice_candidates(state, invocation)
        if (
            len(selected_ids) < effect.cost_choice.minimum
            or len(selected_ids) > effect.cost_choice.maximum
            or len(selected_ids) != len(set(selected_ids))
            or any(item not in cost_candidates for item in selected_ids)
        ):
            raise IllegalActionError("effect cost card selection is not legal")
    elif selected_ids:
        raise IllegalActionError("this activated effect does not accept cost cards")
    energy_ids = _activation_energy_ids(
        state,
        player_id,
        effect,
        action.payload.get("energy_instance_ids"),
    )
    _execute_operations(
        state,
        invocation,
        effect.cost,
        events,
        selected_ids=selected_ids,
        energy_ids=energy_ids,
    )
    pre_choice_operations = [
        operation
        for operation in effect.actions
        if not _operation_requires_selected_choice(operation)
    ]
    if pre_choice_operations:
        _execute_operations(
            state,
            invocation,
            pre_choice_operations,
            events,
            selected_ids=[],
        )
    events.append(
        GameEvent(
            event_type="effect_activated",
            player_id=player_id,
            data={
                "invocation_id": invocation.invocation_id,
                "effect_id": effect.effect_id,
                "source_card_instance_id": source_id,
                "trigger": effect.trigger,
                "timing": effect.timing,
                "execution_mode": effect.execution_mode,
                "energy_instance_ids": energy_ids,
            },
            source="player",
        )
    )
    if _activated_effect_needs_pending_resolution(state, invocation):
        state.pending_effects.append(invocation)
        return
    _record_effect_usage(state, invocation)
    events.append(
        GameEvent(
            event_type="effect_resolved",
            player_id=invocation.player_id,
            data={
                "invocation_id": invocation.invocation_id,
                "effect_id": invocation.effect_id,
                "source_card_instance_id": invocation.source_card_instance_id,
                "selected_card_instance_ids": [],
                "selected_card_instance_ids_by_group": {},
                "selected_branch": None,
                "selected_color_slot": None,
                "selected_count": None,
                "selected_position_slot": None,
                "trigger": effect.trigger,
                "timing": effect.timing,
            },
            source="player",
        )
    )
    _resolve_automatic_effects(state, events)
    _continue_after_effect_queue(state, events)


def _resolve_effect(
    state: MatchState,
    action: ActionRequest,
    events: list[GameEvent],
) -> None:
    if state.pending_choice is not None:
        raise IllegalActionError("another pending choice must be resolved first")
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
                    "trigger": effect.trigger,
                    "timing": effect.timing,
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
    selected_ids_by_group: dict[str, list[str]] | None = None
    if _effect_uses_grouped_stage_member_choice(effect):
        selected_ids = []
        selected_ids_by_group = _validate_grouped_stage_member_choice(
            state,
            invocation,
            action.payload.get("selected_card_instance_ids_by_group"),
        )
        for group in effect.choice.selection_groups:
            selected_ids.extend(selected_ids_by_group.get(group.group_id, []))
    elif not isinstance(selected_ids, list) or any(
        not isinstance(item, str) for item in selected_ids
    ):
        raise IllegalActionError("effect card selections must be a list of IDs")
    selected_branch = action.payload.get("selected_branch")
    candidates = _effect_choice_candidates(state, invocation)
    if _effect_uses_cost_card_choice(effect) and invocation.resolution_stage == "initial":
        cost_candidates = _effect_cost_choice_candidates(state, invocation)
        if (
            effect.cost_choice is None
            or len(selected_ids) < effect.cost_choice.minimum
            or len(selected_ids) > effect.cost_choice.maximum
            or len(selected_ids) != len(set(selected_ids))
            or any(item not in cost_candidates for item in selected_ids)
            or not _selected_cards_satisfy_choice_condition(
                state, selected_ids, effect.cost_choice
            )
        ):
            raise IllegalActionError("effect cost card selection is not legal")
    elif _effect_uses_branch_choice(effect):
        selected_branch = _validate_branch_choice(
            state,
            effect,
            invocation,
            selected_branch,
            selected_ids,
            candidates,
        )
    elif (
        (
            _effect_uses_post_action_card_choice(effect)
            or _effect_uses_post_cost_card_choice(effect)
        )
        and invocation.resolution_stage == "initial"
    ):
        if selected_ids:
            raise IllegalActionError(
                "this effect accepts card selections after its first step"
            )
    elif _effect_uses_follow_up_card_choice(effect, invocation):
        choice = effect.follow_up_choice
        if choice is None:
            raise IllegalActionError("effect follow-up selection is not legal")
        minimum, maximum = _effect_choice_bounds(state, invocation, choice)
        if (
            len(selected_ids) < minimum
            or len(selected_ids) > maximum
            or len(selected_ids) != len(set(selected_ids))
            or any(item not in candidates for item in selected_ids)
            or not _selected_cards_satisfy_choice_condition(
                state, selected_ids, choice
            )
        ):
            raise IllegalActionError("effect follow-up selection is not legal")
    elif _effect_uses_grouped_stage_member_choice(effect):
        pass
    elif _effect_uses_card_choice(effect):
        minimum, maximum = _effect_choice_bounds(state, invocation, effect.choice)
        if (
            len(selected_ids) < minimum
            or len(selected_ids) > maximum
            or len(selected_ids) != len(set(selected_ids))
            or any(item not in candidates for item in selected_ids)
            or not _selected_cards_satisfy_choice_condition(
                state, selected_ids, effect.choice
            )
        ):
            raise IllegalActionError("effect card selection is not legal")
    elif _effect_uses_inspection_choice(effect):
        if selected_ids:
            raise IllegalActionError(
                "inspection effects must use resolve_effect_choice for card selection"
            )
    elif selected_ids:
        raise IllegalActionError("this effect does not accept card selections")
    selected_color_slot = action.payload.get("selected_color_slot")
    selected_count = action.payload.get("selected_count")
    selected_position_slot = action.payload.get(
        "to_slot",
        action.payload.get("selected_position_slot"),
    )
    selected_destination = action.payload.get("selected_destination")
    if _effect_accepts_color_choice(effect):
        allowed_colors = set(effect.choice.color_slots if effect.choice else [])
        if not isinstance(selected_color_slot, str) or (
            allowed_colors and selected_color_slot not in allowed_colors
        ):
            raise IllegalActionError("effect color selection is not legal")
    elif selected_color_slot is not None:
        raise IllegalActionError("this effect does not accept a color selection")
    if _effect_uses_count_choice(effect):
        if (
            not isinstance(selected_count, int)
            or isinstance(selected_count, bool)
            or effect.choice is None
            or selected_count < effect.choice.minimum
            or selected_count > effect.choice.maximum
        ):
            raise IllegalActionError("effect count selection is not legal")
    elif selected_count is not None:
        raise IllegalActionError("this effect does not accept a count selection")
    operation_selected_count = selected_count
    if operation_selected_count is None and _effect_uses_selected_count_amount(effect):
        operation_selected_count = len(selected_ids)
    if _effect_uses_position_change_choice(effect):
        position_slots = _position_change_source_target_slots(state, invocation)
        if selected_position_slot is None:
            selected_position_slot = position_slots[0] if position_slots else None
        if selected_position_slot not in position_slots:
            raise IllegalActionError("effect position change selection is not legal")
    elif _effect_uses_deploy_to_empty_stage_choice(effect, invocation):
        if not isinstance(selected_position_slot, str):
            selected_position_slot = action.payload.get("slot")
        deploy_slots = _empty_member_area_slots(state.players[invocation.player_id])
        if selected_position_slot not in deploy_slots:
            raise IllegalActionError("effect deploy slot selection is not legal")
    elif selected_position_slot is not None and not _effect_branch_accepts_position_choice(
        effect, invocation
    ):
        raise IllegalActionError("this effect does not accept a position selection")
    destination_choice = _effect_follow_up_choice(effect, invocation) or effect.choice
    destination_options = (
        list(destination_choice.destination_options)
        if destination_choice is not None
        else []
    )
    if destination_options:
        if (
            invocation.resolution_stage == "initial"
            and _effect_uses_post_action_card_choice(effect)
        ):
            if selected_destination is not None:
                raise IllegalActionError(
                    "this effect accepts a destination after its first step"
                )
        elif (
            not isinstance(selected_destination, str)
            or selected_destination not in destination_options
        ):
            raise IllegalActionError("effect destination selection is not legal")
    elif selected_destination is not None:
        raise IllegalActionError("this effect does not accept a destination selection")

    if invocation.resolution_stage == "initial":
        unavailable_reason = _effect_unavailable_reason(state, invocation)
        if unavailable_reason is not None:
            if (
                invocation.trigger_data.get("_condition_checked_at_trigger") is True
                and unavailable_reason in _EXPIRABLE_STALE_TRIGGER_REASONS
            ):
                state.pending_effects.remove(invocation)
                events.append(
                    GameEvent(
                        event_type="effect_not_activatable",
                        player_id=invocation.player_id,
                        data={
                            "invocation_id": invocation.invocation_id,
                            "effect_id": invocation.effect_id,
                            "source_card_instance_id": invocation.source_card_instance_id,
                            "reason": unavailable_reason,
                            "trigger": effect.trigger,
                            "timing": effect.timing,
                        },
                        source="system",
                    )
                )
                _resolve_automatic_effects(state, events)
                _continue_after_effect_queue(state, events)
                return
            raise IllegalActionError(
                f"effect is no longer activatable: {unavailable_reason}"
            )
        _execute_operations(
            state,
            invocation,
            effect.cost,
            events,
            selected_ids=selected_ids,
            energy_ids=action.payload.get("energy_instance_ids", []),
            selected_color_slot=selected_color_slot,
            selected_count=operation_selected_count,
            selected_position_slot=selected_position_slot,
        )
        if effect.cost:
            events.append(
                GameEvent(
                    event_type="effect_cost_paid",
                    player_id=invocation.player_id,
                    data={
                        "invocation_id": invocation.invocation_id,
                        "effect_id": invocation.effect_id,
                        "source_card_instance_id": invocation.source_card_instance_id,
                        "selected_card_instance_ids": selected_ids,
                        "energy_instance_ids": action.payload.get(
                            "energy_instance_ids", []
                        ),
                    },
                    source="player",
                )
            )
        invocation.resolution_stage = "after_cost"
        if _effect_uses_inspection_choice(effect):
            _begin_effect_inspection_choice(state, invocation, events)
            return
        if _effect_uses_multi_player_choice(effect):
            _begin_multi_player_effect_choice(state, invocation, events)
            return
        if _effect_uses_post_cost_card_choice(effect):
            _append_effect_choice_started_event(
                state,
                invocation,
                events,
                reason="post_cost_card_choice",
            )
            return
        if _effect_uses_post_action_card_choice(effect):
            _execute_operations(
                state,
                invocation,
                _post_action_initial_operations(effect),
                events,
                selected_ids=[],
                selected_color_slot=selected_color_slot,
                selected_count=operation_selected_count,
                selected_position_slot=selected_position_slot,
            )
            if _post_action_choice_should_continue(state, invocation):
                _append_effect_choice_started_event(
                    state,
                    invocation,
                    events,
                    reason="post_action_card_choice",
                )
                return
            operations = []
        elif _effect_uses_branch_choice(effect):
            invocation.trigger_data["selected_branch"] = selected_branch
            branch_operations = [
                operation
                for operation in effect.actions
                if operation.branch == selected_branch
            ]
            _execute_operations(
                state,
                invocation,
                [
                    operation
                    for operation in branch_operations
                    if not _operation_requires_selected_choice(operation)
                ],
                events,
                selected_ids=[],
                energy_ids=action.payload.get("energy_instance_ids", []),
                selected_color_slot=selected_color_slot,
                selected_count=operation_selected_count,
                selected_position_slot=selected_position_slot,
            )
            if any(
                _operation_requires_selected_choice(operation)
                for operation in branch_operations
            ):
                _append_effect_choice_started_event(
                    state,
                    invocation,
                    events,
                    reason="branch_follow_up_choice",
                )
                return
            operations = []
        else:
            operations = effect.actions
    else:
        if _effect_uses_branch_choice(effect):
            branch = invocation.trigger_data.get("selected_branch")
            operations = [
                operation
                for operation in effect.actions
                if operation.branch == branch
                and _operation_requires_selected_choice(operation)
            ]
        elif _effect_uses_post_action_card_choice(effect):
            operations = _post_action_follow_up_operations(effect)
        elif _effect_uses_follow_up_card_choice(effect, invocation):
            operations = effect.actions
        else:
            operations = [
                operation
                for operation in effect.actions
                if _operation_requires_selected_choice(operation)
            ]
    _execute_operations(
        state,
        invocation,
        operations,
        events,
        selected_ids=selected_ids,
        selected_ids_by_group=selected_ids_by_group,
        selected_color_slot=selected_color_slot,
        selected_count=operation_selected_count,
        selected_position_slot=selected_position_slot,
        selected_destination=selected_destination,
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
                "selected_card_instance_ids_by_group": selected_ids_by_group or {},
                "selected_branch": selected_branch,
                "selected_color_slot": selected_color_slot,
                "selected_count": operation_selected_count,
                "selected_position_slot": selected_position_slot,
                "trigger": effect.trigger,
                "timing": effect.timing,
            },
            source="player",
        )
    )
    _resolve_automatic_effects(state, events)
    _continue_after_effect_queue(state, events)


def _begin_effect_inspection_choice(
    state: MatchState,
    invocation: EffectInvocation,
    events: list[GameEvent],
) -> None:
    effect = state.effect_definitions[invocation.effect_id]
    choice = effect.choice
    if choice is None or not _effect_uses_inspection_choice(effect):
        raise IllegalActionError("effect does not define an inspection follow-up")
    if state.pending_choice is not None:
        raise IllegalActionError("another choice is already pending")
    player = state.players[invocation.player_id]
    amount = choice.amount or 0
    if choice.amount_source == "own_stage_member_count_plus_2":
        amount = (
            sum(1 for item in player.member_area.values() if item is not None)
            + 2
        )
    inspected: list[str] = []
    for _ in range(max(0, amount)):
        instance_id = _take_main_deck_card(state, invocation.player_id, events)
        if instance_id is None:
            break
        player.resolution_area.append(instance_id)
        state.cards[instance_id].face_up = True
        inspected.append(instance_id)
    candidates = _inspection_choice_candidates(state, invocation, inspected)
    minimum = min(choice.minimum, len(candidates))
    maximum = min(choice.maximum, len(candidates))
    state.pending_choice = PendingChoice(
        choice_type="effect_inspection_selection",
        player_id=invocation.player_id,
        message_ja="確認したカードの処理を選んでください。",
        message_zh="请选择检查后的卡牌处理结果。",
        options={
            "invocation_id": invocation.invocation_id,
            "effect_id": invocation.effect_id,
            "source_card_instance_id": invocation.source_card_instance_id,
            "inspected_card_instance_ids": inspected,
            "candidate_card_instance_ids": candidates,
            "minimum": minimum,
            "maximum": maximum,
            "requires_order": choice.requires_order,
            "selected_destination": choice.selected_destination,
            "unselected_destination": choice.unselected_destination,
            "reveal_selected_to_opponent": choice.reveal_selected_to_opponent,
        },
    )
    events.append(
        GameEvent(
            event_type="effect_inspection_started",
            player_id=invocation.player_id,
            data={
                "invocation_id": invocation.invocation_id,
                "effect_id": invocation.effect_id,
                "source_card_instance_id": invocation.source_card_instance_id,
                "inspected_card_instance_ids": inspected,
                "candidate_card_instance_ids": candidates,
                "minimum": minimum,
                "maximum": maximum,
                "requires_order": choice.requires_order,
                "selected_destination": choice.selected_destination,
                "unselected_destination": choice.unselected_destination,
                "reveal_selected_to_opponent": choice.reveal_selected_to_opponent,
            },
            source="player",
        )
    )


def _append_effect_choice_started_event(
    state: MatchState,
    invocation: EffectInvocation,
    events: list[GameEvent],
    *,
    reason: str,
) -> None:
    effect = state.effect_definitions[invocation.effect_id]
    options = _effect_resolution_options(state, invocation)
    events.append(
        GameEvent(
            event_type="effect_choice_started",
            player_id=invocation.player_id,
            data={
                "invocation_id": invocation.invocation_id,
                "effect_id": invocation.effect_id,
                "source_card_instance_id": invocation.source_card_instance_id,
                "reason": reason,
                "resolution_stage": invocation.resolution_stage,
                "selected_branch": invocation.trigger_data.get("selected_branch"),
                "choice_type": options.get("choice_type"),
                "candidate_card_instance_ids": options.get(
                    "candidate_card_instance_ids", []
                ),
                "card_selection_minimum": options.get("card_selection_minimum"),
                "card_selection_maximum": options.get("card_selection_maximum"),
                "trigger": effect.trigger,
                "timing": effect.timing,
            },
            source="system",
        )
    )


def _begin_multi_player_effect_choice(
    state: MatchState,
    invocation: EffectInvocation,
    events: list[GameEvent],
) -> None:
    effect = state.effect_definitions[invocation.effect_id]
    choice = effect.choice
    if choice is None or not _effect_uses_multi_player_choice(effect):
        raise IllegalActionError("effect does not define a multi-player choice")
    if state.pending_choice is not None:
        raise IllegalActionError("another choice is already pending")
    player_order = [
        invocation.player_id,
        "player_2" if invocation.player_id == "player_1" else "player_1",
    ]
    options = {
        "invocation_id": invocation.invocation_id,
        "effect_id": invocation.effect_id,
        "source_card_instance_id": invocation.source_card_instance_id,
        "multi_player_choice_type": choice.choice_type,
        "player_order": player_order,
        "current_index": 0,
        "selections": {},
        "draw_amount": choice.amount or 0,
        "discard_amount": choice.discard_amount,
        "target_hand_size": choice.target_hand_size,
        "maximum_cost": choice.maximum_cost,
        "card_type": choice.card_type,
    }
    if choice.choice_type == "multi_player_draw_then_discard":
        amount = choice.amount or 0
        for player_id in player_order:
            _draw(
                state,
                player_id,
                amount,
                events,
                reason=f"effect:{invocation.effect_id}",
            )
    _refresh_multi_player_choice_options(state, options)
    state.pending_choice = PendingChoice(
        choice_type="multi_player_effect_selection",
        player_id=player_order[0],
        message_ja="能力の処理を選んでください。",
        message_zh="请选择技能处理内容。",
        options=options,
    )
    events.append(
        GameEvent(
            event_type="effect_multi_player_choice_started",
            player_id=invocation.player_id,
            data={
                "invocation_id": invocation.invocation_id,
                "effect_id": invocation.effect_id,
                "choice_type": choice.choice_type,
                "player_order": player_order,
            },
            source="player",
        )
    )


def _resolve_effect_choice(
    state: MatchState,
    action: ActionRequest,
    events: list[GameEvent],
) -> None:
    pending = state.pending_choice
    if pending is not None and pending.choice_type == "multi_player_effect_selection":
        _resolve_multi_player_effect_choice(state, action, events)
        return
    if pending is None or pending.choice_type != "effect_inspection_selection":
        raise IllegalActionError("no effect inspection choice is pending")
    if action.player_id != pending.player_id:
        raise IllegalActionError("only the effect owner may resolve this choice")
    invocation = _find_pending_invocation(state, pending.options.get("invocation_id"))
    if invocation.player_id != state.pending_effects[0].player_id:
        raise IllegalActionError("another player's effects must resolve first")
    effect = state.effect_definitions[invocation.effect_id]
    selected_ids = action.payload.get("selected_card_instance_ids", [])
    if not isinstance(selected_ids, list) or any(
        not isinstance(item, str) for item in selected_ids
    ):
        raise IllegalActionError("effect choice selections must be a list of IDs")
    selected_ids = list(selected_ids)
    ordered_ids = action.payload.get("ordered_card_instance_ids", [])
    if ordered_ids in (None, []):
        ordered_ids = list(selected_ids)
    if not isinstance(ordered_ids, list) or any(
        not isinstance(item, str) for item in ordered_ids
    ):
        raise IllegalActionError("effect choice ordering must be a list of IDs")
    candidate_ids = pending.options.get("candidate_card_instance_ids", [])
    inspected_ids = pending.options.get("inspected_card_instance_ids", [])
    minimum = pending.options.get("minimum", 0)
    maximum = pending.options.get("maximum", 0)
    requires_order = bool(pending.options.get("requires_order", False))
    if (
        not isinstance(candidate_ids, list)
        or any(not isinstance(item, str) for item in candidate_ids)
        or not isinstance(inspected_ids, list)
        or any(not isinstance(item, str) for item in inspected_ids)
        or not isinstance(minimum, int)
        or not isinstance(maximum, int)
    ):
        raise IllegalActionError("pending effect inspection metadata is invalid")
    if (
        len(selected_ids) < minimum
        or len(selected_ids) > maximum
        or len(selected_ids) != len(set(selected_ids))
        or any(item not in candidate_ids for item in selected_ids)
    ):
        raise IllegalActionError("effect inspection selection is not legal")
    if requires_order:
        if set(ordered_ids) != set(selected_ids) or len(ordered_ids) != len(selected_ids):
            raise IllegalActionError("effect inspection ordering must match the selected cards")
    elif ordered_ids and any(item not in selected_ids for item in ordered_ids):
        raise IllegalActionError("effect inspection ordering includes unselected cards")

    player = state.players[invocation.player_id]
    for instance_id in inspected_ids:
        if instance_id not in player.resolution_area:
            raise IllegalActionError("inspected cards must remain in the resolution area")
    selected_destination = pending.options.get("selected_destination")
    unselected_destination = pending.options.get("unselected_destination")
    selected_set = set(selected_ids)
    unselected_ids = [item for item in inspected_ids if item not in selected_set]
    for instance_id in selected_ids:
        if instance_id in player.resolution_area:
            player.resolution_area.remove(instance_id)
    for instance_id in unselected_ids:
        if instance_id in player.resolution_area:
            player.resolution_area.remove(instance_id)

    if selected_destination == "hand":
        for instance_id in selected_ids:
            player.hand.append(instance_id)
            state.cards[instance_id].face_up = True
    elif selected_destination == "waiting_room":
        for instance_id in selected_ids:
            player.waiting_room.append(instance_id)
            state.cards[instance_id].face_up = True
    elif selected_destination == "main_deck_top_ordered":
        order = ordered_ids if ordered_ids else selected_ids
        player.main_deck = [*order, *player.main_deck]
        for instance_id in order:
            state.cards[instance_id].face_up = False
    elif selected_ids:
        raise IllegalActionError("unsupported selected destination for inspection effect")

    if unselected_destination == "waiting_room":
        for instance_id in unselected_ids:
            player.waiting_room.append(instance_id)
            state.cards[instance_id].face_up = True
    elif unselected_destination == "main_deck_top_ordered":
        player.main_deck = [*unselected_ids, *player.main_deck]
        for instance_id in unselected_ids:
            state.cards[instance_id].face_up = False
    elif unselected_ids:
        raise IllegalActionError("unsupported unselected destination for inspection effect")

    post_choice_operations = [
        operation
        for operation in effect.actions
        if operation.action_type
        not in {
            "inspect_top_cards",
            "reveal_cards",
            "select_to_hand_from_inspected",
            "reorder_deck_top",
            "move_remaining_cards",
        }
    ]
    if post_choice_operations:
        _execute_operations(
            state,
            invocation,
            post_choice_operations,
            events,
            selected_ids=selected_ids,
        )

    state.pending_choice = None
    state.pending_effects.remove(invocation)
    _record_effect_usage(state, invocation)
    reveal_selected = bool(pending.options.get("reveal_selected_to_opponent", False))
    events.append(
        GameEvent(
            event_type="effect_resolved",
            player_id=invocation.player_id,
            data={
                "invocation_id": invocation.invocation_id,
                "effect_id": invocation.effect_id,
                "source_card_instance_id": invocation.source_card_instance_id,
                "inspected_card_instance_ids": inspected_ids,
                "selected_card_instance_ids": selected_ids,
                "ordered_card_instance_ids": ordered_ids if requires_order else [],
                "unselected_card_instance_ids": unselected_ids,
                "selected_destination": selected_destination,
                "unselected_destination": unselected_destination,
                "reveal_selected_to_opponent": reveal_selected,
                "revealed_cards": [
                    _public_card_snapshot(state, instance_id)
                    for instance_id in selected_ids
                ]
                if reveal_selected
                else [],
                "trigger": effect.trigger,
                "timing": effect.timing,
            },
            source="player",
        )
    )
    _resolve_automatic_effects(state, events)
    _continue_after_effect_queue(state, events)


def _skip_effect(
    state: MatchState,
    action: ActionRequest,
    events: list[GameEvent],
) -> None:
    if not state.pending_effects:
        raise IllegalActionError("there is no pending effect to skip")
    invocation_id = action.payload.get("invocation_id")
    if invocation_id is None and state.pending_choice is not None:
        invocation_id = state.pending_choice.options.get("invocation_id")
    if not isinstance(invocation_id, str):
        raise IllegalActionError("skip_effect requires an invocation_id")
    invocation = _find_pending_invocation(state, invocation_id)
    pending_player_id = state.pending_choice.player_id if state.pending_choice else None
    if action.player_id not in {invocation.player_id, pending_player_id}:
        raise IllegalActionError("only the effect owner or pending chooser may skip it")
    if invocation.player_id != state.pending_effects[0].player_id:
        raise IllegalActionError("another player's effects must resolve first")

    pending_choice_type = state.pending_choice.choice_type if state.pending_choice else None
    cleaned_resolution_ids: list[str] = []
    if (
        state.pending_choice is not None
        and state.pending_choice.options.get("invocation_id") == invocation.invocation_id
    ):
        inspected = state.pending_choice.options.get("inspected_card_instance_ids", [])
        if isinstance(inspected, list):
            player = state.players[invocation.player_id]
            for instance_id in inspected:
                if isinstance(instance_id, str) and instance_id in player.resolution_area:
                    player.resolution_area.remove(instance_id)
                    player.waiting_room.append(instance_id)
                    state.cards[instance_id].face_up = True
                    cleaned_resolution_ids.append(instance_id)
        state.pending_choice = None

    effect = state.effect_definitions.get(invocation.effect_id)
    state.pending_effects.remove(invocation)
    _record_effect_usage(state, invocation)
    events.append(
        GameEvent(
            event_type="effect_skipped_due_to_error",
            player_id=invocation.player_id,
            data={
                "invocation_id": invocation.invocation_id,
                "effect_id": invocation.effect_id,
                "source_card_instance_id": invocation.source_card_instance_id,
                "trigger": effect.trigger if effect else None,
                "timing": effect.timing if effect else None,
                "label_ja": effect.label_ja if effect else None,
                "pending_choice_type": pending_choice_type,
                "cleaned_resolution_area_instance_ids": cleaned_resolution_ids,
                "skipped_by_player_id": action.player_id,
                "reason": action.payload.get("reason"),
                "error_message": action.payload.get("error_message"),
            },
            source="manual",
        )
    )
    _resolve_automatic_effects(state, events)
    _continue_after_effect_queue(state, events)


def _resolve_multi_player_effect_choice(
    state: MatchState,
    action: ActionRequest,
    events: list[GameEvent],
) -> None:
    pending = state.pending_choice
    if pending is None or pending.choice_type != "multi_player_effect_selection":
        raise IllegalActionError("no multi-player effect choice is pending")
    if action.player_id != pending.player_id:
        raise IllegalActionError("only the pending player may resolve this choice")
    invocation = _find_pending_invocation(state, pending.options.get("invocation_id"))
    if invocation.player_id != state.pending_effects[0].player_id:
        raise IllegalActionError("another player's effects must resolve first")
    choice_type = pending.options.get("multi_player_choice_type")
    if choice_type == "multi_player_deploy_waiting_member":
        _resolve_multi_player_deploy_choice(state, action, pending, events)
    elif choice_type in {
        "multi_player_discard_to_hand_size_then_draw",
        "multi_player_draw_then_discard",
    }:
        _resolve_multi_player_discard_choice(state, action, pending, events)
    else:
        raise IllegalActionError("unsupported multi-player effect choice")
    _advance_multi_player_effect_choice(state, events)


def _resolve_multi_player_deploy_choice(
    state: MatchState,
    action: ActionRequest,
    pending: PendingChoice,
    events: list[GameEvent],
) -> None:
    player_id = pending.player_id
    player = state.players[player_id]
    candidates = list(pending.options.get("candidate_card_instance_ids", []))
    slots = list(pending.options.get("available_slots", []))
    minimum = int(pending.options.get("minimum", 0))
    selected = action.payload.get("selected_card_instance_id")
    slot = action.payload.get("slot")
    if minimum == 0 and selected is None and slot is None:
        _record_multi_player_selection(pending, player_id, {"skipped": True})
        return
    if not isinstance(selected, str) or selected not in candidates:
        raise IllegalActionError("selected Member is not legal for this effect")
    if not isinstance(slot, str) or slot not in slots:
        raise IllegalActionError("selected Member Area slot is not legal")
    if player.member_area.get(slot) is not None:
        raise IllegalActionError("selected Member Area slot is no longer empty")
    if selected not in player.waiting_room:
        raise IllegalActionError("selected Member must remain in Waiting Room")
    player.waiting_room.remove(selected)
    player.member_area[slot] = selected
    player.member_entered_count_this_turn += 1
    if slot not in player.member_areas_entered_this_turn:
        player.member_areas_entered_this_turn.append(slot)
    state.cards[selected].face_up = True
    state.cards[selected].orientation = "wait"
    _record_multi_player_selection(
        pending,
        player_id,
        {"selected_card_instance_id": selected, "slot": slot},
    )
    events.append(
        GameEvent(
            event_type="effect_member_deployed_from_waiting_room",
            player_id=player_id,
            data={
                "invocation_id": pending.options.get("invocation_id"),
                "effect_id": pending.options.get("effect_id"),
                "card_instance_id": selected,
                "slot": slot,
                "orientation": "wait",
            },
            source="player",
        )
    )


def _resolve_multi_player_discard_choice(
    state: MatchState,
    action: ActionRequest,
    pending: PendingChoice,
    events: list[GameEvent],
) -> None:
    player_id = pending.player_id
    player = state.players[player_id]
    candidates = list(pending.options.get("candidate_card_instance_ids", []))
    required = int(pending.options.get("minimum", 0))
    selected_ids = action.payload.get("selected_card_instance_ids", [])
    if not isinstance(selected_ids, list) or any(
        not isinstance(item, str) for item in selected_ids
    ):
        raise IllegalActionError("discard selections must be a list of IDs")
    if (
        len(selected_ids) != required
        or len(selected_ids) != len(set(selected_ids))
        or any(item not in candidates for item in selected_ids)
    ):
        raise IllegalActionError("discard selection is not legal")
    for instance_id in selected_ids:
        if instance_id not in player.hand:
            raise IllegalActionError("discard target must remain in hand")
        player.hand.remove(instance_id)
        player.waiting_room.append(instance_id)
        state.cards[instance_id].face_up = True
    _record_multi_player_selection(
        pending,
        player_id,
        {"selected_card_instance_ids": list(selected_ids)},
    )
    events.append(
        GameEvent(
            event_type="effect_hand_adjustment_discarded",
            player_id=player_id,
            data={
                "invocation_id": pending.options.get("invocation_id"),
                "effect_id": pending.options.get("effect_id"),
                "discarded_card_instance_ids": list(selected_ids),
            },
            source="player",
        )
    )


def _advance_multi_player_effect_choice(
    state: MatchState,
    events: list[GameEvent],
) -> None:
    pending = state.pending_choice
    if pending is None or pending.choice_type != "multi_player_effect_selection":
        return
    player_order = list(pending.options.get("player_order", []))
    current_index = int(pending.options.get("current_index", 0)) + 1
    pending.options["current_index"] = current_index
    while current_index < len(player_order):
        pending.player_id = player_order[current_index]
        _refresh_multi_player_choice_options(state, pending.options)
        if int(pending.options.get("minimum", 0)) > 0:
            return
        _record_multi_player_selection(
            pending,
            pending.player_id,
            {"skipped": True},
        )
        events.append(
            GameEvent(
                event_type="effect_multi_player_choice_skipped",
                player_id=pending.player_id,
                data={
                    "invocation_id": pending.options.get("invocation_id"),
                    "effect_id": pending.options.get("effect_id"),
                    "choice_type": pending.options.get("multi_player_choice_type"),
                },
                source="system",
            )
        )
        current_index += 1
        pending.options["current_index"] = current_index
    _complete_multi_player_effect_choice(state, pending, events)


def _refresh_multi_player_choice_options(
    state: MatchState,
    options: dict[str, Any],
) -> None:
    player_order = list(options.get("player_order", []))
    current_index = int(options.get("current_index", 0))
    player_id = player_order[current_index] if current_index < len(player_order) else None
    options["candidate_card_instance_ids"] = []
    options["available_slots"] = []
    options["minimum"] = 0
    options["maximum"] = 0
    if player_id is None:
        return
    player = state.players[player_id]
    choice_type = options.get("multi_player_choice_type")
    if choice_type == "multi_player_deploy_waiting_member":
        maximum_cost = options.get("maximum_cost")
        candidates = [
            item
            for item in player.waiting_room
            if state.cards[item].card.card_type == options.get("card_type")
            and (
                not isinstance(maximum_cost, int)
                or (state.cards[item].card.cost or 0) <= maximum_cost
            )
        ]
        slots = [
            slot
            for slot in ("left", "center", "right")
            if player.member_area.get(slot) is None
        ]
        options["candidate_card_instance_ids"] = candidates
        options["available_slots"] = slots
        options["minimum"] = 1 if candidates and slots else 0
        options["maximum"] = 1 if candidates and slots else 0
    elif choice_type == "multi_player_discard_to_hand_size_then_draw":
        target = options.get("target_hand_size")
        required = 0
        if isinstance(target, int):
            required = max(0, len(player.hand) - target)
        options["candidate_card_instance_ids"] = list(player.hand)
        options["minimum"] = required
        options["maximum"] = required
    elif choice_type == "multi_player_draw_then_discard":
        discard_amount = options.get("discard_amount")
        required = discard_amount if isinstance(discard_amount, int) else 0
        required = min(max(0, required), len(player.hand))
        options["candidate_card_instance_ids"] = list(player.hand)
        options["minimum"] = required
        options["maximum"] = required


def _record_multi_player_selection(
    pending: PendingChoice,
    player_id: str,
    selection: dict[str, Any],
) -> None:
    selections = pending.options.setdefault("selections", {})
    if not isinstance(selections, dict):
        raise IllegalActionError("multi-player choice selections are invalid")
    selections[player_id] = selection


def _complete_multi_player_effect_choice(
    state: MatchState,
    pending: PendingChoice,
    events: list[GameEvent],
) -> None:
    invocation = _find_pending_invocation(state, pending.options.get("invocation_id"))
    effect = state.effect_definitions[invocation.effect_id]
    state.pending_choice = None
    if pending.options.get("multi_player_choice_type") == (
        "multi_player_discard_to_hand_size_then_draw"
    ):
        amount = int(pending.options.get("draw_amount", 0))
        for player_id in pending.options.get("player_order", []):
            _draw(
                state,
                player_id,
                amount,
                events,
                reason=f"effect:{invocation.effect_id}",
            )
    invocation.resolution_stage = "after_cost"
    if effect.follow_up_choice is not None:
        if _effect_choice_candidates(state, invocation):
            state.pending_choice = None
            return
        _execute_operations(
            state,
            invocation,
            [
                operation
                for operation in effect.actions
                if not _operation_requires_selected_choice(operation)
            ],
            events,
            selected_ids=[],
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
                "multi_player_choice_type": pending.options.get(
                    "multi_player_choice_type"
                ),
                "selections": pending.options.get("selections", {}),
                "trigger": effect.trigger,
                "timing": effect.timing,
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
            if effect is None or trigger not in str(effect.trigger).split("|"):
                continue
            if _source_trigger_disabled(state, source.owner_id, source_id, trigger):
                events.append(
                    GameEvent(
                        event_type="effect_trigger_disabled",
                        player_id=source.owner_id,
                        data={
                            "effect_id": effect_id,
                            "source_card_instance_id": source_id,
                            "trigger": trigger,
                        },
                        source="system",
                    )
                )
                continue
            if _effect_usage_limit_reached(state, effect, source_id):
                continue
            invocation = EffectInvocation(
                invocation_id=_new_invocation_id(state, effect_id, source_id),
                effect_id=effect_id,
                source_card_instance_id=source_id,
                player_id=source.owner_id,
                trigger_event=trigger,
                trigger_data={**trigger_data, "_condition_checked_at_trigger": True},
            )
            unavailable_reason = _effect_unavailable_reason(state, invocation)
            if unavailable_reason is not None:
                events.append(
                    GameEvent(
                        event_type="effect_not_activatable",
                        player_id=source.owner_id,
                        data={
                            "effect_id": effect_id,
                            "source_card_instance_id": source_id,
                            "reason": unavailable_reason,
                            "trigger": trigger,
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
                        "timing": effect.timing,
                        "execution_mode": effect.execution_mode,
                        "is_optional": effect.is_optional,
                    },
                )
            )


def _queue_member_moved_effects(
    state: MatchState,
    player_id: str,
    moved_member_instance_ids: list[str],
    events: list[GameEvent],
    *,
    from_slot: str,
    to_slot: str,
) -> None:
    moved_ids = [
        instance_id
        for instance_id in moved_member_instance_ids
        if instance_id in state.cards
        and state.cards[instance_id].owner_id == player_id
        and state.cards[instance_id].card.card_type == "member"
    ]
    if not moved_ids:
        return
    _queue_triggered_effects(
        state,
        "member_moved",
        events,
        source_instance_ids=moved_ids,
        trigger_data={
            "turn_number": state.turn_number,
            "from_slot": from_slot,
            "to_slot": to_slot,
            "moved_member_instance_ids": list(moved_ids),
        },
    )


def _record_member_area_moved(player: Any, slot: str) -> None:
    if slot not in player.member_areas_moved_this_turn:
        player.member_areas_moved_this_turn.append(slot)


def _source_trigger_disabled(
    state: MatchState,
    player_id: str,
    source_card_instance_id: str,
    trigger: str,
) -> bool:
    for modifier in state.players[player_id].manual_modifiers:
        if (
            modifier.modifier_type != "flag"
            or modifier.flag != "disabled_live_success_effects"
            or modifier.target_card_instance_id != source_card_instance_id
        ):
            continue
        if not isinstance(modifier.value, dict):
            return True
        disabled_trigger = modifier.value.get("trigger")
        if disabled_trigger in {None, trigger}:
            return True
    return False


def _effect_condition_met(
    state: MatchState,
    invocation: EffectInvocation,
) -> bool:
    return _effect_unavailable_reason(state, invocation) is None


def _normalized_card_name(name: str) -> str:
    return "".join(name.split())


def _card_name_matches(actual: str, expected: str) -> bool:
    return _normalized_card_name(actual) == _normalized_card_name(expected)


def _card_name_in(actual: str, expected_names: Iterable[str]) -> bool:
    normalized = _normalized_card_name(actual)
    return normalized in {_normalized_card_name(name) for name in expected_names}


def _effect_unavailable_reason(
    state: MatchState,
    invocation: EffectInvocation,
) -> str | None:
    effect = state.effect_definitions[invocation.effect_id]
    player = state.players[invocation.player_id]
    minimum_energy_deck_cards = effect.condition.get("minimum_energy_deck_cards")
    if isinstance(minimum_energy_deck_cards, int):
        if len(player.energy_deck) < minimum_energy_deck_cards:
            return "energy_deck_empty"
    minimum_energy = effect.condition.get("minimum_active_energy")
    if isinstance(minimum_energy, int):
        active = sum(
            state.cards[item].orientation == "active" for item in player.energy_area
        )
        if active < minimum_energy:
            return "insufficient_active_energy"
    ready_history = effect.condition.get("effect_ready_history")
    if isinstance(ready_history, dict):
        work_key = ready_history.get("work_key")
        ready_type = ready_history.get("ready_type")
        if isinstance(work_key, str) and isinstance(ready_type, str):
            if _effect_ready_flag(work_key, ready_type) not in player.effect_ready_flags_this_turn:
                return "effect_ready_history_missing"
    if effect.condition.get("own_deck_refreshed_this_turn"):
        if not player.refreshed_this_turn:
            return "deck_not_refreshed_this_turn"
    live_judgment_basis = effect.condition.get("live_judgment_basis")
    if isinstance(live_judgment_basis, str):
        summary = state.live_judgment_summary or {}
        if summary.get("basis") != live_judgment_basis:
            return "live_judgment_basis_mismatch"
    opponent = state.players["player_2" if invocation.player_id == "player_1" else "player_1"]
    live_score_relation = effect.condition.get("live_score_relation")
    if live_score_relation == "greater_than_opponent":
        if player.live_result.total_score <= opponent.live_result.total_score:
            return "live_score_not_higher"
    elif live_score_relation == "equal_to_opponent":
        if player.live_result.total_score != opponent.live_result.total_score:
            return "live_score_not_equal"
    excess_heart_count = effect.condition.get("own_excess_heart_count_at_least")
    if isinstance(excess_heart_count, int):
        if _own_excess_heart_count(player) < excess_heart_count:
            return "excess_heart_count_too_low"
    maximum_excess_heart_count = effect.condition.get("own_excess_heart_count_at_most")
    if isinstance(maximum_excess_heart_count, int):
        if _own_excess_heart_count(player) > maximum_excess_heart_count:
            return "excess_heart_count_too_high"
    opponent_excess_heart_count = effect.condition.get(
        "opponent_excess_heart_count_at_least"
    )
    if isinstance(opponent_excess_heart_count, int):
        if _own_excess_heart_count(opponent) < opponent_excess_heart_count:
            return "opponent_excess_heart_count_too_low"
    opponent_success_excess_heart_at_most = effect.condition.get(
        "opponent_success_excess_heart_count_at_most"
    )
    if isinstance(opponent_success_excess_heart_at_most, int):
        if not opponent.live_result.requirements_satisfied:
            return "opponent_live_not_successful"
        if _own_excess_heart_count(opponent) > opponent_success_excess_heart_at_most:
            return "opponent_excess_heart_count_too_high"
    color_excess_heart_count = effect.condition.get(
        "own_excess_heart_color_count_at_least"
    )
    if isinstance(color_excess_heart_count, dict):
        color_slot = color_excess_heart_count.get("color_slot")
        count = color_excess_heart_count.get("count")
        if isinstance(color_slot, str) and isinstance(count, int):
            if _own_excess_heart_color_count(player, color_slot) < count:
                return "excess_heart_color_count_too_low"
    yell_no_blade_or_excess = effect.condition.get(
        "own_yell_no_blade_heartless_or_excess_heart_count_at_least"
    )
    if isinstance(yell_no_blade_or_excess, int):
        no_blade_heartless = (
            _yell_revealed_without_blade_heart_count(state, player) == 0
        )
        enough_excess = _own_excess_heart_count(player) >= yell_no_blade_or_excess
        if not no_blade_heartless and not enough_excess:
            return "yell_revealed_non_blade_heart_exists_and_excess_heart_count_too_low"
    yell_revealed_type = effect.condition.get("yell_revealed_card_type_count_at_least")
    if isinstance(yell_revealed_type, dict):
        card_type = yell_revealed_type.get("card_type")
        count = yell_revealed_type.get("count")
        if isinstance(card_type, str) and isinstance(count, int):
            actual = sum(
                state.cards[item].card.card_type == card_type
                for item in player.live_result.revealed_instance_ids
            )
            if actual < count:
                return "yell_revealed_card_type_count_too_low"
    yell_revealed_work = effect.condition.get("own_yell_revealed_work_count_at_least")
    if isinstance(yell_revealed_work, dict):
        work_key = yell_revealed_work.get("work_key")
        count = yell_revealed_work.get("count")
        if isinstance(work_key, str) and isinstance(count, int):
            actual = sum(
                work_key in state.cards[item].card.work_keys
                for item in player.live_result.revealed_instance_ids
            )
            if actual < count:
                return "yell_revealed_work_count_too_low"
    if effect.condition.get("live_success_any_revealed_live2_stage_heart_variety5_or_member_moved"):
        revealed_live_count = sum(
            state.cards[item].card.card_type == "live"
            for item in player.live_result.revealed_instance_ids
        )
        stage_colors = {
            color
            for item in player.member_area.values()
            if item is not None
            for color in _member_heart_color_slots(state, player.player_id, item)
            if color
            in {"heart01", "heart02", "heart03", "heart04", "heart05", "heart06"}
        }
        if (
            revealed_live_count < 2
            and len(stage_colors) < 5
            and not player.member_areas_entered_this_turn
        ):
            return "live_success_complex_score_condition_not_met"
    yell_revealed_more = effect.condition.get(
        "yell_revealed_card_type_more_than_opponent"
    )
    if isinstance(yell_revealed_more, str):
        own_actual = sum(
            state.cards[item].card.card_type == yell_revealed_more
            for item in player.live_result.revealed_instance_ids
        )
        opponent_actual = sum(
            state.cards[item].card.card_type == yell_revealed_more
            for item in opponent.live_result.revealed_instance_ids
        )
        if own_actual <= opponent_actual:
            return "yell_revealed_card_type_not_more_than_opponent"
    if effect.condition.get("yell_revealed_card_count_less_than_opponent"):
        if len(player.live_result.revealed_instance_ids) >= len(
            opponent.live_result.revealed_instance_ids
        ):
            return "yell_revealed_card_count_not_less_than_opponent"
    yell_revealed_less = effect.condition.get(
        "yell_revealed_card_type_less_than_opponent"
    )
    if isinstance(yell_revealed_less, str):
        own_actual = sum(
            state.cards[item].card.card_type == yell_revealed_less
            for item in player.live_result.revealed_instance_ids
        )
        opponent_actual = sum(
            state.cards[item].card.card_type == yell_revealed_less
            for item in opponent.live_result.revealed_instance_ids
        )
        if own_actual >= opponent_actual:
            return "yell_revealed_card_type_not_less_than_opponent"
    yell_revealed_member_distinct = effect.condition.get(
        "own_yell_revealed_member_distinct_name_count_at_least"
    )
    if isinstance(yell_revealed_member_distinct, dict):
        work_key = yell_revealed_member_distinct.get("work_key")
        count = yell_revealed_member_distinct.get("count")
        if isinstance(work_key, str) and isinstance(count, int):
            distinct_names = {
                state.cards[item].card.name_ja
                for item in player.live_result.revealed_instance_ids
                if state.cards[item].card.card_type == "member"
                and work_key in state.cards[item].card.work_keys
            }
            if len(distinct_names) < count:
                return "yell_revealed_member_distinct_name_count_too_low"
    yell_revealed_member_work_count = effect.condition.get(
        "own_yell_revealed_member_work_count_at_least"
    )
    if isinstance(yell_revealed_member_work_count, dict):
        work_key = yell_revealed_member_work_count.get("work_key")
        count = yell_revealed_member_work_count.get("count")
        if isinstance(work_key, str) and isinstance(count, int):
            actual = sum(
                state.cards[item].card.card_type == "member"
                and work_key in state.cards[item].card.work_keys
                for item in player.live_result.revealed_instance_ids
            )
            if actual < count:
                return "yell_revealed_member_work_count_too_low"
    yell_revealed_member_without_blade_heart = effect.condition.get(
        "own_yell_revealed_member_without_blade_heart_count_at_least"
    )
    if isinstance(yell_revealed_member_without_blade_heart, dict):
        work_key = yell_revealed_member_without_blade_heart.get("work_key")
        count = yell_revealed_member_without_blade_heart.get("count")
        if isinstance(work_key, str) and isinstance(count, int):
            actual = sum(
                state.cards[item].card.card_type == "member"
                and work_key in state.cards[item].card.work_keys
                and not _card_has_blade_heart(state.cards[item].card)
                for item in player.live_result.revealed_instance_ids
            )
            if actual < count:
                return "yell_revealed_member_without_blade_heart_count_too_low"
    yell_revealed_member_heart_colors = effect.condition.get(
        "own_yell_revealed_member_heart_colors_present"
    )
    if isinstance(yell_revealed_member_heart_colors, dict):
        color_slots = yell_revealed_member_heart_colors.get("color_slots")
        work_key = yell_revealed_member_heart_colors.get("work_key")
        if isinstance(color_slots, list) and all(
            isinstance(color, str) for color in color_slots
        ):
            actual = {
                color
                for item in player.live_result.revealed_instance_ids
                if state.cards[item].card.card_type == "member"
                and (
                    not isinstance(work_key, str)
                    or work_key in state.cards[item].card.work_keys
                )
                for color, amount in state.cards[item].card.basic_hearts.items()
                if amount > 0
            }
            if not set(color_slots).issubset(actual):
                return "yell_revealed_member_heart_colors_missing"
    yell_revealed_special_count = effect.condition.get(
        "own_yell_revealed_special_blade_heart_count_at_least"
    )
    if isinstance(yell_revealed_special_count, dict):
        effect_type = yell_revealed_special_count.get("effect_type")
        count = yell_revealed_special_count.get("count")
        card_type = yell_revealed_special_count.get("card_type")
        work_key = yell_revealed_special_count.get("work_key")
        if isinstance(effect_type, str) and isinstance(count, int):
            actual = sum(
                any(
                    special.effect_type == effect_type
                    for special in state.cards[item].card.special_blade_hearts
                )
                and (
                    not isinstance(card_type, str)
                    or state.cards[item].card.card_type == card_type
                )
                and (
                    not isinstance(work_key, str)
                    or work_key in state.cards[item].card.work_keys
                )
                for item in player.live_result.revealed_instance_ids
            )
            if actual < count:
                return "yell_revealed_special_blade_heart_count_too_low"
    if effect.condition.get("own_energy_less_than_opponent"):
        if len(player.energy_area) >= len(opponent.energy_area):
            return "energy_count_not_lower"
    if effect.condition.get("own_energy_more_than_opponent"):
        if len(player.energy_area) <= len(opponent.energy_area):
            return "energy_count_not_higher"
    exact_energy_count = effect.condition.get("own_energy_count_exact")
    if isinstance(exact_energy_count, int):
        if len(player.energy_area) != exact_energy_count:
            return "energy_count_not_exact"
    if effect.condition.get("own_hand_more_than_opponent"):
        if len(player.hand) <= len(opponent.hand):
            return "hand_count_not_higher"
    maximum_hand_count = effect.condition.get("own_hand_count_at_most")
    if isinstance(maximum_hand_count, int):
        if len(player.hand) > maximum_hand_count:
            return "hand_count_too_high"
    if effect.condition.get("own_success_live_count_less_than_opponent"):
        if len(player.success_live_area) >= len(opponent.success_live_area):
            return "success_live_count_not_lower"
    if effect.condition.get("own_success_live_count_equals_opponent"):
        if len(player.success_live_area) != len(opponent.success_live_area):
            return "success_live_count_not_equal"
    turn_number_exact = effect.condition.get("turn_number_exact")
    if isinstance(turn_number_exact, int):
        if state.turn_number != turn_number_exact:
            return "turn_number_mismatch"
    forbidden_hand_type = effect.condition.get("own_hand_has_no_card_type")
    if isinstance(forbidden_hand_type, str):
        if any(
            state.cards[item].card.card_type == forbidden_hand_type
            for item in player.hand
        ):
            return "hand_contains_forbidden_card_type"
    success_score = effect.condition.get("success_live_score_at_least")
    if isinstance(success_score, int):
        total = sum(
            _card_score(state, player.player_id, item) for item in player.success_live_area
        )
        if total < success_score:
            return "success_live_score_too_low"
    if effect.condition.get("success_live_score_more_than_opponent"):
        own_total = sum(
            _card_score(state, player.player_id, item) for item in player.success_live_area
        )
        opponent_total = sum(
            _card_score(state, opponent.player_id, item)
            for item in opponent.success_live_area
        )
        if own_total <= opponent_total:
            return "success_live_score_not_higher"
    maximum_success_score = effect.condition.get("success_live_score_at_most")
    if isinstance(maximum_success_score, int):
        total = sum(
            _card_score(state, player.player_id, item) for item in player.success_live_area
        )
        if total > maximum_success_score:
            return "success_live_score_too_high"
    success_count = effect.condition.get("success_live_count_at_least")
    if isinstance(success_count, int):
        if len(player.success_live_area) < success_count:
            return "success_live_count_too_low"
    any_success_count = effect.condition.get("any_success_live_count_at_least")
    if isinstance(any_success_count, int):
        if not any(
            len(target_player.success_live_area) >= any_success_count
            for target_player in state.players.values()
        ):
            return "any_success_live_count_too_low"
    maximum_success_count = effect.condition.get("success_live_count_at_most")
    if isinstance(maximum_success_count, int):
        if len(player.success_live_area) > maximum_success_count:
            return "success_live_count_too_high"
    total_success_count = effect.condition.get("total_success_live_count_at_least")
    if isinstance(total_success_count, int):
        if (
            len(player.success_live_area)
            + len(opponent.success_live_area)
            < total_success_count
        ):
            return "total_success_live_count_too_low"
    success_work = effect.condition.get("success_live_work_count_at_least")
    if isinstance(success_work, dict):
        work_key = success_work.get("work_key")
        count = success_work.get("count")
        if isinstance(work_key, str) and isinstance(count, int):
            actual = sum(
                work_key in state.cards[item].card.work_keys
                for item in player.success_live_area
            )
            if actual < count:
                return "success_live_work_count_too_low"
    success_unit = effect.condition.get("success_live_unit_count_at_least")
    if isinstance(success_unit, dict):
        unit_key = success_unit.get("unit_key")
        count = success_unit.get("count")
        if isinstance(unit_key, str) and isinstance(count, int):
            actual = sum(
                unit_key in state.cards[item].card.unit_keys
                for item in player.success_live_area
            )
            if actual < count:
                return "success_live_unit_count_too_low"
    success_name = effect.condition.get("success_live_name_count_at_least")
    if isinstance(success_name, dict):
        name_ja = success_name.get("name_ja")
        count = success_name.get("count")
        if isinstance(name_ja, str) and isinstance(count, int):
            actual = sum(
                _card_name_matches(state.cards[item].card.name_ja, name_ja)
                for item in player.success_live_area
            )
            if actual < count:
                return "success_live_name_count_too_low"
    live_area_count = effect.condition.get("live_area_count_at_least")
    if isinstance(live_area_count, int):
        if len(player.live_area) < live_area_count:
            return "live_area_count_too_low"
    live_area_score_at_most = effect.condition.get("live_area_score_at_most")
    if isinstance(live_area_score_at_most, int):
        if not any(
            state.cards[item].card.card_type == "live"
            and _card_score(state, player.player_id, item) <= live_area_score_at_most
            for item in player.live_area
        ):
            return "live_area_score_too_high"
    live_area_card = effect.condition.get("live_area_card_exists")
    if isinstance(live_area_card, dict):
        card_type = live_area_card.get("card_type")
        work_key = live_area_card.get("work_key")
        unit_key = live_area_card.get("unit_key")
        exclude_name_ja = live_area_card.get("exclude_name_ja")
        if not any(
            (not isinstance(card_type, str) or state.cards[item].card.card_type == card_type)
            and (
                not isinstance(work_key, str)
                or work_key in state.cards[item].card.work_keys
            )
            and (
                not isinstance(unit_key, str)
                or unit_key in state.cards[item].card.unit_keys
            )
            and (
                not isinstance(exclude_name_ja, str)
                or not _card_name_matches(
                    state.cards[item].card.name_ja, exclude_name_ja
                )
            )
            for item in player.live_area
        ):
            return "live_area_card_unavailable"
    live_area_work = effect.condition.get("live_area_work_count_at_least")
    if isinstance(live_area_work, dict):
        work_key = live_area_work.get("work_key")
        count = live_area_work.get("count")
        if isinstance(work_key, str) and isinstance(count, int):
            actual = sum(
                work_key in state.cards[item].card.work_keys
                for item in player.live_area
            )
            if actual < count:
                return "live_area_work_count_too_low"
    live_area_unit = effect.condition.get("live_area_unit_count_at_least")
    if isinstance(live_area_unit, dict):
        unit_key = live_area_unit.get("unit_key")
        count = live_area_unit.get("count")
        if isinstance(unit_key, str) and isinstance(count, int):
            actual = sum(
                unit_key in state.cards[item].card.unit_keys
                for item in player.live_area
            )
            if actual < count:
                return "live_area_unit_count_too_low"
    live_required_heart = effect.condition.get("live_area_required_heart_at_least")
    if isinstance(live_required_heart, dict):
        color_slot = live_required_heart.get("color_slot")
        count = live_required_heart.get("count")
        if isinstance(color_slot, str) and isinstance(count, int):
            actual = sum(
                state.cards[item].card.required_hearts.get(color_slot, 0)
                for item in player.live_area
            )
            if actual < count:
                return "live_area_required_heart_too_low"
    live_work_required_total = effect.condition.get(
        "live_area_work_required_heart_total_at_least"
    )
    if isinstance(live_work_required_total, dict):
        work_key = live_work_required_total.get("work_key")
        count = live_work_required_total.get("count")
        if isinstance(work_key, str) and isinstance(count, int):
            if not any(
                state.cards[item].card.card_type == "live"
                and work_key in state.cards[item].card.work_keys
                and sum(
                    amount
                    for amount in state.cards[item].card.required_hearts.values()
                    if amount > 0
                )
                >= count
                for item in player.live_area
            ):
                return "live_area_work_required_heart_total_too_low"
    live_or_success_required = effect.condition.get(
        "live_or_success_required_heart_at_least"
    )
    if isinstance(live_or_success_required, dict):
        color_slot = live_or_success_required.get("color_slot")
        count = live_or_success_required.get("count")
        work_key = live_or_success_required.get("work_key")
        if isinstance(color_slot, str) and isinstance(count, int):
            actual = sum(
                state.cards[item].card.required_hearts.get(color_slot, 0)
                for item in [*player.live_area, *player.success_live_area]
                if not isinstance(work_key, str)
                or work_key in state.cards[item].card.work_keys
            )
            if actual < count:
                return "live_or_success_required_heart_too_low"
    waiting_room_count = effect.condition.get("waiting_room_count_at_least")
    if isinstance(waiting_room_count, int):
        if len(player.waiting_room) < waiting_room_count:
            return "waiting_room_count_too_low"
    waiting_live_unit = effect.condition.get("waiting_room_live_unit_count_at_least")
    if isinstance(waiting_live_unit, dict):
        unit_key = waiting_live_unit.get("unit_key")
        count = waiting_live_unit.get("count")
        if isinstance(unit_key, str) and isinstance(count, int):
            actual = sum(
                state.cards[item].card.card_type == "live"
                and unit_key in state.cards[item].card.unit_keys
                for item in player.waiting_room
            )
            if actual < count:
                return "waiting_room_live_unit_count_too_low"
    waiting_live_name_contains = effect.condition.get("waiting_room_live_name_contains")
    if isinstance(waiting_live_name_contains, str):
        if not any(
            state.cards[item].card.card_type == "live"
            and waiting_live_name_contains in state.cards[item].card.name_ja
            for item in player.waiting_room
        ):
            return "waiting_room_live_name_missing"
    waiting_live_work_distinct = effect.condition.get(
        "waiting_room_live_work_distinct_name_count_at_least"
    )
    if isinstance(waiting_live_work_distinct, dict):
        work_key = waiting_live_work_distinct.get("work_key")
        count = waiting_live_work_distinct.get("count")
        if isinstance(work_key, str) and isinstance(count, int):
            actual = _waiting_room_live_work_distinct_name_count(
                state,
                invocation.player_id,
                work_key,
            )
            if actual < count:
                return "waiting_room_live_work_distinct_name_count_too_low"
    own_energy_count = effect.condition.get("own_energy_count_at_least")
    if isinstance(own_energy_count, int):
        if len(player.energy_area) < own_energy_count:
            return "energy_count_too_low"
    total_energy_count = effect.condition.get("total_energy_count_at_least")
    if isinstance(total_energy_count, int):
        if len(player.energy_area) + len(opponent.energy_area) < total_energy_count:
            return "total_energy_count_too_low"
    opponent_success_score = effect.condition.get("opponent_success_live_score_at_least")
    if isinstance(opponent_success_score, int):
        total = sum(
            _card_score(state, opponent.player_id, item)
            for item in opponent.success_live_area
        )
        if total < opponent_success_score:
            return "opponent_success_live_score_too_low"
    opponent_success_count = effect.condition.get("opponent_success_live_count_at_least")
    if isinstance(opponent_success_count, int):
        if len(opponent.success_live_area) < opponent_success_count:
            return "opponent_success_live_count_too_low"
    opponent_stage_count = effect.condition.get("opponent_stage_member_count_at_least")
    if isinstance(opponent_stage_count, int):
        actual = sum(1 for item in opponent.member_area.values() if item is not None)
        if actual < opponent_stage_count:
            return "opponent_stage_member_count_too_low"
    played_from_zone_not = effect.condition.get("played_from_zone_not")
    if isinstance(played_from_zone_not, str):
        if played_from_zone_not == invocation.trigger_data.get("source_zone"):
            return "played_from_zone_mismatch"
    played_from_zone = effect.condition.get("played_from_zone")
    if isinstance(played_from_zone, str):
        if played_from_zone != invocation.trigger_data.get("source_zone"):
            return "played_from_zone_mismatch"
    trigger_member_id = invocation.trigger_data.get("card_instance_id")
    if not isinstance(trigger_member_id, str):
        moved_ids = invocation.trigger_data.get("moved_member_instance_ids")
        if (
            isinstance(moved_ids, list)
            and invocation.source_card_instance_id in moved_ids
        ):
            trigger_member_id = invocation.source_card_instance_id
    if effect.condition.get("trigger_member_is_source"):
        if trigger_member_id != invocation.source_card_instance_id:
            return "trigger_member_not_source"
    if effect.condition.get("trigger_member_not_source"):
        if trigger_member_id is None or trigger_member_id == invocation.source_card_instance_id:
            return "trigger_member_is_source"
    trigger_member_cost = effect.condition.get("trigger_member_cost_exact")
    if isinstance(trigger_member_cost, int):
        if (
            not isinstance(trigger_member_id, str)
            or trigger_member_id not in state.cards
            or (state.cards[trigger_member_id].card.cost or 0) != trigger_member_cost
        ):
            return "trigger_member_cost_mismatch"
    trigger_member_work = effect.condition.get("trigger_member_work_key")
    if isinstance(trigger_member_work, str):
        if (
            not isinstance(trigger_member_id, str)
            or trigger_member_id not in state.cards
            or trigger_member_work not in state.cards[trigger_member_id].card.work_keys
        ):
            return "trigger_member_work_mismatch"
    trigger_member_unit = effect.condition.get("trigger_member_unit_key")
    if isinstance(trigger_member_unit, str):
        if (
            not isinstance(trigger_member_id, str)
            or trigger_member_id not in state.cards
            or trigger_member_unit not in state.cards[trigger_member_id].card.unit_keys
        ):
            return "trigger_member_unit_mismatch"
    source_orientation = effect.condition.get("source_orientation")
    if isinstance(source_orientation, str):
        if state.cards[invocation.source_card_instance_id].orientation != source_orientation:
            return "source_orientation_mismatch"
    source_zone = effect.condition.get("source_zone")
    if source_zone == "stage" and (
        _top_member_slot(player, invocation.source_card_instance_id) is None
    ):
        return "source_zone_mismatch"
    source_score_exact = effect.condition.get("source_score_exact")
    if isinstance(source_score_exact, int):
        if (
            _card_score(
                state,
                invocation.player_id,
                invocation.source_card_instance_id,
            )
            != source_score_exact
        ):
            return "source_score_mismatch"
    source_blade_at_least = effect.condition.get("source_blade_at_least")
    if isinstance(source_blade_at_least, int):
        actual = _member_base_blade(
            state,
            invocation.player_id,
            invocation.source_card_instance_id,
        ) + _target_modifier_total(
            player,
            "blade",
            invocation.source_card_instance_id,
        )
        if actual < source_blade_at_least:
            return "source_blade_too_low"
    if effect.condition.get("source_not_moved_this_turn"):
        source_slot = _top_member_slot(player, invocation.source_card_instance_id)
        if source_slot is None:
            return "source_slot_mismatch"
        if source_slot in player.member_areas_moved_this_turn:
            return "source_moved_this_turn"
    moved_slot_member = effect.condition.get("own_stage_slot_member_moved_this_turn")
    if isinstance(moved_slot_member, dict):
        slot = moved_slot_member.get("slot")
        work_key = moved_slot_member.get("work_key")
        if not isinstance(slot, str) or slot not in player.member_area:
            return "stage_slot_invalid"
        if slot not in player.member_areas_moved_this_turn:
            return "stage_slot_member_not_moved_this_turn"
        instance_id = player.member_area.get(slot)
        if instance_id is None:
            return "stage_slot_member_missing"
        if isinstance(work_key, str) and work_key not in state.cards[instance_id].card.work_keys:
            return "stage_slot_member_work_mismatch"
    source_attached_energy_count = effect.condition.get(
        "source_attached_energy_count_at_least"
    )
    if isinstance(source_attached_energy_count, int):
        source_slot = _top_member_slot(player, invocation.source_card_instance_id)
        if source_slot is None:
            return "source_slot_mismatch"
        actual = sum(
            state.cards[item].card.card_type == "energy"
            for item in player.member_area_attachments[source_slot]
        )
        if actual < source_attached_energy_count:
            return "source_attached_energy_count_too_low"
    if effect.condition.get("own_stage_has_attached_energy_member"):
        if not any(
            any(
                state.cards[attached_id].card.card_type == "energy"
                for attached_id in player.member_area_attachments[slot]
            )
            for slot, instance_id in player.member_area.items()
            if instance_id is not None
        ):
            return "stage_attached_energy_member_missing"
    if effect.condition.get("opposing_member_cost_greater_than_source"):
        source_slot = _top_member_slot(player, invocation.source_card_instance_id)
        if source_slot is None:
            return "source_slot_mismatch"
        opposing_id = opponent.member_area.get(source_slot)
        if opposing_id is None:
            return "opposing_member_missing"
        source_cost = state.cards[invocation.source_card_instance_id].card.cost or 0
        opposing_cost = state.cards[opposing_id].card.cost or 0
        if opposing_cost <= source_cost:
            return "opposing_member_cost_not_higher_than_source"
    own_stage_cost = effect.condition.get("own_stage_member_cost_at_least")
    if isinstance(own_stage_cost, int):
        if not any(
            (state.cards[item].card.cost or 0) >= own_stage_cost
            for item in player.member_area.values()
            if item is not None
        ):
            return "stage_member_cost_too_low"
    if effect.condition.get("own_stage_member_cost_greater_than_source"):
        source_cost = state.cards[invocation.source_card_instance_id].card.cost or 0
        if not any(
            (state.cards[item].card.cost or 0) > source_cost
            for item in player.member_area.values()
            if item is not None
        ):
            return "stage_member_cost_not_higher_than_source"
    if effect.condition.get("own_side_stage_member_costs_equal"):
        left_id = player.member_area.get("left")
        right_id = player.member_area.get("right")
        if left_id is None or right_id is None:
            return "side_stage_member_missing"
        left_cost = state.cards[left_id].card.cost
        right_cost = state.cards[right_id].card.cost
        if left_cost != right_cost:
            return "side_stage_member_cost_mismatch"
    side_original_blade = effect.condition.get(
        "own_side_stage_member_original_blade_exact"
    )
    if isinstance(side_original_blade, int):
        left_id = player.member_area.get("left")
        right_id = player.member_area.get("right")
        if left_id is None or right_id is None:
            return "side_stage_member_missing"
        if any(
            (state.cards[item].card.blade or 0) != side_original_blade
            for item in (left_id, right_id)
        ):
            return "side_stage_member_original_blade_mismatch"
    stage_blade_total = effect.condition.get("own_stage_blade_total_at_least")
    if isinstance(stage_blade_total, int):
        total = sum(
            _member_base_blade(state, invocation.player_id, item)
            + _target_modifier_total(player, "blade", item)
            for item in player.member_area.values()
            if item is not None
        )
        if total < stage_blade_total:
            return "stage_blade_total_too_low"
    stage_work_blade_max = effect.condition.get(
        "own_stage_member_work_blade_count_at_most"
    )
    if isinstance(stage_work_blade_max, dict):
        work_key = stage_work_blade_max.get("work_key")
        minimum_blade = stage_work_blade_max.get("minimum_blade")
        count = stage_work_blade_max.get("count")
        if (
            isinstance(work_key, str)
            and isinstance(minimum_blade, int)
            and isinstance(count, int)
        ):
            actual = sum(
                work_key in state.cards[item].card.work_keys
                and (
                    _member_base_blade(state, invocation.player_id, item)
                    + _target_modifier_total(player, "blade", item)
                )
                >= minimum_blade
                for item in player.member_area.values()
                if item is not None
            )
            if actual > count:
                return "stage_member_work_blade_count_too_high"
    stage_heart_variety = effect.condition.get("own_stage_heart_color_variety_at_least")
    if isinstance(stage_heart_variety, int):
        colors = {
            color
            for item in player.member_area.values()
            if item is not None
            for color, amount in _member_base_hearts(
                state, invocation.player_id, item
            ).items()
            if amount > 0
        }
        if len(colors) < stage_heart_variety:
            return "stage_heart_color_variety_too_low"
    own_stage_count = effect.condition.get("own_stage_member_count_at_least")
    if isinstance(own_stage_count, int):
        if (
            sum(1 for item in player.member_area.values() if item is not None)
            < own_stage_count
        ):
            return "stage_member_count_too_low"
    entered_this_turn_count = effect.condition.get(
        "own_member_entered_count_this_turn_at_least"
    )
    if isinstance(entered_this_turn_count, int):
        if player.member_entered_count_this_turn < entered_this_turn_count:
            return "member_entered_count_this_turn_too_low"
    entered_work = effect.condition.get("own_stage_member_work_entered_this_turn")
    if isinstance(entered_work, str):
        if not any(
            slot in player.member_areas_entered_this_turn
            and item is not None
            and entered_work in state.cards[item].card.work_keys
            for slot, item in player.member_area.items()
        ):
            return "stage_member_work_not_entered_this_turn"
    own_stage_count_exact = effect.condition.get("own_stage_member_count_exact")
    if isinstance(own_stage_count_exact, int):
        if (
            sum(1 for item in player.member_area.values() if item is not None)
            != own_stage_count_exact
        ):
            return "stage_member_count_not_exact"
    own_stage_cost_sum = effect.condition.get("own_stage_member_cost_sum_at_least")
    if isinstance(own_stage_cost_sum, int):
        total = sum(
            state.cards[item].card.cost or 0
            for item in player.member_area.values()
            if item is not None
        )
        if total < own_stage_cost_sum:
            return "stage_member_cost_sum_too_low"
    own_stage_work_cost_sum = effect.condition.get(
        "own_stage_member_work_cost_sum_at_least"
    )
    if isinstance(own_stage_work_cost_sum, dict):
        work_key = own_stage_work_cost_sum.get("work_key")
        count = own_stage_work_cost_sum.get("count")
        if isinstance(work_key, str) and isinstance(count, int):
            total = sum(
                state.cards[item].card.cost or 0
                for item in player.member_area.values()
                if item is not None and work_key in state.cards[item].card.work_keys
            )
            if total < count:
                return "stage_member_work_cost_sum_too_low"
    same_name = effect.condition.get("own_stage_same_name_member_count_at_least")
    if isinstance(same_name, dict):
        work_key = same_name.get("work_key")
        count = same_name.get("count")
        if isinstance(count, int):
            names: Counter[str] = Counter()
            for item in player.member_area.values():
                if item is None:
                    continue
                card = state.cards[item].card
                if isinstance(work_key, str) and work_key not in card.work_keys:
                    continue
                names[card.name_ja] += 1
            if not names or max(names.values()) < count:
                return "same_name_stage_member_count_too_low"
    distinct_name_cost = effect.condition.get(
        "own_stage_distinct_name_and_cost_member_count_at_least"
    )
    if isinstance(distinct_name_cost, int):
        pairs = {
            (state.cards[item].card.name_ja, state.cards[item].card.cost)
            for item in player.member_area.values()
            if item is not None
        }
        if len(pairs) < distinct_name_cost:
            return "stage_distinct_name_cost_count_too_low"
    distinct_cost = effect.condition.get("own_stage_distinct_cost_member_count_at_least")
    if isinstance(distinct_cost, int):
        costs = {
            state.cards[item].card.cost
            for item in player.member_area.values()
            if item is not None
        }
        if len(costs) < distinct_cost:
            return "stage_distinct_cost_count_too_low"
    distinct_unit = effect.condition.get(
        "own_stage_member_unit_distinct_name_count_at_least"
    )
    if isinstance(distinct_unit, dict):
        unit_key = distinct_unit.get("unit_key")
        count = distinct_unit.get("count")
        if isinstance(unit_key, str) and isinstance(count, int):
            names = {
                state.cards[item].card.name_ja
                for item in player.member_area.values()
                if item is not None and unit_key in state.cards[item].card.unit_keys
            }
            if len(names) < count:
                return "stage_unit_distinct_name_count_too_low"
    distinct_stage_waiting_unit = effect.condition.get(
        "own_stage_waiting_member_unit_distinct_name_count_at_least"
    )
    if isinstance(distinct_stage_waiting_unit, dict):
        unit_key = distinct_stage_waiting_unit.get("unit_key")
        count = distinct_stage_waiting_unit.get("count")
        if isinstance(unit_key, str) and isinstance(count, int):
            instance_ids = [
                *(item for item in player.member_area.values() if item is not None),
                *player.waiting_room,
            ]
            names = {
                state.cards[item].card.name_ja
                for item in instance_ids
                if state.cards[item].card.card_type == "member"
                and unit_key in state.cards[item].card.unit_keys
            }
            if len(names) < count:
                return "stage_waiting_unit_distinct_name_count_too_low"
    distinct_stage_waiting_work = effect.condition.get(
        "own_stage_waiting_member_work_distinct_name_count_at_least"
    )
    if isinstance(distinct_stage_waiting_work, dict):
        work_key = distinct_stage_waiting_work.get("work_key")
        count = distinct_stage_waiting_work.get("count")
        if isinstance(work_key, str) and isinstance(count, int):
            names = {
                state.cards[item].card.name_ja
                for item in [
                    *(item for item in player.member_area.values() if item is not None),
                    *player.waiting_room,
                ]
                if state.cards[item].card.card_type == "member"
                and work_key in state.cards[item].card.work_keys
            }
            if len(names) < count:
                return "stage_waiting_work_distinct_name_count_too_low"
    stage_heart = effect.condition.get("own_stage_heart_at_least")
    if isinstance(stage_heart, dict):
        color_slot = stage_heart.get("color_slot")
        count = stage_heart.get("count")
        work_key = stage_heart.get("work_key")
        unit_key = stage_heart.get("unit_key")
        if isinstance(color_slot, str) and isinstance(count, int):
            actual = _stage_heart_total(
                state,
                invocation.player_id,
                color_slot,
                work_key=work_key,
                unit_key=unit_key,
            )
            if actual < count:
                return "stage_heart_count_too_low"
    stage_heart_colors = effect.condition.get("own_stage_heart_colors_present")
    if isinstance(stage_heart_colors, list) and all(
        isinstance(color, str) for color in stage_heart_colors
    ):
        actual = {
            color
            for item in player.member_area.values()
            if item is not None
            for color, amount in state.cards[item].card.basic_hearts.items()
            if amount > 0
        }
        if not set(stage_heart_colors).issubset(actual):
            return "stage_heart_colors_missing"
    stage_total_heart = effect.condition.get("own_stage_total_heart_at_least")
    if isinstance(stage_total_heart, dict):
        count = stage_total_heart.get("count")
        work_key = stage_total_heart.get("work_key")
        unit_key = stage_total_heart.get("unit_key")
        if isinstance(count, int):
            actual = _stage_total_heart_count(
                state,
                invocation.player_id,
                work_key=work_key,
                unit_key=unit_key,
            )
            if actual < count:
                return "stage_total_heart_count_too_low"
    if effect.condition.get("own_stage_total_heart_more_than_opponent"):
        own_total = _stage_total_heart_count(state, invocation.player_id)
        opponent_total = _stage_total_heart_count(state, opponent.player_id)
        if own_total <= opponent_total:
            return "stage_total_heart_count_not_higher_than_opponent"
    if effect.condition.get("own_stage_member_cost_higher_than_all_opponent"):
        own_costs = [
            state.cards[item].card.cost or 0
            for item in player.member_area.values()
            if item is not None
        ]
        opponent_costs = [
            state.cards[item].card.cost or 0
            for item in opponent.member_area.values()
            if item is not None
        ]
        if not own_costs or any(
            own_cost <= opponent_cost
            for own_cost in own_costs
            for opponent_cost in opponent_costs
        ):
            return "stage_member_cost_not_higher_than_all_opponent"
    if effect.condition.get("source_has_most_stage_hearts"):
        source_id = invocation.source_card_instance_id
        source_total = _member_nonstatic_heart_total(
            state,
            invocation.player_id,
            source_id,
        )
        if source_total <= 0:
            return "source_stage_heart_count_too_low"
        for target_player_id, target_player in state.players.items():
            for item in target_player.member_area.values():
                if item is None or item == source_id:
                    continue
                target_total = _member_nonstatic_heart_total(
                    state,
                    target_player_id,
                    item,
                )
                if target_total >= source_total:
                    return "source_stage_heart_count_not_highest"
    stage_extra_heart = effect.condition.get(
        "own_stage_member_more_than_original_heart_count_at_least"
    )
    if isinstance(stage_extra_heart, dict):
        count = stage_extra_heart.get("count")
        work_key = stage_extra_heart.get("work_key")
        unit_key = stage_extra_heart.get("unit_key")
        if isinstance(count, int):
            actual = _stage_member_more_than_original_heart_count(
                state,
                invocation.player_id,
                work_key=work_key,
                unit_key=unit_key,
            )
            if actual < count:
                return "stage_member_more_than_original_heart_count_too_low"
    stage_member_heart = effect.condition.get("own_stage_member_heart_at_least")
    if isinstance(stage_member_heart, dict):
        color_slot = stage_member_heart.get("color_slot")
        count = stage_member_heart.get("count")
        work_key = stage_member_heart.get("work_key")
        unit_key = stage_member_heart.get("unit_key")
        if isinstance(color_slot, str) and isinstance(count, int):
            if not any(
                _member_heart_count(
                    state,
                    invocation.player_id,
                    item,
                    color_slot,
                    work_key=work_key,
                    unit_key=unit_key,
                )
                >= count
                for item in player.member_area.values()
                if item is not None
            ):
                return "stage_member_heart_count_too_low"
    stage_slot_member_heart = effect.condition.get("own_stage_slot_member_heart_at_least")
    if isinstance(stage_slot_member_heart, dict):
        slot = stage_slot_member_heart.get("slot")
        color_slot = stage_slot_member_heart.get("color_slot")
        count = stage_slot_member_heart.get("count")
        work_key = stage_slot_member_heart.get("work_key")
        unit_key = stage_slot_member_heart.get("unit_key")
        if isinstance(slot, str) and isinstance(color_slot, str) and isinstance(count, int):
            instance_id = player.member_area.get(slot)
            if instance_id is None or _member_heart_count(
                state,
                invocation.player_id,
                instance_id,
                color_slot,
                work_key=work_key,
                unit_key=unit_key,
            ) < count:
                return "stage_slot_member_heart_count_too_low"
    stage_slot_member_work = effect.condition.get("own_stage_slot_member_work")
    if isinstance(stage_slot_member_work, dict):
        slot = stage_slot_member_work.get("slot")
        work_key = stage_slot_member_work.get("work_key")
        if isinstance(slot, str) and isinstance(work_key, str):
            instance_id = player.member_area.get(slot)
            if instance_id is None:
                return "stage_slot_member_missing"
            if work_key not in state.cards[instance_id].card.work_keys:
                return "stage_slot_member_work_mismatch"
    center_blade = effect.condition.get("center_member_blade_at_least")
    if isinstance(center_blade, dict):
        count = center_blade.get("count")
        work_key = center_blade.get("work_key")
        center_id = player.member_area.get("center")
        if not isinstance(count, int) or center_id is None:
            return "center_member_blade_too_low"
        center_card = state.cards[center_id].card
        if isinstance(work_key, str) and work_key not in center_card.work_keys:
            return "center_member_work_mismatch"
        actual = _member_base_blade(
            state, invocation.player_id, center_id
        ) + _target_modifier_total(
            player, "blade", center_id
        )
        if actual < count:
            return "center_member_blade_too_low"
    center_work_cost = effect.condition.get(
        "center_member_work_cost_greater_than_opponent"
    )
    if isinstance(center_work_cost, dict):
        work_key = center_work_cost.get("work_key")
        own_center_id = player.member_area.get("center")
        opponent_center_id = opponent.member_area.get("center")
        if own_center_id is None or opponent_center_id is None:
            return "center_member_missing"
        own_center = state.cards[own_center_id].card
        opponent_center = state.cards[opponent_center_id].card
        if isinstance(work_key, str) and work_key not in own_center.work_keys:
            return "center_member_work_mismatch"
        if (own_center.cost or 0) <= (opponent_center.cost or 0):
            return "center_member_cost_not_higher_than_opponent"
    center_work_minimum_cost = effect.condition.get(
        "own_center_member_work_cost_at_least"
    )
    if isinstance(center_work_minimum_cost, dict):
        work_key = center_work_minimum_cost.get("work_key")
        count = center_work_minimum_cost.get("count")
        center_id = player.member_area.get("center")
        if center_id is None or not isinstance(count, int):
            return "center_member_cost_too_low"
        center_card = state.cards[center_id].card
        if isinstance(work_key, str) and work_key not in center_card.work_keys:
            return "center_member_work_mismatch"
        if (center_card.cost or 0) < count:
            return "center_member_cost_too_low"
    if effect.condition.get("own_center_member_highest_cost"):
        center_id = player.member_area.get("center")
        if center_id is None:
            return "center_member_missing"
        center_cost = state.cards[center_id].card.cost or 0
        if any(
            (state.cards[item].card.cost or 0) > center_cost
            for slot, item in player.member_area.items()
            if slot != "center" and item is not None
        ):
            return "center_member_cost_not_highest"
    waiting_member_work = effect.condition.get("waiting_room_member_work_count_at_least")
    if isinstance(waiting_member_work, dict):
        work_key = waiting_member_work.get("work_key")
        count = waiting_member_work.get("count")
        if isinstance(work_key, str) and isinstance(count, int):
            actual = sum(
                state.cards[item].card.card_type == "member"
                and work_key in state.cards[item].card.work_keys
                for item in player.waiting_room
            )
            if actual < count:
                return "waiting_room_member_work_count_too_low"
    waiting_work = effect.condition.get("waiting_room_work_count_at_least")
    if isinstance(waiting_work, dict):
        work_key = waiting_work.get("work_key")
        count = waiting_work.get("count")
        if isinstance(work_key, str) and isinstance(count, int):
            actual = sum(
                work_key in state.cards[item].card.work_keys
                for item in player.waiting_room
            )
            if actual < count:
                return "waiting_room_work_count_too_low"
    total_stage_count = effect.condition.get("total_stage_member_count_at_least")
    if isinstance(total_stage_count, int):
        total = sum(
            1
            for target_player in state.players.values()
            for item in target_player.member_area.values()
            if item is not None
        )
        if total < total_stage_count:
            return "total_stage_member_count_too_low"
    source_slot = effect.condition.get("source_slot")
    if isinstance(source_slot, str):
        if _top_member_slot(player, invocation.source_card_instance_id) != source_slot:
            return "source_slot_mismatch"
    if effect.condition.get("any_stage_member_cost_at_least"):
        minimum_cost = effect.condition["any_stage_member_cost_at_least"]
        if isinstance(minimum_cost, int) and not any(
            (state.cards[item].card.cost or 0) >= minimum_cost
            for target_player in state.players.values()
            for item in target_player.member_area.values()
            if item is not None
        ):
            return "stage_member_cost_too_low"
    own_stage_work = effect.condition.get("own_stage_member_work_count_at_least")
    if isinstance(own_stage_work, dict):
        work_key = own_stage_work.get("work_key")
        count = own_stage_work.get("count")
        minimum_cost = own_stage_work.get("minimum_cost")
        if isinstance(work_key, str) and isinstance(count, int):
            actual = 0
            for item in player.member_area.values():
                if item is None:
                    continue
                card = state.cards[item].card
                if work_key not in card.work_keys:
                    continue
                if isinstance(minimum_cost, int) and (card.cost or 0) < minimum_cost:
                    continue
                actual += 1
            if actual < count:
                return "stage_member_work_count_too_low"
    own_stage_unit = effect.condition.get("own_stage_member_unit_count_at_least")
    if isinstance(own_stage_unit, dict):
        unit_key = own_stage_unit.get("unit_key")
        count = own_stage_unit.get("count")
        if isinstance(unit_key, str) and isinstance(count, int):
            actual = sum(
                item is not None and unit_key in state.cards[item].card.unit_keys
                for item in player.member_area.values()
            )
            if actual < count:
                return "stage_member_unit_count_too_low"
    own_other_stage_unit = effect.condition.get(
        "own_stage_other_member_unit_count_at_least"
    )
    if isinstance(own_other_stage_unit, dict):
        unit_key = own_other_stage_unit.get("unit_key")
        count = own_other_stage_unit.get("count")
        if isinstance(unit_key, str) and isinstance(count, int):
            actual = sum(
                item is not None
                and item != invocation.source_card_instance_id
                and unit_key in state.cards[item].card.unit_keys
                for item in player.member_area.values()
            )
            if actual < count:
                return "stage_other_member_unit_count_too_low"
    only_unit = effect.condition.get("own_stage_members_only_unit_key")
    if isinstance(only_unit, str):
        stage_members = [item for item in player.member_area.values() if item is not None]
        if not stage_members or any(
            only_unit not in state.cards[item].card.unit_keys for item in stage_members
        ):
            return "stage_member_unit_mismatch"
    only_work = effect.condition.get("own_stage_members_only_work_key")
    if isinstance(only_work, str):
        stage_members = [item for item in player.member_area.values() if item is not None]
        if not stage_members or any(
            only_work not in state.cards[item].card.work_keys for item in stage_members
        ):
            return "stage_member_work_mismatch"
    if effect.condition.get("own_live_has_card_without_live_start_or_success_effects"):
        if not _live_area_has_card_without_effect_timings(
            state,
            invocation.player_id,
            {"live_start", "live_success"},
        ):
            return "live_card_without_start_or_success_effect_missing"
    required_units = effect.condition.get("own_stage_member_unit_keys_present")
    if isinstance(required_units, list) and all(
        isinstance(unit_key, str) for unit_key in required_units
    ):
        present = {
            unit_key
            for item in player.member_area.values()
            if item is not None
            for unit_key in state.cards[item].card.unit_keys
        }
        if not set(required_units).issubset(present):
            return "stage_member_unit_missing"
    slot_names = effect.condition.get("own_stage_slot_names")
    if isinstance(slot_names, dict):
        for slot, name_ja in slot_names.items():
            if not isinstance(slot, str) or not isinstance(name_ja, str):
                continue
            instance_id = player.member_area.get(slot)
            if instance_id is None or not _card_name_matches(
                state.cards[instance_id].card.name_ja, name_ja
            ):
                return "stage_slot_name_mismatch"
    named_cost_relation = effect.condition.get(
        "own_stage_named_member_cost_greater_than_named"
    )
    if isinstance(named_cost_relation, dict):
        lower_name = named_cost_relation.get("lower_name_ja")
        higher_name = named_cost_relation.get("higher_name_ja")
        if isinstance(lower_name, str) and isinstance(higher_name, str):
            lower_cost = None
            higher_cost = None
            for instance_id in player.member_area.values():
                if instance_id is None:
                    continue
                card = state.cards[instance_id].card
                if _card_name_matches(card.name_ja, lower_name):
                    lower_cost = card.cost or 0
                elif _card_name_matches(card.name_ja, higher_name):
                    higher_cost = card.cost or 0
            if lower_cost is None or higher_cost is None:
                return "named_stage_member_missing"
            if higher_cost <= lower_cost:
                return "named_stage_member_cost_not_higher"
    name_any = effect.condition.get("own_stage_member_name_any")
    if isinstance(name_any, list) and all(isinstance(item, str) for item in name_any):
        if not any(
            item is not None and _card_name_in(state.cards[item].card.name_ja, name_any)
            for item in player.member_area.values()
        ):
            return "stage_member_name_missing"
    names_present = effect.condition.get("own_stage_member_names_present")
    if isinstance(names_present, list) and all(
        isinstance(item, str) for item in names_present
    ):
        actual_names = {
            _normalized_card_name(state.cards[item].card.name_ja)
            for item in player.member_area.values()
            if item is not None
        }
        required_names = {_normalized_card_name(name) for name in names_present}
        if not required_names.issubset(actual_names):
            return "stage_member_names_missing"
    names_any_distinct = effect.condition.get(
        "own_stage_member_names_any_distinct_count_at_least"
    )
    if isinstance(names_any_distinct, dict):
        raw_names = names_any_distinct.get("name_ja_any")
        count = names_any_distinct.get("count")
        if isinstance(raw_names, list) and isinstance(count, int):
            allowed = {
                _normalized_card_name(item) for item in raw_names if isinstance(item, str)
            }
            actual = {
                _normalized_card_name(state.cards[item].card.name_ja)
                for item in player.member_area.values()
                if item is not None
                and _normalized_card_name(state.cards[item].card.name_ja) in allowed
            }
            if len(actual) < count:
                return "stage_member_names_any_distinct_count_too_low"
    opponent_wait_count = effect.condition.get("opponent_stage_wait_member_count_at_least")
    if isinstance(opponent_wait_count, int):
        actual = sum(
            item is not None and state.cards[item].orientation == "wait"
            for item in opponent.member_area.values()
        )
        if actual < opponent_wait_count:
            return "opponent_wait_member_count_too_low"
    if effect.condition.get("own_stage_cost_sum_less_than_opponent"):
        own_total = sum(
            state.cards[item].card.cost or 0
            for item in player.member_area.values()
            if item is not None
        )
        opponent_total = sum(
            state.cards[item].card.cost or 0
            for item in opponent.member_area.values()
            if item is not None
        )
        if own_total >= opponent_total:
            return "stage_cost_sum_not_lower"
    baton_entered_work = effect.condition.get("own_baton_entered_stage_member_work_count_at_least")
    if isinstance(baton_entered_work, dict):
        work_key = baton_entered_work.get("work_key")
        required_count = baton_entered_work.get("count")
        if not isinstance(work_key, str) or not isinstance(required_count, int):
            return "invalid_baton_entered_work_condition"
        actual = 0
        for slot in player.member_areas_baton_entered_this_turn:
            instance_id = player.member_area.get(slot)
            if instance_id is None:
                continue
            if work_key in state.cards[instance_id].card.work_keys:
                actual += 1
        if actual < required_count:
            return "baton_entered_stage_member_work_count_too_low"
    replacement_id = invocation.trigger_data.get("replacement_card_instance_id")
    minimum_cost = effect.condition.get("replacement_member_minimum_cost")
    if isinstance(minimum_cost, int):
        if not isinstance(replacement_id, str):
            return "replacement_member_unavailable"
        if (state.cards[replacement_id].card.cost or 0) < minimum_cost:
            return "replacement_member_cost_too_low"
    if effect.condition.get("replacement_member_cost_less_than_source"):
        if not isinstance(replacement_id, str):
            return "replacement_member_unavailable"
        source_cost = state.cards[invocation.source_card_instance_id].card.cost or 0
        if (state.cards[replacement_id].card.cost or 0) >= source_cost:
            return "replacement_member_cost_too_high"
    if effect.condition.get("requires_baton_touch"):
        if not invocation.trigger_data.get("used_baton_touch"):
            return "baton_touch_required"
    work_key = effect.condition.get("replacement_member_work_key")
    if isinstance(work_key, str):
        if not isinstance(replacement_id, str):
            return "replacement_member_unavailable"
        if work_key not in state.cards[replacement_id].card.work_keys:
            return "replacement_member_work_mismatch"
    replacement_name = effect.condition.get("replacement_member_name_ja")
    if isinstance(replacement_name, str):
        if not isinstance(replacement_id, str):
            return "replacement_member_unavailable"
        if not _card_name_matches(
            state.cards[replacement_id].card.name_ja, replacement_name
        ):
            return "replacement_member_name_mismatch"
    replacement_name_not = effect.condition.get("replacement_member_name_ja_not")
    if isinstance(replacement_name_not, str):
        if not isinstance(replacement_id, str):
            return "replacement_member_unavailable"
        if _card_name_matches(
            state.cards[replacement_id].card.name_ja, replacement_name_not
        ):
            return "replacement_member_name_forbidden"
    if _effect_uses_inspection_choice(effect):
        return None
    if (
        _effect_uses_cost_card_choice(effect)
        and invocation.resolution_stage == "initial"
    ):
        cost_candidates = _effect_cost_choice_candidates(state, invocation)
        if effect.cost_choice.minimum > 0 and (
            len(cost_candidates) < effect.cost_choice.minimum
            or not _choice_candidates_can_satisfy_condition(
                state, cost_candidates, effect.cost_choice
            )
        ):
            return "cost_choice_candidates_unavailable"
        return None
    if (
        _effect_uses_card_choice(effect)
        and not (
            (
                _effect_uses_post_action_card_choice(effect)
                or _effect_uses_post_cost_card_choice(effect)
            )
            and invocation.resolution_stage == "initial"
        )
        and effect.choice.minimum > 0
    ):
        choice_candidates = _effect_choice_candidates(state, invocation)
        if (
            len(choice_candidates) < effect.choice.minimum
            or not _choice_candidates_can_satisfy_condition(
                state, choice_candidates, effect.choice
            )
        ):
            return "choice_candidates_unavailable"
    if (
        _effect_uses_card_choice(effect)
        and not (
            (
                _effect_uses_post_action_card_choice(effect)
                or _effect_uses_post_cost_card_choice(effect)
            )
            and invocation.resolution_stage == "initial"
        )
        and effect.choice.maximum > 0
        and effect.choice.minimum > 0
        and effect.choice.zone == "stage"
        and not _effect_choice_candidates(state, invocation)
    ):
        return "choice_candidates_unavailable"
    if _effect_uses_grouped_stage_member_choice(effect) and not (
        _grouped_stage_member_choice_has_legal_assignment(state, invocation)
    ):
        return "grouped_stage_member_choice_unavailable"
    if _effect_uses_position_change_choice(effect) and not (
        _position_change_source_target_slots(state, invocation)
    ):
        return "position_change_unavailable"
    if _effect_uses_deploy_to_empty_stage_choice(effect, invocation) and (
        not _effect_choice_candidates(state, invocation)
        or not _empty_member_area_slots(player)
    ):
        return "deploy_member_unavailable"
    if (
        _effect_uses_branch_choice(effect)
        and invocation.resolution_stage == "initial"
        and not _available_effect_branches(state, invocation)
    ):
        return "branch_choice_unavailable"
    return None


def _effect_resolution_options(
    state: MatchState,
    invocation: EffectInvocation,
) -> dict[str, Any]:
    effect = state.effect_definitions[invocation.effect_id]
    candidate_ids: list[str] = []
    follow_up_choice = _effect_follow_up_choice(effect, invocation)
    if follow_up_choice is not None:
        candidate_ids = _effect_candidates_for_choice(
            state,
            invocation,
            follow_up_choice,
        )
    elif _effect_uses_cost_card_choice(effect) and invocation.resolution_stage == "initial":
        candidate_ids = _effect_cost_choice_candidates(state, invocation)
    elif not _effect_uses_grouped_stage_member_choice(effect) and not _effect_uses_inspection_choice(effect) and not (
        (
            _effect_uses_post_action_card_choice(effect)
            or _effect_uses_post_cost_card_choice(effect)
        )
        and invocation.resolution_stage == "initial"
    ):
        candidate_ids = _effect_choice_candidates(state, invocation)
    options: dict[str, Any] = {
        "candidate_card_instance_ids": candidate_ids,
        "resolution_stage": invocation.resolution_stage,
    }
    if effect.cost_choice is not None and invocation.resolution_stage == "initial":
        options["choice_type"] = effect.cost_choice.choice_type
        options["choice_zone"] = effect.cost_choice.zone
        options["card_selection_minimum"] = effect.cost_choice.minimum
        options["card_selection_maximum"] = effect.cost_choice.maximum
        options["cost_choice"] = effect.cost_choice.model_dump()
    elif (
        follow_up_choice is not None
        or (effect.choice is not None and not _effect_uses_inspection_choice(effect))
    ):
        choice = follow_up_choice or effect.choice
        minimum, maximum = _effect_choice_bounds(state, invocation, choice)
        options["choice_type"] = choice.choice_type
        options["card_selection_minimum"] = minimum
        options["card_selection_maximum"] = maximum
        if _effect_uses_grouped_stage_member_choice(effect):
            options["choice_groups"] = _effect_group_choice_options(
                state, invocation
            )
        if _effect_uses_branch_choice(effect):
            options["branch_ids"] = list(effect.choice.branch_ids)
            if invocation.resolution_stage == "initial":
                options["available_branch_ids"] = _available_effect_branches(
                    state,
                    invocation,
                )
            options["branch_energy_required"] = dict(
                effect.choice.branch_energy_required
            )
            if effect.choice.branch_energy_required:
                player = state.players[invocation.player_id]
                options["energy_instance_ids"] = [
                    item
                    for item in player.energy_area
                    if state.cards[item].orientation == "active"
                ]
            branch = invocation.trigger_data.get("selected_branch")
            if isinstance(branch, str):
                options["selected_branch"] = branch
                options["card_selection_minimum"] = (
                    effect.choice.branch_selection_minimum.get(branch, 0)
                )
                options["card_selection_maximum"] = (
                    effect.choice.branch_selection_maximum.get(branch, 0)
                )
                energy_required = effect.choice.branch_energy_required.get(branch, 0)
                if energy_required:
                    options["energy_required"] = energy_required
                branch_choice = _branch_choice_filter(effect, branch)
                if branch_choice is not None:
                    options["choice_zone"] = _resolved_choice_zone(branch_choice)
                    options["choice_orientation"] = branch_choice.orientation
                    options["target_player"] = branch_choice.target_player
                branch_operations = [
                    operation
                    for operation in effect.actions
                    if operation.branch == branch
                ]
                if any(
                    operation.action_type == "position_change_selected"
                    for operation in branch_operations
                ):
                    options["position_change_slots_by_candidate"] = (
                        _position_change_slots_by_candidate(
                            state,
                            invocation.player_id,
                            options.get("candidate_card_instance_ids", []),
                        )
                    )
        choice_zone = choice.zone
        if choice_zone is None and choice.choice_type == "energy_from_area":
            choice_zone = "energy_area"
        elif choice_zone is None and choice.choice_type == "member_from_stage":
            choice_zone = "stage"
        options.setdefault("choice_zone", choice_zone)
        options.setdefault("choice_orientation", choice.orientation)
        options["color_slots"] = list(choice.color_slots)
        options["destination_options"] = list(choice.destination_options)
        options.setdefault("target_player", choice.target_player)
        if _effect_uses_position_change_choice(effect):
            options["position_change_slots"] = _position_change_source_target_slots(
                state, invocation
            )
        if _effect_uses_deploy_to_empty_stage_choice(effect, invocation):
            options["available_slots"] = _empty_member_area_slots(
                state.players[invocation.player_id]
            )
    pay_amount = 0
    if invocation.resolution_stage == "initial":
        pay_amount = sum(
            _operation_amount(operation, player=state.players[invocation.player_id])
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
    elif (
        invocation.resolution_stage == "initial"
        and effect.choice is not None
        and effect.choice.choice_type == "choose_count"
        and any(
            operation.action_type == "pay_energy"
            and operation.amount_source == "selected_count"
            for operation in effect.cost
        )
    ):
        player = state.players[invocation.player_id]
        options["energy_instance_ids"] = [
            item
            for item in player.energy_area
            if state.cards[item].orientation == "active"
        ]
        options["energy_required_source"] = "selected_count"
    return options


def _effect_choice_bounds(
    state: MatchState,
    invocation: EffectInvocation,
    choice: Any,
) -> tuple[int, int]:
    if choice is None:
        return 0, 0
    if choice.amount_source == "own_stage_member_count":
        player = state.players[invocation.player_id]
        amount = sum(1 for item in player.member_area.values() if item is not None)
        return amount, amount
    if choice.amount_source == "own_stage_member_work_count":
        player = state.players[invocation.player_id]
        work_key = choice.amount_source_work_key
        if not isinstance(work_key, str):
            return 0, 0
        amount = sum(
            1
            for item in player.member_area.values()
            if item is not None and work_key in state.cards[item].card.work_keys
        )
        return amount, amount
    if choice.amount_source == "own_stage_member_unit_count":
        player = state.players[invocation.player_id]
        unit_key = choice.amount_source_unit_key
        if not isinstance(unit_key, str):
            return 0, 0
        amount = sum(
            1
            for item in player.member_area.values()
            if item is not None and unit_key in state.cards[item].card.unit_keys
        )
        return amount, amount
    if choice.amount_source == "opponent_stage_wait_member_count":
        opponent_id = "player_2" if invocation.player_id == "player_1" else "player_1"
        opponent = state.players[opponent_id]
        amount = sum(
            instance_id is not None
            and state.cards[instance_id].orientation == "wait"
            for instance_id in opponent.member_area.values()
        )
        return choice.minimum, min(choice.maximum, amount)
    return choice.minimum, choice.maximum


def _effect_choice_candidates(
    state: MatchState,
    invocation: EffectInvocation,
) -> list[str]:
    effect = state.effect_definitions[invocation.effect_id]
    follow_up_choice = _effect_follow_up_choice(effect, invocation)
    if follow_up_choice is not None:
        if not _choice_condition_met(state, invocation, follow_up_choice):
            return []
        return _effect_candidates_for_choice(state, invocation, follow_up_choice)
    if (
        effect.choice is None
        or _effect_uses_inspection_choice(effect)
        or _effect_uses_grouped_stage_member_choice(effect)
    ):
        return []
    if (
        _effect_uses_branch_choice(effect)
        and invocation.resolution_stage == "initial"
    ):
        return []
    if _effect_uses_branch_choice(effect):
        branch = invocation.trigger_data.get("selected_branch")
        if isinstance(branch, str):
            branch_choice = _branch_choice_filter(effect, branch)
            if branch_choice is not None:
                return _effect_candidates_for_choice(state, invocation, branch_choice)
    if _effect_uses_post_action_card_choice(
        effect
    ) and not _post_action_choice_condition_met(effect, invocation):
        return []
    return _effect_candidates_for_choice(state, invocation, effect.choice)


def _resolved_choice_zone(choice: Any) -> str | None:
    zone = choice.zone
    if zone is None and choice.choice_type == "energy_from_area":
        return "energy_area"
    if zone is None and choice.choice_type == "member_from_stage":
        return "stage"
    return zone


def _branch_choice_filter(effect: Any, branch: str) -> Any | None:
    if effect.choice is None:
        return None
    raw_filters = getattr(effect.choice, "branch_choice_filters", {})
    if not isinstance(raw_filters, dict):
        return None
    raw = raw_filters.get(branch)
    if not isinstance(raw, dict):
        return None
    return SimpleNamespace(
        choice_type=raw.get("choice_type", "member_from_stage"),
        zone=raw.get("zone"),
        card_type=raw.get("card_type"),
        orientation=raw.get("orientation"),
        color_slots=[],
        minimum=0,
        maximum=1,
        work_key=raw.get("work_key"),
        unit_key=raw.get("unit_key"),
        exclude_unit_key=raw.get("exclude_unit_key"),
        unit_keys_any=list(raw.get("unit_keys_any", []))
        if isinstance(raw.get("unit_keys_any", []), list)
        else [],
        ability_bucket=[],
        exclude_source=bool(raw.get("exclude_source", False)),
        target_player=raw.get("target_player", "self"),
        name_ja_any=list(raw.get("name_ja_any", []))
        if isinstance(raw.get("name_ja_any", []), list)
        else [],
        minimum_cost=raw.get("minimum_cost"),
        maximum_cost=raw.get("maximum_cost"),
        minimum_blade=raw.get("minimum_blade"),
        maximum_blade=raw.get("maximum_blade"),
        minimum_original_blade=raw.get("minimum_original_blade"),
        maximum_original_blade=raw.get("maximum_original_blade"),
        minimum_score=raw.get("minimum_score"),
        maximum_score=raw.get("maximum_score"),
        heart_color_slot=raw.get("heart_color_slot"),
        minimum_heart_count=raw.get("minimum_heart_count"),
        required_heart_color_slot=raw.get("required_heart_color_slot"),
        minimum_required_heart=raw.get("minimum_required_heart"),
        baton_entered_this_turn=bool(raw.get("baton_entered_this_turn", False)),
    )


def _choice_condition_met(
    state: MatchState,
    invocation: EffectInvocation,
    choice: Any,
) -> bool:
    condition = getattr(choice, "condition", {})
    if not isinstance(condition, dict):
        return True
    return _effect_operation_condition_met(state, invocation, condition)


def _effect_operation_condition_met(
    state: MatchState,
    invocation: EffectInvocation,
    condition: dict[str, Any],
    operation_context: dict[str, Any] | None = None,
) -> bool:
    player = state.players[invocation.player_id]
    stage_members = [
        item for item in player.member_area.values() if item is not None
    ]
    cleared_excess = condition.get("last_cleared_excess_heart_count_at_least")
    if isinstance(cleared_excess, int):
        actual = 0
        if operation_context is not None:
            actual = int(operation_context.get("last_cleared_excess_heart_count", 0))
        if actual < cleared_excess:
            return False
    excess_at_least = condition.get("own_excess_heart_count_at_least")
    if isinstance(excess_at_least, int):
        if _own_excess_heart_count(player) < excess_at_least:
            return False
    excess_at_most = condition.get("own_excess_heart_count_at_most")
    if isinstance(excess_at_most, int):
        if _own_excess_heart_count(player) > excess_at_most:
            return False
    if condition.get("last_revealed_top_member_without_blade_heart"):
        revealed = []
        if operation_context is not None:
            revealed = list(operation_context.get("revealed_card_instance_ids", []))
        if len(revealed) != 1:
            return False
        card = state.cards[revealed[0]].card
        if card.card_type != "member" or _card_has_blade_heart(card):
            return False
    if condition.get("last_revealed_top_matched"):
        matched = []
        if operation_context is not None:
            matched = list(operation_context.get("matched_card_instance_ids", []))
        if not matched:
            return False
    if condition.get("last_revealed_top_member_cost_at_most_selected_count"):
        revealed = []
        selected_count = None
        if operation_context is not None:
            revealed = list(operation_context.get("revealed_card_instance_ids", []))
            selected_count = operation_context.get("selected_count")
        if (
            len(revealed) != 1
            or not isinstance(selected_count, int)
            or isinstance(selected_count, bool)
        ):
            return False
        card = state.cards[revealed[0]].card
        if card.card_type != "member" or (card.cost or 0) > selected_count:
            return False
    milled_all_work = condition.get("milled_all_work_key")
    if isinstance(milled_all_work, str):
        milled = []
        if operation_context is not None:
            milled = list(operation_context.get("milled_card_instance_ids", []))
        if not milled or any(
            milled_all_work not in state.cards[item].card.work_keys for item in milled
        ):
            return False
    stage_count = condition.get("own_stage_member_count_at_least")
    if isinstance(stage_count, int) and len(stage_members) < stage_count:
        return False
    if condition.get("source_moved_this_turn"):
        source_slot = _top_member_slot(player, invocation.source_card_instance_id)
        if source_slot is None or source_slot not in player.member_areas_moved_this_turn:
            return False
    played_from_zone = condition.get("played_from_zone")
    if isinstance(played_from_zone, str):
        if played_from_zone != invocation.trigger_data.get("source_zone"):
            return False
    if condition.get("own_stage_other_member_moved_this_turn"):
        source_slot = _top_member_slot(player, invocation.source_card_instance_id)
        moved_slots = set(player.member_areas_moved_this_turn)
        if source_slot is not None:
            moved_slots.discard(source_slot)
        if not any(player.member_area.get(slot) is not None for slot in moved_slots):
            return False
    distinct_names = condition.get("own_stage_member_distinct_name_count_at_least")
    if isinstance(distinct_names, int):
        names = {state.cards[item].card.name_ja for item in stage_members}
        if len(names) < distinct_names:
            return False
    success_score = condition.get("success_live_score_at_least")
    if isinstance(success_score, int):
        total = sum(
            _card_score(state, player.player_id, item) for item in player.success_live_area
        )
        if total < success_score:
            return False
    success_work = condition.get("success_live_work_count_at_least")
    if isinstance(success_work, dict):
        work_key = success_work.get("work_key")
        count = success_work.get("count")
        if isinstance(work_key, str) and isinstance(count, int):
            actual = sum(
                work_key in state.cards[item].card.work_keys
                for item in player.success_live_area
            )
            if actual < count:
                return False
    selected_count = condition.get("selected_card_count_at_least")
    if isinstance(selected_count, int):
        selected = []
        if operation_context is not None:
            selected = list(operation_context.get("selected_card_instance_ids", []))
        if len(selected) < selected_count:
            return False
    return True


def _operation_condition_met(
    state: MatchState,
    invocation: EffectInvocation,
    operation: Any,
    operation_context: dict[str, Any],
) -> bool:
    if not isinstance(operation.value, dict):
        return True
    condition = operation.value.get("condition")
    if not isinstance(condition, dict):
        return True
    return _effect_operation_condition_met(
        state,
        invocation,
        condition,
        operation_context,
    )


def _available_effect_branches(
    state: MatchState,
    invocation: EffectInvocation,
) -> list[str]:
    effect = state.effect_definitions[invocation.effect_id]
    if effect.choice is None:
        return []
    return [
        branch
        for branch in effect.choice.branch_ids
        if _branch_unavailable_reason(state, invocation, branch) is None
    ]


def _branch_unavailable_reason(
    state: MatchState,
    invocation: EffectInvocation,
    branch: str,
) -> str | None:
    effect = state.effect_definitions[invocation.effect_id]
    if effect.choice is None:
        return "branch_choice_missing"
    player = state.players[invocation.player_id]
    required_energy = effect.choice.branch_energy_required.get(branch, 0)
    if required_energy:
        active_energy = sum(
            state.cards[item].orientation == "active" for item in player.energy_area
        )
        if active_energy < required_energy:
            return "branch_energy_unavailable"
    conditions = effect.choice.branch_conditions.get(branch, {})
    if not isinstance(conditions, dict):
        return "branch_condition_invalid"
    distinct_names = conditions.get("waiting_room_live_distinct_name_count_at_least")
    if isinstance(distinct_names, int):
        actual = len(
            {
                state.cards[item].card.name_ja
                for item in player.waiting_room
                if state.cards[item].card.card_type == "live"
            }
        )
        if actual < distinct_names:
            return "waiting_room_live_distinct_name_count_too_low"
    distinct_groups = conditions.get("waiting_room_live_distinct_group_count_at_least")
    if isinstance(distinct_groups, int):
        actual = _waiting_room_live_distinct_group_count(state, invocation.player_id)
        if actual < distinct_groups:
            return "waiting_room_live_distinct_group_count_too_low"
    success_live_count = conditions.get("success_live_count_at_least")
    if isinstance(success_live_count, int):
        if len(player.success_live_area) < success_live_count:
            return "success_live_count_too_low"
    source_orientation = conditions.get("source_orientation")
    if isinstance(source_orientation, str):
        source = state.cards.get(invocation.source_card_instance_id)
        if source is None or source.orientation != source_orientation:
            return "source_orientation_mismatch"
    minimum = effect.choice.branch_selection_minimum.get(branch, 0)
    if minimum > 0:
        branch_choice = _branch_choice_filter(effect, branch)
        if branch_choice is not None:
            candidates = _effect_candidates_for_choice(state, invocation, branch_choice)
        else:
            candidates = _effect_candidates_for_choice(state, invocation, effect.choice)
        if len(candidates) < minimum:
            return "branch_choice_candidates_unavailable"
    return None


def _effect_group_choice_options(
    state: MatchState,
    invocation: EffectInvocation,
) -> list[dict[str, Any]]:
    effect = state.effect_definitions[invocation.effect_id]
    if effect.choice is None:
        return []
    selected_by_group: dict[str, list[str]] = {}
    options: list[dict[str, Any]] = []
    for group in effect.choice.selection_groups:
        excluded = {
            instance_id
            for group_id in group.exclude_group_ids
            for instance_id in selected_by_group.get(group_id, [])
        }
        excluded_names = {
            state.cards[instance_id].card.name_ja
            for group_id in group.exclude_group_names
            for instance_id in selected_by_group.get(group_id, [])
        }
        candidates = [
            item
            for item in _stage_member_candidates_for_group(state, invocation, group)
            if item not in excluded and state.cards[item].card.name_ja not in excluded_names
        ]
        options.append(
            {
                "group_id": group.group_id,
                "label_ja": group.label_ja,
                "candidate_card_instance_ids": candidates,
                "exclude_group_ids": list(group.exclude_group_ids),
                "exclude_group_names": list(group.exclude_group_names),
                "minimum": group.minimum,
                "maximum": group.maximum,
            }
        )
        selected_by_group[group.group_id] = []
    return options


def _validate_grouped_stage_member_choice(
    state: MatchState,
    invocation: EffectInvocation,
    payload: Any,
) -> dict[str, list[str]]:
    effect = state.effect_definitions[invocation.effect_id]
    if effect.choice is None:
        raise IllegalActionError("grouped effect is missing choice metadata")
    if not isinstance(payload, dict):
        raise IllegalActionError("grouped effect selection is required")
    selected_by_group: dict[str, list[str]] = {}
    known_group_ids = {group.group_id for group in effect.choice.selection_groups}
    unknown_group_ids = set(payload) - known_group_ids
    if unknown_group_ids:
        raise IllegalActionError("grouped effect selection has an unknown group")
    all_selected: set[str] = set()
    for group in effect.choice.selection_groups:
        raw_selected = payload.get(group.group_id, [])
        if not isinstance(raw_selected, list) or any(
            not isinstance(item, str) for item in raw_selected
        ):
            raise IllegalActionError("grouped effect selections must be ID lists")
        selected = list(raw_selected)
        excluded = {
            instance_id
            for group_id in group.exclude_group_ids
            for instance_id in selected_by_group.get(group_id, [])
        }
        excluded_names = {
            state.cards[instance_id].card.name_ja
            for group_id in group.exclude_group_names
            for instance_id in selected_by_group.get(group_id, [])
        }
        candidates = [
            item
            for item in _stage_member_candidates_for_group(state, invocation, group)
            if item not in excluded and state.cards[item].card.name_ja not in excluded_names
        ]
        if (
            len(selected) < group.minimum
            or len(selected) > group.maximum
            or len(selected) != len(set(selected))
            or any(item not in candidates for item in selected)
            or any(item in all_selected for item in selected)
        ):
            raise IllegalActionError("grouped effect selection is not legal")
        selected_by_group[group.group_id] = selected
        all_selected.update(selected)
    return selected_by_group


def _grouped_stage_member_choice_has_legal_assignment(
    state: MatchState,
    invocation: EffectInvocation,
) -> bool:
    effect = state.effect_definitions[invocation.effect_id]
    if effect.choice is None:
        return False
    groups = list(effect.choice.selection_groups)

    def backtrack(index: int, selected_by_group: dict[str, list[str]], used: set[str]) -> bool:
        if index >= len(groups):
            return True
        group = groups[index]
        excluded = {
            instance_id
            for group_id in group.exclude_group_ids
            for instance_id in selected_by_group.get(group_id, [])
        }
        excluded_names = {
            state.cards[instance_id].card.name_ja
            for group_id in group.exclude_group_names
            for instance_id in selected_by_group.get(group_id, [])
        }
        candidates = [
            item
            for item in _stage_member_candidates_for_group(state, invocation, group)
            if item not in excluded
            and state.cards[item].card.name_ja not in excluded_names
            and item not in used
        ]
        if len(candidates) < group.minimum:
            return False
        if group.minimum == 0:
            selected_by_group[group.group_id] = []
            if backtrack(index + 1, selected_by_group, used):
                return True
        if group.minimum == 1 and group.maximum == 1:
            for candidate in candidates:
                selected_by_group[group.group_id] = [candidate]
                if backtrack(index + 1, selected_by_group, {*used, candidate}):
                    return True
            selected_by_group.pop(group.group_id, None)
            return False
        selected = candidates[: group.minimum]
        selected_by_group[group.group_id] = selected
        return backtrack(index + 1, selected_by_group, {*used, *selected})

    return backtrack(0, {}, set())


def _stage_member_candidates_for_group(
    state: MatchState,
    invocation: EffectInvocation,
    group: Any,
) -> list[str]:
    choice = SimpleNamespace(
        choice_type="member_from_stage",
        zone=group.zone or "stage",
        target_player="self",
        card_type=group.card_type,
        work_key=group.work_key,
        unit_key=group.unit_key,
        exclude_unit_key=None,
        unit_keys_any=[],
        name_ja_any=list(group.name_ja_any),
        orientation=None,
        exclude_source=False,
        minimum_cost=None,
        maximum_cost=None,
        minimum_blade=None,
        maximum_blade=None,
        minimum_original_blade=None,
        maximum_original_blade=None,
        minimum_score=None,
        maximum_score=None,
    )
    return _effect_candidates_for_choice(state, invocation, choice)


def _effect_cost_choice_candidates(
    state: MatchState,
    invocation: EffectInvocation,
) -> list[str]:
    effect = state.effect_definitions[invocation.effect_id]
    if effect.cost_choice is None:
        return []
    return _effect_candidates_for_choice(state, invocation, effect.cost_choice)


def _selected_cards_satisfy_choice_condition(
    state: MatchState,
    selected_ids: list[str],
    choice: Any,
) -> bool:
    condition = getattr(choice, "condition", {})
    if not isinstance(condition, dict) or not condition:
        return True
    selected_cards = [
        state.cards[item].card for item in selected_ids if item in state.cards
    ]
    if len(selected_cards) != len(selected_ids):
        return False
    if condition.get("selected_share_unit_key"):
        if not selected_cards:
            return False
        shared_units = set(selected_cards[0].unit_keys)
        for card in selected_cards[1:]:
            shared_units.intersection_update(card.unit_keys)
        if not shared_units:
            return False
    if condition.get("selected_share_work_key"):
        if not selected_cards:
            return False
        shared_works = set(selected_cards[0].work_keys)
        for card in selected_cards[1:]:
            shared_works.intersection_update(card.work_keys)
        if not shared_works:
            return False
    if condition.get("selected_same_name_ja"):
        if len({card.name_ja for card in selected_cards}) > 1:
            return False
    return True


def _choice_candidates_can_satisfy_condition(
    state: MatchState,
    candidate_ids: list[str],
    choice: Any,
) -> bool:
    condition = getattr(choice, "condition", {})
    if not isinstance(condition, dict) or not condition:
        return True
    minimum = getattr(choice, "minimum", 0)
    if condition.get("selected_share_unit_key"):
        counts: dict[str, int] = {}
        for instance_id in candidate_ids:
            for unit_key in state.cards[instance_id].card.unit_keys:
                counts[unit_key] = counts.get(unit_key, 0) + 1
        return any(count >= minimum for count in counts.values())
    if condition.get("selected_share_work_key"):
        counts: dict[str, int] = {}
        for instance_id in candidate_ids:
            for work_key in state.cards[instance_id].card.work_keys:
                counts[work_key] = counts.get(work_key, 0) + 1
        return any(count >= minimum for count in counts.values())
    if condition.get("selected_same_name_ja"):
        counts: dict[str, int] = {}
        for instance_id in candidate_ids:
            name_ja = state.cards[instance_id].card.name_ja
            counts[name_ja] = counts.get(name_ja, 0) + 1
        return any(count >= minimum for count in counts.values())
    return True


def _choice_card_type_stat_filters(choice: Any) -> list[dict[str, Any]]:
    value = getattr(choice, "value", None)
    if not isinstance(value, dict):
        return []
    raw_filters = value.get("card_type_stat_filters")
    if not isinstance(raw_filters, list):
        return []
    return [item for item in raw_filters if isinstance(item, dict)]


def _matches_card_type_stat_filter(
    state: MatchState,
    player_id: str,
    instance_id: str,
    filters: list[dict[str, Any]],
) -> bool:
    card = state.cards[instance_id].card
    for item_filter in filters:
        card_type = item_filter.get("card_type")
        if isinstance(card_type, str) and card.card_type != card_type:
            continue
        minimum_cost = item_filter.get("minimum_cost")
        if isinstance(minimum_cost, int) and (card.cost or 0) < minimum_cost:
            continue
        maximum_cost = item_filter.get("maximum_cost")
        if isinstance(maximum_cost, int) and (card.cost or 0) > maximum_cost:
            continue
        minimum_score = item_filter.get("minimum_score")
        if isinstance(minimum_score, int):
            if _card_score(state, player_id, instance_id) < minimum_score:
                continue
        maximum_score = item_filter.get("maximum_score")
        if isinstance(maximum_score, int):
            if _card_score(state, player_id, instance_id) > maximum_score:
                continue
        return True
    return False


def _effect_candidates_for_choice(
    state: MatchState,
    invocation: EffectInvocation,
    choice: Any,
) -> list[str]:
    player = state.players[invocation.player_id]
    zone = choice.zone
    if zone is None and choice.choice_type == "energy_from_area":
        zone = "energy_area"
    elif zone is None and choice.choice_type == "member_from_stage":
        zone = "stage"
    if zone == "waiting_room":
        candidates = list(player.waiting_room)
    elif zone == "hand":
        target_player = player
        if choice.target_player == "opponent":
            target_player = state.players[
                "player_2" if invocation.player_id == "player_1" else "player_1"
            ]
        candidates = list(target_player.hand)
    elif zone == "stage":
        target_player = player
        if choice.target_player == "opponent":
            target_player = state.players[
                "player_2" if invocation.player_id == "player_1" else "player_1"
            ]
        candidates = [
            item for item in target_player.member_area.values() if item is not None
        ]
    elif zone == "energy_area":
        candidates = list(player.energy_area)
    elif zone == "resolution_area":
        candidates = list(player.resolution_area)
    else:
        return []
    if choice.card_type:
        candidates = [
            item
            for item in candidates
            if state.cards[item].card.card_type == choice.card_type
        ]
    if choice.work_key:
        candidates = [
            item
            for item in candidates
            if choice.work_key in state.cards[item].card.work_keys
        ]
    if choice.unit_key:
        candidates = [
            item
            for item in candidates
            if choice.unit_key in state.cards[item].card.unit_keys
        ]
    if getattr(choice, "exclude_unit_key", None):
        candidates = [
            item
            for item in candidates
            if choice.exclude_unit_key not in state.cards[item].card.unit_keys
        ]
    if choice.unit_keys_any:
        allowed_units = set(choice.unit_keys_any)
        candidates = [
            item
            for item in candidates
            if allowed_units.intersection(state.cards[item].card.unit_keys)
        ]
    if choice.name_ja_any:
        candidates = [
            item
            for item in candidates
            if _card_name_in(state.cards[item].card.name_ja, choice.name_ja_any)
        ]
    stat_filters = _choice_card_type_stat_filters(choice)
    if stat_filters:
        candidates = [
            item
            for item in candidates
            if _matches_card_type_stat_filter(
                state,
                invocation.player_id,
                item,
                stat_filters,
            )
        ]
    if choice.orientation:
        candidates = [
            item
            for item in candidates
            if state.cards[item].orientation == choice.orientation
        ]
    if choice.exclude_source:
        candidates = [
            item for item in candidates if item != invocation.source_card_instance_id
        ]
    if getattr(choice, "baton_entered_this_turn", False):
        target_player = player
        if getattr(choice, "target_player", "self") == "opponent":
            target_player = state.players[
                "player_2" if invocation.player_id == "player_1" else "player_1"
            ]
        baton_slots = set(target_player.member_areas_baton_entered_this_turn)
        candidates = [
            item
            for item in candidates
            if _top_member_slot(target_player, item) in baton_slots
        ]
    if choice.minimum_cost is not None:
        candidates = [
            item
            for item in candidates
            if (state.cards[item].card.cost or 0) >= choice.minimum_cost
        ]
    if choice.maximum_cost is not None:
        candidates = [
            item
            for item in candidates
            if (state.cards[item].card.cost or 0) <= choice.maximum_cost
        ]
    blade_player_id = invocation.player_id
    if getattr(choice, "target_player", "self") == "opponent":
        blade_player_id = (
            "player_2" if invocation.player_id == "player_1" else "player_1"
        )
    if getattr(choice, "minimum_blade", None) is not None:
        candidates = [
            item
            for item in candidates
            if (
                _member_base_blade(state, blade_player_id, item)
                + _target_modifier_total(
                    state.players[blade_player_id], "blade", item
                )
            )
            >= choice.minimum_blade
        ]
    if choice.maximum_blade is not None:
        candidates = [
            item
            for item in candidates
            if (
                _member_base_blade(state, blade_player_id, item)
                + _target_modifier_total(
                    state.players[blade_player_id], "blade", item
                )
            )
            <= choice.maximum_blade
        ]
    if getattr(choice, "minimum_original_blade", None) is not None:
        candidates = [
            item
            for item in candidates
            if (state.cards[item].card.blade or 0) >= choice.minimum_original_blade
        ]
    if getattr(choice, "maximum_original_blade", None) is not None:
        candidates = [
            item
            for item in candidates
            if (state.cards[item].card.blade or 0) <= choice.maximum_original_blade
        ]
    if choice.minimum_score is not None:
        candidates = [
            item
            for item in candidates
            if _card_score(state, invocation.player_id, item) >= choice.minimum_score
        ]
    if choice.maximum_score is not None:
        candidates = [
            item
            for item in candidates
            if _card_score(state, invocation.player_id, item) <= choice.maximum_score
        ]
    heart_color_slot = getattr(choice, "heart_color_slot", None)
    minimum_heart_count = getattr(choice, "minimum_heart_count", None)
    if heart_color_slot is not None and minimum_heart_count is not None:
        candidates = [
            item
            for item in candidates
            if _card_heart_or_required_heart_count(
                state.cards[item].card,
                heart_color_slot,
            )
            >= minimum_heart_count
        ]
    required_heart_color_slot = getattr(choice, "required_heart_color_slot", None)
    minimum_required_heart = getattr(choice, "minimum_required_heart", None)
    if (
        required_heart_color_slot is not None
        and minimum_required_heart is not None
    ):
        candidates = [
            item
            for item in candidates
            if state.cards[item].card.required_hearts.get(
                required_heart_color_slot, 0
            )
            >= minimum_required_heart
        ]
    return candidates


def _card_heart_or_required_heart_count(card: Any, color_slot: str) -> int:
    if card.card_type == "live":
        return card.required_hearts.get(color_slot, 0)
    return card.basic_hearts.get(color_slot, 0)


def _operation_requires_selected_choice(operation: Any) -> bool:
    if operation.action_type == "ready_energy" and operation.target == "auto":
        return False
    if operation.target == "selected" and operation.action_type in {
        "apply_wait_member",
        "gain_blade",
        "gain_heart",
        "gain_heart_from_selected_card_colors",
    }:
        return True
    return operation.action_type in {
        "apply_wait_energy",
        "deploy_selected_to_empty_stage",
        "discard_from_hand",
        "move_selected_to_deck_bottom",
        "move_selected_to_hand",
        "move_selected_to_deck_top",
        "move_selected_to_deck_top_or_bottom",
        "position_change_source",
        "position_change_selected",
        "ready_energy",
        "ready_member",
        "replace_member_base_hearts",
        "return_from_waiting_room",
    }


def _post_action_initial_operations(effect: Any) -> list[Any]:
    operations: list[Any] = []
    for operation in effect.actions:
        if _operation_requires_selected_choice(operation):
            break
        operations.append(operation)
    return operations


def _post_action_follow_up_operations(effect: Any) -> list[Any]:
    operations: list[Any] = []
    found_selected_operation = False
    for operation in effect.actions:
        if _operation_requires_selected_choice(operation):
            found_selected_operation = True
        if found_selected_operation:
            operations.append(operation)
    return operations


def _effect_uses_inspection_choice(effect: Any) -> bool:
    return bool(effect.choice and effect.choice.choice_type == "inspect_top_select")


def _effect_uses_multi_player_choice(effect: Any) -> bool:
    return bool(
        effect.choice
        and effect.choice.choice_type
        in {
            "multi_player_deploy_waiting_member",
            "multi_player_discard_to_hand_size_then_draw",
            "multi_player_draw_then_discard",
        }
    )


def _effect_follow_up_choice(effect: Any, invocation: EffectInvocation) -> Any | None:
    if (
        invocation.resolution_stage == "after_cost"
        and _effect_uses_multi_player_choice(effect)
        and effect.follow_up_choice is not None
    ):
        return effect.follow_up_choice
    return None


def _effect_uses_follow_up_card_choice(
    effect: Any,
    invocation: EffectInvocation,
) -> bool:
    return _effect_follow_up_choice(effect, invocation) is not None


def _effect_uses_grouped_stage_member_choice(effect: Any) -> bool:
    return bool(effect.choice and effect.choice.choice_type == "member_group_from_stage")


def _effect_uses_card_choice(effect: Any) -> bool:
    if not effect.choice or _effect_uses_inspection_choice(effect):
        return False
    if _effect_uses_multi_player_choice(effect):
        return False
    if _effect_uses_grouped_stage_member_choice(effect):
        return False
    if _effect_uses_branch_choice(effect):
        return False
    if effect.choice.choice_type in {
        "card_from_zone",
        "energy_from_area",
        "member_from_stage",
        "post_action_card_from_zone",
    }:
        return True
    return effect.choice.zone in {"waiting_room", "hand", "stage", "energy_area"}


def _effect_uses_post_action_card_choice(effect: Any) -> bool:
    return bool(effect.choice and effect.choice.choice_type == "post_action_card_from_zone")


def _post_action_choice_has_condition(effect: Any) -> bool:
    return bool(
        effect.choice
        and effect.choice.post_action_condition_key is not None
        and effect.choice.post_action_condition_minimum is not None
    )


def _post_action_choice_condition_met(effect: Any, invocation: EffectInvocation) -> bool:
    if effect.choice is None:
        return True
    key = effect.choice.post_action_condition_key
    minimum = effect.choice.post_action_condition_minimum
    if key is None or minimum is None:
        return True
    value = invocation.trigger_data.get(key, 0)
    return isinstance(value, int) and value >= minimum


def _post_action_choice_should_continue(
    state: MatchState,
    invocation: EffectInvocation,
) -> bool:
    effect = state.effect_definitions[invocation.effect_id]
    if not _post_action_choice_condition_met(effect, invocation):
        return False
    if effect.choice is None:
        return False
    minimum, maximum = _effect_choice_bounds(state, invocation, effect.choice)
    if not _post_action_choice_has_condition(effect):
        return maximum > 0
    return len(_effect_choice_candidates(state, invocation)) >= minimum


def _effect_uses_cost_card_choice(effect: Any) -> bool:
    return bool(effect.cost_choice and effect.cost_choice.zone in {"hand"})


def _effect_uses_post_cost_card_choice(effect: Any) -> bool:
    return bool(
        effect.choice
        and (
            any(
                operation.action_type == "source_to_waiting_room"
                for operation in effect.cost
            )
            or (
                effect.cost_choice is not None
                and not _effect_uses_inspection_choice(effect)
                and _effect_uses_card_choice(effect)
            )
        )
    )


def _stage_member_targets_for_operation(
    state: MatchState,
    player: PlayerState,
    invocation: EffectInvocation,
    operation: Any,
) -> list[str]:
    work_key = None
    unit_key = None
    slot = None
    moved_this_turn = False
    exclude_source = False
    name_ja = None
    name_ja_any: set[str] = set()
    maximum = None
    if isinstance(operation.value, dict):
        work_key = operation.value.get("work_key")
        unit_key = operation.value.get("unit_key")
        slot = operation.value.get("slot")
        moved_this_turn = bool(operation.value.get("moved_this_turn", False))
        exclude_source = bool(operation.value.get("exclude_source", False))
        name_ja = operation.value.get("name_ja")
        raw_names = operation.value.get("name_ja_any")
        if isinstance(raw_names, list):
            name_ja_any = {str(item) for item in raw_names}
        raw_maximum = operation.value.get("maximum")
        if isinstance(raw_maximum, int) and raw_maximum > 0:
            maximum = raw_maximum
    target_entries = (
        [(slot, player.member_area.get(slot))]
        if isinstance(slot, str)
        else list(player.member_area.items())
    )
    targets: list[str] = []
    for target_slot, target_id in target_entries:
        if target_id is None:
            continue
        if exclude_source and target_id == invocation.source_card_instance_id:
            continue
        if moved_this_turn and target_slot not in player.member_areas_moved_this_turn:
            continue
        card = state.cards[target_id].card
        if isinstance(work_key, str) and work_key not in card.work_keys:
            continue
        if isinstance(unit_key, str) and unit_key not in card.unit_keys:
            continue
        if isinstance(name_ja, str) and not _card_name_matches(card.name_ja, name_ja):
            continue
        if name_ja_any and not _card_name_in(card.name_ja, name_ja_any):
            continue
        targets.append(target_id)
        if maximum is not None and len(targets) >= maximum:
            break
    return targets


def _stage_member_target_for_operation_value(
    state: MatchState,
    player: PlayerState,
    operation: Any,
) -> str | None:
    name_ja = None
    if isinstance(operation.value, dict):
        name_ja = operation.value.get("target_stage_member_name_ja")
    if not isinstance(name_ja, str):
        return None
    for instance_id in player.member_area.values():
        if instance_id is None:
            continue
        if _card_name_matches(state.cards[instance_id].card.name_ja, name_ja):
            return instance_id
    return None


def _effect_ready_flag(work_key: str, ready_type: str) -> str:
    return f"{work_key}:{ready_type}"


def _record_effect_ready_flag(
    state: MatchState,
    player: PlayerState,
    invocation: EffectInvocation,
    *,
    ready_type: str,
    previous_orientation: str,
) -> None:
    if previous_orientation != "wait":
        return
    source_card = state.cards[invocation.source_card_instance_id].card
    for work_key in source_card.work_keys:
        flag = _effect_ready_flag(work_key, ready_type)
        if flag not in player.effect_ready_flags_this_turn:
            player.effect_ready_flags_this_turn.append(flag)


def _effect_uses_branch_choice(effect: Any) -> bool:
    return bool(effect.choice and effect.choice.choice_type == "choose_effect_branch")


def _effect_branch_accepts_position_choice(
    effect: Any, invocation: EffectInvocation
) -> bool:
    if not _effect_uses_branch_choice(effect):
        return False
    branch = invocation.trigger_data.get("selected_branch")
    if not isinstance(branch, str):
        return False
    return any(
        operation.branch == branch
        and operation.action_type == "position_change_selected"
        for operation in effect.actions
    )


def _validate_branch_choice(
    state: MatchState,
    effect: Any,
    invocation: EffectInvocation,
    selected_branch: Any,
    selected_ids: list[str],
    candidates: list[str],
) -> str:
    if effect.choice is None:
        raise IllegalActionError("branch effect is missing choice metadata")
    if invocation.resolution_stage == "initial":
        if not isinstance(selected_branch, str):
            raise IllegalActionError("effect branch selection is required")
        if selected_branch not in effect.choice.branch_ids:
            raise IllegalActionError("effect branch selection is not legal")
        if _branch_unavailable_reason(state, invocation, selected_branch) is not None:
            raise IllegalActionError("effect branch selection is unavailable")
        if selected_ids:
            raise IllegalActionError(
                "this effect accepts card selections after branch setup"
            )
        return selected_branch
    branch = invocation.trigger_data.get("selected_branch")
    if not isinstance(branch, str) or branch not in effect.choice.branch_ids:
        raise IllegalActionError("pending effect branch metadata is invalid")
    if selected_branch is not None and selected_branch != branch:
        raise IllegalActionError("effect branch cannot be changed after setup")
    minimum = effect.choice.branch_selection_minimum.get(branch, 0)
    maximum = effect.choice.branch_selection_maximum.get(branch, 0)
    if (
        len(selected_ids) < minimum
        or len(selected_ids) > maximum
        or len(selected_ids) != len(set(selected_ids))
        or any(item not in candidates for item in selected_ids)
    ):
        raise IllegalActionError("effect branch card selection is not legal")
    return branch


def _is_stage_member_instance(state: MatchState, instance_id: str) -> bool:
    for player in state.players.values():
        if instance_id in player.member_area.values():
            return state.cards[instance_id].card.card_type == "member"
    return False


def _operation_selected_ids(
    operation: Any,
    selected_ids: list[str],
    selected_ids_by_group: dict[str, list[str]] | None,
) -> list[str]:
    if isinstance(operation.value, dict) and selected_ids_by_group is not None:
        group_id = operation.value.get("target_group_id")
        if isinstance(group_id, str):
            return list(selected_ids_by_group.get(group_id, []))
    return selected_ids


def _effect_uses_color_choice(effect: Any) -> bool:
    return bool(effect.choice and effect.choice.choice_type == "choose_color")


def _effect_accepts_color_choice(effect: Any) -> bool:
    return bool(
        effect.choice
        and (
            effect.choice.choice_type == "choose_color"
            or bool(effect.choice.color_slots)
        )
    )


def _effect_uses_count_choice(effect: Any) -> bool:
    return bool(effect.choice and effect.choice.choice_type == "choose_count")


def _effect_uses_position_change_choice(effect: Any) -> bool:
    return bool(
        effect.choice and effect.choice.choice_type == "position_change_source"
    )


def _effect_uses_deploy_to_empty_stage_choice(
    effect: Any,
    invocation: EffectInvocation | None = None,
) -> bool:
    choice = _effect_follow_up_choice(effect, invocation) if invocation else None
    choice = choice or effect.choice
    return bool(choice and choice.choice_type == "deploy_member_from_waiting_room")


def _empty_member_area_slots(player: Any) -> list[str]:
    return [
        slot
        for slot in ("left", "center", "right")
        if player.member_area.get(slot) is None
    ]


def _position_change_source_target_slots(
    state: MatchState,
    invocation: EffectInvocation,
) -> list[str]:
    effect = state.effect_definitions[invocation.effect_id]
    excluded_slots = set()
    if effect.choice is not None:
        excluded_slots = set(effect.choice.excluded_position_slots)
    player = state.players[invocation.player_id]
    from_slot = _top_member_slot(player, invocation.source_card_instance_id)
    if from_slot is None:
        return []
    return [
        slot
        for slot in ("left", "center", "right")
        if slot != from_slot and slot not in excluded_slots
    ]


def _position_change_slots_by_candidate(
    state: MatchState,
    player_id: str,
    candidate_ids: object,
) -> dict[str, list[str]]:
    if not isinstance(candidate_ids, list):
        return {}
    player = state.players[player_id]
    slots_by_candidate: dict[str, list[str]] = {}
    for candidate_id in candidate_ids:
        if not isinstance(candidate_id, str):
            continue
        from_slot = _top_member_slot(player, candidate_id)
        if from_slot is None:
            continue
        slots_by_candidate[candidate_id] = [
            slot for slot in ("left", "center", "right") if slot != from_slot
        ]
    return slots_by_candidate


def _inspection_choice_candidates(
    state: MatchState,
    invocation: EffectInvocation,
    inspected_ids: list[str],
) -> list[str]:
    effect = state.effect_definitions[invocation.effect_id]
    choice = effect.choice
    if choice is None:
        return []
    candidates = list(inspected_ids)
    if choice.card_type:
        candidates = [
            item
            for item in candidates
            if state.cards[item].card.card_type == choice.card_type
        ]
    if choice.work_key:
        candidates = [
            item
            for item in candidates
            if choice.work_key in state.cards[item].card.work_keys
        ]
    if choice.unit_key:
        candidates = [
            item
            for item in candidates
            if choice.unit_key in state.cards[item].card.unit_keys
        ]
    if choice.name_ja_any:
        candidates = [
            item
            for item in candidates
            if _card_name_in(state.cards[item].card.name_ja, choice.name_ja_any)
        ]
    stat_filters = _choice_card_type_stat_filters(choice)
    if stat_filters:
        candidates = [
            item
            for item in candidates
            if _matches_card_type_stat_filter(
                state,
                invocation.player_id,
                item,
                stat_filters,
            )
        ]
    if choice.minimum_cost is not None:
        candidates = [
            item
            for item in candidates
            if (state.cards[item].card.cost or 0) >= choice.minimum_cost
        ]
    if choice.maximum_cost is not None:
        candidates = [
            item
            for item in candidates
            if (state.cards[item].card.cost or 0) <= choice.maximum_cost
        ]
    heart_color_slot = getattr(choice, "heart_color_slot", None)
    minimum_heart_count = getattr(choice, "minimum_heart_count", None)
    if heart_color_slot is not None and minimum_heart_count is not None:
        candidates = [
            item
            for item in candidates
            if _card_heart_or_required_heart_count(
                state.cards[item].card,
                heart_color_slot,
            )
            >= minimum_heart_count
        ]
    if choice.ability_bucket:
        allowed = set(choice.ability_bucket)
        candidates = [
            item
            for item in candidates
            if state.cards[item].card.ability_bucket in allowed
        ]
    return candidates


def _card_matches_operation_filter(
    state: MatchState,
    instance_id: str,
    operation: Any,
    *,
    selected_count: Any = None,
) -> bool:
    card = state.cards[instance_id].card
    if operation.card_type and card.card_type != operation.card_type:
        return False
    value = operation.value if isinstance(operation.value, dict) else {}
    minimum_cost = value.get("minimum_cost")
    if value.get("minimum_cost_source") == "selected_count":
        minimum_cost = selected_count
    if isinstance(minimum_cost, int) and (card.cost or 0) < minimum_cost:
        return False
    maximum_cost = value.get("maximum_cost")
    if value.get("maximum_cost_source") == "selected_count":
        maximum_cost = selected_count
    if isinstance(maximum_cost, int) and (card.cost or 0) > maximum_cost:
        return False
    name_ja_any = value.get("name_ja_any")
    if isinstance(name_ja_any, list) and name_ja_any:
        allowed_names = {item for item in name_ja_any if isinstance(item, str)}
        if card.name_ja not in allowed_names:
            return False
    work_key = value.get("work_key")
    if isinstance(work_key, str) and work_key not in card.work_keys:
        return False
    unit_key = value.get("unit_key")
    if isinstance(unit_key, str) and unit_key not in card.unit_keys:
        return False
    return True


def _execute_operations(
    state: MatchState,
    invocation: EffectInvocation,
    operations: list[Any],
    events: list[GameEvent],
    *,
    selected_ids: list[str],
    selected_ids_by_group: dict[str, list[str]] | None = None,
    energy_ids: Any = None,
    selected_color_slot: Any = None,
    selected_count: Any = None,
    selected_position_slot: Any = None,
    selected_destination: Any = None,
) -> None:
    player = state.players[invocation.player_id]
    effect = state.effect_definitions[invocation.effect_id]
    operation_context: dict[str, Any] = {
        "source_card_instance_id": invocation.source_card_instance_id,
        "selected_card_instance_ids": list(selected_ids),
        "selected_count": selected_count,
    }
    for operation in operations:
        if not _operation_condition_met(state, invocation, operation, operation_context):
            continue
        operation_type = operation.action_type
        operation_selected_ids = _operation_selected_ids(
            operation,
            selected_ids,
            selected_ids_by_group,
        )
        if operation_type == "apply_wait":
            state.cards[invocation.source_card_instance_id].orientation = "wait"
        elif operation_type == "source_to_waiting_room":
            slot = _top_member_slot(player, invocation.source_card_instance_id)
            if slot is not None:
                _move_top_member_off_stage(
                    state,
                    invocation.player_id,
                    slot,
                    "waiting_room",
                    events,
                    reason=f"effect:{invocation.effect_id}",
                )
            elif invocation.source_card_instance_id in player.hand:
                player.hand.remove(invocation.source_card_instance_id)
                player.waiting_room.append(invocation.source_card_instance_id)
                state.cards[invocation.source_card_instance_id].face_up = True
            else:
                raise IllegalActionError("effect source must be on Stage or in hand")
        elif operation_type == "apply_wait_member":
            if operation.target == "opponent_stage_cost2_all":
                opponent_id = (
                    "player_2" if invocation.player_id == "player_1" else "player_1"
                )
                opponent = state.players[opponent_id]
                for instance_id in opponent.member_area.values():
                    if (
                        instance_id is not None
                        and state.cards[instance_id].card.card_type == "member"
                        and (state.cards[instance_id].card.cost or 0) <= 2
                    ):
                        state.cards[instance_id].orientation = "wait"
            elif operation.target == "opponent_stage_original_blade_at_most":
                opponent_id = (
                    "player_2" if invocation.player_id == "player_1" else "player_1"
                )
                threshold = operation.amount if isinstance(operation.amount, int) else 0
                opponent = state.players[opponent_id]
                for instance_id in opponent.member_area.values():
                    if (
                        instance_id is not None
                        and state.cards[instance_id].card.card_type == "member"
                        and (state.cards[instance_id].card.blade or 0) <= threshold
                    ):
                        state.cards[instance_id].orientation = "wait"
            elif operation.target == "selected":
                for instance_id in operation_selected_ids:
                    if not _is_stage_member_instance(state, instance_id):
                        raise IllegalActionError("selected Member must be on Stage")
                    state.cards[instance_id].orientation = "wait"
            else:
                state.cards[invocation.source_card_instance_id].orientation = "wait"
        elif operation_type == "draw_card":
            target_player_id = invocation.player_id
            if operation.target == "opponent":
                target_player_id = (
                    "player_2" if invocation.player_id == "player_1" else "player_1"
                )
            _draw(
                state,
                target_player_id,
                _operation_amount(operation, selected_count, player),
                events,
                reason=f"effect:{invocation.effect_id}",
            )
        elif operation_type == "draw_card_per_stage_member":
            work_key = None
            unit_key = None
            if isinstance(operation.value, dict):
                raw_work_key = operation.value.get("work_key")
                if isinstance(raw_work_key, str):
                    work_key = raw_work_key
                raw_unit_key = operation.value.get("unit_key")
                if isinstance(raw_unit_key, str):
                    unit_key = raw_unit_key
            amount = sum(
                1
                for instance_id in player.member_area.values()
                if instance_id is not None
                and (work_key is None or work_key in state.cards[instance_id].card.work_keys)
                and (unit_key is None or unit_key in state.cards[instance_id].card.unit_keys)
            )
            _draw(
                state,
                invocation.player_id,
                amount,
                events,
                reason=f"effect:{invocation.effect_id}",
            )
        elif operation_type == "draw_until_hand_size":
            target_hand_size = operation.target_hand_size
            if not isinstance(target_hand_size, int):
                raise IllegalActionError("draw_until_hand_size requires target_hand_size")
            _draw(
                state,
                invocation.player_id,
                max(0, target_hand_size - len(player.hand)),
                events,
                reason=f"effect:{invocation.effect_id}",
            )
        elif operation_type == "clear_excess_hearts":
            target_player_id = invocation.player_id
            if operation.target == "opponent":
                target_player_id = (
                    "player_2" if invocation.player_id == "player_1" else "player_1"
                )
            target_player = state.players[target_player_id]
            cleared_count = 0
            if target_player.live_result.live_allocations:
                allocation = target_player.live_result.live_allocations[-1]
                remaining_hearts = allocation.get("remaining_hearts", {})
                if isinstance(remaining_hearts, dict):
                    cleared_count += sum(
                        amount
                        for amount in remaining_hearts.values()
                        if isinstance(amount, int) and amount > 0
                    )
                remaining_all = allocation.get("remaining_all_color_hearts", 0)
                if isinstance(remaining_all, int) and remaining_all > 0:
                    cleared_count += remaining_all
                allocation["remaining_hearts"] = {}
                allocation["remaining_all_color_hearts"] = 0
            operation_context["last_cleared_excess_heart_count"] = cleared_count
            events.append(
                GameEvent(
                    event_type="excess_hearts_cleared",
                    player_id=target_player_id,
                    data={
                        "invocation_id": invocation.invocation_id,
                        "effect_id": invocation.effect_id,
                        "cleared_count": cleared_count,
                    },
                    source="system",
                )
            )
        elif operation_type == "grant_live_success_draw":
            amount = operation.amount if isinstance(operation.amount, int) else 1
            player.manual_modifiers.append(
                ManualModifier(
                    modifier_id=(
                        f"effect:{invocation.invocation_id}:"
                        f"granted_live_success_draw"
                    ),
                    modifier_type="flag",
                    duration=_effect_modifier_duration(effect.duration),
                    created_turn=state.turn_number,
                    flag="granted_live_success_draw",
                    value={"amount": amount},
                    target_card_instance_id=invocation.source_card_instance_id,
                )
            )
        elif operation_type == "disable_source_live_success_effects":
            player.manual_modifiers.append(
                ManualModifier(
                    modifier_id=(
                        f"effect:{invocation.invocation_id}:"
                        f"disabled_live_success_effects"
                    ),
                    modifier_type="flag",
                    duration=_effect_modifier_duration(effect.duration),
                    created_turn=state.turn_number,
                    flag="disabled_live_success_effects",
                    value={"trigger": "live_succeeded"},
                    target_card_instance_id=invocation.source_card_instance_id,
                )
            )
        elif operation_type == "reveal_top_cards":
            amount = _operation_amount(
                operation,
                selected_count,
                player,
                state=state,
                operation_context=operation_context,
            )
            revealed: list[str] = []
            for _ in range(max(0, amount)):
                instance_id = _take_main_deck_card(
                    state,
                    invocation.player_id,
                    events,
                )
                if instance_id is None:
                    break
                player.waiting_room.append(instance_id)
                state.cards[instance_id].face_up = True
                revealed.append(instance_id)
            operation_context["revealed_card_instance_ids"] = revealed
            events.append(
                GameEvent(
                    event_type="effect_cards_revealed",
                    player_id=invocation.player_id,
                    data={
                        "invocation_id": invocation.invocation_id,
                        "effect_id": invocation.effect_id,
                        "revealed_card_instance_ids": revealed,
                        "revealed_cards": [
                            _public_card_snapshot(state, instance_id)
                            for instance_id in revealed
                        ],
                    },
                    source="system",
                )
            )
        elif operation_type == "reveal_top_to_hand":
            amount = _operation_amount(
                operation,
                selected_count,
                player,
                state=state,
                operation_context=operation_context,
            )
            revealed: list[str] = []
            for _ in range(max(0, amount)):
                instance_id = _take_main_deck_card(
                    state,
                    invocation.player_id,
                    events,
                )
                if instance_id is None:
                    break
                player.hand.append(instance_id)
                state.cards[instance_id].face_up = True
                revealed.append(instance_id)
            operation_context["revealed_card_instance_ids"] = revealed
            events.append(
                GameEvent(
                    event_type="effect_cards_revealed_to_hand",
                    player_id=invocation.player_id,
                    data={
                        "invocation_id": invocation.invocation_id,
                        "effect_id": invocation.effect_id,
                        "revealed_card_instance_ids": revealed,
                        "revealed_cards": [
                            _public_card_snapshot(state, instance_id)
                            for instance_id in revealed
                        ],
                    },
                    source="system",
                )
            )
        elif operation_type == "reveal_top_matching_to_hand_else_waiting":
            amount = _operation_amount(
                operation,
                selected_count,
                player,
                state=state,
                operation_context=operation_context,
            )
            revealed: list[str] = []
            matched: list[str] = []
            waiting: list[str] = []
            for _ in range(max(0, amount)):
                instance_id = _take_main_deck_card(
                    state,
                    invocation.player_id,
                    events,
                )
                if instance_id is None:
                    break
                revealed.append(instance_id)
                state.cards[instance_id].face_up = True
                if _card_matches_operation_filter(
                    state,
                    instance_id,
                    operation,
                    selected_count=selected_count,
                ):
                    player.hand.append(instance_id)
                    matched.append(instance_id)
                else:
                    player.waiting_room.append(instance_id)
                    waiting.append(instance_id)
            operation_context["revealed_card_instance_ids"] = revealed
            operation_context["matched_card_instance_ids"] = matched
            events.append(
                GameEvent(
                    event_type="effect_top_cards_revealed",
                    player_id=invocation.player_id,
                    data={
                        "invocation_id": invocation.invocation_id,
                        "effect_id": invocation.effect_id,
                        "revealed_card_instance_ids": revealed,
                        "matched_card_instance_ids": matched,
                        "moved_to_hand_instance_ids": matched,
                        "moved_to_waiting_room_instance_ids": waiting,
                        "revealed_cards": [
                            _public_card_snapshot(state, instance_id)
                            for instance_id in revealed
                        ],
                    },
                    source="system",
                )
            )
        elif operation_type == "reveal_top_matching_to_hand_else_deck_top":
            amount = _operation_amount(
                operation,
                selected_count,
                player,
                state=state,
                operation_context=operation_context,
            )
            revealed: list[str] = []
            matched: list[str] = []
            deck_top: list[str] = []
            for _ in range(max(0, amount)):
                instance_id = _take_main_deck_card(
                    state,
                    invocation.player_id,
                    events,
                )
                if instance_id is None:
                    break
                revealed.append(instance_id)
                state.cards[instance_id].face_up = True
                if _card_matches_operation_filter(
                    state,
                    instance_id,
                    operation,
                    selected_count=selected_count,
                ):
                    player.hand.append(instance_id)
                    matched.append(instance_id)
                else:
                    player.main_deck.insert(0, instance_id)
                    deck_top.append(instance_id)
            operation_context["revealed_card_instance_ids"] = revealed
            operation_context["matched_card_instance_ids"] = matched
            events.append(
                GameEvent(
                    event_type="effect_top_cards_revealed",
                    player_id=invocation.player_id,
                    data={
                        "invocation_id": invocation.invocation_id,
                        "effect_id": invocation.effect_id,
                        "revealed_card_instance_ids": revealed,
                        "matched_card_instance_ids": matched,
                        "moved_to_hand_instance_ids": matched,
                        "moved_to_deck_top_instance_ids": deck_top,
                        "revealed_cards": [
                            _public_card_snapshot(state, instance_id)
                            for instance_id in revealed
                        ],
                    },
                    source="system",
                )
            )
        elif operation_type == "reveal_selected_cards":
            for instance_id in operation_selected_ids:
                state.cards[instance_id].face_up = True
            events.append(
                GameEvent(
                    event_type="effect_cards_revealed",
                    player_id=invocation.player_id,
                    data={
                        "invocation_id": invocation.invocation_id,
                        "effect_id": invocation.effect_id,
                        "revealed_card_instance_ids": list(operation_selected_ids),
                        "revealed_cards": [
                            _public_card_snapshot(state, instance_id)
                            for instance_id in operation_selected_ids
                        ],
                    },
                    source="system",
                )
            )
        elif operation_type == "draw_if_selected_none_card_type":
            if not any(
                state.cards[item].card.card_type == operation.card_type
                for item in operation_selected_ids
            ):
                _draw(
                    state,
                    invocation.player_id,
                    operation.amount or 0,
                    events,
                    reason=f"effect:{invocation.effect_id}",
                )
        elif operation_type == "draw_if_selected_card_type":
            if any(
                state.cards[item].card.card_type == operation.card_type
                for item in operation_selected_ids
            ):
                _draw(
                    state,
                    invocation.player_id,
                    operation.amount or 0,
                    events,
                    reason=f"effect:{invocation.effect_id}",
                )
        elif operation_type == "discard_from_hand":
            for instance_id in operation_selected_ids:
                if instance_id not in player.hand:
                    raise IllegalActionError("effect discard target must be in hand")
                player.hand.remove(instance_id)
                player.waiting_room.append(instance_id)
        elif operation_type == "return_from_waiting_room":
            for instance_id in operation_selected_ids:
                if instance_id not in player.waiting_room:
                    raise IllegalActionError("effect return target must be in Waiting Room")
                player.waiting_room.remove(instance_id)
                player.hand.append(instance_id)
                state.cards[instance_id].face_up = True
        elif operation_type == "return_baton_replaced_member_to_hand":
            instance_id = invocation.trigger_data.get("replacement_card_instance_id")
            if not isinstance(instance_id, str):
                raise IllegalActionError("baton replaced member is unavailable")
            if instance_id not in player.waiting_room:
                raise IllegalActionError("baton replaced member must be in Waiting Room")
            player.waiting_room.remove(instance_id)
            player.hand.append(instance_id)
            state.cards[instance_id].face_up = True
        elif operation_type == "move_selected_to_hand":
            for instance_id in operation_selected_ids:
                if instance_id in player.resolution_area:
                    player.resolution_area.remove(instance_id)
                elif instance_id in player.waiting_room:
                    player.waiting_room.remove(instance_id)
                else:
                    raise IllegalActionError(
                        "effect hand target must be in a selectable public zone"
                    )
                player.hand.append(instance_id)
                state.cards[instance_id].face_up = True
        elif operation_type == "move_selected_to_deck_bottom":
            for instance_id in operation_selected_ids:
                if instance_id in player.hand:
                    player.hand.remove(instance_id)
                elif instance_id in player.resolution_area:
                    player.resolution_area.remove(instance_id)
                else:
                    raise IllegalActionError(
                        "effect deck-bottom target must be in hand or Resolution Area"
                    )
                player.main_deck.append(instance_id)
                state.cards[instance_id].face_up = False
        elif operation_type == "move_selected_to_deck_top_or_bottom":
            if selected_destination not in {
                "main_deck_top",
                "main_deck_bottom",
            }:
                raise IllegalActionError("effect deck destination is not legal")
            for instance_id in operation_selected_ids:
                if instance_id not in player.hand:
                    raise IllegalActionError("effect deck target must be in hand")
                player.hand.remove(instance_id)
            if selected_destination == "main_deck_top":
                for instance_id in reversed(operation_selected_ids):
                    player.main_deck.insert(0, instance_id)
                    state.cards[instance_id].face_up = False
            else:
                for instance_id in operation_selected_ids:
                    player.main_deck.append(instance_id)
                    state.cards[instance_id].face_up = False
        elif operation_type == "deploy_selected_to_empty_stage":
            if len(operation_selected_ids) != 1:
                raise IllegalActionError("effect requires exactly one Member to deploy")
            slot = selected_position_slot
            if not isinstance(slot, str) or slot not in _empty_member_area_slots(player):
                raise IllegalActionError("effect deploy slot selection is not legal")
            instance_id = operation_selected_ids[0]
            source_zone = effect.choice.zone if effect.choice is not None else "waiting_room"
            if source_zone == "hand":
                if instance_id not in player.hand:
                    raise IllegalActionError("effect deploy target must be in hand")
                player.hand.remove(instance_id)
            elif source_zone in {None, "waiting_room"}:
                if instance_id not in player.waiting_room:
                    raise IllegalActionError(
                        "effect deploy target must be in Waiting Room"
                    )
                player.waiting_room.remove(instance_id)
            else:
                raise IllegalActionError("effect deploy source zone is not supported")
            if state.cards[instance_id].card.card_type != "member":
                raise IllegalActionError("effect deploy target must be a Member")
            player.member_area[slot] = instance_id
            player.member_entered_count_this_turn += 1
            if slot not in player.member_areas_entered_this_turn:
                player.member_areas_entered_this_turn.append(slot)
            state.cards[instance_id].face_up = True
            state.cards[instance_id].orientation = operation.orientation or "wait"
            events.append(
                GameEvent(
                    event_type=(
                        "effect_member_deployed_from_hand"
                        if source_zone == "hand"
                        else "effect_member_deployed_from_waiting_room"
                    ),
                    player_id=invocation.player_id,
                    data={
                        "invocation_id": invocation.invocation_id,
                        "effect_id": invocation.effect_id,
                        "card_instance_id": instance_id,
                        "source_zone": source_zone or "waiting_room",
                        "slot": slot,
                        "orientation": state.cards[instance_id].orientation,
                    },
                    source="system",
                )
            )
        elif operation_type == "move_waiting_room_members_to_deck_bottom":
            if operation.target not in {None, "self", "both"}:
                raise IllegalActionError(
                    "waiting-room member deck-bottom target must be self or both"
                )
            target_player_ids = (
                list(state.players)
                if operation.target == "both"
                else [invocation.player_id]
            )
            total_moved = 0
            moved_by_player: dict[str, list[str]] = {}
            for target_player_id in target_player_ids:
                target_player = state.players[target_player_id]
                moved = [
                    instance_id
                    for instance_id in target_player.waiting_room
                    if state.cards[instance_id].card.card_type == "member"
                ]
                if not moved:
                    moved_by_player[target_player_id] = []
                    continue
                target_player.waiting_room = [
                    instance_id
                    for instance_id in target_player.waiting_room
                    if instance_id not in set(moved)
                ]
                shuffled = _deterministic_shuffle(
                    moved,
                    state.seed,
                    (
                        f"effect:{invocation.invocation_id}:"
                        f"waiting-members-bottom:{target_player_id}"
                    ),
                )
                target_player.main_deck.extend(shuffled)
                for instance_id in shuffled:
                    state.cards[instance_id].face_up = False
                total_moved += len(shuffled)
                moved_by_player[target_player_id] = shuffled
            invocation.trigger_data["bulk_moved_waiting_room_member_count"] = (
                total_moved
            )
            events.append(
                GameEvent(
                    event_type="effect_cards_moved_to_deck_bottom",
                    player_id=invocation.player_id,
                    data={
                        "invocation_id": invocation.invocation_id,
                        "effect_id": invocation.effect_id,
                        "moved_card_instance_ids_by_player": moved_by_player,
                        "total_moved": total_moved,
                    },
                    source="system",
                )
            )
        elif operation_type == "move_selected_to_deck_top":
            source_zone = effect.choice.zone if effect.choice is not None else "waiting_room"
            for instance_id in reversed(operation_selected_ids):
                if source_zone == "hand":
                    if instance_id not in player.hand:
                        raise IllegalActionError("effect deck-top target must be in hand")
                    player.hand.remove(instance_id)
                elif source_zone == "resolution_area":
                    if instance_id not in player.resolution_area:
                        raise IllegalActionError(
                            "effect deck-top target must be in Resolution Area"
                        )
                    player.resolution_area.remove(instance_id)
                else:
                    if instance_id not in player.waiting_room:
                        raise IllegalActionError(
                            "effect deck-top target must be in Waiting Room"
                        )
                    player.waiting_room.remove(instance_id)
                player.main_deck.insert(0, instance_id)
                state.cards[instance_id].face_up = False
        elif operation_type == "ready_member":
            if operation.target == "self_stage_all":
                for instance_id in player.member_area.values():
                    if instance_id is not None:
                        previous = state.cards[instance_id].orientation
                        state.cards[instance_id].orientation = "active"
                        _record_effect_ready_flag(
                            state,
                            player,
                            invocation,
                            ready_type="member",
                            previous_orientation=previous,
                        )
            elif operation.target == "source":
                if not _is_stage_member_instance(state, invocation.source_card_instance_id):
                    raise IllegalActionError("effect source must be on Stage")
                previous = state.cards[invocation.source_card_instance_id].orientation
                state.cards[invocation.source_card_instance_id].orientation = "active"
                _record_effect_ready_flag(
                    state,
                    player,
                    invocation,
                    ready_type="member",
                    previous_orientation=previous,
                )
            else:
                for instance_id in operation_selected_ids:
                    if not _is_stage_member_instance(state, instance_id):
                        raise IllegalActionError("selected Member must be on Stage")
                    previous = state.cards[instance_id].orientation
                    state.cards[instance_id].orientation = "active"
                    _record_effect_ready_flag(
                        state,
                        player,
                        invocation,
                        ready_type="member",
                        previous_orientation=previous,
                    )
        elif operation_type == "apply_wait_energy":
            required = _operation_amount(operation, selected_count)
            if required and len(operation_selected_ids) != required:
                raise IllegalActionError(
                    f"effect requires exactly {required} selected Energy"
                )
            if len(operation_selected_ids) != len(set(operation_selected_ids)):
                raise IllegalActionError("selected Energy must be unique")
            for instance_id in operation_selected_ids:
                if (
                    instance_id not in player.energy_area
                    or state.cards[instance_id].card.card_type != "energy"
                ):
                    raise IllegalActionError(
                        "selected Energy must be in the Energy Area"
                    )
                state.cards[instance_id].orientation = "wait"
        elif operation_type == "pay_energy":
            required = _operation_amount(
                operation,
                selected_count,
                player,
                state=state,
                operation_context=operation_context,
            )
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
        elif operation_type == "place_energy_from_deck":
            if operation.target not in {None, "self", "opponent", "both"}:
                raise IllegalActionError(
                    "place_energy_from_deck only supports self, opponent, or both players"
                )
            amount = _operation_amount(
                operation,
                selected_count,
                player,
                state=state,
                operation_context=operation_context,
            )
            if operation.target == "both":
                target_player_ids = list(state.players)
            elif operation.target == "opponent":
                target_player_ids = [
                    "player_2" if invocation.player_id == "player_1" else "player_1"
                ]
            else:
                target_player_ids = [invocation.player_id]
            for target_player_id in target_player_ids:
                target_player = state.players[target_player_id]
                if len(target_player.energy_deck) < amount:
                    continue
                _move_energy_to_area(
                    state,
                    target_player_id,
                    amount,
                    events,
                    reason=f"effect:{invocation.effect_id}",
                    orientation=operation.orientation or "active",
                )
        elif operation_type == "gain_blade":
            amount = _operation_amount(
                operation,
                selected_count,
                player,
                state=state,
                operation_context=operation_context,
            )
            target_ids = (
                operation_selected_ids
                if operation.target == "selected"
                or _effect_uses_grouped_stage_member_choice(effect)
                else [invocation.source_card_instance_id]
            )
            for target_id in target_ids:
                player.manual_modifiers.append(
                    ManualModifier(
                        modifier_id=f"effect:{invocation.invocation_id}:blade:{target_id}",
                        modifier_type="blade",
                        duration=_effect_modifier_duration(effect.duration),
                        created_turn=state.turn_number,
                        amount=amount,
                        target_card_instance_id=target_id,
                    )
                )
        elif operation_type == "gain_blade_to_stage_members":
            for target_id in _stage_member_targets_for_operation(
                state, player, invocation, operation
            ):
                player.manual_modifiers.append(
                    ManualModifier(
                        modifier_id=f"effect:{invocation.invocation_id}:blade:{target_id}",
                        modifier_type="blade",
                        duration=_effect_modifier_duration(effect.duration),
                        created_turn=state.turn_number,
                        amount=operation.amount or 0,
                        target_card_instance_id=target_id,
                    )
                )
        elif operation_type == "gain_heart_to_stage_members":
            color_slot = operation.color_slot or selected_color_slot
            if not isinstance(color_slot, str):
                raise IllegalActionError(
                    "gain_heart_to_stage_members requires a selected Heart color"
                )
            amount = _operation_amount(
                operation,
                selected_count,
                player,
                state=state,
                operation_context=operation_context,
            )
            for target_id in _stage_member_targets_for_operation(
                state, player, invocation, operation
            ):
                player.manual_modifiers.append(
                    ManualModifier(
                        modifier_id=(
                            f"effect:{invocation.invocation_id}:heart:"
                            f"{color_slot}:{target_id}"
                        ),
                        modifier_type="heart",
                        duration=_effect_modifier_duration(effect.duration),
                        created_turn=state.turn_number,
                        amount=amount,
                        color_slot=color_slot,
                        target_card_instance_id=target_id,
                    )
                )
        elif operation_type == "gain_heart":
            color_slot = operation.color_slot or selected_color_slot
            if not isinstance(color_slot, str):
                raise IllegalActionError("effect requires a selected Heart color")
            target_ids = (
                operation_selected_ids
                if operation.target == "selected"
                else operation_selected_ids or [invocation.source_card_instance_id]
            )
            amount = _operation_amount(
                operation,
                selected_count,
                player,
                state=state,
                operation_context=operation_context,
            )
            for target_id in target_ids:
                player.manual_modifiers.append(
                    ManualModifier(
                        modifier_id=(
                            f"effect:{invocation.invocation_id}:heart:"
                            f"{color_slot}:{target_id}"
                        ),
                        modifier_type="heart",
                        duration=_effect_modifier_duration(effect.duration),
                        created_turn=state.turn_number,
                        amount=amount,
                        color_slot=color_slot,
                        target_card_instance_id=target_id,
                    )
                )
        elif operation_type == "gain_heart_from_selected_card_colors":
            target_id = _stage_member_target_for_operation_value(
                state,
                player,
                operation,
            )
            for selected_id in operation_selected_ids:
                if selected_id not in state.cards:
                    raise IllegalActionError("selected Heart source card is unavailable")
                selected_card = state.cards[selected_id].card
                color_slots = [
                    color_slot
                    for color_slot, amount in sorted(selected_card.basic_hearts.items())
                    if amount > 0
                ]
                for color_slot in color_slots:
                    player.manual_modifiers.append(
                        ManualModifier(
                            modifier_id=(
                                f"effect:{invocation.invocation_id}:heart_from_card:"
                                f"{selected_id}:{color_slot}"
                            ),
                            modifier_type="heart",
                            duration=_effect_modifier_duration(effect.duration),
                            created_turn=state.turn_number,
                            amount=1,
                            color_slot=color_slot,
                            target_card_instance_id=target_id,
                        )
                    )
        elif operation_type == "replace_member_base_hearts":
            color_slot = operation.color_slot or selected_color_slot
            if not isinstance(color_slot, str):
                raise IllegalActionError(
                    "replace_member_base_hearts requires a selected Heart color"
                )
            target_ids = operation_selected_ids or [invocation.source_card_instance_id]
            for target_id in target_ids:
                player.manual_modifiers.append(
                    ManualModifier(
                        modifier_id=(
                            f"effect:{invocation.invocation_id}:"
                            f"base_heart_replacement:{color_slot}:{target_id}"
                        ),
                        modifier_type="base_heart_replacement",
                        duration=_effect_modifier_duration(effect.duration),
                        created_turn=state.turn_number,
                        color_slot=color_slot,
                        value={"mode": "replace_original_hearts"},
                        target_card_instance_id=target_id,
                    )
                )
        elif operation_type == "replace_member_base_blade":
            target_ids = list(operation_selected_ids)
            if not target_ids:
                if isinstance(operation.value, dict):
                    target_ids = _stage_member_targets_for_operation(
                        state, player, invocation, operation
                    )
                else:
                    target_ids = [invocation.source_card_instance_id]
            for target_id in target_ids:
                player.manual_modifiers.append(
                    ManualModifier(
                        modifier_id=(
                            f"effect:{invocation.invocation_id}:"
                            f"base_blade_replacement:{target_id}"
                        ),
                        modifier_type="base_blade_replacement",
                        duration=_effect_modifier_duration(effect.duration),
                        created_turn=state.turn_number,
                        amount=operation.amount or 0,
                        value={"mode": "replace_original_blade"},
                        target_card_instance_id=target_id,
                    )
                )
        elif operation_type == "position_change_source":
            from_slot = _top_member_slot(player, invocation.source_card_instance_id)
            if from_slot is None:
                raise IllegalActionError("position change source is not on Stage")
            target_slots = _position_change_source_target_slots(state, invocation)
            to_slot = selected_position_slot
            if to_slot is None:
                to_slot = target_slots[0] if target_slots else None
            if to_slot not in target_slots:
                raise IllegalActionError("position change target slot is not legal")
            _position_change(
                state,
                invocation.player_id,
                {"from_slot": from_slot, "to_slot": to_slot},
                events,
            )
        elif operation_type == "position_change_selected":
            if len(operation_selected_ids) != 1:
                raise IllegalActionError(
                    "position change selected requires exactly one member"
                )
            selected_id = operation_selected_ids[0]
            from_slot = _top_member_slot(player, selected_id)
            if from_slot is None:
                raise IllegalActionError(
                    "position change selected target is not on Stage"
                )
            target_slots = [
                slot for slot in ("left", "center", "right") if slot != from_slot
            ]
            to_slot = selected_position_slot
            if to_slot is None:
                to_slot = target_slots[0] if target_slots else None
            if to_slot not in target_slots:
                raise IllegalActionError("position change target slot is not legal")
            _position_change(
                state,
                invocation.player_id,
                {"from_slot": from_slot, "to_slot": to_slot},
                events,
            )
        elif operation_type == "modify_score":
            player.manual_modifiers.append(
                ManualModifier(
                    modifier_id=f"effect:{invocation.invocation_id}:score",
                    modifier_type="score",
                    duration=_effect_modifier_duration(effect.duration),
                    created_turn=state.turn_number,
                    amount=_operation_amount(
                        operation,
                        selected_count,
                        player,
                        state=state,
                        operation_context=operation_context,
                    ),
                )
            )
        elif operation_type == "replace_score":
            player.manual_modifiers.append(
                ManualModifier(
                    modifier_id=f"effect:{invocation.invocation_id}:score:replace",
                    modifier_type="score_replacement",
                    duration=_effect_modifier_duration(effect.duration),
                    created_turn=state.turn_number,
                    amount=operation.amount or 0,
                    target_card_instance_id=invocation.source_card_instance_id,
                )
            )
        elif operation_type == "modify_required_heart":
            color_slot = operation.color_slot
            if not isinstance(color_slot, str):
                raise IllegalActionError("modify_required_heart requires color_slot")
            player.manual_modifiers.append(
                ManualModifier(
                    modifier_id=(
                        f"effect:{invocation.invocation_id}:required_heart:"
                        f"{color_slot}"
                    ),
                    modifier_type="required_heart",
                    duration=_effect_modifier_duration(effect.duration),
                    created_turn=state.turn_number,
                    amount=_operation_amount(
                        operation,
                        selected_count,
                        player,
                        state=state,
                        operation_context=operation_context,
                    ),
                    color_slot=color_slot,
                    target_card_instance_id=_live_modifier_target_id(
                        state, invocation
                    ),
                )
            )
        elif operation_type == "replace_required_hearts":
            if not isinstance(operation.value, dict):
                raise IllegalActionError("replace_required_hearts requires a value map")
            replacement = {
                str(color): int(amount)
                for color, amount in operation.value.items()
                if isinstance(amount, int) and amount > 0
            }
            player.manual_modifiers.append(
                ManualModifier(
                    modifier_id=f"effect:{invocation.invocation_id}:required_heart:replace",
                    modifier_type="required_heart",
                    duration=_effect_modifier_duration(effect.duration),
                    created_turn=state.turn_number,
                    value={
                        "mode": "replace",
                        "required_hearts": dict(sorted(replacement.items())),
                    },
                    target_card_instance_id=_live_modifier_target_id(
                        state, invocation
                    ),
                )
            )
        elif operation_type == "replace_yell_blade_hearts":
            color_slot = operation.color_slot
            if not isinstance(color_slot, str):
                raise IllegalActionError("replace_yell_blade_hearts requires color_slot")
            player.manual_modifiers.append(
                ManualModifier(
                    modifier_id=(
                        f"effect:{invocation.invocation_id}:"
                        f"yell_blade_heart_replacement:{color_slot}"
                    ),
                    modifier_type="yell_blade_heart_replacement",
                    duration=_effect_modifier_duration(effect.duration),
                    created_turn=state.turn_number,
                    color_slot=color_slot,
                    value=dict(operation.value or {}),
                )
            )
        elif operation_type == "modify_yell_count":
            amount = operation.amount
            if not isinstance(amount, int):
                raise IllegalActionError("modify_yell_count requires an integer amount")
            player.manual_modifiers.append(
                ManualModifier(
                    modifier_id=f"effect:{invocation.invocation_id}:yell_count",
                    modifier_type="yell_count_modifier",
                    duration=_effect_modifier_duration(effect.duration),
                    created_turn=state.turn_number,
                    amount=amount,
                    target_card_instance_id=invocation.source_card_instance_id,
                )
            )
        elif operation_type == "ready_energy":
            if operation_selected_ids:
                required = _operation_amount(operation, selected_count)
                if required and len(operation_selected_ids) != required:
                    raise IllegalActionError(
                        f"effect requires exactly {required} selected Energy"
                    )
                if len(operation_selected_ids) != len(set(operation_selected_ids)):
                    raise IllegalActionError("selected Energy must be unique")
                for instance_id in operation_selected_ids:
                    if (
                        instance_id not in player.energy_area
                        or state.cards[instance_id].card.card_type != "energy"
                    ):
                        raise IllegalActionError(
                            "selected Energy must be in the Energy Area"
                        )
                    previous = state.cards[instance_id].orientation
                    state.cards[instance_id].orientation = "active"
                    _record_effect_ready_flag(
                        state,
                        player,
                        invocation,
                        ready_type="energy",
                        previous_orientation=previous,
                    )
            else:
                waiting = [
                    item
                    for item in player.energy_area
                    if state.cards[item].orientation == "wait"
                ]
                amount = _operation_amount(operation, selected_count, player, state=state)
                for instance_id in waiting[:amount]:
                    previous = state.cards[instance_id].orientation
                    state.cards[instance_id].orientation = "active"
                    _record_effect_ready_flag(
                        state,
                        player,
                        invocation,
                        ready_type="energy",
                        previous_orientation=previous,
                    )
        elif operation_type == "set_flag":
            if not operation.flag:
                raise IllegalActionError("effect set_flag requires a flag name")
            target_card_instance_id = (
                invocation.source_card_instance_id
                if operation.target == "source"
                else None
            )
            player.manual_modifiers.append(
                ManualModifier(
                    modifier_id=f"effect:{invocation.invocation_id}:flag:{operation.flag}",
                    modifier_type="flag",
                    duration=_effect_modifier_duration(effect.duration),
                    created_turn=state.turn_number,
                    flag=operation.flag,
                    value=operation.value if operation.value is not None else True,
                    target_card_instance_id=target_card_instance_id,
                )
            )
        elif operation_type == "prevent_equal_score_success_live_placement":
            summary = state.live_judgment_summary or {}
            if summary.get("basis") != "equal_total_score":
                continue
            prevented: dict[str, list[str]] = {}
            for target_player_id, moved_ids in list(
                state.success_live_moved_instance_ids.items()
            ):
                target_player = state.players[target_player_id]
                for instance_id in list(moved_ids):
                    if instance_id not in target_player.success_live_area:
                        continue
                    target_player.success_live_area.remove(instance_id)
                    target_player.live_area.append(instance_id)
                    prevented.setdefault(target_player_id, []).append(instance_id)
            if prevented:
                state.success_live_moved_instance_ids = {}
                state.success_live_moved_player_ids = []
                events.append(
                    GameEvent(
                        event_type="success_live_placement_prevented",
                        player_id=invocation.player_id,
                        data={
                            "invocation_id": invocation.invocation_id,
                            "effect_id": invocation.effect_id,
                            "prevented_instance_ids_by_player": prevented,
                        },
                        source="system",
                    )
                )
        elif operation_type == "rotate_stage_members":
            target = operation.target or "self"
            if target == "both":
                target_player_ids = list(state.players)
            elif target == "opponent":
                target_player_ids = [
                    "player_2" if invocation.player_id == "player_1" else "player_1"
                ]
            elif target == "self":
                target_player_ids = [invocation.player_id]
            else:
                raise IllegalActionError(
                    "rotate_stage_members only supports self, opponent, or both"
                )
            for target_player_id in target_player_ids:
                _rotate_stage_member_groups(state, target_player_id, events)
        elif operation_type == "mill_top_cards":
            milled: list[str] = []
            for _ in range(operation.amount or 0):
                instance_id = _take_main_deck_card(
                    state,
                    invocation.player_id,
                    events,
                )
                if instance_id is None:
                    break
                player.waiting_room.append(instance_id)
                state.cards[instance_id].face_up = True
                milled.append(instance_id)
            operation_context["milled_card_instance_ids"] = milled
            events.append(
                GameEvent(
                    event_type="effect_cards_milled",
                    player_id=invocation.player_id,
                    data={
                        "invocation_id": invocation.invocation_id,
                        "effect_id": invocation.effect_id,
                        "milled_card_instance_ids": milled,
                    },
                    source="system",
                )
            )
        elif operation_type == "draw_if_milled_all_card_type":
            milled = operation_context.get("milled_card_instance_ids", [])
            if milled and all(
                state.cards[item].card.card_type == operation.card_type
                for item in milled
            ):
                _draw(
                    state,
                    invocation.player_id,
                    operation.amount or 0,
                    events,
                    reason=f"effect:{invocation.effect_id}",
                )
        elif operation_type == "draw_if_milled_any_card_type":
            milled = operation_context.get("milled_card_instance_ids", [])
            if any(
                state.cards[item].card.card_type == operation.card_type
                for item in milled
            ):
                _draw(
                    state,
                    invocation.player_id,
                    operation.amount or 0,
                    events,
                    reason=f"effect:{invocation.effect_id}",
                )
        elif operation_type == "gain_heart_if_milled_all_have_heart":
            milled = operation_context.get("milled_card_instance_ids", [])
            color_slot = operation.color_slot
            if color_slot and milled and all(
                state.cards[item].card.basic_hearts.get(color_slot, 0) > 0
                for item in milled
            ):
                player.manual_modifiers.append(
                    ManualModifier(
                        modifier_id=(
                            f"effect:{invocation.invocation_id}:heart:{color_slot}"
                        ),
                        modifier_type="heart",
                        duration=_effect_modifier_duration(effect.duration),
                        created_turn=state.turn_number,
                        amount=operation.amount or 0,
                        color_slot=color_slot,
                    )
                )
        elif operation_type == "gain_blade_if_milled_any_card_type":
            milled = operation_context.get("milled_card_instance_ids", [])
            if any(
                state.cards[item].card.card_type == operation.card_type
                for item in milled
            ):
                player.manual_modifiers.append(
                    ManualModifier(
                        modifier_id=f"effect:{invocation.invocation_id}:blade",
                        modifier_type="blade",
                        duration=_effect_modifier_duration(effect.duration),
                        created_turn=state.turn_number,
                        amount=operation.amount or 0,
                        target_card_instance_id=invocation.source_card_instance_id,
                    )
                )
        elif operation_type == "gain_blade_if_milled_all_card_type":
            milled = operation_context.get("milled_card_instance_ids", [])
            if milled and all(
                state.cards[item].card.card_type == operation.card_type
                for item in milled
            ):
                player.manual_modifiers.append(
                    ManualModifier(
                        modifier_id=f"effect:{invocation.invocation_id}:blade",
                        modifier_type="blade",
                        duration=_effect_modifier_duration(effect.duration),
                        created_turn=state.turn_number,
                        amount=operation.amount or 0,
                        target_card_instance_id=invocation.source_card_instance_id,
                    )
                )
        elif operation_type == "manual_resolution":
            raise IllegalActionError("manual effect operations cannot auto-resolve")
        else:
            raise IllegalActionError(f"unsupported effect operation: {operation_type}")


def _operation_amount(
    operation: Any,
    selected_count: Any = None,
    player: PlayerState | None = None,
    *,
    state: MatchState | None = None,
    operation_context: dict[str, Any] | None = None,
) -> int:
    multiplier = operation.multiplier if isinstance(operation.multiplier, int) else 1
    if isinstance(operation.amount, int):
        return operation.amount * multiplier
    if operation.amount_source == "all_energy_active_bonus" and player is not None:
        if player.energy_area and all(
            state is not None and state.cards[item].orientation == "active"
            for item in player.energy_area
        ):
            amount = 1
            if isinstance(operation.value, dict) and isinstance(
                operation.value.get("amount"),
                int,
            ):
                amount = operation.value["amount"]
            return amount * multiplier
        return 0
    if operation.amount_source == "success_live_count" and player is not None:
        return len(player.success_live_area) * multiplier
    if operation.amount_source == "own_hand_count_divided_by" and player is not None:
        divisor = 1
        if isinstance(operation.value, dict):
            raw_divisor = operation.value.get("divisor")
            if isinstance(raw_divisor, int) and raw_divisor > 0:
                divisor = raw_divisor
        return (len(player.hand) // divisor) * multiplier
    if operation.amount_source == "own_energy_count_divided_by" and player is not None:
        divisor = 1
        if isinstance(operation.value, dict):
            raw_divisor = operation.value.get("divisor")
            if isinstance(raw_divisor, int) and raw_divisor > 0:
                divisor = raw_divisor
        return (len(player.energy_area) // divisor) * multiplier
    if (
        operation.amount_source == "milled_member_work_count"
        and state is not None
        and operation_context is not None
    ):
        work_key = None
        if isinstance(operation.value, dict):
            work_key = operation.value.get("work_key")
        if not isinstance(work_key, str):
            return 0
        milled = operation_context.get("milled_card_instance_ids", [])
        if not isinstance(milled, list):
            return 0
        return (
            sum(
                item in state.cards
                and state.cards[item].card.card_type == "member"
                and work_key in state.cards[item].card.work_keys
                for item in milled
            )
            * multiplier
        )
    if (
        operation.amount_source == "success_live_name_count"
        and player is not None
        and state is not None
    ):
        name_ja = None
        if isinstance(operation.value, dict):
            name_ja = operation.value.get("name_ja")
        if not isinstance(name_ja, str):
            return 0
        return (
            sum(
                _card_name_matches(state.cards[item].card.name_ja, name_ja)
                for item in player.success_live_area
            )
            * multiplier
        )
    if operation.amount_source == "success_live_score" and player is not None:
        if state is None:
            return 0
        return (
            sum(
                _card_score(state, player.player_id, item)
                for item in player.success_live_area
            )
            * multiplier
        )
    if (
        operation.amount_source == "success_live_score_threshold_bonus"
        and player is not None
        and state is not None
    ):
        thresholds: dict[int, int] = {}
        if isinstance(operation.value, dict):
            raw_thresholds = operation.value.get("thresholds")
            if isinstance(raw_thresholds, dict):
                thresholds = {
                    int(threshold): int(amount)
                    for threshold, amount in raw_thresholds.items()
                    if isinstance(amount, int)
                    and str(threshold).lstrip("-").isdigit()
                }
        if not thresholds:
            return 0
        actual = sum(
            _card_score(state, player.player_id, item)
            for item in player.success_live_area
        )
        amount = 0
        for threshold, threshold_amount in sorted(thresholds.items()):
            if actual >= threshold:
                amount = threshold_amount
        return amount * multiplier
    if (
        operation.amount_source == "success_live_score_values_bonus"
        and player is not None
        and state is not None
    ):
        scores: set[int] = set()
        if isinstance(operation.value, dict):
            raw_scores = operation.value.get("scores")
            if isinstance(raw_scores, list):
                scores = {score for score in raw_scores if isinstance(score, int)}
        if not scores:
            return 0
        present_scores = {
            _card_score(state, player.player_id, item)
            for item in player.success_live_area
            if _card_score(state, player.player_id, item) in scores
        }
        return len(present_scores) * multiplier
    if operation.amount_source == "live_area_count" and player is not None:
        return len(player.live_area) * multiplier
    if (
        operation.amount_source == "other_live_area_work_count"
        and player is not None
        and state is not None
    ):
        work_key = None
        card_type = None
        if isinstance(operation.value, dict):
            work_key = operation.value.get("work_key")
            card_type = operation.value.get("card_type")
        source_id = None
        if isinstance(operation_context, dict):
            source_id = operation_context.get("source_card_instance_id")
        return (
            sum(
                item != source_id
                and (not isinstance(card_type, str) or state.cards[item].card.card_type == card_type)
                and (
                    not isinstance(work_key, str)
                    or work_key in state.cards[item].card.work_keys
                )
                for item in player.live_area
            )
            * multiplier
        )
    if (
        operation.amount_source == "moved_stage_member_count"
        and player is not None
        and state is not None
    ):
        work_key = None
        unit_key = None
        if isinstance(operation.value, dict):
            work_key = operation.value.get("work_key")
            unit_key = operation.value.get("unit_key")
        count = 0
        for slot in player.member_areas_moved_this_turn:
            instance_id = player.member_area.get(slot)
            if instance_id is None:
                continue
            card = state.cards[instance_id].card
            if isinstance(work_key, str) and work_key not in card.work_keys:
                continue
            if isinstance(unit_key, str) and unit_key not in card.unit_keys:
                continue
            count += 1
        return count * multiplier
    if (
        operation.amount_source == "stage_member_with_heart_excluding_colors_count"
        and player is not None
        and state is not None
    ):
        excluded_colors: set[str] = set()
        work_key = None
        unit_key = None
        if isinstance(operation.value, dict):
            raw_excluded = operation.value.get("exclude_color_slots")
            if isinstance(raw_excluded, list):
                excluded_colors = {
                    color for color in raw_excluded if isinstance(color, str)
                }
            work_key = operation.value.get("work_key")
            unit_key = operation.value.get("unit_key")
        count = 0
        for instance_id in player.member_area.values():
            if instance_id is None:
                continue
            card = state.cards[instance_id].card
            if isinstance(work_key, str) and work_key not in card.work_keys:
                continue
            if isinstance(unit_key, str) and unit_key not in card.unit_keys:
                continue
            colors = {
                color
                for color in _member_heart_color_slots(
                    state, player.player_id, instance_id
                )
                if color not in excluded_colors
            }
            if colors:
                count += 1
        return count * multiplier
    if (
        operation.amount_source == "stage_member_more_than_original_heart_count"
        and player is not None
        and state is not None
    ):
        work_key = None
        unit_key = None
        thresholds: dict[int, int] = {}
        if isinstance(operation.value, dict):
            work_key = operation.value.get("work_key")
            unit_key = operation.value.get("unit_key")
            raw_thresholds = operation.value.get("thresholds")
            if isinstance(raw_thresholds, dict):
                thresholds = {
                    int(threshold): int(amount)
                    for threshold, amount in raw_thresholds.items()
                    if isinstance(amount, int)
                    and str(threshold).lstrip("-").isdigit()
                }
        actual = _stage_member_more_than_original_heart_count(
            state,
            player.player_id,
            work_key=work_key,
            unit_key=unit_key,
        )
        if thresholds:
            amount = 0
            for threshold, threshold_amount in sorted(thresholds.items()):
                if actual >= threshold:
                    amount = threshold_amount
            return amount * multiplier
        return actual * multiplier
    if (
        operation.amount_source == "own_wait_stage_member_count"
        and player is not None
        and state is not None
    ):
        return (
            sum(
                instance_id is not None
                and state.cards[instance_id].orientation == "wait"
                for instance_id in player.member_area.values()
            )
            * multiplier
        )
    if (
        operation.amount_source == "opponent_stage_wait_member_count"
        and player is not None
        and state is not None
    ):
        opponent_id = "player_2" if player.player_id == "player_1" else "player_1"
        opponent = state.players[opponent_id]
        return (
            sum(
                instance_id is not None
                and state.cards[instance_id].orientation == "wait"
                for instance_id in opponent.member_area.values()
            )
            * multiplier
        )
    if (
        operation.amount_source == "stage_slot_member_heart_pair_count"
        and player is not None
        and state is not None
    ):
        slot = "center"
        color_slot = None
        divisor = 2
        cap = None
        work_key = None
        if isinstance(operation.value, dict):
            raw_slot = operation.value.get("slot")
            raw_color_slot = operation.value.get("color_slot")
            raw_divisor = operation.value.get("divisor")
            raw_cap = operation.value.get("cap")
            raw_work_key = operation.value.get("work_key")
            if isinstance(raw_slot, str):
                slot = raw_slot
            if isinstance(raw_color_slot, str):
                color_slot = raw_color_slot
            if isinstance(raw_divisor, int) and raw_divisor > 0:
                divisor = raw_divisor
            if isinstance(raw_cap, int) and raw_cap >= 0:
                cap = raw_cap
            if isinstance(raw_work_key, str):
                work_key = raw_work_key
        if not isinstance(color_slot, str):
            return 0
        instance_id = player.member_area.get(slot)
        if instance_id is None:
            return 0
        if isinstance(work_key, str) and work_key not in state.cards[instance_id].card.work_keys:
            return 0
        amount = _member_heart_count(
            state,
            player.player_id,
            instance_id,
            color_slot,
        ) // divisor
        if cap is not None:
            amount = min(amount, cap)
        return amount * multiplier
    if (
        operation.amount_source == "stage_member_work_cost_sum_threshold_bonus"
        and player is not None
        and state is not None
    ):
        work_key = None
        thresholds: dict[int, int] = {}
        if isinstance(operation.value, dict):
            work_key = operation.value.get("work_key")
            raw_thresholds = operation.value.get("thresholds")
            if isinstance(raw_thresholds, dict):
                thresholds = {
                    int(threshold): int(amount)
                    for threshold, amount in raw_thresholds.items()
                    if isinstance(amount, int)
                    and str(threshold).lstrip("-").isdigit()
                }
        if not isinstance(work_key, str) or not thresholds:
            return 0
        actual = sum(
            state.cards[item].card.cost or 0
            for item in player.member_area.values()
            if item is not None and work_key in state.cards[item].card.work_keys
        )
        amount = 0
        for threshold, threshold_amount in sorted(thresholds.items()):
            if actual >= threshold:
                amount = threshold_amount
        return amount * multiplier
    if operation.amount_source == "own_stage_member_count" and player is not None:
        return (
            sum(1 for item in player.member_area.values() if item is not None)
            * multiplier
        )
    if (
        operation.amount_source == "own_stage_member_unit_count"
        and player is not None
        and state is not None
    ):
        unit_key = None
        exclude_source = False
        if isinstance(operation.value, dict):
            unit_key = operation.value.get("unit_key")
            exclude_source = bool(operation.value.get("exclude_source"))
        if not isinstance(unit_key, str):
            return 0
        return (
            sum(
                item is not None
                and unit_key in state.cards[item].card.unit_keys
                and (
                    not exclude_source
                    or operation_context is None
                    or item != operation_context.get("source_card_instance_id")
                )
                for item in player.member_area.values()
            )
            * multiplier
        )
    if (
        operation.amount_source == "own_stage_member_filter_count"
        and player is not None
        and state is not None
    ):
        minimum_cost = None
        unit_key = None
        exclude_unit_key = None
        if isinstance(operation.value, dict):
            raw_minimum_cost = operation.value.get("minimum_cost")
            if isinstance(raw_minimum_cost, int):
                minimum_cost = raw_minimum_cost
            unit_key = operation.value.get("unit_key")
            exclude_unit_key = operation.value.get("exclude_unit_key")
        return (
            sum(
                item is not None
                and (
                    minimum_cost is None
                    or (state.cards[item].card.cost or 0) >= minimum_cost
                )
                and (
                    not isinstance(unit_key, str)
                    or unit_key in state.cards[item].card.unit_keys
                )
                and (
                    not isinstance(exclude_unit_key, str)
                    or exclude_unit_key not in state.cards[item].card.unit_keys
                )
                for item in player.member_area.values()
            )
            * multiplier
        )
    if (
        operation.amount_source == "own_stage_member_work_distinct_name_count"
        and player is not None
        and state is not None
    ):
        work_key = None
        if isinstance(operation.value, dict):
            work_key = operation.value.get("work_key")
        names = {
            state.cards[item].card.name_ja
            for item in player.member_area.values()
            if item is not None
            and (
                not isinstance(work_key, str)
                or work_key in state.cards[item].card.work_keys
            )
        }
        return len(names) * multiplier
    if (
        operation.amount_source == "stage_member_heart_color_variety_count"
        and player is not None
        and state is not None
    ):
        work_key = None
        unit_key = None
        color_slots: set[str] = {
            "heart01",
            "heart02",
            "heart03",
            "heart04",
            "heart05",
            "heart06",
        }
        if isinstance(operation.value, dict):
            work_key = operation.value.get("work_key")
            unit_key = operation.value.get("unit_key")
            raw_slots = operation.value.get("color_slots")
            if isinstance(raw_slots, list):
                color_slots = {str(item) for item in raw_slots}
        colors: set[str] = set()
        for instance_id in player.member_area.values():
            if instance_id is None:
                continue
            card = state.cards[instance_id].card
            if isinstance(work_key, str) and work_key not in card.work_keys:
                continue
            if isinstance(unit_key, str) and unit_key not in card.unit_keys:
                continue
            colors.update(
                color
                for color in _member_heart_color_slots(
                    state,
                    player.player_id,
                    instance_id,
                )
                if color in color_slots
            )
        return len(colors) * multiplier
    if (
        operation.amount_source == "waiting_room_live_work_distinct_name_threshold_bonus"
        and player is not None
        and state is not None
    ):
        work_key = None
        thresholds: dict[int, int] = {}
        if isinstance(operation.value, dict):
            work_key = operation.value.get("work_key")
            raw_thresholds = operation.value.get("thresholds")
            if isinstance(raw_thresholds, dict):
                thresholds = {
                    int(threshold): int(amount)
                    for threshold, amount in raw_thresholds.items()
                    if isinstance(amount, int)
                    and str(threshold).lstrip("-").isdigit()
                }
        if not isinstance(work_key, str) or not thresholds:
            return 0
        actual = _waiting_room_live_work_distinct_name_count(
            state,
            player.player_id,
            work_key,
        )
        amount = 0
        for threshold, threshold_amount in sorted(thresholds.items()):
            if actual >= threshold:
                amount = threshold_amount
        return amount * multiplier
    if operation.amount_source == "total_stage_member_count" and state is not None:
        return (
            sum(
                1
                for target_player in state.players.values()
                for item in target_player.member_area.values()
                if item is not None
            )
            * multiplier
        )
    if (
        operation.amount_source == "opponent_success_live_count_difference"
        and player is not None
        and state is not None
    ):
        opponent_id = "player_2" if player.player_id == "player_1" else "player_1"
        opponent = state.players[opponent_id]
        return (
            max(0, len(opponent.success_live_area) - len(player.success_live_area))
            * multiplier
        )
    if (
        operation.amount_source == "revealed_live_count"
        and operation_context is not None
        and state is not None
    ):
        return (
            sum(
                state.cards[item].card.card_type == "live"
                for item in operation_context.get("revealed_card_instance_ids", [])
            )
            * multiplier
        )
    if (
        operation.amount_source == "source_attached_energy_count_plus"
        and operation_context is not None
        and state is not None
        and player is not None
    ):
        source_id = operation_context.get("source_card_instance_id")
        source_slot = (
            _top_member_slot(player, source_id) if isinstance(source_id, str) else None
        )
        if source_slot is None:
            return 0
        addend = 0
        if isinstance(operation.value, dict) and isinstance(operation.value.get("add"), int):
            addend = int(operation.value["add"])
        return (
            sum(
                state.cards[item].card.card_type == "energy"
                for item in player.member_area_attachments[source_slot]
            )
            + addend
        ) * multiplier
    if (
        operation.amount_source == "source_attached_member_count"
        and operation_context is not None
        and state is not None
        and player is not None
    ):
        source_id = operation_context.get("source_card_instance_id")
        source_slot = (
            _top_member_slot(player, source_id) if isinstance(source_id, str) else None
        )
        if source_slot is None:
            return 0
        amount = sum(
            state.cards[item].card.card_type == "member"
            for item in player.member_area_attachments[source_slot]
        )
        if isinstance(operation.value, dict):
            maximum = operation.value.get("max")
            if isinstance(maximum, int):
                amount = min(amount, maximum)
        return amount * multiplier
    if (
        operation.amount_source == "effect_ready_history_score_bonus"
        and state is not None
        and player is not None
        and isinstance(operation.value, dict)
    ):
        work_key = operation.value.get("work_key")
        if not isinstance(work_key, str):
            return 0
        energy_bonus = operation.value.get("energy_bonus", 1)
        member_bonus = operation.value.get("member_bonus", 2)
        if not isinstance(energy_bonus, int):
            energy_bonus = 1
        if not isinstance(member_bonus, int):
            member_bonus = 2
        flags = set(player.effect_ready_flags_this_turn)
        if _effect_ready_flag(work_key, "member") in flags:
            return member_bonus * multiplier
        if _effect_ready_flag(work_key, "energy") in flags:
            return energy_bonus * multiplier
        return 0
    if operation.amount_source == "selected_count":
        if isinstance(selected_count, int) and not isinstance(selected_count, bool):
            return selected_count
        return 0
    if isinstance(selected_count, int) and not isinstance(selected_count, bool):
        return selected_count
    return 0


def _effect_modifier_duration(duration: Any) -> str:
    if duration in {"live", "turn", "game"}:
        return duration
    return "live"


def _live_modifier_target_id(
    state: MatchState,
    invocation: EffectInvocation,
) -> str | None:
    player = state.players[invocation.player_id]
    if invocation.source_card_instance_id in player.live_area:
        return invocation.source_card_instance_id
    if len(player.live_area) == 1:
        return player.live_area[0]
    return None


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
                    "trigger": effect.trigger,
                    "timing": effect.timing,
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
    elif state.phase == "live_judgment" and state.live_success_effects_queued:
        _complete_live_judgment(state, events)
        return
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
    return _effect_usage_count_this_turn(state, effect_id, source_instance_id) > 0


def _effect_usage_limit_reached(
    state: MatchState,
    effect: Any,
    source_instance_id: str,
) -> bool:
    if effect.frequency_limit not in {
        "once_per_turn",
        "once_per_live",
        "twice_per_turn",
    }:
        return False
    limit = 2 if effect.frequency_limit == "twice_per_turn" else 1
    return (
        _effect_usage_count_this_turn(state, effect.effect_id, source_instance_id)
        >= limit
    )


def _effect_usage_count_this_turn(
    state: MatchState,
    effect_id: str,
    source_instance_id: str,
) -> int:
    return sum(
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
        member_hearts.update(_member_base_hearts(state, player_id, instance_id))
        member_hearts.update(_static_heart_bonus(state, player_id, instance_id))
        if member.orientation == "active":
            blade_count += _member_base_blade(state, player_id, instance_id)
            blade_count += _target_modifier_total(player, "blade", instance_id)
            blade_count += _static_numeric_bonus(
                state, player_id, instance_id, "gain_blade"
            )

    raw_blade_count = blade_count
    yell_count_modifier = _yell_count_modifier_total(player)
    blade_count = max(0, blade_count + yell_count_modifier)

    revealed: list[str] = []
    yell_hearts: Counter[str] = Counter()
    all_color_hearts = 0
    draw_count = 0
    score_bonus = 0
    special_results: list[dict[str, Any]] = []
    yell_replacement = _yell_blade_heart_replacement(player)
    for _ in range(max(0, blade_count)):
        instance_id = _take_main_deck_card(state, player_id, events)
        if instance_id is None:
            break
        player.resolution_area.append(instance_id)
        state.cards[instance_id].face_up = True
        revealed.append(instance_id)
        definition = state.cards[instance_id].card
        if definition.blade_heart_color_slot:
            color_slot = (
                yell_replacement["color_slot"]
                if yell_replacement is not None
                else definition.blade_heart_color_slot
            )
            yell_hearts[color_slot] += 1
        for special in definition.special_blade_hearts:
            value = special.value or 0
            result = {
                "card_instance_id": instance_id,
                "effect_type": special.effect_type,
                "value": value,
                "source_alt": special.source_alt,
            }
            if special.effect_type == "all_color":
                if (
                    yell_replacement is not None
                    and yell_replacement.get("include_all_color", True)
                ):
                    converted_color = str(yell_replacement["color_slot"])
                    yell_hearts[converted_color] += value
                    result["converted_to_color_slot"] = converted_color
                else:
                    all_color_hearts += value
            elif special.effect_type == "draw":
                draw_count += value
            elif special.effect_type == "score":
                score_bonus += value
            special_results.append(result)
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
                "raw_blade_count": raw_blade_count,
                "yell_count_modifier": yell_count_modifier,
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
        requirements = _effective_required_hearts(player, live_id, state.cards[live_id].card.required_hearts)
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
            _card_score(state, player_id, instance_id)
            for instance_id in player.live_area
        )
        player.live_result.score_bonus += _modifier_total(player, "score")
        player.live_result.score_bonus += _static_score_bonus(state, player_id)
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
    state.success_live_moved_instance_ids = {}
    state.live_success_effects_queued = False
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
        first_at_match_point = len(first.success_live_area) >= 2
        second_at_match_point = len(second.success_live_area) >= 2
        if first_at_match_point and not second_at_match_point:
            winners = [second_id]
        elif second_at_match_point and not first_at_match_point:
            winners = [first_id]
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
        state.players[player_id].member_areas_moved_this_turn = []
        state.players[player_id].member_entered_count_this_turn = 0
        state.players[player_id].member_areas_baton_entered_this_turn = []
        state.players[player_id].member_instance_ids_baton_entered_this_turn = []
        state.players[player_id].effect_ready_flags_this_turn = []
        state.players[player_id].refreshed_this_turn = False
    state.turn_number += 1
    state.first_player_id = next_first
    state.second_player_id = next_second
    state.next_first_player_id = None
    state.success_live_moved_player_ids = []
    state.success_live_moved_instance_ids = {}
    state.live_success_effects_queued = False
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
            _record_success_live_move(state, player_id, selected)
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
    _queue_live_success_effects(state, events)
    _resolve_automatic_effects(state, events)
    if state.pending_effects:
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
    elif adjustment_type == "return_from_waiting_room":
        instance_id = adjustment.get("target_card_instance_id")
        if instance_id not in player.waiting_room:
            raise IllegalActionError(
                "manual return target must be in waiting room"
            )
        player.waiting_room.remove(instance_id)
        player.hand.append(instance_id)
    elif adjustment_type == "move_card":
        instance_id = adjustment.get("target_card_instance_id")
        to_zone = adjustment.get("to_zone")
        _manual_move_card(state, player_id, instance_id, to_zone, events)
    elif adjustment_type == "attach_card_under_member":
        _attach_card_under_member(state, player_id, adjustment, events)
    elif adjustment_type == "move_attached_card":
        _move_attached_card(state, player_id, adjustment, events)
    elif adjustment_type == "move_member":
        _move_member(state, player_id, adjustment, events)
    elif adjustment_type == "position_change":
        _position_change(state, player_id, adjustment, events)
    elif adjustment_type == "formation_change":
        _formation_change(state, player_id, adjustment, events)
    elif adjustment_type in {"ready_energy", "pay_energy"}:
        target_ids = _manual_energy_target_ids(adjustment)
        if not target_ids:
            raise IllegalActionError(
                "manual Energy adjustment requires at least one target"
            )
        for instance_id in target_ids:
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


def _manual_energy_target_ids(adjustment: dict[str, Any]) -> list[str]:
    target_ids = adjustment.get("target_card_instance_ids")
    if target_ids is not None:
        if (
            not isinstance(target_ids, list)
            or not target_ids
            or any(not isinstance(item, str) for item in target_ids)
            or len(target_ids) != len(set(target_ids))
        ):
            raise IllegalActionError(
                "manual Energy targets must be a non-empty unique ID list"
            )
        return list(target_ids)
    instance_id = adjustment.get("target_card_instance_id")
    if not isinstance(instance_id, str) or not instance_id:
        return []
    return [instance_id]


def _manual_move_card(
    state: MatchState,
    player_id: str,
    instance_id: Any,
    to_zone: Any,
    events: list[GameEvent],
) -> None:
    if not isinstance(instance_id, str) or instance_id not in state.cards:
        raise IllegalActionError("manual move target card does not exist")
    if state.cards[instance_id].owner_id != player_id:
        raise IllegalActionError("manual move target must belong to target player")
    player = state.players[player_id]
    attached_slot = _attached_slot(player, instance_id)
    if attached_slot is not None:
        raise IllegalActionError(
            "attached cards must be moved with move_attached_card"
        )
    stage_slot = _top_member_slot(player, instance_id)
    was_on_stage = stage_slot is not None
    if stage_slot is not None and to_zone not in {
        "member_left",
        "member_center",
        "member_right",
    }:
        _clean_stage_attachments(
            state,
            player_id,
            stage_slot,
            events,
            reason="manual_move_off_stage",
        )
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
        if was_on_stage and to_zone == "waiting_room" and stage_slot is not None:
            _queue_triggered_effects(
                state,
                "member_left_stage_to_waiting_room",
                events,
                source_instance_ids=[instance_id],
                trigger_data={
                    "turn_number": state.turn_number,
                    "from_slot": stage_slot,
                    "to_zone": to_zone,
                },
            )
        return
    if to_zone in {"member_left", "member_center", "member_right"}:
        slot = str(to_zone).removeprefix("member_")
        if state.cards[instance_id].card.card_type != "member":
            raise IllegalActionError("only Member cards may enter a Member Area")
        if was_on_stage and stage_slot == slot:
            raise IllegalActionError("Member is already in the target area")
        if player.member_area[slot] is not None:
            raise IllegalActionError("manual move Member Area slot is occupied")
        player.member_area[slot] = instance_id
        if was_on_stage and stage_slot is not None:
            player.member_area_attachments[slot] = list(
                player.member_area_attachments[stage_slot]
            )
            player.member_area_attachments[stage_slot] = []
            events.append(
                GameEvent(
                    event_type="stage_member_group_moved",
                    player_id=player_id,
                    data={
                        "card_instance_id": instance_id,
                        "from_slot": stage_slot,
                        "to_slot": slot,
                        "attached_card_instance_ids": list(
                            player.member_area_attachments[slot]
                        ),
                    },
                    source="manual",
                )
            )
            _record_member_area_moved(player, slot)
            _queue_member_moved_effects(
                state,
                player_id,
                [instance_id],
                events,
                from_slot=stage_slot,
                to_slot=slot,
            )
        if not was_on_stage:
            player.member_entered_count_this_turn += 1
            if slot not in player.member_areas_entered_this_turn:
                player.member_areas_entered_this_turn.append(slot)
        return
    raise IllegalActionError("manual move target zone is invalid")


def _attach_card_under_member(
    state: MatchState,
    player_id: str,
    adjustment: dict[str, Any],
    events: list[GameEvent],
) -> None:
    player = state.players[player_id]
    instance_id = adjustment.get("target_card_instance_id")
    slot = adjustment.get("target_slot")
    if not isinstance(instance_id, str) or instance_id not in state.cards:
        raise IllegalActionError("attachment target card does not exist")
    if state.cards[instance_id].owner_id != player_id:
        raise IllegalActionError("attachment target must belong to target player")
    if slot not in player.member_area or player.member_area[slot] is None:
        raise IllegalActionError("attachment target slot requires a top Member")
    card_type = state.cards[instance_id].card.card_type
    if card_type == "member":
        if instance_id not in player.hand:
            raise IllegalActionError("attached Member must come from hand")
        player.hand.remove(instance_id)
        if slot not in player.member_areas_entered_this_turn:
            player.member_areas_entered_this_turn.append(slot)
    elif card_type == "energy":
        if instance_id not in player.energy_area:
            raise IllegalActionError("attached Energy must come from Energy Area")
        player.energy_area.remove(instance_id)
    else:
        raise IllegalActionError("only Member or Energy cards may be attached")
    player.member_area_attachments[slot].append(instance_id)
    state.cards[instance_id].face_up = True
    events.append(
        GameEvent(
            event_type="card_attached_under_member",
            player_id=player_id,
            data={
                "card_instance_id": instance_id,
                "card_type": card_type,
                "slot": slot,
                "top_member_instance_id": player.member_area[slot],
            },
            source="manual",
        )
    )


def _move_attached_card(
    state: MatchState,
    player_id: str,
    adjustment: dict[str, Any],
    events: list[GameEvent],
) -> None:
    player = state.players[player_id]
    instance_id = adjustment.get("target_card_instance_id")
    to_zone = adjustment.get("to_zone")
    if not isinstance(instance_id, str) or instance_id not in state.cards:
        raise IllegalActionError("attached card target does not exist")
    slot = _attached_slot(player, instance_id)
    if slot is None:
        raise IllegalActionError("target card is not attached under a Member")
    card = state.cards[instance_id]
    if card.owner_id != player_id:
        raise IllegalActionError("attached card must belong to target player")
    if card.card.card_type == "member":
        allowed = {
            "hand": player.hand,
            "waiting_room": player.waiting_room,
        }
        if to_zone in allowed:
            player.member_area_attachments[slot].remove(instance_id)
            allowed[to_zone].append(instance_id)
        elif to_zone in {"member_left", "member_center", "member_right"}:
            target_slot = str(to_zone).removeprefix("member_")
            if player.member_area[target_slot] is not None:
                raise IllegalActionError(
                    "attached Member may only enter an empty Member Area"
                )
            player.member_area_attachments[slot].remove(instance_id)
            player.member_area[target_slot] = instance_id
        else:
            raise IllegalActionError("attached Member destination is invalid")
    elif card.card.card_type == "energy":
        if to_zone == "energy_deck":
            player.member_area_attachments[slot].remove(instance_id)
            player.energy_deck.append(instance_id)
            card.face_up = False
        elif to_zone == "energy_area":
            orientation = adjustment.get("orientation")
            if orientation not in {"active", "wait"}:
                raise IllegalActionError(
                    "moving attached Energy to Energy Area requires orientation"
                )
            player.member_area_attachments[slot].remove(instance_id)
            player.energy_area.append(instance_id)
            card.face_up = True
            card.orientation = orientation
        else:
            raise IllegalActionError("attached Energy destination is invalid")
    else:
        raise IllegalActionError("only attached Member or Energy cards may move")
    events.append(
        GameEvent(
            event_type="attached_card_moved",
            player_id=player_id,
            data={
                "card_instance_id": instance_id,
                "card_type": card.card.card_type,
                "from_slot": slot,
                "to_zone": to_zone,
                "orientation": (
                    card.orientation if to_zone == "energy_area" else None
                ),
            },
            source="manual",
        )
    )


def _move_member(
    state: MatchState,
    player_id: str,
    adjustment: dict[str, Any],
    events: list[GameEvent],
) -> None:
    player = state.players[player_id]
    instance_id = adjustment.get("target_card_instance_id")
    to_slot = adjustment.get("to_slot")
    if not isinstance(instance_id, str):
        raise IllegalActionError("move_member requires a Member card instance")
    from_slot = _top_member_slot(player, instance_id)
    if from_slot is None:
        raise IllegalActionError(
            "move_member target must be a top Member currently on Stage"
        )
    _position_change(
        state,
        player_id,
        {"from_slot": from_slot, "to_slot": to_slot},
        events,
    )


def _position_change(
    state: MatchState,
    player_id: str,
    adjustment: dict[str, Any],
    events: list[GameEvent],
) -> None:
    player = state.players[player_id]
    from_slot = adjustment.get("from_slot")
    to_slot = adjustment.get("to_slot")
    if (
        from_slot not in player.member_area
        or to_slot not in player.member_area
        or from_slot == to_slot
    ):
        raise IllegalActionError("position_change requires two different slots")
    moving_id = player.member_area[from_slot]
    if moving_id is None:
        raise IllegalActionError("position_change source slot is empty")
    target_id = player.member_area[to_slot]
    moving_attachments = list(player.member_area_attachments[from_slot])
    target_attachments = list(player.member_area_attachments[to_slot])
    player.member_area[from_slot], player.member_area[to_slot] = (
        target_id,
        moving_id,
    )
    (
        player.member_area_attachments[from_slot],
        player.member_area_attachments[to_slot],
    ) = (
        target_attachments,
        moving_attachments,
    )
    event_type = (
        "stage_member_group_moved"
        if target_id is None
        else "stage_member_groups_swapped"
    )
    events.append(
        GameEvent(
            event_type=event_type,
            player_id=player_id,
            data={
                "from_slot": from_slot,
                "to_slot": to_slot,
                "moving_member_instance_id": moving_id,
                "target_member_instance_id": target_id,
                "moving_attached_card_instance_ids": moving_attachments,
                "target_attached_card_instance_ids": target_attachments,
            },
            source="manual",
        )
    )
    moved_entries = [(moving_id, str(from_slot), str(to_slot))]
    if target_id is not None:
        moved_entries.append((target_id, str(to_slot), str(from_slot)))
    for member_id, source_slot, destination_slot in moved_entries:
        _record_member_area_moved(player, destination_slot)
        _queue_member_moved_effects(
            state,
            player_id,
            [member_id],
            events,
            from_slot=source_slot,
            to_slot=destination_slot,
        )


def _formation_change(
    state: MatchState,
    player_id: str,
    adjustment: dict[str, Any],
    events: list[GameEvent],
    *,
    source: str = "manual",
) -> None:
    player = state.players[player_id]
    assignments = adjustment.get("slot_assignments")
    slots = ("left", "center", "right")
    if not isinstance(assignments, dict) or set(assignments) != set(slots):
        raise IllegalActionError(
            "formation_change requires left, center, and right assignments"
        )
    current_ids = [item for item in player.member_area.values() if item is not None]
    assigned_ids = [assignments[slot] for slot in slots if assignments[slot] is not None]
    if (
        any(not isinstance(item, str) for item in assigned_ids)
        or len(assigned_ids) != len(set(assigned_ids))
        or set(assigned_ids) != set(current_ids)
    ):
        raise IllegalActionError(
            "formation_change must assign every current top Member exactly once"
        )
    attachment_by_member = {
        member_id: list(player.member_area_attachments[slot])
        for slot, member_id in player.member_area.items()
        if member_id is not None
    }
    before_slot_by_member = {
        member_id: slot
        for slot, member_id in player.member_area.items()
        if member_id is not None
    }
    before = dict(player.member_area)
    before_attachments = {
        slot: list(player.member_area_attachments[slot]) for slot in slots
    }
    player.member_area = {slot: assignments[slot] for slot in slots}
    player.member_area_attachments = {
        slot: (
            attachment_by_member.get(assignments[slot], [])
            if assignments[slot] is not None
            else []
        )
        for slot in slots
    }
    events.append(
        GameEvent(
            event_type="stage_formation_changed",
            player_id=player_id,
            data={
                "before": before,
                "after": dict(player.member_area),
                "before_attachments": before_attachments,
                "after_attachments": {
                    slot: list(player.member_area_attachments[slot])
                    for slot in slots
                },
            },
            source=source,
        )
    )
    for to_slot, member_id in player.member_area.items():
        if member_id is None:
            continue
        from_slot = before_slot_by_member[member_id]
        if from_slot == to_slot:
            continue
        _record_member_area_moved(player, to_slot)
        _queue_member_moved_effects(
            state,
            player_id,
            [member_id],
            events,
            from_slot=from_slot,
            to_slot=to_slot,
        )


def _rotate_stage_member_groups(
    state: MatchState,
    player_id: str,
    events: list[GameEvent],
) -> None:
    before = dict(state.players[player_id].member_area)
    _formation_change(
        state,
        player_id,
        {
            "slot_assignments": {
                "left": before["center"],
                "center": before["right"],
                "right": before["left"],
            }
        },
        events,
        source="system",
    )


def _move_top_member_off_stage(
    state: MatchState,
    player_id: str,
    slot: str,
    to_zone: str,
    events: list[GameEvent],
    *,
    reason: str,
) -> str:
    player = state.players[player_id]
    instance_id = player.member_area[slot]
    if instance_id is None:
        raise IllegalActionError("Member Area slot is empty")
    _clean_stage_attachments(state, player_id, slot, events, reason=reason)
    player.member_area[slot] = None
    if to_zone != "waiting_room":
        raise IllegalActionError("unsupported top Member destination")
    player.waiting_room.append(instance_id)
    _queue_triggered_effects(
        state,
        "member_left_stage_to_waiting_room",
        events,
        source_instance_ids=[instance_id],
        trigger_data={
            "turn_number": state.turn_number,
            "from_slot": slot,
            "to_zone": to_zone,
        },
    )
    return instance_id


def _clean_stage_attachments(
    state: MatchState,
    player_id: str,
    slot: str,
    events: list[GameEvent],
    *,
    reason: str,
) -> None:
    player = state.players[player_id]
    attached = list(player.member_area_attachments[slot])
    if not attached:
        return
    member_ids: list[str] = []
    energy_ids: list[str] = []
    for instance_id in attached:
        card = state.cards[instance_id]
        if card.card.card_type == "member":
            player.waiting_room.append(instance_id)
            member_ids.append(instance_id)
        elif card.card.card_type == "energy":
            player.energy_deck.append(instance_id)
            card.face_up = False
            energy_ids.append(instance_id)
        else:
            raise IllegalActionError("invalid attached card type")
    player.member_area_attachments[slot] = []
    events.append(
        GameEvent(
            event_type="stage_attachments_cleaned",
            player_id=player_id,
            data={
                "slot": slot,
                "reason": reason,
                "member_to_waiting_room_instance_ids": member_ids,
                "energy_to_energy_deck_instance_ids": energy_ids,
            },
            source="system",
        )
    )


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


def _top_member_slot(player: Any, instance_id: str) -> str | None:
    return next(
        (slot for slot, current in player.member_area.items() if current == instance_id),
        None,
    )


def _live_area_has_card_without_effect_timings(
    state: MatchState,
    player_id: str,
    excluded_timings: set[str],
) -> bool:
    player = state.players[player_id]
    for instance_id in player.live_area:
        if state.cards[instance_id].card.card_type != "live":
            continue
        has_excluded_timing = False
        for effect_id in state.cards[instance_id].card.effect_ids:
            effect = state.effect_definitions.get(effect_id)
            if effect is not None and effect.timing in excluded_timings:
                has_excluded_timing = True
                break
        if not has_excluded_timing:
            return True
    return False


def _attached_slot(player: Any, instance_id: str) -> str | None:
    return next(
        (
            slot
            for slot, attached in player.member_area_attachments.items()
            if instance_id in attached
        ),
        None,
    )


def _validate_stage_state(state: MatchState) -> None:
    expected_slots = {"left", "center", "right"}
    for player in state.players.values():
        if set(player.member_area) != expected_slots:
            raise IllegalActionError("Member Area slots are invalid")
        if set(player.member_area_attachments) != expected_slots:
            raise IllegalActionError("Member Area attachment slots are invalid")
        seen: set[str] = set()
        for slot in ("left", "center", "right"):
            top_id = player.member_area[slot]
            attachments = player.member_area_attachments[slot]
            if top_id is None and attachments:
                raise IllegalActionError(
                    "Member Area attachments require a top Member"
                )
            if top_id is not None:
                if top_id in seen:
                    raise IllegalActionError("a card cannot occupy multiple Stage slots")
                if state.cards[top_id].card.card_type != "member":
                    raise IllegalActionError("top Stage cards must be Members")
                seen.add(top_id)
            if len(attachments) != len(set(attachments)):
                raise IllegalActionError("attached cards must be unique")
            for instance_id in attachments:
                if instance_id in seen:
                    raise IllegalActionError(
                        "a card cannot occupy multiple Stage positions"
                    )
                if state.cards[instance_id].owner_id != player.player_id:
                    raise IllegalActionError(
                        "attached cards must belong to the Stage owner"
                    )
                if state.cards[instance_id].card.card_type not in {
                    "member",
                    "energy",
                }:
                    raise IllegalActionError(
                        "only Member or Energy cards may be attached"
                    )
                seen.add(instance_id)
        other_zones = (
            player.main_deck,
            player.energy_deck,
            player.hand,
            player.energy_area,
            player.live_area,
            player.waiting_room,
            player.resolution_area,
            player.success_live_area,
        )
        for zone in other_zones:
            if seen.intersection(zone):
                raise IllegalActionError(
                    "Stage cards cannot also exist in another zone"
                )


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
    player.refreshed_this_turn = True
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
    orientation: str = "active",
) -> None:
    if orientation not in {"active", "wait"}:
        raise IllegalActionError(f"unsupported Energy orientation: {orientation}")
    player = state.players[player_id]
    moved: list[str] = []
    for _ in range(amount):
        if not player.energy_deck:
            break
        instance_id = player.energy_deck.pop(0)
        player.energy_area.append(instance_id)
        state.cards[instance_id].face_up = True
        state.cards[instance_id].orientation = orientation
        moved.append(instance_id)
    events.append(
        GameEvent(
            event_type="energy_added",
            player_id=player_id,
            data={
                "instance_ids": moved,
                "reason": reason,
                "source_zone": "energy_deck",
                "orientation": orientation,
            },
        )
    )
    if moved and reason.startswith("effect:"):
        source_ids = [
            source_id for source_id in player.member_area.values() if source_id is not None
        ]
        _queue_triggered_effects(
            state,
            "energy_placed_by_effect",
            events,
            source_instance_ids=source_ids,
            trigger_data={
                "turn_number": state.turn_number,
                "energy_instance_ids": list(moved),
                "reason": reason,
                "orientation": orientation,
            },
        )


def _static_test_validated_effects(
    state: MatchState,
    player_id: str,
    source_instance_id: str,
) -> list[Any]:
    definitions = state.cards[source_instance_id].card
    effects: list[Any] = []
    for effect_id in definitions.effect_ids:
        effect = state.effect_definitions.get(effect_id)
        if (
            effect is None
            or effect.timing != "static_always"
            or effect.simulation_support != "test_validated_executable"
        ):
            continue
        invocation = EffectInvocation(
            invocation_id=f"static:{source_instance_id}:{effect.effect_id}",
            effect_id=effect.effect_id,
            source_card_instance_id=source_instance_id,
            player_id=player_id,
            trigger_event="static_always",
        )
        if _effect_condition_met(state, invocation):
            effects.append(effect)
    return effects


def _effective_member_play_cost(
    state: MatchState,
    player_id: str,
    instance_id: str,
) -> int:
    card = state.cards[instance_id].card
    cost = card.cost or 0
    reduction = 0
    player = state.players[player_id]
    for effect in _static_test_validated_effects(state, player_id, instance_id):
        for operation in effect.actions:
            if operation.action_type == "reduce_play_cost":
                reduction += _operation_amount(operation, player=player, state=state)
    return max(0, cost - reduction)


def _baton_replacement_static_restrictions_allow(
    state: MatchState,
    player_id: str,
    replaced_instance_id: str,
    new_instance_id: str,
) -> bool:
    new_card = state.cards[new_instance_id].card
    for effect in _static_test_validated_effects(
        state,
        player_id,
        replaced_instance_id,
    ):
        for operation in effect.actions:
            if operation.action_type != "restrict_baton_replacement_unit":
                continue
            unit_key = None
            if isinstance(operation.value, dict):
                unit_key = operation.value.get("unit_key")
            if isinstance(unit_key, str) and unit_key not in new_card.unit_keys:
                return False
    return True


def _validate_baton_replacement_static_restrictions(
    state: MatchState,
    player_id: str,
    replaced_instance_id: str,
    new_instance_id: str,
) -> None:
    if not _baton_replacement_static_restrictions_allow(
        state,
        player_id,
        replaced_instance_id,
        new_instance_id,
    ):
        raise IllegalActionError(
            "the replaced Member cannot Baton Touch with the selected Member"
        )


def _ready_player_cards(
    state: MatchState,
    player_id: str,
    events: list[GameEvent],
) -> None:
    player = state.players[player_id]
    skip_ready_ids = {
        modifier.target_card_instance_id
        for modifier in player.manual_modifiers
        if modifier.modifier_type == "flag"
        and modifier.flag == "skip_next_active_phase_ready"
        and modifier.target_card_instance_id
    }
    ready_ids = [
        *player.energy_area,
        *[instance_id for instance_id in player.member_area.values() if instance_id],
    ]
    readied_ids: list[str] = []
    skipped_ids: list[str] = []
    for instance_id in ready_ids:
        if instance_id in skip_ready_ids:
            skipped_ids.append(instance_id)
            continue
        state.cards[instance_id].orientation = "active"
        readied_ids.append(instance_id)
    if skip_ready_ids:
        player.manual_modifiers = [
            modifier
            for modifier in player.manual_modifiers
            if not (
                modifier.modifier_type == "flag"
                and modifier.flag == "skip_next_active_phase_ready"
            )
        ]
    events.append(
        GameEvent(
            event_type="cards_readied",
            player_id=player_id,
            data={"instance_ids": readied_ids, "skipped_instance_ids": skipped_ids},
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
        new_cost = _effective_member_play_cost(state, player_id, instance_id)
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
                        "new_member_cost": new_cost,
                        "printed_member_cost": definition.cost or 0,
                        "use_baton_touch": False,
                        "replaced_card_instance_id": current_instance_id,
                        "replaced_member_cost": replaced_cost,
                    }
                )
            if current_instance_id is None or new_cost <= 0:
                continue
            if (
                slot in player.member_areas_baton_entered_this_turn
                or current_instance_id
                in player.member_instance_ids_baton_entered_this_turn
            ):
                continue
            if not _baton_replacement_static_restrictions_allow(
                state,
                player_id,
                current_instance_id,
                instance_id,
            ):
                continue
            replaced_cost = state.cards[current_instance_id].card.cost or 0
            payment_cost = max(0, new_cost - replaced_cost)
            if payment_cost <= active_energy_count:
                placements.append(
                    {
                        "card_instance_id": instance_id,
                        "slot": slot,
                        "payment_cost": payment_cost,
                        "new_member_cost": new_cost,
                        "printed_member_cost": definition.cost or 0,
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


def _static_heart_bonus(
    state: MatchState,
    player_id: str,
    source_instance_id: str,
) -> Counter[str]:
    hearts: Counter[str] = Counter()
    for effect in _active_static_effects(state, player_id, source_instance_id):
        for operation in effect.actions:
            if operation.action_type != "gain_heart":
                continue
            color_slot = operation.color_slot
            if color_slot:
                hearts[color_slot] += _operation_amount(
                    operation,
                    player=state.players[player_id],
                    state=state,
                    operation_context={"source_card_instance_id": source_instance_id},
                )
    return hearts


def _static_numeric_bonus(
    state: MatchState,
    player_id: str,
    source_instance_id: str,
    action_type: str,
) -> int:
    total = 0
    for effect in _active_static_effects(state, player_id, source_instance_id):
        for operation in effect.actions:
            if operation.action_type == action_type:
                total += _operation_amount(
                    operation,
                    player=state.players[player_id],
                    state=state,
                    operation_context={"source_card_instance_id": source_instance_id},
                )
    return total


def _static_score_bonus(state: MatchState, player_id: str) -> int:
    total = 0
    for source_instance_id in state.players[player_id].member_area.values():
        if source_instance_id is None:
            continue
        total += _static_numeric_bonus(
            state, player_id, source_instance_id, "modify_score"
        )
    return total


def _active_static_effects(
    state: MatchState,
    player_id: str,
    source_instance_id: str,
) -> list[Any]:
    definitions = state.cards[source_instance_id].card
    effects = []
    for effect_id in definitions.effect_ids:
        effect = state.effect_definitions.get(effect_id)
        if (
            effect is None
            or effect.timing != "static_always"
            or effect.simulation_support != "test_validated_executable"
        ):
            continue
        invocation = EffectInvocation(
            invocation_id=f"static:{source_instance_id}:{effect.effect_id}",
            effect_id=effect.effect_id,
            source_card_instance_id=source_instance_id,
            player_id=player_id,
            trigger_event="static_always",
        )
        if _effect_condition_met(state, invocation):
            effects.append(effect)
    return effects


def _modifier_total(player: Any, modifier_type: str) -> int:
    return sum(
        modifier.amount or 0
        for modifier in player.manual_modifiers
        if modifier.modifier_type == modifier_type
        and modifier.target_card_instance_id is None
    )


def _card_score(state: MatchState, player_id: str, instance_id: str) -> int:
    for modifier in reversed(state.players[player_id].manual_modifiers):
        if (
            modifier.modifier_type == "score_replacement"
            and modifier.target_card_instance_id == instance_id
            and modifier.amount is not None
        ):
            return modifier.amount
    return state.cards[instance_id].card.score or 0


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


def _yell_blade_heart_replacement(player: Any) -> dict[str, Any] | None:
    for modifier in reversed(player.manual_modifiers):
        if (
            modifier.modifier_type == "yell_blade_heart_replacement"
            and modifier.color_slot
        ):
            value = dict(modifier.value or {})
            value["color_slot"] = modifier.color_slot
            value.setdefault("include_all_color", True)
            return value
    return None


def _yell_count_modifier_total(player: Any) -> int:
    return sum(
        modifier.amount or 0
        for modifier in player.manual_modifiers
        if modifier.modifier_type == "yell_count_modifier"
    )


def _own_excess_heart_count(player: Any) -> int:
    allocation = (
        player.live_result.live_allocations[-1]
        if player.live_result.live_allocations
        else {}
    )
    remaining_hearts = allocation.get("remaining_hearts", {})
    regular_excess = (
        sum(amount for amount in remaining_hearts.values() if isinstance(amount, int))
        if isinstance(remaining_hearts, dict)
        else 0
    )
    all_color_excess = allocation.get("remaining_all_color_hearts", 0)
    if not isinstance(all_color_excess, int):
        all_color_excess = 0
    return regular_excess + all_color_excess


def _own_excess_heart_color_count(player: Any, color_slot: str) -> int:
    allocation = (
        player.live_result.live_allocations[-1]
        if player.live_result.live_allocations
        else {}
    )
    remaining_hearts = allocation.get("remaining_hearts", {})
    if not isinstance(remaining_hearts, dict):
        return 0
    count = remaining_hearts.get(color_slot, 0)
    return count if isinstance(count, int) else 0


def _yell_revealed_without_blade_heart_count(
    state: MatchState,
    player: Any,
) -> int:
    return sum(
        not _card_has_blade_heart(state.cards[item].card)
        for item in player.live_result.revealed_instance_ids
    )


def _card_has_blade_heart(card: Any) -> bool:
    return bool(card.blade_heart_color_slot or card.special_blade_hearts)


def _stage_heart_total(
    state: MatchState,
    player_id: str,
    color_slot: str,
    *,
    work_key: Any = None,
    unit_key: Any = None,
) -> int:
    total = 0
    player = state.players[player_id]
    for instance_id in player.member_area.values():
        if instance_id is None:
            continue
        card = state.cards[instance_id].card
        if isinstance(work_key, str) and work_key not in card.work_keys:
            continue
        if isinstance(unit_key, str) and unit_key not in card.unit_keys:
            continue
        total += _member_heart_count(state, player_id, instance_id, color_slot)
    return total


def _waiting_room_live_work_distinct_name_count(
    state: MatchState,
    player_id: str,
    work_key: str,
) -> int:
    return len(
        {
            state.cards[item].card.name_ja
            for item in state.players[player_id].waiting_room
            if state.cards[item].card.card_type == "live"
            and work_key in state.cards[item].card.work_keys
        }
    )


def _waiting_room_live_distinct_group_count(
    state: MatchState,
    player_id: str,
) -> int:
    groups: set[str] = set()
    for item in state.players[player_id].waiting_room:
        card = state.cards[item].card
        if card.card_type != "live":
            continue
        source_groups = card.unit_keys or card.work_keys
        groups.update(source_groups)
    return len(groups)


def _member_heart_count(
    state: MatchState,
    player_id: str,
    instance_id: str,
    color_slot: str,
    *,
    work_key: Any = None,
    unit_key: Any = None,
) -> int:
    player = state.players[player_id]
    card = state.cards[instance_id].card
    if isinstance(work_key, str) and work_key not in card.work_keys:
        return 0
    if isinstance(unit_key, str) and unit_key not in card.unit_keys:
        return 0
    total = _member_base_hearts(state, player_id, instance_id).get(color_slot, 0)
    total += sum(
        modifier.amount or 0
        for modifier in player.manual_modifiers
        if modifier.modifier_type == "heart"
        and modifier.target_card_instance_id == instance_id
        and modifier.color_slot == color_slot
    )
    for effect in _active_static_effects(state, player_id, instance_id):
        for operation in effect.actions:
            if operation.action_type == "gain_heart" and operation.color_slot == color_slot:
                total += _operation_amount(operation, player=player)
    return total


def _member_heart_color_slots(
    state: MatchState,
    player_id: str,
    instance_id: str,
) -> set[str]:
    colors = {
        color
        for color, amount in _member_base_hearts(
            state, player_id, instance_id
        ).items()
        if amount > 0
    }
    colors.update(
        modifier.color_slot
        for modifier in state.players[player_id].manual_modifiers
        if modifier.modifier_type == "heart"
        and modifier.target_card_instance_id == instance_id
        and modifier.color_slot
        and (modifier.amount or 0) > 0
    )
    for effect in _active_static_effects(state, player_id, instance_id):
        for operation in effect.actions:
            if (
                operation.action_type == "gain_heart"
                and operation.color_slot
                and _operation_amount(
                    operation,
                    player=state.players[player_id],
                    state=state,
                )
                > 0
            ):
                colors.add(operation.color_slot)
    return colors


def _member_nonstatic_heart_total(
    state: MatchState,
    player_id: str,
    instance_id: str,
) -> int:
    player = state.players[player_id]
    total = sum(
        amount
        for amount in _member_base_hearts(state, player_id, instance_id).values()
        if amount > 0
    )
    total += sum(
        modifier.amount or 0
        for modifier in player.manual_modifiers
        if modifier.modifier_type == "heart"
        and modifier.target_card_instance_id == instance_id
    )
    return max(0, total)


def _member_base_hearts(
    state: MatchState,
    player_id: str,
    instance_id: str,
) -> Counter[str]:
    card = state.cards[instance_id].card
    replacement = next(
        (
            modifier
            for modifier in reversed(state.players[player_id].manual_modifiers)
            if modifier.modifier_type == "base_heart_replacement"
            and modifier.target_card_instance_id == instance_id
            and modifier.color_slot
        ),
        None,
    )
    if replacement is None:
        return Counter(card.basic_hearts)
    total = sum(amount for amount in card.basic_hearts.values() if amount > 0)
    return Counter({replacement.color_slot: total}) if total > 0 else Counter()


def _member_base_blade(
    state: MatchState,
    player_id: str,
    instance_id: str,
) -> int:
    card = state.cards[instance_id].card
    replacement = next(
        (
            modifier
            for modifier in reversed(state.players[player_id].manual_modifiers)
            if modifier.modifier_type == "base_blade_replacement"
            and modifier.target_card_instance_id == instance_id
            and modifier.amount is not None
        ),
        None,
    )
    if replacement is None:
        return card.blade or 0
    return max(0, replacement.amount or 0)


def _stage_total_heart_count(
    state: MatchState,
    player_id: str,
    *,
    work_key: Any = None,
    unit_key: Any = None,
) -> int:
    total = 0
    for instance_id in state.players[player_id].member_area.values():
        if instance_id is None:
            continue
        card = state.cards[instance_id].card
        if isinstance(work_key, str) and work_key not in card.work_keys:
            continue
        if isinstance(unit_key, str) and unit_key not in card.unit_keys:
            continue
        colors = set(_member_base_hearts(state, player_id, instance_id))
        colors.update(
            modifier.color_slot
            for modifier in state.players[player_id].manual_modifiers
            if modifier.modifier_type == "heart"
            and modifier.target_card_instance_id == instance_id
            and modifier.color_slot
        )
        for effect in _active_static_effects(state, player_id, instance_id):
            for operation in effect.actions:
                if operation.action_type == "gain_heart" and operation.color_slot:
                    colors.add(operation.color_slot)
        total += sum(
            _member_heart_count(state, player_id, instance_id, color)
            for color in colors
        )
    return total


def _stage_member_more_than_original_heart_count(
    state: MatchState,
    player_id: str,
    *,
    work_key: Any = None,
    unit_key: Any = None,
) -> int:
    count = 0
    for instance_id in state.players[player_id].member_area.values():
        if instance_id is None:
            continue
        card = state.cards[instance_id].card
        if isinstance(work_key, str) and work_key not in card.work_keys:
            continue
        if isinstance(unit_key, str) and unit_key not in card.unit_keys:
            continue
        original_total = sum(amount for amount in card.basic_hearts.values() if amount > 0)
        current_total = sum(
            _member_heart_count(state, player_id, instance_id, color)
            for color in _member_heart_color_slots(state, player_id, instance_id)
        )
        if current_total > original_total:
            count += 1
    return count


def _effective_required_hearts(
    player: Any,
    live_instance_id: str,
    base_requirements: dict[str, int],
) -> dict[str, int]:
    replacement: dict[str, int] | None = None
    deltas: Counter[str] = Counter()
    for modifier in player.manual_modifiers:
        if modifier.modifier_type != "required_heart":
            continue
        if modifier.target_card_instance_id not in {None, live_instance_id}:
            continue
        if isinstance(modifier.value, dict) and modifier.value.get("mode") == "replace":
            hearts = modifier.value.get("required_hearts")
            if isinstance(hearts, dict):
                replacement = {
                    str(color): int(amount)
                    for color, amount in hearts.items()
                    if isinstance(amount, int) and amount > 0
                }
            continue
        if modifier.color_slot:
            deltas[modifier.color_slot] += modifier.amount or 0
    requirements = Counter(replacement if replacement is not None else base_requirements)
    for color, amount in deltas.items():
        requirements[color] = max(0, requirements[color] + amount)
        if requirements[color] == 0:
            del requirements[color]
    return dict(sorted(requirements.items()))


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


def _queue_live_success_effects(
    state: MatchState,
    events: list[GameEvent],
) -> None:
    if state.live_success_effects_queued:
        return
    state.live_success_effects_queued = True
    for player_id, live_ids in state.success_live_moved_instance_ids.items():
        if not live_ids:
            continue
        stage_sources = [
            instance_id
            for instance_id in state.players[player_id].member_area.values()
            if instance_id is not None
        ]
        _queue_triggered_effects(
            state,
            "live_succeeded",
            events,
            source_instance_ids=[*stage_sources, *live_ids],
            trigger_data={
                "turn_number": state.turn_number,
                "successful_live_instance_ids": list(live_ids),
            },
        )
        _resolve_granted_live_success_draws(state, player_id, live_ids, events)


def _resolve_granted_live_success_draws(
    state: MatchState,
    player_id: str,
    live_ids: list[str],
    events: list[GameEvent],
) -> None:
    player = state.players[player_id]
    successful_live_ids = set(live_ids)
    for modifier in player.manual_modifiers:
        if (
            modifier.modifier_type != "flag"
            or modifier.flag != "granted_live_success_draw"
            or modifier.target_card_instance_id not in successful_live_ids
        ):
            continue
        amount = 1
        if isinstance(modifier.value, dict) and isinstance(
            modifier.value.get("amount"),
            int,
        ):
            amount = modifier.value["amount"]
        _draw(
            state,
            player_id,
            amount,
            events,
            reason=f"granted_effect:{modifier.modifier_id}",
        )
        events.append(
            GameEvent(
                event_type="granted_live_success_draw_resolved",
                player_id=player_id,
                data={
                    "modifier_id": modifier.modifier_id,
                    "live_card_instance_id": modifier.target_card_instance_id,
                    "amount": amount,
                },
                source="system",
            )
        )


def _record_success_live_move(
    state: MatchState,
    player_id: str,
    instance_id: str,
) -> None:
    if player_id not in state.success_live_moved_player_ids:
        state.success_live_moved_player_ids.append(player_id)
    state.success_live_moved_instance_ids.setdefault(player_id, []).append(instance_id)
