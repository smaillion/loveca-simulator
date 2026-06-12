# 019 Effect Execution MVP Specification

## 1. Purpose

This specification defines the first limited executable-effect slice for the local Battle Simulator.

It does not define the final Effect DSL, a database schema, AI behavior, full card coverage, or automatic parsing from Japanese text.

## 2. Registry Boundary

Executable effect definitions are stored in a version-controlled JSON registry for this MVP.

Every definition must identify:

* `effect_id`
* `card_code`
* `text_revision_id`
* `raw_text_hash`
* `effect_index`
* trigger, condition, cost, choice, action, and duration data
* `simulation_support`
* `review_status`

The registry must be validated against Card Text Revision data when a match is created. A missing revision or hash mismatch prevents that effect from loading.

The complete validated definitions used by a match must be serialized into its initial GameState. Replay must not depend on the current registry file.

## 3. State And Action Boundary

GameState owns:

* the registry version
* validated effect-definition snapshots
* pending effect invocations
* per-turn effect usage
* effect-created modifiers

Controllers may only interact with effects through LegalActionGenerator output.

The initial effect actions are:

* `activate_effect`
* `resolve_effect`
* `manual_adjustment` with effect source fields

UI code must not execute effects or mutate GameState directly.

## 4. Trigger And Resolution Rules

The MVP supports:

* `member_played` for `登場`
* player activation during Main Phase for `起動`
* `live_started` at comprehensive rule 8.3.8 timing
* `baton_touch_performed` after the Baton Touch event

Multiple waiting automatic abilities owned by the same player must be exposed as selectable pending invocations. Forced effects with no player choice may resolve deterministically inside the Action that produced the trigger.

Optional effects may be declined explicitly. Silent skipping is forbidden.

## 5. Initial Supported Operations

The restricted executor supports:

* draw a card
* discard a selected hand card
* return a selected Member from Waiting Room to hand
* apply Wait to the source Member
* ready a selected Member
* pay Active Energy
* gain Blade until Live end
* ready Energy
* manual resolution

Unknown operations must fail registry validation.

## 6. Manual Resolution

An effect with `manual_resolution` support must remain pending until:

* the player declines it when the effect is optional; or
* a structured `ManualAdjustmentAction` identifies the invocation, effect, and source card instance.

Free-text-only resolution and direct UI mutation are forbidden.

## 7. Initial Card Coverage

The first reviewed implementation set is limited to:

* `LL-bp1-001`
* `PL!-bp3-001`
* `PL!N-bp1-001`
* `PL!HS-sd1-001`

Automated entries may be `test_validated_executable` after rule tests pass. Human review remains mandatory for `reviewed_executable`.

## 8. Replay Requirements

Invocation IDs, modifier IDs, choices, costs, results, and usage records must be deterministic and serializable.

The same initial state and Action sequence must reproduce the same final state even if the external registry later changes.

## 9. Dependencies

Depends on:

* [002 Rule Engine](002-rule-engine.spec.md)
* [003 GameState and Actions](003-gamestate-and-actions.spec.md)
* [005 Action System](005-action-system.spec.md)
* [007 Effect DSL](007-effect-dsl.spec.md)
* [008 Randomness and Replay](008-randomness-and-replay.spec.md)
* [012 Controller and Legal Actions](012-controller-and-legal-actions.spec.md)
* [015 Effect Taxonomy](015-effect-taxonomy.spec.md)
* [018 Card Data Storage](018-card-data-storage.spec.md)
