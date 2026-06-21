"""Black-box sandbox deck construction and match-driving smoke test.

This is an exploratory tool, not a production simulator or AI player. It builds
diverse legal decks from the local card DB, then drives matches only through
LegalAction output. Unsupported mandatory manual effects are recorded as
blockers instead of being silently auto-resolved.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sqlite3
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from loveca.decks.analyzer import DECKLIST_VERSION, DeckEntry, DeckList, analyze_deck
from loveca.simulation.effects import load_effect_registry
from loveca.simulation.engine import IllegalActionError, generate_legal_actions
from loveca.simulation.models import ActionRequest, LegalAction, MatchState
from loveca.simulation.service import MatchService

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = PROJECT_ROOT / "data_sources" / "effect-registry.v0.json"


@dataclass
class SandboxDeckSummary:
    name: str
    members: int
    lives: int
    energy: int
    unique_cards: int
    effect_summary: dict[str, int]
    timing_summary: dict[str, int]
    sample_cards: list[str]


@dataclass
class SandboxMatchSummary:
    match_index: int
    first_deck: str
    second_deck: str
    status: str
    final_phase: str
    turn_number: int
    action_count: int
    success_live_counts: dict[str, int] = field(default_factory=dict)
    blocker: str | None = None
    blocker_detail: dict[str, Any] = field(default_factory=dict)
    events: dict[str, int] = field(default_factory=dict)
    skipped_effects: list[dict[str, Any]] = field(default_factory=list)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("data/loveca.sqlite3"))
    parser.add_argument("--output", type=Path, default=Path("logs/ai_sandbox"))
    parser.add_argument("--decks", type=int, default=20)
    parser.add_argument("--matches", type=int, default=20)
    parser.add_argument("--max-actions", type=int, default=450)
    parser.add_argument(
        "--manual-policy",
        choices=("block", "noop", "skip"),
        default="block",
        help=(
            "block records unresolved mandatory manual effects as blockers; "
            "noop resolves them with a marked no-op flag for plumbing-only tests; "
            "skip records a structured skipped-effect event and continues"
        ),
    )
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    decks = build_decks(args.database, args.decks)
    deck_summaries = [
        summarize_deck(args.database, deck)
        for deck in decks
    ]
    match_summaries = run_matches(
        args.database,
        decks,
        match_count=args.matches,
        max_actions=args.max_actions,
        manual_policy=args.manual_policy,
    )
    write_outputs(args.output, decks, deck_summaries, match_summaries)
    print(f"Wrote sandbox report to {args.output / 'sandbox-report.md'}")
    return 0


def build_decks(database: Path, count: int) -> list[DeckList]:
    effect_priority = _load_effect_priority(DEFAULT_REGISTRY)
    members = _load_card_pool(database, "member", effect_priority)
    lives = _load_card_pool(database, "live", effect_priority)
    energies = _load_card_pool(database, "energy", effect_priority)
    if len(members) < 12 or len(lives) < 12 or len(energies) < 12:
        raise RuntimeError("local card database does not contain enough cards")
    member_by_work = _group_by_work(members)
    live_by_work = _group_by_work(lives)
    compatible_work_keys = sorted(
        work_key
        for work_key in set(member_by_work).intersection(live_by_work)
        if len(member_by_work[work_key]) >= 12 and len(live_by_work[work_key]) >= 12
    )

    decks: list[DeckList] = []
    for index in range(count):
        if compatible_work_keys:
            work_key = compatible_work_keys[index % len(compatible_work_keys)]
            work_cycle = index // len(compatible_work_keys)
            live_source = sorted(
                live_by_work[work_key],
                key=lambda item: (
                    _live_progress_cost(item),
                    -int(item.get("score", 0)),
                    -effect_priority.get(item["card_code"], 0),
                    item["card_code"],
                ),
            )
            live_codes = _window(live_source, work_cycle * 3, 3)
            required_colors = _required_color_profile(live_codes)
            member_codes = _select_member_cards_for_progress(
                member_by_work[work_key],
                required_colors,
                effect_priority,
                work_cycle,
            )
        else:
            required_colors = Counter()
            member_codes = _select_member_cards_for_progress(
                members,
                required_colors,
                effect_priority,
                index,
            )
            live_source = sorted(
                lives,
                key=lambda item: (
                    _live_progress_cost(item),
                    -int(item.get("score", 0)),
                    -effect_priority.get(item["card_code"], 0),
                    item["card_code"],
                ),
            )
            live_codes = _window(live_source, index * 3, 3)
        energy_codes = _window(energies, index * 12, 12)
        decks.append(
            DeckList(
                version=DECKLIST_VERSION,
                name=f"Sandbox Deck {index + 1:02d}",
                main_deck=tuple(
                    [
                        *(
                            DeckEntry(
                                card_code=item["card_code"],
                                quantity=4,
                                preferred_printing_id=item["card_id"],
                            )
                            for item in member_codes
                        ),
                        *(
                            DeckEntry(
                                card_code=item["card_code"],
                                quantity=4,
                                preferred_printing_id=item["card_id"],
                            )
                            for item in live_codes
                        ),
                    ]
                ),
                energy_deck=tuple(
                    DeckEntry(
                        card_code=item["card_code"],
                        quantity=1,
                        preferred_printing_id=item["card_id"],
                    )
                    for item in energy_codes
                ),
            )
        )
    return decks


def _select_member_cards_for_progress(
    source: list[dict[str, Any]],
    required_colors: Counter[str],
    effect_priority: dict[str, int],
    offset: int,
) -> list[dict[str, Any]]:
    low_cost_source = sorted(
        source,
        key=lambda item: (
            int(item.get("cost") if item.get("cost") is not None else 99),
            -_member_heart_fit_score(item, required_colors),
            -effect_priority.get(item["card_code"], 0),
            item["card_code"],
        ),
    )
    skill_source = sorted(
        source,
        key=lambda item: (
            -effect_priority.get(item["card_code"], 0),
            -_member_heart_fit_score(item, required_colors),
            int(item.get("cost") if item.get("cost") is not None else 99),
            item["card_code"],
        ),
    )
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(items: list[dict[str, Any]], limit: int) -> None:
        for item in items:
            if len(selected) >= limit:
                return
            card_code = str(item["card_code"])
            if card_code in seen:
                continue
            selected.append(item)
            seen.add(card_code)

    add(_window(low_cost_source, offset * 3, 6), 6)
    add(_window(skill_source, offset * 6, 12), 12)
    add(low_cost_source, 12)
    add(skill_source, 12)
    return selected[:12]


def summarize_deck(database: Path, deck: DeckList) -> SandboxDeckSummary:
    analysis = analyze_deck(database, deck)
    if not analysis.is_legal:
        raise RuntimeError(f"generated illegal deck {deck.name}: {analysis.issues}")
    return SandboxDeckSummary(
        name=deck.name or "(unnamed)",
        members=analysis.card_type_counts["main_deck"].get("member", 0),
        lives=analysis.card_type_counts["main_deck"].get("live", 0),
        energy=analysis.card_type_counts["energy_deck"].get("energy", 0),
        unique_cards=len(analysis.copy_counts),
        effect_summary=dict(analysis.effect_execution_summary),
        timing_summary=dict(analysis.effect_timing_summary),
        sample_cards=[
            entry.card_code
            for entry in [*deck.main_deck[:4], *deck.main_deck[-2:], *deck.energy_deck[:2]]
        ],
    )


def run_matches(
    database: Path,
    decks: list[DeckList],
    *,
    match_count: int,
    max_actions: int,
    manual_policy: str,
) -> list[SandboxMatchSummary]:
    results: list[SandboxMatchSummary] = []
    with tempfile.TemporaryDirectory(prefix="loveca-ai-sandbox-") as tmp:
        runtime = Path(tmp) / "matches.sqlite3"
        service = MatchService(database, runtime)
        for index in range(match_count):
            first = decks[index % len(decks)]
            second = decks[(index * 7 + 3) % len(decks)]
            result = service.create_match(
                first_name="Sandbox A",
                first_deck=first,
                second_name="Sandbox B",
                second_deck=second,
                seed=9000 + index,
                match_id=f"sandbox-{index + 1:02d}",
            )
            state = result.state
            event_counts: Counter[str] = Counter(event.event_type for event in result.events)
            skipped_effects: list[dict[str, Any]] = []
            blocker = None
            blocker_detail: dict[str, Any] = {}
            actions = 0
            while actions < max_actions and state.phase != "complete":
                legal_actions = generate_legal_actions(state)
                decision = choose_action(
                    state,
                    legal_actions,
                    manual_policy=manual_policy,
                )
                if decision is None:
                    blocker = classify_blocker(state, legal_actions)
                    blocker_detail = describe_state(state, legal_actions)
                    break
                action_type, player_id, payload = decision
                try:
                    applied = service.apply(
                        state.match_id,
                        ActionRequest(
                            action_type=action_type,
                            expected_revision=state.revision,
                            player_id=player_id,
                            payload=payload,
                        ),
                    )
                except IllegalActionError as exc:
                    blocker = "illegal_action"
                    blocker_detail = {
                        **describe_state(state, legal_actions),
                        "attempted_action": action_type,
                        "error": str(exc),
                    }
                    break
                state = applied.state
                actions += 1
                event_counts.update(event.event_type for event in applied.events)
                for event in applied.events:
                    if event.event_type == "effect_skipped_due_to_error":
                        skipped_effects.append(dict(event.data))
            status = "completed" if state.phase == "complete" else "blocked"
            if actions >= max_actions and state.phase != "complete":
                legal_actions = generate_legal_actions(state)
                diagnosis = diagnose_max_actions(state, legal_actions)
                blocker = f"max_actions:{diagnosis['reason']}"
                blocker_detail = {
                    **describe_state(state, legal_actions),
                    "max_action_diagnosis": diagnosis,
                }
            results.append(
                SandboxMatchSummary(
                    match_index=index + 1,
                    first_deck=first.name or "(unnamed)",
                    second_deck=second.name or "(unnamed)",
                    status=status,
                    final_phase=state.phase,
                    turn_number=state.turn_number,
                    action_count=actions,
                    success_live_counts={
                        player_id: len(player.success_live_area)
                        for player_id, player in state.players.items()
                    },
                    blocker=blocker,
                    blocker_detail=blocker_detail,
                    events=dict(sorted(event_counts.items())),
                    skipped_effects=skipped_effects,
                )
            )
    return results


def choose_action(
    state: MatchState,
    legal_actions: list[LegalAction],
    *,
    manual_policy: str,
) -> tuple[str, str | None, dict[str, Any]] | None:
    if not legal_actions:
        return None
    by_type = {action.action_type: action for action in legal_actions}
    if "choose_first_player" in by_type:
        action = by_type["choose_first_player"]
        return action.action_type, action.player_id, {"first_player_id": "player_1"}
    if "submit_mulligan" in by_type:
        action = by_type["submit_mulligan"]
        selected = _choose_mulligan_cards_for_progress(state, action.player_id or "")
        return action.action_type, action.player_id, {"card_instance_ids": selected}
    if "resolve_effect_choice" in by_type:
        action = by_type["resolve_effect_choice"]
        options = action.options
        candidates = list(options.get("candidate_card_instance_ids", []))
        if (
            options.get("multi_player_choice_type")
            == "multi_player_deploy_waiting_member"
        ):
            slots = list(options.get("available_slots", []))
            payload: dict[str, Any] = {}
            if candidates and slots:
                payload = {
                    "selected_card_instance_id": candidates[0],
                    "slot": slots[0],
                }
            return action.action_type, action.player_id, payload
        minimum = int(options.get("minimum", 0))
        maximum = int(options.get("maximum", len(candidates)))
        selected = candidates[: max(minimum, min(maximum, len(candidates)))]
        payload = {"selected_card_instance_ids": selected}
        if options.get("requires_order"):
            payload["ordered_card_instance_ids"] = list(selected)
        return action.action_type, action.player_id, payload
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
            )
    if "resolve_effect" in by_type:
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
                )
            if manual_policy == "skip" and "skip_effect" in by_type:
                return (
                    "skip_effect",
                    action.player_id,
                    {
                        "invocation_id": invocation["invocation_id"],
                        "reason": "ai sandbox skipped unresolved mandatory effect",
                        "error_message": "manual_resolution is not automated",
                    },
                )
            if manual_policy == "noop" and "manual_adjustment" in by_type:
                return (
                    "manual_adjustment",
                    action.player_id,
                    {
                        "reason": "ai sandbox no-op placeholder for unresolved mandatory effect",
                        "requires_confirmation": True,
                        "confirmed_by": "ai_sandbox_noop",
                        "source_invocation_id": invocation["invocation_id"],
                        "source_effect_id": invocation["effect_id"],
                        "source_card_instance_id": invocation["source_card_instance_id"],
                        "adjustments": [
                            {
                                "adjustment_type": "set_flag",
                                "target_player_id": action.player_id,
                                "flag": "ai_sandbox_unresolved_manual_effect",
                                "value": invocation["effect_id"],
                                "duration": "turn",
                            }
                        ],
                    },
                )
            return None
        payload: dict[str, Any] = {"invocation_id": invocation["invocation_id"]}
        candidates = list(invocation.get("candidate_card_instance_ids", []))
        choice = invocation.get("choice") or {}
        cost_choice = invocation.get("cost_choice") or {}
        choice_type = invocation.get("choice_type") or choice.get("choice_type")
        card_minimum = int(
            invocation.get(
                "card_selection_minimum",
                choice.get("minimum", 0),
            )
        )
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
            )
        if choice_type in {
            "multi_player_discard_to_hand_size_then_draw",
            "multi_player_draw_then_discard",
            "multi_player_deploy_waiting_member",
        }:
            return action.action_type, action.player_id, payload
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
                candidates = [
                    item
                    for item in group.get("candidate_card_instance_ids", [])
                    if item not in excluded and item not in used
                ]
                minimum = int(group.get("minimum", 0))
                maximum = int(group.get("maximum", len(candidates)))
                selected = candidates[: max(minimum, min(maximum, len(candidates)))]
                selected_by_group[group_id] = selected
                used.update(selected)
            payload["selected_card_instance_ids_by_group"] = selected_by_group
            return action.action_type, action.player_id, payload
        if choice_type == "position_change_source":
            slots = list(invocation.get("position_change_slots", []))
            if slots:
                payload["to_slot"] = slots[0]
            return action.action_type, action.player_id, payload
        if choice.get("choice_type") == "choose_effect_branch":
            selected_branch = invocation.get("selected_branch")
            if selected_branch:
                payload["selected_branch"] = selected_branch
                minimum = int(
                    choice.get("branch_selection_minimum", {}).get(
                        selected_branch, 0
                    )
                )
                maximum = int(
                    choice.get("branch_selection_maximum", {}).get(
                        selected_branch, len(candidates)
                    )
                )
                if candidates:
                    selected_cards = candidates[
                        : max(minimum, min(maximum, len(candidates)))
                    ]
                    payload["selected_card_instance_ids"] = selected_cards
                    position_slots_by_candidate = invocation.get(
                        "position_change_slots_by_candidate",
                        {},
                    )
                    if (
                        len(selected_cards) == 1
                        and isinstance(position_slots_by_candidate, dict)
                    ):
                        slots = position_slots_by_candidate.get(selected_cards[0], [])
                        if slots:
                            payload["to_slot"] = slots[0]
            else:
                branches = (
                    list(invocation.get("available_branch_ids", []))
                    or list(invocation.get("branch_ids", []))
                    or list(choice.get("branch_ids", []))
                )
                if branches:
                    branch_energy_required = dict(
                        invocation.get("branch_energy_required", {})
                        or choice.get("branch_energy_required", {})
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
        elif candidates:
            minimum = int(
                invocation.get(
                    "card_selection_minimum",
                    choice.get("minimum", 1),
                )
            )
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
            required = int(
                invocation.get(
                    "energy_required",
                    choice.get("minimum", 1),
                )
            )
            payload["energy_instance_ids"] = energy[:required]
        return action.action_type, action.player_id, payload
    if "play_member" in by_type:
        action = by_type["play_member"]
        player = state.players[action.player_id or ""]
        stage_count = sum(item is not None for item in player.member_area.values())
        stage_target = 3
        placements = list(action.options.get("placements", []))
        if stage_count >= stage_target:
            improving_replacements: list[dict[str, Any]] = []
            for item in placements:
                replaced_id = item.get("replaced_card_instance_id")
                new_id = item.get("card_instance_id")
                if not isinstance(replaced_id, str) or not isinstance(new_id, str):
                    continue
                improvement = _member_progress_value(state, new_id) - _member_progress_value(
                    state, replaced_id
                )
                if improvement > 0:
                    improving_replacements.append({**item, "_progress_improvement": improvement})
            if not improving_replacements and "end_main_phase" in by_type:
                end_action = by_type["end_main_phase"]
                return end_action.action_type, end_action.player_id, {}
            placements = improving_replacements or placements
        placements = sorted(
            placements,
            key=lambda item: (
                -int(item.get("_progress_improvement", 0)),
                1 if item.get("replaced_card_instance_id") else 0,
                1 if item.get("use_baton_touch") else 0,
                -_member_progress_value(state, item.get("card_instance_id", "")),
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
        )
    if "end_main_phase" in by_type:
        action = by_type["end_main_phase"]
        return action.action_type, action.player_id, {}
    if "set_live_cards" in by_type:
        action = by_type["set_live_cards"]
        selected = _choose_live_cards_for_progress(state, action.player_id or "")
        return action.action_type, action.player_id, {"card_instance_ids": selected}
    if "start_next_turn" in by_type:
        action = by_type["start_next_turn"]
        return action.action_type, action.player_id, {}
    if "advance_phase" in by_type:
        action = by_type["advance_phase"]
        return action.action_type, action.player_id, {}
    return None


def _choose_live_cards_for_progress(state: MatchState, player_id: str) -> list[str]:
    """Choose a small, likely reachable Live set for sandbox progress.

    This smoke controller is not trying to play optimally. It only needs to avoid
    repeatedly setting hard-to-satisfy Live piles that stretch games to the action
    cap without discovering new rule blockers.
    """

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
        if missing:
            size_penalty = size
        else:
            size_penalty = abs(size - target_size)
        pressure_score = total_score(combo) if success_gap > 0 else 0
        return (
            missing,
            size_penalty,
            -pressure_score,
            -total_score(combo),
            requirement_total(combo),
            tuple(state.cards[instance_id].card.card_code for instance_id in combo),
        )

    best = min(
        combinations,
        key=combo_key,
    )
    return list(best)


def _choose_mulligan_cards_for_progress(state: MatchState, player_id: str) -> list[str]:
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
        key=lambda item: (
            -_member_progress_value(state, item),
            state.cards[item].card.card_code,
        ),
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
    return [
        instance_id
        for instance_id in hand
        if instance_id not in keep
    ]


def _member_progress_value(state: MatchState, instance_id: object) -> int:
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


def classify_blocker(state: MatchState, legal_actions: list[LegalAction]) -> str:
    for action in legal_actions:
        if action.action_type != "manual_adjustment":
            continue
        if action.options.get("source_invocations"):
            return "mandatory_manual_resolution"
    if state.pending_effects:
        return "pending_effect_without_policy"
    if state.pending_choice is not None:
        return f"unhandled_pending_choice:{state.pending_choice.choice_type}"
    return "no_legal_action"


def diagnose_max_actions(
    state: MatchState,
    legal_actions: list[LegalAction],
) -> dict[str, Any]:
    hand_type_counts = {
        player_id: _zone_type_counts(state, player.hand)
        for player_id, player in state.players.items()
    }
    success_live_counts = {
        player_id: len(player.success_live_area)
        for player_id, player in state.players.items()
    }
    live_hand_counts = {
        player_id: counts.get("live", 0)
        for player_id, counts in hand_type_counts.items()
    }
    reason = "action_cap_reached"
    if state.pending_effects:
        reason = "pending_effect_at_cap"
    elif state.pending_choice is not None:
        reason = f"pending_choice_at_cap:{state.pending_choice.choice_type}"
    elif all(count == 0 for count in live_hand_counts.values()):
        if any(count >= 2 for count in success_live_counts.values()):
            reason = "match_point_players_have_no_live_in_hand"
        else:
            reason = "no_live_cards_in_hand"
    elif any(
        action.action_type == "play_member"
        and (action.options.get("placements") or [])
        for action in legal_actions
    ):
        reason = "member_development_at_cap"
    elif any(action.action_type == "set_live_cards" for action in legal_actions):
        reason = "live_set_available_at_cap"
    elif any(action.action_type == "advance_phase" for action in legal_actions):
        reason = "phase_progression_at_cap"
    return {
        "reason": reason,
        "phase": state.phase,
        "turn_number": state.turn_number,
        "success_live_counts": success_live_counts,
        "hand_type_counts": hand_type_counts,
        "legal_action_types": [action.action_type for action in legal_actions],
    }


def describe_state(state: MatchState, legal_actions: list[LegalAction]) -> dict[str, Any]:
    return {
        "phase": state.phase,
        "turn_number": state.turn_number,
        "pending_choice": state.pending_choice.model_dump() if state.pending_choice else None,
        "pending_effects": [item.model_dump() for item in state.pending_effects[:3]],
        "legal_actions": [action.model_dump() for action in legal_actions],
    }


def _zone_type_counts(state: MatchState, instance_ids: list[str]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for instance_id in instance_ids:
        if instance_id in state.cards:
            counts[state.cards[instance_id].card.card_type] += 1
    return dict(sorted(counts.items()))


def write_outputs(
    output: Path,
    decks: list[DeckList],
    deck_summaries: list[SandboxDeckSummary],
    match_summaries: list[SandboxMatchSummary],
) -> None:
    effect_metadata = _load_effect_metadata(DEFAULT_REGISTRY)
    (output / "decks").mkdir(parents=True, exist_ok=True)
    for deck in decks:
        payload = {
            "version": deck.version,
            "name": deck.name,
            "main_deck": [asdict(entry) for entry in deck.main_deck],
            "energy_deck": [asdict(entry) for entry in deck.energy_deck],
        }
        (output / "decks" / f"{deck.name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    (output / "sandbox-summary.json").write_text(
        json.dumps(
            {
                "deck_summaries": [asdict(item) for item in deck_summaries],
                "match_summaries": [asdict(item) for item in match_summaries],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    completed = sum(item.status == "completed" for item in match_summaries)
    blockers = Counter(item.blocker or "none" for item in match_summaries)
    skipped_effect_counts: Counter[str] = Counter(
        skipped.get("effect_id", "(unknown)")
        for item in match_summaries
        for skipped in item.skipped_effects
    )
    total_success_lives = Counter(
        sum(item.success_live_counts.values()) for item in match_summaries
    )
    lines = [
        "# AI Sandbox Black-Box Playtest Report",
        "",
        "## Scope",
        "",
        f"* {len(deck_summaries)} generated legal decklists from the local card DB.",
        f"* {len(match_summaries)} match attempts driven only through LegalAction output.",
        "* In `block` mode, unsupported mandatory manual effects are recorded as blockers.",
        "* In `noop` mode, unsupported mandatory manual effects are advanced with a marked no-op flag for plumbing-only testing.",
        "* In `skip` mode, unsupported mandatory manual effects produce `effect_skipped_due_to_error` events and continue.",
        "",
        "## Summary",
        "",
        f"* Decks generated: {len(deck_summaries)}",
        f"* Matches attempted: {len(match_summaries)}",
        f"* Matches completed: {completed}",
        f"* Blockers: {dict(sorted(blockers.items()))}",
        f"* Skipped effects: {dict(skipped_effect_counts.most_common(20))}",
        f"* Total success Live counts per match: {dict(sorted(total_success_lives.items()))}",
        "",
        "## Deck Coverage",
        "",
        "| Deck | Unique cards | Effects | Timings | Sample cards |",
        "|---|---:|---|---|---|",
    ]
    for item in deck_summaries:
        lines.append(
            f"| {item.name} | {item.unique_cards} | {item.effect_summary} | "
            f"{item.timing_summary} | {', '.join(item.sample_cards)} |"
        )
    lines.extend(
        [
            "",
            "## Match Results",
            "",
            "| # | Status | Decks | Phase | Turn | Actions | Success Lives | Blocker |",
            "|---:|---|---|---|---:|---:|---|---|",
        ]
    )
    for item in match_summaries:
        success_counts = ", ".join(
            f"{player_id}:{count}"
            for player_id, count in sorted(item.success_live_counts.items())
        )
        lines.append(
            f"| {item.match_index} | {item.status} | {item.first_deck} vs {item.second_deck} | "
            f"{item.final_phase} | {item.turn_number} | {item.action_count} | "
            f"{success_counts} | {item.blocker or ''} |"
        )
    if skipped_effect_counts:
        lines.extend(
            [
                "",
                "## Skipped Effect IDs",
                "",
                "| Effect ID | Count | Trigger | Timing | Support | Label JA |",
                "|---|---:|---|---|---|---|",
            ]
        )
        for effect_id, count in skipped_effect_counts.most_common(50):
            metadata = effect_metadata.get(effect_id, {})
            lines.append(
                f"| {effect_id} | {count} | "
                f"{metadata.get('trigger', '')} | "
                f"{metadata.get('timing', '')} | "
                f"{metadata.get('simulation_support', '')} | "
                f"{_markdown_cell(metadata.get('label_ja', ''))} |"
            )
    lines.extend(
        [
            "",
            "## Rule / Engine Follow-Up Themes",
            "",
            "* Mandatory `manual_resolution` effects still block automated black-box play.",
            "* LegalAction payloads are sufficient for many core phases, but a richer test controller needs effect-specific policies.",
            "* Deck diversity is easy to generate from the local DB, but meaningful AI play requires strategy heuristics beyond this smoke harness.",
        ]
    )
    (output / "sandbox-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_effect_priority(registry_path: Path) -> dict[str, int]:
    if not registry_path.exists():
        return {}
    registry = load_effect_registry(registry_path)
    priority: dict[str, int] = {}
    for effect in registry.effects:
        score = 1
        if effect.simulation_support == "test_validated_executable":
            score = 3
        elif effect.execution_mode in {"auto_resolve", "prompt_then_resolve"}:
            score = 2
        priority[effect.card_code] = max(priority.get(effect.card_code, 0), score)
    return priority


def _load_effect_metadata(registry_path: Path) -> dict[str, dict[str, str]]:
    if not registry_path.exists():
        return {}
    registry = load_effect_registry(registry_path)
    return {
        effect.effect_id: {
            "label_ja": effect.label_ja,
            "trigger": effect.trigger,
            "timing": effect.timing,
            "simulation_support": effect.simulation_support,
        }
        for effect in registry.effects
    }


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _load_card_pool(
    database: Path,
    card_type: str,
    effect_priority: dict[str, int],
) -> list[dict[str, Any]]:
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT
                card.id AS gameplay_card_id,
                card.card_code,
                MIN(printing.card_id) AS card_id,
                member.cost AS cost,
                member.blade AS blade,
                live.score AS score,
                (
                    SELECT GROUP_CONCAT(heart.color_slot || ':' || heart.value)
                    FROM card_heart_values AS heart
                    WHERE heart.gameplay_card_id = card.id
                      AND heart.heart_role = 'basic'
                ) AS basic_hearts,
                (
                    SELECT GROUP_CONCAT(heart.color_slot || ':' || heart.value)
                    FROM card_heart_values AS heart
                    WHERE heart.gameplay_card_id = card.id
                      AND heart.heart_role = 'required'
                ) AS required_hearts,
                GROUP_CONCAT(DISTINCT work.work_key) AS work_keys,
                GROUP_CONCAT(DISTINCT unit.unit_key) AS unit_keys
            FROM gameplay_cards AS card
            JOIN card_printings AS printing
              ON printing.gameplay_card_id = card.id
            LEFT JOIN member_card_attributes AS member
              ON member.gameplay_card_id = card.id
            LEFT JOIN live_card_attributes AS live
              ON live.gameplay_card_id = card.id
            LEFT JOIN gameplay_card_works AS work_link
              ON work_link.gameplay_card_id = card.id
            LEFT JOIN works AS work
              ON work.id = work_link.work_id
            LEFT JOIN gameplay_card_units AS unit_link
              ON unit_link.gameplay_card_id = card.id
            LEFT JOIN units AS unit
              ON unit.id = unit_link.unit_id
            WHERE card.card_type = ?
            GROUP BY card.id, card.card_code
            ORDER BY card.card_code
            """,
            (card_type,),
        ).fetchall()
    pool = [
        {
            "card_code": str(row["card_code"]),
            "card_id": str(row["card_id"]),
            "cost": int(row["cost"] or 0),
            "blade": int(row["blade"] or 0),
            "score": int(row["score"] or 0),
            "basic_hearts": _split_heart_values(row["basic_hearts"]),
            "required_hearts": _split_heart_values(row["required_hearts"]),
            "work_keys": _split_keys(row["work_keys"]),
            "unit_keys": _split_keys(row["unit_keys"]),
        }
        for row in rows
    ]
    return sorted(
        pool,
        key=lambda item: (
            -effect_priority.get(item["card_code"], 0),
            item["card_code"],
        ),
    )


def _group_by_work(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        for work_key in item.get("work_keys", []):
            grouped.setdefault(work_key, []).append(item)
    return grouped


def _required_color_profile(live_items: list[dict[str, Any]]) -> Counter[str]:
    profile: Counter[str] = Counter()
    for item in live_items:
        for color, amount in item.get("required_hearts", {}).items():
            if color != "heart0":
                profile[color] += int(amount)
    return profile


def _member_heart_fit_score(
    member_item: dict[str, Any],
    required_colors: Counter[str],
) -> int:
    hearts: dict[str, int] = member_item.get("basic_hearts", {})
    matched = sum(
        min(int(hearts.get(color, 0)), amount)
        for color, amount in required_colors.items()
    )
    total_hearts = sum(int(value) for value in hearts.values())
    return matched * 10 + total_hearts * 2 + int(member_item.get("blade", 0))


def _live_progress_cost(live_item: dict[str, Any]) -> int:
    required: dict[str, int] = live_item.get("required_hearts", {})
    colored = sum(
        int(amount)
        for color, amount in required.items()
        if color != "heart0"
    )
    flexible = int(required.get("heart0", 0))
    color_count = sum(1 for color, amount in required.items() if color != "heart0" and amount)
    return colored * 3 + flexible + color_count


def _split_heart_values(value: object) -> dict[str, int]:
    if not isinstance(value, str) or not value:
        return {}
    result: dict[str, int] = {}
    for item in value.split(","):
        if ":" not in item:
            continue
        color, raw_amount = item.split(":", 1)
        try:
            amount = int(raw_amount)
        except ValueError:
            continue
        result[color] = result.get(color, 0) + amount
    return result


def _split_keys(value: object) -> list[str]:
    if not isinstance(value, str) or not value:
        return []
    return sorted({item for item in value.split(",") if item})


def _window(items: list[dict[str, Any]], start: int, size: int) -> list[dict[str, Any]]:
    return [items[(start + offset) % len(items)] for offset in range(size)]


if __name__ == "__main__":
    raise SystemExit(main())
