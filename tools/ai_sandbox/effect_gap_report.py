"""Rank remaining manual-resolution effects for Phase 5 planning.

This report is intentionally conservative.  It does not create registry entries
or infer executable semantics.  It groups existing registry entries that are
still marked ``manual_resolution`` so the next exact-text implementation pass can
start from the highest-impact remaining patterns.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from loveca.simulation.effects import (
    DEFAULT_EFFECT_REGISTRY,
    EffectDefinition,
    load_effect_registry,
)

GAP_REPORT_SCHEMA_VERSION = "effect_gap_report_v0.2"


@dataclass
class EffectGapGroup:
    pattern_id: str
    count: int
    trigger: str
    timing: str
    effect_type: str
    frequency_limit: str
    label_ja: str
    card_types: dict[str, int]
    sample_effect_ids: list[str]
    sample_card_codes: list[str]
    actual_trigger_count: int
    unresolved_reason: str
    suggested_next_step: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rank manual-resolution effect patterns for Phase 5 planning."
    )
    parser.add_argument("--database", type=Path, default=Path("data/loveca.sqlite3"))
    parser.add_argument("--registry", type=Path, default=DEFAULT_EFFECT_REGISTRY)
    parser.add_argument("--output", type=Path, default=Path("logs/effect_gap_report"))
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument(
        "--sandbox-summary",
        type=Path,
        action="append",
        default=[],
        help=(
            "Optional blackbox sandbox-summary.json. May be supplied more than once; "
            "skipped effect counts are combined and used as observed trigger frequency."
        ),
    )
    args = parser.parse_args()

    report = build_effect_gap_report(
        registry_path=args.registry,
        database_path=args.database,
        actual_trigger_counts=load_actual_trigger_counts(args.sandbox_summary),
        top=max(1, args.top),
    )
    write_gap_outputs(args.output, report)
    print(f"Wrote effect gap report to {args.output / 'effect-gap-report.md'}")
    return 0


def build_effect_gap_report(
    *,
    registry_path: Path = DEFAULT_EFFECT_REGISTRY,
    database_path: Path | None = None,
    actual_trigger_counts: dict[str, int] | None = None,
    top: int = 50,
) -> dict[str, Any]:
    registry = load_effect_registry(registry_path)
    card_types = load_card_types(database_path) if database_path else {}
    manual_effects = [
        effect for effect in registry.effects if effect.simulation_support == "manual_resolution"
    ]
    executable_effects = [
        effect
        for effect in registry.effects
        if effect.simulation_support == "test_validated_executable"
    ]
    observed_counts = actual_trigger_counts or {}
    groups = group_manual_effects(manual_effects, card_types, observed_counts)
    trigger_counts = Counter(effect.trigger for effect in manual_effects)
    timing_counts = Counter(effect.timing for effect in manual_effects)
    card_type_counts = Counter(card_types.get(effect.card_code, "unknown") for effect in manual_effects)
    return {
        "schema_version": GAP_REPORT_SCHEMA_VERSION,
        "registry_path": str(registry_path),
        "database_path": str(database_path) if database_path else None,
        "total_effects": len(registry.effects),
        "test_validated_executable": len(executable_effects),
        "manual_resolution": len(manual_effects),
        "rough_executable_coverage": (
            len(executable_effects) / len(registry.effects) if registry.effects else 0.0
        ),
        "manual_by_trigger": dict(trigger_counts.most_common()),
        "manual_by_timing": dict(timing_counts.most_common()),
        "manual_by_card_type": dict(card_type_counts.most_common()),
        "actual_trigger_samples": sum(observed_counts.values()),
        "top_manual_patterns": [asdict(group) for group in groups[:top]],
    }


def load_actual_trigger_counts(summary_paths: list[Path]) -> dict[str, int]:
    """Combine observed skipped-effect counts from deterministic sandbox reports."""

    counts: Counter[str] = Counter()

    def add_skipped_items(items: object, *, source: Path) -> None:
        if not isinstance(items, list):
            raise ValueError(f"{source}: skipped_effects must be an array")
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("effect_id"), str):
                raise ValueError(f"{source}: invalid skipped effect item")
            counts[item["effect_id"]] += 1

    for path in summary_paths:
        if path.suffix == ".jsonl":
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                add_skipped_items(payload.get("skipped_effects", []), source=path)
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            for match in payload:
                if not isinstance(match, dict):
                    raise ValueError(f"{path}: match summaries must be objects")
                add_skipped_items(match.get("skipped_effects", []), source=path)
            continue
        summary = payload.get("summary", payload)
        skipped = summary.get("skipped_effects", {}) if isinstance(summary, dict) else {}
        if not isinstance(skipped, dict):
            raise ValueError(f"{path}: skipped_effects must be an object")
        for effect_id, count in skipped.items():
            if not isinstance(effect_id, str) or not isinstance(count, int) or count < 0:
                raise ValueError(
                    f"{path}: skipped_effects must map effect IDs to non-negative integers"
                )
            counts[effect_id] += count
    return dict(counts)


def load_card_types(database_path: Path | None) -> dict[str, str]:
    if database_path is None or not database_path.exists():
        return {}
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT card_code, card_type FROM gameplay_cards"
        ).fetchall()
    return {str(card_code): str(card_type) for card_code, card_type in rows}


def group_manual_effects(
    effects: list[EffectDefinition],
    card_types: dict[str, str],
    actual_trigger_counts: dict[str, int] | None = None,
) -> list[EffectGapGroup]:
    observed_counts = actual_trigger_counts or {}
    grouped: dict[tuple[str, str, str, str, str], list[EffectDefinition]] = defaultdict(list)
    for effect in effects:
        grouped[
            (
                effect.trigger,
                effect.timing,
                effect.effect_type,
                effect.frequency_limit,
                normalize_label(effect.label_ja),
            )
        ].append(effect)
    groups: list[EffectGapGroup] = []
    for key, items in grouped.items():
        trigger, timing, effect_type, frequency_limit, label_ja = key
        sorted_items = sorted(items, key=lambda effect: effect.effect_id)
        card_type_counts = Counter(
            card_types.get(effect.card_code, "unknown") for effect in sorted_items
        )
        groups.append(
            EffectGapGroup(
                pattern_id=pattern_id_for_key(key),
                count=len(sorted_items),
                trigger=trigger,
                timing=timing,
                effect_type=effect_type,
                frequency_limit=frequency_limit,
                label_ja=label_ja,
                card_types=dict(card_type_counts.most_common()),
                sample_effect_ids=[effect.effect_id for effect in sorted_items[:8]],
                sample_card_codes=[effect.card_code for effect in sorted_items[:8]],
                actual_trigger_count=sum(
                    observed_counts.get(effect.effect_id, 0) for effect in sorted_items
                ),
                unresolved_reason=classify_unresolved_reason(
                    trigger,
                    timing,
                    label_ja,
                ),
                suggested_next_step=suggest_next_step(trigger, timing, label_ja),
            )
        )
    return sorted(
        groups,
        key=lambda group: (
            -group.actual_trigger_count,
            -group.count,
            priority_for_trigger(group.trigger, group.timing),
            group.label_ja,
            group.pattern_id,
        ),
    )


def classify_unresolved_reason(trigger: str, timing: str, label_ja: str) -> str:
    """Return a controlled reason instead of implying every manual effect is forgotten work."""

    if trigger == "static_always" or timing == "static" or "【常時】" in label_ja:
        if "能力" in label_ja and ("発動" in label_ja or "得る" in label_ja):
            return "nested_or_inherited_effect_invocation_not_modeled"
        return "continuous_or_inherited_rule_evaluation_not_modeled"
    if "能力" in label_ja and ("発動" in label_ja or "すべて得る" in label_ja):
        return "nested_or_inherited_effect_invocation_not_modeled"
    if "相手" in label_ja and any(
        token in label_ja for token in ("手札", "選ぶ", "見る", "公開")
    ):
        return "opponent_or_private_information_choice_requires_structured_remote_choice"
    if any(token in label_ja for token in ("フォーメーション", "ポジションチェンジ")):
        return "formation_or_cross_player_position_choice_requires_multi_step_choice"
    if trigger in {"yell_card_revealed", "auto_triggered_event"} or "応援" in label_ja:
        return "event_history_or_yell_context_not_yet_structured"
    if any(token in label_ja for token in ("繰り返", "そのたび", "好きな回数", "まで行う")):
        return "repeated_or_variable_multi_stage_resolution_not_yet_structured"
    if "両方" in label_ja or "お互い" in label_ja:
        return "both_player_resolution_requires_ordered_multi_player_choice"
    return "exact_text_executor_not_yet_rules_reviewed"


def normalize_label(label: str) -> str:
    return "\n".join(line.strip() for line in label.strip().splitlines() if line.strip())


def pattern_id_for_key(key: tuple[str, str, str, str, str]) -> str:
    raw = "\x1f".join(key).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


def priority_for_trigger(trigger: str, timing: str) -> int:
    if trigger in {"member_played", "live_started", "live_succeeded", "player_activation"}:
        return 0
    if timing in {"on_play", "live_start", "live_success", "activated"}:
        return 1
    if trigger == "static_always":
        return 5
    return 3


def suggest_next_step(trigger: str, timing: str, label_ja: str) -> str:
    if "相手" in label_ja and ("選ぶ" in label_ja or "見る" in label_ja):
        return "opponent_or_private_choice_review"
    if trigger == "member_played" or timing == "on_play":
        return "on_play_exact_text_executor_candidate"
    if trigger == "live_started" or timing == "live_start":
        return "live_start_modifier_or_choice_candidate"
    if trigger == "live_succeeded" or timing == "live_success":
        return "live_success_reveal_score_or_draw_candidate"
    if trigger == "player_activation" or timing == "activated":
        return "activated_effect_choice_or_cost_candidate"
    if trigger == "static_always":
        return "static_or_continuous_rules_review"
    return "manual_pattern_review"


def write_gap_outputs(output: Path, report: dict[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "effect-gap-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Effect Gap Report",
        "",
        "## Scope",
        "",
        "* Groups existing `manual_resolution` registry entries by exact Japanese label and timing.",
        "* Does not infer executable semantics or mutate `effect-registry.v0.json`.",
        "* Use this as the next Phase 5 planning input after sandbox/API Play reports.",
        "",
        "## Summary",
        "",
        f"* Total registry entries: `{report['total_effects']}`",
        f"* Test-validated executable: `{report['test_validated_executable']}`",
        f"* Manual resolution: `{report['manual_resolution']}`",
        f"* Rough executable coverage: `{report['rough_executable_coverage']:.2%}`",
        f"* Manual by trigger: `{report['manual_by_trigger']}`",
        f"* Manual by card type: `{report['manual_by_card_type']}`",
        f"* Observed skipped triggers: `{report.get('actual_trigger_samples', 0)}`",
        "",
        "## Top Manual Patterns",
        "",
        "| Observed | Count | Pattern | Trigger | Timing | Types | Unresolved reason | Suggested next step | Samples | Label JA |",
        "|---:|---:|---|---|---|---|---|---|---|---|",
    ]
    for group in report["top_manual_patterns"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(group.get("actual_trigger_count", 0)),
                    str(group["count"]),
                    f"`{group['pattern_id']}`",
                    f"`{group['trigger']}`",
                    f"`{group['timing']}`",
                    _markdown_cell(group["card_types"]),
                    f"`{group['unresolved_reason']}`",
                    f"`{group['suggested_next_step']}`",
                    _markdown_cell(", ".join(group["sample_effect_ids"])),
                    _markdown_cell(group["label_ja"]),
                ]
            )
            + " |"
        )
    (output / "effect-gap-report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


if __name__ == "__main__":
    raise SystemExit(main())
