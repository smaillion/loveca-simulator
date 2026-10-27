"""Validated, versioned effect registry loading for match-local snapshots."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_serializer, model_validator

DEFAULT_EFFECT_REGISTRY = (
    Path(__file__).parents[3] / "data_sources" / "effect-registry.v0.json"
)

SUPPORTED_EFFECT_ACTIONS = {
    "apply_wait",
    "apply_wait_energy",
    "apply_wait_member",
    "apply_wait_to_stage_members",
    "attach_selected_under_source",
    "attach_baton_replaced_member_under_source",
    "clear_excess_hearts",
    "conceal_selected_cards",
    "discard_from_hand",
    "draw_card",
    "draw_card_per_stage_member",
    "draw_until_hand_size",
    "disable_source_live_success_effects",
    "deploy_selected_to_empty_stage",
    "deploy_selected_to_stage",
    "gain_blade",
    "gain_blade_to_stage_members",
    "gain_blade_if_milled_all_card_type",
    "grant_live_success_draw",
    "grant_muse_blade_aura_if_success_score_icon",
    "gain_heart",
    "gain_heart_to_stage_members",
    "inspect_top_cards",
    "manual_resolution",
    "modify_score",
    "modify_source_score_if_selected_blade_highest",
    "modify_source_score_if_selected_blade_six",
    "modify_required_heart",
    "modify_yell_count",
    "move_remaining_cards",
    "move_waiting_room_members_to_deck_bottom",
    "move_selected_to_deck_bottom",
    "move_selected_to_deck_position",
    "move_selected_energy_to_energy_deck",
    "move_selected_to_deck_top",
    "move_selected_to_deck_top_or_bottom",
    "move_selected_to_hand",
    "pay_energy",
    "place_energy_from_deck",
    "position_change_source",
    "position_change_selected",
    "prevent_equal_score_success_live_placement",
    "prevent_baton_replacement",
    "prevent_opponent_active_phase_ready",
    "prevent_source_active_phase_ready",
    "ready_energy",
    "ready_member",
    "reorder_deck_top",
    "replace_score",
    "replace_yell_blade_hearts",
    "reduce_play_cost",
    "restrict_baton_replacement_unit",
    "rotate_stage_members",
    "draw_if_selected_card_type",
    "draw_if_selected_none_card_type",
    "draw_if_selected_without_blade_heart",
    "reveal_cards",
    "reveal_top_cards",
    "reveal_top_in_place",
    "reveal_top_matching_to_hand_else_deck_top",
    "reveal_top_matching_to_hand_else_waiting",
    "reveal_until_matching_to_hand_else_waiting",
    "reveal_top_to_hand",
    "reveal_selected_cards",
    "return_from_waiting_room",
    "select_to_hand_from_inspected",
    "set_flag",
    "replace_member_base_hearts",
    "replace_member_base_blade",
    "replace_required_hearts",
    "return_baton_replaced_member_to_hand",
    "return_source_live_to_hand",
    "source_to_waiting_room",
    "mill_bottom_cards",
    "mill_top_cards",
    "draw_if_milled_all_card_type",
    "draw_if_milled_any_card_type",
    "gain_heart_if_milled_all_have_heart",
    "gain_source_heart_if_milled_member_blade_colors",
    "gain_heart_from_selected_card_colors",
    "gain_blade_if_milled_any_card_type",
}


class EffectRegistryError(RuntimeError):
    """Raised when a registry cannot be safely loaded."""


class EffectOperation(BaseModel):
    action_type: str
    target: str | None = None
    amount: int | None = None
    amount_source: Literal[
        "all_energy_active_bonus",
        "success_live_count",
        "success_live_name_count",
        "success_live_score",
        "success_live_score_threshold_bonus",
        "success_live_score_values_bonus",
        "live_area_count",
        "other_live_area_work_count",
        "moved_stage_member_count",
        "stage_slot_member_heart_pair_count",
        "stage_member_with_heart_excluding_colors_count",
        "stage_member_more_than_original_heart_count",
        "own_wait_stage_member_count",
        "opponent_stage_wait_member_count",
        "stage_member_work_cost_sum_threshold_bonus",
        "effect_ready_history_score_bonus",
        "selected_count",
        "baton_replaced_member_work_count",
        "baton_replaced_member_without_blade_heart_count",
        "own_stage_member_count",
        "own_stage_member_unit_count",
        "own_stage_member_filter_count",
        "total_stage_member_count",
        "opponent_success_live_count_difference",
        "stage_member_heart_color_variety_count",
        "own_hand_count_divided_by",
        "own_other_hand_count",
        "own_energy_count_divided_by",
        "milled_member_work_count",
        "revealed_live_count",
        "own_stage_member_work_distinct_name_count",
        "own_yell_revealed_member_without_blade_heart_count",
        "waiting_room_live_work_distinct_name_threshold_bonus",
        "source_attached_energy_count",
        "source_attached_energy_count_plus",
        "source_attached_member_count",
        "selected_member_matching_source_attribute_count",
        "selected_member_cost15_heart_amount",
        "success_live_score_card_count_capped",
    ] | None = None
    branch: str | None = None
    multiplier: int | None = None
    orientation: Literal["active", "wait"] | None = None
    entry_trigger_policy: Literal["member_area_external_only"] | None = None
    overlap_source_policy: Literal["original_stage_member"] | None = None
    source_object_policy: Literal[
        "original_moved_stage_member", "original_live_start_heart_source",
        "original_live_start_wait_cost_source",
        "original_onplay_mill_source",
        "original_onplay_muse_blade_aura",
    ] | None = None
    overlap_observer_policy: Literal[
        "ignore_disjoint_source_triggers", "require_complete_source_bindings"
    ] | None = None
    color_slot: str | None = None
    card_type: str | None = None
    flag: str | None = None
    value: object | None = None
    target_hand_size: int | None = None

    @model_serializer(mode="wrap")
    def serialize_entry_policy(self, handler) -> dict[str, Any]:
        result = handler(self)
        if self.entry_trigger_policy is None:
            # Historical effect snapshots retain their exact shape and hash.
            result.pop("entry_trigger_policy", None)
        if self.overlap_source_policy is None:
            result.pop("overlap_source_policy", None)
        if self.source_object_policy is None:
            result.pop("source_object_policy", None)
        if self.overlap_observer_policy is None:
            result.pop("overlap_observer_policy", None)
        return result

    @model_validator(mode="after")
    def validate_operation_shape(self) -> EffectOperation:
        if self.action_type == "grant_muse_blade_aura_if_success_score_icon" and (
            self.model_dump(exclude_defaults=True, exclude_none=True) != {
                "action_type": "grant_muse_blade_aura_if_success_score_icon",
                "source_object_policy": "original_onplay_muse_blade_aura", "target": "source", "amount": 1,
            }
        ):
            raise ValueError("Muse aura requires the fixed original source Blade-one grant")
        if self.source_object_policy == "original_onplay_muse_blade_aura" and (
            self.action_type != "grant_muse_blade_aura_if_success_score_icon"
        ):
            raise ValueError("Muse aura source policy only supports its bounded grant")
        if self.action_type == "gain_source_heart_if_milled_member_blade_colors" and (
            self.model_dump(exclude_defaults=True, exclude_none=True) != {
                "action_type": "gain_source_heart_if_milled_member_blade_colors",
                "source_object_policy": "original_onplay_mill_source",
                "target": "source", "amount": 1, "color_slot": "heart04",
            }
        ):
            raise ValueError("milled Member Blade colors require a fixed green source Heart")
        if self.source_object_policy == "original_onplay_mill_source" and (
            self.action_type != "gain_source_heart_if_milled_member_blade_colors"
        ):
            raise ValueError("on-play mill source policy only supports its bounded Heart operation")
        if self.source_object_policy == "original_moved_stage_member" and (
            self.action_type != "ready_member" or self.target != "source"
            or self.amount is not None or self.amount_source is not None
            or self.branch is not None or self.value is not None
            or self.multiplier is not None
            or self.orientation is not None or self.color_slot is not None
            or self.flag is not None or self.target_hand_size is not None or self.card_type is not None
        ):
            raise ValueError("source object policy only supports readying the moved source Member")
        if self.source_object_policy == "original_live_start_heart_source" and (
            self.action_type != "gain_heart" or self.target != "source" or self.amount != 2
            or self.amount_source is not None or self.branch is not None or self.value is not None
            or self.multiplier is not None or self.orientation is not None or self.color_slot is not None
            or self.flag is not None or self.target_hand_size is not None or self.card_type is not None
        ):
            raise ValueError("Live Heart source policy only supports two chosen-color source Hearts")
        if self.source_object_policy == "original_live_start_wait_cost_source" and (
            (self.action_type, self.amount) not in {("gain_blade", 2), ("gain_heart", 1)}
            or self.target != "source" or self.amount_source is not None or self.branch is not None
            or self.value is not None or self.multiplier is not None or self.orientation is not None
            or self.color_slot is not None or self.flag is not None or self.target_hand_size is not None
            or self.card_type is not None
        ):
            raise ValueError("Wait cost source policy requires source Blade2 or chosen Heart1")
        if self.overlap_observer_policy is not None and self.action_type != "deploy_selected_to_stage":
            raise ValueError("overlap observer policy requires bounded Stage deployment")
        if self.action_type == "modify_source_score_if_selected_blade_highest" and (
            self.amount != 1 or self.amount_source is not None
            or self.target is not None or self.multiplier is not None
            or self.branch is not None or self.value is not None
        ):
            raise ValueError("selected Blade comparison only supports a fixed source Live score +1")
        if self.overlap_source_policy is not None and (
            self.action_type != "gain_blade"
            or self.target not in {None, "self"}
            or self.amount is None
            or self.amount <= 0
            or self.amount_source is not None
            or self.branch is not None
            or self.multiplier is not None
            or self.value is not None
        ):
            raise ValueError("overlap source policy requires a fixed self Blade modifier")
        if self.action_type == "deploy_selected_to_stage" and (
            self.orientation is None or self.branch is not None
            or self.entry_trigger_policy is not None
            or self.amount not in {None, 1} or self.amount_source is not None
            or self.target not in {None, "self"}
        ):
            raise ValueError("Stage deployment requires explicit orientation and self target")
        if (
            self.entry_trigger_policy is not None
            and self.action_type != "deploy_selected_to_empty_stage"
        ):
            raise ValueError("entry_trigger_policy is only supported for Member deployment")
        if self.action_type == "place_energy_from_deck":
            if self.target not in {None, "self", "opponent", "both"}:
                raise ValueError(
                    "place_energy_from_deck only supports target=self, opponent, or both"
                )
            if self.amount_source is None and (self.amount is None or self.amount < 1):
                raise ValueError(
                    "place_energy_from_deck requires a positive amount or amount_source"
                )
            if self.orientation is None:
                raise ValueError("place_energy_from_deck requires an orientation")
        elif (
            self.orientation is not None
            and self.action_type not in {
                "deploy_selected_to_empty_stage", "deploy_selected_to_stage",
            }
        ):
            raise ValueError(
                f"orientation is not supported for effect operation {self.action_type}"
            )
        if self.color_slot is not None and self.action_type not in {
            "gain_heart",
            "gain_heart_to_stage_members",
            "gain_heart_if_milled_all_have_heart",
            "gain_source_heart_if_milled_member_blade_colors",
            "modify_required_heart",
            "replace_member_base_hearts",
            "replace_yell_blade_hearts",
        }:
            raise ValueError(
                f"color_slot is not supported for effect operation {self.action_type}"
            )
        if self.action_type == "replace_yell_blade_hearts" and not self.color_slot:
            raise ValueError("replace_yell_blade_hearts requires color_slot")
        if self.card_type is not None and self.action_type not in {
            "draw_if_milled_all_card_type",
            "draw_if_milled_any_card_type",
            "draw_if_selected_card_type",
            "draw_if_selected_none_card_type",
            "gain_blade_if_milled_all_card_type",
            "gain_blade_if_milled_any_card_type",
            "reveal_top_matching_to_hand_else_deck_top",
            "reveal_top_matching_to_hand_else_waiting",
            "reveal_until_matching_to_hand_else_waiting",
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


class EffectSelectionGroup(BaseModel):
    group_id: str
    label_ja: str | None = None
    zone: str | None = None
    card_type: str | None = None
    work_key: str | None = None
    unit_key: str | None = None
    name_ja_any: list[str] = Field(default_factory=list)
    exclude_name_ja_any: list[str] = Field(default_factory=list)
    minimum: int = 1
    maximum: int = 1
    exclude_group_ids: list[str] = Field(default_factory=list)
    exclude_group_names: list[str] = Field(default_factory=list)


class EffectChoice(BaseModel):
    cost_payment_policy: Literal["triggered_inspection", "triggered_inspection_reorder"] | None = None
    inspection_activation_policy: Literal["start_after_cost"] | None = None
    choice_type: str
    deployment_policy: Literal["simultaneous_member_area_entry"] | None = None
    selection_policy: Literal[
        "private_filtered_may_choose_none", "public_single_as_much_as_possible",
        "public_named_groups_as_much_as_possible", "public_other_nijigasaki_cost_heart",
        "public_yell_aqours_bottom_three",
        "public_nijigasaki_blade_four_heart",
        "public_aqours_blade_six_source_score",
        "public_four_lily_white_live",
        "private_ten_minus_hand_keep_two",
        "public_both_waiting_live_one",
    ] | None = None
    zone: str | None = None
    card_type: str | None = None
    orientation: str | None = None
    color_slots: list[str] = Field(default_factory=list)
    minimum: int = 0
    maximum: int = 1
    amount: int | None = None
    amount_source: Literal[
        "own_stage_member_count",
        "own_stage_member_work_count",
        "own_stage_member_unit_count",
        "own_stage_member_count_plus_2",
        "opponent_stage_wait_member_count",
        "own_active_energy_count",
        "cost_selected_count",
    ] | None = None
    amount_source_work_key: str | None = None
    amount_source_unit_key: str | None = None
    target_hand_size: int | None = None
    discard_amount: int | None = None
    condition: dict[str, Any] = Field(default_factory=dict)
    requires_order: bool = False
    selected_destination: str | None = None
    destination_options: list[str] = Field(default_factory=list)
    unselected_destination: str | None = None
    reveal_selected_to_opponent: bool = False
    work_key: str | None = None
    unit_key: str | None = None
    exclude_unit_key: str | None = None
    unit_keys_any: list[str] = Field(default_factory=list)
    ability_bucket: list[str] = Field(default_factory=list)
    exclude_source: bool = False
    target_player: Literal["self", "opponent"] = "self"
    name_ja_any: list[str] = Field(default_factory=list)
    exclude_name_ja_any: list[str] = Field(default_factory=list)
    minimum_cost: int | None = None
    maximum_cost: int | None = None
    minimum_blade: int | None = None
    maximum_blade: int | None = None
    minimum_original_blade: int | None = None
    maximum_original_blade: int | None = None
    minimum_score: int | None = None
    maximum_score: int | None = None
    excluded_position_slots: list[str] = Field(default_factory=list)
    heart_color_slot: str | None = None
    heart_color_slots_any: list[str] = Field(default_factory=list)
    heart_color_slots_all: list[str] = Field(default_factory=list)
    minimum_heart_count: int | None = None
    required_heart_color_slot: str | None = None
    minimum_required_heart: int | None = None
    minimum_required_heart_total: int | None = None
    exclude_blade_heart: bool = False
    maximum_cost_less_than_cost_selected: bool = False
    exclude_stage_unit_keys: bool = False
    branch_ids: list[str] = Field(default_factory=list)
    branch_selection_minimum: dict[str, int] = Field(default_factory=dict)
    branch_selection_maximum: dict[str, int] = Field(default_factory=dict)
    branch_energy_required: dict[str, int] = Field(default_factory=dict)
    branch_conditions: dict[str, dict[str, Any]] = Field(default_factory=dict)
    auto_branch_from_cost_choice: bool = False
    branch_cost_conditions: dict[str, dict[str, str]] = Field(default_factory=dict)
    branch_choice_filters: dict[str, dict[str, Any]] = Field(default_factory=dict)
    post_action_condition_key: str | None = None
    post_action_condition_minimum: int | None = None
    selection_groups: list[EffectSelectionGroup] = Field(default_factory=list)
    position_target_unit_keys_any: list[str] = Field(default_factory=list)
    share_unit_with_cost_selected: bool = False
    same_name_as_cost_selected: bool = False
    share_unit_with_stage: bool = False
    same_name_as_stage: bool = False
    value: object | None = None

    @model_serializer(mode="wrap")
    def serialize_deployment_policy(self, handler) -> dict[str, Any]:
        result = handler(self)
        if self.cost_payment_policy is None:
            result.pop("cost_payment_policy", None)
        if self.inspection_activation_policy is None:
            result.pop("inspection_activation_policy", None)
        if self.deployment_policy is None:
            result.pop("deployment_policy", None)
        if self.selection_policy is None:
            result.pop("selection_policy", None)
        return result

    @model_validator(mode="after")
    def validate_deployment_policy(self) -> EffectChoice:
        if self.selection_policy == "public_both_waiting_live_one" and (
            self.model_dump(exclude_defaults=True, exclude_none=True) != {
                "choice_type": "multi_player_waiting_live_recovery",
                "selection_policy": "public_both_waiting_live_one", "zone": "waiting_room",
                "card_type": "live", "minimum": 1, "selected_destination": "hand",
            }
        ):
            raise ValueError("both-player recovery requires one public Waiting Room Live per player")
        if self.choice_type == "multi_player_waiting_live_recovery" and self.selection_policy != "public_both_waiting_live_one":
            raise ValueError("both-player recovery requires its explicit snapshot policy")
        if self.selection_policy == "private_ten_minus_hand_keep_two" and (
            self.model_dump(exclude_defaults=True, exclude_none=True) != {
                "choice_type": "inspect_top_select",
                "selection_policy": "private_ten_minus_hand_keep_two", "maximum": 2,
                "selected_destination": "hand", "unselected_destination": "waiting_room",
            }
        ):
            raise ValueError("ten-minus-hand inspection requires a private zero-to-two choice")
        if self.selection_policy == "public_four_lily_white_live" and (
            self.model_dump(exclude_defaults=True, exclude_none=True) != {
                "choice_type": "inspect_top_select", "amount": 4,
                "selection_policy": "public_four_lily_white_live",
                "card_type": "live", "unit_key": "lily_white", "minimum": 1,
                "selected_destination": "hand", "unselected_destination": "waiting_room",
                "reveal_selected_to_opponent": True,
            }
        ):
            raise ValueError("public four-card prototype requires the bounded lily-white Live choice")
        if self.cost_payment_policy == "triggered_inspection" and (
            self.choice_type != "inspect_top_select" or self.target_player != "self"
            or self.amount is None or self.amount <= 0 or self.amount_source is not None
            or self.minimum not in {0, 1} or self.maximum != 1 or self.requires_order
            or self.selected_destination != "hand" or self.unselected_destination != "waiting_room"
            or self.inspection_activation_policy is not None or self.selection_policy is not None
        ):
            raise ValueError("triggered inspection cost policy requires fixed private look and hand selection")
        if self.cost_payment_policy == "triggered_inspection_reorder" and (
            self.choice_type != "inspect_top_select" or self.target_player != "self"
            or self.amount != 2 or self.amount_source is not None
            or self.minimum != 0 or self.maximum != 2 or not self.requires_order
            or self.selected_destination != "main_deck_top_ordered" or self.unselected_destination != "waiting_room"
            or self.reveal_selected_to_opponent or self.card_type is not None or self.work_key is not None
            or self.condition or self.selection_groups or self.name_ja_any or self.unit_key is not None
            or self.inspection_activation_policy is not None or self.selection_policy is not None
        ):
            raise ValueError("triggered inspection cost policy requires a private two-card reorder")
        if self.inspection_activation_policy is not None and (
            self.choice_type != "inspect_top_select" or self.target_player != "self"
            or self.amount is None or self.amount <= 0
            or self.amount_source is not None
            or self.minimum != self.amount or self.maximum != self.amount
            or not self.requires_order or self.selected_destination != "main_deck_top_ordered"
            or self.unselected_destination is not None or self.reveal_selected_to_opponent
        ):
            raise ValueError("activated inspection policy requires a private full top-deck reorder")
        if self.selection_policy == "public_yell_aqours_bottom_three" and (
            self.model_dump(exclude_defaults=True, exclude_none=True) != {
                "choice_type": "card_from_zone", "zone": "resolution_area",
                "selection_policy": "public_yell_aqours_bottom_three", "maximum": 3,
                "work_key": "aqours", "requires_order": True,
            }
        ):
            raise ValueError("Yell bottom selection requires zero to three own Aqours cards")
        if self.selection_policy == "public_other_nijigasaki_cost_heart" and (
            self.model_dump(exclude_defaults=True, exclude_none=True) != {
                "choice_type": "member_from_stage", "zone": "stage", "card_type": "member",
                "selection_policy": "public_other_nijigasaki_cost_heart",
                "minimum": 1, "work_key": "nijigasaki", "exclude_source": True,
            }
        ):
            raise ValueError("other Nijigasaki selection requires one other own Stage Member")
        if self.selection_policy == "public_aqours_blade_six_source_score" and (
            self.model_dump(exclude_defaults=True, exclude_none=True) != {
                "choice_type": "member_from_stage", "zone": "stage", "card_type": "member",
                "selection_policy": "public_aqours_blade_six_source_score",
                "minimum": 1, "work_key": "aqours",
            }
        ):
            raise ValueError("Aqours Blade-six selection must not pre-filter the body condition")
        if self.selection_policy == "public_nijigasaki_blade_four_heart" and (
            self.model_dump(exclude_defaults=True, exclude_none=True) != {
                "choice_type": "member_from_stage", "zone": "stage", "card_type": "member",
                "selection_policy": "public_nijigasaki_blade_four_heart",
                "minimum": 1, "work_key": "nijigasaki", "minimum_blade": 4,
            }
        ):
            raise ValueError("Blade-four selection requires one own Nijigasaki Stage Member")
        if self.selection_policy == "public_single_as_much_as_possible" and (
            self.choice_type != "member_from_stage" or self.zone != "stage"
            or self.target_player != "self" or self.card_type != "member"
            or self.minimum != 1 or self.maximum != 1 or self.amount_source is not None
            or len(self.name_ja_any) != 1 or not self.name_ja_any[0].strip() or self.condition
        ):
            raise ValueError("public single selection requires one named own Stage Member")
        if self.selection_policy == "public_named_groups_as_much_as_possible" and (
            self.choice_type != "member_group_from_stage" or self.zone != "stage"
            or self.card_type != "member" or self.target_player != "self" or self.condition
            or self.amount_source is not None or len(self.selection_groups) != 2
            or len({g.group_id for g in self.selection_groups}) != 2
            or any(not g.group_id or g.zone != "stage" or g.card_type != "member"
                   or g.minimum != 1 or g.maximum != 1 or len(g.name_ja_any) != 1
                   or not g.name_ja_any[0].strip() or g.exclude_group_ids or g.exclude_group_names
                   or g.work_key or g.unit_key or g.exclude_name_ja_any for g in self.selection_groups)
            or len({"".join(g.name_ja_any[0].split()) for g in self.selection_groups
                    if g.name_ja_any}) != 2
        ):
            raise ValueError("public named groups require two independent named own Stage Members")
        if self.selection_policy == "private_filtered_may_choose_none" and (
            self.choice_type != "card_from_zone" or self.zone != "hand"
            or self.target_player != "self" or self.card_type != "member"
            or self.minimum != 1 or self.maximum != 1 or self.amount_source is not None
        ):
            raise ValueError("private selection only supports one filtered own-hand Member")
        if self.deployment_policy is not None and (
            self.choice_type != "multi_player_deploy_waiting_member"
            or self.zone != "waiting_room" or self.card_type != "member"
            or self.orientation not in {"active", "wait"} or self.maximum != 1
        ):
            raise ValueError(
                "simultaneous deployment requires a single Waiting Room Member and orientation"
            )
        return self


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
    follow_up_choice: EffectChoice | None = None
    actions: list[EffectOperation]
    duration: str | None = None
    simulation_support: str
    review_status: str
    source_reference: str

    @model_validator(mode="after")
    def validate_triggered_inspection_cost(self) -> EffectDefinition:
        if any(c is not None and c.cost_payment_policy is not None for c in (self.cost_choice, self.follow_up_choice)):
            raise ValueError("inspection cost policy must be the main effect choice")
        if self.choice is None or self.choice.cost_payment_policy is None:
            return self
        reorder = self.choice.cost_payment_policy == "triggered_inspection_reorder"
        expected_actions = ["inspect_top_cards", "reorder_deck_top" if reorder else "select_to_hand_from_inspected", "move_remaining_cards"]
        if (
            self.effect_type != "triggered" or self.timing != "on_play" or self.trigger != "member_played"
            or self.condition
            or self.execution_mode != "prompt_then_resolve" or self.simulation_support == "manual_resolution"
            or self.frequency_limit != "none" or self.duration is not None or self.follow_up_choice is not None
            or len(self.cost) != 1
            or [op.action_type for op in self.actions] != expected_actions
            or self.actions[0].amount != self.choice.amount
            or any(op.amount_source is not None or op.branch is not None for op in [*self.cost, *self.actions])
        ):
            raise ValueError("triggered inspection cost policy requires one fixed on-play cost")
        cost = self.cost[0]
        hand = self.cost_choice
        discard = (cost.action_type == "discard_from_hand" and cost.target is None
                   and hand is not None and hand.choice_type == "card_from_zone" and hand.zone == "hand"
                   and hand.target_player == "self" and hand.minimum == hand.maximum == 1
                   and hand.card_type in {None, "live"} and not hand.condition and not hand.selection_groups)
        wait = (cost.action_type == "apply_wait" and cost.target == "source" and hand is None and self.is_optional)
        if not (wait or (discard and not reorder)) or cost.amount is not None or cost.value is not None:
            raise ValueError("triggered inspection cost policy only supports one hand discard or source Wait")
        return self

    @model_validator(mode="after")
    def validate_entry_count_snapshot(self) -> EffectDefinition:
        keys = {"trigger_member_entry_count_exact", "trigger_source_zone"}
        if not keys.intersection(self.condition):
            return self
        count = self.condition.get("trigger_member_entry_count_exact")
        if (
            set(self.condition) != keys
            or type(count) is not int
            or count < 1
            or self.condition.get("trigger_source_zone") != "stage"
            or self.trigger != "own_member_played"
            or self.effect_type != "triggered"
            or self.execution_mode != "auto_resolve"
            or self.is_optional
            or self.frequency_limit != "none"
            or self.cost
            or self.cost_choice
            or self.choice
            or self.follow_up_choice
            or self.duration is not None
            or len(self.actions) != 1
            or self.actions[0].action_type != "draw_until_hand_size"
            or self.actions[0].target not in {None, "self"}
            or self.actions[0].amount_source is not None
            or self.actions[0].branch is not None
            or self.actions[0].value is not None
        ):
            raise ValueError("entry count snapshot requires a bounded mandatory draw-to-hand observer")
        return self

    @model_validator(mode="after")
    def validate_operations(self) -> EffectDefinition:
        if self.choice and self.choice.selection_policy == "public_both_waiting_live_one" and (
            self.cost or self.cost_choice or self.follow_up_choice or self.condition or self.is_optional
            or self.effect_type != "triggered" or self.timing != "on_play" or self.trigger != "member_played"
            or self.duration is not None or self.frequency_limit != "none"
            or self.execution_mode != "prompt_then_resolve"
            or [op.model_dump(exclude_defaults=True, exclude_none=True) for op in self.actions] != [
                {"action_type": "return_from_waiting_room", "target": "both"},
            ]
        ):
            raise ValueError("both-player recovery only supports the fixed mandatory on-play sequence")
        if any(op.action_type == "grant_muse_blade_aura_if_success_score_icon" for op in self.actions) and (
            self.cost or self.cost_choice or self.choice or self.follow_up_choice or self.condition
            or self.is_optional or self.effect_type != "triggered" or self.timing != "on_play"
            or self.trigger != "member_played" or self.frequency_limit != "none"
            or self.duration != "live" or self.execution_mode != "auto_resolve" or len(self.actions) != 1
        ):
            raise ValueError("Muse aura only supports the fixed mandatory on-play Live-limited grant")
        if any(op.action_type == "gain_source_heart_if_milled_member_blade_colors" for op in self.actions) and (
            self.cost or self.cost_choice or self.choice or self.follow_up_choice or self.condition
            or self.is_optional or self.effect_type != "triggered" or self.timing != "on_play"
            or self.trigger != "member_played" or self.frequency_limit != "none"
            or self.duration != "live" or self.execution_mode != "auto_resolve"
            or len(self.actions) != 2
            or self.actions[0].model_dump(exclude_defaults=True, exclude_none=True) != {
                "action_type": "mill_top_cards", "amount": 3,
            }
            or self.actions[1].action_type != "gain_source_heart_if_milled_member_blade_colors"
        ):
            raise ValueError("milled Member Blade colors require the fixed on-play mill-three sequence")
        if self.choice and self.choice.selection_policy == "private_ten_minus_hand_keep_two" and (
            self.cost or self.cost_choice or self.follow_up_choice or self.condition
            or self.is_optional or self.effect_type != "triggered" or self.timing != "on_play"
            or self.trigger != "member_played" or self.frequency_limit != "none"
            or self.duration is not None or self.execution_mode != "prompt_then_resolve"
            or [op.model_dump(exclude_defaults=True, exclude_none=True) for op in self.actions] != [
                {"action_type": "inspect_top_cards"},
                {"action_type": "select_to_hand_from_inspected"},
                {"action_type": "move_remaining_cards"},
            ]
        ):
            raise ValueError("ten-minus-hand inspection only supports its fixed on-play sequence")
        if self.choice and self.choice.selection_policy == "public_four_lily_white_live" and (
            self.cost or self.cost_choice or self.follow_up_choice or self.condition
            or self.is_optional or self.effect_type != "triggered" or self.timing != "on_play"
            or self.trigger != "member_played" or self.frequency_limit != "none"
            or self.duration is not None or self.execution_mode != "prompt_then_resolve"
            or [op.model_dump(exclude_defaults=True, exclude_none=True) for op in self.actions] != [
                {"action_type": "reveal_cards", "amount": 4},
                {"action_type": "select_to_hand_from_inspected"},
                {"action_type": "move_remaining_cards"},
            ]
        ):
            raise ValueError("public four-card prototype only supports its fixed on-play sequence")
        if any(op.source_object_policy is not None for op in self.cost):
            raise ValueError("source object policy cannot be a cost")
        if any(op.source_object_policy == "original_moved_stage_member" for op in self.actions) and (
            len(self.actions) != 1 or self.effect_type != "triggered"
            or self.simulation_support == "manual_resolution"
            or self.trigger != "member_moved" or self.execution_mode != "auto_resolve"
            or self.condition != {"source_zone": "stage", "source_orientation": "wait"}
            or self.cost or self.cost_choice or self.choice or self.follow_up_choice
            or self.is_optional or self.duration is not None or self.frequency_limit != "none"
        ):
            raise ValueError("source object policy requires a bounded Wait movement trigger")
        if any(op.source_object_policy == "original_live_start_heart_source" for op in self.actions) and (
            len(self.actions) != 1 or self.effect_type != "triggered" or self.trigger != "live_started"
            or self.execution_mode != "prompt_then_resolve" or self.simulation_support == "manual_resolution"
            or self.condition or not self.is_optional or self.duration != "live" or self.follow_up_choice
            or len(self.cost) != 1 or self.cost[0].action_type != "discard_from_hand"
            or self.cost[0].amount_source is not None or self.cost[0].target not in {None, "self"}
            or self.cost_choice is None or self.cost_choice.choice_type != "card_from_zone"
            or self.cost_choice.zone != "hand" or self.cost_choice.target_player != "self"
            or self.cost_choice.minimum != 2 or self.cost_choice.maximum != 2
            or self.choice is None or self.choice.choice_type != "choose_color"
            or set(self.choice.color_slots) != {f"heart0{i}" for i in range(1, 7)}
        ):
            raise ValueError("Live Heart source policy requires optional discard-two then choose-color")
        if any(op.source_object_policy == "original_live_start_wait_cost_source" for op in self.actions) and (
            len(self.actions) != 1 or self.effect_type != "triggered" or self.trigger != "live_started"
            or self.execution_mode != "prompt_then_resolve" or self.simulation_support == "manual_resolution"
            or self.condition or not self.is_optional or self.duration != "live" or self.follow_up_choice
            or len(self.cost) != 1 or self.cost[0].action_type != "apply_wait_member"
            or self.cost[0].target != "selected" or self.cost[0].amount_source is not None
            or self.cost_choice is None or self.cost_choice.choice_type != "member_from_stage"
            or self.cost_choice.zone != "stage" or self.cost_choice.target_player != "self"
            or self.cost_choice.card_type != "member" or self.cost_choice.work_key != "nijigasaki"
            or self.cost_choice.orientation != "active" or self.cost_choice.exclude_source
            or self.cost_choice.minimum != 1 or self.cost_choice.maximum != 1
            or (self.actions[0].action_type == "gain_blade" and self.choice is not None)
            or (self.actions[0].action_type == "gain_heart" and (
                self.choice is None or self.choice.choice_type != "choose_color"
                or set(self.choice.color_slots) != {f"heart0{i}" for i in range(1, 7)}))
        ):
            raise ValueError("Wait cost source policy requires one optional Active Nijigasaki Member cost")
        if any(choice is not None and choice.inspection_activation_policy is not None
               for choice in (self.cost_choice, self.follow_up_choice)):
            raise ValueError("inspection activation policy must be the main effect choice")
        if self.choice is not None and self.choice.inspection_activation_policy is not None and (
            self.effect_type != "activated" or self.trigger != "player_activation"
            or self.execution_mode != "prompt_then_resolve"
            or self.simulation_support == "manual_resolution"
            or self.cost_choice is not None or self.follow_up_choice is not None
            or len(self.cost) != 1 or self.cost[0].action_type != "pay_energy"
            or self.cost[0].amount is None or self.cost[0].amount <= 0
            or self.cost[0].amount_source is not None
            or self.cost[0].branch is not None or self.cost[0].target not in {None, "self"}
            or [op.action_type for op in self.actions] != ["inspect_top_cards", "reorder_deck_top", "move_remaining_cards"]
            or self.actions[0].amount != self.choice.amount or self.actions[0].amount_source is not None
            or any(op.branch is not None for op in self.actions)
        ):
            raise ValueError("activated inspection policy requires fixed Energy cost and structured reorder")
        if any(op.action_type == "modify_source_score_if_selected_blade_highest" for op in self.actions):
            choice = self.choice
            if (
                len(self.actions) != 1 or self.cost or self.cost_choice or self.follow_up_choice
                or self.duration != "live" or self.trigger != "live_succeeded"
                or self.execution_mode != "prompt_then_resolve"
                or choice is None or choice.choice_type != "member_from_stage"
                or choice.zone != "stage" or choice.target_player != "self"
                or choice.card_type != "member" or choice.minimum != 1 or choice.maximum != 1
            ):
                raise ValueError("source score comparison requires one own Stage Member at Live success")
        if any(op.overlap_observer_policy is not None for op in self.cost):
            raise ValueError("overlap observer policy cannot be used as a cost")
        if any(op.overlap_source_policy is not None for op in self.cost):
            raise ValueError("overlap source policy cannot be used as a cost")
        if any(op.overlap_source_policy is not None for op in self.actions) and (
            len(self.actions) != 1
            or self.trigger != "own_member_played"
            or self.effect_type != "triggered"
            or self.execution_mode != "auto_resolve"
            or self.duration != "live"
            or self.cost
            or self.cost_choice
            or self.choice
            or self.follow_up_choice
            or self.is_optional
            or not isinstance(self.condition.get("source_slot"), str)
            or self.condition.get("source_slot") not in {"left", "center", "right"}
            or set(self.condition)
            - {
                "source_slot",
                "trigger_member_cost_exact",
                "trigger_member_work_key",
                "trigger_member_unit_key",
                "trigger_member_not_source",
            }
        ):
            raise ValueError("overlap source policy requires a bounded positional entry observer")
        if (
            (self.cost_choice and self.cost_choice.selection_policy is not None)
            or (self.follow_up_choice and self.follow_up_choice.selection_policy is not None)
            or (
                self.choice and self.choice.selection_policy == "private_filtered_may_choose_none"
                and not any(op.action_type == "deploy_selected_to_stage" for op in self.actions)
            )
        ):
            raise ValueError("private selection policy requires bounded Stage deployment")
        if self.choice and self.choice.selection_policy == "public_yell_aqours_bottom_three" and (
            self.cost or self.cost_choice or self.follow_up_choice
            or self.condition or self.is_optional
            or self.trigger != "live_succeeded" or self.effect_type != "triggered"
            or self.timing != "live_success" or self.frequency_limit != "once_per_live"
            or self.execution_mode != "prompt_then_resolve" or self.duration is not None
            or len(self.actions) != 1
            or self.actions[0].model_dump(exclude_defaults=True, exclude_none=True) != {
                "action_type": "move_selected_to_deck_bottom",
            }
        ):
            raise ValueError(
                "Yell bottom selection only supports mandatory Live-success bottom return"
            )
        if any(op.amount_source == "selected_member_cost15_heart_amount"
               for op in [*self.cost, *self.actions]) and (
            not self.choice or self.choice.selection_policy != "public_other_nijigasaki_cost_heart"
        ):
            raise ValueError("cost15 Heart amount requires its bounded selection policy")
        if (self.choice
                and self.choice.selection_policy == "public_other_nijigasaki_cost_heart") and (
            self.cost or self.cost_choice or self.follow_up_choice
            or self.condition or self.is_optional
            or self.trigger != "live_started" or self.effect_type != "triggered"
            or self.execution_mode != "prompt_then_resolve" or self.duration != "live"
            or len(self.actions) != 1 or self.actions[0].action_type != "gain_heart"
            or self.actions[0].target != "selected" or self.actions[0].amount is not None
            or self.actions[0].amount_source != "selected_member_cost15_heart_amount"
            or self.actions[0].color_slot != "heart03" or self.actions[0].value is not None
            or self.actions[0].multiplier is not None or self.actions[0].branch is not None
            or self.actions[0].model_dump(exclude_defaults=True, exclude_none=True) != {
                "action_type": "gain_heart", "target": "selected", "color_slot": "heart03",
                "amount_source": "selected_member_cost15_heart_amount",
            }
        ):
            raise ValueError("other Nijigasaki selection only supports bounded cost15 Heart")
        if any(op.action_type == "modify_source_score_if_selected_blade_six"
               for op in self.actions) and (
            not self.choice
            or self.choice.selection_policy != "public_aqours_blade_six_source_score"
        ):
            raise ValueError("Blade-six source score requires its bounded selection policy")
        if (self.choice
                and self.choice.selection_policy == "public_aqours_blade_six_source_score") and (
            self.cost or self.cost_choice or self.follow_up_choice
            or self.condition or self.is_optional
            or self.trigger != "live_started" or self.timing != "live_start"
            or self.effect_type != "triggered" or self.frequency_limit != "once_per_live"
            or self.execution_mode != "prompt_then_resolve" or self.duration != "live"
            or len(self.actions) != 1
            or self.actions[0].model_dump(exclude_defaults=True, exclude_none=True) != {
                "action_type": "modify_source_score_if_selected_blade_six", "amount": 1,
            }
        ):
            raise ValueError("Aqours Blade-six policy only supports source Live score +1")
        if (self.choice
                and self.choice.selection_policy == "public_nijigasaki_blade_four_heart") and (
            self.cost or self.cost_choice or self.follow_up_choice
            or self.condition or self.is_optional
            or self.trigger != "live_started" or self.timing != "live_start"
            or self.effect_type != "triggered" or self.frequency_limit != "once_per_live"
            or self.execution_mode != "prompt_then_resolve" or self.duration != "live"
            or len(self.actions) != 1
            or self.actions[0].model_dump(exclude_defaults=True, exclude_none=True) != {
                "action_type": "gain_heart", "target": "selected", "amount": 2,
                "color_slot": "heart02",
            }
        ):
            raise ValueError("Blade-four selection only supports its mandatory Live-start Heart")
        if self.choice and self.choice.selection_policy == "public_single_as_much_as_possible" and (
            self.cost or self.cost_choice or self.follow_up_choice or self.condition or self.is_optional
            or self.trigger != "live_started" or self.effect_type != "triggered"
            or self.execution_mode != "prompt_then_resolve" or self.duration != "live"
            or len(self.actions) != 1 or self.actions[0].action_type != "gain_blade"
            or self.actions[0].target != "selected" or self.actions[0].amount != 1
            or self.actions[0].amount_source is not None or self.actions[0].value is not None
            or self.actions[0].branch is not None
        ):
            raise ValueError("public single selection only supports a mandatory named Live-start Blade")
        if self.choice and self.choice.selection_policy == "public_named_groups_as_much_as_possible":
            group_ids = {g.group_id for g in self.choice.selection_groups}
            if (
                self.cost or self.cost_choice or self.follow_up_choice or self.condition or self.is_optional
                or self.trigger != "live_started" or self.effect_type != "triggered"
                or self.execution_mode != "prompt_then_resolve" or self.duration != "live"
                or len(self.actions) != 4
                or any(op.action_type not in {"gain_heart", "gain_blade"}
                       or op.target != "selected" or op.amount != 1 or op.amount_source is not None
                       or op.multiplier is not None or op.orientation is not None
                       or op.branch is not None or not isinstance(op.value, dict)
                       or set(op.value) != {"target_group_id"}
                       or op.value.get("target_group_id") not in group_ids
                       or (op.action_type == "gain_heart" and not op.color_slot)
                       or (op.action_type == "gain_blade" and op.color_slot is not None)
                       for op in self.actions)
                or any(sorted(op.action_type for op in self.actions
                              if isinstance(op.value, dict) and op.value.get("target_group_id") == group_id)
                       != ["gain_blade", "gain_heart"] for group_id in group_ids)
            ):
                raise ValueError("public named groups only support one Heart and Blade per Live-start target")
        if any(op.action_type == "deploy_selected_to_stage" for op in self.actions):
            if (
                len(self.actions) != 1 or self.follow_up_choice is not None
                or self.cost_choice is not None or self.choice is None
                or self.choice.zone not in {"hand", "waiting_room"}
                or self.choice.target_player not in {None, "self"}
                or self.choice.choice_type != "card_from_zone"
                or self.choice.card_type != "member"
                or self.choice.minimum != 1 or self.choice.maximum != 1
                or any(
                    op.action_type != "pay_energy" or op.amount_source is not None
                    or op.target not in {None, "self"} or not op.amount or op.amount < 0
                    or op.branch is not None
                    for op in self.cost
                )
            ):
                raise ValueError(
                    "Stage deployment only supports one external Member and Energy cost"
                )
        if self.choice and self.choice.deployment_policy is not None and (
            self.actions or self.follow_up_choice is not None
        ):
            raise ValueError("simultaneous Member deployment does not support follow-up operations")
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
        if self.choice is not None and self.choice.auto_branch_from_cost_choice:
            if (
                self.choice.choice_type != "choose_effect_branch"
                or self.cost_choice is None
                or self.cost_choice.zone != "hand"
                or self.cost_choice.minimum != 1
                or self.cost_choice.maximum != 1
                or not any(operation.action_type == "discard_from_hand" for operation in self.cost)
            ):
                raise ValueError("cost result branch requires exactly one hand discard cost")
            conditions = self.choice.branch_cost_conditions
            if set(conditions) != set(self.choice.branch_ids) or len(conditions) != 2:
                raise ValueError("cost result branch requires two exhaustive work conditions")
            pairs = [next(iter(value.items())) for value in conditions.values() if len(value) == 1]
            if (
                len(pairs) != 2
                or {key for key, _ in pairs} != {
                    "selected_cost_has_work_key", "selected_cost_lacks_work_key",
                }
                or not pairs[0][1]
                or pairs[0][1] != pairs[1][1]
            ):
                raise ValueError("cost result branch requires complementary work conditions")
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
            row = connection.execute(
                """
                SELECT revision.id, revision.raw_text_hash
                FROM gameplay_cards AS card
                JOIN card_text_revisions AS revision
                  ON revision.gameplay_card_id = card.id
                WHERE card.card_code = ?
                ORDER BY revision.revision_number DESC, revision.id DESC
                LIMIT 1
                """,
                (effect.card_code,),
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
