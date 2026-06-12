# 015 Effect Taxonomy Specification

## 1. Purpose

This specification defines the first conceptual taxonomy for semantic card effects.

It applies to both first-class products:

* Deck Analyzer
* Playable Battle Simulator

This spec does not define a database schema, API contract, scraper, UI, migration, or executable effect implementation.

## 2. Design Principle

Card effects must be modeled in four separate layers:

1. `raw_effect_text`
2. `effect_tags`
3. structured Effect DSL
4. executable effect implementation

Raw official Japanese text must always be preserved. Effect tags support Deck Analyzer and Simple AI. Structured Effect DSL supports future simulator automation. Executable implementations are trusted only after validation and review.

## 3. Simulation Support Status

Every card effect must have a `simulation_support` status.

Required statuses:

* `unsupported`: only raw official text is stored.
* `tagged_only`: effect has tags but no executable DSL.
* `manual_resolution`: simulator displays raw text and asks the player to resolve manually.
* `partially_executable`: some parts can be automated, some require manual handling.
* `fully_executable`: effect can be executed by the engine.
* `test_validated_executable`: effect is executable and covered by automated rule-test validation, but has not completed required human review.
* `reviewed_executable`: effect is executable and manually reviewed.

The Battle Simulator must not auto-resolve `unsupported`, `tagged_only`, or `manual_resolution` effects.

## 4. Effect Instance Fields

An effect instance should conceptually include:

* `effect_id`
* `card_code`
* `text_revision_id`
* `effect_index`
* `raw_text`
* `effect_type`
* `timing`
* `frequency_limit`
* `is_optional`
* `cost`
* `condition`
* `choice`
* `target`
* `actions`
* `duration`
* `modifier`
* `source_zone`
* `affected_zone`
* `simulation_support`
* `parse_confidence`
* `review_status`
* `parser_version`
* `raw_text_hash`

These fields are conceptual requirements for future specs. They are not a final SQL schema or implementation class.

`card_code` identifies the Gameplay Card. `text_revision_id` and `raw_text_hash` identify the exact official Japanese text being interpreted. Effect instances must not bind directly to a printing `card_id`.

## 5. Effect Types

The first DSL version should support:

* `triggered`: an effect that triggers from a game event.
* `activated`: an effect the player chooses to activate during a valid timing window.
* `continuous`: an effect that continuously modifies state while its condition is true.
* `replacement`: an effect that replaces or modifies another event or rule process.
* `static`: a non-triggered rule-like ability defining a property or restriction.
* `manual`: an intentionally non-executable effect requiring manual handling.

## 6. Timing Types

The first DSL version should support:

* `on_play`
* `activated_main`
* `auto_event`
* `live_start`
* `live_success`
* `always`

## 7. Action Categories

The first DSL version should support:

* `draw_card`
* `look_at_top_cards`
* `select_card_to_hand`
* `discard_from_hand`
* `move_card`
* `ready_energy`
* `pay_energy`
* `position_change`
* `apply_wait`
* `gain_blade`
* `gain_heart`
* `modify_score`
* `return_from_waiting_room`
* `stack_deck`

## 8. Condition Categories

The first DSL version should support:

* `zone_contains`
* `card_attribute_match`
* `cost_threshold`
* `count_threshold`
* `score_threshold`
* `this_turn_event`
* `revealed_card_condition`
* `opponent_state_condition`

## 9. Conceptual DSL Flow

Structured effects should follow:

```text
Trigger -> Condition -> Cost -> Choice -> Target -> Action -> Duration
```

Choices and targets must remain compatible with legal action generation and future replay.

## 10. Deck Analyzer Policy

Deck Analyzer MVP may rely on `effect_tags` rather than fully executable effects.

Recommended effect tags:

* `draw`
* `search`
* `energy_boost`
* `cost_reduce`
* `live_support`
* `heart_gain`
* `blade_gain`
* `score_boost`
* `recycle`
* `starter`
* `consistency`
* `finisher`
* `manual_complexity`
* `requires_choice`

Deck Analyzer must not require all effects to be fully executable.

## 11. Battle Simulator MVP Policy

Battle Simulator MVP may use:

* numeric card data
* basic rule engine behavior
* manual effect handling
* limited auto-executable effects

Basic numeric and structural processes should be automated:

* draw
* hand management
* Energy handling
* playing Members
* playing Lives
* Live success checks
* score and victory tracking
* basic zone movement

For `manual_resolution` effects, the simulator should:

1. Display `raw_effect_text`.
2. Pause automatic resolution.
3. Ask the human player to resolve manually.
4. Record the result as one or more structured `ManualAdjustmentAction` records.
5. Allow the game to continue.

Manual resolution must not mutate GameState directly.

`ManualAdjustmentAction` fields and adjustment entry fields are owned by [005-action-system.spec.md](005-action-system.spec.md).

For AI vs AI debug mode, default policy for `manual_resolution` effects is `skip_and_log`.

Under `skip_and_log`, the semantic effect is skipped with explicit log annotation, and play continues only through legal Actions.

Approximation by `effect_tags` is allowed only in explicit experimental mode. Silent auto-resolution is forbidden.

Other explicit policies may include:

* `tag_approximation_experimental`
* `exclude_manual_cards`

## 12. LLM-Assisted Parsing Policy

LLM-assisted parsing may generate initial `effect_tags` and Effect DSL drafts.

LLM output is not authoritative.

The system must preserve:

* `parse_confidence`
* `parser_version`
* `raw_text_hash`
* `review_status`

A card effect must not become `reviewed_executable` without human review. Automated rule-test validation alone is not enough.

Automated rule-test validation may promote an effect to `test_validated_executable` when execution behavior is covered by tests but human review is still pending.

Recommended pipeline:

```text
Official raw text
-> Card Text Revision
-> LLM-assisted draft parse
-> effect_tags
-> Effect DSL draft
-> schema validation
-> rule validation
-> test_validated_executable, when automated rule tests cover behavior
-> manual review
-> reviewed_executable effect
```

## 13. Review Workflow

The effect review workflow is intentionally lightweight but must distinguish parser output, contributor proposals, human review, rules-sensitive review, and release approval.

Initial roles:

* `parser`: automated parser, script, or LLM-assisted process that creates initial effect tags or Effect DSL drafts.
* `contributor`: human contributor who proposes corrections or manual effect mappings.
* `reviewer`: human reviewer who checks that Effect DSL matches official card text.
* `rules_reviewer`: human reviewer who checks timing, rule interpretation, FAQ/ruling-sensitive behavior, and complex interactions.
* `maintainer`: project maintainer who approves final inclusion or release.

Initial review states:

* `unparsed`
* `parsed_draft`
* `schema_validated`
* `test_validated`
* `human_reviewed`
* `rules_reviewed`
* `approved`
* `deprecated`

Review should confirm:

* raw Japanese text matches the modeled effect
* tags are appropriate
* DSL timing and conditions are correct
* cost, choice, target, and actions match official meaning
* executable behavior follows the Rule Engine
* replay and deterministic behavior are preserved

Authority rules:

* `fully_executable` means the effect can technically execute.
* `test_validated_executable` means the effect passes automated rule tests.
* `reviewed_executable` requires human review.
* Automated rule-test validation alone cannot promote an effect to `reviewed_executable`.
* Effects involving complex timing, replacement effects, continuous effects, opponent choice, or official FAQ/ruling-sensitive behavior require `rules_reviewer` review before `reviewed_executable`.
* `maintainer` approval is required for public release or an official recommended executable card pool.

## 14. Anti-Patterns

Avoid:

* treating all effects as raw text only
* hard-coding card effects by `card_code` or printing `card_id` inside the game engine
* binding effect interpretations directly to Card Printing instead of Card Text Revision
* letting UI directly implement card effect logic
* letting AI bypass rule validation
* assuming LLM-parsed effects are authoritative
* blocking simulator MVP until every effect is fully executable
* mixing manual resolution UI prompts into the core rule engine
* making Deck Analyzer depend on full effect execution
* making GameState impossible to serialize
* making effect parsing impossible to audit or re-run

## 15. Dependencies

Depends on:

* [005-action-system.spec.md](005-action-system.spec.md)
* [008-randomness-and-replay.spec.md](008-randomness-and-replay.spec.md)
* [016-terminology-normalization.spec.md](016-terminology-normalization.spec.md)
* [017-public-release-and-export-policy.spec.md](017-public-release-and-export-policy.spec.md)
