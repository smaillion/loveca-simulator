# 007 Effect DSL Specification

## 1. Purpose

This spec defines conceptual requirements for the future structured Effect DSL.

It does not define a final JSON schema, database schema, parser implementation, API, or executable engine.

## 2. Required Modeling Layers

The Effect DSL is the third layer in the required four-layer model:

1. `raw_effect_text`
2. `effect_tags`
3. structured Effect DSL
4. executable effect implementation

The DSL must remain traceable to raw Japanese official text.

Every DSL draft must identify `card_code`, `text_revision_id`, and `raw_text_hash`. A DSL draft must not bind directly to printing `card_id`.

## 3. DSL Shape

The DSL should follow:

```text
Trigger -> Condition -> Cost -> Choice -> Target -> Visibility -> Action -> Duration
```

This shape must support future validation, manual review, replay, and deterministic simulation.

The DSL describes structured effect meaning. It does not itself mutate GameState. Executable behavior must resolve through Rule Engine validation, LegalActionGenerator prompts, and Action boundaries.

## 4. Required Taxonomy

The DSL must align with [015-effect-taxonomy.spec.md](015-effect-taxonomy.spec.md), including:

* effect types
* trigger families
* timing types
* action families
* condition categories
* choice shapes
* visibility model
* source and target constraints
* effect instance conceptual fields
* support statuses
* execution modes

## 5. Required Prompt Boundary

The DSL must support the distinction between:

* effects that resolve automatically
* effects that require structured player choice
* effects that require manual completion after structured trigger detection

The DSL must therefore carry enough information for LegalActionGenerator to produce replay-safe prompts for:

* accept or decline
* target selection
* card selection
* Energy-instance selection
* count selection
* order selection
* color selection
* selection visibility and reveal requirements

A DSL draft that cannot express the necessary structured prompt boundary must not be promoted to `partially_executable`.

## 6. Review Requirements

Every DSL draft should record:

* parse confidence
* review status
* parser version
* raw text hash

LLM-assisted DSL drafts are untrusted until validated and reviewed.

## 7. Execution Boundary

DSL representation is not the same as executable implementation.

A DSL effect may be:

* non-executable
* manually resolved
* partially executable
* fully executable
* test validated executable
* reviewed executable

The simulator must check both `simulation_support` and `execution_mode` before automatic resolution.

`reviewed_executable` requires human review. Automated rule-test validation alone may support `test_validated_executable`, but it is not sufficient for reviewed status.

## 8. Dependencies

Depends on:

* [002-rule-engine.spec.md](002-rule-engine.spec.md)
* [003-gamestate-and-actions.spec.md](003-gamestate-and-actions.spec.md)
* [005-action-system.spec.md](005-action-system.spec.md)
* [008-randomness-and-replay.spec.md](008-randomness-and-replay.spec.md)
* [015-effect-taxonomy.spec.md](015-effect-taxonomy.spec.md)
* [016-terminology-normalization.spec.md](016-terminology-normalization.spec.md)
* [018-card-data-storage.spec.md](018-card-data-storage.spec.md)
