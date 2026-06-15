# 012 Controller and Legal Actions Specification

## 1. Purpose

This spec defines conceptual requirements for PlayerController behavior and legal action generation.

It does not define implementation code, UI behavior, network protocol, APIs, or AI algorithms.

## 2. Controller Model

Controllers choose Actions. Controllers do not validate or resolve Actions.

Initial controller concepts:

* HumanController
* SimpleAIController
* FutureAIController

All controllers must use the same LegalActionGenerator boundary.

## 3. LegalActionGenerator

LegalActionGenerator produces legal Actions for:

* current GameState
* active player
* current turn
* current phase
* rule version
* relevant zones and resources
* effect support status when applicable
* effect execution mode when applicable

LegalActionGenerator is part of the Rule Engine boundary.

## 4. HumanController Requirements

HumanController may receive a choice from CLI, local UI, or future online client flow.

HumanController must:

* choose from legal Actions
* avoid direct GameState mutation
* submit selected Actions for validation and resolution
* use ManualAdjustmentAction for manual resolution results
* use structured effect-resolution prompts when the Rule Engine exposes them

## 5. SimpleAIController Requirements

SimpleAIController must:

* choose from legal Actions
* avoid direct GameState mutation
* avoid bypassing Rule Engine validation
* be deterministic when seed context is fixed
* log selected Action and reason
* follow manual-effect policy defined by [010-simple-ai.spec.md](010-simple-ai.spec.md)

## 6. UI Boundary

UI may present legal Actions and collect user choices.

UI must not:

* directly mutate GameState
* create unvalidated state changes
* authoritatively decide when an effect is triggered
* implement card effect logic as authoritative behavior
* bypass ActionResolver

## 7. Online Boundary

Future online clients should submit selected Actions to an authoritative server.

Clients may present legal choices, but server validation remains authoritative.

## 8. Dependencies

Depends on:

* [002-rule-engine.spec.md](002-rule-engine.spec.md)
* [003-gamestate-and-actions.spec.md](003-gamestate-and-actions.spec.md)
* [005-action-system.spec.md](005-action-system.spec.md)
* [008-randomness-and-replay.spec.md](008-randomness-and-replay.spec.md)

Informs:

* [010-simple-ai.spec.md](010-simple-ai.spec.md)
* [011-simulator-mvp.spec.md](011-simulator-mvp.spec.md)
