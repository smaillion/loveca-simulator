# 021 Browser Engine and Local-Rule Online Specification

## 1. Purpose

This specification defines the long-term browser-side rule engine strategy and the local-rule online architecture.

The goal is to preserve a path toward pure browser play and low-cost local-rule online after the rules stabilize. It is not a blocker for the current GitHub Pages preview, and it is not the short-term online MVP.

Short-term online play should use hosted FastAPI with the existing Python engine. The browser engine is a later cost-reduction and offline/static-play track.

This specification does not define a production relay server, account system, matchmaking system, anti-cheat model, or authoritative competitive server.

## 2. Core Decision

The long-term project strategy uses a dual-engine model:

* Python engine: reference implementation, rule exploration environment, sandbox runner, importer-adjacent validation, pytest oracle.
* TypeScript browser engine: browser runtime for GitHub Pages, local browser play, future low-cost online play, and user-facing preview builds.

The TypeScript browser engine should not fork game rules conceptually. It must implement the same serialized GameState, Action, Event, LegalAction, deterministic randomness, and replay boundaries defined by the existing core specs.

Python remains the primary development and hosted-online engine until the TypeScript engine has enough parity to replace it for browser-only play.

## 3. Non-Goals

The first browser engine MVP does not include:

* full effect automation
* Simple AI
* AI-vs-AI
* Monte Carlo or win-rate simulation
* online relay implementation
* account or cloud deck storage
* server-side authoritative rule validation
* cheat resistance beyond local consistency checks
* full parity with every Python-only debug helper

Unsupported effects may remain manual or skippable in debug mode, but they must be represented by explicit replay-safe Actions or explicit debug skip Events.

## 4. Shared Contract

The Python and TypeScript engines must share these conceptual contracts:

* DeckList format: `decklist.v0`
* Action boundary: all state changes are Actions
* LegalActionGenerator boundary: UI only renders legal actions supplied by the engine
* GameState serialization model
* deterministic random seed model
* Action log and Event log model
* replay export shape
* card database fingerprint
* effect registry hash
* rule version
* app/protocol version

The browser engine may use TypeScript-native data structures internally, but its exported state and replay artifacts must remain compatible with the project-level serialized model.

## 5. Long-Term Browser Engine MVP Scope

The first browser engine MVP, when scheduled, should cover one complete local two-player match without a backend.

Required rules:

* create a match from two inline DeckList payloads
* deterministic deck shuffling from seed
* opening hand draw
* mulligan
* initial Energy setup
* turn order and phase progression
* Active Phase
* Energy Phase
* Draw Phase
* Main Phase
* Member play into empty slots
* Baton Touch only if the current TypeScript rule slice has the needed cost and replacement logic; otherwise explicitly defer it
* Live Set
* Live reveal
* Yell by active Member Blade count
* Heart allocation, including `heart0`
* Live score comparison
* Success Live movement
* next-turn first-player selection
* victory at three successful Lives
* draw and Yell deck refresh from Waiting Room
* replay export

Minimum state zones:

* main deck
* Energy Deck
* hand
* member area
* member-area attachments if the UI can already display them; otherwise defer automatic rules and preserve empty defaults
* Energy Area
* Live Area
* Waiting Room
* Resolution Area
* Success Live Area

The first MVP may intentionally omit structured executable effects. If omitted, effect triggers must still be visible as unsupported/manual prompts where the existing preview data can identify them.

## 6. Browser Runtime Services

The browser build should expose the same UI-facing API shape currently used by `web/src/api.ts`.

Browser runtime modules:

* `BrowserCatalogStore`
  * reads static parsed card data from `preview-data`
  * applies catalog filters locally
* `BrowserDeckLibrary`
  * stores decks in browser storage
  * imports and exports deck JSON
  * runs MVP deck analysis locally
* `BrowserMatchRuntime`
  * creates matches from local deck data
  * applies Actions through the TypeScript engine
  * stores match snapshots, Actions, Events, and replay metadata locally
* `BrowserAssetResolver`
  * uses official image URLs from parsed card data
  * does not require bundled official card images
* `CompatibilityFingerprint`
  * calculates local data and engine compatibility metadata

Persistent browser storage should use IndexedDB once match history and replay logs become non-trivial. LocalStorage is acceptable only for small preview data such as UI preferences and small deck records.

## 7. Cross-Engine Fixtures

The project should introduce replay fixtures that can be run against both engines.

Each fixture should contain:

* fixture id
* rule version
* card database fingerprint
* effect registry hash
* player decks
* seed
* ordered Action sequence
* expected final state hash
* expected key state assertions
* optional expected Event sequence fragments

The first fixture set should focus on low-effect rules:

* setup and mulligan
* empty-slot Member play
* Live Set and replacement draw
* Yell with normal Blade
* all-color Heart allocation
* single-player successful Live
* simultaneous successful Live
* next-turn first-player selection
* deck refresh during draw
* deck refresh during Yell

Python should generate or verify the reference expected results. TypeScript must match the same key assertions before browser play is treated as supported.

## 8. State Hashing

Canonical state hashing is required for browser engine parity and future online play.

Hash input must include deterministic public state relevant to replay:

* rule version
* phase
* turn number
* first and second player ids
* pending choices
* pending effects
* player zones in order
* card instance ownership, identity, orientation, face-up state, and card definition references
* live result summaries
* game result

Hash input must exclude volatile UI state:

* selected tab
* dialog visibility
* scroll position
* localized labels
* local image loading status

Private information is not protected in the first local-rule online mode. This project phase prioritizes rule testing over hidden-information enforcement.

## 9. ActionEnvelope

Future online play should transport Actions through a versioned ActionEnvelope.

Minimum fields:

* `protocol_version`
* `message_id`
* `match_id`
* `sender_player_id`
* `action`
* `expected_revision`
* `pre_state_hash`
* `post_state_hash`, after local application
* `compatibility_fingerprint`
* `sent_at`

The relay should forward envelopes. It should not validate action legality.

The receiving client must:

* compare compatibility metadata
* compare `expected_revision`
* compare `pre_state_hash`
* validate the Action through the local engine
* apply the Action
* compare the resulting `post_state_hash`
* record divergence when hashes differ

## 10. Compatibility Fingerprint

The compatibility fingerprint exists to prevent silent divergence.

Minimum fields:

* app version
* browser engine version
* protocol version
* rule version
* card database fingerprint
* preview data package hash
* effect registry hash
* decklist hash for each player

If fingerprints differ, the UI must warn users before match start. Online mode may refuse to start if the difference can affect rules or card identity.

## 11. Low-Cost Online Relationship

The browser engine is the prerequisite for the cheapest long-term online model, but not for the first hosted online MVP.

Short-term online model:

* GitHub Pages SPA connects to hosted FastAPI
* hosted FastAPI runs the existing Python engine
* hosted runtime MatchState expires automatically
* no accounts, cloud deck storage, or permanent user history

Medium-term protocol work:

* ActionEnvelope
* compatibility fingerprint
* replay export
* protocol versioning
* room lifecycle contracts

Long-term local-rule target online model:

* both browsers run the TypeScript engine locally
* both browsers load local/static card data
* the relay only forwards envelopes
* user decks and replays remain local
* no account system is required
* no authoritative server database is required

The relay may later support:

* room creation
* room joining
* seat assignment
* heartbeat
* reconnect within TTL
* short-lived message buffering
* divergence report upload, optional and explicit

Any feature that requires the relay to understand official card data, card effects, or rule legality is out of scope for the low-cost online track.

## 12. Implementation Subtasks

### 12.1 Foundation

* Define shared TypeScript engine types aligned with the serialized GameState and Action model.
* Add browser-compatible deterministic random helpers.
* Add canonical serialization and state hash helpers.
* Add compatibility fingerprint helpers.
* Add fixture loader shared by tests.

### 12.2 Browser Match Runtime

* Implement match creation from two DeckLists.
* Resolve preferred printing to deterministic CardDefinitions from preview data.
* Create CardInstances and initial zones.
* Shuffle main decks deterministically.
* Store match snapshots and Events in browser storage.
* Export replay JSON from browser storage.

### 12.3 Core Rules MVP

* Implement setup, opening hand, mulligan, and initial Energy.
* Implement phase progression through a full turn.
* Implement Member play into legal slots.
* Implement Live Set and replacement draw.
* Implement Performance, Yell, Heart allocation, Live judgment, and Success Live movement.
* Implement next-turn setup and victory detection.
* Implement deck refresh for draw and Yell.

### 12.4 UI Wiring

* Route preview-mode match APIs to `BrowserMatchRuntime`.
* Re-enable browser preview match creation only when the browser engine is available.
* Keep unsupported-effect messaging explicit.
* Ensure replay export works without `/api/matches`.

### 12.5 Cross-Engine Regression

* Add Python reference fixtures for the MVP flows.
* Add TypeScript tests that consume the same fixtures.
* Compare final state hashes and key state assertions.
* Add at least one browser UI smoke test for creating and completing an MVP match.

### 12.6 Online Readiness Scaffold

* Define ActionEnvelope TypeScript type.
* Add envelope JSON round-trip tests.
* Add pre/post state hash checks in local loopback tests.
* Add protocol documentation for the future relay without implementing the relay yet.

## 13. Development Order

Recommended order:

1. state/action type mapping
2. deterministic RNG and state hash
3. browser match creation and setup
4. opening hand and mulligan
5. phase progression and Member play
6. Live Set, Yell, and Live judgment
7. next turn and victory
8. replay export
9. UI wiring
10. cross-engine fixture parity
11. ActionEnvelope scaffold

This order applies when the browser engine track is scheduled. It should not block hosted online MVP work or battle UI demo preview work.

## 14. Estimated Effort

For the first TypeScript browser engine MVP, assuming one developer already familiar with the project and after the project chooses to start this long-term track:

* optimistic: 4 to 6 focused development days
* realistic: 1.5 to 2.5 weeks
* cautious: 3 to 4 weeks if cross-engine fixture parity exposes hidden Python/TypeScript behavior differences

The estimate includes tests and UI wiring for the MVP rules. It does not include broad effect automation, online relay implementation, IndexedDB migration, or mobile UX polish beyond avoiding broken layout.

## 15. Acceptance Criteria

The long-term browser-engine MVP is complete when:

* a static browser build can create a local two-player match without FastAPI
* a match can proceed through at least one complete Live judgment
* a match can continue until normal three-successful-Live victory or draw
* browser replay export works
* unsupported effects are explicit and replay-safe
* TypeScript tests pass for the shared fixture set
* Python reference fixture assertions and TypeScript fixture assertions agree on key state results
* no `/api/matches` request is made in browser preview mode

## 16. Dependencies

Depends on:

* [001 Deck Analyzer](001-deck-analyzer.spec.md)
* [002 Rule Engine](002-rule-engine.spec.md)
* [003 GameState and Actions](003-gamestate-and-actions.spec.md)
* [005 Action System](005-action-system.spec.md)
* [008 Randomness and Replay](008-randomness-and-replay.spec.md)
* [011 Simulator MVP](011-simulator-mvp.spec.md)
* [012 Controller and Legal Actions](012-controller-and-legal-actions.spec.md)
* [017 Public Release and Export Policy](017-public-release-and-export-policy.spec.md)
* [019 Effect Execution MVP](019-effect-execution-mvp.spec.md)
* [020 Stage Attachments and Movement](020-stage-attachments-and-movement.spec.md)
