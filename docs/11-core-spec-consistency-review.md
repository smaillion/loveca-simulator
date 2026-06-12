# Core Spec Consistency Review

## Purpose

This document records the focused consistency review of the new core rule and controller specs before source-review planning begins.

It is a documentation review artifact only. It does not define implementation code, database schema, migrations, scraper behavior, or frontend behavior.

## Review Scope

Reviewed core specs:

* [002 Rule Engine](../specs/002-rule-engine.spec.md)
* [003 GameState and Actions](../specs/003-gamestate-and-actions.spec.md)
* [005 Action System](../specs/005-action-system.spec.md)
* [012 Controller and Legal Actions](../specs/012-controller-and-legal-actions.spec.md)

Related specs checked for alignment:

* [008 Randomness and Replay](../specs/008-randomness-and-replay.spec.md)
* [010 Simple AI](../specs/010-simple-ai.spec.md)
* [011 Simulator MVP](../specs/011-simulator-mvp.spec.md)
* [015 Effect Taxonomy](../specs/015-effect-taxonomy.spec.md)

## Executive Summary

The new core specs are consistent enough to proceed to official-source review.

No blocking contradictions were found across Rule Engine ownership, serializable GameState, Action-only mutation, LegalActionGenerator usage, UI isolation, replay readiness, manual adjustment actions, Simple AI boundaries, or future authoritative-server readiness.

Remaining issues are specification depth risks, not architecture conflicts.

## Findings

### Shared Validation

`002-rule-engine.spec.md` owns shared validation for Deck Analyzer, Battle Simulator, Simple AI, and future server-side play.

This supports a single conceptual source of rule truth and prevents Deck Analyzer legality checks from drifting away from simulator legality checks.

### Serializable GameState

`003-gamestate-and-actions.spec.md` requires GameState to be serializable, controller-independent, and UI-independent.

This remains consistent with replay, future online multiplayer, and AI controller boundaries.

### Action-Only Mutation

`005-action-system.spec.md` requires all GameState changes to go through serializable Actions resolved by ActionResolver behavior.

Manual resolution is also represented through structured `ManualAdjustmentAction` records rather than direct state edits.

### Controller Boundaries

`012-controller-and-legal-actions.spec.md` requires HumanController and SimpleAIController to choose from the same LegalActionGenerator output.

Controllers select Actions; they do not validate, resolve, or directly mutate GameState.

### Replay Readiness

The core specs preserve deterministic replay requirements by requiring ordered Action logs, serializable randomness context, and replay-safe manual adjustment actions.

### Online Readiness

The reviewed specs do not contradict future online multiplayer. They preserve the later ability for clients to submit intended Actions to an authoritative server that owns validation and resolution.

## Non-Blocking Follow-Up

`ManualAdjustmentAction.source`, `reason`, and `requires_confirmation` should eventually receive controlled value guidance.

This does not block terminology source review or MVP rule subset planning.

## Source-Review Gate

Source review may proceed with these assumptions:

* Japanese official terminology remains canonical.
* Deck Analyzer and Battle Simulator should share normalized terminology IDs from [016 Terminology Normalization](../specs/016-terminology-normalization.spec.md).
* MVP rule automation should wait for official-source confirmation of exact rule wording.
* Unsupported or ambiguous rules should be marked as out of MVP or requiring review.
