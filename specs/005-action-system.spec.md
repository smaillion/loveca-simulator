# 005 Action System Specification

## 1. Purpose

This spec defines conceptual requirements for replay-safe Actions, including manual adjustment actions.

It does not define implementation code, database schema, APIs, or UI behavior.

GameState ownership and high-level transition requirements are defined by [003-gamestate-and-actions.spec.md](003-gamestate-and-actions.spec.md). This spec owns Action safety, structured prompt follow-up, and manual adjustment boundaries.

## 2. Core Action Rule

All GameState changes must go through serializable Actions resolved by the ActionResolver.

Actions must:

* be serializable
* be replayable
* be loggable
* identify the acting player or responsible system process
* preserve enough context for validation
* avoid direct GameState mutation outside ActionResolver

## 3. Structured Effect Follow-Up

An effect that requires user choice must first become a structured pending decision owned by the Rule Engine and LegalActionGenerator.

Examples include:

* inspect top cards, then keep some
* choose specific Energy cards for a cost or state change
* choose a target Member to ready or apply Wait
* choose a Heart color
* choose card order on top of deck
* accept or decline an optional effect

These are not generic manual adjustments. They are structured effect-resolution steps and should be represented by dedicated Actions such as `resolve_effect` or future choice-resolution Actions.

## 4. ManualAdjustmentAction

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

`ManualAdjustmentAction` is the replay-safe boundary for semantic remainder that is still unresolved after structured trigger, cost, choice, target, and visibility handling have been modeled.

It is not a generic skill interpreter.

## 5. Adjustment Entry

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
* `move_member`
* `attach_card_under_member`
* `move_attached_card`
* `position_change`
* `formation_change`
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

`move_member` accepts only a top Member currently occupying a Member Area.
The engine derives the source slot from the card instance and rejects Members
in the hand, decks, other zones, or attached under another Member. Moving to an
occupied destination swaps the complete Member groups, including attachments.
`position_change` remains the slot-oriented equivalent for replay compatibility.

`inspect_top_cards` is a two-step manual operation. It moves a specified
number of cards from the top of the main deck to the Resolution Area and
creates a pending structured choice. The resolving Action must record:

* inspected card instance IDs
* minimum and maximum selection count
* selected card instance IDs
* whether selected cards are revealed to the opponent
* selected and unselected destinations

Selected cards may move to hand only after the pending choice is resolved.
Unselected cards move to the destination required by the effect, initially
Waiting Room. Treating this operation as ordinary `draw_card` is forbidden.

Stage adjustment entries must preserve the distinction between a top Member
and cards under that Member. Generic `move_card` must not silently detach a
card from under a Member. Position and formation changes move the complete
Member group, including all cards under the top Member.

## 6. Manual-Adjustment Boundaries

`ManualAdjustmentAction` must not be used to replace effect semantics that should already be modeled as structured prompt data.

The following distinctions are required:

* `draw_card` must not be used to represent top-deck inspection, reveal, filtered keep-to-hand, or search.
* `pay_energy` must be distinct from choosing Energy cards to become Wait or Active.
* moving a new Energy card from the Energy Deck into the Energy Area must use a structured effect operation and must not be represented as `draw_card`, `move_card`, or a manual Energy adjustment.
* `discard_card` must be distinct from choosing cards from hand under modeled effect filters.
* selecting cards to keep after inspection must not be modeled as generic draw.
* target selection for ready or Wait effects must not be represented only as a free-form note.

If an effect depends on inspect, reveal, choose, target, or cost selection, the engine should first surface a structured pending choice. Manual adjustment should only capture the unresolved semantic remainder and resulting state changes.

## 7. Validation Requirements

`ManualAdjustmentAction` must be validated at least for:

* zone existence
* card ownership
* card instance existence
* legal target player reference
* basic structural consistency
* required confirmation when `requires_confirmation` is true

Manual adjustment validation is not a substitute for full semantic effect execution. It is the replay-safe boundary for manual resolution after structured prompt boundaries have already been respected.

## 8. Forbidden Patterns

Manual resolution must not:

* be free-text only
* bypass action logging
* mutate GameState directly
* skip ActionResolver
* rely on UI-only state
* produce unreplayable match history
* serve as the first and only modeling layer for a choice-driven effect

## 9. Dependencies

Informs:

* [002-rule-engine.spec.md](002-rule-engine.spec.md)
* [003-gamestate-and-actions.spec.md](003-gamestate-and-actions.spec.md)
* [008-randomness-and-replay.spec.md](008-randomness-and-replay.spec.md)
* [011-simulator-mvp.spec.md](011-simulator-mvp.spec.md)
* [015-effect-taxonomy.spec.md](015-effect-taxonomy.spec.md)
