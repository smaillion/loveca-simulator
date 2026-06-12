# Love Live! Series Official Card Game Analysis & Simulation Platform

## 1. Project Purpose

This project aims to build a complete platform for Love Live! Series Official Card Game, also known as ラブカ.

The platform has two first-class products:

* Deck Analyzer
* Battle Simulator

Neither product is secondary. Both should share the same underlying card data, domain model, rule model, validation logic, effect model, randomness model, and replay-friendly action model.

The first purpose of the project is not to publish an online service. The first purpose is to establish reliable architecture, terminology, and local tooling that can grow into both serious deck analysis and playable simulation.

## 2. Long-Term Vision

The long-term platform should support:

* structured card database
* official card data import
* deck construction
* deck legality validation
* deck strength analysis
* probability analysis
* Monte Carlo simulation
* playable local battle simulator
* Human vs Human local play
* Human vs Simple AI play
* AI vs AI debug simulation
* replay system
* simple user interface
* future advanced AI
* future online multiplayer
* future tournament tools

The game engine should be usable in CLI mode, local UI mode, AI simulation mode, and future server-authoritative online mode without rewriting the core engine.

## 3. Product A: Deck Analyzer

The Deck Analyzer should help players understand deck legality, consistency, and probability.

It should eventually support:

* deck import
* deck legality validation
* card type ratio analysis
* cost curve analysis
* Heart distribution analysis
* Live requirement coverage analysis
* key-card access probability
* hypergeometric probability calculations
* Monte Carlo draw simulation
* consistency scoring
* weakness detection
* improvement suggestions
* future matchup simulation

The analyzer must not depend on UI implementation details. It should reuse the same card database and rule validation logic used by the Battle Simulator.

## 4. Product B: Battle Simulator

The Battle Simulator should allow playable local matches and automated debug matches.

It should eventually support:

* loading two real decks
* starting a match
* drawing opening hands
* mulligan
* turn progression
* playing Member cards
* playing Live cards
* paying Energy
* resolving basic Live success
* tracking successful Lives
* detecting victory
* Human vs Human local play
* Human vs Simple AI play
* AI vs AI debug mode
* action logs
* replay preparation
* simple UI
* future online multiplayer

The simulator must not depend on frontend framework logic. Human players, AI controllers, CLI runners, local UI, and future online clients should all interact with the same core rule engine through legal actions.

## 5. MVP Definition

The first complete MVP should include both a Deck Analyzer MVP and a Battle Simulator MVP.

### MVP-A: Deck Analyzer

Minimum capabilities:

* import deck list
* validate deck legality
* analyze card type ratio
* analyze cost curve
* analyze Heart distribution
* analyze Live card count
* estimate key-card access probability

### MVP-B: Battle Simulator

Minimum capabilities:

* load two decks
* start game
* draw opening hands
* mulligan manually or by AI
* play turns
* play Member cards
* play Live cards
* pay Energy
* resolve basic Live success
* detect victory
* support Human vs Human
* support Human vs Simple AI
* support AI vs AI debug simulation

No online multiplayer is required in the MVP. No advanced AI is required in the MVP. No full automatic card effect execution is required in the MVP. Manual effect handling or limited effect support is acceptable for the first simulator prototype.

## 6. Non-Goals for Initial Version

Initial versions should not attempt to provide:

* public online multiplayer
* tournament operations
* judge-level ruling completeness
* full automatic parsing of all card effects
* advanced competitive AI
* full card image redistribution
* replacement for official rule documents

These are future directions or out-of-scope responsibilities until the core data, rules, and simulation architecture is reliable.

## 7. Development Principles

* Official sources are the primary source of truth.
* Japanese official text is the canonical language for card and rule data.
* Raw card text and structured effect data must be separated.
* Card effects must be modeled in separate layers: raw text, tags, structured DSL, and executable implementation.
* Every card effect should have an explicit simulation support status.
* Deck Analyzer and Battle Simulator should share core models and validation.
* All state changes in simulated play should be represented as actions.
* Randomness should be deterministic when a seed is provided.
* Game state, actions, and logs should be designed for replay from the beginning.
* Rule implementation should be test-driven.
* Simulation should begin with simplified assumptions and evolve incrementally.
* All data transformations should be reproducible.
* Architecture documentation should precede detailed specifications and implementation.

## 8. Future Online Multiplayer Direction

Online multiplayer is not required for the MVP, but the architecture should prepare for it.

Future online play should prefer an authoritative server model. The server should own official match state and validate actions. Clients should submit intended actions and display state, but they should not be trusted as the source of truth.

Early architecture choices should avoid coupling the engine to local UI state. The same rule engine should be usable in local mode, dedicated server mode, simulation mode, AI debug mode, and replay mode.

## 9. Target Users

Target users include:

* personal deck builders
* competitive players who want statistical analysis
* players who want local playable testing
* developers interested in card game simulation
* AI and agent-based testing workflows
* future tournament or online-play tooling
