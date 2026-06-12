# Data Model Notes

## 1. Purpose

This document describes the conceptual data model for the platform.

It does not define database tables, API contracts, migrations, or implementation classes. It describes business concepts, ownership boundaries, and versioning needs that future specifications can refine.

The frozen logical card storage contract and ERD are defined in [018 Card Data Storage](../specs/018-card-data-storage.spec.md) and [Card Data ERD](12-card-data-erd.md).

The same conceptual model should support both first-class products:

* Deck Analyzer
* Battle Simulator

## 2. Core Entities

### Card

Card is an umbrella term. The persistent data model must distinguish Gameplay Card from Card Printing.

### Gameplay Card

A Gameplay Card is the rule-level definition identified by `card_code`.

It owns canonical Japanese name, card type, Member or Live attributes, Heart data, Special Blade Hearts, text revisions, Work and Unit associations, and deck legality identity.

Deck Analyzer, Rule Engine, Battle Simulator, and AI use Gameplay Card identity.

### Card Printing

A Card Printing is an official rarity, illustration, or release version identified by complete `card_id`.

It owns rarity, image reference, Card Set membership, and printing-level source observations. Multiple Card Printings may reference one Gameplay Card.

### CardInstance

A CardInstance is one copy of a Gameplay Card in a match context.

It exists because individual copies may occupy different zones, move independently, and eventually carry temporary match state. CardInstance concepts belong to simulation and rule modeling, not to the canonical card database alone.

### Card Set

A Card Set represents an official card-list grouping such as `BP01`, `PLSD01`, or `PR`.

It provides stable source grouping and import validation context for Card Printings. The official detail-page `収録商品` label remains raw Japanese source data in Phase 1 rather than a normalized Product entity.

### Card Text Revision

A Card Text Revision is one immutable official Japanese text version for a Gameplay Card.

It owns the raw text hash and observation history used by effect tags, Effect DSL drafts, executable behavior, and review records.

### Work and Unit

Work and Unit normalize official `作品名` and `参加ユニット` values.

Both are many-to-many relationships with Gameplay Card. Their associations preserve original Japanese labels and source observations.

### Deck

A Deck is a playable collection of cards prepared under construction rules.

Decks are used by both analysis and simulation. The Deck Analyzer evaluates legality and consistency. The Battle Simulator uses decks to create match starting state.

### Deck List

A Deck List is a portable representation of a deck's contents.

It identifies Gameplay Cards by `card_code` and quantity. It may optionally retain a preferred Card Printing for presentation, plus user notes or analysis targets. It is user-created data and should remain separate from official source data.

### Player

A Player is a participant in a match.

In local play this may be a human user, an AI-controlled participant, or a debug simulation participant. Future online play may attach account identity, but the core game engine should not require online account concepts.

### Match

A Match is a complete game session using decks, players, rule version, initial randomness, actions, and events.

The Match concept connects deck data, player state, GameState, action logs, replay requirements, and match results.

### Match Result

A Match Result summarizes the outcome of a completed match.

It may include winner, loser, number of turns, successful Live counts, final state summary, relevant rule version, and replay reference.

### Source Observation

A Source Observation describes what an official source exposed for one Card Printing at a specific time.

It records official source URL, source version, fetch timestamp, parser version, language, raw source labels, and validation notes. It supports auditing, text revision provenance, and reproducible imports.

### Import Batch

An Import Batch represents one bounded importer execution.

It records requested Card Sets, parser version, timing, status, result counts, and errors. Partial imports remain explicit rather than appearing complete.

### Rule Version

A Rule Version identifies the official rule context used for validation or simulation.

It matters because deck legality, action legality, effect interpretation, and victory rules may change over time.

## 3. Relationships

### Gameplay Card Has Printings

A Gameplay Card has one or more Card Printings.

This prevents rarity, image, and Card Set differences from duplicating rule attributes or effect behavior.

### Card Printing Belongs to Card Set

A Card Printing belongs to one reviewed Card Set grouping for its card-list observation.

This supports source filtering and import validation without treating raw `収録商品` text as a normalized Product.

### Deck Contains Cards

A Deck contains card references and quantities.

The conceptual deck model should support legality validation, ratio analysis, probability calculations, and construction of match starting state.

### Match Uses Decks

A Match uses prepared decks for each player.

Deck data should be validated before match start. Once a match begins, the engine operates on match state and CardInstances rather than editing the original Deck List.

### CardInstance Refers to Card

Every CardInstance should refer back to a Gameplay Card definition.

This allows the engine to track individual copies while still using canonical card metadata and effect information.

### Match Produces Action Logs

A Match should produce a log of actions and relevant events.

This supports replay preparation, AI debugging, Monte Carlo audits, regression testing, and future online dispute review.

### Rule Version Affects Validation

Validation should be interpreted under a known Rule Version.

This applies to deck legality, action legality, state invariants, Live resolution, and future effect execution.

### Gameplay Card Has Text Revisions

A Gameplay Card may have multiple official text revisions but at most one current revision.

Effect tags, DSL drafts, executable behavior, and reviews refer to a specific revision and raw text hash.

### Deck Entry References Gameplay Card

A Deck Entry references `card_code` and may optionally select a preferred Card Printing for presentation.

Copy limits, legality, analysis, and simulation use Gameplay Card identity. A preferred printing must belong to the same Gameplay Card.

## 4. Data Ownership

### Official Source of Truth

Official Japanese source material is authoritative for card data and rule data.

The project should preserve official source references and should not allow unofficial data to silently override official data.

### Local Normalized Data

Local normalized data is the project's structured representation of official source data.

It exists for search, validation, analysis, and simulation. It should remain traceable back to official sources.

Rule identity belongs to Gameplay Card. Printing metadata and source observations belong to Card Printing. Raw official effect text history belongs to Card Text Revision.

### Derived Data

Derived data is created by the project or user workflows.

Examples include effect tags, analysis summaries, consistency scores, probability results, and translations. Derived data should not replace canonical Japanese source data.

Semantic effect data has multiple derived layers. Effect tags, structured Effect DSL records, executable behavior, parse confidence, review status, and simulation support status are all derived from a specific Card Text Revision and should remain traceable to its `raw_text_hash`.

LLM-assisted parsing may produce draft tags or Effect DSL records, but those drafts are not authoritative data. Drafts should preserve parse confidence, parser version, raw text hash, and review status so they can be audited, re-run, or rejected.

### User-Created Deck Data

Deck Lists and user notes are user-created data.

They may reference official cards, but they are owned separately from official source records. This distinction matters for export, sharing, and future account features.

## 5. Data Versioning

The conceptual model should preserve enough metadata to understand when and how data was produced.

Important versioning concepts:

* fetched_at: when source data was retrieved
* source_url: where source data came from
* source_version: what official source version or release context was used
* parser_version: what importer or parser interpretation produced local data
* rule_version: what official rule context applies

Versioning must support:

* new card releases
* source site changes
* parser improvements
* rule changes
* card errata
* FAQ and ruling updates

## 6. Validation Ownership

Validation is shared infrastructure, not a product-specific feature.

Deck Analyzer needs validation to report legality and assumptions. Battle Simulator needs validation to prevent illegal game states and actions. AI needs validation to choose only legal actions. Future online play needs validation to enforce authoritative state.

Validation should cover different domains:

* imported source data
* normalized card data
* deck construction
* match setup
* action legality
* state invariants
* effect model consistency

## 7. Future Expansion

### New Card Releases

New Card Sets and Card Printings should be added without rewriting existing analysis or simulator architecture.

The model should allow multiple Card Sets, printings, import batches, source versions, and validation passes.

### Rule Changes

Rules should be versioned so old decks, replays, and analysis results can be understood under their original assumptions.

### Card Errata

Errata should preserve both source history and current official meaning.

Future specifications should decide how to compare old and new card text without losing traceability.

### Effect Updates

Raw Japanese effect text revisions and structured effect data should remain separate.

Structured effect updates should be reviewable and versioned because effect modeling is interpretive and may improve over time.

Every modeled effect should conceptually track simulation support status. This allows Deck Analyzer, Battle Simulator, AI, and replay workflows to distinguish unsupported effects from tag-only, manual, partially executable, fully executable, and reviewed executable behavior.

Deck Analyzer may use tags and derived heuristics without requiring full effect execution. Battle Simulator must distinguish manual effects from executable effects before attempting automatic resolution.

`test_validated_executable` represents executable behavior covered by automated rule tests but not yet human reviewed. `reviewed_executable` requires human review.

Manual resolution should produce structured manual adjustment actions so replay remains reproducible.

Manual adjustment actions are container actions with one or more structured adjustment entries. The exact field ownership belongs to [005-action-system.spec.md](../specs/005-action-system.spec.md).

Effect review should distinguish parser drafts, contributor proposals, human review, rules-sensitive review, and maintainer approval.

### Online Account and User Data

Future online features may introduce accounts, deck ownership, match history, ranking, and tournament data.

These concepts should remain outside the core card and rule source-of-truth model. The game engine should not require online account data to validate or simulate a match.
