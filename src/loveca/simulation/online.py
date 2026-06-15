"""Transport-independent online readiness helpers.

This module intentionally contains no WebSocket, room, relay, or account logic.
It only owns deterministic hashes and envelopes that replay and future online
sync can share.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from loveca import __version__
from loveca.db.bootstrap import connect_database, get_schema_version
from loveca.decks.analyzer import DeckList
from loveca.simulation.effects import EffectRegistry, load_effect_registry
from loveca.simulation.models import ActionRequest, MatchState, RULE_VERSION

ONLINE_PROTOCOL_VERSION = "loveca-online.v0"


class ActionEnvelope(BaseModel):
    protocol_version: str = ONLINE_PROTOCOL_VERSION
    message_id: str
    match_id: str
    sender_player_id: str | None = None
    expected_revision: int
    base_state_hash: str
    action: ActionRequest
    resulting_state_hash: str | None = None


class CompatibilityFingerprint(BaseModel):
    app_version: str = __version__
    protocol_version: str = ONLINE_PROTOCOL_VERSION
    rule_version: str = RULE_VERSION
    card_database_fingerprint: str | None = None
    effect_registry_hash: str | None = None
    decklist_hashes: dict[str, str] = Field(default_factory=dict)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def match_state_hash(state: MatchState) -> str:
    return sha256_json(state.model_dump(mode="json"))


def action_envelope_hash(envelope: ActionEnvelope) -> str:
    return sha256_json(envelope.model_dump(mode="json"))


def effect_registry_hash(registry: EffectRegistry | Path) -> str:
    if isinstance(registry, Path):
        registry = load_effect_registry(registry)
    return sha256_json(registry.model_dump(mode="json"))


def decklist_hash(deck: DeckList) -> str:
    payload = {
        "version": deck.version,
        "name": deck.name,
        "main_deck": [
            {
                "card_code": entry.card_code,
                "quantity": entry.quantity,
                "preferred_printing_id": entry.preferred_printing_id,
            }
            for entry in deck.main_deck
        ],
        "energy_deck": [
            {
                "card_code": entry.card_code,
                "quantity": entry.quantity,
                "preferred_printing_id": entry.preferred_printing_id,
            }
            for entry in deck.energy_deck
        ],
    }
    return sha256_json(payload)


def card_database_fingerprint(database_path: Path) -> str:
    version = get_schema_version(database_path)
    with connect_database(database_path) as connection:
        payload = {
            "schema_version": version,
            "tables": {
                "gameplay_cards": _table_digest(
                    connection,
                    "SELECT card_code, canonical_name_ja, card_type FROM gameplay_cards ORDER BY card_code",
                ),
                "card_printings": _table_digest(
                    connection,
                    "SELECT card_id, gameplay_card_id, rarity_ja, image_url FROM card_printings ORDER BY card_id",
                ),
                "card_text_revisions": _table_digest(
                    connection,
                    """
                    SELECT gameplay_card_id, revision_number, raw_text_hash, revision_status
                    FROM card_text_revisions
                    ORDER BY gameplay_card_id, revision_number, raw_text_hash
                    """,
                ),
            },
        }
    return sha256_json(payload)


def build_compatibility_fingerprint(
    *,
    card_database_path: Path | None = None,
    effect_registry_path: Path | None = None,
    decks: dict[str, DeckList] | None = None,
    rule_version: str = RULE_VERSION,
    protocol_version: str = ONLINE_PROTOCOL_VERSION,
) -> CompatibilityFingerprint:
    return CompatibilityFingerprint(
        protocol_version=protocol_version,
        rule_version=rule_version,
        card_database_fingerprint=(
            card_database_fingerprint(card_database_path)
            if card_database_path is not None
            else None
        ),
        effect_registry_hash=(
            effect_registry_hash(effect_registry_path)
            if effect_registry_path is not None
            else None
        ),
        decklist_hashes={
            player_id: decklist_hash(deck) for player_id, deck in (decks or {}).items()
        },
    )


def compatibility_report(
    local: CompatibilityFingerprint,
    remote: CompatibilityFingerprint,
) -> dict[str, Any]:
    fields: tuple[
        Literal[
            "app_version",
            "protocol_version",
            "rule_version",
            "card_database_fingerprint",
            "effect_registry_hash",
            "decklist_hashes",
        ],
        ...,
    ] = (
        "app_version",
        "protocol_version",
        "rule_version",
        "card_database_fingerprint",
        "effect_registry_hash",
        "decklist_hashes",
    )
    local_dump = local.model_dump(mode="json")
    remote_dump = remote.model_dump(mode="json")
    mismatches = [
        field for field in fields if local_dump.get(field) != remote_dump.get(field)
    ]
    return {
        "is_compatible": not mismatches,
        "mismatches": mismatches,
        "local": local_dump,
        "remote": remote_dump,
    }


def _table_digest(connection: sqlite3.Connection, query: str) -> dict[str, Any]:
    rows = [dict(row) for row in connection.execute(query)]
    return {
        "count": len(rows),
        "hash": sha256_json(rows),
    }

