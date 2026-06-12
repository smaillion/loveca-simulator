"""Build match-local card definitions and instances from the card catalog."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from loveca.db.bootstrap import connect_database, get_schema_version
from loveca.db.schema import SCHEMA_VERSION
from loveca.decks.analyzer import DeckDatabaseError, DeckList
from loveca.simulation.models import (
    CardDefinition,
    CardInstance,
    PlayerState,
    SpecialBladeHeart,
)
from loveca.simulation.effects import (
    DEFAULT_EFFECT_REGISTRY,
    EffectDefinition,
    load_effect_registry,
    validate_registry_for_cards,
)


@dataclass(frozen=True)
class MatchPlayerInput:
    player_id: str
    name: str
    deck: DeckList


def build_match_cards(
    database_path: Path,
    players: tuple[MatchPlayerInput, MatchPlayerInput],
    effect_registry_path: Path = DEFAULT_EFFECT_REGISTRY,
) -> tuple[
    dict[str, CardInstance],
    dict[str, PlayerState],
    str,
    dict[str, EffectDefinition],
]:
    if get_schema_version(database_path) != SCHEMA_VERSION:
        raise DeckDatabaseError(f"match setup requires card schema v{SCHEMA_VERSION}")

    with closing(connect_database(database_path)) as connection:
        requested_codes = {
            entry.card_code
            for player in players
            for entry in (*player.deck.main_deck, *player.deck.energy_deck)
        }
        registry = load_effect_registry(effect_registry_path)
        effects, effect_errors = validate_registry_for_cards(
            connection, registry, requested_codes
        )
        definitions = _load_definitions(connection, players, effects, effect_errors)

    instances: dict[str, CardInstance] = {}
    states: dict[str, PlayerState] = {}
    for player in players:
        main_ids: list[str] = []
        energy_ids: list[str] = []
        sequence = 1
        for section, entries in (
            ("M", player.deck.main_deck),
            ("E", player.deck.energy_deck),
        ):
            target = main_ids if section == "M" else energy_ids
            for entry in entries:
                definition = definitions[(entry.card_code, entry.preferred_printing_id)]
                for _ in range(entry.quantity):
                    instance_id = f"{player.player_id}-{section}{sequence:03d}"
                    sequence += 1
                    instances[instance_id] = CardInstance(
                        instance_id=instance_id,
                        owner_id=player.player_id,
                        card=definition,
                        face_up=False,
                    )
                    target.append(instance_id)
        states[player.player_id] = PlayerState(
            player_id=player.player_id,
            name=player.name,
            main_deck=main_ids,
            energy_deck=energy_ids,
        )
    return instances, states, registry.registry_version, effects


def _load_definitions(
    connection: sqlite3.Connection,
    players: tuple[MatchPlayerInput, MatchPlayerInput],
    effects: dict[str, EffectDefinition],
    effect_errors: dict[str, list[str]],
) -> dict[tuple[str, str | None], CardDefinition]:
    requested = {
        (entry.card_code, entry.preferred_printing_id)
        for player in players
        for entry in (*player.deck.main_deck, *player.deck.energy_deck)
    }
    definitions: dict[tuple[str, str | None], CardDefinition] = {}
    for card_code, preferred_printing_id in sorted(requested):
        definitions[(card_code, preferred_printing_id)] = _load_definition(
            connection,
            card_code,
            preferred_printing_id,
            effects,
            effect_errors,
        )
    return definitions


def _load_definition(
    connection: sqlite3.Connection,
    card_code: str,
    preferred_printing_id: str | None,
    effects: dict[str, EffectDefinition],
    effect_errors: dict[str, list[str]],
) -> CardDefinition:
    row = connection.execute(
        """
        SELECT
            card.id AS gameplay_card_id,
            card.card_code,
            card.canonical_name_ja,
            card.card_type,
            printing.card_id,
            member.cost,
            member.blade,
            member.blade_heart_color_slot AS member_blade_heart,
            live.score,
            live.blade_heart_color_slot AS live_blade_heart,
            (
                SELECT revision.raw_effect_text_ja
                FROM card_text_revisions AS revision
                WHERE revision.gameplay_card_id = card.id
                ORDER BY
                    CASE revision.revision_status WHEN 'current' THEN 0 ELSE 1 END,
                    revision.revision_number DESC
                LIMIT 1
            ) AS raw_effect_text_ja
            ,(
                SELECT revision.id
                FROM card_text_revisions AS revision
                WHERE revision.gameplay_card_id = card.id
                ORDER BY
                    CASE revision.revision_status WHEN 'current' THEN 0 ELSE 1 END,
                    revision.revision_number DESC
                LIMIT 1
            ) AS text_revision_id
            ,(
                SELECT revision.raw_text_hash
                FROM card_text_revisions AS revision
                WHERE revision.gameplay_card_id = card.id
                ORDER BY
                    CASE revision.revision_status WHEN 'current' THEN 0 ELSE 1 END,
                    revision.revision_number DESC
                LIMIT 1
            ) AS raw_text_hash
        FROM gameplay_cards AS card
        LEFT JOIN member_card_attributes AS member
            ON member.gameplay_card_id = card.id
        LEFT JOIN live_card_attributes AS live
            ON live.gameplay_card_id = card.id
        JOIN card_printings AS printing
            ON printing.gameplay_card_id = card.id
        WHERE card.card_code = ?
          AND (? IS NULL OR printing.card_id = ?)
        ORDER BY printing.card_id
        LIMIT 1
        """,
        (card_code, preferred_printing_id, preferred_printing_id),
    ).fetchone()
    if row is None:
        identity = preferred_printing_id or card_code
        raise DeckDatabaseError(f"card or preferred printing is unavailable: {identity}")

    gameplay_card_id = int(row["gameplay_card_id"])
    hearts: dict[str, dict[str, int]] = defaultdict(dict)
    for heart in connection.execute(
        """
        SELECT heart_role, color_slot, value
        FROM card_heart_values
        WHERE gameplay_card_id = ?
        ORDER BY heart_role, color_slot
        """,
        (gameplay_card_id,),
    ):
        hearts[str(heart["heart_role"])][str(heart["color_slot"])] = int(
            heart["value"]
        )

    specials = [
        SpecialBladeHeart(
            effect_type=special["effect_type"],
            value=special["value"],
            source_alt=special["source_alt"],
        )
        for special in connection.execute(
            """
            SELECT effect_type, value, source_alt
            FROM special_blade_hearts
            WHERE gameplay_card_id = ?
            ORDER BY ordinal
            """,
            (gameplay_card_id,),
        )
    ]
    work_keys = [
        str(work["work_key"])
        for work in connection.execute(
            """
            SELECT DISTINCT work.work_key
            FROM gameplay_card_works AS link
            JOIN works AS work ON work.id = link.work_id
            WHERE link.gameplay_card_id = ?
            ORDER BY work.work_key
            """,
            (gameplay_card_id,),
        )
    ]
    card_effect_ids = sorted(
        effect.effect_id
        for effect in effects.values()
        if effect.card_code == card_code
    )
    errors = effect_errors.get(card_code, [])
    if errors:
        registry_status = "hash_mismatch"
    elif card_effect_ids:
        registry_status = "supported"
    else:
        registry_status = "unregistered"
    blade_heart = row["member_blade_heart"] or row["live_blade_heart"]
    return CardDefinition(
        card_code=str(row["card_code"]),
        card_id=str(row["card_id"]),
        name_ja=str(row["canonical_name_ja"]),
        card_type=str(row["card_type"]),
        cost=row["cost"],
        blade=row["blade"],
        score=row["score"],
        basic_hearts=hearts["basic"],
        required_hearts=hearts["required"],
        blade_heart_color_slot=blade_heart,
        special_blade_hearts=specials,
        raw_effect_text_ja=row["raw_effect_text_ja"],
        text_revision_id=row["text_revision_id"],
        raw_text_hash=row["raw_text_hash"],
        work_keys=work_keys,
        effect_ids=card_effect_ids,
        effect_registry_status=registry_status,
        effect_registry_errors=errors,
    )
