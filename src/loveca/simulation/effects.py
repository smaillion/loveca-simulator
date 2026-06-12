"""Validated, versioned effect registry loading for match-local snapshots."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


DEFAULT_EFFECT_REGISTRY = (
    Path(__file__).parents[3] / "data_sources" / "effect-registry.v0.json"
)

SUPPORTED_EFFECT_ACTIONS = {
    "apply_wait",
    "discard_from_hand",
    "draw_card",
    "gain_blade",
    "manual_resolution",
    "pay_energy",
    "ready_energy",
    "ready_member",
    "return_from_waiting_room",
}


class EffectRegistryError(RuntimeError):
    """Raised when a registry cannot be safely loaded."""


class EffectOperation(BaseModel):
    action_type: str
    target: str | None = None
    amount: int | None = None


class EffectChoice(BaseModel):
    choice_type: str
    zone: str
    card_type: str | None = None
    orientation: str | None = None
    minimum: int = 0
    maximum: int = 1


class EffectDefinition(BaseModel):
    effect_id: str
    card_code: str
    text_revision_id: int
    raw_text_hash: str
    effect_index: int
    label_ja: str
    effect_type: str
    timing: str
    trigger: str
    frequency_limit: str
    is_optional: bool
    condition: dict[str, object] = Field(default_factory=dict)
    cost: list[EffectOperation] = Field(default_factory=list)
    choice: EffectChoice | None = None
    actions: list[EffectOperation]
    duration: str | None = None
    simulation_support: str
    review_status: str
    source_reference: str

    @model_validator(mode="after")
    def validate_operations(self) -> "EffectDefinition":
        operations = [*self.cost, *self.actions]
        unknown = {
            operation.action_type
            for operation in operations
            if operation.action_type not in SUPPORTED_EFFECT_ACTIONS
        }
        if unknown:
            raise ValueError(f"unsupported effect operations: {sorted(unknown)}")
        return self


class EffectRegistry(BaseModel):
    registry_version: str
    rule_version: str
    effects: list[EffectDefinition]

    @model_validator(mode="after")
    def validate_unique_effects(self) -> "EffectRegistry":
        ids = [effect.effect_id for effect in self.effects]
        if len(ids) != len(set(ids)):
            raise ValueError("effect registry contains duplicate effect_id values")
        identities = [
            (effect.card_code, effect.raw_text_hash, effect.effect_index)
            for effect in self.effects
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("effect registry contains duplicate card effect identities")
        return self


def load_effect_registry(path: Path = DEFAULT_EFFECT_REGISTRY) -> EffectRegistry:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return EffectRegistry.model_validate(payload)
    except (OSError, ValueError) as exc:
        raise EffectRegistryError(f"invalid effect registry {path}: {exc}") from exc


def validate_registry_for_cards(
    connection: sqlite3.Connection,
    registry: EffectRegistry,
    card_codes: set[str],
) -> tuple[dict[str, EffectDefinition], dict[str, list[str]]]:
    """Return definitions safe for the current DB and explicit per-card errors."""

    valid: dict[str, EffectDefinition] = {}
    errors: dict[str, list[str]] = {}
    for effect in registry.effects:
        if effect.card_code not in card_codes:
            continue
        row = connection.execute(
            """
            SELECT revision.id, revision.raw_text_hash
            FROM gameplay_cards AS card
            JOIN card_text_revisions AS revision
              ON revision.gameplay_card_id = card.id
            WHERE card.card_code = ?
              AND revision.id = ?
            """,
            (effect.card_code, effect.text_revision_id),
        ).fetchone()
        if row is None:
            errors.setdefault(effect.card_code, []).append(
                f"{effect.effect_id}: text revision {effect.text_revision_id} is unavailable"
            )
            continue
        if str(row["raw_text_hash"]) != effect.raw_text_hash:
            errors.setdefault(effect.card_code, []).append(
                f"{effect.effect_id}: raw effect text hash mismatch"
            )
            continue
        valid[effect.effect_id] = effect
    return valid, errors
