# Domain Glossary

## 1. Purpose

This glossary defines shared vocabulary for the Love Live! Series Official Card Game Analysis & Simulation Platform.

The terms here should be used consistently across architecture documents, future specifications, tests, UI labels, and contributor discussions.

Japanese official text remains the canonical language for card and rule data. English terms in this glossary are architectural working terms used to describe the system.

## 2. Game Concepts

### Match

Definition: A complete game session between players using valid decks under a specific rule version.

Purpose: Provides the top-level context for GameState, players, actions, events, victory detection, replay, and results.

Related Concepts: Player, Deck, GameState, Match Result, Action Log, Replay.

### Turn

Definition: A player's ordered opportunity to progress through the game flow and take legal actions.

Purpose: Structures timing, priority, phase transitions, draws, plays, Live attempts, and end-of-turn behavior.

Related Concepts: Phase, Action, Event, TurnStarted, EndTurnAction.

### Phase

Definition: A named segment of a turn with specific legal actions and timing rules.

Purpose: Controls which actions, triggers, and validations are available at a given point in the turn lifecycle.

Related Concepts: Turn, Action Window, PhaseChanged, Legal Action.

### Player

Definition: A participant in a match who owns a deck, zones, resources, and decision-making controller.

Purpose: Separates each participant's state, legal choices, successful Lives, and victory progress.

Related Concepts: PlayerState, Controller, Deck, Hand, Stage, Energy Deck.

### Deck

Definition: A playable collection of cards prepared before a match according to deck construction rules.

Purpose: Serves both deck analysis and battle simulation as the player's main card source.

Related Concepts: Deck List, Card, Deck Legality, Match.

### Energy Deck

Definition: A specialized card collection or zone associated with Energy cards, subject to official construction and gameplay rules.

Purpose: Supports Energy-related costs, resources, and simulator actions.

Related Concepts: Energy, PayEnergyAction, PlayerState, Deck Validation.

### Hand

Definition: A player's private zone containing cards available for future actions.

Purpose: Represents hidden player resources used for playing cards and making decisions.

Related Concepts: PlayerState, DrawCardAction, PlayMemberAction, PlayLiveAction.

### Stage

Definition: The in-play zone where Member cards or other relevant cards contribute to gameplay.

Purpose: Represents board presence, Heart contribution, Live support, and ongoing card state.

Related Concepts: Member, Card Instance, Zone Movement, Live Resolution.

### Live Area

Definition: The zone or context where a Live attempt is placed or resolved.

Purpose: Supports Live card play, success checks, and transition to Success Live Area when successful.

Related Concepts: Live, LiveStarted, LiveSucceeded, Success Live Area.

### Waiting Room

Definition: A discard-like zone containing cards that have been used, moved, or otherwise left active play.

Purpose: Tracks spent cards and supports effects or rules that refer to discarded or waiting cards.

Related Concepts: Zone Movement, CardMoved, Effect, Replay.

### Success Live Area

Definition: The zone that tracks successfully completed Live cards.

Purpose: Represents progress toward victory and supports victory condition checks.

Related Concepts: Live, LiveSucceeded, Victory Condition, Match Result.

### Victory Condition

Definition: The rule-defined condition that determines when a player wins a match.

Purpose: Allows the engine, simulator, and AI to identify game completion consistently.

Related Concepts: Match Result, Success Live Area, Rule Engine, Validation.

## 3. Card Concepts

### Card

Definition: A general term for official card data. Architecture discussions should use Gameplay Card, Card Printing, or Card Instance when identity precision matters.

Purpose: Provides a readable umbrella term without collapsing rule identity, printing identity, and runtime-copy identity.

Related Concepts: Gameplay Card, Card Printing, Card Instance, Member, Live, Energy.

### Gameplay Card

Definition: A rule-level official card definition identified by stable `card_code`, excluding rarity, illustration, and printing suffixes.

Purpose: Owns canonical Japanese name, card type, rule attributes, text revisions, effect interpretations, deck legality identity, and simulator behavior.

Related Concepts: Card Printing, Card Text Revision, Deck Entry, Member, Live, Energy.

### Card Printing

Definition: A specific official rarity, illustration, or release version identified by the complete official `card_id`.

Purpose: Owns printing-level metadata such as rarity, card image, Card Set membership, and source observations without duplicating gameplay rules.

Related Concepts: Gameplay Card, Card Set, Rarity, Source Observation.

### Card Instance

Definition: A specific runtime copy of a Gameplay Card inside a match.

Purpose: Distinguishes canonical card data from a copy that moves between zones and carries temporary match state.

Related Concepts: Gameplay Card, Zone, GameState, CardMoved.

### Member

Definition: A card type representing a playable character or member card under official rules.

Purpose: Supports board development, Heart contribution, and Live success setup.

Related Concepts: Stage, Cost, Heart, PlayMemberAction.

### Live

Definition: A card type representing a Live attempt or objective under official rules.

Purpose: Drives Live resolution and progress toward victory.

Related Concepts: Live Area, Success Live Area, Live Requirement Coverage, Victory Condition.

### Energy

Definition: A card type and resource concept used to pay costs under official rules.

Purpose: Supports cost payment, resource planning, deck legality, and simulation actions.

Energy cards do not currently have special card-specific attributes in the project model. They are represented as Energy cards and used as one Energy card for payment/readiness purposes.

Related Concepts: Energy Deck, Cost, PayEnergyAction.

### Cost

Definition: A numeric or rule-defined requirement needed to play or resolve certain cards or actions.

Purpose: Enables legality validation, cost curve analysis, and AI resource decisions.

Related Concepts: Energy, Cost Curve, Legal Action, Validation.

### Heart

Definition: A card attribute used by game rules and deck analysis, especially for Live support and distribution analysis.

Purpose: Supports Live success evaluation, deck consistency analysis, and card comparison.

Heart data must preserve color distinctions. Member cards use basic Heart by color. Live cards use required Heart by color.

The source color slots currently used by the importer review are `heart01` pink, `heart02` red, `heart03` yellow, `heart04` green, `heart05` blue, and `heart06` purple. `heart0` represents any color and is used only where official data indicates an any-color requirement or all-color Blade Heart icon.

Related Concepts: Heart Distribution, Live Requirement Coverage, Member.

### Blade

Definition: A Member card attribute recorded from official card data as `ブレード`.

Purpose: Determines how many cards a Member contributes to the Yell reveal process during Live resolution.

Blade and Penlight are treated as the same project concept unless later source review proves a rule distinction. The canonical internal name should be `blade`.

Related Concepts: Member, Yell, Live Resolution, Validation.

### Blade Heart

Definition: A card icon or source field that identifies the Heart color contributed or processed through Yell.

Purpose: Supports Yell draw behavior and Live required Heart checks without confusing the icon color with the Member `blade` reveal count.

Blade Heart color may appear in official Member or Live card data. It is not an Energy card attribute. Official card-list HTML may represent an all-color Blade Heart icon with `alt="ALL1"`, normalized as `heart0`.

Related Concepts: Blade, Heart, Yell, Live Requirement Coverage.

### Special Blade Heart

Definition: A Live-card-specific Blade Heart icon called `特別なブレードハート` in the official quick manual and exposed under `特殊ハート` in official card detail data.

Purpose: Produces a fixed rule effect when the Live card is revealed by Yell.

Confirmed forms include:

* ALL: treated as an arbitrary Heart color during Live success judgment
* Draw: draws the stated number of cards after all Yell processing ends
* Score: adds the stated value during Live win/loss score judgment

Special Blade Hearts are structured Live attributes, not Member Blade values and not free-form card effect text. Their original icon labels must be preserved.

Related Concepts: Live, Blade Heart, Yell, Live Success Judgment, Live Judgment.

### Card Set

Definition: An official card-list grouping identified by a code such as `BP01`, `PLSD01`, or `PR`.

Purpose: Groups Card Printings for official source review, import validation, and search filtering.

The official `収録商品` label is preserved as raw Japanese source data in Phase 1 and is not automatically normalized as a Product entity.

Related Concepts: Card Printing, Source Observation, Import Batch.

### Card Text Revision

Definition: One immutable version of the official Japanese effect text associated with a Gameplay Card.

Purpose: Preserves errata and text history while allowing effect tags, Effect DSL, and executable behavior to remain traceable to exact source text.

Related Concepts: Gameplay Card, Raw Effect Text, Effect Tag, Effect DSL, Review Status.

### Work

Definition: A normalized official `作品名` identity associated with one or more Gameplay Cards.

Purpose: Supports consistent series filtering and cross-product analysis while retaining the original Japanese source label.

Related Concepts: Gameplay Card, Unit, Source Observation.

### Unit

Definition: A normalized official `参加ユニット` identity associated with one or more Gameplay Cards.

Purpose: Supports unit-based search, analysis, and future effect conditions while retaining the original Japanese source label.

Related Concepts: Gameplay Card, Work, Source Observation.

### Rarity

Definition: An official card classification describing rarity or printing category.

Purpose: Supports card metadata, search, collection context, and future UI filtering.

Related Concepts: Card Printing, Card Set, Source Observation.

### Source Observation

Definition: A timestamped record of the official Japanese fields observed for one Card Printing from one official source.

Purpose: Preserves source URL, parser version, raw labels such as `収録商品`, and validation notes without mixing source payloads into normalized rule identity.

Related Concepts: Card Printing, Card Text Revision, Work, Unit, Import Batch.

### Import Batch

Definition: One bounded importer execution with requested sources, parser version, timing, result counts, and errors.

Purpose: Makes successful, partial, and failed imports auditable and reproducible.

Related Concepts: Source Observation, Card Set, Parser Version, Import Log.

## 4. Rule Concepts

### Action

Definition: A player, AI, or system intent that may change GameState when validated and resolved.

Purpose: Makes state changes explicit, serializable, loggable, and replayable.

Related Concepts: Legal Action, Action Log, Resolution, Replay.

### Legal Action

Definition: An action option that is valid for the current GameState, player, phase, and rule version.

Purpose: Ensures Human and AI controllers choose only from rule-approved options.

Related Concepts: LegalActionGenerator, Controller, Validation, Rule Engine.

### Trigger

Definition: A condition point where an effect or rule may become relevant due to an event or timing window.

Purpose: Supports structured effect modeling and future automated effect execution.

Related Concepts: Event, Effect, Condition, Resolution.

### Effect

Definition: A card or rule behavior that reacts to triggers, checks conditions, and produces actions or events.

Purpose: Separates raw official effect text from machine-readable behavior.

Related Concepts: Trigger, Condition, Action, Raw Effect Text.

### Effect Tag

Definition: A semantic label attached to an effect, such as draw, search, energy, or live_support.

Purpose: Supports deck analysis, search, and Simple AI heuristics before full effect execution is available.

Related Concepts: Effect, Deck Analyzer, Simple AI, Simulation Support Status.

### Effect DSL

Definition: A future structured representation of effect behavior using concepts such as Trigger, Condition, Cost, Choice, Target, Action, and Duration.

Purpose: Provides a path from raw Japanese effect text toward reviewed executable behavior without hard-coding individual cards.

Related Concepts: Effect, Trigger, Condition, Action, Review Status.

### Simulation Support Status

Definition: A confidence and capability label describing how much simulator support an effect has.

Purpose: Prevents analyzer, simulator, and AI behavior from treating unsupported or tag-only effects as executable rules.

Related Concepts: unsupported, tagged_only, manual_resolution, partially_executable, fully_executable, test_validated_executable, reviewed_executable.

### ManualAdjustmentAction

Definition: A structured, serializable Action that records a manual effect resolution adjustment.

Purpose: Keeps manual resolution replay-safe by preventing direct GameState mutation and avoiding note-only logs.

Related Concepts: manual_resolution, Action, Replay, GameState.

### Event

Definition: A recorded fact that something happened during state transition or rule resolution.

Purpose: Supports triggers, logs, replay inspection, AI explanation, and debugging.

Related Concepts: Action, Resolution, Action Log, Replay.

### Resolution

Definition: The process of applying a validated action or effect outcome to produce a new game state and events.

Purpose: Centralizes state transition behavior and keeps controllers from mutating state directly.

Related Concepts: ActionResolver, GameState, Event, Validation.

### Validation

Definition: The process of determining whether data, decks, actions, or state satisfy applicable rules.

Purpose: Protects correctness across imports, deck analysis, simulation, AI, and future online play.

Related Concepts: Deck Validation, Action Validation, State Invariant Validation.

### Zone Movement

Definition: The rule-governed movement of a Card Instance from one zone to another.

Purpose: Makes card location changes explicit for validation, replay, triggers, and logs.

Related Concepts: CardMoved, Zone, Action, Event.

## 5. Analyzer Concepts

### Cost Curve

Definition: The distribution of card costs within a deck.

Purpose: Helps evaluate early playability, resource pressure, and deck consistency.

Related Concepts: Cost, Deck Analyzer, Simple AI.

### Heart Distribution

Definition: The distribution of Heart values or colors within a deck.

Purpose: Helps evaluate Live support reliability and deck balance.

Related Concepts: Heart, Live Requirement Coverage, Deck Analyzer.

### Live Requirement Coverage

Definition: A measure of how well a deck can satisfy the requirements of its Live cards.

Purpose: Helps identify whether a deck can consistently complete its intended Lives.

Related Concepts: Live, Heart Distribution, Success Live Area.

### Key Card Access Probability

Definition: The estimated probability of seeing a specific card or card group by a given timing point.

Purpose: Helps evaluate consistency around important cards and strategies.

Related Concepts: Hypergeometric Analysis, Monte Carlo Simulation, Random Seed.

### Hypergeometric Analysis

Definition: A mathematical probability method for estimating draws without replacement.

Purpose: Provides fast baseline probabilities for deck consistency questions.

Related Concepts: Key Card Access Probability, Deck, Hand.

### Monte Carlo Simulation

Definition: Repeated seeded or random trials used to estimate outcomes through simulation.

Purpose: Evaluates scenarios that are too complex for simple formulas.

Related Concepts: Random Seed, Deterministic Simulation, AI vs AI Debug Mode.

### Consistency Score

Definition: A derived summary measure of how reliably a deck performs a target plan.

Purpose: Provides a high-level analyzer output after lower-level metrics are trustworthy.

Related Concepts: Cost Curve, Key Card Access Probability, Live Requirement Coverage.

## 6. Simulator Concepts

### Controller

Definition: A decision-making layer that chooses a legal action for a player.

Purpose: Allows humans, simple AI, future AI, CLI runners, and UI clients to use the same engine.

Related Concepts: Human Controller, AI Controller, Legal Action.

### Human Controller

Definition: A controller that receives a choice from a human user.

Purpose: Supports local playable matches and future UI or online clients.

Related Concepts: Controller, Legal Action, Battle Simulator.

### AI Controller

Definition: A controller that chooses legal actions using an automated policy.

Purpose: Supports Human vs AI, AI vs AI debug simulation, and future advanced testing.

Related Concepts: Simple AI, FutureAIController, Random Seed.

### Simple AI

Definition: The first deterministic, explainable AI policy that makes legal decisions using simple heuristics.

Purpose: Enables simulator MVP, automated debug games, and regression tests without requiring strong play.

Related Concepts: AI Controller, Legal Action, AI Decision Log.

### Replay

Definition: A reproducible record of a match based on initial state, random seed, and action log.

Purpose: Supports debugging, sharing, regression tests, future spectator tools, and online dispute review.

Related Concepts: Action Log, Random Seed, Deterministic Simulation.

### Action Log

Definition: A chronological record of validated actions, relevant decisions, and state-transition metadata.

Purpose: Supports replay, AI explanation, debugging, and online readiness.

Related Concepts: Action, Event, Replay.

### Random Seed

Definition: A recorded value used to make random operations reproducible.

Purpose: Ensures shuffles, AI tie-breaks, simulations, and replays can be reproduced.

Related Concepts: Deterministic Simulation, Monte Carlo Simulation, Replay.

### Deterministic Simulation

Definition: A simulation that produces the same result from the same initial state, action log, and random seed.

Purpose: Enables reliable tests, replay, AI debugging, and future server synchronization.

Related Concepts: Random Seed, Replay, Action Log.

## 7. Future Online Concepts

### Authoritative Server

Definition: A server that owns official match state and validates all player actions.

Purpose: Reduces cheating risk and keeps online matches synchronized.

Related Concepts: Server State, Client State, Action Validation.

### Client State

Definition: A player's local view or projection of match state.

Purpose: Supports display and input without becoming the trusted source of game truth.

Related Concepts: Server State, Authoritative Server, Spectator Mode.

### Server State

Definition: The trusted match state maintained by an authoritative server.

Purpose: Provides the official basis for action validation, synchronization, and results.

Related Concepts: Authoritative Server, GameState, Online Multiplayer.

### Matchmaking

Definition: A future online service that pairs players into matches.

Purpose: Supports public online play and tournament-style workflows.

Related Concepts: Online Multiplayer, Player, Match.

### Spectator Mode

Definition: A future feature allowing observers to view a match without controlling a player.

Purpose: Supports tournaments, learning, and community sharing.

Related Concepts: Replay Sharing, Client State, Action Log.

### Replay Sharing

Definition: A future feature for storing and distributing reproducible match records.

Purpose: Supports analysis, review, tournaments, and community discussion.

Related Concepts: Replay, Action Log, Spectator Mode.
