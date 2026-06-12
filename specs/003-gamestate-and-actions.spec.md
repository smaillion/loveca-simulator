# 003 GameState and Actions Specification

## 1. Purpose

This spec defines conceptual requirements for serializable GameState and replay-safe Actions.

It does not define implementation code, APIs, database schema, network protocol, or class structure.

## 2. GameState Requirements

GameState represents the authoritative state of a match at a point in time.

GameState must be:

* serializable
* replay-compatible
* UI-independent
* controller-independent
* rule-version-aware
* suitable for future authoritative server use

## 3. Conceptual GameState Contents

GameState should conceptually contain:

* match identifier
* rule version
* players
* player states
* current turn
* current phase
* zones
* card instances
* resources
* successful Live progress
* pending choices or manual-resolution context when needed
* deterministic random seed context when needed
* action log reference or replay context

These are conceptual requirements, not an implementation schema.

## 4. Action Requirements

All state changes must be represented by Actions.

Actions must be:

* serializable
* replayable
* validated before resolution
* resolved through ActionResolver behavior
* logged in action order
* compatible with deterministic replay

## 5. Action Ownership

General Action safety and `ManualAdjustmentAction` fields are owned by [005-action-system.spec.md](005-action-system.spec.md).

This spec owns the higher-level requirement that GameState transitions are Action-based and replay-safe.

## 6. UI Boundary

UI may display GameState and request Actions.

UI must not directly mutate GameState or implement authoritative rule behavior.

## 7. AI Boundary

AI may inspect legal action options and choose an Action.

AI must not directly mutate GameState or bypass Rule Engine validation.

## 8. Replay Boundary

Replay reproduction should be possible from:

* initial GameState
* deterministic random seed context
* ordered Actions
* rule version
* relevant source data versions

Replay requirements are further specified by [008-randomness-and-replay.spec.md](008-randomness-and-replay.spec.md).

## 9. Online Readiness

Future online clients should submit intended Actions to an authoritative server.

The server should own authoritative GameState, validate Actions, resolve state transitions, and emit state updates or events.

## 10. Dependencies

Depends on:

* [005-action-system.spec.md](005-action-system.spec.md)
* [008-randomness-and-replay.spec.md](008-randomness-and-replay.spec.md)

Informs:

* [002-rule-engine.spec.md](002-rule-engine.spec.md)
* [010-simple-ai.spec.md](010-simple-ai.spec.md)
* [011-simulator-mvp.spec.md](011-simulator-mvp.spec.md)
* [012-controller-and-legal-actions.spec.md](012-controller-and-legal-actions.spec.md)

