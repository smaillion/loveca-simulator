# Roadmap Expanded

## 1. Purpose

This document provides a detailed long-term roadmap for the platform.

It expands [05-development-roadmap.md](05-development-roadmap.md) with goals, deliverables, risks, dependencies, and exit criteria for each phase.

## 2. Phase 0: Research and Documentation

### Goal

Establish shared understanding before specification and coding.

### Deliverables

* project vision
* source policy
* domain glossary
* data model notes
* rule model notes
* architecture overview
* expanded roadmap
* AI and simulation notes
* replay and online readiness notes

### Risks

* misunderstanding official rules
* premature implementation
* unclear terminology
* analyzer and simulator divergence

### Dependencies

* official Japanese source availability
* project goals and MVP boundaries

### Exit Criteria

* all foundational architecture documents exist
* Deck Analyzer and Battle Simulator are documented as equal first-class products
* MVP and future features are clearly separated
* source and copyright policy is documented

## 3. Phase 1: Card Database Foundation

### Goal

Build reliable local card data infrastructure.

### Deliverables

* future database schema specification
* import pipeline specification
* source tracking design
* card validation design
* canonical Japanese data handling
* public release data boundary

### Risks

* official site format changes
* copyright concerns
* incomplete data normalization
* loss of source traceability

### Dependencies

* source policy
* data model notes
* domain glossary

### Exit Criteria

* card data concepts and import ownership are specified
* validation requirements are specified
* local use and public release boundaries are understood
* future implementation can begin without inventing source policy in code

## 4. Phase 2: Deck Analyzer MVP

### Goal

Build the first useful deck analysis feature.

### Deliverables

* deck import design
* deck legality validation
* card type ratio analysis
* cost curve analysis
* Heart distribution analysis
* Live card count analysis
* key-card probability analysis

### Risks

* incomplete legality rules
* incorrect probability assumptions
* insufficient card metadata
* analyzer logic diverging from simulator validation

### Dependencies

* card database foundation
* rule validation concepts
* deck construction rules

### Exit Criteria

* MVP deck analysis can evaluate a deck without UI dependency
* legality validation is shared or aligned with the rule engine design
* probability assumptions are documented

## 5. Phase 3: Game Engine Foundation

### Goal

Build the core engine model before UI.

### Deliverables

* GameState specification
* PlayerState specification
* zone model specification
* turn flow specification
* action system specification
* event system specification
* deterministic randomness model

### Risks

* GameState not serializable
* actions not replayable
* rules mixed with UI
* insufficient legal action generation

### Dependencies

* rule model notes
* architecture overview
* source policy

### Exit Criteria

* core match state concepts are serializable in design
* all state changes are represented as actions in design
* legal action generation is part of the engine architecture
* randomness strategy is documented

## 6. Phase 4: Simulator MVP

### Goal

Build a playable local simulator.

### Deliverables

* Human vs Human local play
* Human vs Simple AI
* AI vs AI debug runner
* opening hand and mulligan flow
* Member play
* Live play
* Energy payment
* basic Live success resolution
* victory detection
* action logs

### Risks

* AI bypassing rules
* manual effect handling causing ambiguity
* incomplete action validation
* unsupported effects confusing users

### Dependencies

* game engine foundation
* legal action generation
* Simple AI policy
* deck validation

### Exit Criteria

* a local match can be completed under MVP rules
* Simple AI can make legal, deterministic, explainable choices
* AI vs AI debug mode produces action logs and final summaries
* unsupported effect behavior is clearly bounded

## 7. Phase 5: Effect DSL

### Goal

Introduce structured card effect modeling.

### Deliverables

* trigger model
* condition model
* action model
* effect schema specification
* manual effect tagging workflow
* review process for structured effects
* simulation support status taxonomy

### Risks

* effect language too rigid
* too much manual data entry
* rule edge cases
* hard-coded card behavior creeping into engine logic
* tag-only effects being treated as executable

### Dependencies

* raw Japanese effect text storage
* event model
* action model
* manual review workflow
* effect modeling and taxonomy documentation

### Exit Criteria

* raw text and structured effects remain separate
* effect representation can describe simple common effects
* unsupported effects can be marked without breaking simulation
* analyzer and simulator can distinguish tag-only, manual, executable, and reviewed effects

## 8. Phase 6: Rule Expansion

### Goal

Gradually support more official rules and card effects.

### Deliverables

* broader official rule coverage
* card effect execution expansion
* FAQ and ruling integration
* regression test suite
* rule-version-aware behavior
* reviewed executable effect coverage

### Risks

* edge cases
* rule updates
* inconsistent card wording
* replay compatibility across rule versions

### Dependencies

* effect DSL
* rule version tracking
* source policy
* replay-ready action model

### Exit Criteria

* common gameplay cases are automated
* rule assumptions are traceable to official sources
* known rulings and errata can be represented

## 9. Phase 7: Simple UI

### Goal

Provide accessible visual gameplay and deck analysis UI.

### Deliverables

* deck list UI
* card search UI
* analyzer dashboard
* battlefield and zone UI
* match controls
* replay controls preparation

### Risks

* UI coupled with engine
* state synchronization issues
* UI masking unsupported rules
* analyzer and simulator UX diverging from shared model

### Dependencies

* stable analyzer workflows
* stable engine actions
* serializable GameState
* clear unsupported-effect handling

### Exit Criteria

* UI consumes engine and analyzer capabilities without owning rule logic
* match state can be displayed from serializable state
* user actions are routed through legal action choices

## 10. Phase 8: Advanced AI

### Goal

Improve AI strength and simulation value.

### Deliverables

* stronger heuristic AI
* Monte Carlo AI exploration
* matchup simulation
* AI policy comparison
* explainable decision logs

### Risks

* performance
* poor evaluation heuristics
* hidden randomness
* AI relying on invalid shortcuts

### Dependencies

* legal action system
* deterministic randomness
* replayable simulator
* baseline Simple AI

### Exit Criteria

* AI policies are comparable in debug runs
* decisions remain legal and explainable
* seeded simulations are reproducible

## 11. Phase 9: Online Multiplayer Preparation

### Goal

Prepare the engine and protocol concepts for online play.

### Deliverables

* client/server architecture design
* serialization protocol specification
* authoritative server model
* match synchronization design
* anti-cheat considerations
* spectator mode preparation
* replay sharing preparation

### Risks

* engine not server-compatible
* replay and online sync divergence
* latency problems
* insufficient validation boundary

### Dependencies

* serializable GameState
* serializable Action
* deterministic random seed
* action validation
* replay model

### Exit Criteria

* server-authoritative assumptions are documented
* client state and server state are separated conceptually
* action validation remains server-compatible
* replay and online synchronization use compatible concepts

## 12. Phase 10: Online Multiplayer

### Goal

Support actual online play.

### Deliverables

* accounts
* matchmaking
* private rooms
* online matches
* spectator mode
* replay sharing
* tournament support

### Risks

* infrastructure cost
* security
* abuse prevention
* operational complexity
* live rules disputes

### Dependencies

* online multiplayer preparation
* authoritative server implementation
* security and operations design
* stable rule engine

### Exit Criteria

* online matches can be completed through authoritative validation
* clients do not own trusted match state
* replays can be generated from online matches
* operational risks are actively managed
