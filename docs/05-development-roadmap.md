# Development Roadmap

## 1. Purpose

This roadmap summarizes the long-term development path for the Love Live! Series Official Card Game Analysis & Simulation Platform.

The platform has two first-class tracks:

* Deck Analyzer
* Battle Simulator

Both tracks share foundational architecture:

* card database
* domain model
* rule model
* validation logic
* effect model
* randomness model
* replay-friendly action model

Detailed phase planning is maintained in [07-roadmap-expanded.md](07-roadmap-expanded.md).

## 2. Phase 0: Research and Documentation

Goal: Establish shared understanding before specification and coding.

Primary deliverables:

* project vision
* source policy
* domain glossary
* data model notes
* rule model notes
* architecture overview
* expanded roadmap
* AI and simulation notes
* replay and online readiness notes

Key risks:

* misunderstanding official rules
* premature implementation
* unclear terminology
* analyzer and simulator architectures diverging too early

## 3. Phase 1: Card Database Foundation

Goal: Build reliable local card data infrastructure.

Primary deliverables:

* conceptual data model refinement
* future database schema specification
* import pipeline design
* source tracking design
* card validation design
* Japanese canonical source-data handling

Dependencies:

* source policy
* domain glossary
* data model notes

Key risks:

* official site format changes
* copyright concerns
* incomplete normalization
* loss of source traceability

## 4. Phase 2: Deck Analyzer MVP

Goal: Build the first useful deck analysis feature.

Primary deliverables:

* deck import design
* deck legality validation
* card type ratio analysis
* cost curve analysis
* Heart distribution analysis
* Live card count analysis
* key-card access probability

Dependencies:

* card database foundation
* deck validation rules
* probability assumptions

Key risks:

* incomplete legality rules
* incorrect probability assumptions
* insufficient card metadata

## 5. Phase 3: Game Engine Foundation

Goal: Build the core rule engine model before UI.

Primary deliverables:

* GameState concept specification
* PlayerState concept specification
* zone model
* turn flow
* action system
* event system
* deterministic randomness model
* replay-ready action logging design

Dependencies:

* rule model notes
* domain glossary
* source policy

Key risks:

* GameState not serializable
* actions not replayable
* rules mixed with UI concerns
* randomness hidden in helper behavior

## 6. Phase 4: Simulator MVP

Goal: Build a playable local simulator.

Primary deliverables:

* Human vs Human local play
* Human vs Simple AI
* AI vs AI debug runner
* manual or limited effect handling
* action logs
* victory detection
* deterministic match reproduction preparation

Dependencies:

* game engine foundation
* legal action generation
* simple AI policy
* deck loading and validation

Key risks:

* AI bypassing rules
* manual effect handling causing ambiguity
* incomplete action validation
* unclear user responsibility for unsupported effects

## 7. Phase 5: Effect DSL

Goal: Introduce structured card effect modeling.

Primary deliverables:

* trigger model
* condition model
* action model
* effect schema specification
* manual effect tagging workflow
* review process for interpreted effects
* simulation support status taxonomy

Dependencies:

* Japanese raw effect text storage
* effect support status taxonomy
* rule engine foundation
* event model

Key risks:

* effect language too rigid
* too much manual data entry
* rule edge cases
* accidental hard-coding of individual cards
* treating tag-only effects as executable

## 8. Phase 6: Rule Expansion

Goal: Gradually support more official rules and card effects.

Primary deliverables:

* broader official rule coverage
* more card effect execution
* FAQ and ruling integration
* regression test suite
* rule-version-aware validation
* reviewed executable effect coverage

Dependencies:

* effect DSL
* rule version tracking
* source policy

Key risks:

* edge cases
* rule updates
* inconsistent card wording
* difficulty preserving old replay behavior

## 9. Phase 7: Simple UI

Goal: Provide accessible visual gameplay and deck analysis UI.

Primary deliverables:

* deck list UI
* card search UI
* deck analyzer dashboard
* battlefield and zone UI
* match controls
* replay controls preparation

Dependencies:

* stable analyzer workflows
* stable engine actions
* serializable state

Key risks:

* UI coupled with engine
* state synchronization issues
* UI masking unsupported rules

## 10. Phase 8: Advanced AI

Goal: Improve AI strength and simulation value.

Primary deliverables:

* stronger heuristic AI
* Monte Carlo AI exploration
* matchup simulation
* AI policy comparison
* explainable AI decision logs

Dependencies:

* legal action system
* deterministic randomness
* replayable simulator
* baseline Simple AI

Key risks:

* performance
* poor evaluation heuristics
* hidden randomness
* AI depending on invalid shortcuts

## 11. Phase 9: Online Multiplayer Preparation

Goal: Prepare the engine and protocol concepts for online play.

Primary deliverables:

* client/server architecture design
* serialization protocol specification
* authoritative server model
* match synchronization design
* anti-cheat considerations
* spectator and replay-sharing preparation

Dependencies:

* serializable GameState
* serializable actions
* action validation
* deterministic replay

Key risks:

* engine not server-compatible
* replay and online sync divergence
* latency problems
* insufficient validation boundary

## 12. Phase 10: Online Multiplayer

Goal: Support actual online play.

Primary deliverables:

* accounts
* matchmaking
* private rooms
* online matches
* spectator mode
* replay sharing
* tournament support

Dependencies:

* online preparation phase
* security design
* operational infrastructure
* authoritative server implementation

Key risks:

* infrastructure cost
* security
* abuse prevention
* operational complexity
* rules disputes in live service context
