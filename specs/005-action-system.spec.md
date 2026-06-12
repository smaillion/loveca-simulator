# 005 Action System Specification

## 1. Purpose

This spec defines conceptual requirements for replay-safe Actions, including manual adjustment actions.

It does not define implementation code, database schema, APIs, or UI behavior.

GameState ownership and high-level transition requirements are defined by [003-gamestate-and-actions.spec.md](003-gamestate-and-actions.spec.md). This spec owns Action safety and manual adjustment structure.

## 2. Core Action Rule

All GameState changes must go through serializable Actions resolved by the ActionResolver.

Actions must:

* be serializable
* be replayable
* be loggable
* identify the acting player or responsible system process
* preserve enough context for validation
* avoid direct GameState mutation outside ActionResolver

## 3. ManualAdjustmentAction

Manual resolution must produce structured, serializable, replayable `ManualAdjustmentAction` records.

`ManualAdjustmentAction` is a container action that contains one or more low-level adjustment entries.

Minimum `ManualAdjustmentAction` fields:

* `action_id`
* `action_type`
* `match_id`
* `turn`
* `phase`
* `player_id`
* `source`
* `source_card_instance_id`
* `source_effect_id`
* `reason`
* `adjustments`
* `requires_confirmation`
* `confirmed_by`
* `created_at`
* `note`

`note` is optional supporting context. Note-only manual resolution is forbidden.

`source_card_instance_id` identifies the runtime card copy in GameState. It must not be confused with official printing `card_id` or Gameplay Card `card_code`.

## 4. Adjustment Entry

Each `ManualAdjustmentAction` contains one or more adjustment entries.

Minimum adjustment entry fields:

* `adjustment_id`
* `adjustment_type`
* `target_card_instance_id`
* `from_zone`
* `to_zone`
* `from_position`
* `to_position`
* `amount`
* `target_player_id`
* `metadata`

Initial `adjustment_type` values:

* `move_card`
* `draw_card`
* `inspect_top_cards`
* `discard_card`
* `ready_energy`
* `pay_energy`
* `apply_wait`
* `remove_wait`
* `modify_score`
* `modify_heart`
* `modify_blade`
* `set_flag`
* `clear_flag`

`inspect_top_cards` is a two-step manual operation. It moves a specified
number of cards from the top of the main deck to the Resolution Area and
creates a pending structured choice. The resolving Action must record:

* inspected card instance IDs
* Japanese selection criteria
* minimum and maximum selection count
* selected card instance IDs
* whether selected cards are revealed to the opponent
* selected and unselected destinations

Selected cards may move to hand only after the pending choice is resolved.
Unselected cards move to the destination required by the effect, initially
Waiting Room. Treating this operation as ordinary `draw_card` is forbidden.

## 5. Validation Requirements

`ManualAdjustmentAction` must be validated at least for:

* zone existence
* card ownership
* card instance existence
* legal target player reference
* basic structural consistency
* required confirmation when `requires_confirmation` is true

Manual adjustment validation is not a substitute for full semantic effect execution. It is the replay-safe boundary for manual resolution.

## 6. Forbidden Patterns

Manual resolution must not:

* be free-text only
* bypass action logging
* mutate GameState directly
* skip ActionResolver
* rely on UI-only state
* produce unreplayable match history

## 7. Dependencies

Informs:

* [002-rule-engine.spec.md](002-rule-engine.spec.md)
* [003-gamestate-and-actions.spec.md](003-gamestate-and-actions.spec.md)
* [008-randomness-and-replay.spec.md](008-randomness-and-replay.spec.md)
* [011-simulator-mvp.spec.md](011-simulator-mvp.spec.md)
* [015-effect-taxonomy.spec.md](015-effect-taxonomy.spec.md)
