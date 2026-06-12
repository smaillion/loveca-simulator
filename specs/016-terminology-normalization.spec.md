# 016 Terminology Normalization Specification

## 1. Purpose

This spec owns official Japanese terminology normalization and cross-module terminology consistency.

It does not define implementation code, database schema, UI, or scraper behavior.

## 2. Ownership

This spec owns:

* official Japanese terminology normalization
* canonical internal enum names
* display names
* aliases
* cross-module terminology consistency
* mapping between Japanese official terms and English architecture terms

## 3. Canonical Language Rule

Japanese official terminology is authoritative for card and rule data.

English architecture terms may be used internally for consistency, but they must map back to official Japanese terminology where relevant.

## 4. Normalization Responsibilities

Terminology normalization must support:

* `zones`
* `card_types`
* `card_identity_terms`
* `timing_terms`
* `effect_keywords`
* `action_terms`
* `resource_terms`
* `status_terms`
* `turn_phase_terms`
* `deck_construction_terms`

Each normalized term should conceptually include:

* `term_id`
* `official_japanese`
* `canonical_internal_name`
* `category`
* `display_ja`
* `display_en`
* `display_zh`
* `aliases`
* `source_reference`
* `validation_status`
* `notes`

These fields are conceptual and do not define a database schema.

## 5. Alias Policy

Aliases may exist for:

* alternate translations
* common player shorthand
* internal stable identifiers
* UI display labels

Aliases must not replace canonical Japanese source terms.

## 6. Cross-Module Consistency

Deck Analyzer, Battle Simulator, Data Importer, Effect DSL, Simple AI, and future UI must use terminology consistently.

When terms differ between official Japanese text and internal architecture language, the mapping should be explicit.

## 7. Source-Reviewed Examples

Current review status for provisional terms is tracked in [data_sources/terminology-review.md](../data_sources/terminology-review.md).

Terms must be one of:

* `source_confirmed`
* `ambiguous`
* `deprecated`
* removed from the review artifact

Provisional examples must not remain unclassified after source review.

## 8. Validation Status

Terminology records should support validation status values such as:

* `provisional`
* `source_confirmed`
* `deprecated`
* `ambiguous`

The exact lifecycle may be refined later, but provisional terms must be distinguishable from source-confirmed terms.

## 9. Dependencies

This spec informs:

* [000 Card Database](000-card-database.spec.md)
* [001 Deck Analyzer](001-deck-analyzer.spec.md)
* [007 Effect DSL](007-effect-dsl.spec.md)
* [014 Data Importer](014-data-importer.spec.md)
* [015 Effect Taxonomy](015-effect-taxonomy.spec.md)
* [018 Card Data Storage](018-card-data-storage.spec.md)

Architecture identity terms must remain explicit:

* `card_code`: Gameplay Card rule identity
* `card_id`: complete official Card Printing identity
* `card_instance_id`: runtime match-copy identity
* `text_revision_id`: immutable official Japanese text revision identity

These engineering identifiers do not replace official Japanese display terminology.
