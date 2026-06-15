"""Read-only catalog queries for the full imported card database."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from loveca.db.bootstrap import connect_database, get_schema_version
from loveca.db.schema import SCHEMA_VERSION
from loveca.simulation.effects import (
    DEFAULT_EFFECT_REGISTRY,
    load_effect_registry,
    validate_registry_for_cards,
)


class CardCatalogError(RuntimeError):
    """Raised when the local card catalog cannot be queried."""


def list_catalog_cards(
    database_path: Path,
    *,
    query: str | None = None,
    card_type: str | None = None,
    product_code: str | None = None,
    work_key: str | None = None,
    unit_key: str | None = None,
    basic_heart_color: str | None = None,
    member_cost_min: int | None = None,
    member_cost_max: int | None = None,
    member_blade_min: int | None = None,
    member_blade_max: int | None = None,
    member_blade_heart_color: str | None = None,
    required_heart_color: str | None = None,
    required_heart_min: int | None = None,
    required_heart_max: int | None = None,
    live_score_min: int | None = None,
    live_score_max: int | None = None,
    has_live_blade_heart: bool | None = None,
    live_blade_heart_color: str | None = None,
    review_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    _require_schema(database_path)
    summary_rows = _load_summary_rows(database_path)
    filtered = [
        row
        for row in summary_rows
        if _matches_summary(
            row,
            query=query,
            card_type=card_type,
            product_code=product_code,
            work_key=work_key,
            unit_key=unit_key,
            basic_heart_color=basic_heart_color,
            member_cost_min=member_cost_min,
            member_cost_max=member_cost_max,
            member_blade_min=member_blade_min,
            member_blade_max=member_blade_max,
            member_blade_heart_color=member_blade_heart_color,
            required_heart_color=required_heart_color,
            required_heart_min=required_heart_min,
            required_heart_max=required_heart_max,
            live_score_min=live_score_min,
            live_score_max=live_score_max,
            has_live_blade_heart=has_live_blade_heart,
            live_blade_heart_color=live_blade_heart_color,
            review_only=review_only,
        )
    ]
    total = len(filtered)
    return {
        "items": filtered[offset : offset + limit],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def get_catalog_card(database_path: Path, card_code: str) -> dict[str, Any]:
    _require_schema(database_path)
    with closing(connect_database(database_path)) as connection:
        row = connection.execute(
            """
            SELECT
                card.id AS gameplay_card_id,
                card.card_code,
                card.canonical_name_ja,
                card.card_type,
                card.validation_status AS card_validation_status,
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
            WHERE card.card_code = ?
            """,
            (card_code,),
        ).fetchone()
        if row is None:
            raise CardCatalogError(f"card not found: {card_code}")

        gameplay_card_id = int(row["gameplay_card_id"])
        registry = load_effect_registry(DEFAULT_EFFECT_REGISTRY)
        valid_effects, effect_errors = validate_registry_for_cards(
            connection, registry, {card_code}
        )
        printings = _load_printings(connection, gameplay_card_id)
        source_observations = _load_source_observations(connection, gameplay_card_id)
        text_revisions = _load_text_revisions(connection, gameplay_card_id)
        heart_values = _load_heart_values(connection, gameplay_card_id)
        special_blade_hearts = _load_special_blade_hearts(
            connection, gameplay_card_id
        )
        works = _load_entities(connection, gameplay_card_id, "work")
        units = _load_entities(connection, gameplay_card_id, "unit")
        review_candidates = _load_review_candidates(connection, gameplay_card_id)
        printing_references = _load_printing_references(connection, gameplay_card_id)

    return {
        "card": {
            "gameplay_card_id": gameplay_card_id,
            "card_code": str(row["card_code"]),
            "name_ja": str(row["canonical_name_ja"]),
            "card_type": str(row["card_type"]),
            "validation_status": str(row["card_validation_status"]),
            "cost": row["cost"],
            "blade": row["blade"],
            "member_blade_heart_color_slot": row["member_blade_heart_color_slot"],
            "score": row["score"],
            "live_blade_heart_color_slot": row["live_blade_heart_color_slot"],
            "heart_values": heart_values,
            "special_blade_hearts": special_blade_hearts,
            "works": works,
            "units": units,
            "review_candidates": review_candidates,
            "printing_references": printing_references,
            "effect_registry_status": _effect_registry_status(
                card_code, valid_effects, effect_errors
            ),
            "effect_registry_errors": effect_errors.get(card_code, []),
            "effects": _effect_summaries(card_code, valid_effects, effect_errors),
        },
        "printings": printings,
        "source_observations": source_observations,
        "text_revisions": text_revisions,
    }


def list_catalog_facets(database_path: Path) -> dict[str, Any]:
    _require_schema(database_path)
    with closing(connect_database(database_path)) as connection:
        work_rows = connection.execute(
            """
            SELECT DISTINCT work.work_key, work.canonical_name_ja
            FROM gameplay_card_works AS link
            JOIN works AS work
                ON work.id = link.work_id
            ORDER BY work.canonical_name_ja, work.work_key
            """
        ).fetchall()
        unit_rows = connection.execute(
            """
            SELECT DISTINCT unit.unit_key, unit.canonical_name_ja
            FROM gameplay_card_units AS link
            JOIN units AS unit
                ON unit.id = link.unit_id
            ORDER BY unit.canonical_name_ja, unit.unit_key
            """
        ).fetchall()
    return {
        "works": [
            {
                "work_key": str(row["work_key"]),
                "canonical_name_ja": str(row["canonical_name_ja"]),
            }
            for row in work_rows
        ],
        "units": [
            {
                "unit_key": str(row["unit_key"]),
                "canonical_name_ja": str(row["canonical_name_ja"]),
            }
            for row in unit_rows
        ],
    }


def list_review_candidates(
    database_path: Path,
    *,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    _require_schema(database_path)
    with closing(connect_database(database_path)) as connection:
        rows = connection.execute(
            """
            SELECT
                candidate.id,
                candidate.entity_type,
                candidate.raw_value_ja,
                candidate.review_status,
                candidate.created_at,
                observation.source_url,
                observation.fetched_at,
                printing.card_id,
                card.card_code,
                card.canonical_name_ja,
                card.card_type
            FROM normalization_candidates AS candidate
            JOIN source_observations AS observation
                ON observation.id = candidate.first_source_observation_id
            JOIN card_printings AS printing
                ON printing.id = observation.card_printing_id
            JOIN gameplay_cards AS card
                ON card.id = printing.gameplay_card_id
            ORDER BY candidate.created_at DESC, candidate.id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        total = connection.execute(
            "SELECT COUNT(*) FROM normalization_candidates"
        ).fetchone()[0]
    return {
        "items": [
            {
                "candidate_id": int(row["id"]),
                "entity_type": str(row["entity_type"]),
                "raw_value_ja": str(row["raw_value_ja"]),
                "review_status": str(row["review_status"]),
                "created_at": str(row["created_at"]),
                "source_url": str(row["source_url"]),
                "fetched_at": str(row["fetched_at"]),
                "card_id": str(row["card_id"]),
                "card_code": str(row["card_code"]),
                "name_ja": str(row["canonical_name_ja"]),
                "card_type": str(row["card_type"]),
            }
            for row in rows
        ],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


def _require_schema(database_path: Path) -> None:
    version = get_schema_version(database_path)
    if version != SCHEMA_VERSION:
        raise CardCatalogError(f"catalog requires card schema v{SCHEMA_VERSION}")


def _load_summary_rows(
    database_path: Path,
) -> list[dict[str, Any]]:
    with closing(connect_database(database_path)) as connection:
        rows = connection.execute(_summary_query()).fetchall()
        work_key_map = _load_entity_key_map(connection, "work")
        unit_key_map = _load_entity_key_map(connection, "unit")
        heart_map = _load_summary_heart_values(connection)
    return [
        _serialize_summary_row(
            row,
            work_keys=work_key_map.get(int(row["gameplay_card_id"]), []),
            unit_keys=unit_key_map.get(int(row["gameplay_card_id"]), []),
            heart_values=heart_map.get(
                int(row["gameplay_card_id"]),
                {"basic": {}, "required": {}},
            ),
        )
        for row in rows
    ]


def _summary_query() -> str:
    return """
        SELECT
            card.id AS gameplay_card_id,
            card.card_code,
            card.canonical_name_ja,
            card.card_type,
            card.validation_status AS card_validation_status,
            member.cost,
            member.blade,
            member.blade_heart_color_slot AS member_blade_heart_color_slot,
            live.score,
            live.blade_heart_color_slot AS live_blade_heart_color_slot,
            printing.card_id AS primary_card_id,
            card_set.card_set_code AS primary_card_set_code,
            printing.rarity_ja AS primary_rarity_ja,
            printing.image_url AS primary_image_url,
            printing.card_id AS searchable_card_ids,
            (
                SELECT COUNT(*)
                FROM card_printings AS nested_printing
                WHERE nested_printing.gameplay_card_id = card.id
            ) AS printing_count,
            (
                SELECT COUNT(*)
                FROM card_text_revisions AS revision
                WHERE revision.gameplay_card_id = card.id
            ) AS revision_count,
            (
                SELECT COUNT(*)
                FROM source_observations AS observation
                JOIN card_printings AS printing
                    ON printing.id = observation.card_printing_id
                WHERE printing.gameplay_card_id = card.id
            ) AS observation_count,
            (
                SELECT COUNT(*)
                FROM normalization_candidates AS candidate
                JOIN source_observations AS observation
                    ON observation.id = candidate.first_source_observation_id
                JOIN card_printings AS printing
                    ON printing.id = observation.card_printing_id
                WHERE printing.gameplay_card_id = card.id
                  AND candidate.review_status = 'pending'
            ) AS pending_candidate_count,
            (
                SELECT COUNT(*)
                FROM printing_references AS reference
                JOIN card_printings AS printing
                    ON printing.id = reference.source_printing_id
                WHERE printing.gameplay_card_id = card.id
                  AND reference.review_status = 'unfetched'
                ) AS unresolved_reference_count
        FROM card_printings AS printing
        JOIN gameplay_cards AS card
            ON card.id = printing.gameplay_card_id
        JOIN card_sets AS card_set
            ON card_set.id = printing.card_set_id
        LEFT JOIN member_card_attributes AS member
            ON member.gameplay_card_id = card.id
        LEFT JOIN live_card_attributes AS live
            ON live.gameplay_card_id = card.id
        ORDER BY card.canonical_name_ja, card.card_code, printing.card_id
    """


def _serialize_summary_row(
    row: sqlite3.Row,
    *,
    work_keys: list[str],
    unit_keys: list[str],
    heart_values: dict[str, dict[str, int]],
) -> dict[str, Any]:
    basic_hearts = heart_values.get("basic", {})
    required_hearts = heart_values.get("required", {})
    return {
        "gameplay_card_id": int(row["gameplay_card_id"]),
        "card_code": str(row["card_code"]),
        "name_ja": str(row["canonical_name_ja"]),
        "card_type": str(row["card_type"]),
        "validation_status": str(row["card_validation_status"]),
        "card_id": row["primary_card_id"],
        "card_set_code": row["primary_card_set_code"],
        "rarity_ja": row["primary_rarity_ja"],
        "image_url": row["primary_image_url"],
        "searchable_card_ids": row["searchable_card_ids"],
        "cost": row["cost"],
        "blade": row["blade"],
        "member_blade_heart_color_slot": row["member_blade_heart_color_slot"],
        "score": row["score"],
        "live_blade_heart_color_slot": row["live_blade_heart_color_slot"],
        "basic_heart_by_color": basic_hearts,
        "basic_heart_total": sum(basic_hearts.values()),
        "required_heart_by_color": required_hearts,
        "required_heart_total": sum(required_hearts.values()),
        "has_live_blade_heart": row["live_blade_heart_color_slot"] is not None,
        "printing_count": int(row["printing_count"]),
        "revision_count": int(row["revision_count"]),
        "observation_count": int(row["observation_count"]),
        "pending_candidate_count": int(row["pending_candidate_count"]),
        "unresolved_reference_count": int(row["unresolved_reference_count"]),
        "review_issue_count": int(row["pending_candidate_count"])
        + int(row["unresolved_reference_count"]),
        "work_keys": work_keys,
        "unit_keys": unit_keys,
    }


def _matches_summary(
    row: dict[str, Any],
    *,
    query: str | None,
    card_type: str | None,
    product_code: str | None,
    work_key: str | None,
    unit_key: str | None,
    basic_heart_color: str | None,
    member_cost_min: int | None,
    member_cost_max: int | None,
    member_blade_min: int | None,
    member_blade_max: int | None,
    member_blade_heart_color: str | None,
    required_heart_color: str | None,
    required_heart_min: int | None,
    required_heart_max: int | None,
    live_score_min: int | None,
    live_score_max: int | None,
    has_live_blade_heart: bool | None,
    live_blade_heart_color: str | None,
    review_only: bool,
) -> bool:
    member_filters_active = any(
        value is not None and value != ""
        for value in (
            basic_heart_color,
            member_cost_min,
            member_cost_max,
            member_blade_min,
            member_blade_max,
            member_blade_heart_color,
        )
    )
    live_filters_active = any(
        value is not None and value != ""
        for value in (
            required_heart_color,
            required_heart_min,
            required_heart_max,
            live_score_min,
            live_score_max,
            has_live_blade_heart,
            live_blade_heart_color,
        )
    )
    if card_type and row["card_type"] != card_type:
        return False
    if product_code and row["card_set_code"] != product_code:
        return False
    if work_key and work_key not in row["work_keys"]:
        return False
    if unit_key and unit_key not in row["unit_keys"]:
        return False
    if row["card_type"] == "member":
        if basic_heart_color and row["basic_heart_by_color"].get(basic_heart_color, 0) <= 0:
            return False
        if (
            member_blade_heart_color
            and row["member_blade_heart_color_slot"] != member_blade_heart_color
        ):
            return False
        if not _matches_numeric_filter(row["cost"], member_cost_min, member_cost_max):
            return False
        if not _matches_numeric_filter(row["blade"], member_blade_min, member_blade_max):
            return False
        if not card_type and live_filters_active and not member_filters_active:
            return False
    elif row["card_type"] == "live":
        if (
            required_heart_color
            and row["required_heart_by_color"].get(required_heart_color, 0) <= 0
        ):
            return False
        required_heart_value = (
            row["required_heart_by_color"].get(required_heart_color, 0)
            if required_heart_color
            else row["required_heart_total"]
        )
        if not _matches_numeric_filter(
            required_heart_value, required_heart_min, required_heart_max
        ):
            return False
        if not _matches_numeric_filter(row["score"], live_score_min, live_score_max):
            return False
        if (
            has_live_blade_heart is not None
            and row["has_live_blade_heart"] != has_live_blade_heart
        ):
            return False
        if live_blade_heart_color and row["live_blade_heart_color_slot"] != live_blade_heart_color:
            return False
        if not card_type and member_filters_active and not live_filters_active:
            return False
    elif not card_type and (member_filters_active or live_filters_active):
        return False
    if review_only and row["review_issue_count"] == 0:
        return False
    if query:
        normalized = query.strip().lower()
        if normalized:
            haystack = " ".join(
                str(value).lower()
                for value in (
                    row["card_code"],
                    row["name_ja"],
                    row["card_id"],
                    row["searchable_card_ids"],
                    row["card_set_code"],
                    row["rarity_ja"],
                )
                if value is not None
            )
            if normalized not in haystack:
                return False
    return True


def _matches_numeric_filter(
    value: Any,
    minimum: int | None,
    maximum: int | None,
) -> bool:
    if minimum is None and maximum is None:
        return True
    if value is None:
        return False
    numeric = int(value)
    if minimum is not None and numeric < minimum:
        return False
    if maximum is not None and numeric > maximum:
        return False
    return True


def _load_summary_heart_values(
    connection: sqlite3.Connection,
) -> dict[int, dict[str, dict[str, int]]]:
    mapping: dict[int, dict[str, dict[str, int]]] = {}
    rows = connection.execute(
        """
        SELECT gameplay_card_id, heart_role, color_slot, value
        FROM card_heart_values
        ORDER BY gameplay_card_id, heart_role, color_slot
        """
    ).fetchall()
    for row in rows:
        gameplay_card_id = int(row["gameplay_card_id"])
        role = str(row["heart_role"])
        color_slot = str(row["color_slot"])
        value = int(row["value"])
        grouped = mapping.setdefault(gameplay_card_id, {"basic": {}, "required": {}})
        grouped[role][color_slot] = value
    return mapping


def _load_printings(connection: sqlite3.Connection, gameplay_card_id: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            printing.card_id,
            card_set.card_set_code,
            printing.rarity_ja,
            printing.image_url,
            (
                SELECT observation.source_url
                FROM source_observations AS observation
                WHERE observation.card_printing_id = printing.id
                ORDER BY observation.id
                LIMIT 1
            ) AS source_url,
            (
                SELECT observation.fetched_at
                FROM source_observations AS observation
                WHERE observation.card_printing_id = printing.id
                ORDER BY observation.id
                LIMIT 1
            ) AS fetched_at,
            (
                SELECT observation.parser_version
                FROM source_observations AS observation
                WHERE observation.card_printing_id = printing.id
                ORDER BY observation.id
                LIMIT 1
            ) AS parser_version,
            (
                SELECT observation.raw_product_label_ja
                FROM source_observations AS observation
                WHERE observation.card_printing_id = printing.id
                ORDER BY observation.id
                LIMIT 1
            ) AS raw_product_label_ja,
            (
                SELECT observation.raw_fields_json
                FROM source_observations AS observation
                WHERE observation.card_printing_id = printing.id
                ORDER BY observation.id
                LIMIT 1
            ) AS raw_fields_json,
            (
                SELECT observation.parse_notes_json
                FROM source_observations AS observation
                WHERE observation.card_printing_id = printing.id
                ORDER BY observation.id
                LIMIT 1
            ) AS parse_notes_json,
            (
                SELECT observation.language
                FROM source_observations AS observation
                WHERE observation.card_printing_id = printing.id
                ORDER BY observation.id
                LIMIT 1
            ) AS language
        FROM card_printings AS printing
        JOIN card_sets AS card_set
            ON card_set.id = printing.card_set_id
        WHERE printing.gameplay_card_id = ?
        ORDER BY printing.card_id
        """,
        (gameplay_card_id,),
    ).fetchall()
    return [
        {
            "card_id": str(row["card_id"]),
            "card_set_code": str(row["card_set_code"]),
            "rarity_ja": row["rarity_ja"],
            "image_url": row["image_url"],
            "source_url": row["source_url"],
            "fetched_at": row["fetched_at"],
            "parser_version": row["parser_version"],
            "raw_product_label_ja": row["raw_product_label_ja"],
            "language": row["language"],
            "raw_fields": _safe_json_loads(row["raw_fields_json"]),
            "parse_notes": _safe_json_loads(row["parse_notes_json"]),
        }
        for row in rows
    ]


def _load_source_observations(
    connection: sqlite3.Connection,
    gameplay_card_id: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            observation.id,
            observation.source_url,
            observation.source_version,
            observation.fetched_at,
            observation.parser_version,
            observation.language,
            observation.raw_product_label_ja,
            observation.raw_fields_json,
            observation.parse_notes_json,
            printing.card_id
        FROM source_observations AS observation
        JOIN card_printings AS printing
            ON printing.id = observation.card_printing_id
        WHERE printing.gameplay_card_id = ?
        ORDER BY observation.id
        """,
        (gameplay_card_id,),
    ).fetchall()
    return [
        {
            "source_observation_id": int(row["id"]),
            "source_url": str(row["source_url"]),
            "source_version": row["source_version"],
            "fetched_at": str(row["fetched_at"]),
            "parser_version": str(row["parser_version"]),
            "language": str(row["language"]),
            "raw_product_label_ja": row["raw_product_label_ja"],
            "card_id": str(row["card_id"]),
            "raw_fields": _safe_json_loads(row["raw_fields_json"]),
            "parse_notes": _safe_json_loads(row["parse_notes_json"]),
        }
        for row in rows
    ]


def _load_text_revisions(
    connection: sqlite3.Connection,
    gameplay_card_id: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            revision.id,
            revision.revision_number,
            revision.raw_effect_text_ja,
            revision.raw_text_hash,
            revision.revision_status,
            revision.first_observed_at,
            revision.last_observed_at,
            (
                SELECT observation.source_url
                FROM card_text_revision_observations AS link
                JOIN source_observations AS observation
                    ON observation.id = link.source_observation_id
                WHERE link.text_revision_id = revision.id
                ORDER BY observation.id
                LIMIT 1
            ) AS source_url
        FROM card_text_revisions AS revision
        WHERE revision.gameplay_card_id = ?
        GROUP BY revision.id
        ORDER BY revision.revision_number
        """,
        (gameplay_card_id,),
    ).fetchall()
    return [
        {
            "revision_id": int(row["id"]),
            "revision_number": int(row["revision_number"]),
            "raw_effect_text_ja": str(row["raw_effect_text_ja"]),
            "raw_text_hash": str(row["raw_text_hash"]),
            "revision_status": str(row["revision_status"]),
            "first_observed_at": str(row["first_observed_at"]),
            "last_observed_at": str(row["last_observed_at"]),
            "source_url": str(row["source_url"]),
        }
        for row in rows
    ]


def _load_heart_values(
    connection: sqlite3.Connection,
    gameplay_card_id: int,
) -> dict[str, dict[str, int]]:
    hearts: dict[str, dict[str, int]] = {"basic": {}, "required": {}}
    for row in connection.execute(
        """
        SELECT heart_role, color_slot, value
        FROM card_heart_values
        WHERE gameplay_card_id = ?
        ORDER BY heart_role, color_slot
        """,
        (gameplay_card_id,),
    ):
        hearts[str(row["heart_role"])][str(row["color_slot"])] = int(row["value"])
    return hearts


def _load_special_blade_hearts(
    connection: sqlite3.Connection,
    gameplay_card_id: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT ordinal, effect_type, value, resolution_timing, source_alt, source_field
        FROM special_blade_hearts
        WHERE gameplay_card_id = ?
        ORDER BY ordinal
        """,
        (gameplay_card_id,),
    ).fetchall()
    return [
        {
            "ordinal": int(row["ordinal"]),
            "effect_type": str(row["effect_type"]),
            "value": row["value"],
            "resolution_timing": row["resolution_timing"],
            "source_alt": str(row["source_alt"]),
            "source_field": str(row["source_field"]),
        }
        for row in rows
    ]


def _load_entities(
    connection: sqlite3.Connection,
    gameplay_card_id: int,
    entity_type: str,
) -> list[dict[str, Any]]:
    if entity_type == "work":
        rows = connection.execute(
            """
            SELECT work.work_key, work.canonical_name_ja, link.raw_label_ja
            FROM gameplay_card_works AS link
            JOIN works AS work
                ON work.id = link.work_id
            WHERE link.gameplay_card_id = ?
            ORDER BY work.work_key, link.source_observation_id
            """,
            (gameplay_card_id,),
        ).fetchall()
        return _dedupe_entities(
            {
                "work_key": str(row["work_key"]),
                "canonical_name_ja": str(row["canonical_name_ja"]),
                "raw_label_ja": str(row["raw_label_ja"]),
            }
            for row in rows
        )
    rows = connection.execute(
        """
        SELECT unit.unit_key, unit.canonical_name_ja, link.raw_label_ja
        FROM gameplay_card_units AS link
        JOIN units AS unit
            ON unit.id = link.unit_id
        WHERE link.gameplay_card_id = ?
        ORDER BY unit.unit_key, link.source_observation_id
        """,
        (gameplay_card_id,),
    ).fetchall()
    return _dedupe_entities(
        {
            "unit_key": str(row["unit_key"]),
            "canonical_name_ja": str(row["canonical_name_ja"]),
            "raw_label_ja": str(row["raw_label_ja"]),
        }
        for row in rows
    )


def _dedupe_entities(entries: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for entry in entries:
        fingerprint = tuple(sorted(entry.items()))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        result.append(entry)
    return result


def _load_entity_key_map(
    connection: sqlite3.Connection,
    entity_type: str,
) -> dict[int, list[str]]:
    if entity_type == "work":
        rows = connection.execute(
            """
            SELECT link.gameplay_card_id, work.work_key AS entity_key
            FROM gameplay_card_works AS link
            JOIN works AS work
                ON work.id = link.work_id
            ORDER BY link.gameplay_card_id, work.work_key
            """
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT link.gameplay_card_id, unit.unit_key AS entity_key
            FROM gameplay_card_units AS link
            JOIN units AS unit
                ON unit.id = link.unit_id
            ORDER BY link.gameplay_card_id, unit.unit_key
            """
        ).fetchall()
    mapping: dict[int, list[str]] = {}
    for row in rows:
        gameplay_card_id = int(row["gameplay_card_id"])
        key = str(row["entity_key"])
        mapping.setdefault(gameplay_card_id, [])
        if key not in mapping[gameplay_card_id]:
            mapping[gameplay_card_id].append(key)
    return mapping


def _load_review_candidates(
    connection: sqlite3.Connection,
    gameplay_card_id: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            candidate.id,
            candidate.entity_type,
            candidate.raw_value_ja,
            candidate.review_status,
            candidate.created_at
        FROM normalization_candidates AS candidate
        JOIN source_observations AS observation
            ON observation.id = candidate.first_source_observation_id
        JOIN card_printings AS printing
            ON printing.id = observation.card_printing_id
        WHERE printing.gameplay_card_id = ?
        ORDER BY candidate.created_at DESC, candidate.id DESC
        """,
        (gameplay_card_id,),
    ).fetchall()
    return [
        {
            "candidate_id": int(row["id"]),
            "entity_type": str(row["entity_type"]),
            "raw_value_ja": str(row["raw_value_ja"]),
            "review_status": str(row["review_status"]),
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]


def _load_printing_references(
    connection: sqlite3.Connection,
    gameplay_card_id: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            reference.id,
            reference.related_card_id,
            reference.related_card_code,
            reference.review_status,
            reference.source_observation_id
        FROM printing_references AS reference
        JOIN card_printings AS printing
            ON printing.id = reference.source_printing_id
        WHERE printing.gameplay_card_id = ?
        ORDER BY reference.id
        """,
        (gameplay_card_id,),
    ).fetchall()
    return [
        {
            "reference_id": int(row["id"]),
            "related_card_id": str(row["related_card_id"]),
            "related_card_code": str(row["related_card_code"]),
            "review_status": str(row["review_status"]),
            "source_observation_id": int(row["source_observation_id"]),
        }
        for row in rows
    ]


def _safe_json_loads(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _effect_registry_status(
    card_code: str,
    valid_effects: dict[str, Any],
    effect_errors: dict[str, list[str]],
) -> str:
    if effect_errors.get(card_code):
        return "hash_mismatch"
    if any(effect.card_code == card_code for effect in valid_effects.values()):
        return "supported"
    return "unregistered"


def _effect_summaries(
    card_code: str,
    valid_effects: dict[str, Any],
    effect_errors: dict[str, list[str]],
) -> list[dict[str, Any]]:
    summaries = [
        {
            "effect_id": effect.effect_id,
            "label_ja": effect.label_ja,
            "effect_type": effect.effect_type,
            "timing": effect.timing,
            "trigger": effect.trigger,
            "execution_mode": effect.execution_mode,
            "frequency_limit": effect.frequency_limit,
            "is_optional": effect.is_optional,
            "simulation_support": effect.simulation_support,
            "review_status": effect.review_status,
        }
        for effect in valid_effects.values()
        if effect.card_code == card_code
    ]
    summaries.sort(key=lambda item: item["effect_id"])
    if summaries or not effect_errors.get(card_code):
        return summaries
    return []
