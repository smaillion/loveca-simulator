# Specification Index

## Purpose

This directory contains markdown specifications for future implementation phases.

Current specs are requirement and architecture specifications only. They do not define physical database schemas, SQL, migrations, APIs, implementation classes, scraper code, UI code, or executable effect behavior.

## Current Specs

* [000 Card Database](000-card-database.spec.md)
* [001 Deck Analyzer](001-deck-analyzer.spec.md)
* [002 Rule Engine](002-rule-engine.spec.md)
* [003 GameState and Actions](003-gamestate-and-actions.spec.md)
* [005 Action System](005-action-system.spec.md)
* [007 Effect DSL](007-effect-dsl.spec.md)
* [008 Randomness and Replay](008-randomness-and-replay.spec.md)
* [010 Simple AI](010-simple-ai.spec.md)
* [011 Simulator MVP](011-simulator-mvp.spec.md)
* [012 Controller and Legal Actions](012-controller-and-legal-actions.spec.md)
* [014 Data Importer](014-data-importer.spec.md)
* [015 Effect Taxonomy](015-effect-taxonomy.spec.md)
* [016 Terminology Normalization](016-terminology-normalization.spec.md)
* [017 Public Release and Export Policy](017-public-release-and-export-policy.spec.md)
* [018 Card Data Storage](018-card-data-storage.spec.md)

## Dependency Graph

```text
015 Effect Taxonomy
  -> 000 Card Database
  -> 001 Deck Analyzer
  -> 002 Rule Engine
  -> 003 GameState and Actions
  -> 005 Action System
  -> 007 Effect DSL
  -> 008 Randomness and Replay
  -> 010 Simple AI
  -> 011 Simulator MVP
  -> 014 Data Importer

016 Terminology Normalization
  -> 000 Card Database
  -> 001 Deck Analyzer
  -> 007 Effect DSL
  -> 014 Data Importer
  -> 015 Effect Taxonomy
  -> 018 Card Data Storage

017 Public Release and Export Policy
  -> 000 Card Database
  -> 001 Deck Analyzer
  -> 014 Data Importer
  -> 015 Effect Taxonomy
  -> 018 Card Data Storage

018 Card Data Storage
  -> 001 Deck Analyzer
  -> 007 Effect DSL
  -> 014 Data Importer

000 Card Database
  -> 001 Deck Analyzer
  -> 014 Data Importer
  -> 018 Card Data Storage

002 Rule Engine
  -> 003 GameState and Actions
  -> 005 Action System
  -> 011 Simulator MVP
  -> 012 Controller and Legal Actions

003 GameState and Actions
  -> 005 Action System
  -> 008 Randomness and Replay
  -> 011 Simulator MVP
  -> 012 Controller and Legal Actions

007 Effect DSL
  -> 002 Rule Engine
  -> 003 GameState and Actions
  -> 005 Action System
  -> 008 Randomness and Replay
  -> 010 Simple AI
  -> 011 Simulator MVP

005 Action System
  -> 002 Rule Engine
  -> 003 GameState and Actions
  -> 008 Randomness and Replay
  -> 011 Simulator MVP
  -> 015 Effect Taxonomy

008 Randomness and Replay
  -> 005 Action System
  -> 010 Simple AI
  -> 011 Simulator MVP

010 Simple AI
  -> 002 Rule Engine
  -> 003 GameState and Actions
  -> 012 Controller and Legal Actions
  -> 011 Simulator MVP

012 Controller and Legal Actions
  -> 002 Rule Engine
  -> 003 GameState and Actions
  -> 005 Action System
  -> 008 Randomness and Replay
  -> 010 Simple AI
  -> 011 Simulator MVP
```

## Effect Modeling Rule

All effect-related specs must preserve the four-layer model:

1. `raw_effect_text`
2. `effect_tags`
3. structured Effect DSL
4. executable effect implementation

Raw official text is versioned through Card Text Revision. Tags, DSL, and executable review state must identify the revision and raw text hash they interpret.

LLM-assisted parsing may produce drafts, but it is not authoritative. `reviewed_executable` requires human review. Automated rule-test validation alone may only support `test_validated_executable`.
