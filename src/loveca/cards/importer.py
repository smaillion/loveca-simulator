"""Import normalized local card JSON into the versioned SQLite catalog."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
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
) -> ImportSummary:
    input_bytes = input_path.read_bytes()
    normalization_bytes = normalization_path.read_bytes()
    records = _load_card_records(input_bytes, input_path)
    normalization = _load_normalization(normalization_bytes, normalization_path)
    parser_version = _common_parser_version(records)

    initialize_database(database_path)
    started_at = _utc_now()

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

        review_candidates: set[tuple[str, str]] = set()
        try:
            connection.execute("BEGIN IMMEDIATE")
            for index, record in enumerate(records):
                _import_card_record(
                    connection,
                    record=record,
                    record_index=index,
                    batch_id=batch_id,
                    normalization=normalization,
                    review_candidates=review_candidates,
                )

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
    )


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
) -> None:
    card_id = _required_string(record, "card_id", record_index)
    card_code = _required_string(record, "card_code", record_index)
    if derive_card_code(card_id) != card_code:
        raise CardImportValidationError(
            f"record {record_index}: card_id {card_id!r} does not derive "
            f"card_code {card_code!r}"
        )

    name = _required_string(record, "name", record_index)
    card_type = _normalize_card_type(record.get("card_type"), record_index)
    card_set_code = _required_string(record, "product_code", record_index)
    source_url = _required_string(record, "source_url", record_index)
    fetched_at = _required_string(record, "fetched_at", record_index)
    _validate_timestamp(fetched_at, record_index)
    parser_version = _required_string(record, "parser_version", record_index)
    parse_notes = record.get("parse_notes")
    if not isinstance(parse_notes, dict):
        raise CardImportValidationError(
            f"record {record_index}: parse_notes must be an object"
        )

    _validate_type_attributes(record, card_type, record_index)
    card_set_id = _upsert_card_set(
        connection,
        card_set_code=card_set_code,
        source_url=_card_list_root(source_url),
    )
    gameplay_card_id = _upsert_gameplay_card(
        connection,
        card_code=card_code,
        name=name,
        card_type=card_type,
    )
    printing_id = _upsert_card_printing(
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
    _upsert_text_revision(
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


def _upsert_card_set(
    connection: sqlite3.Connection,
    *,
    card_set_code: str,
    source_url: str,
) -> int:
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
        return int(cursor.lastrowid)
    _merge_optional_value(
        connection,
        table="card_sets",
        row_id=int(row["id"]),
        column="source_url",
        existing=row["source_url"],
        incoming=source_url,
        identity=f"Card Set {card_set_code}",
    )
    return int(row["id"])


def _upsert_gameplay_card(
    connection: sqlite3.Connection,
    *,
    card_code: str,
    name: str,
    card_type: str,
) -> int:
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
        return int(cursor.lastrowid)
    _require_equal(
        row["canonical_name_ja"],
        name,
        f"Gameplay Card {card_code} canonical_name_ja",
    )
    _require_equal(
        row["card_type"],
        card_type,
        f"Gameplay Card {card_code} card_type",
    )
    return int(row["id"])


def _upsert_card_printing(
    connection: sqlite3.Connection,
    *,
    card_id: str,
    gameplay_card_id: int,
    card_set_id: int,
    rarity: Any,
    image_url: Any,
) -> int:
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
        return int(cursor.lastrowid)
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
    return int(row["id"])


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
) -> None:
    text = _optional_string(raw_text, "raw_effect_text")
    if text is None:
        return
    normalized_text = normalize_effect_text(text)
    if not normalized_text:
        return
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
