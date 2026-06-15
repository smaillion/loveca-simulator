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
* trigger, timing, condition, cost, choice, visibility, action, and duration data
* `simulation_support`
* `execution_mode`
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
* `resolve_effect_choice`
* `manual_adjustment` with effect source fields

UI code must not execute effects, detect effects authoritatively, or mutate GameState directly.

## 4. Trigger And Resolution Rules

The MVP supports:

* `member_played` for `登場`
* player activation during Main Phase for `起動`
* `live_started` at comprehensive rule 8.3.8 timing
* `live_succeeded` after successful Live movement is determined
* `baton_touch_performed` after the Baton Touch event

Trigger detection belongs to the Rule Engine. Pending effects must originate from rule events, not from UI fallback or manual prompt creation.

Multiple waiting abilities owned by the same player must be exposed as selectable pending invocations. Forced effects with no player choice may resolve deterministically inside the Action that produced the trigger.

Optional effects may be declined explicitly. Silent skipping is forbidden.

## 5. Execution Modes

The MVP must distinguish:

* `auto_resolve`
* `prompt_then_resolve`
* `manual_resolution`

`prompt_then_resolve` is the default mode when a trigger is detected but a player must still confirm, choose a target, choose a card, choose Energy, choose count, choose order, or choose color.

`manual_resolution` must be reserved for unresolved semantic remainder after structured trigger and prompt boundaries are already known.

## 6. Initial Supported Operations

The restricted executor supports:

* draw a card
* discard a selected hand card
* return a selected Member from Waiting Room to hand
* apply Wait to the source Member
* apply Wait to selected Energy
* ready a selected Member
* pay Active Energy
* gain Heart until a bounded duration
* gain Blade until Live end
* modify score until a bounded duration
* ready Energy
* inspect top cards, select, reveal, reorder, and move remaining cards for registered patterns
* place the top Energy Deck card into the Energy Area as Active or Wait
* manual resolution

Unknown operations must fail registry validation.

The structured operation for Energy Deck placement is `place_energy_from_deck`. It must not expose the Energy Deck as a player card-selection zone. Resolution takes the deterministic top card, records the source as the Energy Deck, and records the resulting orientation. If an optional effect requires this operation and the Energy Deck is empty, the effect is not offered as activatable.

The MVP supports these prompt shapes for registered effects:

* card selection from hand, Waiting Room, Stage, or Energy Area
* Energy-instance selection
* Heart color selection
* count selection
* inspect-top selection and ordering

The MVP does not yet claim broad support for:

* arbitrary reveal-and-keep semantics outside registered patterns
* attached-card deployment flows
* arbitrary target-filter prompts
* continuous effects
* replacement effects

These gaps must remain explicit in docs and review artifacts until modeled.

## 7. Manual Resolution

An effect with `manual_resolution` support must remain pending until:

* the player declines it when the effect is optional; or
* a structured `ManualAdjustmentAction` identifies the invocation, effect, and source card instance.

Free-text-only resolution and direct UI mutation are forbidden.

`manual_resolution` must not be used as a generic substitute for structured target selection, Energy selection, or top-deck inspection when those prompt boundaries are already known.

## 8. Initial Card Coverage

The current reviewed implementation set is limited to:

* `LL-bp1-001`
* `PL!-bp3-001`
* `PL!-bp3-014`
* exact-text `登場` top-2 reorder entries registered in `effect-registry.v0.json`
* exact-text `ライブ成功時` top-3 reorder entries registered in `effect-registry.v0.json`
* `PL!-bp6-002`
* `PL!-bp6-008`
* `PL!N-bp1-001`
* `PL!HS-sd1-001`
* exact-text Energy Deck placement entries registered in `effect-registry.v0.json`

In addition, the registry may include broad timing-only `manual_resolution` entries for `登場`, `起動`, `ライブ開始時`, and `ライブ成功時` effects. These entries exist so the Rule Engine and LegalActionGenerator can surface replay-safe prompts at the correct timing. They do not imply structured semantic execution.

The executable subset remains intentionally narrow. Broad timing prompt coverage must not be described as broad automatic skill execution coverage.

Automated entries may be `test_validated_executable` after rule tests pass. Human review remains mandatory for `reviewed_executable`.

## 9. Replay Requirements

Invocation IDs, modifier IDs, choices, costs, results, visibility requirements, and usage records must be deterministic and serializable.

The same initial state and Action sequence must reproduce the same final state even if the external registry later changes.

## 10. Dependencies

Depends on:

* [002 Rule Engine](002-rule-engine.spec.md)
* [003 GameState and Actions](003-gamestate-and-actions.spec.md)
* [005 Action System](005-action-system.spec.md)
* [007 Effect DSL](007-effect-dsl.spec.md)
* [008 Randomness and Replay](008-randomness-and-replay.spec.md)
* [012 Controller and Legal Actions](012-controller-and-legal-actions.spec.md)
* [015 Effect Taxonomy](015-effect-taxonomy.spec.md)
* [018 Card Data Storage](018-card-data-storage.spec.md)
