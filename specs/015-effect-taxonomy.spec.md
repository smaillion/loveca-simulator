# 015 Effect Taxonomy Specification

## 1. Purpose

This specification defines the conceptual taxonomy for semantic card effects.

It applies to both first-class products:

* Deck Analyzer
* Playable Battle Simulator

This spec does not define a database schema, API contract, scraper, UI implementation, migration, or executable effect code.

## 2. Design Principle

Card effects must be modeled in four separate layers:

1. `raw_effect_text`
2. `effect_tags`
3. structured Effect DSL
4. executable effect implementation

Raw official Japanese text must always be preserved. Effect tags support Deck Analyzer and Simple AI. Structured Effect DSL supports future simulator automation. Executable implementations are trusted only after validation and review.

## 3. Two Classification Axes

Every effect instance must be classified on two different axes:

* `simulation_support`: how much of the effect is automated and trusted
* `execution_mode`: how the simulator currently interacts with the effect

These axes must not be conflated.

`simulation_support` describes automation and review maturity.

`execution_mode` describes runtime interaction shape:

* `auto_resolve`: the engine can resolve the effect inside the triggering or resolving Action without additional player input.
* `prompt_then_resolve`: the engine detects the effect, creates a legal effect-resolution prompt, and resolves it only after structured player choice, target selection, cost selection, or acceptance.
* `manual_resolution`: the engine detects the effect, but the unresolved semantic remainder must be completed through replay-safe manual Actions.

UI must not infer `execution_mode` on its own. It is owned by effect modeling, Rule Engine trigger detection, and LegalActionGenerator output.

## 4. Simulation Support Status

Every card effect must have a `simulation_support` status.

Required statuses:

* `unsupported`: only raw official text is stored.
* `tagged_only`: effect has tags but no executable DSL.
* `manual_resolution`: the effect is detected and surfaced, but its semantic meaning is not modeled deeply enough for structured automated handling.
* `partially_executable`: trigger, condition, cost, choice, and target boundaries are modeled, but some semantic steps still require manual completion.
* `fully_executable`: effect can be executed by the engine under supported assumptions.
* `test_validated_executable`: effect is executable and covered by automated rule-test validation, but has not completed required human review.
* `reviewed_executable`: effect is executable and manually reviewed.

The Battle Simulator must not auto-resolve `unsupported`, `tagged_only`, or `manual_resolution` effects.

`partially_executable` must not be assigned unless the effect already has explicit structured trigger, cost, choice, and target boundaries. Partial automation without a structured prompt boundary is forbidden.

## 5. Effect Instance Fields

An effect instance should conceptually include:

* `effect_id`
* `card_code`
* `text_revision_id`
* `effect_index`
* `raw_text`
* `raw_text_hash`
* `effect_type`
* `trigger`
* `timing`
* `frequency_limit`
* `is_optional`
* `simulation_support`
* `execution_mode`
* `parse_confidence`
* `review_status`
* `parser_version`
* `condition`
* `cost`
* `choice`
* `target`
* `visibility`
* `actions`
* `duration`
* `modifier`
* `source_zone`
* `affected_zone`

These fields are conceptual requirements for future specs. They are not a final SQL schema or implementation class.

`card_code` identifies the Gameplay Card. `text_revision_id` and `raw_text_hash` identify the exact official Japanese text being interpreted. Effect instances must not bind directly to a printing `card_id`.

## 6. Effect Types

The first DSL version should support:

* `triggered`: an effect that triggers from a game event.
* `activated`: an effect the player chooses to activate during a valid timing window.
* `continuous`: an effect that continuously modifies state while its condition is true.
* `replacement`: an effect that replaces or modifies another event or rule process.
* `static`: a non-triggered rule-like ability defining a property or restriction.
* `manual`: an intentionally non-executable effect requiring manual handling.

## 7. Trigger And Timing Types

The first structured model must preserve both official Japanese trigger labels and normalized internal trigger/timing values.

### Official label mapping

Initial normalized mapping:

* `【登場】` -> trigger `member_played`, timing `on_play`
* `【起動】` -> trigger `player_activation`, timing `activated_main`
* `【ライブ開始時】` -> trigger `live_started`, timing `live_start`
* `【ライブ成功時】` -> trigger `live_succeeded`, timing `live_success`
* `【自動】` -> trigger `auto_triggered_event`, timing `auto_triggered_event`
* `【常時】` -> trigger `static_always`, timing `static_always`
* `【バトンタッチ】` or Baton-Touch-specific trigger text -> trigger `baton_touch_performed`, timing `baton_touch`

The audit layer must preserve the original Japanese label even when multiple labels normalize to the same internal timing family.

### Normalized timing families

The first structured model should support:

* `on_play`
* `activated_main`
* `live_start`
* `live_success`
* `baton_touch`
* `auto_triggered_event`
* `static_always`

## 8. Choice Shapes

Effects must distinguish structured choice shapes from generic manual resolution.

Initial choice shapes should support:

* choose card(s) from a zone
* inspect top `N` cards, then select `M`
* choose a Heart color
* choose order
* choose count
* choose Energy instances
* optional accept or decline

Choice modeling must preserve:

* minimum and maximum selection count
* source zone
* target restrictions
* visibility rules
* selected and unselected card destinations when applicable

## 9. Visibility Model

The first structured model should support:

* `private`: only the controlling player inspects the information
* `reveal_to_owner`: cards are surfaced to the controlling player in a structured prompt
* `reveal_to_opponent`: selected or revealed cards must be visible to the opponent
* `public`: zone movement or game state is publicly visible

Visibility must be modeled explicitly for top-deck inspection, reveal, search, and conditional keep-to-hand effects.

## 10. Action Families

The first structured model should support at least:

* `draw_card`
* `inspect_top_cards`
* `reveal_cards`
* `select_to_hand_from_inspected`
* `move_remaining_cards`
* `discard_from_hand`
* `move_card`
* `ready_member`
* `apply_wait_member`
* `ready_energy`
* `apply_wait_energy`
* `pay_energy`
* `place_energy_from_deck`
* `attach_under_member`
* `deploy_from_attachment`
* `position_change`
* `choose_heart_color`
* `gain_blade`
* `gain_heart`
* `modify_score`
* `return_from_waiting_room`
* `reorder_deck_top`
* `move_card_top_or_bottom`

`draw_card` must not be used to represent top-deck inspection, reveal, filtered keep-to-hand, or reorder effects.

`pay_energy` must be distinct from choosing Energy cards to become Wait or Active because a cost-selection prompt has different validation and replay requirements from a later state adjustment.

`place_energy_from_deck` moves the deterministic top card of an Energy Deck into the Energy Area with an explicit `active` or `wait` orientation. It is distinct from Energy payment, changing the orientation of Energy already in the Energy Area, and drawing from the main deck. Effects using it must define the target player, amount, and destination orientation.

## 11. Duration Semantics

Modifier duration must be modeled explicitly.

Initial duration families:

* `live`
* `turn`
* `game`

Persistent modifiers must not rely on ambiguous free-text interpretation.

## 12. Source And Target Constraints

The first structured model should support explicit source and target constraints such as:

* member only
* energy only
* live only
* attached card only
* stage top member only

Generic zone-based targeting without card-type constraints is not enough for reliable replay-safe prompts.

## 13. Conceptual DSL Flow

Structured effects should follow:

```text
Trigger -> Condition -> Cost -> Choice -> Target -> Visibility -> Action -> Duration
```

Choices and targets must remain compatible with legal action generation, replay, and future online authoritative validation.

## 14. Deck Analyzer Policy

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

## 15. Battle Simulator Policy

Battle Simulator may use:

* numeric card data
* basic rule engine behavior
* structured prompts for supported effects
* manual completion for unresolved semantic steps

For `manual_resolution` effects, the simulator should:

1. detect the effect through the Rule Engine trigger boundary
2. display the raw Japanese effect text
3. pause automatic resolution
4. request structured manual completion
5. record the result as one or more replay-safe Actions
6. allow the game to continue

Manual resolution must not mutate GameState directly.

`ManualAdjustmentAction` fields and adjustment entry fields are owned by [005-action-system.spec.md](005-action-system.spec.md).

For AI vs AI debug mode, default policy for `manual_resolution` effects is `skip_and_log`.

Under `skip_and_log`, the semantic effect is skipped with explicit log annotation, and play continues only through legal Actions.

Approximation by `effect_tags` is allowed only in explicit experimental mode. Silent auto-resolution is forbidden.

## 16. LLM-Assisted Parsing Policy

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

## 17. Review Workflow

The effect review workflow is intentionally lightweight but must distinguish parser output, contributor proposals, human review, rules-sensitive review, and release approval.

Initial roles:

* `parser`: automated parser, script, or LLM-assisted process that creates initial effect tags or Effect DSL drafts.
* `contributor`: human contributor who proposes corrections or manual effect mappings.
* `reviewer`: human reviewer who checks that Effect DSL matches official card text.
* `rules_reviewer`: human reviewer who checks timing, rule interpretation, and comprehensive-rules-sensitive behavior.
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
* trigger and timing mapping are correct
* cost, choice, target, visibility, and actions match official meaning
* executable behavior follows the Rule Engine
* replay and deterministic behavior are preserved

Authority rules:

* `fully_executable` means the effect can technically execute.
* `test_validated_executable` means the effect passes automated rule tests.
* `reviewed_executable` requires human review.
* Automated rule-test validation alone cannot promote an effect to `reviewed_executable`.
* Effects involving complex timing, replacement effects, continuous effects, opponent choice, or comprehensive-rules-sensitive behavior require `rules_reviewer` review before `reviewed_executable`.
* `maintainer` approval is required for public release or an official recommended executable card pool.

## 18. Anti-Patterns

Avoid:

* treating all effects as raw text only
* hard-coding card effects by `card_code` or printing `card_id` inside the game engine
* binding effect interpretations directly to Card Printing instead of Card Text Revision
* letting UI detect or trigger effects authoritatively
* letting UI directly implement card effect logic
* letting AI bypass rule validation
* assuming LLM-parsed effects are authoritative
* using `ManualAdjustmentAction` as a generic replacement for structured choice or target modeling
* blocking simulator MVP until every effect is fully executable
* making Deck Analyzer depend on full effect execution
* making GameState impossible to serialize
* making effect parsing impossible to audit or re-run

## 19. Dependencies

Depends on:

* [005-action-system.spec.md](005-action-system.spec.md)
* [008-randomness-and-replay.spec.md](008-randomness-and-replay.spec.md)
* [016-terminology-normalization.spec.md](016-terminology-normalization.spec.md)
* [017-public-release-and-export-policy.spec.md](017-public-release-and-export-policy.spec.md)
