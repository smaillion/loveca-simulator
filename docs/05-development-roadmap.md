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

## Current Roadmap Status

The roadmap is no longer treated as a strictly linear implementation sequence.

The project now advances through a main phase plus parallel product tracks:

* Phase 1 Card Database is substantially complete and is now in maintenance, formal importer, and incremental update work.
* Phase 2 Deck Analyzer MVP is implemented. Probability analysis and deeper deck advice are deferred.
* Phase 3 Game Engine Foundation is implemented for local, replayable rules validation.
* Phase 4 Simulator MVP has exceeded the original Human-vs-Human target through the visual rule validator. Simple AI and AI-vs-AI are intentionally deferred.
* Phase 5 Effect DSL and structured effect execution is the current primary development focus.
* Phase 6 Rule Expansion has not started as a broad phase.
* Phase 7 Simple UI has been pulled forward to support human rule validation and Deck Builder workflows.
* Phase 8 Advanced AI is now the lowest-priority major phase and should not block online testing.
* Phase 9 and Phase 10 should begin earlier as a parallel adoption and feedback track, starting with a low-cost hosted FastAPI online MVP before any local-engine browser rewrite.

This is a planned adjustment, not a project direction change. The current priority is to stabilize effect trigger detection, structured prompts, replay-safe effect resolution, and early online feedback loops before returning to AI, Monte Carlo, or win-rate work.

Parallel infrastructure track:

* local card databases remain user-local
* initialization should prioritize a local importer that builds card data and cache from official sources on the user's machine
* future setup may support versioned bootstrap asset packages for app-owned metadata, manifests, checksums, and redistribution-approved artifacts
* CDN/static packaging must stay inside the source and public-release policy; copyright-sensitive official assets require redistribution review
* short-term hosted online work must not become a card data, image, account, or deck storage service
* medium-term protocol work should standardize ActionEnvelope, compatibility fingerprints, and replay export
* long-term browser engine work remains a cost-reduction and pure-static-play direction after rules stabilize
* incremental local updates and backward compatibility are required so users can keep testing online while the rule engine evolves

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
* local bootstrap asset package design
* CDN/static distribution boundary for app-owned assets, manifests, and optional local cache artifacts

Dependencies:

* source policy
* domain glossary
* data model notes

Key risks:

* official site format changes
* copyright concerns
* incomplete normalization
* loss of source traceability
* accidentally treating local-use official assets as public redistributable data

## 4. Phase 2: Deck Analyzer MVP

Goal: Build the first useful deck analysis feature.

Primary deliverables:

* deck import design
* deck legality validation
* card type ratio analysis
* cost curve analysis
* Heart distribution analysis
* Live card count analysis
* key-card access probability, deferred until the simulator and effect prompt boundaries are stable

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
* Human vs Simple AI, deferred until effect prompts are stable
* AI vs AI debug runner, deferred until Simple AI is restored
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

Current subphases:

* Phase 5A: effect semantics audit
* Phase 5B: structured prompt MVP
* Phase 5C: common effect pattern coverage
* Phase 5D: reviewed executable effect pool

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

Status: This phase has been pulled forward. The React/FastAPI UI is already used as the main human rule validator and Deck Builder surface while Phase 5 effect work continues.

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

Status: Lowest priority among major phases. AI work should resume only after online human testing, compatibility, and structured effect prompts are stable enough to provide better training and validation data.

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
* mature online/human feedback loop

Key risks:

* performance
* poor evaluation heuristics
* hidden randomness
* AI depending on invalid shortcuts
* spending effort on simulated play before enough human rule-validation feedback exists

## 11. Phase 9: Online Multiplayer Preparation

Goal: Prepare the engine and protocol concepts for online play as an early parallel adoption track. The first target is low-cost local-engine network testing, not authoritative competitive play.

Primary deliverables:

* client/server architecture design
* serialization protocol specification
* low-cost local-engine online battle plan
* lightweight relay protocol concept
* compatibility handshake and state hash design
* divergence report format
* local importer/update compatibility requirements
* backward-compatible protocol and replay versioning plan
* tester onboarding and local setup guidance
* authoritative server model
* match synchronization design
* anti-cheat considerations
* spectator and replay-sharing preparation

Dependencies:

* serializable GameState
* serializable actions
* action validation
* deterministic replay
* stable effect registry snapshotting
* local card database importer and incremental update flow
* versioned compatibility fingerprints

Key risks:

* engine not server-compatible
* replay and online sync divergence
* latency problems
* insufficient validation boundary
* testers mistaking low-cost synchronized local-engine play for competitive authoritative play
* breaking older local data or replays during rapid rule-engine iteration

## 12. Phase 10: Online Multiplayer

Goal: Support actual online play early enough to attract testers and generate rule-engine feedback. The first practical target is private-room synchronized local-engine play; public competitive play remains out of scope until much later.

Primary deliverables:

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

Dependencies:

* online preparation phase
* security design
* operational infrastructure
* low-cost relay implementation for early testing
* local importer and updater stability
* backward-compatible protocol and state hashing
* authoritative server implementation for competitive/public play

Key risks:

* infrastructure cost
* security
* abuse prevention
* operational complexity
* rules disputes in live service context
