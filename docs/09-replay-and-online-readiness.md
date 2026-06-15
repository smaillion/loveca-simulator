# Replay and Online Readiness

## 1. Purpose

This document describes replay and online multiplayer readiness.

Replay and online multiplayer are not full MVP features, but the architecture must prepare for them from the beginning. Decisions made in the local simulator can make future replay and online play either straightforward or extremely expensive to retrofit.

## 2. Serializable GameState

GameState should be serializable in concept.

GameState serialization requirements are owned by the GameState and Actions specification. Replay and randomness requirements are owned by the Randomness and Replay specification.

The platform should support:

* GameState to portable representation
* portable representation back to GameState
* state snapshots for debugging
* state comparison for regression tests
* state transmission for future online synchronization

Serializable GameState supports:

* replay
* AI debugging
* Monte Carlo simulation
* bug reproduction
* future server-authoritative online play

## 3. Serializable Action

Actions should be serializable because all state changes should happen through actions.

Serializable actions support:

* action logs
* replay reproduction
* online client requests
* server-side validation
* regression test cases
* AI decision audit

Actions should represent player or system intent clearly enough to be validated against the GameState and rule version.

## 4. Deterministic Random Seed

All random operations should support deterministic seeds.

This includes:

* shuffle
* opening hand generation
* mulligan randomness if any
* AI random tie-breaks
* simulation runs
* future randomized effect behavior if applicable
* automatic effect resolution when supported

Randomness should be centralized and explicit. It should not be hidden inside arbitrary helper behavior.

## 5. Action Logs

Action logs should record the sequence of validated actions during a match.

Action logs should support:

* replay
* AI explanation
* debugging
* match summaries
* future spectator mode
* future online dispute review

AI decisions should include selection reasons where practical. Human decisions should be recorded as selected actions without requiring private user intent.

## 6. Replay Reproduction

Given the following, a match should be reproducible:

* initial GameState
* deck order or shuffle seed
* action log
* random seed
* rule version

The reproduced match should produce the same resulting GameState and relevant event sequence.

Replay support is useful before a replay viewer exists because it makes bugs and AI behavior easier to diagnose.

## 7. Event-Sourcing Approach

The architecture should be event-sourcing-friendly.

Actions represent requested or chosen state changes. Resolution produces new GameState and events. Events record facts that occurred.

This approach supports:

* trigger processing
* replay inspection
* UI updates
* debugging
* online synchronization
* audit trails

The project does not need a full event-sourcing infrastructure in the MVP, but it should avoid choices that make event-based replay impossible.

## 8. Local Mode vs Server Mode

The core game engine should be usable in:

* local mode
* CLI debug mode
* AI vs AI simulation mode
* future server mode

Local mode may allow a single process to own match state and controller input.

Server mode should assume the server owns authoritative state, validates actions, and sends state updates or events to clients.

The engine should not depend on local UI state.

## 9. Authoritative Server Concept

Future online multiplayer should prefer an authoritative server architecture.

In this model:

* the server owns official Match and GameState
* clients display state and submit desired actions
* the server validates actions
* the server resolves actions
* the server broadcasts results or state updates

This reduces cheating risk and keeps players synchronized.

## 9A. Low-Cost Local-Engine Online Track

Before a full authoritative server exists, the project may support a low-cost online testing mode where both players run the rule engine locally and a lightweight relay only forwards versioned protocol messages.

This mode is intended for human rules testing and feedback collection. It is not a competitive, anti-cheat, or ranked-play architecture.

The low-cost track still depends on the same replay-ready foundations:

* deterministic GameState serialization
* deterministic random seed handling
* serializable Actions
* revision checks
* canonical state hashes
* divergence reports

The detailed plan is owned by [16-low-cost-online-battle-plan.md](16-low-cost-online-battle-plan.md).

## 10. Client and Server Separation

Client state and server state should be conceptually separate.

Client state:

* display state
* selected UI elements
* pending local input
* animations
* optional predictions

Server state:

* authoritative GameState
* validated action log
* random seed context
* rule version
* match result

The core engine should align with server-state needs, not with UI-only state.

## 11. Spectator Mode Preparation

Spectator mode is a future feature, but replay-ready architecture helps prepare for it.

A spectator should eventually be able to receive state updates or event streams without controlling a player.

This requires:

* clear separation of controller input and state observation
* serializable state or events
* hidden-information policy
* action log integrity

## 12. Replay Sharing Preparation

Replay sharing should be based on reproducible match records, not video capture.

A future replay record may include:

* metadata
* rule version
* source data version references
* initial deck references
* random seed
* action log
* event summary
* final result

Public replay sharing may need to avoid redistributing copyrighted card text beyond what is acceptable under the source policy.

Replay records should preserve whether an effect was manually resolved, partially executable, fully executable, or reviewed executable at the time of the match. This helps explain simulator behavior when effect support improves later.

Manual effect resolution must produce structured `ManualAdjustmentAction` records. Note-only log annotations are not replay-safe. Manual resolution must not mutate GameState directly.

Manual adjustment records should contain structured adjustment entries such as card movement, draw, discard, Energy readiness/payment, Wait state, score, Heart, Blade, and flag changes. The exact fields are owned by the Action System specification.

## 13. Risks If Not Considered Early

If replay and online readiness are ignored early, the project risks:

* GameState that cannot be serialized
* actions that cannot be replayed
* randomness that cannot be reproduced
* AI behavior that cannot be debugged
* UI becoming the only owner of match state
* simulator logic that cannot run on a server
* online play requiring major engine rewrites
* inability to investigate rules bugs from match logs

Preparing for replay does not mean building online multiplayer in the MVP. It means keeping state, actions, events, and randomness clean enough that online play remains possible later.
