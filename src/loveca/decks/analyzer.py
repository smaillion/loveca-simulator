"""Deck file parsing, legality checks, and summary analysis."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loveca.db.bootstrap import connect_database, get_schema_version
from loveca.db.schema import SCHEMA_VERSION


DECKLIST_VERSION = "decklist.v0"
MAIN_DECK_MEMBER_COUNT = 48
MAIN_DECK_LIVE_COUNT = 12
ENERGY_DECK_COUNT = 12
MAX_COPIES_PER_CARD_CODE = 4


class DeckAnalyzerError(RuntimeError):
    """Base error for deck analyzer failures."""


class DeckFileError(DeckAnalyzerError):
    """Raised when a deck file does not match the MVP decklist contract."""


class DeckDatabaseError(DeckAnalyzerError):
    """Raised when the card database cannot support deck analysis."""


@dataclass(frozen=True)
class DeckEntry:
    card_code: str
    quantity: int
    preferred_printing_id: str | None = None


@dataclass(frozen=True)
class DeckList:
    version: str
    main_deck: tuple[DeckEntry, ...]
    energy_deck: tuple[DeckEntry, ...]
    name: str | None = None


@dataclass(frozen=True)
class DeckIssue:
    severity: str
    code: str
    message: str
    section: str | None = None
    card_code: str | None = None


@dataclass(frozen=True)
class CardSnapshot:
    gameplay_card_id: int
    card_code: str
    name_ja: str
    card_type: str
    cost: int | None = None
    blade: int | None = None
    member_blade_heart_color_slot: str | None = None
    score: int | None = None
    live_blade_heart_color_slot: str | None = None
    hearts: dict[str, dict[str, int]] = field(default_factory=dict)
    special_blade_hearts: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class DeckAnalysis:
    deck_name: str | None
    is_legal: bool
    issues: tuple[DeckIssue, ...]
    card_type_counts: dict[str, dict[str, int]]
    copy_counts: dict[str, int]
    member_cost_curve: dict[str, int]
    member_basic_heart_distribution: dict[str, int]
    live_required_heart_distribution: dict[str, int]
    member_blade_summary: dict[str, float | int]
    live_score_distribution: dict[str, int]
    special_blade_heart_summary: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "deck_name": self.deck_name,
            "is_legal": self.is_legal,
            "issues": [issue.__dict__ for issue in self.issues],
            "card_type_counts": self.card_type_counts,
            "copy_counts": self.copy_counts,
            "member_cost_curve": self.member_cost_curve,
            "member_basic_heart_distribution": self.member_basic_heart_distribution,
            "live_required_heart_distribution": self.live_required_heart_distribution,
            "member_blade_summary": self.member_blade_summary,
            "live_score_distribution": self.live_score_distribution,
            "special_blade_heart_summary": self.special_blade_heart_summary,
        }


def load_deck(path: Path) -> DeckList:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeckFileError(f"invalid deck file: {path}") from exc
    return parse_deck(payload)


def parse_deck(payload: Any) -> DeckList:
    if not isinstance(payload, dict):
        raise DeckFileError("deck file must contain a JSON object")

    version = payload.get("version")
    if version != DECKLIST_VERSION:
        raise DeckFileError(
            f"deck version must be {DECKLIST_VERSION!r}; got {version!r}"
        )

    name = payload.get("name")
    if name is not None and not isinstance(name, str):
        raise DeckFileError("deck name must be a string or null")

    return DeckList(
        version=version,
        name=name,
        main_deck=_load_entries(payload.get("main_deck"), "main_deck"),
        energy_deck=_load_entries(payload.get("energy_deck"), "energy_deck"),
    )


def analyze_deck(database_path: Path, deck: DeckList) -> DeckAnalysis:
    version = get_schema_version(database_path)
    if version != SCHEMA_VERSION:
        raise DeckDatabaseError(
            f"deck analysis requires schema v{SCHEMA_VERSION}; got {version!r}"
        )

    card_codes = {entry.card_code for entry in (*deck.main_deck, *deck.energy_deck)}
    printing_ids = {
        entry.preferred_printing_id
        for entry in (*deck.main_deck, *deck.energy_deck)
        if entry.preferred_printing_id is not None
    }

    with closing(connect_database(database_path)) as connection:
        cards = _load_card_snapshots(connection, card_codes)
        printing_map = _load_printing_card_codes(connection, printing_ids)

    issues: list[DeckIssue] = []
    issues.extend(_validate_entries(deck, cards, printing_map))
    issues.extend(_validate_deck_counts(deck, cards))

    return _build_analysis(deck, cards, issues)


def analyze_deck_file(database_path: Path, deck_path: Path) -> DeckAnalysis:
    return analyze_deck(database_path, load_deck(deck_path))


def render_analysis_text(analysis: DeckAnalysis) -> str:
    lines = [
        f"Deck: {analysis.deck_name or '(unnamed)'}",
        f"Status: {'legal' if analysis.is_legal else 'illegal'}",
        "",
        "Issues:",
    ]
    if analysis.issues:
        for issue in analysis.issues:
            location = ""
            if issue.section or issue.card_code:
                parts = [part for part in (issue.section, issue.card_code) if part]
                location = f" [{' / '.join(parts)}]"
            lines.append(f"- {issue.severity.upper()} {issue.code}{location}: {issue.message}")
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "Card Type Counts:",
            _format_nested_counts(analysis.card_type_counts),
            "",
            "Member Cost Curve:",
            _format_counts(analysis.member_cost_curve),
            "",
            "Member Basic Heart Distribution:",
            _format_counts(analysis.member_basic_heart_distribution),
            "",
            "Live Required Heart Distribution:",
            _format_counts(analysis.live_required_heart_distribution),
            "",
            "Member Blade Summary:",
            _format_counts(analysis.member_blade_summary),
            "",
            "Live Score Distribution:",
            _format_counts(analysis.live_score_distribution),
            "",
            "Special Blade Heart Summary:",
            _format_counts(analysis.special_blade_heart_summary),
        ]
    )
    return "\n".join(lines)


def render_analysis_json(analysis: DeckAnalysis) -> str:
    return json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


def _load_entries(payload: Any, field_name: str) -> tuple[DeckEntry, ...]:
    if not isinstance(payload, list):
        raise DeckFileError(f"{field_name} must be an array")

    entries: list[DeckEntry] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise DeckFileError(f"{field_name}[{index}] must be an object")
        card_code = item.get("card_code")
        if not isinstance(card_code, str) or not card_code:
            raise DeckFileError(f"{field_name}[{index}].card_code must be non-empty")
        quantity = item.get("quantity")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            raise DeckFileError(f"{field_name}[{index}].quantity must be a positive integer")
        preferred_printing_id = item.get("preferred_printing_id")
        if preferred_printing_id is not None and (
            not isinstance(preferred_printing_id, str) or not preferred_printing_id
        ):
            raise DeckFileError(
                f"{field_name}[{index}].preferred_printing_id must be non-empty or null"
            )
        entries.append(
            DeckEntry(
                card_code=card_code,
                quantity=quantity,
                preferred_printing_id=preferred_printing_id,
            )
        )
    return tuple(entries)


def _load_card_snapshots(
    connection: sqlite3.Connection,
    card_codes: set[str],
) -> dict[str, CardSnapshot]:
    if not card_codes:
        return {}

    placeholders = ", ".join("?" for _ in card_codes)
    rows = connection.execute(
        f"""
        SELECT
            card.id AS gameplay_card_id,
            card.card_code,
            card.canonical_name_ja,
            card.card_type,
            member.cost,
            member.blade,
            member.blade_heart_color_slot AS member_blade_heart_color_slot,
            live.score,
            live.blade_heart_color_slot AS live_blade_heart_color_slot
        FROM gameplay_cards AS card
        LEFT JOIN member_card_attributes AS member
            ON member.gameplay_card_id = card.id
        LEFT JOIN live_card_attributes AS live
            ON live.gameplay_card_id = card.id
        WHERE card.card_code IN ({placeholders})
        """,
        tuple(sorted(card_codes)),
    ).fetchall()

    snapshots = {
        str(row["card_code"]): CardSnapshot(
            gameplay_card_id=int(row["gameplay_card_id"]),
            card_code=str(row["card_code"]),
            name_ja=str(row["canonical_name_ja"]),
            card_type=str(row["card_type"]),
            cost=row["cost"],
            blade=row["blade"],
            member_blade_heart_color_slot=row["member_blade_heart_color_slot"],
            score=row["score"],
            live_blade_heart_color_slot=row["live_blade_heart_color_slot"],
        )
        for row in rows
    }

    ids = [snapshot.gameplay_card_id for snapshot in snapshots.values()]
    if not ids:
        return snapshots
    id_placeholders = ", ".join("?" for _ in ids)

    hearts_by_id: dict[int, dict[str, dict[str, int]]] = defaultdict(
        lambda: {"basic": {}, "required": {}}
    )
    for row in connection.execute(
        f"""
        SELECT gameplay_card_id, heart_role, color_slot, value
        FROM card_heart_values
        WHERE gameplay_card_id IN ({id_placeholders})
        ORDER BY heart_role, color_slot
        """,
        ids,
    ):
        hearts_by_id[int(row["gameplay_card_id"])][str(row["heart_role"])][
            str(row["color_slot"])
        ] = int(row["value"])

    specials_by_id: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in connection.execute(
        f"""
        SELECT gameplay_card_id, effect_type, value, source_alt
        FROM special_blade_hearts
        WHERE gameplay_card_id IN ({id_placeholders})
        ORDER BY gameplay_card_id, ordinal
        """,
        ids,
    ):
        specials_by_id[int(row["gameplay_card_id"])].append(
            {
                "effect_type": row["effect_type"],
                "value": row["value"],
                "source_alt": row["source_alt"],
            }
        )

    return {
        card_code: CardSnapshot(
            gameplay_card_id=snapshot.gameplay_card_id,
            card_code=snapshot.card_code,
            name_ja=snapshot.name_ja,
            card_type=snapshot.card_type,
            cost=snapshot.cost,
            blade=snapshot.blade,
            member_blade_heart_color_slot=snapshot.member_blade_heart_color_slot,
            score=snapshot.score,
            live_blade_heart_color_slot=snapshot.live_blade_heart_color_slot,
            hearts=hearts_by_id[snapshot.gameplay_card_id],
            special_blade_hearts=tuple(specials_by_id[snapshot.gameplay_card_id]),
        )
        for card_code, snapshot in snapshots.items()
    }


def _load_printing_card_codes(
    connection: sqlite3.Connection,
    printing_ids: set[str],
) -> dict[str, str]:
    if not printing_ids:
        return {}
    placeholders = ", ".join("?" for _ in printing_ids)
    rows = connection.execute(
        f"""
        SELECT printing.card_id, card.card_code
        FROM card_printings AS printing
        JOIN gameplay_cards AS card
            ON card.id = printing.gameplay_card_id
        WHERE printing.card_id IN ({placeholders})
        """,
        tuple(sorted(printing_ids)),
    ).fetchall()
    return {str(row["card_id"]): str(row["card_code"]) for row in rows}


def _validate_entries(
    deck: DeckList,
    cards: dict[str, CardSnapshot],
    printing_map: dict[str, str],
) -> list[DeckIssue]:
    issues: list[DeckIssue] = []
    for section_name, entries in (
        ("main_deck", deck.main_deck),
        ("energy_deck", deck.energy_deck),
    ):
        for entry in entries:
            card = cards.get(entry.card_code)
            if card is None:
                issues.append(
                    DeckIssue(
                        severity="error",
                        code="unknown_card",
                        section=section_name,
                        card_code=entry.card_code,
                        message=f"card_code {entry.card_code!r} is not in the database",
                    )
                )
            elif section_name == "main_deck" and card.card_type == "energy":
                issues.append(
                    DeckIssue(
                        severity="error",
                        code="wrong_deck_section",
                        section=section_name,
                        card_code=entry.card_code,
                        message="Energy cards are not allowed in the main deck",
                    )
                )
            elif section_name == "energy_deck" and card.card_type != "energy":
                issues.append(
                    DeckIssue(
                        severity="error",
                        code="wrong_deck_section",
                        section=section_name,
                        card_code=entry.card_code,
                        message="Only Energy cards are allowed in the Energy deck",
                    )
                )

            if entry.preferred_printing_id is None:
                continue
            printing_card_code = printing_map.get(entry.preferred_printing_id)
            if printing_card_code is None:
                issues.append(
                    DeckIssue(
                        severity="error",
                        code="unknown_preferred_printing",
                        section=section_name,
                        card_code=entry.card_code,
                        message=(
                            "preferred_printing_id "
                            f"{entry.preferred_printing_id!r} is not in the database"
                        ),
                    )
                )
            elif printing_card_code != entry.card_code:
                issues.append(
                    DeckIssue(
                        severity="error",
                        code="preferred_printing_mismatch",
                        section=section_name,
                        card_code=entry.card_code,
                        message=(
                            "preferred_printing_id "
                            f"{entry.preferred_printing_id!r} belongs to "
                            f"{printing_card_code!r}"
                        ),
                    )
                )
    return issues


def _validate_deck_counts(
    deck: DeckList,
    cards: dict[str, CardSnapshot],
) -> list[DeckIssue]:
    issues: list[DeckIssue] = []
    main_counts = _section_type_counts(deck.main_deck, cards)
    energy_counts = _section_type_counts(deck.energy_deck, cards)

    expected_counts = (
        ("main_deck", "member", MAIN_DECK_MEMBER_COUNT, main_counts["member"]),
        ("main_deck", "live", MAIN_DECK_LIVE_COUNT, main_counts["live"]),
        ("energy_deck", "energy", ENERGY_DECK_COUNT, energy_counts["energy"]),
    )
    for section, card_type, expected, actual in expected_counts:
        if actual != expected:
            issues.append(
                DeckIssue(
                    severity="error",
                    code="deck_count_mismatch",
                    section=section,
                    message=(
                        f"{section} requires exactly {expected} {card_type} cards; "
                        f"found {actual}"
                    ),
                )
            )

    for card_code, quantity in _copy_counts(deck).items():
        card = cards.get(card_code)
        if card is None or card.card_type == "energy":
            continue
        if quantity > MAX_COPIES_PER_CARD_CODE:
            issues.append(
                DeckIssue(
                    severity="error",
                    code="copy_limit_exceeded",
                    card_code=card_code,
                    message=(
                        f"{card_code!r} has {quantity} copies; "
                        f"maximum is {MAX_COPIES_PER_CARD_CODE}"
                    ),
                )
            )
    return issues


def _build_analysis(
    deck: DeckList,
    cards: dict[str, CardSnapshot],
    issues: list[DeckIssue],
) -> DeckAnalysis:
    card_type_counts = {
        "main_deck": dict(_section_type_counts(deck.main_deck, cards)),
        "energy_deck": dict(_section_type_counts(deck.energy_deck, cards)),
        "total": dict(_section_type_counts((*deck.main_deck, *deck.energy_deck), cards)),
    }
    copy_counts = dict(sorted(_copy_counts(deck).items()))

    member_cost_curve: Counter[str] = Counter()
    member_basic_hearts: Counter[str] = Counter()
    member_blade_total = 0
    member_blade_count = 0
    member_blade_missing = 0

    live_required_hearts: Counter[str] = Counter()
    live_score_distribution: Counter[str] = Counter()
    special_blade_summary: Counter[str] = Counter()

    for entry in deck.main_deck:
        card = cards.get(entry.card_code)
        if card is None:
            continue
        if card.card_type == "member":
            member_cost_curve[_nullable_key(card.cost)] += entry.quantity
            for color_slot, value in card.hearts.get("basic", {}).items():
                member_basic_hearts[color_slot] += value * entry.quantity
            if card.blade is None:
                member_blade_missing += entry.quantity
            else:
                member_blade_total += card.blade * entry.quantity
                member_blade_count += entry.quantity
        elif card.card_type == "live":
            live_score_distribution[_nullable_key(card.score)] += entry.quantity
            for color_slot, value in card.hearts.get("required", {}).items():
                live_required_hearts[color_slot] += value * entry.quantity
            for special in card.special_blade_hearts:
                special_blade_summary[_special_blade_key(special)] += entry.quantity

    blade_average = (
        round(member_blade_total / member_blade_count, 2)
        if member_blade_count
        else 0
    )

    return DeckAnalysis(
        deck_name=deck.name,
        is_legal=not any(issue.severity == "error" for issue in issues),
        issues=tuple(issues),
        card_type_counts=_sort_nested_counts(card_type_counts),
        copy_counts=copy_counts,
        member_cost_curve=dict(sorted(member_cost_curve.items())),
        member_basic_heart_distribution=dict(sorted(member_basic_hearts.items())),
        live_required_heart_distribution=dict(sorted(live_required_hearts.items())),
        member_blade_summary={
            "total": member_blade_total,
            "average": blade_average,
            "counted_cards": member_blade_count,
            "missing_cards": member_blade_missing,
        },
        live_score_distribution=dict(sorted(live_score_distribution.items())),
        special_blade_heart_summary=dict(sorted(special_blade_summary.items())),
    )


def _section_type_counts(
    entries: tuple[DeckEntry, ...],
    cards: dict[str, CardSnapshot],
) -> Counter[str]:
    counts: Counter[str] = Counter({"member": 0, "live": 0, "energy": 0, "unknown": 0})
    for entry in entries:
        card = cards.get(entry.card_code)
        counts[card.card_type if card else "unknown"] += entry.quantity
    return counts


def _copy_counts(deck: DeckList) -> Counter[str]:
    counts: Counter[str] = Counter()
    for entry in (*deck.main_deck, *deck.energy_deck):
        counts[entry.card_code] += entry.quantity
    return counts


def _nullable_key(value: int | None) -> str:
    return "null" if value is None else str(value)


def _special_blade_key(special: dict[str, Any]) -> str:
    source_alt = special.get("source_alt")
    if isinstance(source_alt, str) and source_alt:
        return source_alt
    effect_type = special.get("effect_type")
    value = special.get("value")
    return f"{effect_type}{value if value is not None else ''}"


def _sort_nested_counts(
    counts: dict[str, dict[str, int]],
) -> dict[str, dict[str, int]]:
    return {section: dict(sorted(values.items())) for section, values in counts.items()}


def _format_nested_counts(values: dict[str, dict[str, int]]) -> str:
    if not values:
        return "- none"
    return "\n".join(
        f"- {section}: "
        + ", ".join(f"{key}={value}" for key, value in counts.items())
        for section, counts in values.items()
    )


def _format_counts(values: dict[str, Any]) -> str:
    if not values:
        return "- none"
    return "\n".join(f"- {key}: {value}" for key, value in values.items())
