"""Generate rule-audit packs from deterministic sandbox matches.

This tool is a bridge between the deterministic sandbox and human/Codex rule
review.  It does not try to make smarter play decisions.  Instead, it records a
compact, replay-oriented timeline that another reviewer can audit against the
official comprehensive rules.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from loveca.decks.analyzer import DeckList
from loveca.simulation.engine import IllegalActionError, generate_legal_actions
from loveca.simulation.models import ActionRequest, GameEvent, LegalAction, MatchState
from loveca.simulation.service import MatchService
from tools.ai_sandbox.blackbox_playtest import (
    build_decks,
    choose_action,
    classify_blocker,
    diagnose_max_actions,
    describe_state,
    summarize_deck,
)
from tools.ai_sandbox.semantic_playtest import DEFAULT_RULES_PDF, RuleContext, load_rule_context

AUDIT_SCHEMA_VERSION = "rules_audit_pack_v0.1"
FOCUS_EVENT_TYPES = {
    "baton_touch_performed",
    "effect_auto_resolved",
    "effect_cost_paid",
    "effect_declined",
    "effect_not_activatable",
    "effect_resolved",
    "effect_skipped_due_to_error",
    "effect_triggered",
    "live_judgment_completed",
    "live_started",
    "manual_adjustment_applied",
    "special_blade_heart_resolved",
}


@dataclass
class AuditStep:
    action_index: int
    phase_before: str
    turn_before: int
    revision_before: int
    active_player_before: str | None
    legal_action_types: list[str]
    chosen_action_type: str | None
    chosen_player_id: str | None
    success_live_counts_before: dict[str, int] = field(default_factory=dict)
    chosen_payload: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    phase_after: str | None = None
    turn_after: int | None = None
    revision_after: int | None = None
    active_player_after: str | None = None
    success_live_counts_after: dict[str, int] = field(default_factory=dict)
    pending_choice_after: str | None = None
    pending_effects_after: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


@dataclass
class AuditMatch:
    match_index: int
    match_id: str
    first_deck: str
    second_deck: str
    seed: int
    status: str
    final_phase: str
    turn_number: int
    action_count: int
    blocker: str | None = None
    blocker_detail: dict[str, Any] = field(default_factory=dict)
    success_live_counts: dict[str, int] = field(default_factory=dict)
    event_counts: dict[str, int] = field(default_factory=dict)
    skipped_effects: list[dict[str, Any]] = field(default_factory=list)
    notable_steps: list[AuditStep] = field(default_factory=list)
    timeline: list[AuditStep] = field(default_factory=list)


@dataclass
class AuditPack:
    schema_version: str
    database_path: str
    rule_context: RuleContext
    manual_policy: str
    max_actions: int
    deck_summaries: list[dict[str, Any]]
    matches: list[AuditMatch]
    blocker_counts: dict[str, int]
    event_counts: dict[str, int]
    skipped_effect_counts: dict[str, int]
    audit_questions: list[str]


def build_rules_audit_pack(
    database: Path,
    *,
    decks: int,
    loops: int,
    max_actions: int,
    manual_policy: str,
    rules_pdf: Path,
    rule_context_chars: int,
) -> AuditPack:
    decklists = build_decks(database, decks)
    deck_summaries = [asdict(summarize_deck(database, deck)) for deck in decklists]
    rule_context = load_rule_context(rules_pdf, max_chars=rule_context_chars)
    matches = run_audit_matches(
        database,
        decklists,
        match_count=loops,
        max_actions=max_actions,
        manual_policy=manual_policy,
    )
    blocker_counts = Counter(item.blocker or "none" for item in matches)
    event_counts: Counter[str] = Counter()
    skipped_effect_counts: Counter[str] = Counter()
    for item in matches:
        event_counts.update(item.event_counts)
        skipped_effect_counts.update(
            skipped.get("effect_id", "(unknown)") for skipped in item.skipped_effects
        )
    return AuditPack(
        schema_version=AUDIT_SCHEMA_VERSION,
        database_path=str(database),
        rule_context=rule_context,
        manual_policy=manual_policy,
        max_actions=max_actions,
        deck_summaries=deck_summaries,
        matches=matches,
        blocker_counts=dict(sorted(blocker_counts.items())),
        event_counts=dict(sorted(event_counts.items())),
        skipped_effect_counts=dict(skipped_effect_counts.most_common(50)),
        audit_questions=_audit_questions(),
    )


def run_audit_matches(
    database: Path,
    decks: list[DeckList],
    *,
    match_count: int,
    max_actions: int,
    manual_policy: str,
) -> list[AuditMatch]:
    results: list[AuditMatch] = []
    with tempfile.TemporaryDirectory(prefix="loveca-rules-audit-") as tmp:
        service = MatchService(database, Path(tmp) / "matches.sqlite3")
        for index in range(match_count):
            first = decks[index % len(decks)]
            second = decks[(index * 7 + 3) % len(decks)]
            seed = 91000 + index
            match_id = f"rules-audit-{index + 1:02d}"
            created = service.create_match(
                first_name="Audit A",
                first_deck=first,
                second_name="Audit B",
                second_deck=second,
                seed=seed,
                match_id=match_id,
            )
            state = created.state
            event_counts: Counter[str] = Counter(event.event_type for event in created.events)
            skipped_effects = [
                dict(event.data)
                for event in created.events
                if event.event_type == "effect_skipped_due_to_error"
            ]
            timeline: list[AuditStep] = []
            notable_steps: list[AuditStep] = [
                _system_step(0, created.events, state, "create_match")
            ]
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
                step = _step_before(actions + 1, state, legal_actions, action_type, player_id, payload)
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
                    step.error = str(exc)
                    blocker_detail = {
                        **describe_state(state, legal_actions),
                        "attempted_action": action_type,
                        "attempted_payload": _compact(payload),
                        "error": str(exc),
                    }
                    timeline.append(step)
                    notable_steps.append(step)
                    break
                state = applied.state
                actions += 1
                _fill_step_after(step, applied.events, state)
                timeline.append(step)
                if _is_notable_step(step):
                    notable_steps.append(step)
                event_counts.update(event.event_type for event in applied.events)
                skipped_effects.extend(
                    dict(event.data)
                    for event in applied.events
                    if event.event_type == "effect_skipped_due_to_error"
                )
            if actions >= max_actions and state.phase != "complete":
                legal_actions = generate_legal_actions(state)
                diagnosis = diagnose_max_actions(state, legal_actions)
                blocker = f"max_actions:{diagnosis['reason']}"
                blocker_detail = {
                    **describe_state(state, legal_actions),
                    "max_action_diagnosis": diagnosis,
                }
            results.append(
                AuditMatch(
                    match_index=index + 1,
                    match_id=match_id,
                    first_deck=first.name or "(unnamed)",
                    second_deck=second.name or "(unnamed)",
                    seed=seed,
                    status="completed" if state.phase == "complete" else "blocked",
                    final_phase=state.phase,
                    turn_number=state.turn_number,
                    action_count=actions,
                    blocker=blocker,
                    blocker_detail=_compact(blocker_detail),
                    success_live_counts={
                        player_id: len(player.success_live_area)
                        for player_id, player in state.players.items()
                    },
                    event_counts=dict(sorted(event_counts.items())),
                    skipped_effects=[_compact(item) for item in skipped_effects],
                    notable_steps=notable_steps,
                    timeline=timeline,
                )
            )
    return results


def write_audit_pack(output: Path, pack: AuditPack) -> None:
    output.mkdir(parents=True, exist_ok=True)
    payload = asdict(pack)
    (output / "audit-pack.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "audit-pack.md").write_text(
        _render_markdown(pack),
        encoding="utf-8",
    )


def _system_step(index: int, events: list[GameEvent], state: MatchState, label: str) -> AuditStep:
    step = AuditStep(
        action_index=index,
        phase_before=label,
        turn_before=state.turn_number,
        revision_before=max(0, state.revision - 1),
        active_player_before=None,
        legal_action_types=[],
        chosen_action_type=label,
        chosen_player_id=None,
        success_live_counts_before={
            player_id: len(player.success_live_area)
            for player_id, player in state.players.items()
        },
    )
    _fill_step_after(step, events, state)
    return step


def _step_before(
    index: int,
    state: MatchState,
    legal_actions: list[LegalAction],
    action_type: str,
    player_id: str | None,
    payload: dict[str, Any],
) -> AuditStep:
    return AuditStep(
        action_index=index,
        phase_before=state.phase,
        turn_before=state.turn_number,
        revision_before=state.revision,
        active_player_before=state.active_player_id,
        legal_action_types=[action.action_type for action in legal_actions],
        chosen_action_type=action_type,
        chosen_player_id=player_id,
        success_live_counts_before={
            player_id: len(player.success_live_area)
            for player_id, player in state.players.items()
        },
        chosen_payload=_compact(payload),
    )


def _fill_step_after(step: AuditStep, events: list[GameEvent], state: MatchState) -> None:
    step.events = [_compact_event(event) for event in events]
    step.phase_after = state.phase
    step.turn_after = state.turn_number
    step.revision_after = state.revision
    step.active_player_after = state.active_player_id
    step.success_live_counts_after = {
        player_id: len(player.success_live_area)
        for player_id, player in state.players.items()
    }
    step.pending_choice_after = state.pending_choice.choice_type if state.pending_choice else None
    step.pending_effects_after = [
        {
            "invocation_id": item.invocation_id,
            "effect_id": item.effect_id,
            "source_card_instance_id": item.source_card_instance_id,
            "player_id": item.player_id,
            "trigger_event": item.trigger_event,
            "resolution_stage": item.resolution_stage,
        }
        for item in state.pending_effects[:5]
    ]


def _compact_event(event: GameEvent) -> dict[str, Any]:
    return {
        "event_type": event.event_type,
        "player_id": event.player_id,
        "source": event.source,
        "data": _compact(event.data),
    }


def _compact(value: Any, *, depth: int = 0) -> Any:
    if depth >= 5:
        return "..."
    if isinstance(value, dict):
        return {
            str(key): _compact(item, depth=depth + 1)
            for key, item in value.items()
            if key not in {"state_json", "current_state_json", "initial_state_json"}
        }
    if isinstance(value, list):
        compacted = [_compact(item, depth=depth + 1) for item in value[:12]]
        if len(value) > 12:
            compacted.append(f"... +{len(value) - 12} more")
        return compacted
    if isinstance(value, tuple):
        return [_compact(item, depth=depth + 1) for item in value[:12]]
    if isinstance(value, str) and len(value) > 500:
        return value[:500] + f"... <truncated {len(value) - 500} chars>"
    return value


def _is_notable_step(step: AuditStep) -> bool:
    if step.error:
        return True
    if step.pending_choice_after or step.pending_effects_after:
        return True
    if step.chosen_action_type in {
        "resolve_effect",
        "resolve_effect_choice",
        "skip_effect",
        "manual_adjustment",
        "resolve_live_requirements",
        "set_live_cards",
        "play_member",
        "start_next_turn",
    }:
        return True
    return any(event.get("event_type") in FOCUS_EVENT_TYPES for event in step.events)


def _audit_questions() -> list[str]:
    return [
        "総合ルール ver.1.06 と照合し、Live カードセット、公開情報、控室、成功 Live の扱いに矛盾がないか確認する。",
        "バトンタッチ後の再バトンタッチ制限、同名条件、コスト軽減が公式ルールとカード文面に合っているか確認する。",
        "自動解決された効果について、ユーザーに見える確認イベントが不足していないか確認する。",
        "skip_effect が出た場合、その効果は manual tool で人間が安全に処理できるか、または構造化 executor が必要か分類する。",
        "sandbox の行動選択が実際のプレイヤーとして不自然すぎて、ルール不具合検出を妨げていないか確認する。",
    ]


def _render_markdown(pack: AuditPack) -> str:
    completed = sum(item.status == "completed" for item in pack.matches)
    lines = [
        "# ルール監査用 Sandbox Pack",
        "",
        "## Scope",
        "",
        f"- Schema: `{pack.schema_version}`",
        f"- Database: `{pack.database_path}`",
        f"- Matches: `{len(pack.matches)}`",
        f"- Manual policy: `{pack.manual_policy}`",
        f"- Max actions: `{pack.max_actions}`",
        f"- Completed: `{completed}/{len(pack.matches)}`",
        "",
        "## Rule Context",
        "",
        f"- Source: `{pack.rule_context.source_path}`",
        f"- Loaded: `{pack.rule_context.loaded}`",
        f"- Extractor: `{pack.rule_context.extractor}`",
        f"- Characters: `{pack.rule_context.char_count}`",
    ]
    if pack.rule_context.error:
        lines.append(f"- Error: `{pack.rule_context.error}`")
    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- Blockers: `{pack.blocker_counts}`",
            f"- Top skipped effects: `{pack.skipped_effect_counts}`",
            "",
            "## Audit Questions",
            "",
        ]
    )
    lines.extend(f"- {question}" for question in pack.audit_questions)
    lines.extend(
        [
            "",
            "## Match Results",
            "",
            "| # | Status | Decks | Phase | Turn | Actions | Success Live | Blocker |",
            "|---:|---|---|---|---:|---:|---|---|",
        ]
    )
    for item in pack.matches:
        success_counts = ", ".join(
            f"{player}:{count}" for player, count in sorted(item.success_live_counts.items())
        )
        lines.append(
            f"| {item.match_index} | {item.status} | "
            f"{_md(item.first_deck)} vs {_md(item.second_deck)} | "
            f"{item.final_phase} | {item.turn_number} | {item.action_count} | "
            f"{success_counts} | {item.blocker or ''} |"
        )
    lines.extend(["", "## Notable Timeline", ""])
    for item in pack.matches:
        lines.extend(
            [
                f"### Match {item.match_index}: {_md(item.first_deck)} vs {_md(item.second_deck)}",
                "",
                f"- Final: `{item.status}` / `{item.final_phase}` / blocker `{item.blocker or 'none'}`",
                "",
                "| Step | Action | Phase | Events | Pending | Error |",
                "|---:|---|---|---|---|---|",
            ]
        )
        for step in item.notable_steps[:40]:
            event_types = "; ".join(_event_summary(event) for event in step.events[:8])
            pending = step.pending_choice_after or ""
            if step.pending_effects_after:
                pending = (
                    pending
                    + " "
                    + ", ".join(
                        f"{effect['effect_id']}@{effect.get('source_card_instance_id', '')}"
                        for effect in step.pending_effects_after[:3]
                    )
                ).strip()
            lines.append(
                f"| {step.action_index} | {step.chosen_action_type or ''} | "
                f"{step.phase_before} -> {step.phase_after} | "
                f"{_md(event_types)} | {_md(pending)} | {_md(step.error or '')} |"
            )
        if len(item.notable_steps) > 40:
            lines.append(f"| ... | ... | ... | ... | ... | +{len(item.notable_steps) - 40} more |")
        lines.append("")
        if item.blocker and item.blocker.startswith("max_actions"):
            lines.extend(
                [
                    "**Max-action tail**",
                    "",
                    "| Step | Action | Phase | Events | Success Live |",
                    "|---:|---|---|---|---|",
                ]
            )
            for step in item.timeline[-12:]:
                event_types = "; ".join(_event_summary(event) for event in step.events[:5])
                lines.append(
                    f"| {step.action_index} | {step.chosen_action_type or ''} | "
                    f"{step.phase_before} -> {step.phase_after} | "
                    f"{_md(event_types)} | {step.success_live_counts_after} |"
                )
            lines.append("")
    lines.extend(
        [
            "## Reviewer Instructions",
            "",
            "- `audit-pack.json` contains the compact full timeline for each match.",
            "- Please cite match number, step number, official rule section if available, and suspected fix direction.",
            "- Do not count agent/manual recovery as executable registry coverage.",
            "",
        ]
    )
    return "\n".join(lines)


def _md(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _event_summary(event: dict[str, Any]) -> str:
    event_type = event.get("event_type", "")
    data = event.get("data") or {}
    player_id = event.get("player_id")
    if event_type == "live_judgment_started":
        return (
            f"{event_type}(basis={data.get('basis')}, "
            f"winners={data.get('winner_ids')}, scores={data.get('scores')})"
        )
    if event_type == "success_live_selected":
        return f"{event_type}({player_id}:{data.get('card_instance_id')})"
    if event_type == "baton_touch_performed":
        return (
            f"{event_type}(slot={data.get('slot')}, "
            f"replaced={data.get('replaced_card_instance_id')}, "
            f"payment={data.get('payment_cost')})"
        )
    if event_type == "member_played":
        return (
            f"{event_type}({data.get('card_instance_id')} "
            f"slot={data.get('slot')} baton={data.get('baton_touch')})"
        )
    if event_type in {
        "effect_triggered",
        "effect_resolved",
        "effect_auto_resolved",
        "effect_declined",
        "effect_not_activatable",
        "effect_cost_paid",
        "effect_choice_started",
        "effect_skipped_due_to_error",
    }:
        detail = (
            f"{data.get('effect_id')}@{data.get('source_card_instance_id')}"
            if data.get("effect_id")
            else ""
        )
        if data.get("reason"):
            detail = f"{detail} reason={data.get('reason')}".strip()
        return f"{event_type}({detail})"
    if event_type == "live_requirements_resolved":
        return f"{event_type}({player_id})"
    if event_type == "live_cards_revealed":
        return f"{event_type}({player_id})"
    return event_type


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/loveca.sqlite3"))
    parser.add_argument("--output", type=Path, default=Path("logs/rules_audit/latest"))
    parser.add_argument("--decks", type=int, default=10)
    parser.add_argument("--loops", type=int, default=10)
    parser.add_argument("--max-actions", type=int, default=180)
    parser.add_argument("--manual-policy", choices=["block", "noop", "skip"], default="skip")
    parser.add_argument("--rules-pdf", type=Path, default=DEFAULT_RULES_PDF)
    parser.add_argument("--rule-context-chars", type=int, default=16000)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    pack = build_rules_audit_pack(
        args.database,
        decks=args.decks,
        loops=args.loops,
        max_actions=args.max_actions,
        manual_policy=args.manual_policy,
        rules_pdf=args.rules_pdf,
        rule_context_chars=args.rule_context_chars,
    )
    write_audit_pack(args.output, pack)
    print(f"Wrote rules audit pack to {args.output}")
    print(f"Blockers: {pack.blocker_counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
