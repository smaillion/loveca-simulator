# Architecture Overview

## 1. Purpose

This document describes the complete platform architecture at a conceptual level.

It avoids implementation details, database schemas, API definitions, and class designs. It defines responsibilities, dependency direction, and shared components so future specifications can be written consistently.

The architecture must support two first-class products:

* Deck Analyzer
* Battle Simulator

Both products share core platform layers.

## 2. Architecture Principles

* Use layered architecture.
* Keep official source data independent from simulator and UI.
* Keep domain concepts reusable across analyzer, simulator, AI, replay, and future online play.
* Keep rule validation centralized.
* Keep GameState and actions serializable.
* Keep randomness deterministic when seeded.
* Keep UI and controller choices outside core rule resolution.
* Keep Japanese official text as the canonical source language.
* Keep raw effect text, effect tags, structured DSL, and executable effect behavior separate.
* Require explicit simulation support status before simulator automation.
* Treat LLM-assisted effect parsing as draft data until validated and reviewed.
* Use terminology normalization specs for official Japanese terms, internal enum names, display names, and aliases.
* Treat public-release export policy as a standalone ownership area.

## 3. Layer 1: Data Layer

### Responsibilities

The Data Layer owns source-backed and locally persisted information.

Responsible for:

* Gameplay Card metadata
* Card Printing metadata
* Card Set metadata
* Japanese raw official card text
* Card Text Revision history
* normalized card data
* card image references
* import logs
* source tracking
* version tracking
* rule source references
* local user deck records when applicable

### Dependencies

The Data Layer should not depend on:

* simulator behavior
* UI behavior
* AI policy
* online server behavior

Higher layers may read from the Data Layer through clearly defined application services or future specifications.

## 4. Layer 2: Domain Layer

### Responsibilities

The Domain Layer owns shared business concepts.

Responsible for:

* Card
* Gameplay Card
* Card Printing
* CardInstance
* Deck
* Player
* Zone
* GameState
* Action
* Event
* Trigger
* Effect
* Effect Tag
* Simulation Support Status
* Rule Version

The Domain Layer should express the vocabulary of the game and platform without deciding presentation behavior.

### Dependencies

The Domain Layer may depend on conceptual data from the Data Layer, but should not depend on:

* Deck Analyzer calculations
* Battle Simulator runners
* UI framework state
* online account systems

## 5. Layer 3: Rule Engine

### Responsibilities

The Rule Engine owns validation and state transition rules.

Responsible for:

* deck legality validation
* action validation
* legal action generation
* turn flow
* phase transitions
* zone movement
* Live resolution
* victory condition
* event dispatch
* trigger processing
* state invariant validation

### Dependencies

The Rule Engine depends on the Domain Layer and rule data. It should not depend on:

* UI controls
* AI shortcuts
* deck analyzer report formatting
* local-only assumptions that would prevent future server use

The Rule Engine must be reusable by Deck Analyzer, Battle Simulator, AI, and future online server workflows.

The Rule Engine, GameState and Actions, Action System, and Controller and Legal Actions specs together define the implementation-facing boundaries for validation, state transitions, and controller choice.

## 6. Layer 4A: Deck Analyzer

### Responsibilities

The Deck Analyzer owns analytical reports and probability-oriented views of decks.

Responsible for:

* deck legality report
* card type ratio
* cost curve
* Heart distribution
* Live requirement coverage
* key-card access probability
* hypergeometric analysis
* Monte Carlo draw analysis
* consistency scoring
* future weakness detection
* future improvement suggestions

The Deck Analyzer may use effect tags for MVP analysis and heuristics. It must not depend on every effect being fully executable.

### Dependencies

The Deck Analyzer depends on:

* Data Layer for card data
* Domain Layer for deck concepts
* Rule Engine for legality and validation
* shared randomness model for simulations

The Deck Analyzer must not depend on:

* UI framework logic
* Battle Simulator runner internals
* AI policy internals

## 7. Layer 4B: Battle Simulator

### Responsibilities

The Battle Simulator owns playable and automated match execution.

Responsible for:

* match setup
* turn progression
* human actions
* AI actions
* legal action generation usage
* action resolution usage
* victory detection
* action logs
* replay preparation
* AI vs AI debug mode

The Battle Simulator may use manual resolution and limited auto-executable effects in the MVP. It must check simulation support status before resolving semantic effects automatically.

### Dependencies

The Battle Simulator depends on:

* Data Layer for deck and card data
* Domain Layer for match and state concepts
* Rule Engine for validation and resolution
* shared randomness model
* controller abstractions

The Battle Simulator must not depend on:

* frontend framework state
* online account systems
* analyzer report formatting

## 8. Layer 5: Presentation and Future Extensions

### Responsibilities

Layer 5 contains user-facing and future platform capabilities.

Responsible for:

* simple UI
* replay viewer
* advanced AI
* online multiplayer
* tournament tools
* analytics dashboard
* spectator experience

### Dependencies

Layer 5 depends on lower layers. Lower layers should not depend on Layer 5.

This allows the same core engine to support CLI mode, local UI mode, AI simulation mode, and future server-authoritative online mode.

## 9. Shared Components

Shared components should include:

* card data access
* deck validation
* action validation
* legal action generation
* rule version handling
* effect model
* effect support status
* deterministic randomness
* action logging
* GameState serialization concept
* ManualAdjustmentAction concept
* replay-friendly event records

`ManualAdjustmentAction` is a structured container action, not a note-only log. Its field ownership belongs to the Action System specification.

These components should be designed once and reused rather than duplicated separately for analyzer and simulator.

## 10. Dependency Direction

Dependency direction should flow upward:

* Data Layer supports Domain Layer.
* Domain Layer supports Rule Engine.
* Rule Engine supports Deck Analyzer and Battle Simulator.
* Deck Analyzer and Battle Simulator support Presentation and Future Extensions.

Lower layers should not import, depend on, or assume higher-layer behavior.

## 11. Anti-Patterns to Avoid

Avoid:

* Deck Analyzer implementing its own legality rules separately from the Rule Engine
* Battle Simulator mutating GameState outside validated actions
* AI choosing actions that bypass legal action generation
* UI storing the only authoritative match state
* hard-coding individual card effects directly into engine flow
* treating effect tags as executable behavior
* auto-resolving unreviewed semantic effects without support status
* treating LLM-parsed effects as authoritative
* mixing manual resolution prompts into the core rule engine
* representing manual resolution as note-only logs
* treating parser output as equivalent to reviewer or rules reviewer approval
* hiding randomness inside arbitrary helper behavior
* storing translations as replacements for Japanese official text
* designing local-only engine behavior that cannot later run on an authoritative server

## 12. How the Architecture Supports Deck Analysis

Deck analysis reads card and deck data, applies shared validation, and produces reports.

Because legality and rule interpretation are shared with the simulator, analysis results should remain aligned with actual playable behavior.

## 13. How the Architecture Supports the Simulator

The simulator uses the same card data, domain model, legal action system, rule validation, and deterministic randomness.

This makes playable matches, AI debug simulations, replay, and future online play part of the same architectural family rather than separate systems.

## 14. How the Architecture Supports AI

AI operates as a controller that chooses from legal actions generated by the engine.

This allows Simple AI, future advanced AI, and AI vs AI debug modes to share validation and action resolution with human play.

Controller behavior and LegalActionGenerator boundaries are owned by the Controller and Legal Actions specification.

## 15. How the Architecture Supports Replay

Replay readiness comes from serializable GameState, serializable actions, deterministic random seeds, and action logs.

The architecture should make replay a natural result of match execution, not an afterthought.

## 16. How the Architecture Supports Online Multiplayer

Future online multiplayer should use an authoritative server model.

The same core rule engine should validate actions on the server, while clients submit choices and display state. Early separation between engine, controller, UI, and state serialization reduces the risk of rewriting the simulator for online play.
