# 011 Simulator MVP Specification

## 1. Purpose

This spec defines effect-related requirements for the Battle Simulator MVP.

It does not define implementation code, UI, APIs, database schemas, or full effect execution.

## 2. MVP Execution Strategy

Battle Simulator MVP may use:

* numeric card data
* basic rule engine behavior
* manual effect handling
* limited auto-executable effects

The simulator must not wait for every semantic card effect to become fully executable.

MVP rule coverage is intentionally narrow. Unsupported official rule details must be documented as assumptions rather than silently treated as complete rule coverage.

## 3. Automated Structural Processes

The MVP should automate basic numeric and structural processes:

* draw
* hand management
* Energy handling
* playing Members
* playing Lives
* Live success checks
* score and victory tracking
* basic zone movement

## 4. Manual Resolution Policy

For `manual_resolution` effects, the simulator should:

1. Display `raw_effect_text`.
2. Pause automatic resolution.
3. Ask the human player to resolve manually.
4. Record the result as one or more structured `ManualAdjustmentAction` records.
5. Allow the game to continue.

Manual resolution prompts belong to presentation/controller flow, not the core Rule Engine. Manual resolution must not mutate GameState directly.

`ManualAdjustmentAction` fields and adjustment entry fields are owned by [005-action-system.spec.md](005-action-system.spec.md).

## 5. AI vs AI Debug Policy

For AI vs AI debug mode, the default policy for cards with `manual_resolution` effects is `skip_and_log`.

Under `skip_and_log`, the semantic effect is skipped, the skip is recorded in the Action log or simulation log, and the game continues only through legal Actions.

Approximation by `effect_tags` is allowed only in explicit experimental mode. Silent auto-resolution is forbidden.

Alternative explicit policies may include:

* `tag_approximation_experimental`
* `exclude_manual_cards`

The selected policy must be logged in run assumptions.

## 6. Support Status Requirement

The simulator must check effect `simulation_support` before auto-resolution.

Only `partially_executable`, `fully_executable`, `test_validated_executable`, and `reviewed_executable` effects may be considered for automatic handling, and partially executable effects must expose manual boundaries.

For default local simulator runs, `reviewed_executable` and `test_validated_executable` should be preferred when available. `fully_executable` may be used for local development or prototype automation only when the run output clearly labels the effect support status and assumptions. Public recommended executable card pools require review and approval as defined by [015-effect-taxonomy.spec.md](015-effect-taxonomy.spec.md) and [017-public-release-and-export-policy.spec.md](017-public-release-and-export-policy.spec.md).

## 7. Dependencies

Depends on:

* [002-rule-engine.spec.md](002-rule-engine.spec.md)
* [003-gamestate-and-actions.spec.md](003-gamestate-and-actions.spec.md)
* [005-action-system.spec.md](005-action-system.spec.md)
* [008-randomness-and-replay.spec.md](008-randomness-and-replay.spec.md)
* [007-effect-dsl.spec.md](007-effect-dsl.spec.md)
* [010-simple-ai.spec.md](010-simple-ai.spec.md)
* [012-controller-and-legal-actions.spec.md](012-controller-and-legal-actions.spec.md)
* [015-effect-taxonomy.spec.md](015-effect-taxonomy.spec.md)
