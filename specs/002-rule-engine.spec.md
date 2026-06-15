# 002 Rule Engine Specification

## 1. Purpose

This spec defines conceptual responsibilities and boundaries for the shared Rule Engine.

It does not define implementation code, APIs, database schema, UI behavior, or full official rule coverage.

## 2. Scope

The Rule Engine must be shared by:

* Deck Analyzer
* Battle Simulator
* Simple AI
* future advanced AI
* future authoritative online server

Deck Analyzer and Battle Simulator must not implement separate incompatible legality or rule-validation logic.

## 3. Responsibilities

The Rule Engine owns:

* deck legality validation
* match setup validation
* action validation
* LegalActionGenerator rules
* turn and phase transition rules
* zone movement validation
* basic Live resolution rules
* victory condition checks
* state invariant validation
* effect execution boundaries
* effect trigger detection
* pending effect queue creation
* structured effect-choice validation
* rule-version-aware validation

## 4. MVP Rule Boundary

Simulator MVP should use a narrow rule subset:

* deck loading and validation assumptions
* opening hand and mulligan flow
* turn progression
* playing Members
* playing Lives
* paying Energy at a basic structural level
* basic Live success checks
* score and victory tracking
* manual or limited effect handling

Unsupported official rule details must be documented as assumptions and must not be silently treated as complete rule coverage.

## 5. Validation Boundary

The Rule Engine validates whether an Action is legal for:

* current GameState
* active player
* current turn
* current phase
* relevant zones
* available resources
* rule version
* effect support status when applicable
* effect execution mode when applicable

Invalid Actions must be rejected before resolution.

## 6. State Mutation Boundary

The Rule Engine must not allow direct GameState mutation by UI, AI, importer, analyzer, or controller code.

All GameState changes must go through serializable Actions and ActionResolver behavior as defined by:

* [003-gamestate-and-actions.spec.md](003-gamestate-and-actions.spec.md)
* [005-action-system.spec.md](005-action-system.spec.md)

## 7. Analyzer Relationship

Deck Analyzer may call Rule Engine validation for deck legality and rule assumptions.

Analyzer reports must distinguish:

* official validated facts
* rule-version-dependent findings
* heuristic analysis
* unsupported or uncertain effect assumptions

## 8. Simulator Relationship

Battle Simulator must use Rule Engine validation for legal action generation, action validation, phase progression, zone movement, Live resolution, and victory checks.

Simulator MVP may use manual resolution for unsupported effects, but manual resolution must still produce replay-safe Actions.

The Rule Engine is also responsible for determining when an effect is triggered and whether it should appear as:

* an automatic resolution
* a structured pending effect prompt
* a manual-resolution boundary

UI code must not authoritatively detect or enqueue effects on its own.

## 9. Online Readiness

The Rule Engine should be compatible with future authoritative server use.

Future clients may request Actions, but the authoritative server must validate and resolve Actions through the same conceptual Rule Engine boundary.

## 10. Dependencies

Depends on:

* [003-gamestate-and-actions.spec.md](003-gamestate-and-actions.spec.md)
* [005-action-system.spec.md](005-action-system.spec.md)
* [008-randomness-and-replay.spec.md](008-randomness-and-replay.spec.md)
* [015-effect-taxonomy.spec.md](015-effect-taxonomy.spec.md)

Informs:

* [001-deck-analyzer.spec.md](001-deck-analyzer.spec.md)
* [010-simple-ai.spec.md](010-simple-ai.spec.md)
* [011-simulator-mvp.spec.md](011-simulator-mvp.spec.md)
* [012-controller-and-legal-actions.spec.md](012-controller-and-legal-actions.spec.md)
