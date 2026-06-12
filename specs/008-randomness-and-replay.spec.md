# 008 Randomness and Replay Specification

## 1. Purpose

This spec defines conceptual requirements for deterministic randomness, replay-safe state transitions, and manual resolution recording.

It does not define implementation code, APIs, persistence schema, or replay UI.

## 2. Deterministic Randomness

All random operations must support deterministic seeds.

This includes:

* deck shuffle
* opening hand draw
* mulligan randomness, if any
* AI tie-breaks
* Monte Carlo simulation runs
* supported random effect resolution

Randomness must not be hidden inside arbitrary helper behavior.

## 3. Replay-Safe State Changes

All GameState changes must be represented by serializable Actions.

Replay reproduction should be possible from:

* initial GameState
* deck order or shuffle seed
* deterministic random seed context
* ordered Action log
* rule version
* relevant source data versions

## 4. Manual Resolution

Manual effect resolution must produce structured `ManualAdjustmentAction` records.

Note-only log annotations are not replay-safe.

Manual resolution must not mutate GameState directly. A manual adjustment must describe the intended state change as a serializable, replayable Action that can be validated against manual-resolution rules and recorded in the Action log.

## 5. ManualAdjustmentAction Requirements

`ManualAdjustmentAction` is defined by [005-action-system.spec.md](005-action-system.spec.md).

It is a container action that contains one or more low-level adjustment entries.

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

Initial adjustment types:

* `move_card`
* `draw_card`
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

Manual adjustment actions must be validated at least for zone existence, card ownership, and basic structural consistency.

## 6. Replay Output Requirements

Replay records should distinguish:

* automatic Actions
* partially executable effect Actions
* manual adjustment Actions
* AI-selected Actions
* system-generated Actions

This distinction is required for debugging, future online readiness, and explaining simulator behavior when effect support improves later.

## 7. Dependencies

Depends on:

* [005 Action System](005-action-system.spec.md)
* [011 Simulator MVP](011-simulator-mvp.spec.md)
* [015 Effect Taxonomy](015-effect-taxonomy.spec.md)
