"""Import normalized local card JSON into the versioned SQLite catalog."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
import urllib.parse
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loveca.db.bootstrap import connect_database, initialize_database


CARD_TYPE_MAP = {
    "メンバー": "member",
    "ライブ": "live",
    "エネルギー": "energy",
    "member": "member",
    "live": "live",
    "energy": "energy",
}
HEART_COLOR_SLOTS = {
    "heart0",
    "heart01",
    "heart02",
    "heart03",
    "heart04",
    "heart05",
    "heart06",
}
ENTITY_SOURCE_LABELS = {
    "作品名": "work",
    "参加ユニット": "unit",
}


class CardImportError(RuntimeError):
    """Base error for local normalized-card imports."""


class CardImportValidationError(CardImportError):
    """Raised when normalized input does not satisfy the import contract."""


class CardImportConflictError(CardImportError):
    """Raised when an existing non-empty canonical value conflicts."""


@dataclass(frozen=True)
class ImportSummary:
    batch_id: int
    status: str
    records_seen: int
    records_imported: int
    review_candidates: int
    targeted_card_sets: tuple[str, ...] = ()
    new_gameplay_cards: int = 0
    new_card_printings: int = 0
    new_text_revisions: int = 0
    reused_text_revisions: int = 0


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    record_index: int
    field: str
    message: str
    card_id: str | None = None


@dataclass(frozen=True)
class ValidationSummary:
    records_seen: int
    records_selected: int
    targeted_card_sets: tuple[str, ...]
    review_candidates: int
    per_card_set_counts: dict[str, int]
    issues: tuple[ValidationIssue, ...]

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")


@dataclass(frozen=True)
class NormalizedEntity:
    key: str
    canonical_name_ja: str


@dataclass(frozen=True)
class EntityNormalization:
    works: dict[str, tuple[NormalizedEntity, ...]]
    units: dict[str, tuple[NormalizedEntity, ...]]

    def resolve(
        self,
        entity_type: str,
        raw_value: str,
    ) -> tuple[NormalizedEntity, ...] | None:
        mapping = self.works if entity_type == "work" else self.units
        return mapping.get(raw_value)


def import_normalized_cards(
    database_path: Path,
    input_path: Path,
    normalization_path: Path,
    card_set_codes: tuple[str, ...] | None = None,
) -> ImportSummary:
    input_bytes = input_path.read_bytes()
    normalization_bytes = normalization_path.read_bytes()
    all_records = _prepare_loaded_records(_load_card_records(input_bytes, input_path))
    normalization = _load_normalization(normalization_bytes, normalization_path)
    targeted_card_sets = _normalize_card_set_codes(card_set_codes)
    records = _select_records_by_card_set(all_records, targeted_card_sets)
    parser_version = _common_parser_version(records)
    validation = _validate_loaded_records(
        all_records,
        normalization,
        card_set_codes=card_set_codes,
    )

    initialize_database(database_path)
    started_at = _utc_now()
    new_gameplay_cards = 0
    new_card_printings = 0
    new_text_revisions = 0
    reused_text_revisions = 0

    with closing(connect_database(database_path)) as connection:
        batch_id = _create_import_batch(
            connection,
            input_path=input_path,
            normalization_path=normalization_path,
            input_hash=_sha256(input_bytes),
            normalization_hash=_sha256(normalization_bytes),
            parser_version=parser_version,
            started_at=started_at,
            records_seen=len(records),
        )
        connection.commit()

        if validation.error_count:
            connection.execute(
                """
                UPDATE import_batches
                SET finished_at = ?,
                    status = 'failed',
                    records_imported = 0,
                    review_candidates = ?,
                    error_message = ?
                WHERE id = ?
                """,
                (
                    _utc_now(),
                    validation.review_candidates,
                    _format_validation_errors(validation),
                    batch_id,
                ),
            )
            connection.commit()
            raise CardImportValidationError(_format_validation_errors(validation))

        review_candidates: set[tuple[str, str]] = set()
        try:
            connection.execute("BEGIN IMMEDIATE")
            for index, record in enumerate(records):
                import_outcome = _import_card_record(
                    connection,
                    record=record,
                    record_index=index,
                    batch_id=batch_id,
                    normalization=normalization,
                    review_candidates=review_candidates,
                )
                if import_outcome["new_gameplay_card"]:
                    new_gameplay_cards += 1
                if import_outcome["new_card_printing"]:
                    new_card_printings += 1
                if import_outcome["new_text_revision"]:
                    new_text_revisions += 1
                if import_outcome["reused_text_revision"]:
                    reused_text_revisions += 1

            status = (
                "completed_with_review" if review_candidates else "completed"
            )
            finished_at = _utc_now()
            connection.execute(
                """
                UPDATE import_batches
                SET finished_at = ?,
                    status = ?,
                    records_imported = ?,
                    review_candidates = ?
                WHERE id = ?
                """,
                (
                    finished_at,
                    status,
                    len(records),
                    len(review_candidates),
                    batch_id,
                ),
            )
            connection.commit()
        except Exception as exc:
            connection.rollback()
            connection.execute(
                """
                UPDATE import_batches
                SET finished_at = ?,
                    status = 'failed',
                    records_imported = 0,
                    review_candidates = 0,
                    error_message = ?
                WHERE id = ?
                """,
                (_utc_now(), str(exc), batch_id),
            )
            connection.commit()
            if isinstance(exc, CardImportError):
                raise
            if isinstance(exc, sqlite3.IntegrityError):
                raise CardImportValidationError(str(exc)) from exc
            raise

    return ImportSummary(
        batch_id=batch_id,
        status=status,
        records_seen=len(records),
        records_imported=len(records),
        review_candidates=len(review_candidates),
        targeted_card_sets=targeted_card_sets,
        new_gameplay_cards=new_gameplay_cards,
        new_card_printings=new_card_printings,
        new_text_revisions=new_text_revisions,
        reused_text_revisions=reused_text_revisions,
    )


def validate_normalized_cards(
    input_path: Path,
    normalization_path: Path,
    card_set_codes: tuple[str, ...] | None = None,
) -> ValidationSummary:
    input_bytes = input_path.read_bytes()
    normalization_bytes = normalization_path.read_bytes()
    records = _prepare_loaded_records(_load_card_records(input_bytes, input_path))
    normalization = _load_normalization(normalization_bytes, normalization_path)
    return _validate_loaded_records(records, normalization, card_set_codes=card_set_codes)


def write_validation_report(
    report_path: Path,
    *,
    input_path: Path,
    normalization_path: Path,
    summary: ValidationSummary,
) -> None:
    lines = [
        "# Card Import Validation Report",
        "",
        "## Summary",
        "",
        f"* Input: `{input_path}`",
        f"* Normalization: `{normalization_path}`",
        f"* Records seen: `{summary.records_seen}`",
        f"* Records selected: `{summary.records_selected}`",
        f"* Targeted card sets: `{', '.join(summary.targeted_card_sets) or 'all'}`",
        f"* Errors: `{summary.error_count}`",
        f"* Warnings: `{summary.warning_count}`",
        f"* Review candidates: `{summary.review_candidates}`",
        "",
        "## Card Set Coverage",
        "",
        "| card_set_code | selected_records |",
        "| --- | ---: |",
    ]
    for card_set_code, count in summary.per_card_set_counts.items():
        lines.append(f"| `{card_set_code}` | {count} |")
    if not summary.per_card_set_counts:
        lines.append("| - | 0 |")

    lines.extend(
        [
            "",
            "## Issues",
            "",
            "| severity | record | card_id | field | message |",
            "| --- | ---: | --- | --- | --- |",
        ]
    )
    if summary.issues:
        for issue in summary.issues:
            lines.append(
                f"| `{issue.severity}` | {issue.record_index} | "
                f"`{issue.card_id or '-'}` | `{issue.field}` | {issue.message} |"
            )
    else:
        lines.append("| `ok` | - | `-` | `-` | no issues |")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def write_import_report(
    report_path: Path,
    *,
    input_path: Path,
    normalization_path: Path,
    summary: ImportSummary,
) -> None:
    lines = [
        "# Card Import Report",
        "",
        "## Summary",
        "",
        f"* Input: `{input_path}`",
        f"* Normalization: `{normalization_path}`",
        f"* Batch id: `{summary.batch_id}`",
        f"* Status: `{summary.status}`",
        f"* Records seen: `{summary.records_seen}`",
        f"* Records imported: `{summary.records_imported}`",
        f"* Targeted card sets: `{', '.join(summary.targeted_card_sets) or 'all'}`",
        f"* New Gameplay Cards: `{summary.new_gameplay_cards}`",
        f"* New Card Printings: `{summary.new_card_printings}`",
        f"* New Text Revisions: `{summary.new_text_revisions}`",
        f"* Reused Text Revisions: `{summary.reused_text_revisions}`",
        f"* Review candidates: `{summary.review_candidates}`",
        "",
    ]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def normalize_effect_text(raw_text: str) -> str:
    return raw_text.replace("\r\n", "\n").replace("\r", "\n").strip()


def hash_effect_text(raw_text: str) -> str:
    return _sha256(normalize_effect_text(raw_text).encode("utf-8"))


def derive_card_code(card_id: str) -> str:
    match = re.match(
        r"^(?P<card_code>.+?-(?:E)?\d{2,4})(?:-.+)?$",
        card_id,
        re.IGNORECASE,
    )
    return match.group("card_code") if match else card_id


def _load_card_records(data: bytes, path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CardImportValidationError(f"invalid normalized JSON: {path}") from exc
    if not isinstance(payload, list):
        raise CardImportValidationError("normalized card input must be a JSON array")
    if not all(isinstance(item, dict) for item in payload):
        raise CardImportValidationError("every normalized card record must be an object")
    return payload


def _load_normalization(data: bytes, path: Path) -> EntityNormalization:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CardImportValidationError(f"invalid normalization JSON: {path}") from exc
    if payload.get("version") != 1:
        raise CardImportValidationError("normalization mapping version must be 1")
    return EntityNormalization(
        works=_load_entity_mapping(payload.get("works"), "works"),
        units=_load_entity_mapping(payload.get("units"), "units"),
    )


def _load_entity_mapping(
    payload: Any,
    field_name: str,
) -> dict[str, tuple[NormalizedEntity, ...]]:
    if not isinstance(payload, dict):
        raise CardImportValidationError(
            f"normalization field {field_name!r} must be an object"
        )
    result: dict[str, tuple[NormalizedEntity, ...]] = {}
    for raw_value, entries in payload.items():
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise CardImportValidationError(
                f"{field_name} normalization keys must be non-empty strings"
            )
        if not isinstance(entries, list) or not entries:
            raise CardImportValidationError(
                f"{field_name}[{raw_value!r}] must be a non-empty array"
            )
        normalized: list[NormalizedEntity] = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise CardImportValidationError(
                    f"{field_name}[{raw_value!r}] entries must be objects"
                )
            key = entry.get("key")
            name = entry.get("canonical_name_ja")
            if not isinstance(key, str) or not key:
                raise CardImportValidationError(
                    f"{field_name}[{raw_value!r}] entry has no key"
                )
            if not isinstance(name, str) or not name:
                raise CardImportValidationError(
                    f"{field_name}[{raw_value!r}] entry has no canonical_name_ja"
                )
            normalized.append(NormalizedEntity(key=key, canonical_name_ja=name))
        result[raw_value] = tuple(normalized)
    return result


def _validate_loaded_records(
    records: list[dict[str, Any]],
    normalization: EntityNormalization,
    *,
    card_set_codes: tuple[str, ...] | None,
) -> ValidationSummary:
    targeted_card_sets = _normalize_card_set_codes(card_set_codes)
    selected_records = _select_records_by_card_set(records, targeted_card_sets)
    issues: list[ValidationIssue] = []
    review_candidates: set[tuple[str, str]] = set()
    per_card_set_counts: dict[str, int] = {}

    if targeted_card_sets and not selected_records:
        issues.append(
            ValidationIssue(
                severity="error",
                record_index=-1,
                card_id=None,
                field="card_set_codes",
                message=(
                    "no records matched requested card_set_codes "
                    + ", ".join(targeted_card_sets)
                ),
            )
        )

    for index, record in enumerate(selected_records):
        card_set_code = record.get("product_code")
        if isinstance(card_set_code, str) and card_set_code:
            per_card_set_counts[card_set_code] = per_card_set_counts.get(card_set_code, 0) + 1
        issues.extend(
            _validate_record_for_import(
                record,
                record_index=index,
                normalization=normalization,
                review_candidates=review_candidates,
            )
        )

    return ValidationSummary(
        records_seen=len(records),
        records_selected=len(selected_records),
        targeted_card_sets=targeted_card_sets,
        review_candidates=len(review_candidates),
        per_card_set_counts=dict(sorted(per_card_set_counts.items())),
        issues=tuple(issues),
    )


def _prepare_loaded_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _promote_duplicate_energy_card_codes(
        _backfill_names_from_card_code(records)
    )


def _normalize_card_set_codes(card_set_codes: tuple[str, ...] | None) -> tuple[str, ...]:
    if not card_set_codes:
        return ()
    normalized: list[str] = []
    seen: set[str] = set()
    for value in card_set_codes:
        if not isinstance(value, str) or not value.strip():
            raise CardImportValidationError("card_set_codes must be non-empty strings")
        item = value.strip()
        if item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return tuple(normalized)


def _select_records_by_card_set(
    records: list[dict[str, Any]],
    card_set_codes: tuple[str, ...],
) -> list[dict[str, Any]]:
    if not card_set_codes:
        return list(records)
    allowed = set(card_set_codes)
    return [
        record
        for record in records
        if isinstance(record.get("product_code"), str) and record["product_code"] in allowed
    ]


def _backfill_names_from_card_code(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names_by_code: dict[str, str] = {}
    ambiguous_codes: set[str] = set()
    for record in records:
        card_code = record.get("card_code")
        name = record.get("name")
        if not isinstance(card_code, str) or not card_code:
            continue
        if not isinstance(name, str) or not name:
            continue
        existing = names_by_code.get(card_code)
        if existing is None:
            names_by_code[card_code] = name
        elif existing != name:
            ambiguous_codes.add(card_code)

    enriched_records: list[dict[str, Any]] = []
    for record in records:
        card_code = record.get("card_code")
        if (
            isinstance(card_code, str)
            and card_code not in ambiguous_codes
            and record.get("name") in (None, "")
            and card_code in names_by_code
        ):
            cloned = dict(record)
            parse_notes = dict(cloned.get("parse_notes") or {})
            parse_notes["name_backfilled_from_card_code"] = card_code
            cloned["parse_notes"] = parse_notes
            cloned["name"] = names_by_code[card_code]
            enriched_records.append(cloned)
            continue
        if (
            isinstance(card_code, str)
            and card_code
            and record.get("card_type") in {"エネルギー", "energy"}
            and record.get("name") in (None, "")
        ):
            cloned = dict(record)
            parse_notes = dict(cloned.get("parse_notes") or {})
            parse_notes["name_placeholder_from_card_code"] = card_code
            cloned["parse_notes"] = parse_notes
            cloned["name"] = card_code
            enriched_records.append(cloned)
            continue
        enriched_records.append(record)
    return enriched_records


def _promote_duplicate_energy_card_codes(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        card_code = record.get("card_code")
        card_id = record.get("card_id")
        if not isinstance(card_code, str) or not isinstance(card_id, str):
            continue
        if not card_code or not card_id:
            continue
        grouped.setdefault(card_code, []).append(record)

    promoted_ids: set[str] = set()
    for card_code, items in grouped.items():
        if len(items) < 2:
            continue
        if not all(record.get("card_type") in {"エネルギー", "energy"} for record in items):
            continue
        if len({str(record.get("card_id")) for record in items}) < 2:
            continue
        promoted_ids.update(str(record.get("card_id")) for record in items)

    if not promoted_ids:
        return records

    promoted_records: list[dict[str, Any]] = []
    for record in records:
        card_id = record.get("card_id")
        card_code = record.get("card_code")
        if (
            isinstance(card_id, str)
            and card_id in promoted_ids
            and isinstance(card_code, str)
            and card_id != card_code
        ):
            cloned = dict(record)
            parse_notes = dict(cloned.get("parse_notes") or {})
            parse_notes["gameplay_card_code_strategy"] = "full_card_id_conflict_fallback"
            parse_notes.setdefault("derived_card_code", card_code)
            parse_notes["duplicate_energy_card_code_fallback"] = True
            cloned["parse_notes"] = parse_notes
            cloned["card_code"] = card_id
            promoted_records.append(cloned)
            continue
        promoted_records.append(record)
    return promoted_records


def _validate_record_for_import(
    record: dict[str, Any],
    *,
    record_index: int,
    normalization: EntityNormalization,
    review_candidates: set[tuple[str, str]],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    card_id = _safe_record_string(record.get("card_id"))
    try:
        required_values = {
            "card_id": _required_string(record, "card_id", record_index),
            "card_code": _required_string(record, "card_code", record_index),
            "name": _required_string(record, "name", record_index),
            "product_code": _required_string(record, "product_code", record_index),
            "source_url": _required_string(record, "source_url", record_index),
            "fetched_at": _required_string(record, "fetched_at", record_index),
            "parser_version": _required_string(record, "parser_version", record_index),
        }
        card_type = _normalize_card_type(record.get("card_type"), record_index)
        parse_notes = record.get("parse_notes")
        if not isinstance(parse_notes, dict):
            raise CardImportValidationError(
                f"record {record_index}: parse_notes must be an object"
            )
        if "name_placeholder_from_card_code" in parse_notes:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    record_index=record_index,
                    card_id=required_values["card_id"],
                    field="name",
                    message=(
                        "official name missing; using card_code placeholder "
                        f"{parse_notes['name_placeholder_from_card_code']!r}"
                    ),
                )
            )
        _validate_timestamp(required_values["fetched_at"], record_index)
        _card_list_root(required_values["source_url"])
        if not _card_code_matches_identity(
            card_id=required_values["card_id"],
            card_code=required_values["card_code"],
            card_type=card_type,
            parse_notes=parse_notes,
        ):
            raise CardImportValidationError(
                f"record {record_index}: card_id {required_values['card_id']!r} does not derive "
                f"card_code {required_values['card_code']!r}"
            )
        _validate_type_attributes(record, card_type, record_index)
        _validate_heart_values(record, card_type)
        _validate_special_blade_hearts(record, card_type)
        _validate_related_printing_ids(record, required_values["card_code"])
        _validate_entity_mappings(
            parse_notes=parse_notes,
            normalization=normalization,
            review_candidates=review_candidates,
            record_index=record_index,
            card_id=required_values["card_id"],
            issues=issues,
        )
    except CardImportValidationError as exc:
        field, message = _split_validation_message(str(exc))
        issues.append(
            ValidationIssue(
                severity="error",
                record_index=record_index,
                card_id=card_id,
                field=field,
                message=message,
            )
        )
    except CardImportConflictError as exc:
        issues.append(
            ValidationIssue(
                severity="error",
                record_index=record_index,
                card_id=card_id,
                field="conflict",
                message=str(exc),
            )
        )
    return issues


def _create_import_batch(
    connection: sqlite3.Connection,
    *,
    input_path: Path,
    normalization_path: Path,
    input_hash: str,
    normalization_hash: str,
    parser_version: str | None,
    started_at: str,
    records_seen: int,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO import_batches (
            input_path,
            normalization_path,
            input_hash,
            normalization_hash,
            parser_version,
            started_at,
            status,
            records_seen
        )
        VALUES (?, ?, ?, ?, ?, ?, 'running', ?)
        """,
        (
            str(input_path),
            str(normalization_path),
            input_hash,
            normalization_hash,
            parser_version,
            started_at,
            records_seen,
        ),
    )
    return int(cursor.lastrowid)


def _import_card_record(
    connection: sqlite3.Connection,
    *,
    record: dict[str, Any],
    record_index: int,
    batch_id: int,
    normalization: EntityNormalization,
    review_candidates: set[tuple[str, str]],
) -> dict[str, bool]:
    card_id = _required_string(record, "card_id", record_index)
    card_code = _required_string(record, "card_code", record_index)
    card_type = _normalize_card_type(record.get("card_type"), record_index)
    parse_notes = record.get("parse_notes")
    if not isinstance(parse_notes, dict):
        raise CardImportValidationError(
            f"record {record_index}: parse_notes must be an object"
        )
    if not _card_code_matches_identity(
        card_id=card_id,
        card_code=card_code,
        card_type=card_type,
        parse_notes=parse_notes,
    ):
        raise CardImportValidationError(
            f"record {record_index}: card_id {card_id!r} does not derive "
            f"card_code {card_code!r}"
        )

    name = _required_string(record, "name", record_index)
    card_set_code = _required_string(record, "product_code", record_index)
    source_url = _required_string(record, "source_url", record_index)
    fetched_at = _required_string(record, "fetched_at", record_index)
    _validate_timestamp(fetched_at, record_index)
    parser_version = _required_string(record, "parser_version", record_index)

    _validate_type_attributes(record, card_type, record_index)
    card_set_id, _new_card_set = _upsert_card_set(
        connection,
        card_set_code=card_set_code,
        source_url=_card_list_root(source_url),
    )
    gameplay_card_id, new_gameplay_card = _upsert_gameplay_card(
        connection,
        card_code=card_code,
        name=name,
        card_type=card_type,
    )
    printing_id, new_card_printing = _upsert_card_printing(
        connection,
        card_id=card_id,
        gameplay_card_id=gameplay_card_id,
        card_set_id=card_set_id,
        rarity=record.get("rarity"),
        image_url=record.get("image_url"),
    )
    _upsert_type_attributes(
        connection,
        gameplay_card_id=gameplay_card_id,
        card_type=card_type,
        record=record,
    )
    _upsert_heart_values(
        connection,
        gameplay_card_id=gameplay_card_id,
        card_type=card_type,
        record=record,
    )
    _upsert_special_blade_hearts(
        connection,
        gameplay_card_id=gameplay_card_id,
        card_type=card_type,
        record=record,
    )

    observation_id = _upsert_source_observation(
        connection,
        printing_id=printing_id,
        batch_id=batch_id,
        source_url=source_url,
        fetched_at=fetched_at,
        parser_version=parser_version,
        raw_product_label=record.get("product"),
        parse_notes=parse_notes,
    )
    text_revision_outcome = _upsert_text_revision(
        connection,
        gameplay_card_id=gameplay_card_id,
        observation_id=observation_id,
        fetched_at=fetched_at,
        raw_text=record.get("raw_effect_text"),
    )
    _upsert_entities(
        connection,
        gameplay_card_id=gameplay_card_id,
        observation_id=observation_id,
        parse_notes=parse_notes,
        normalization=normalization,
        review_candidates=review_candidates,
    )
    _upsert_printing_references(
        connection,
        printing_id=printing_id,
        observation_id=observation_id,
        card_code=card_code,
        related_ids=record.get("related_printing_ids"),
    )
    return {
        "new_gameplay_card": new_gameplay_card,
        "new_card_printing": new_card_printing,
        "new_text_revision": text_revision_outcome["new_text_revision"],
        "reused_text_revision": text_revision_outcome["reused_text_revision"],
    }


def _validate_type_attributes(
    record: dict[str, Any],
    card_type: str,
    record_index: int,
) -> None:
    member_attributes = record.get("member_attributes")
    live_attributes = record.get("live_attributes")
    if card_type == "member":
        if not isinstance(member_attributes, dict) or live_attributes is not None:
            raise CardImportValidationError(
                f"record {record_index}: Member requires only member_attributes"
            )
    elif card_type == "live":
        if not isinstance(live_attributes, dict) or member_attributes is not None:
            raise CardImportValidationError(
                f"record {record_index}: Live requires only live_attributes"
            )
        if "blade" in live_attributes:
            raise CardImportValidationError(
                f"record {record_index}: Live attributes must not contain blade"
            )
    elif member_attributes is not None or live_attributes is not None:
        raise CardImportValidationError(
            f"record {record_index}: Energy must not have type-specific attributes"
        )


def _validate_heart_values(record: dict[str, Any], card_type: str) -> None:
    if card_type == "member":
        role = "basic"
        values = record["member_attributes"].get("heart_by_color")
    elif card_type == "live":
        role = "required"
        values = record["live_attributes"].get("required_heart_by_color")
    else:
        return
    if not isinstance(values, dict):
        raise CardImportValidationError(f"{role} Heart values must be an object")
    for color_slot, raw_value in values.items():
        if color_slot not in HEART_COLOR_SLOTS:
            raise CardImportValidationError(f"unknown Heart color slot: {color_slot!r}")
        if raw_value is None:
            continue
        _positive_int(raw_value, f"{role} Heart {color_slot}")
        if role == "basic" and color_slot == "heart0":
            raise CardImportValidationError("Member basic Heart cannot use heart0")


def _validate_special_blade_hearts(record: dict[str, Any], card_type: str) -> None:
    if card_type != "live":
        return
    entries = record["live_attributes"].get("special_blade_hearts") or []
    if not isinstance(entries, list):
        raise CardImportValidationError("special_blade_hearts must be an array")
    for entry in entries:
        if not isinstance(entry, dict):
            raise CardImportValidationError("special_blade_hearts entries must be objects")
        effect_type = _required_mapping_string(entry, "effect_type")
        if effect_type not in {"all_color", "draw", "score", "unknown"}:
            raise CardImportValidationError(
                f"unknown special Blade Heart type: {effect_type!r}"
            )
        value = entry.get("value")
        normalized_value = (
            None if value is None else _positive_int(value, "special Blade Heart value")
        )
        if effect_type != "unknown" and normalized_value is None:
            raise CardImportValidationError(
                f"special Blade Heart {effect_type!r} requires a value"
            )
        _required_mapping_string(entry, "source_alt")
        _required_mapping_string(entry, "source_field")
        _optional_string(entry.get("resolution_timing"), "resolution_timing")


def _validate_related_printing_ids(record: dict[str, Any], card_code: str) -> None:
    related_ids = record.get("related_printing_ids")
    if related_ids is None:
        return
    if not isinstance(related_ids, list):
        raise CardImportValidationError("related_printing_ids must be an array")
    for related_card_id in related_ids:
        if not isinstance(related_card_id, str) or not related_card_id:
            raise CardImportValidationError(
                "related_printing_ids entries must be non-empty strings"
            )
        related_card_code = derive_card_code(related_card_id)
        if related_card_code != card_code:
            raise CardImportConflictError(
                f"related printing {related_card_id!r} does not share "
                f"card_code {card_code!r}"
            )


def _validate_entity_mappings(
    *,
    parse_notes: dict[str, Any],
    normalization: EntityNormalization,
    review_candidates: set[tuple[str, str]],
    record_index: int,
    card_id: str,
    issues: list[ValidationIssue],
) -> None:
    fields = parse_notes.get("unmapped_fields") or []
    if not isinstance(fields, list):
        raise CardImportValidationError("parse_notes.unmapped_fields must be an array")
    for field in fields:
        if not isinstance(field, dict):
            raise CardImportValidationError("unmapped_fields entries must be objects")
        entity_type = ENTITY_SOURCE_LABELS.get(field.get("label"))
        if entity_type is None:
            continue
        raw_value = field.get("raw_text")
        if not isinstance(raw_value, str) or not raw_value:
            raise CardImportValidationError(
                f"{entity_type} source label must contain Japanese raw text"
            )
        if normalization.resolve(entity_type, raw_value) is None:
            review_candidates.add((entity_type, raw_value))
            issues.append(
                ValidationIssue(
                    severity="warning",
                    record_index=record_index,
                    card_id=card_id,
                    field=entity_type,
                    message=f"{entity_type} {raw_value!r} requires normalization review",
                )
            )


def _upsert_card_set(
    connection: sqlite3.Connection,
    *,
    card_set_code: str,
    source_url: str,
) -> tuple[int, bool]:
    row = connection.execute(
        "SELECT id, source_url FROM card_sets WHERE card_set_code = ?",
        (card_set_code,),
    ).fetchone()
    if row is None:
        cursor = connection.execute(
            """
            INSERT INTO card_sets (card_set_code, source_url)
            VALUES (?, ?)
            """,
            (card_set_code, source_url),
        )
        return int(cursor.lastrowid), True
    _merge_optional_value(
        connection,
        table="card_sets",
        row_id=int(row["id"]),
        column="source_url",
        existing=row["source_url"],
        incoming=source_url,
        identity=f"Card Set {card_set_code}",
    )
    return int(row["id"]), False


def _upsert_gameplay_card(
    connection: sqlite3.Connection,
    *,
    card_code: str,
    name: str,
    card_type: str,
) -> tuple[int, bool]:
    row = connection.execute(
        """
        SELECT id, canonical_name_ja, card_type
        FROM gameplay_cards
        WHERE card_code = ?
        """,
        (card_code,),
    ).fetchone()
    if row is None:
        cursor = connection.execute(
            """
            INSERT INTO gameplay_cards (
                card_code,
                canonical_name_ja,
                card_type
            )
            VALUES (?, ?, ?)
            """,
            (card_code, name, card_type),
        )
        return int(cursor.lastrowid), True
    existing_name = str(row["canonical_name_ja"])
    if not _names_match(existing_name, name):
        if _looks_like_name_fallback(existing_name, card_code) and not _looks_like_name_fallback(
            name,
            card_code,
        ):
            connection.execute(
                """
                UPDATE gameplay_cards
                SET canonical_name_ja = ?
                WHERE id = ?
                """,
                (name, row["id"]),
            )
        elif not _looks_like_name_fallback(existing_name, card_code) and _looks_like_name_fallback(
            name,
            card_code,
        ):
            pass
        else:
            _require_equal(
                existing_name,
                name,
                f"Gameplay Card {card_code} canonical_name_ja",
            )
    _require_equal(
        row["card_type"],
        card_type,
        f"Gameplay Card {card_code} card_type",
    )
    return int(row["id"]), False


def _upsert_card_printing(
    connection: sqlite3.Connection,
    *,
    card_id: str,
    gameplay_card_id: int,
    card_set_id: int,
    rarity: Any,
    image_url: Any,
) -> tuple[int, bool]:
    rarity_value = _optional_string(rarity, "rarity")
    image_value = _optional_string(image_url, "image_url")
    row = connection.execute(
        """
        SELECT id, gameplay_card_id, card_set_id, rarity_ja, image_url
        FROM card_printings
        WHERE card_id = ?
        """,
        (card_id,),
    ).fetchone()
    if row is None:
        cursor = connection.execute(
            """
            INSERT INTO card_printings (
                card_id,
                gameplay_card_id,
                card_set_id,
                rarity_ja,
                image_url
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (card_id, gameplay_card_id, card_set_id, rarity_value, image_value),
        )
        return int(cursor.lastrowid), True
    _require_equal(
        int(row["gameplay_card_id"]),
        gameplay_card_id,
        f"Card Printing {card_id} gameplay_card_id",
    )
    _require_equal(
        int(row["card_set_id"]),
        card_set_id,
        f"Card Printing {card_id} card_set_id",
    )
    _merge_optional_value(
        connection,
        table="card_printings",
        row_id=int(row["id"]),
        column="rarity_ja",
        existing=row["rarity_ja"],
        incoming=rarity_value,
        identity=f"Card Printing {card_id}",
    )
    _merge_optional_value(
        connection,
        table="card_printings",
        row_id=int(row["id"]),
        column="image_url",
        existing=row["image_url"],
        incoming=image_value,
        identity=f"Card Printing {card_id}",
    )
    return int(row["id"]), False


def _upsert_type_attributes(
    connection: sqlite3.Connection,
    *,
    gameplay_card_id: int,
    card_type: str,
    record: dict[str, Any],
) -> None:
    if card_type == "member":
        attributes = record["member_attributes"]
        _upsert_attribute_row(
            connection,
            table="member_card_attributes",
            gameplay_card_id=gameplay_card_id,
            fields={
                "cost": _optional_non_negative_int(attributes.get("cost"), "cost"),
                "blade": _optional_non_negative_int(attributes.get("blade"), "blade"),
                "blade_heart_color_slot": _optional_color_slot(
                    attributes.get("blade_heart_color"),
                    "blade_heart_color",
                ),
            },
        )
    elif card_type == "live":
        attributes = record["live_attributes"]
        _upsert_attribute_row(
            connection,
            table="live_card_attributes",
            gameplay_card_id=gameplay_card_id,
            fields={
                "score": _optional_non_negative_int(attributes.get("score"), "score"),
                "blade_heart_color_slot": _optional_color_slot(
                    attributes.get("blade_heart_color"),
                    "blade_heart_color",
                ),
            },
        )


def _upsert_attribute_row(
    connection: sqlite3.Connection,
    *,
    table: str,
    gameplay_card_id: int,
    fields: dict[str, Any],
) -> None:
    row = connection.execute(
        f"SELECT * FROM {table} WHERE gameplay_card_id = ?",
        (gameplay_card_id,),
    ).fetchone()
    if row is None:
        columns = ", ".join(("gameplay_card_id", *fields.keys()))
        placeholders = ", ".join("?" for _ in range(len(fields) + 1))
        connection.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
            (gameplay_card_id, *fields.values()),
        )
        return
    for column, incoming in fields.items():
        _merge_optional_value(
            connection,
            table=table,
            row_id=gameplay_card_id,
            id_column="gameplay_card_id",
            column=column,
            existing=row[column],
            incoming=incoming,
            identity=f"{table} for gameplay_card_id {gameplay_card_id}",
        )


def _upsert_heart_values(
    connection: sqlite3.Connection,
    *,
    gameplay_card_id: int,
    card_type: str,
    record: dict[str, Any],
) -> None:
    if card_type == "member":
        role = "basic"
        source_label = "基本ハート"
        values = record["member_attributes"].get("heart_by_color")
    elif card_type == "live":
        role = "required"
        source_label = "必要ハート"
        values = record["live_attributes"].get("required_heart_by_color")
    else:
        return
    if not isinstance(values, dict):
        raise CardImportValidationError(f"{role} Heart values must be an object")
    for color_slot, raw_value in values.items():
        if color_slot not in HEART_COLOR_SLOTS:
            raise CardImportValidationError(
                f"unknown Heart color slot: {color_slot!r}"
            )
        if raw_value is None:
            continue
        value = _positive_int(raw_value, f"{role} Heart {color_slot}")
        if role == "basic" and color_slot == "heart0":
            raise CardImportValidationError("Member basic Heart cannot use heart0")
        row = connection.execute(
            """
            SELECT value
            FROM card_heart_values
            WHERE gameplay_card_id = ?
              AND heart_role = ?
              AND color_slot = ?
            """,
            (gameplay_card_id, role, color_slot),
        ).fetchone()
        if row is None:
            connection.execute(
                """
                INSERT INTO card_heart_values (
                    gameplay_card_id,
                    heart_role,
                    color_slot,
                    value,
                    source_label
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (gameplay_card_id, role, color_slot, value, source_label),
            )
        else:
            _require_equal(
                int(row["value"]),
                value,
                f"Heart value {gameplay_card_id}/{role}/{color_slot}",
            )


def _upsert_special_blade_hearts(
    connection: sqlite3.Connection,
    *,
    gameplay_card_id: int,
    card_type: str,
    record: dict[str, Any],
) -> None:
    if card_type != "live":
        return
    entries = record["live_attributes"].get("special_blade_hearts") or []
    if not isinstance(entries, list):
        raise CardImportValidationError("special_blade_hearts must be an array")
    for ordinal, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise CardImportValidationError(
                "special_blade_hearts entries must be objects"
            )
        effect_type = _required_mapping_string(entry, "effect_type")
        if effect_type not in {"all_color", "draw", "score", "unknown"}:
            raise CardImportValidationError(
                f"unknown special Blade Heart type: {effect_type!r}"
            )
        value = entry.get("value")
        normalized_value = (
            None if value is None else _positive_int(value, "special Blade Heart value")
        )
        if effect_type != "unknown" and normalized_value is None:
            raise CardImportValidationError(
                f"special Blade Heart {effect_type!r} requires a value"
            )
        values = {
            "effect_type": effect_type,
            "value": normalized_value,
            "resolution_timing": _optional_string(
                entry.get("resolution_timing"),
                "resolution_timing",
            ),
            "source_alt": _required_mapping_string(entry, "source_alt"),
            "source_field": _required_mapping_string(entry, "source_field"),
            "validation_status": (
                "requires_review" if effect_type == "unknown" else "source_confirmed"
            ),
        }
        row = connection.execute(
            """
            SELECT *
            FROM special_blade_hearts
            WHERE gameplay_card_id = ? AND ordinal = ?
            """,
            (gameplay_card_id, ordinal),
        ).fetchone()
        if row is None:
            connection.execute(
                """
                INSERT INTO special_blade_hearts (
                    gameplay_card_id,
                    ordinal,
                    effect_type,
                    value,
                    resolution_timing,
                    source_alt,
                    source_field,
                    validation_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (gameplay_card_id, ordinal, *values.values()),
            )
        else:
            for column, incoming in values.items():
                _require_equal(
                    row[column],
                    incoming,
                    f"Special Blade Heart {gameplay_card_id}/{ordinal}/{column}",
                )


def _upsert_source_observation(
    connection: sqlite3.Connection,
    *,
    printing_id: int,
    batch_id: int,
    source_url: str,
    fetched_at: str,
    parser_version: str,
    raw_product_label: Any,
    parse_notes: dict[str, Any],
) -> int:
    raw_fields = parse_notes.get("unmapped_fields") or []
    raw_fields_json = _canonical_json(raw_fields)
    parse_notes_json = _canonical_json(parse_notes)
    product_label = _optional_string(raw_product_label, "product")
    row = connection.execute(
        """
        SELECT id, raw_product_label_ja, raw_fields_json, parse_notes_json
        FROM source_observations
        WHERE card_printing_id = ?
          AND source_url = ?
          AND fetched_at = ?
          AND parser_version = ?
        """,
        (printing_id, source_url, fetched_at, parser_version),
    ).fetchone()
    if row is None:
        cursor = connection.execute(
            """
            INSERT INTO source_observations (
                card_printing_id,
                import_batch_id,
                source_url,
                fetched_at,
                parser_version,
                raw_product_label_ja,
                raw_fields_json,
                parse_notes_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                printing_id,
                batch_id,
                source_url,
                fetched_at,
                parser_version,
                product_label,
                raw_fields_json,
                parse_notes_json,
            ),
        )
        return int(cursor.lastrowid)
    _require_equal(
        row["raw_product_label_ja"],
        product_label,
        f"Source Observation {row['id']} raw_product_label_ja",
    )
    _require_equal(
        row["raw_fields_json"],
        raw_fields_json,
        f"Source Observation {row['id']} raw_fields_json",
    )
    _require_equal(
        row["parse_notes_json"],
        parse_notes_json,
        f"Source Observation {row['id']} parse_notes_json",
    )
    return int(row["id"])


def _upsert_text_revision(
    connection: sqlite3.Connection,
    *,
    gameplay_card_id: int,
    observation_id: int,
    fetched_at: str,
    raw_text: Any,
) -> dict[str, bool]:
    text = _optional_string(raw_text, "raw_effect_text")
    if text is None:
        return {"new_text_revision": False, "reused_text_revision": False}
    normalized_text = normalize_effect_text(text)
    if not normalized_text:
        return {"new_text_revision": False, "reused_text_revision": False}
    raw_text_hash = hash_effect_text(normalized_text)
    row = connection.execute(
        """
        SELECT id, raw_effect_text_ja
        FROM card_text_revisions
        WHERE gameplay_card_id = ? AND raw_text_hash = ?
        """,
        (gameplay_card_id, raw_text_hash),
    ).fetchone()
    if row is None:
        revision_number = int(
            connection.execute(
                """
                SELECT COALESCE(MAX(revision_number), 0) + 1
                FROM card_text_revisions
                WHERE gameplay_card_id = ?
                """,
                (gameplay_card_id,),
            ).fetchone()[0]
        )
        cursor = connection.execute(
            """
            INSERT INTO card_text_revisions (
                gameplay_card_id,
                revision_number,
                raw_effect_text_ja,
                raw_text_hash,
                revision_status,
                created_from_observation_id,
                first_observed_at,
                last_observed_at
            )
            VALUES (?, ?, ?, ?, 'provisional', ?, ?, ?)
            """,
            (
                gameplay_card_id,
                revision_number,
                normalized_text,
                raw_text_hash,
                observation_id,
                fetched_at,
                fetched_at,
            ),
        )
        revision_id = int(cursor.lastrowid)
        outcome = {"new_text_revision": True, "reused_text_revision": False}
    else:
        _require_equal(
            row["raw_effect_text_ja"],
            normalized_text,
            f"Card Text Revision {row['id']} raw text",
        )
        revision_id = int(row["id"])
        connection.execute(
            """
            UPDATE card_text_revisions
            SET first_observed_at = MIN(first_observed_at, ?),
                last_observed_at = MAX(last_observed_at, ?)
            WHERE id = ?
            """,
            (fetched_at, fetched_at, revision_id),
        )
        outcome = {"new_text_revision": False, "reused_text_revision": True}
    connection.execute(
        """
        INSERT OR IGNORE INTO card_text_revision_observations (
            text_revision_id,
            source_observation_id
        )
        VALUES (?, ?)
        """,
        (revision_id, observation_id),
    )
    return outcome


def _upsert_entities(
    connection: sqlite3.Connection,
    *,
    gameplay_card_id: int,
    observation_id: int,
    parse_notes: dict[str, Any],
    normalization: EntityNormalization,
    review_candidates: set[tuple[str, str]],
) -> None:
    fields = parse_notes.get("unmapped_fields") or []
    if not isinstance(fields, list):
        raise CardImportValidationError("parse_notes.unmapped_fields must be an array")
    for field in fields:
        if not isinstance(field, dict):
            raise CardImportValidationError("unmapped_fields entries must be objects")
        entity_type = ENTITY_SOURCE_LABELS.get(field.get("label"))
        if entity_type is None:
            continue
        raw_value = field.get("raw_text")
        if not isinstance(raw_value, str) or not raw_value:
            raise CardImportValidationError(
                f"{entity_type} source label must contain Japanese raw text"
            )
        entities = normalization.resolve(entity_type, raw_value)
        if entities is None:
            review_candidates.add((entity_type, raw_value))
            connection.execute(
                """
                INSERT OR IGNORE INTO normalization_candidates (
                    entity_type,
                    raw_value_ja,
                    first_source_observation_id,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (entity_type, raw_value, observation_id, _utc_now()),
            )
            continue
        for entity in entities:
            entity_id = _upsert_normalized_entity(
                connection,
                entity_type=entity_type,
                entity=entity,
            )
            relation_table = (
                "gameplay_card_works"
                if entity_type == "work"
                else "gameplay_card_units"
            )
            entity_column = "work_id" if entity_type == "work" else "unit_id"
            connection.execute(
                f"""
                INSERT OR IGNORE INTO {relation_table} (
                    gameplay_card_id,
                    {entity_column},
                    source_observation_id,
                    raw_label_ja
                )
                VALUES (?, ?, ?, ?)
                """,
                (gameplay_card_id, entity_id, observation_id, raw_value),
            )


def _upsert_normalized_entity(
    connection: sqlite3.Connection,
    *,
    entity_type: str,
    entity: NormalizedEntity,
) -> int:
    table = "works" if entity_type == "work" else "units"
    key_column = "work_key" if entity_type == "work" else "unit_key"
    row = connection.execute(
        f"""
        SELECT id, canonical_name_ja
        FROM {table}
        WHERE {key_column} = ?
        """,
        (entity.key,),
    ).fetchone()
    if row is None:
        cursor = connection.execute(
            f"""
            INSERT INTO {table} ({key_column}, canonical_name_ja)
            VALUES (?, ?)
            """,
            (entity.key, entity.canonical_name_ja),
        )
        return int(cursor.lastrowid)
    _require_equal(
        row["canonical_name_ja"],
        entity.canonical_name_ja,
        f"{entity_type} {entity.key} canonical_name_ja",
    )
    return int(row["id"])


def _upsert_printing_references(
    connection: sqlite3.Connection,
    *,
    printing_id: int,
    observation_id: int,
    card_code: str,
    related_ids: Any,
) -> None:
    if related_ids is None:
        return
    if not isinstance(related_ids, list):
        raise CardImportValidationError("related_printing_ids must be an array")
    for related_card_id in related_ids:
        if not isinstance(related_card_id, str) or not related_card_id:
            raise CardImportValidationError(
                "related_printing_ids entries must be non-empty strings"
            )
        related_card_code = derive_card_code(related_card_id)
        if related_card_code != card_code:
            raise CardImportConflictError(
                f"related printing {related_card_id!r} does not share "
                f"card_code {card_code!r}"
            )
        connection.execute(
            """
            INSERT OR IGNORE INTO printing_references (
                source_printing_id,
                related_card_id,
                related_card_code,
                source_observation_id
            )
            VALUES (?, ?, ?, ?)
            """,
            (printing_id, related_card_id, related_card_code, observation_id),
        )


def _merge_optional_value(
    connection: sqlite3.Connection,
    *,
    table: str,
    row_id: int,
    column: str,
    existing: Any,
    incoming: Any,
    identity: str,
    id_column: str = "id",
) -> None:
    if incoming is None:
        return
    if existing is None:
        connection.execute(
            f"UPDATE {table} SET {column} = ? WHERE {id_column} = ?",
            (incoming, row_id),
        )
        return
    _require_equal(existing, incoming, f"{identity} {column}")


def _require_equal(existing: Any, incoming: Any, identity: str) -> None:
    if existing != incoming:
        raise CardImportConflictError(
            f"{identity} conflict: existing={existing!r}, incoming={incoming!r}"
        )


def _required_string(
    record: dict[str, Any],
    field: str,
    record_index: int,
) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise CardImportValidationError(
            f"record {record_index}: {field} must be a non-empty string"
        )
    return value


def _safe_record_string(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _split_validation_message(message: str) -> tuple[str, str]:
    normalized = message.strip()
    if ": " not in normalized:
        return "record", normalized
    prefix, detail = normalized.split(": ", 1)
    if prefix.startswith("record "):
        return "record", detail
    return prefix, detail


def _format_validation_errors(summary: ValidationSummary) -> str:
    errors = [issue for issue in summary.issues if issue.severity == "error"]
    if not errors:
        return "validation failed"
    preview = "; ".join(
        f"record {issue.record_index} [{issue.field}] {issue.message}"
        for issue in errors[:5]
    )
    suffix = "" if len(errors) <= 5 else f"; ... {len(errors) - 5} more error(s)"
    return preview + suffix


def _required_mapping_string(record: dict[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise CardImportValidationError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CardImportValidationError(f"{field} must be a string or null")
    return value or None


def _normalize_card_type(value: Any, record_index: int) -> str:
    if not isinstance(value, str) or value not in CARD_TYPE_MAP:
        raise CardImportValidationError(
            f"record {record_index}: unknown card_type {value!r}"
        )
    return CARD_TYPE_MAP[value]


def _optional_non_negative_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CardImportValidationError(
            f"{field} must be a non-negative integer or null"
        )
    return value


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise CardImportValidationError(f"{field} must be a positive integer")
    return value


def _optional_color_slot(value: Any, field: str) -> str | None:
    result = _optional_string(value, field)
    if result is not None and result not in HEART_COLOR_SLOTS:
        raise CardImportValidationError(f"{field} has unknown color slot {result!r}")
    return result


def _card_list_root(source_url: str) -> str:
    parsed = urllib.parse.urlsplit(source_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.hostname.lower() != "llofficial-cardgame.com"
    ):
        raise CardImportValidationError(
            f"source_url is not an official HTTPS card-list URL: {source_url!r}"
        )
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, "/cardlist/", "", "")
    )


def _common_parser_version(records: list[dict[str, Any]]) -> str | None:
    versions = {
        item.get("parser_version")
        for item in records
        if isinstance(item.get("parser_version"), str)
    }
    if not versions:
        return None
    if len(versions) == 1:
        return str(next(iter(versions)))
    return "mixed"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _validate_timestamp(value: str, record_index: int) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CardImportValidationError(
            f"record {record_index}: fetched_at must be ISO 8601"
        ) from exc
    if parsed.tzinfo is None:
        raise CardImportValidationError(
            f"record {record_index}: fetched_at must include a timezone"
        )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _card_code_matches_identity(
    *,
    card_id: str,
    card_code: str,
    card_type: str,
    parse_notes: Any,
) -> bool:
    derived = derive_card_code(card_id)
    if derived == card_code:
        return True
    if card_type == "energy" and card_code == card_id:
        return True
    if isinstance(parse_notes, dict):
        strategy = parse_notes.get("gameplay_card_code_strategy")
        if strategy == "full_card_id_conflict_fallback" and card_code == card_id:
            return True
    return False


def _names_match(existing: str, incoming: str) -> bool:
    return _normalize_name_identity(existing) == _normalize_name_identity(incoming)


def _normalize_name_identity(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return "".join(
        part
        for part in normalized
        if not part.isspace() and part not in {"+", "＋"}
    )


def _looks_like_name_fallback(value: str, card_code: str) -> bool:
    normalized_name = _normalize_name_identity(value)
    normalized_code = _normalize_name_identity(card_code)
    return normalized_name == normalized_code or (
        normalized_name.startswith(normalized_code)
        and len(normalized_name) > len(normalized_code)
        and normalized_name[len(normalized_code)] == "-"
    )
