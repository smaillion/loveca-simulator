"""Serializable runtime models for the local rules debugger."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from loveca.simulation.effects import EffectDefinition

RULE_VERSION = "1.06"
MATCH_RUNTIME_SCHEMA_VERSION = 2

Phase = Literal[
    "setup_choose_first",
    "setup_mulligan_first",
    "setup_mulligan_second",
    "first_active",
    "first_energy",
    "first_draw",
    "first_main",
    "second_active",
    "second_energy",
    "second_draw",
    "second_main",
    "live_set_first",
    "live_set_second",
    "performance_first",
    "yell_first",
    "performance_second",
    "yell_second",
    "live_judgment",
    "turn_complete",
    "complete",
]

ModifierDuration = Literal["live", "turn", "game"]
ModifierType = Literal["score", "blade", "heart", "flag"]


class SpecialBladeHeart(BaseModel):
    effect_type: Literal["all_color", "draw", "score", "unknown"]
    value: int | None = None
    source_alt: str


class CardDefinition(BaseModel):
    card_code: str
    card_id: str
    image_url: str | None = None
    name_ja: str
    card_type: Literal["member", "live", "energy"]
    cost: int | None = None
    blade: int | None = None
    score: int | None = None
    basic_hearts: dict[str, int] = Field(default_factory=dict)
    required_hearts: dict[str, int] = Field(default_factory=dict)
    blade_heart_color_slot: str | None = None
    special_blade_hearts: list[SpecialBladeHeart] = Field(default_factory=list)
    raw_effect_text_ja: str | None = None
    text_revision_id: int | None = None
    raw_text_hash: str | None = None
    work_keys: list[str] = Field(default_factory=list)
    unit_keys: list[str] = Field(default_factory=list)
    ability_bucket: Literal["none", "static_only", "other"] = "none"
    effect_ids: list[str] = Field(default_factory=list)
    effect_registry_status: Literal[
        "supported", "unregistered", "hash_mismatch"
    ] = "unregistered"
    effect_registry_errors: list[str] = Field(default_factory=list)


class CardInstance(BaseModel):
    instance_id: str
    owner_id: str
    card: CardDefinition
    orientation: Literal["active", "wait"] = "active"
    face_up: bool = True


class LivePerformanceResult(BaseModel):
    blade_count: int = 0
    revealed_instance_ids: list[str] = Field(default_factory=list)
    member_hearts: dict[str, int] = Field(default_factory=dict)
    manual_hearts: dict[str, int] = Field(default_factory=dict)
    yell_hearts: dict[str, int] = Field(default_factory=dict)
    available_hearts: dict[str, int] = Field(default_factory=dict)
    all_color_hearts: int = 0
    special_blade_heart_results: list[dict[str, Any]] = Field(default_factory=list)
    draw_count: int = 0
    live_allocations: list[dict[str, Any]] = Field(default_factory=list)
    score_bonus: int = 0
    base_score: int = 0
    requirements_satisfied: bool | None = None
    total_score: int = 0


class ManualModifier(BaseModel):
    modifier_id: str
    modifier_type: ModifierType
    duration: ModifierDuration
    created_turn: int
    amount: int | None = None
    color_slot: str | None = None
    flag: str | None = None
    value: Any = None
    target_card_instance_id: str | None = None


class EffectInvocation(BaseModel):
    invocation_id: str
    effect_id: str
    source_card_instance_id: str
    player_id: str
    trigger_event: str
    trigger_data: dict[str, Any] = Field(default_factory=dict)
    resolution_stage: Literal["initial", "after_cost"] = "initial"


class EffectUsage(BaseModel):
    effect_id: str
    source_card_instance_id: str
    turn_number: int
    usage_count: int = 1


class PlayerState(BaseModel):
    player_id: str
    name: str
    main_deck: list[str] = Field(default_factory=list)
    energy_deck: list[str] = Field(default_factory=list)
    hand: list[str] = Field(default_factory=list)
    member_area: dict[str, str | None] = Field(
        default_factory=lambda: {"left": None, "center": None, "right": None}
    )
    member_area_attachments: dict[str, list[str]] = Field(
        default_factory=lambda: {"left": [], "center": [], "right": []}
    )
    member_areas_entered_this_turn: list[str] = Field(default_factory=list)
    energy_area: list[str] = Field(default_factory=list)
    live_area: list[str] = Field(default_factory=list)
    waiting_room: list[str] = Field(default_factory=list)
    resolution_area: list[str] = Field(default_factory=list)
    success_live_area: list[str] = Field(default_factory=list)
    manual_modifiers: list[ManualModifier] = Field(default_factory=list)
    refresh_count: int = 0
    live_result: LivePerformanceResult = Field(default_factory=LivePerformanceResult)


class PendingChoice(BaseModel):
    choice_type: Literal[
        "mulligan",
        "live_requirements",
        "success_live",
        "manual_card_selection",
        "effect_inspection_selection",
        "multi_player_effect_selection",
    ]
    player_id: str
    message_ja: str
    message_zh: str
    options: dict[str, Any] = Field(default_factory=dict)


class GameResult(BaseModel):
    outcome: Literal["win", "draw"]
    winner_player_ids: list[str] = Field(default_factory=list)
    reason: Literal["success_live_threshold"] = "success_live_threshold"
    final_turn: int


class MatchState(BaseModel):
    match_id: str
    rule_version: str = RULE_VERSION
    seed: int
    revision: int = 0
    phase: Phase = "setup_choose_first"
    first_player_id: str | None = None
    second_player_id: str | None = None
    turn_number: int = 1
    next_first_player_id: str | None = None
    success_live_moved_player_ids: list[str] = Field(default_factory=list)
    success_live_moved_instance_ids: dict[str, list[str]] = Field(default_factory=dict)
    live_success_effects_queued: bool = False
    active_player_id: str | None = None
    players: dict[str, PlayerState]
    cards: dict[str, CardInstance]
    effect_registry_version: str | None = None
    effect_definitions: dict[str, EffectDefinition] = Field(default_factory=dict)
    pending_effects: list[EffectInvocation] = Field(default_factory=list)
    effect_usage: list[EffectUsage] = Field(default_factory=list)
    pending_choice: PendingChoice | None = None
    live_winner_ids: list[str] = Field(default_factory=list)
    live_judgment_summary: dict[str, Any] | None = None
    game_result: GameResult | None = None
    completed_reason: str | None = None


class ActionRequest(BaseModel):
    action_id: str | None = None
    action_type: Literal[
        "choose_first_player",
        "submit_mulligan",
        "advance_phase",
        "play_member",
        "end_main_phase",
        "set_live_cards",
        "resolve_live_requirements",
        "manual_adjustment",
        "start_next_turn",
        "activate_effect",
        "resolve_effect",
        "resolve_effect_choice",
        "skip_effect",
        "resolve_manual_inspection",
    ]
    expected_revision: int
    player_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class GameEvent(BaseModel):
    event_type: str
    player_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    source: Literal["player", "system", "manual"] = "system"


class LegalAction(BaseModel):
    action_type: str
    player_id: str | None = None
    label_zh: str
    label_ja: str
    options: dict[str, Any] = Field(default_factory=dict)


class ActionResult(BaseModel):
    state: MatchState
    events: list[GameEvent]
    legal_actions: list[LegalAction]
