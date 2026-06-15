"""Black-box sandbox deck construction and match-driving smoke test.

This is an exploratory tool, not a production simulator or AI player. It builds
diverse legal decks from the local card DB, then drives matches only through
LegalAction output. Unsupported mandatory manual effects are recorded as
blockers instead of being silently auto-resolved.
"""

from __future__ import annotations

import argparse
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
    blocker: str | None = None
    blocker_detail: dict[str, Any] = field(default_factory=dict)
    events: dict[str, int] = field(default_factory=dict)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("data/loveca.sqlite3"))
    parser.add_argument("--output", type=Path, default=Path("logs/ai_sandbox"))
    parser.add_argument("--decks", type=int, default=20)
    parser.add_argument("--matches", type=int, default=20)
    parser.add_argument("--max-actions", type=int, default=220)
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

    decks: list[DeckList] = []
    for index in range(count):
        member_codes = _window(members, index * 12, 12)
        live_codes = _window(lives, index * 12, 12)
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
                                quantity=1,
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
            status = "completed" if state.phase == "complete" else "blocked"
            if actions >= max_actions and state.phase != "complete":
                blocker = "max_actions"
                blocker_detail = describe_state(state, generate_legal_actions(state))
            results.append(
                SandboxMatchSummary(
                    match_index=index + 1,
                    first_deck=first.name or "(unnamed)",
                    second_deck=second.name or "(unnamed)",
                    status=status,
                    final_phase=state.phase,
                    turn_number=state.turn_number,
                    action_count=actions,
                    blocker=blocker,
                    blocker_detail=blocker_detail,
                    events=dict(sorted(event_counts.items())),
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
        return action.action_type, action.player_id, {"card_instance_ids": []}
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
                    payload["selected_card_instance_ids"] = candidates[
                        : max(minimum, min(maximum, len(candidates)))
                    ]
            else:
                branches = list(invocation.get("branch_ids", [])) or list(
                    choice.get("branch_ids", [])
                )
                if branches:
                    payload["selected_branch"] = branches[0]
        elif candidates:
            payload["selected_card_instance_ids"] = candidates[: choice.get("minimum", 1)]
        if choice.get("choice_type") == "choose_color":
            colors = list(choice.get("color_slots", []))
            payload["selected_color_slot"] = colors[0] if colors else "heart01"
        if choice.get("choice_type") == "choose_count":
            payload["selected_count"] = choice.get("minimum", 0)
        energy = list(invocation.get("active_energy_instance_ids", []))
        if energy:
            payload["energy_instance_ids"] = energy[: choice.get("minimum", 1)]
        return action.action_type, action.player_id, payload
    if "play_member" in by_type:
        action = by_type["play_member"]
        placements = sorted(
            action.options.get("placements", []),
            key=lambda item: (
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
        player = state.players[action.player_id or ""]
        selected = [
            instance_id
            for instance_id in player.hand
            if state.cards[instance_id].card.card_type == "live"
        ][:1]
        return action.action_type, action.player_id, {"card_instance_ids": selected}
    if "start_next_turn" in by_type:
        action = by_type["start_next_turn"]
        return action.action_type, action.player_id, {}
    if "advance_phase" in by_type:
        action = by_type["advance_phase"]
        return action.action_type, action.player_id, {}
    return None


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


def describe_state(state: MatchState, legal_actions: list[LegalAction]) -> dict[str, Any]:
    return {
        "phase": state.phase,
        "turn_number": state.turn_number,
        "pending_choice": state.pending_choice.model_dump() if state.pending_choice else None,
        "pending_effects": [item.model_dump() for item in state.pending_effects[:3]],
        "legal_actions": [action.model_dump() for action in legal_actions],
    }


def write_outputs(
    output: Path,
    decks: list[DeckList],
    deck_summaries: list[SandboxDeckSummary],
    match_summaries: list[SandboxMatchSummary],
) -> None:
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
    lines = [
        "# AI Sandbox Black-Box Playtest Report",
        "",
        "## Scope",
        "",
        "* 20 generated legal decklists from the local card DB.",
        "* 20 match attempts driven only through LegalAction output.",
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
            "| # | Status | Decks | Phase | Turn | Actions | Blocker |",
            "|---:|---|---|---|---:|---:|---|",
        ]
    )
    for item in match_summaries:
        lines.append(
            f"| {item.match_index} | {item.status} | {item.first_deck} vs {item.second_deck} | "
            f"{item.final_phase} | {item.turn_number} | {item.action_count} | {item.blocker or ''} |"
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


def _load_card_pool(
    database: Path,
    card_type: str,
    effect_priority: dict[str, int],
) -> list[dict[str, str]]:
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT card.card_code, MIN(printing.card_id) AS card_id
            FROM gameplay_cards AS card
            JOIN card_printings AS printing
              ON printing.gameplay_card_id = card.id
            WHERE card.card_type = ?
            GROUP BY card.card_code
            ORDER BY card.card_code
            """,
            (card_type,),
        ).fetchall()
    pool = [{"card_code": str(row["card_code"]), "card_id": str(row["card_id"])} for row in rows]
    return sorted(
        pool,
        key=lambda item: (
            -effect_priority.get(item["card_code"], 0),
            item["card_code"],
        ),
    )


def _window(items: list[dict[str, str]], start: int, size: int) -> list[dict[str, str]]:
    return [items[(start + offset) % len(items)] for offset in range(size)]


if __name__ == "__main__":
    raise SystemExit(main())
