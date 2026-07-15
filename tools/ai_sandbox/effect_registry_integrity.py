"""Audit effect registry bindings against local official Japanese card text."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from loveca.simulation.effect_candidates import (
    EffectCandidate,
    _timing_segments_with_markers,
    discover_effect_candidates,
)
from loveca.simulation.effects import (
    DEFAULT_EFFECT_REGISTRY,
    EffectDefinition,
    load_effect_registry,
)

DEFAULT_DATABASE = Path("data/loveca.sqlite3")
DEFAULT_OUTPUT = Path("logs/effect_registry_integrity")
SCHEMA_VERSION = "effect_registry_integrity_v0.1"

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class IntegrityIssue:
    severity: Severity
    code: str
    effect_id: str
    card_code: str
    message: str
    expected: Any = None
    actual: Any = None


@dataclass(frozen=True)
class IntegrityResult:
    registry_effect_count: int
    candidate_count: int
    executable_count: int
    manual_count: int
    issues: tuple[IntegrityIssue, ...]

    @property
    def error_count(self) -> int:
        return sum(issue.severity == "error" for issue in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(issue.severity == "warning" for issue in self.issues)


@dataclass(frozen=True)
class SourceRevision:
    card_code: str
    text_revision_id: int
    raw_text_hash: str
    raw_effect_text_ja: str


_MARKER_SEMANTICS: dict[str, tuple[str, str, str, str]] = {
    "【登場】": ("triggered", "on_play", "member_played", "none"),
    "【起動】": ("activated", "activated_main", "player_activation", "none"),
    "【ライブ開始時】": (
        "triggered",
        "live_start",
        "live_started",
        "once_per_live",
    ),
    "【ライブ成功時】": (
        "triggered",
        "live_success",
        "live_succeeded",
        "once_per_live",
    ),
    "【自動】": ("triggered", "auto_triggered_event", "auto_triggered_event", "none"),
    "【常時】": ("static", "static_always", "static_always", "none"),
    "【バトンタッチ時】": (
        "triggered",
        "baton_touch",
        "baton_touch_performed",
        "none",
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--registry", type=Path, default=DEFAULT_EFFECT_REGISTRY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return a non-zero exit status when integrity errors remain.",
    )
    args = parser.parse_args()

    result = audit_effect_registry(args.database, args.registry)
    write_integrity_report(args.output, result)
    print(
        "Effect registry integrity: "
        f"{result.error_count} errors, {result.warning_count} warnings, "
        f"{result.registry_effect_count} effects"
    )
    return 1 if args.strict and result.error_count else 0


def audit_effect_registry(
    database_path: Path,
    registry_path: Path = DEFAULT_EFFECT_REGISTRY,
) -> IntegrityResult:
    registry = load_effect_registry(registry_path)
    revisions = _load_source_revisions(database_path)
    revisions_by_identity = {
        (item.card_code, item.text_revision_id, item.raw_text_hash): item
        for item in revisions
    }
    revisions_by_card_hash: dict[tuple[str, str], list[SourceRevision]] = {}
    revisions_by_card_id: dict[tuple[str, int], list[SourceRevision]] = {}
    for item in revisions:
        revisions_by_card_hash.setdefault(
            (item.card_code, item.raw_text_hash), []
        ).append(item)
        revisions_by_card_id.setdefault(
            (item.card_code, item.text_revision_id), []
        ).append(item)

    candidates = discover_effect_candidates(
        database_path,
        registry_path=registry_path,
        include_registered=True,
    )
    candidates_by_id = {candidate.effect_id: candidate for candidate in candidates}
    issues: list[IntegrityIssue] = []
    identities: dict[tuple[str, str, int], str] = {}

    for effect in registry.effects:
        identity = (effect.card_code, effect.raw_text_hash, effect.effect_index)
        previous_effect_id = identities.get(identity)
        if previous_effect_id is not None:
            issues.append(
                _issue(
                    effect,
                    "duplicate_effect_identity",
                    "Multiple effect IDs bind the same source segment.",
                    expected=previous_effect_id,
                    actual=effect.effect_id,
                )
            )
        else:
            identities[identity] = effect.effect_id

        source_identity = (
            effect.card_code,
            effect.text_revision_id,
            effect.raw_text_hash,
        )
        source = revisions_by_identity.get(source_identity)
        if source is None:
            issues.extend(
                _source_binding_issues(
                    effect,
                    revisions_by_card_hash,
                    revisions_by_card_id,
                )
            )
        else:
            issues.extend(_source_segment_issues(effect, source))

        if re.search(r"\?{3,}", effect.label_ja):
            issues.append(
                _issue(
                    effect,
                    "mojibake_label",
                    "Japanese effect label contains a run of replacement question marks.",
                    actual=effect.label_ja,
                )
            )

        candidate = candidates_by_id.get(effect.effect_id)
        if candidate is None:
            issues.append(
                _issue(
                    effect,
                    "candidate_missing",
                    "Candidate discovery cannot reproduce this effect identity.",
                )
            )
        else:
            issues.extend(_candidate_binding_issues(effect, candidate))

    executable_count = sum(
        effect.simulation_support == "test_validated_executable"
        for effect in registry.effects
    )
    return IntegrityResult(
        registry_effect_count=len(registry.effects),
        candidate_count=len(candidates),
        executable_count=executable_count,
        manual_count=len(registry.effects) - executable_count,
        issues=tuple(
            sorted(
                issues,
                key=lambda item: (
                    0 if item.severity == "error" else 1,
                    item.card_code,
                    item.effect_id,
                    item.code,
                ),
            )
        ),
    )


def _load_source_revisions(database_path: Path) -> list[SourceRevision]:
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT card.card_code, revision.id AS text_revision_id,
                   revision.raw_text_hash, revision.raw_effect_text_ja
            FROM gameplay_cards AS card
            JOIN card_text_revisions AS revision
              ON revision.gameplay_card_id = card.id
            WHERE revision.raw_effect_text_ja IS NOT NULL
              AND length(trim(revision.raw_effect_text_ja)) > 0
            ORDER BY card.card_code, revision.id
            """
        ).fetchall()
    return [
        SourceRevision(
            card_code=str(row["card_code"]),
            text_revision_id=int(row["text_revision_id"]),
            raw_text_hash=str(row["raw_text_hash"]),
            raw_effect_text_ja=str(row["raw_effect_text_ja"]).strip(),
        )
        for row in rows
    ]


def _source_binding_issues(
    effect: EffectDefinition,
    revisions_by_card_hash: dict[tuple[str, str], list[SourceRevision]],
    revisions_by_card_id: dict[tuple[str, int], list[SourceRevision]],
) -> list[IntegrityIssue]:
    same_hash = revisions_by_card_hash.get((effect.card_code, effect.raw_text_hash), [])
    if same_hash:
        return [
            _issue(
                effect,
                "text_revision_id_mismatch",
                "The hash exists for this card, but the bound text revision ID is stale.",
                expected=[item.text_revision_id for item in same_hash],
                actual=effect.text_revision_id,
            )
        ]
    same_id = revisions_by_card_id.get((effect.card_code, effect.text_revision_id), [])
    if same_id:
        return [
            _issue(
                effect,
                "raw_text_hash_mismatch",
                "The text revision exists, but its raw text hash differs.",
                expected=[item.raw_text_hash for item in same_id],
                actual=effect.raw_text_hash,
            )
        ]
    return [
        _issue(
            effect,
            "source_revision_missing",
            "No local official text revision matches this registry binding.",
            actual={
                "text_revision_id": effect.text_revision_id,
                "raw_text_hash": effect.raw_text_hash,
            },
        )
    ]


def _source_segment_issues(
    effect: EffectDefinition,
    source: SourceRevision,
) -> list[IntegrityIssue]:
    segments = {
        effect_index: (marker, label)
        for effect_index, marker, label in _timing_segments_with_markers(
            source.raw_effect_text_ja
        )
    }
    segment = segments.get(effect.effect_index)
    if segment is None:
        return [
            _issue(
                effect,
                "effect_index_missing",
                "The bound effect index does not exist in the source revision.",
                expected=sorted(segments),
                actual=effect.effect_index,
            )
        ]
    marker, label = segment
    issues: list[IntegrityIssue] = []
    if effect.label_ja != label:
        issues.append(
            _issue(
                effect,
                "label_mismatch",
                "Registry label is not the exact official Japanese source segment.",
                expected=label,
                actual=effect.label_ja,
            )
        )
    effect_type, timing, trigger, frequency = _MARKER_SEMANTICS[marker]
    comparisons: list[tuple[str, Any, Any]] = [("effect_type", effect_type, effect.effect_type)]
    if marker != "【自動】":
        comparisons.extend(
            [
                ("timing", timing, effect.timing),
                ("trigger", trigger, effect.trigger),
            ]
        )
    if "【ターン1回】" in label:
        frequency = "once_per_turn"
    elif "【ターン2回】" in label:
        frequency = "twice_per_turn"
    if marker != "【自動】" or "【ターン1回】" in label:
        comparisons.append(("frequency_limit", frequency, effect.frequency_limit))
    for field_name, expected, actual in comparisons:
        if expected != actual:
            issues.append(
                _issue(
                    effect,
                    f"{field_name}_mismatch",
                    f"Registry {field_name} disagrees with the source timing marker.",
                    expected=expected,
                    actual=actual,
                )
            )
    return issues


def _candidate_binding_issues(
    effect: EffectDefinition,
    candidate: EffectCandidate,
) -> list[IntegrityIssue]:
    expected = (
        effect.card_code,
        effect.text_revision_id,
        effect.raw_text_hash,
        effect.effect_index,
    )
    actual = (
        candidate.card_code,
        candidate.text_revision_id,
        candidate.raw_text_hash,
        candidate.effect_index,
    )
    if expected == actual:
        return []
    return [
        _issue(
            effect,
            "candidate_binding_mismatch",
            "Candidate discovery selected a different source revision or segment.",
            expected=expected,
            actual=actual,
        )
    ]


def _issue(
    effect: EffectDefinition,
    code: str,
    message: str,
    *,
    expected: Any = None,
    actual: Any = None,
    severity: Severity = "error",
) -> IntegrityIssue:
    return IntegrityIssue(
        severity=severity,
        code=code,
        effect_id=effect.effect_id,
        card_code=effect.card_code,
        message=message,
        expected=expected,
        actual=actual,
    )


def write_integrity_report(output_dir: Path, result: IntegrityResult) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "registry_effect_count": result.registry_effect_count,
        "candidate_count": result.candidate_count,
        "executable_count": result.executable_count,
        "manual_count": result.manual_count,
        "error_count": result.error_count,
        "warning_count": result.warning_count,
        "issues": [asdict(issue) for issue in result.issues],
    }
    (output_dir / "effect-registry-integrity.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Effect Registry Integrity",
        "",
        f"- Registry effects: {result.registry_effect_count}",
        f"- Candidate effects: {result.candidate_count}",
        f"- Executable: {result.executable_count}",
        f"- Manual: {result.manual_count}",
        f"- Errors: {result.error_count}",
        f"- Warnings: {result.warning_count}",
        "",
        "| Severity | Code | Effect | Message |",
        "| --- | --- | --- | --- |",
    ]
    for issue in result.issues:
        message = issue.message.replace("|", "\\|")
        lines.append(
            f"| {issue.severity} | `{issue.code}` | `{issue.effect_id}` | {message} |"
        )
    (output_dir / "effect-registry-integrity.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
