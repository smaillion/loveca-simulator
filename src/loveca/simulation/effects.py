"""Validated, versioned effect registry loading for match-local snapshots."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

DEFAULT_EFFECT_REGISTRY = (
    Path(__file__).parents[3] / "data_sources" / "effect-registry.v0.json"
)

SUPPORTED_EFFECT_ACTIONS = {
    "apply_wait",
    "apply_wait_energy",
    "apply_wait_member",
    "discard_from_hand",
    "draw_card",
    "draw_card_per_stage_member",
    "draw_until_hand_size",
    "gain_blade",
    "gain_blade_if_milled_all_card_type",
    "gain_heart",
    "inspect_top_cards",
    "manual_resolution",
    "modify_score",
    "move_remaining_cards",
    "move_selected_to_deck_bottom",
    "move_selected_to_deck_top",
    "move_selected_to_hand",
    "pay_energy",
    "place_energy_from_deck",
    "ready_energy",
    "ready_member",
    "reorder_deck_top",
    "draw_if_selected_card_type",
    "draw_if_selected_none_card_type",
    "reveal_cards",
    "reveal_selected_cards",
    "return_from_waiting_room",
    "select_to_hand_from_inspected",
    "set_flag",
    "source_to_waiting_room",
    "mill_top_cards",
    "draw_if_milled_all_card_type",
    "draw_if_milled_any_card_type",
    "gain_heart_if_milled_all_have_heart",
    "gain_blade_if_milled_any_card_type",
}


class EffectRegistryError(RuntimeError):
    """Raised when a registry cannot be safely loaded."""


class EffectOperation(BaseModel):
    action_type: str
    target: str | None = None
    amount: int | None = None
    amount_source: Literal[
        "success_live_count",
        "live_area_count",
        "selected_count",
    ] | None = None
    branch: str | None = None
    orientation: Literal["active", "wait"] | None = None
    color_slot: str | None = None
    card_type: str | None = None
    flag: str | None = None
    value: object | None = None
    target_hand_size: int | None = None

    @model_validator(mode="after")
    def validate_operation_shape(self) -> EffectOperation:
        if self.action_type == "place_energy_from_deck":
            if self.target not in {None, "self"}:
                raise ValueError("place_energy_from_deck only supports target=self")
            if self.amount is None or self.amount < 1:
                raise ValueError("place_energy_from_deck requires a positive amount")
            if self.orientation is None:
                raise ValueError("place_energy_from_deck requires an orientation")
        elif self.orientation is not None:
            raise ValueError(
                f"orientation is not supported for effect operation {self.action_type}"
            )
        if self.color_slot is not None and self.action_type not in {
            "gain_heart",
            "gain_heart_if_milled_all_have_heart",
        }:
            raise ValueError(
                f"color_slot is not supported for effect operation {self.action_type}"
            )
        if self.card_type is not None and self.action_type not in {
            "draw_if_milled_all_card_type",
            "draw_if_milled_any_card_type",
            "draw_if_selected_card_type",
            "draw_if_selected_none_card_type",
            "gain_blade_if_milled_all_card_type",
            "gain_blade_if_milled_any_card_type",
        }:
            raise ValueError(
                f"card_type is not supported for effect operation {self.action_type}"
            )
        if self.flag is not None and self.action_type != "set_flag":
            raise ValueError(
                f"flag is not supported for effect operation {self.action_type}"
            )
        if self.target_hand_size is not None:
            if self.action_type != "draw_until_hand_size":
                raise ValueError(
                    f"target_hand_size is not supported for effect operation {self.action_type}"
                )
            if self.target_hand_size < 0:
                raise ValueError("draw_until_hand_size requires a non-negative target")
        return self


class EffectChoice(BaseModel):
    choice_type: str
    zone: str | None = None
    card_type: str | None = None
    orientation: str | None = None
    color_slots: list[str] = Field(default_factory=list)
    minimum: int = 0
    maximum: int = 1
    amount: int | None = None
    amount_source: Literal["own_stage_member_count_plus_2"] | None = None
    target_hand_size: int | None = None
    requires_order: bool = False
    selected_destination: str | None = None
    unselected_destination: str | None = None
    reveal_selected_to_opponent: bool = False
    work_key: str | None = None
    unit_key: str | None = None
    ability_bucket: list[str] = Field(default_factory=list)
    exclude_source: bool = False
    target_player: Literal["self", "opponent"] = "self"
    name_ja_any: list[str] = Field(default_factory=list)
    minimum_cost: int | None = None
    maximum_cost: int | None = None
    maximum_blade: int | None = None
    minimum_score: int | None = None
    maximum_score: int | None = None
    branch_ids: list[str] = Field(default_factory=list)
    branch_selection_minimum: dict[str, int] = Field(default_factory=dict)
    branch_selection_maximum: dict[str, int] = Field(default_factory=dict)


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
    execution_mode: str
    frequency_limit: str
    is_optional: bool
    condition: dict[str, object] = Field(default_factory=dict)
    cost: list[EffectOperation] = Field(default_factory=list)
    cost_choice: EffectChoice | None = None
    choice: EffectChoice | None = None
    actions: list[EffectOperation]
    duration: str | None = None
    simulation_support: str
    review_status: str
    source_reference: str

    @model_validator(mode="after")
    def validate_operations(self) -> EffectDefinition:
        operations = [*self.cost, *self.actions]
        unknown = {
            operation.action_type
            for operation in operations
            if operation.action_type not in SUPPORTED_EFFECT_ACTIONS
        }
        if unknown:
            raise ValueError(f"unsupported effect operations: {sorted(unknown)}")
        if self.execution_mode not in {
            "auto_resolve",
            "prompt_then_resolve",
            "manual_resolution",
        }:
            raise ValueError(f"unsupported execution_mode: {self.execution_mode}")
        if self.execution_mode == "manual_resolution":
            if self.simulation_support != "manual_resolution":
                raise ValueError(
                    "manual_resolution execution_mode requires manual_resolution support"
                )
        elif self.execution_mode == "auto_resolve":
            if (
                self.is_optional
                or self.choice is not None
                or self.cost_choice is not None
                or self.cost
            ):
                raise ValueError(
                    "auto_resolve execution_mode requires no option, choice, or cost"
                )
        return self


class EffectRegistry(BaseModel):
    registry_version: str
    rule_version: str
    effects: list[EffectDefinition]

    @model_validator(mode="after")
    def validate_unique_effects(self) -> EffectRegistry:
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
            row = connection.execute(
                """
                SELECT revision.id, revision.raw_text_hash
                FROM gameplay_cards AS card
                JOIN card_text_revisions AS revision
                  ON revision.gameplay_card_id = card.id
                WHERE card.card_code = ?
                  AND revision.raw_text_hash = ?
                LIMIT 1
                """,
                (effect.card_code, effect.raw_text_hash),
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
