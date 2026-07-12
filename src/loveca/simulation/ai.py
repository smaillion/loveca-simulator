from __future__ import annotations

import itertools
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from loveca.simulation.effects import EffectDefinition, EffectOperation
from loveca.simulation.models import (
    ActionRequest,
    ControllerPolicyVersion,
    LegalAction,
    MatchState,
)
from loveca.simulation.rule_evaluation import (
    AIObservation,
    build_ai_observation,
    estimate_live_combo_missing_hearts,
)

ManualEffectPolicy = Literal["skip", "block", "noop"]


@dataclass(frozen=True)
class SimpleAIDecision:
    action: ActionRequest
    reason: str
    score_summary: dict[str, int | float | str]


@dataclass(frozen=True)
class SimpleAIBlocker:
    reason: str
    legal_action_types: list[str]
    player_ids: list[str | None]


@dataclass(frozen=True)
class SimpleAIPolicy:
    manual_effect_policy: ManualEffectPolicy = "skip"
    policy_version: ControllerPolicyVersion = "simple_ai_v1"


@dataclass(frozen=True)
class AICandidate:
    action_type: str
    player_id: str | None
    payload: dict[str, Any]
    score: float
    reason: str
    components: tuple[tuple[str, float], ...] = ()


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
        allow_player_neutral_actions: bool = False,
    ) -> SimpleAIDecision | SimpleAIBlocker | None:
        available = [
            action
            for action in legal_actions
            if action.player_id in controlled_player_ids
            or (action.player_id is None and controlled_player_ids == set(state.players))
            or (action.player_id is None and allow_player_neutral_actions)
        ]
        if not available:
            return None
        if self.policy.policy_version == "simple_ai_v0":
            decision = choose_simple_ai_action(
                state,
                available,
                manual_policy=self.policy.manual_effect_policy,
            )
            candidate = (
                AICandidate(*decision[:3], score=0, reason=decision[3])
                if decision is not None
                else None
            )
        else:
            viewer_id = _decision_viewer_id(state, available, controlled_player_ids)
            observation = build_ai_observation(state, viewer_id, available)
            candidate = choose_simple_ai_action_v1(
                observation,
                available,
                manual_policy=self.policy.manual_effect_policy,
            )
        if candidate is None:
            return SimpleAIBlocker(
                reason="no_safe_ai_action",
                legal_action_types=[action.action_type for action in available],
                player_ids=[action.player_id for action in available],
            )
        action_type = candidate.action_type
        player_id = candidate.player_id
        payload = candidate.payload
        reason = candidate.reason
        if (
            player_id not in controlled_player_ids
            and not (player_id is None and controlled_player_ids == set(state.players))
            and not (player_id is None and allow_player_neutral_actions)
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
                        "policy_version": self.policy.policy_version,
                        "reason": reason,
                        "score": round(candidate.score, 3),
                        "score_summary": {
                            key: round(value, 3)
                            for key, value in candidate.components[:6]
                        },
                    },
                },
            ),
            reason=reason,
            score_summary={
                "score": round(candidate.score, 3),
                **{
                    key: round(value, 3)
                    for key, value in candidate.components[:6]
                },
            },
        )


def _decision_viewer_id(
    state: MatchState,
    legal_actions: list[LegalAction],
    controlled_player_ids: set[str],
) -> str:
    for action in legal_actions:
        if action.player_id in controlled_player_ids:
            return action.player_id or ""
    if state.active_player_id in controlled_player_ids:
        return state.active_player_id or ""
    return sorted(controlled_player_ids)[0]


def choose_simple_ai_action_v1(
    observation: AIObservation,
    legal_actions: list[LegalAction],
    *,
    manual_policy: ManualEffectPolicy,
) -> AICandidate | None:
    """Choose a deterministic scored action from the authoritative legal list."""

    if not legal_actions:
        return None
    by_type = {action.action_type: action for action in legal_actions}
    if "choose_first_player" in by_type:
        action = by_type["choose_first_player"]
        player_ids = list(action.options.get("player_ids", []))
        selected = observation.player_id if observation.player_id in player_ids else player_ids[0]
        return AICandidate(
            action.action_type,
            action.player_id,
            {"first_player_id": selected},
            1000,
            "setup_choose_first",
        )
    if "submit_mulligan" in by_type:
        action = by_type["submit_mulligan"]
        selected = _choose_mulligan_v1(observation)
        return AICandidate(
            action.action_type,
            action.player_id,
            {"card_instance_ids": selected},
            900,
            "mulligan_curve_and_live_fit",
            (("replace_count", float(len(selected))),),
        )
    if "resolve_effect_choice" in by_type:
        return _choose_follow_up_effect_choice_v1(
            observation,
            by_type["resolve_effect_choice"],
        )
    if "resolve_live_requirements" in by_type:
        return _choose_live_requirement_resolution_v1(
            observation,
            by_type["resolve_live_requirements"],
        )
    if "resolve_effect" in by_type:
        return _choose_effect_resolution_v1(
            observation,
            by_type,
            manual_policy,
        )

    if observation.phase.endswith("_main"):
        candidates: list[AICandidate] = []
        if "activate_effect" in by_type:
            candidates.extend(
                _activation_candidates_v1(observation, by_type["activate_effect"])
            )
        if "play_member" in by_type:
            candidates.extend(_member_play_candidates_v1(observation, by_type["play_member"]))
        if "end_main_phase" in by_type:
            action = by_type["end_main_phase"]
            candidates.append(
                AICandidate(
                    action.action_type,
                    action.player_id,
                    {},
                    0,
                    "preserve_resources_end_main",
                )
            )
        return _best_candidate(candidates)

    if "set_live_cards" in by_type:
        return _choose_live_set_v1(observation, by_type["set_live_cards"])
    if "start_next_turn" in by_type:
        action = by_type["start_next_turn"]
        return AICandidate(action.action_type, action.player_id, {}, 800, "start_next_turn")
    if "advance_phase" in by_type:
        action = by_type["advance_phase"]
        return AICandidate(action.action_type, action.player_id, {}, 700, "advance_phase")
    return None


def _choose_mulligan_v1(observation: AIObservation) -> list[str]:
    player = observation.players[observation.player_id]
    members = [item for item in player.hand if _card_type(observation, item) == "member"]
    lives = [item for item in player.hand if _card_type(observation, item) == "live"]
    live_colors: Counter[str] = Counter()
    for live_id in lives:
        live = observation.evaluation.live(live_id)
        if live is not None:
            live_colors.update(dict(live.required_hearts))
    ranked_members = sorted(
        members,
        key=lambda item: (
            -_member_hand_value(observation, item, live_colors),
            _card_code(observation, item),
            item,
        ),
    )
    ranked_lives = sorted(
        lives,
        key=lambda item: (
            estimate_live_combo_missing_hearts(observation.evaluation, (item,)),
            -_live_score(observation, item),
            _card_code(observation, item),
            item,
        ),
    )
    keep: set[str] = set(ranked_members[:2])
    keep.update(ranked_lives[:1])
    if len(ranked_members) >= 3 and not lives:
        keep.add(ranked_members[2])
    return [item for item in player.hand if item not in keep]


def _choose_follow_up_effect_choice_v1(
    observation: AIObservation,
    action: LegalAction,
) -> AICandidate:
    options = action.options
    candidates = list(options.get("candidate_card_instance_ids", []))
    if options.get("multi_player_choice_type") == "multi_player_deploy_waiting_member":
        slots = list(options.get("available_slots", []))
        selected = _rank_card_ids(observation, candidates, descending=True)
        payload: dict[str, Any] = {}
        if selected and slots:
            payload = {
                "selected_card_instance_id": selected[0],
                "slot": _preferred_slot(slots),
            }
        return AICandidate(
            action.action_type,
            action.player_id,
            payload,
            600,
            "deploy_best_waiting_member",
        )
    minimum = int(options.get("minimum", options.get("card_selection_minimum", 0)))
    maximum = int(
        options.get(
            "maximum",
            options.get("card_selection_maximum", len(candidates)),
        )
    )
    selected_destination = options.get("selected_destination")
    beneficial_selection = selected_destination in {
        "hand",
        "main_deck_top_ordered",
        "main_deck_top",
    }
    target_count = min(maximum, len(candidates)) if beneficial_selection else minimum
    ranked = _rank_card_ids(observation, candidates, descending=beneficial_selection)
    selected = ranked[:target_count]
    payload = {"selected_card_instance_ids": selected}
    if options.get("invocation_id"):
        payload["invocation_id"] = options["invocation_id"]
    if options.get("requires_order"):
        payload["ordered_card_instance_ids"] = list(selected)
    return AICandidate(
        action.action_type,
        action.player_id,
        payload,
        650,
        "effect_follow_up_value_order",
        (("selected", float(len(selected))),),
    )


def _choose_live_requirement_resolution_v1(
    observation: AIObservation,
    action: LegalAction,
) -> AICandidate:
    options = action.options
    if "card_instance_ids" in options:
        choices = list(options.get("card_instance_ids", []))
        choices.sort(
            key=lambda item: (
                -_live_score(observation, item),
                _card_code(observation, item),
                item,
            )
        )
        selected = choices[0] if choices else None
        return AICandidate(
            action.action_type,
            action.player_id,
            {"success_live_instance_id": selected},
            750,
            "success_live_highest_effective_score",
        )
    live_ids = list(options.get("live_instance_ids", []))
    live_ids.sort(
        key=lambda item: (
            _generic_heart_requirement(observation, item),
            -_required_heart_total(observation, item),
            _card_code(observation, item),
        )
    )
    return AICandidate(
        action.action_type,
        action.player_id,
        {"live_instance_ids": live_ids},
        700,
        "resolve_colored_live_requirements_first",
    )


def _activation_candidates_v1(
    observation: AIObservation,
    action: LegalAction,
) -> list[AICandidate]:
    candidates: list[AICandidate] = []
    for activation in action.options.get("activations", []):
        effect_id = activation.get("effect_id")
        effect = observation.effects.get(effect_id) if isinstance(effect_id, str) else None
        if effect is None or effect.simulation_support == "manual_resolution":
            continue
        value, components = _effect_value(observation, effect)
        source_id = activation.get("source_card_instance_id")
        source_cost = 0.0
        source_cost_adjustment = 0.0
        if isinstance(source_id, str):
            source_to_waiting = next(
                (
                    item
                    for item in effect.cost
                    if item.action_type == "source_to_waiting_room"
                ),
                None,
            )
            apply_wait = next(
                (item for item in effect.cost if item.action_type == "apply_wait"),
                None,
            )
            if source_to_waiting is not None:
                generic_cost = abs(
                    _operation_value_without_observation(
                        source_to_waiting,
                        is_cost=True,
                    )
                )
                if source_id in observation.players[observation.player_id].hand:
                    source_cost = max(
                        2.0,
                        min(10.0, _card_value(observation, source_id) * 0.35),
                    )
                else:
                    source_cost = max(2.0, _stage_member_value(observation, source_id))
                source_cost_adjustment = generic_cost - source_cost
                value += source_cost_adjustment
            elif apply_wait is not None:
                generic_cost = abs(
                    _operation_value_without_observation(
                        apply_wait,
                        is_cost=True,
                    )
                )
                source_member = next(
                    (
                        item
                        for item in observation.evaluation.stage_members
                        if item.instance_id == source_id
                    ),
                    None,
                )
                source_cost = float(source_member.blade * 5) if source_member else 2.0
                source_cost_adjustment = generic_cost - source_cost
                value += source_cost_adjustment
        if value <= 0:
            continue
        candidates.append(
            AICandidate(
                action.action_type,
                action.player_id,
                {
                    "effect_id": effect.effect_id,
                    "source_card_instance_id": activation["source_card_instance_id"],
                },
                20 + value,
                "activate_positive_structured_effect",
                (*components, ("source_cost_adjustment", source_cost_adjustment)),
            )
        )
    return candidates


def _member_play_candidates_v1(
    observation: AIObservation,
    action: LegalAction,
) -> list[AICandidate]:
    active_energy = list(action.options.get("active_energy_instance_ids", []))
    stage_by_slot = dict(observation.players[observation.player_id].member_area)
    candidates: list[AICandidate] = []
    for placement in action.options.get("placements", []):
        instance_id = placement.get("card_instance_id")
        if not isinstance(instance_id, str):
            continue
        slot = placement.get("slot")
        payment = int(placement.get("payment_cost", 0))
        member_value = _member_stage_projection_value(observation, instance_id)
        replaced_id = placement.get("replaced_card_instance_id") or stage_by_slot.get(slot)
        replaced_value = _stage_member_value(observation, replaced_id)
        on_play_bonus = _card_trigger_effect_value(
            observation,
            instance_id,
            "member_played",
        )
        empty_bonus = 28 if replaced_id is None else 0
        replacement_gain = (
            member_value
            - replaced_value
            - payment * 2.5
            + on_play_bonus * 0.35
        )
        if replaced_id is not None and replacement_gain <= 0:
            continue
        score = (
            replacement_gain
            + empty_bonus
        )
        candidates.append(
            AICandidate(
                action.action_type,
                action.player_id,
                {
                    "card_instance_id": instance_id,
                    "slot": slot,
                    "use_baton_touch": bool(placement.get("use_baton_touch")),
                    "energy_instance_ids": active_energy[:payment],
                },
                score,
                "play_member_for_live_plan",
                (
                    ("member", member_value),
                    ("replace", -replaced_value),
                    ("energy", -payment * 2.5),
                    ("on_play", on_play_bonus * 0.35),
                    ("empty_slot", float(empty_bonus)),
                ),
            )
        )
    return [item for item in candidates if item.score > 0]


def _choose_live_set_v1(
    observation: AIObservation,
    action: LegalAction,
) -> AICandidate:
    player = observation.players[observation.player_id]
    live_ids = [item for item in player.hand if _card_type(observation, item) == "live"]
    combinations = [
        combo
        for size in range(1, min(3, len(live_ids)) + 1)
        for combo in itertools.combinations(live_ids, size)
    ]
    if not combinations:
        return AICandidate(
            action.action_type,
            action.player_id,
            {"card_instance_ids": []},
            0,
            "no_live_in_hand",
        )
    own_success = observation.evaluation.success_live_count
    opponent_success = observation.evaluation.opponent_success_live_count
    pressure = own_success >= 2 or opponent_success >= 2
    scored: list[AICandidate] = []
    for combo in combinations:
        missing = estimate_live_combo_missing_hearts(observation.evaluation, combo)
        total_score = sum(_live_score(observation, item) for item in combo)
        reachable_bonus = 70 if missing <= 0.25 else max(-45.0, 25 - missing * 20)
        score_pressure = total_score * (13 if pressure else 8)
        size_cost = (len(combo) - 1) * (
            16 if missing > 0.25 else 2 if pressure else 8
        )
        winning_bonus = 45 if own_success >= 2 and missing <= 0.25 else 0
        score = reachable_bonus + score_pressure + winning_bonus - size_cost
        scored.append(
            AICandidate(
                action.action_type,
                action.player_id,
                {"card_instance_ids": list(combo)},
                score,
                "set_best_reachable_live_combo",
                (
                    ("reachable", reachable_bonus),
                    ("score", float(score_pressure)),
                    ("missing_heart", -missing * 30),
                    ("match_point", float(winning_bonus)),
                    ("extra_live_cost", float(-size_cost)),
                ),
            )
        )
    best = _best_candidate(scored)
    if best is not None:
        return best
    return AICandidate(
        action.action_type,
        action.player_id,
        {"card_instance_ids": []},
        0,
        "no_live_in_hand",
    )


def _choose_effect_resolution_v1(
    observation: AIObservation,
    by_type: dict[str, LegalAction],
    manual_policy: ManualEffectPolicy,
) -> AICandidate | None:
    action = by_type["resolve_effect"]
    scored: list[tuple[float, dict[str, Any], EffectDefinition | None]] = []
    for invocation in action.options.get("invocations", []):
        effect_id = invocation.get("effect_id")
        effect = observation.effects.get(effect_id) if isinstance(effect_id, str) else None
        mandatory = not bool(invocation.get("is_optional"))
        value = -10000.0
        if effect is not None:
            value, _components = _effect_value(observation, effect)
        scored.append((10000.0 if mandatory else value, invocation, effect))
    if not scored:
        return None
    _priority, invocation, effect = max(
        scored,
        key=lambda item: (item[0], str(item[1].get("effect_id", ""))),
    )
    if invocation.get("simulation_support") == "manual_resolution":
        if invocation.get("is_optional"):
            return AICandidate(
                action.action_type,
                action.player_id,
                {"invocation_id": invocation["invocation_id"], "accepted": False},
                0,
                "decline_optional_manual_effect",
            )
        if manual_policy == "skip" and "skip_effect" in by_type:
            return AICandidate(
                "skip_effect",
                action.player_id,
                {
                    "invocation_id": invocation["invocation_id"],
                    "reason": "simple_ai skipped unresolved mandatory effect",
                    "error_message": "manual_resolution is not automated",
                },
                -100,
                "skip_unresolved_manual_effect",
            )
        return None
    if effect is None:
        return None
    if not _invocation_choices_are_currently_satisfiable(invocation):
        if invocation.get("is_optional"):
            return AICandidate(
                action.action_type,
                action.player_id,
                {"invocation_id": invocation["invocation_id"], "accepted": False},
                0,
                "decline_unavailable_optional_effect",
            )
        return None
    value, components = _effect_value(observation, effect)
    payload = _structured_effect_payload_v1(observation, invocation, effect)
    if invocation.get("is_optional") and value <= 0:
        payload = {"invocation_id": invocation["invocation_id"], "accepted": False}
        return AICandidate(
            action.action_type,
            action.player_id,
            payload,
            0,
            "decline_nonpositive_optional_effect",
            components,
        )
    payload.setdefault("accepted", True)
    return AICandidate(
        action.action_type,
        action.player_id,
        payload,
        500 + value,
        "resolve_best_structured_effect",
        components,
    )


def _invocation_choices_are_currently_satisfiable(
    invocation: dict[str, Any],
) -> bool:
    choice_type = invocation.get("choice_type")
    uses_card_candidates = choice_type in {
        "card_from_zone",
        "deploy_member_from_waiting_room",
        "member_from_stage",
        "post_action_card_from_zone",
    } or (
        choice_type == "choose_effect_branch"
        and isinstance(invocation.get("selected_branch"), str)
    )
    deferred_without_current_cost = bool(
        invocation.get("choice_deferred_until_after_first_step")
        and invocation.get("resolution_stage") == "initial"
        and not invocation.get("cost_choice")
    )
    if (
        "candidate_card_instance_ids" in invocation
        and uses_card_candidates
        and not deferred_without_current_cost
    ):
        minimum = int(invocation.get("card_selection_minimum", 0))
        candidates = invocation.get("candidate_card_instance_ids", [])
        if not isinstance(candidates, list) or len(candidates) < minimum:
            return False
    for group in invocation.get("choice_groups", []):
        minimum = int(group.get("minimum", 0))
        candidates = group.get("candidate_card_instance_ids", [])
        if not isinstance(candidates, list) or len(candidates) < minimum:
            return False
    energy_required = invocation.get("energy_required")
    if isinstance(energy_required, int) and not isinstance(energy_required, bool):
        energy_ids = invocation.get("energy_instance_ids", [])
        if not isinstance(energy_ids, list) or len(energy_ids) < energy_required:
            return False
    return True


def _structured_effect_payload_v1(
    observation: AIObservation,
    invocation: dict[str, Any],
    effect: EffectDefinition,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"invocation_id": invocation["invocation_id"]}
    choice = invocation.get("choice") or {}
    cost_choice = invocation.get("cost_choice") or {}
    choice_type = invocation.get("choice_type") or choice.get("choice_type")
    candidates = list(invocation.get("candidate_card_instance_ids", []))
    if choice_type in {
        "multi_player_discard_to_hand_size_then_draw",
        "multi_player_draw_then_discard",
        "multi_player_deploy_waiting_member",
    }:
        return payload
    if choice_type in {"member_group_from_stage", "card_groups_from_zone"}:
        selected_by_group: dict[str, list[str]] = {}
        used: set[str] = set()
        for group in invocation.get("choice_groups", []):
            group_id = group.get("group_id")
            if not isinstance(group_id, str):
                continue
            excluded = {
                item
                for excluded_id in group.get("exclude_group_ids", [])
                for item in selected_by_group.get(excluded_id, [])
            }
            group_candidates = [
                item
                for item in group.get("candidate_card_instance_ids", [])
                if item not in excluded and item not in used
            ]
            ranked = _rank_card_ids(observation, group_candidates, descending=True)
            minimum = int(group.get("minimum", 0))
            maximum = int(group.get("maximum", len(ranked)))
            selected = ranked[: max(minimum, min(maximum, len(ranked)))]
            selected_by_group[group_id] = selected
            used.update(selected)
        payload["selected_card_instance_ids_by_group"] = selected_by_group
        return payload
    if choice_type == "position_change_source":
        slots = list(invocation.get("position_change_slots", []))
        if slots:
            payload["to_slot"] = _preferred_slot(slots)
        return payload
    if choice.get("choice_type") == "choose_effect_branch":
        branch = _choose_effect_branch_v1(observation, invocation, effect)
        if branch:
            payload["selected_branch"] = branch
            required = int(invocation.get("branch_energy_required", {}).get(branch, 0))
            if required:
                payload["energy_instance_ids"] = list(
                    invocation.get("energy_instance_ids", [])
                )[:required]
        if invocation.get("resolution_stage") == "initial":
            return payload

    minimum = int(invocation.get("card_selection_minimum", choice.get("minimum", 0)))
    maximum = int(
        invocation.get("card_selection_maximum", choice.get("maximum", len(candidates)))
    )
    is_cost = invocation.get("resolution_stage") == "initial" and bool(cost_choice)
    selection_choice = cost_choice if is_cost else choice
    resolved_choice = {
        **selection_choice,
        "target_player": invocation.get(
            "target_player",
            selection_choice.get("target_player"),
        ),
        "destination_options": invocation.get(
            "destination_options",
            selection_choice.get("destination_options", []),
        ),
    }
    descending = not is_cost and _effect_selection_is_beneficial(
        effect,
        resolved_choice,
    )
    ranked = _rank_card_ids(observation, candidates, descending=descending)
    target_count = minimum if is_cost or not descending else min(maximum, len(ranked))
    selected_count = max(minimum, min(target_count, len(ranked)))
    selected = _select_cards_satisfying_condition(
        observation,
        candidates,
        count=selected_count,
        descending=descending,
        condition=selection_choice.get("condition", {}),
    )
    if candidates or minimum:
        payload["selected_card_instance_ids"] = selected
    position_slots_by_candidate = invocation.get(
        "position_change_slots_by_candidate",
        {},
    )
    if selected and isinstance(position_slots_by_candidate, dict):
        slots = position_slots_by_candidate.get(selected[0], [])
        if isinstance(slots, list) and slots:
            payload["to_slot"] = _preferred_slot(slots)
    destinations = list(invocation.get("destination_options", []))
    destination_follows_first_step = bool(
        invocation.get("choice_deferred_until_after_first_step")
    )
    if (
        destinations
        and "selected_card_instance_ids" in payload
        and not destination_follows_first_step
    ):
        payload["selected_destination"] = destinations[0]
    colors = list(choice.get("color_slots", []))
    if choice_type == "choose_color" or colors:
        payload["selected_color_slot"] = _choose_needed_heart_color(
            observation,
            colors or ["heart01"],
        )
    if choice_type == "choose_count":
        payload["selected_count"] = _choose_effect_count(
            effect,
            choice,
            maximum_override=invocation.get("card_selection_maximum"),
        )
    energy = list(
        invocation.get("energy_instance_ids", [])
        or invocation.get("active_energy_instance_ids", [])
    )
    if energy:
        required = int(invocation.get("energy_required", choice.get("minimum", 1)))
        if invocation.get("energy_required_source") == "selected_count":
            required = int(payload.get("selected_count", 0))
        payload["energy_instance_ids"] = energy[:required]
    return payload


def _choose_effect_branch_v1(
    observation: AIObservation,
    invocation: dict[str, Any],
    effect: EffectDefinition,
) -> str | None:
    existing = invocation.get("selected_branch")
    if isinstance(existing, str):
        return existing
    branches = list(invocation.get("available_branch_ids", []))
    if not branches:
        return None
    required = dict(invocation.get("branch_energy_required", {}))
    available_energy = len(invocation.get("energy_instance_ids", []))
    scored: list[tuple[float, str]] = []
    for branch in branches:
        if int(required.get(branch, 0)) > available_energy:
            continue
        operations = [item for item in effect.actions if item.branch in {None, branch}]
        value = sum(_operation_value(observation, item, is_cost=False) for item in operations)
        value -= int(required.get(branch, 0)) * 4
        scored.append((value, branch))
    return max(scored, key=lambda item: (item[0], item[1]))[1] if scored else branches[0]


def _choose_effect_count(
    effect: EffectDefinition,
    choice: dict[str, Any],
    *,
    maximum_override: object = None,
) -> int:
    minimum = int(choice.get("minimum", 0))
    maximum = int(choice.get("maximum", minimum))
    if isinstance(maximum_override, int) and not isinstance(maximum_override, bool):
        maximum = min(maximum, maximum_override)
    marginal = 0.0
    for operation in effect.actions:
        if operation.amount_source == "selected_count":
            marginal += _operation_value_without_observation(operation, is_cost=False)
    for operation in effect.cost:
        if operation.amount_source == "selected_count":
            marginal += _operation_value_without_observation(operation, is_cost=True)
    return maximum if marginal > 0 else minimum


def _effect_selection_is_beneficial(
    effect: EffectDefinition,
    choice: dict[str, Any],
) -> bool:
    if choice.get("target_player") == "opponent":
        return True
    destinations = set(choice.get("destination_options", []))
    if choice.get("selected_destination") in {"hand", "stage"}:
        return True
    if destinations & {"hand", "stage", "main_deck_top", "main_deck_top_ordered"}:
        return True
    harmful = {"discard_from_hand", "apply_wait", "apply_wait_member", "source_to_waiting_room"}
    return not any(item.action_type in harmful for item in effect.actions)


def _select_cards_satisfying_condition(
    observation: AIObservation,
    candidates: list[str],
    *,
    count: int,
    descending: bool,
    condition: object,
) -> list[str]:
    ranked = _rank_card_ids(observation, candidates, descending=descending)
    if count <= 0 or not isinstance(condition, dict) or not condition:
        return ranked[:count]

    groups: dict[str, list[str]] = {}
    if condition.get("selected_share_unit_key"):
        for instance_id in candidates:
            card = observation.card(instance_id)
            for unit_key in card.unit_keys if card is not None else []:
                groups.setdefault(unit_key, []).append(instance_id)
    elif condition.get("selected_share_work_key"):
        for instance_id in candidates:
            card = observation.card(instance_id)
            for work_key in card.work_keys if card is not None else []:
                groups.setdefault(work_key, []).append(instance_id)
    elif condition.get("selected_same_name_ja"):
        for instance_id in candidates:
            card = observation.card(instance_id)
            if card is not None:
                groups.setdefault(card.name_ja, []).append(instance_id)
    else:
        return ranked[:count]

    valid_selections = {
        tuple(_rank_card_ids(observation, group, descending=descending)[:count])
        for _key, group in sorted(groups.items())
        if len(group) >= count
    }
    if not valid_selections:
        return ranked[:count]
    return list(
        max(
            valid_selections,
            key=lambda selection: (
                sum(_card_value(observation, item) for item in selection)
                * (1 if descending else -1),
                _stable_payload_key({"selected": selection}),
            ),
        )
    )


def _effect_value(
    observation: AIObservation,
    effect: EffectDefinition,
) -> tuple[float, tuple[tuple[str, float], ...]]:
    action_value = sum(
        _operation_value(observation, operation, is_cost=False)
        for operation in effect.actions
    )
    cost_value = sum(
        _operation_value(observation, operation, is_cost=True)
        for operation in effect.cost
    )
    choice_cost = -3.0 * max(0, effect.cost_choice.minimum) if effect.cost_choice else 0.0
    total = action_value + cost_value + choice_cost
    return total, (
        ("effect_actions", action_value),
        ("effect_costs", cost_value),
        ("choice_cost", choice_cost),
    )


def _operation_value(
    observation: AIObservation,
    operation: EffectOperation,
    *,
    is_cost: bool,
) -> float:
    value = _operation_value_without_observation(operation, is_cost=is_cost)
    if operation.action_type == "draw_until_hand_size":
        own = observation.players[observation.player_id]
        target = operation.target_hand_size or own.hand_count
        value = max(0, target - own.hand_count) * 8
        if is_cost:
            value = -value
    if operation.action_type == "modify_required_heart":
        amount = operation.amount or 0
        value = -amount * 6
        if is_cost:
            value = -abs(value)
    return value


def _operation_value_without_observation(
    operation: EffectOperation,
    *,
    is_cost: bool,
) -> float:
    amount = float(operation.amount if operation.amount is not None else 1)
    action_type = operation.action_type
    base = 0.0
    if action_type in {"draw_card", "draw_card_per_stage_member", "draw_until_hand_size"}:
        base = 8 * amount
    elif action_type in {"ready_energy", "place_energy_from_deck"}:
        base = 5 * amount
    elif action_type == "ready_member":
        base = 6 * amount
    elif action_type in {"gain_blade", "gain_blade_to_stage_members"}:
        base = 6 * amount
    elif action_type in {"gain_heart", "gain_heart_to_stage_members"}:
        base = 7 * amount
    elif action_type in {"modify_score", "replace_score"}:
        base = 11 * amount
    elif action_type in {"return_from_waiting_room", "move_selected_to_hand"}:
        base = 7 * amount
    elif action_type in {"inspect_top_cards", "reveal_top_cards", "reveal_cards"}:
        base = 2 * amount
    elif action_type in {"apply_wait", "apply_wait_member", "apply_wait_energy"}:
        base = 6 * amount if operation.target == "opponent" else -5 * amount
    elif action_type == "pay_energy":
        base = -5 * amount
    elif action_type in {"discard_from_hand", "source_to_waiting_room"}:
        base = -6 * amount
    elif action_type in {"modify_required_heart", "replace_required_hearts"}:
        base = 6 * amount
    elif action_type in {
        "position_change_source",
        "position_change_selected",
        "rotate_stage_members",
    }:
        base = 2
    elif action_type == "manual_resolution":
        base = -1000
    if is_cost:
        return -abs(base) if base else -2 * abs(amount)
    return base


def _card_trigger_effect_value(
    observation: AIObservation,
    instance_id: str,
    trigger: str,
) -> float:
    card = observation.card(instance_id)
    if card is None:
        return 0.0
    total = 0.0
    for effect_id in card.effect_ids:
        effect = observation.effects.get(effect_id)
        if (
            effect is not None
            and effect.trigger == trigger
            and effect.simulation_support == "test_validated_executable"
        ):
            total += max(0.0, _effect_value(observation, effect)[0])
    return total


def _choose_needed_heart_color(
    observation: AIObservation,
    colors: list[str],
) -> str:
    available = Counter(dict(observation.evaluation.stage_hearts))
    required: Counter[str] = Counter()
    for live in observation.evaluation.lives:
        required.update(dict(live.required_hearts))
    return max(
        colors,
        key=lambda color: (
            required.get(color, 0) - available.get(color, 0),
            required.get(color, 0),
            color,
        ),
    )


def _member_hand_value(
    observation: AIObservation,
    instance_id: str,
    live_colors: Counter[str] | None = None,
) -> float:
    card = observation.card(instance_id)
    if card is None or card.card_type != "member":
        return 0.0
    live_colors = live_colors or Counter(
        color
        for live in observation.evaluation.lives
        for color, amount in live.required_hearts
        for _ in range(max(0, amount))
    )
    hearts = sum(card.basic_hearts.values())
    color_fit = sum(
        min(amount, live_colors.get(color, 0))
        for color, amount in card.basic_hearts.items()
    )
    return hearts * 10 + (card.blade or 0) * 7 + color_fit * 5 - (card.cost or 0) * 1.4


def _member_stage_projection_value(
    observation: AIObservation,
    instance_id: str,
) -> float:
    card = observation.card(instance_id)
    if card is None or card.card_type != "member":
        return 0.0
    required: Counter[str] = Counter()
    for live in observation.evaluation.lives:
        required.update(dict(live.required_hearts))
    hearts = sum(card.basic_hearts.values())
    color_fit = sum(
        min(amount, required.get(color, 0))
        for color, amount in card.basic_hearts.items()
    )
    return (
        hearts * 10
        + (card.blade or 0) * 7
        + color_fit * 4
        + (card.cost or 0) * 0.3
    )


def _stage_member_value(observation: AIObservation, instance_id: object) -> float:
    if not isinstance(instance_id, str):
        return 0.0
    member = next(
        (
            item
            for item in observation.evaluation.stage_members
            if item.instance_id == instance_id
        ),
        None,
    )
    if member is None:
        return _card_value(observation, instance_id)
    return member.heart_total * 10 + member.blade * 7 + member.cost * 0.3


def _card_value(observation: AIObservation, instance_id: str) -> float:
    card = observation.card(instance_id)
    if card is None:
        return 0.0
    if card.card_type == "member":
        return _member_hand_value(observation, instance_id)
    if card.card_type == "live":
        live = observation.evaluation.live(instance_id)
        missing = estimate_live_combo_missing_hearts(observation.evaluation, (instance_id,))
        score = live.score if live is not None else card.score or 0
        required = live.required_total if live is not None else sum(card.required_hearts.values())
        scarcity_bonus = 0.0
        own_hand = observation.players[observation.player_id].hand
        if instance_id in own_hand:
            live_count = sum(
                _card_type(observation, item) == "live" for item in own_hand
            )
            scarcity_bonus = 100.0 if live_count <= 1 else 25.0 if live_count == 2 else 0.0
        return score * 12 - missing * 8 - required + scarcity_bonus
    return 1.0


def _rank_card_ids(
    observation: AIObservation,
    instance_ids: list[str],
    *,
    descending: bool,
) -> list[str]:
    return sorted(
        instance_ids,
        key=lambda item: (
            -_card_value(observation, item) if descending else _card_value(observation, item),
            _card_code(observation, item),
            item,
        ),
    )


def _live_score(observation: AIObservation, instance_id: str) -> int:
    live = observation.evaluation.live(instance_id)
    if live is not None:
        return live.score
    card = observation.card(instance_id)
    return card.score or 0 if card is not None else 0


def _required_heart_total(observation: AIObservation, instance_id: str) -> int:
    live = observation.evaluation.live(instance_id)
    return live.required_total if live is not None else 0


def _generic_heart_requirement(observation: AIObservation, instance_id: str) -> int:
    live = observation.evaluation.live(instance_id)
    return dict(live.required_hearts).get("heart0", 0) if live is not None else 0


def _card_type(observation: AIObservation, instance_id: str) -> str:
    card = observation.card(instance_id)
    return card.card_type if card is not None else ""


def _card_code(observation: AIObservation, instance_id: str) -> str:
    card = observation.card(instance_id)
    return card.card_code if card is not None else instance_id


def _preferred_slot(slots: list[str]) -> str:
    return min(slots, key=lambda item: ({"center": 0, "left": 1, "right": 2}.get(item, 9), item))


def _best_candidate(candidates: list[AICandidate]) -> AICandidate | None:
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            item.score,
            item.reason,
            item.action_type,
            _stable_payload_key(item.payload),
        ),
    )


def _stable_payload_key(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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
    if choice_type in {"member_group_from_stage", "card_groups_from_zone"}:
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
