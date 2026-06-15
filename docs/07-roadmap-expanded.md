# Roadmap Expanded

## 1. Purpose

This document provides a detailed long-term roadmap for the platform.

It expands [05-development-roadmap.md](05-development-roadmap.md) with goals, deliverables, risks, dependencies, and exit criteria for each phase.

## Current Status And Roadmap Adjustment

The roadmap is now interpreted as a main-phase roadmap with parallel product tracks, not a strict linear sequence.

Current project status:

* Phase 1 Card Database is substantially complete and has moved into maintenance, formal importer, and incremental update workflows.
* Phase 2 Deck Analyzer MVP is implemented. Probability analysis and deeper deck advice are deferred.
* Phase 3 Game Engine Foundation is implemented for local replayable rules validation.
* Phase 4 Simulator MVP has exceeded the original local Human-vs-Human goal through the visual rule validator. Simple AI and AI-vs-AI are intentionally deferred.
* Phase 5 Effect DSL and structured effect execution is the active main phase.
* Phase 6 Rule Expansion has not started as a broad phase.
* Phase 7 Simple UI has been pulled forward to support human rule validation and Deck Builder workflows.
* Phase 8 Advanced AI is now the lowest-priority major phase.
* Phase 9 and Phase 10 should start earlier as a parallel adoption and feedback track, using low-cost local-engine online play before authoritative competitive infrastructure exists.

This adjustment preserves the original direction. It changes the planning model so the next work can focus on effect trigger detection, structured prompts, replay-safe resolution, and early online human feedback before returning to AI, Monte Carlo, or win-rate simulation.

Current Phase 5 subphases:

* Phase 5A: effect semantics audit
* Phase 5B: structured prompt MVP
* Phase 5C: common effect pattern coverage
* Phase 5D: reviewed executable effect pool

Parallel infrastructure track:

* card database, image cache, saved decks, replays, and user preferences remain local user data
* onboarding should prioritize a local importer that builds card data and cache from official sources on the user's machine
* future onboarding may support versioned bootstrap asset packages for application-owned artifacts, manifests, checksums, schemas, and redistribution-approved local cache artifacts
* copyright-sensitive official assets require source-policy review before public packaging
* online relay infrastructure must remain separate from asset distribution and must not become user-data storage
* incremental local updates and backward compatibility are required so testers can keep playing online while the engine evolves
* browser play should use the dual-engine strategy in [021 Browser Engine and Local-Rule Online](../specs/021-browser-engine-and-local-online.spec.md): Python remains the rule-development oracle, while TypeScript becomes the GitHub Pages and future low-cost online runtime

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
* local bootstrap asset package design
* static/CDN distribution boundary

### Risks

* official site format changes
* copyright concerns
* incomplete data normalization
* loss of source traceability
* public packaging accidentally redistributing local-use-only official assets

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
* key-card probability analysis, deferred until simulator and effect prompt assumptions are stable

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
* Human vs Simple AI, deferred until structured effect prompts are stable
* AI vs AI debug runner, deferred until Simple AI is restored
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
* Simple AI can make legal, deterministic, explainable choices, once AI work resumes
* AI vs AI debug mode produces action logs and final summaries, once AI work resumes
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
* Phase 5A effect semantics audit
* Phase 5B structured prompt MVP
* Phase 5C common effect pattern coverage
* Phase 5D reviewed executable effect pool

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
* current registry `test_validated_executable` effects appear as legal prompts in the UI when their trigger timing is reached
* structured Energy, inspection, reveal, selection, and ordering effects no longer depend on generic manual adjustment

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

### Current Status

This phase has been pulled forward. The React/FastAPI UI is already the primary human-facing surface for Deck Builder and local rule validation while Phase 5 effect work continues.

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

### Current Status

Lowest priority among major phases. AI should resume only after online human testing, compatibility handling, and structured effect prompts are stable enough to produce useful validation data.

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
* mature online/human feedback loop

### Exit Criteria

* AI policies are comparable in debug runs
* decisions remain legal and explainable
* seeded simulations are reproducible
* AI work no longer competes with the higher-priority online testing and rule-validation loop

## 11. Phase 9: Online Multiplayer Preparation

### Goal

Prepare the engine and protocol concepts for online play as an early parallel adoption track. The first target is low-cost local-engine network testing, while the later authoritative-server track remains documented but deferred.

### Deliverables

* client/server architecture design
* serialization protocol specification
* low-cost online battle architecture plan
* lightweight relay protocol concept
* compatibility handshake design
* canonical state hash and divergence report design
* local importer/update compatibility requirements
* backward-compatible protocol and replay versioning plan
* tester onboarding and local setup guidance
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
* unclear boundary between test-mode online play and future competitive online play

### Dependencies

* serializable GameState
* serializable Action
* deterministic random seed
* action validation
* replay model
* effect registry snapshot model
* local card database importer and incremental update flow
* versioned compatibility fingerprints

### Exit Criteria

* low-cost local-engine online testing assumptions are documented
* server-authoritative assumptions are documented
* client state and server state are separated conceptually
* action validation remains server-compatible
* replay and online synchronization use compatible concepts
* divergence reports can identify mismatched state hashes and compatibility fingerprints
* users can update local card data without relying on relay-side card storage

## 12. Phase 10: Online Multiplayer

### Goal

Support actual online play early enough to attract testers and generate rule-engine feedback. Early delivery should use private-room synchronized local-engine play; competitive public play remains dependent on later authoritative validation and is not the first target.

### Deliverables

* private rooms
* synchronized online test matches
* reconnect and divergence handling
* local setup and incremental update workflow for testers
* compatibility-gated match start
* feedback and replay bundle export
* accounts
* matchmaking
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
* low-cost relay implementation for early private rooms
* local importer and updater stability
* backward-compatible protocol and state hashing
* authoritative server implementation for competitive/public play
* security and operations design
* stable rule engine

### Exit Criteria

* low-cost private-room online matches can be completed with matching state hashes
* authoritative validation path remains documented for public competitive play
* replays can be generated from online matches
* operational risks are actively managed
* testers can keep local data current through importer/update workflows without online accounts
