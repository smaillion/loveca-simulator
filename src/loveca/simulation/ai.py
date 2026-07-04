from __future__ import annotations

import itertools
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from loveca.simulation.models import ActionRequest, LegalAction, MatchState

ManualEffectPolicy = Literal["skip", "block", "noop"]


@dataclass(frozen=True)
class SimpleAIDecision:
    action: ActionRequest
    reason: str


@dataclass(frozen=True)
class SimpleAIBlocker:
    reason: str
    legal_action_types: list[str]
    player_ids: list[str | None]


@dataclass(frozen=True)
class SimpleAIPolicy:
    manual_effect_policy: ManualEffectPolicy = "skip"


class SimpleAIController:
    """Small deterministic controller that only chooses from legal actions."""

    def __init__(self, policy: SimpleAIPolicy | None = None) -> None:
        self.policy = policy or SimpleAIPolicy()

    def choose_action(
        self,
        state: MatchState,
        legal_actions: list[LegalAction],
        *,
        controlled_player_ids: set[str],
    ) -> SimpleAIDecision | SimpleAIBlocker | None:
        available = [
            action
            for action in legal_actions
            if action.player_id in controlled_player_ids
            or (action.player_id is None and controlled_player_ids == set(state.players))
        ]
        if not available:
            return None
        decision = choose_simple_ai_action(
            state,
            available,
            manual_policy=self.policy.manual_effect_policy,
        )
        if decision is None:
            return SimpleAIBlocker(
                reason="no_safe_ai_action",
                legal_action_types=[action.action_type for action in available],
                player_ids=[action.player_id for action in available],
            )
        action_type, player_id, payload, reason = decision
        if player_id not in controlled_player_ids and not (
            player_id is None and controlled_player_ids == set(state.players)
        ):
            return None
        return SimpleAIDecision(
            action=ActionRequest(
                action_type=action_type,
                expected_revision=state.revision,
                player_id=player_id,
                payload={
                    **payload,
                    "ai_decision": {
                        "controller": "simple_ai",
                        "policy": self.policy.manual_effect_policy,
                        "reason": reason,
                    },
                },
            ),
            reason=reason,
        )


def choose_simple_ai_action(
    state: MatchState,
    legal_actions: list[LegalAction],
    *,
    manual_policy: ManualEffectPolicy,
) -> tuple[str, str | None, dict[str, Any], str] | None:
    if not legal_actions:
        return None
    by_type = {action.action_type: action for action in legal_actions}
    if "choose_first_player" in by_type:
        action = by_type["choose_first_player"]
        return action.action_type, action.player_id, {"first_player_id": "player_1"}, "setup"
    if "submit_mulligan" in by_type:
        action = by_type["submit_mulligan"]
        selected = choose_mulligan_cards_for_progress(state, action.player_id or "")
        return (
            action.action_type,
            action.player_id,
            {"card_instance_ids": selected},
            "mulligan_progress",
        )
    if "resolve_effect_choice" in by_type:
        action = by_type["resolve_effect_choice"]
        options = action.options
        candidates = list(options.get("candidate_card_instance_ids", []))
        if options.get("multi_player_choice_type") == "multi_player_deploy_waiting_member":
            slots = list(options.get("available_slots", []))
            payload: dict[str, Any] = {}
            if candidates and slots:
                payload = {
                    "selected_card_instance_id": candidates[0],
                    "slot": slots[0],
                }
            return action.action_type, action.player_id, payload, "effect_choice_first_candidate"
        minimum = int(options.get("minimum", 0))
        maximum = int(options.get("maximum", len(candidates)))
        selected = candidates[: max(minimum, min(maximum, len(candidates)))]
        payload = {"selected_card_instance_ids": selected}
        if options.get("requires_order"):
            payload["ordered_card_instance_ids"] = list(selected)
        return action.action_type, action.player_id, payload, "effect_choice_minimum"
    if "resolve_live_requirements" in by_type:
        action = by_type["resolve_live_requirements"]
        if state.pending_choice and state.pending_choice.choice_type == "live_requirements":
            return (
                action.action_type,
                action.player_id,
                {
                    "live_instance_ids": list(
                        state.pending_choice.options.get("live_instance_ids", [])
                    )
                },
                "live_requirements_all",
            )
        if state.pending_choice and state.pending_choice.choice_type == "success_live":
            choices = list(state.pending_choice.options.get("card_instance_ids", []))
            choices = sorted(
                choices,
                key=lambda instance_id: (
                    -(state.cards[instance_id].card.score or 0),
                    state.cards[instance_id].card.card_code,
                ),
            )
            return (
                action.action_type,
                action.player_id,
                {"success_live_instance_id": choices[0] if choices else None},
                "success_live_highest_score",
            )
    if "resolve_effect" in by_type:
        return _choose_effect_resolution(state, by_type, manual_policy)
    if "play_member" in by_type:
        return _choose_member_play(state, by_type["play_member"], by_type)
    if "end_main_phase" in by_type:
        action = by_type["end_main_phase"]
        return action.action_type, action.player_id, {}, "end_main_phase"
    if "set_live_cards" in by_type:
        action = by_type["set_live_cards"]
        selected = choose_live_cards_for_progress(state, action.player_id or "")
        return (
            action.action_type,
            action.player_id,
            {"card_instance_ids": selected},
            "set_reachable_live_cards",
        )
    if "start_next_turn" in by_type:
        action = by_type["start_next_turn"]
        return action.action_type, action.player_id, {}, "start_next_turn"
    if "advance_phase" in by_type:
        action = by_type["advance_phase"]
        return action.action_type, action.player_id, {}, "advance_phase"
    return None


def _choose_effect_resolution(
    state: MatchState,
    by_type: dict[str, LegalAction],
    manual_policy: ManualEffectPolicy,
) -> tuple[str, str | None, dict[str, Any], str] | None:
    action = by_type["resolve_effect"]
    invocations = list(action.options.get("invocations", []))
    if not invocations:
        return None
    invocation = invocations[0]
    if invocation.get("simulation_support") == "manual_resolution":
        if invocation.get("is_optional"):
            return (
                action.action_type,
                action.player_id,
                {"invocation_id": invocation["invocation_id"], "accepted": False},
                "decline_optional_manual_effect",
            )
        if manual_policy == "skip" and "skip_effect" in by_type:
            return (
                "skip_effect",
                action.player_id,
                {
                    "invocation_id": invocation["invocation_id"],
                    "reason": "simple_ai skipped unresolved mandatory effect",
                    "error_message": "manual_resolution is not automated",
                },
                "skip_unresolved_manual_effect",
            )
        if manual_policy == "noop" and "manual_adjustment" in by_type:
            return (
                "manual_adjustment",
                action.player_id,
                {
                    "reason": "simple_ai no-op placeholder for unresolved mandatory effect",
                    "requires_confirmation": True,
                    "confirmed_by": "simple_ai_noop",
                    "source_invocation_id": invocation["invocation_id"],
                    "source_effect_id": invocation["effect_id"],
                    "source_card_instance_id": invocation["source_card_instance_id"],
                    "adjustments": [
                        {
                            "adjustment_type": "set_flag",
                            "target_player_id": action.player_id,
                            "flag": "simple_ai_unresolved_manual_effect",
                            "value": invocation["effect_id"],
                            "duration": "turn",
                        }
                    ],
                },
                "noop_unresolved_manual_effect",
            )
        return None
    payload: dict[str, Any] = {"invocation_id": invocation["invocation_id"]}
    candidates = list(invocation.get("candidate_card_instance_ids", []))
    choice = invocation.get("choice") or {}
    cost_choice = invocation.get("cost_choice") or {}
    choice_type = invocation.get("choice_type") or choice.get("choice_type")
    card_minimum = int(invocation.get("card_selection_minimum", choice.get("minimum", 0)))
    available_energy = list(
        invocation.get("energy_instance_ids", [])
        or invocation.get("active_energy_instance_ids", [])
    )
    energy_required = int(invocation.get("energy_required", 0))
    if invocation.get("is_optional") and (
        (card_minimum > 0 and len(candidates) < card_minimum)
        or (energy_required > 0 and len(available_energy) < energy_required)
    ):
        return (
            action.action_type,
            action.player_id,
            {"invocation_id": invocation["invocation_id"], "accepted": False},
            "decline_optional_unpayable_effect",
        )
    if choice_type in {
        "multi_player_discard_to_hand_size_then_draw",
        "multi_player_draw_then_discard",
        "multi_player_deploy_waiting_member",
    }:
        return action.action_type, action.player_id, payload, "resolve_multi_player_effect"
    if choice_type == "member_group_from_stage":
        selected_by_group: dict[str, list[str]] = {}
        used: set[str] = set()
        for group in invocation.get("choice_groups", []):
            group_id = group.get("group_id")
            if not isinstance(group_id, str):
                continue
            excluded = {
                instance_id
                for excluded_group_id in group.get("exclude_group_ids", [])
                for instance_id in selected_by_group.get(excluded_group_id, [])
            }
            group_candidates = [
                item
                for item in group.get("candidate_card_instance_ids", [])
                if item not in excluded and item not in used
            ]
            minimum = int(group.get("minimum", 0))
            maximum = int(group.get("maximum", len(group_candidates)))
            selected = group_candidates[: max(minimum, min(maximum, len(group_candidates)))]
            selected_by_group[group_id] = selected
            used.update(selected)
        payload["selected_card_instance_ids_by_group"] = selected_by_group
        return action.action_type, action.player_id, payload, "resolve_grouped_member_choice"
    if choice_type == "position_change_source":
        slots = list(invocation.get("position_change_slots", []))
        if slots:
            payload["to_slot"] = slots[0]
        return action.action_type, action.player_id, payload, "resolve_position_change"
    if choice.get("choice_type") == "choose_effect_branch":
        _fill_branch_choice_payload(payload, invocation, choice, candidates, available_energy)
    elif candidates:
        minimum = int(invocation.get("card_selection_minimum", choice.get("minimum", 1)))
        maximum = int(
            invocation.get(
                "card_selection_maximum",
                choice.get("maximum", len(candidates)),
            )
        )
        selected_cards = _select_candidate_cards(
            state,
            candidates,
            minimum=minimum,
            maximum=maximum,
            choice=choice or cost_choice,
        )
        if len(selected_cards) < minimum and invocation.get("is_optional"):
            return (
                action.action_type,
                action.player_id,
                {"invocation_id": invocation["invocation_id"], "accepted": False},
                "decline_optional_without_targets",
            )
        payload["selected_card_instance_ids"] = selected_cards
    destinations = list(
        invocation.get("destination_options", [])
        or choice.get("destination_options", [])
    )
    if destinations and "selected_card_instance_ids" in payload:
        payload["selected_destination"] = destinations[0]
    colors = list(choice.get("color_slots", []))
    if choice.get("choice_type") == "choose_color" or colors:
        payload["selected_color_slot"] = colors[0] if colors else "heart01"
    if choice.get("choice_type") == "choose_count":
        payload["selected_count"] = choice.get("minimum", 0)
    energy = available_energy
    if energy and "energy_instance_ids" not in payload:
        required = int(invocation.get("energy_required", choice.get("minimum", 1)))
        payload["energy_instance_ids"] = energy[:required]
    return action.action_type, action.player_id, payload, "resolve_structured_effect"


def _fill_branch_choice_payload(
    payload: dict[str, Any],
    invocation: dict[str, Any],
    choice: dict[str, Any],
    candidates: list[str],
    available_energy: list[str],
) -> None:
    selected_branch = invocation.get("selected_branch")
    if selected_branch:
        payload["selected_branch"] = selected_branch
        minimum = int(choice.get("branch_selection_minimum", {}).get(selected_branch, 0))
        maximum = int(
            choice.get("branch_selection_maximum", {}).get(
                selected_branch,
                len(candidates),
            )
        )
        if candidates:
            selected_cards = candidates[: max(minimum, min(maximum, len(candidates)))]
            payload["selected_card_instance_ids"] = selected_cards
            position_slots_by_candidate = invocation.get("position_change_slots_by_candidate", {})
            if len(selected_cards) == 1 and isinstance(position_slots_by_candidate, dict):
                slots = position_slots_by_candidate.get(selected_cards[0], [])
                if slots:
                    payload["to_slot"] = slots[0]
        return
    branches = (
        list(invocation.get("available_branch_ids", []))
        or list(invocation.get("branch_ids", []))
        or list(choice.get("branch_ids", []))
    )
    if not branches:
        return
    branch_energy_required = dict(
        invocation.get("branch_energy_required", {}) or choice.get("branch_energy_required", {})
    )
    selected = branches[0]
    for branch in branches:
        required = int(branch_energy_required.get(branch, 0))
        if required == 0 or len(available_energy) >= required:
            selected = branch
            break
    payload["selected_branch"] = selected
    required = int(branch_energy_required.get(selected, 0))
    if required:
        payload["energy_instance_ids"] = available_energy[:required]


def _choose_member_play(
    state: MatchState,
    action: LegalAction,
    by_type: dict[str, LegalAction],
) -> tuple[str, str | None, dict[str, Any], str] | None:
    player = state.players[action.player_id or ""]
    stage_count = sum(item is not None for item in player.member_area.values())
    placements = list(action.options.get("placements", []))
    if stage_count >= 3 and "end_main_phase" in by_type:
        end_action = by_type["end_main_phase"]
        return end_action.action_type, end_action.player_id, {}, "stage_full_end_main_phase"
    if stage_count >= 3:
        improving_replacements: list[dict[str, Any]] = []
        for item in placements:
            replaced_id = item.get("replaced_card_instance_id")
            new_id = item.get("card_instance_id")
            if not isinstance(replaced_id, str) or not isinstance(new_id, str):
                continue
            improvement = member_progress_value(state, new_id) - member_progress_value(
                state,
                replaced_id,
            )
            if improvement > 0:
                improving_replacements.append({**item, "_progress_improvement": improvement})
        if not improving_replacements and "end_main_phase" in by_type:
            end_action = by_type["end_main_phase"]
            return (
                end_action.action_type,
                end_action.player_id,
                {},
                "avoid_non_improving_replacement",
            )
        placements = improving_replacements or placements
    placements = sorted(
        placements,
        key=lambda item: (
            -int(item.get("_progress_improvement", 0)),
            1 if item.get("replaced_card_instance_id") else 0,
            1 if item.get("use_baton_touch") else 0,
            -member_progress_value(state, item.get("card_instance_id", "")),
            item.get("payment_cost", 99),
            {"center": 0, "left": 1, "right": 2}.get(item.get("slot"), 9),
            item.get("card_instance_id", ""),
        ),
    )
    if not placements:
        return None
    placement = placements[0]
    energy = list(action.options.get("active_energy_instance_ids", []))
    return (
        action.action_type,
        action.player_id,
        {
            "card_instance_id": placement["card_instance_id"],
            "slot": placement["slot"],
            "use_baton_touch": bool(placement.get("use_baton_touch")),
            "energy_instance_ids": energy[: int(placement.get("payment_cost", 0))],
        },
        "play_best_member",
    )


def choose_live_cards_for_progress(state: MatchState, player_id: str) -> list[str]:
    player = state.players[player_id]
    live_ids = [
        instance_id
        for instance_id in player.hand
        if state.cards[instance_id].card.card_type == "live"
    ]
    if not live_ids:
        return []

    available_hearts: Counter[str] = Counter()
    blade_count = 0
    for member_id in player.member_area.values():
        if member_id is None:
            continue
        card = state.cards[member_id].card
        available_hearts.update(card.basic_hearts)
        blade_count += card.blade or 0

    def requirement_total(instance_ids: tuple[str, ...]) -> int:
        return sum(
            sum(state.cards[instance_id].card.required_hearts.values())
            for instance_id in instance_ids
        )

    def total_score(instance_ids: tuple[str, ...]) -> int:
        return sum(state.cards[instance_id].card.score or 0 for instance_id in instance_ids)

    def unmet_requirement(instance_ids: tuple[str, ...]) -> int:
        required: Counter[str] = Counter()
        for instance_id in instance_ids:
            required.update(state.cards[instance_id].card.required_hearts)
        missing = 0
        flexible = available_hearts.get("heart0", 0) + blade_count
        for color, amount in required.items():
            if color == "heart0":
                missing += max(0, amount - sum(available_hearts.values()) - blade_count)
                continue
            shortage = max(0, amount - available_hearts.get(color, 0))
            if shortage <= flexible:
                flexible -= shortage
            else:
                missing += shortage - flexible
                flexible = 0
        return missing

    high_score_lives = sorted(
        live_ids,
        key=lambda instance_id: (
            -(state.cards[instance_id].card.score or 0),
            sum(state.cards[instance_id].card.required_hearts.values()),
            state.cards[instance_id].card.card_code,
        ),
    )
    reachable_lives = sorted(
        live_ids,
        key=lambda instance_id: (
            unmet_requirement((instance_id,)),
            requirement_total((instance_id,)),
            -(state.cards[instance_id].card.score or 0),
            state.cards[instance_id].card.card_code,
        ),
    )
    pool: list[str] = []
    for instance_id in [*reachable_lives[:8], *high_score_lives[:6]]:
        if instance_id not in pool:
            pool.append(instance_id)
        if len(pool) >= 10:
            break
    combinations: list[tuple[str, ...]] = []
    for size in range(1, min(3, len(pool)) + 1):
        combinations.extend(itertools.combinations(pool, size))
    own_success = len(player.success_live_area)
    opponent_success = max(
        (
            len(other.success_live_area)
            for other_id, other in state.players.items()
            if other_id != player_id
        ),
        default=0,
    )
    success_gap = opponent_success - own_success
    if own_success >= 2:
        target_size = 3 if state.turn_number >= 8 or opponent_success >= 2 else 1
    elif success_gap >= 2:
        target_size = 3
    elif success_gap == 1 or state.turn_number >= 8:
        target_size = 3
    else:
        target_size = 1

    def combo_key(combo: tuple[str, ...]) -> tuple[object, ...]:
        missing = unmet_requirement(combo)
        size = len(combo)
        size_penalty = size if missing else abs(size - target_size)
        pressure_score = total_score(combo) if success_gap > 0 else 0
        return (
            missing,
            size_penalty,
            -pressure_score,
            -total_score(combo),
            requirement_total(combo),
            tuple(state.cards[instance_id].card.card_code for instance_id in combo),
        )

    best = min(combinations, key=combo_key)
    return list(best)


def choose_mulligan_cards_for_progress(state: MatchState, player_id: str) -> list[str]:
    player = state.players[player_id]
    hand = list(player.hand)
    members = [
        instance_id
        for instance_id in hand
        if state.cards[instance_id].card.card_type == "member"
    ]
    lives = [
        instance_id
        for instance_id in hand
        if state.cards[instance_id].card.card_type == "live"
    ]
    sorted_members = sorted(
        members,
        key=lambda item: (-member_progress_value(state, item), state.cards[item].card.card_code),
    )
    sorted_lives = sorted(
        lives,
        key=lambda item: (
            sum(state.cards[item].card.required_hearts.values()),
            -(state.cards[item].card.score or 0),
            state.cards[item].card.card_code,
        ),
    )
    keep: set[str] = set()
    keep.update(sorted_members[: (2 if lives else 1)])
    keep.update(sorted_lives[:2])
    if len(keep) >= 4 and members and lives:
        return []
    return [instance_id for instance_id in hand if instance_id not in keep]


def member_progress_value(state: MatchState, instance_id: object) -> int:
    if not isinstance(instance_id, str) or instance_id not in state.cards:
        return 0
    card = state.cards[instance_id].card
    heart_total = sum(int(amount) for amount in card.basic_hearts.values())
    return heart_total * 4 + int(card.blade or 0) * 3 + int(card.cost or 0)


def _select_candidate_cards(
    state: MatchState,
    candidates: list[str],
    *,
    minimum: int,
    maximum: int,
    choice: dict[str, Any],
) -> list[str]:
    target_count = max(minimum, min(maximum, len(candidates)))
    if target_count <= 0:
        return []
    condition = choice.get("condition") if isinstance(choice, dict) else None
    if isinstance(condition, dict) and condition.get("selected_share_unit_key"):
        for count in range(target_count, minimum - 1, -1):
            for selected in itertools.combinations(candidates, count):
                shared_units: set[str] | None = None
                for instance_id in selected:
                    units = set(state.cards[instance_id].card.unit_keys)
                    shared_units = units if shared_units is None else shared_units & units
                if shared_units:
                    return list(selected)
        return []
    return candidates[:target_count]
