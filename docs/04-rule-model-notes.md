# Rule Model Notes

## 1. Purpose

This document describes the conceptual rule model for the platform.

It does not implement rules, define classes, define APIs, or specify database structure. It explains architecture principles that future specifications and implementation should follow.

The rule model must serve both first-class products:

* Deck Analyzer
* Battle Simulator

It must also prepare for Simple AI, replay, deterministic simulation, and future online multiplayer.

## 2. GameState

GameState represents the complete authoritative state of a match at a point in time.

Conceptually, it includes:

* player states
* current turn and phase
* zones and card locations
* resources
* successful Live progress
* pending action or effect context when needed
* random seed or randomness context when needed
* rule version context

GameState must be serializable because the platform needs replay, AI debugging, Monte Carlo simulation, regression tests, and future online synchronization.

GameState must be UI-independent. A local UI, CLI runner, AI debug runner, or future online server should be able to use the same GameState concept without embedding presentation state in the engine.

## 3. PlayerState

PlayerState represents the match-specific state owned by one player.

It should conceptually include:

* player identity within the match
* deck and Energy Deck zones
* hand
* stage
* Live Area
* Waiting Room
* Success Live Area
* available resources
* successful Live count or progress
* any rule-relevant player status

PlayerState should not decide actions by itself. Decisions belong to controllers. PlayerState records the state that rules and controllers inspect.

## 4. Zones

Zones describe where CardInstances are located.

### Deck

The main draw source for a player during a match.

It must support deterministic shuffle and draw behavior.

### Energy Deck

The zone or collection used for Energy-related gameplay.

It must be modeled separately when official rules distinguish it from the main deck.

### Hand

The private zone of cards available to a player.

It matters for legal action generation, mulligan decisions, AI policy, and hidden information.

### Stage

The in-play zone where Member cards and relevant active cards contribute to gameplay.

It matters for Live support, board state, and future effects.

### Live Area

The zone or context where Live cards are attempted or resolved.

It matters for timing, success checks, and movement to Success Live Area.

### Waiting Room

The zone containing used, discarded, or moved cards according to official rules.

It matters for effects, replay, and state invariants.

### Success Live Area

The zone containing successfully completed Live cards.

It matters for victory progress and match result calculation.

## 5. Turn Flow

Turn flow describes the lifecycle of a player's turn.

The model should represent:

* turn start
* official phase transitions
* action windows
* Live attempt timing
* Live resolution timing at a conceptual level
* turn end

The official comprehensive rules baseline identifies each turn as:

* `先攻通常フェイズ`
* `後攻通常フェイズ`
* `ライブフェイズ`

Each normal phase contains:

* `アクティブフェイズ`
* `エネルギーフェイズ`
* `ドローフェイズ`
* `メインフェイズ`

The Live phase contains:

* `ライブカードセットフェイズ`
* `先攻パフォーマンスフェイズ`
* `後攻パフォーマンスフェイズ`
* `ライブ勝敗判定フェイズ`

Detailed action windows and edge cases should still be owned by future rule specifications.

The engine should treat phase transitions as explicit state changes rather than hidden control flow. This supports validation, action logs, AI decisions, replay, and future online synchronization.

## 6. Actions

An action is a proposed or resolved state-changing intent.

All game state changes should happen through actions because actions can be:

* validated
* serialized
* logged
* replayed
* explained to users
* checked by an authoritative server in the future

Actions should represent both player choices and system-driven transitions when appropriate.

Example action concepts:

* DrawCardAction
* PlayMemberAction
* PlayLiveAction
* PayEnergyAction
* MoveCardAction
* EndPhaseAction
* EndTurnAction

These names are conceptual examples, not implementation requirements.

## 7. Legal Action Generation

The engine should generate legal actions from the current GameState, active player, phase, and rule version.

Human and AI controllers should choose from generated legal actions only.

This ensures:

* AI cannot bypass rules
* UI cannot offer illegal choices
* future online clients cannot invent unvalidated state changes
* replay logs can be checked against the same legality model

Controllers choose. The rule engine validates and resolves.

## 8. Events

Events exist to record that something happened as a result of actions or rule processing.

Events help with:

* trigger processing
* logs
* replay inspection
* AI explanation
* debugging
* future UI updates

Example event concepts:

* TurnStarted
* PhaseChanged
* CardDrawn
* MemberPlayed
* LiveStarted
* LiveSucceeded
* CardMoved

Events should describe facts. They should not be a substitute for validation.

## 9. Effects

Effects represent card or rule behavior that may be triggered by timing, conditions, or events.

Effects should not directly modify GameState. Instead, future effect execution should produce validated action-like outcomes or requests for choices that are resolved by the rule engine.

Effects should be modeled in four layers:

* raw Japanese effect text
* effect tags
* structured Effect DSL
* executable effect implementation

The future structured model should follow the conceptual shape:

* Trigger
* Condition
* Cost
* Choice
* Target
* Action
* Duration

Raw Japanese effect text and structured effect data must remain separate.

This separation is necessary because official text is source data, while structured effects are interpreted data. The system should avoid designs that hard-code individual card IDs into the engine.

Every effect should have a simulation support status so the engine knows whether it is unsupported, tag-only, manually resolved, partially executable, fully executable, or reviewed executable.

Manual resolution is part of simulator/controller flow, not core rule mutation. For manual effects, the simulator may display raw Japanese text, pause automatic resolution, allow the player to resolve the effect manually, and then continue through validated actions.

Manual resolution must produce structured `ManualAdjustmentAction` records and must not mutate GameState directly. The ActionResolver remains responsible for applying validated manual adjustments.

LLM-assisted parsing may provide draft structure for effects, but the Rule Engine must not treat LLM output as authoritative. Executable effect behavior requires validation and review.

## 10. Validation

Validation is the rule model's correctness boundary.

The Rule Engine specification owns deck legality, action validation, legal action generation, turn and phase transitions, zone movement validation, Live resolution, victory checks, and state invariant validation.

Validation should apply to:

* deck construction
* match setup
* action legality
* phase and turn transitions
* zone movement
* Live resolution
* victory conditions
* state invariants
* future effect execution
* effect simulation support status before automatic resolution
* separation between manual resolution prompts and core rule resolution
* ManualAdjustmentAction structural validity

Validation philosophy:

* reject illegal actions before resolution
* keep state invariants explicit
* make assumptions visible
* tie rule decisions to rule version where practical
* prefer deterministic, explainable behavior

## 11. Replay

Replay should be prepared from the beginning even if a full replay viewer is not part of the MVP.

GameState and Action serialization requirements are owned by the GameState and Actions specification. Action safety and manual adjustment structure are owned by the Action System specification.

The platform should support an event-sourcing-friendly approach:

* initial GameState
* deck order or shuffle seed
* random seed
* action log
* resulting events
* final GameState summary

Given the same initial state, action log, and random seed, the same match should be reproducible.

This is required for:

* replay
* AI debugging
* Monte Carlo simulation
* online multiplayer synchronization
* bug reproduction
* regression testing
