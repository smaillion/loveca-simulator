# 018 Card Data Storage Specification

## 1. Purpose

This specification defines the logical storage contract for official card data.

It refines the conceptual requirements in [000 Card Database](000-card-database.spec.md) using the official cross-product importer review. It defines entity ownership, identity boundaries, relationships, uniqueness, nullability, and validation invariants.

It does not define SQL, migrations, ORM classes, APIs, importer implementation, or simulator behavior.

## 2. Identity Model

The storage model must distinguish two official card identities.

### Gameplay Card

A Gameplay Card is the rule-level card definition identified by `card_code`.

It owns:

* canonical Japanese card name
* card type
* Member or Live rule attributes
* Heart values
* Special Blade Hearts
* text revision history
* Work and Unit associations
* Loveca Point restrictions
* derived effect data through a specific text revision

`card_code` must be unique and must not include rarity, illustration, or printing suffixes.

### Card Printing

A Card Printing is one official printed or illustrated version identified by the complete official `card_id`.

It owns:

* rarity or printing classification
* card image reference
* Card Set membership
* printing-level source observations

Multiple Card Printings may reference one Gameplay Card. Printing differences must not duplicate rule attributes or effect interpretations unless official review proves that the gameplay definition changed.

## 3. Core Entities

### Gameplay Card

Required conceptual fields:

* `card_code`
* `canonical_name_ja`
* `card_type`
* `validation_status`

Rules:

* `card_code` is globally unique.
* `canonical_name_ja` is official Japanese data.
* `card_type` is one of `member`, `live`, or `energy`.
* A Gameplay Card must have at least one Card Printing before it is considered source-confirmed.
* Printing rarity, image URL, Card Set, and raw product label do not belong to this entity.

### Card Printing

Required conceptual fields:

* `card_id`
* `card_code`
* `card_set_code`
* `rarity_ja`
* `image_url`
* `validation_status`

Rules:

* `card_id` is globally unique and preserves the complete official printing identifier.
* `card_code` references exactly one Gameplay Card.
* `card_set_code` references exactly one Card Set for the card-list observation.
* `rarity_ja` and `image_url` may be null only when the official source does not expose them; the missing value must remain reviewable.
* A Card Printing must not own Member, Live, Heart, Special Blade Heart, or effect records.

### Card Set

A Card Set represents an official card-list grouping such as `BP01`, `BP03`, `BP06`, `PLSD01`, `HSSD01`, or `PR`.

Required conceptual fields:

* `card_set_code`
* `source_url`
* `validation_status`

Rules:

* `card_set_code` is unique.
* A display name may be added only when confirmed independently from official source data.
* The official `収録商品` text is not a normalized Product entity in Phase 1. It remains a raw source field in Source Observation.

### Member Attributes

Member Attributes form an optional one-to-one extension of Gameplay Card.

Conceptual fields:

* `card_code`
* `cost`
* `blade`
* `blade_heart_color_slot`

Rules:

* A Member Gameplay Card has at most one Member Attributes record.
* A non-Member Gameplay Card must not have one.
* `cost` and `blade` are non-negative when present.
* Missing official values remain null and require an explicit validation status; they must not be converted to zero.
* `blade_heart_color_slot` is optional and must use a normalized Heart color slot or an unresolved source value.

### Live Attributes

Live Attributes form an optional one-to-one extension of Gameplay Card.

Conceptual fields:

* `card_code`
* `score`
* `blade_heart_color_slot`

Rules:

* A Live Gameplay Card has at most one Live Attributes record.
* A non-Live Gameplay Card must not have one.
* `score` is non-negative when present.
* Live Attributes must not contain the Member numeric `blade` field.
* `blade_heart_color_slot` is optional and may use `heart0` for an official all-color Blade Heart.

### Heart Value

Heart Value stores one row per observed Gameplay Card, role, and color slot.

Conceptual fields:

* `card_code`
* `heart_role`
* `color_slot`
* `value`
* `source_label`
* `validation_status`

Rules:

* The unique identity is `(card_code, heart_role, color_slot)`.
* `heart_role` is `basic` or `required`.
* `basic` rows are allowed only for Member cards.
* `required` rows are allowed only for Live cards.
* `heart0` is forbidden for `basic` and allowed for `required`.
* `value` must be positive. An absent color is represented by no row, not a zero row.
* Unknown official color slots must be preserved with their raw source value and a review status; they must not be guessed.

### Special Blade Heart

Special Blade Heart stores repeatable fixed rule attributes on Live Gameplay Cards.

Conceptual fields:

* `special_blade_heart_id`
* `card_code`
* `ordinal`
* `effect_type`
* `value`
* `resolution_timing`
* `source_alt`
* `source_field`
* `validation_status`

Rules:

* Only Live Gameplay Cards may own these records.
* `(card_code, ordinal)` is unique.
* Confirmed `effect_type` values are `all_color`, `draw`, and `score`.
* Unknown icons use `unknown`, preserve exact `source_alt` and `source_field`, and require review.
* Unknown values remain null.
* These records are structural Live data, not free-form Effect DSL records.

### Card Text Revision

Card Text Revision preserves the official Japanese text history for one Gameplay Card.

Conceptual fields:

* `text_revision_id`
* `card_code`
* `revision_number`
* `raw_effect_text_ja`
* `raw_text_hash`
* `revision_status`
* `source_observation_id`
* `first_observed_at`
* `last_observed_at`

Rules:

* `(card_code, revision_number)` is unique.
* `(card_code, raw_text_hash)` must not be duplicated.
* `raw_effect_text_ja` and `raw_text_hash` are immutable after creation.
* At most one revision per Gameplay Card may be `current`.
* Other status values must distinguish at least `provisional`, `superseded`, and `deprecated`.
* A card with no official effect text may have no text revision.
* A Printing observes a revision through Source Observation; it does not own the revision.

### Work and Unit

Work and Unit normalize the official `作品名` and `参加ユニット` fields.

Conceptual fields for each entity:

* stable internal identifier
* canonical Japanese name
* validation status

Gameplay Card associations must:

* be many-to-many
* preserve the raw Japanese source label
* reference the Source Observation that established the association
* avoid inferring a Unit or Work that is absent from official source data

An official field containing multiple works or units must be tokenized only through a reviewed normalization mapping. The raw combined label must always remain available.

### Source Observation

Source Observation records what an official source exposed for one Card Printing at a specific time.

Conceptual fields:

* `source_observation_id`
* `card_id`
* `source_url`
* `source_version`
* `fetched_at`
* `parser_version`
* `language`
* `raw_product_label_ja`
* raw field labels or payload reference
* parse and validation notes

Rules:

* Japanese is the canonical language for official card observations.
* `収録商品` is stored as `raw_product_label_ja`.
* Multiple observations may exist for one Card Printing.
* Source history must not be overwritten when parser behavior or official content changes.
* Bulk raw payload retention remains subject to [017 Public Release and Export Policy](017-public-release-and-export-policy.spec.md).

### Import Batch

Import Batch records one importer execution and its source boundaries.

It must preserve parser version, timing, status, counts, errors, and the Card Sets requested. Partial imports must remain explicit.

### Loveca Point Rule Set and Entry

A Loveca Point Rule Set represents one versioned official restriction policy.

An entry conceptually includes:

* `rule_set_id`
* `card_code`
* `point_value`
* effective dates
* source reference
* notes

Rules:

* Point entries bind Gameplay Card, not Card Printing.
* Point values must not be stored as Live score.
* A Gameplay Card may have different point values in different rule sets.
* Rule-set history must remain available for old deck analyses and replays.

### Deck Entry

Deck Entry is user-created data that references a Gameplay Card.

Conceptual fields:

* `deck_id`
* `card_code`
* `quantity`
* `preferred_printing_id`

Rules:

* Deck legality and copy limits operate on `card_code`.
* `preferred_printing_id` is optional presentation metadata.
* When present, the preferred Card Printing must reference the same `card_code`.
* Changing a preferred printing must not change deck legality or simulator behavior.

## 4. Effect Ownership

Effect Tags, Effect DSL drafts, executable implementations, review records, and simulation support status must reference a specific Card Text Revision.

They must not bind directly to Card Printing.

This preserves:

* traceability to exact Japanese text
* re-parsing after official text changes
* separate review of old and new interpretations
* one shared effect interpretation across equivalent printings

Effect records must preserve `text_revision_id`, `raw_text_hash`, parser version, and review status.

## 5. Validation Invariants

The storage contract must reject or flag:

* duplicate `card_code`
* duplicate full `card_id`
* Card Printing without a matching Gameplay Card or Card Set
* Member attributes on Live or Energy cards
* Live attributes on Member or Energy cards
* any type-specific attributes on Energy cards
* `heart0` used as a Member basic Heart
* required Heart rows on non-Live cards
* Special Blade Hearts on non-Live cards
* effect data without a matching text revision and raw text hash
* more than one current text revision for a Gameplay Card
* Deck Entry preferred printing belonging to another Gameplay Card
* Loveca Point entries bound to a Card Printing

Unknown source values must be preserved and marked for review rather than coerced into known enums.

## 6. Cross-Product Evidence

The v0.3 cross-product review provides the Phase 1 evidence baseline:

* 30 sampled Card Printings
* 30 distinct sampled `card_code` values
* 6 Card Sets
* 12 Member, 12 Live, and 6 Energy cards
* 11 sampled cards with official related-printing relationships
* confirmed separation of Member and Live attributes
* confirmed Energy absence of type-specific attributes
* confirmed `ALL1` and `スコア1` Special Blade Heart labels
* no unknown Heart or Special Blade Heart icon observed in the sample

Related printing IDs demonstrate that multiple `card_id` values may share one `card_code`, even when only one printing from that group is included in the 30-record sample.

## 7. Current SQLite Migration Boundary

The current SQLite schema is a prototype and is not the frozen storage contract.

Future migration planning must account for:

* current `cards.card_number` splitting into Gameplay Card `card_code` and Card Printing `card_id`
* current `cards.product_id` moving to Card Printing -> Card Set
* current `cards.raw_effect_text` moving to Card Text Revision
* current Member, Live, and Heart tables changing ownership from printing-level card IDs to Gameplay Card
* current effect tags moving from card rows to Card Text Revision
* current raw source rows becoming printing-level Source Observations
* current point restrictions resolving card numbers to Gameplay Card and versioned rule sets
* current `products` being replaced by Card Set for Phase 1

No migration or compatibility behavior is defined by this specification.

## 8. Dependencies

Depends on:

* [000 Card Database](000-card-database.spec.md)
* [016 Terminology Normalization](016-terminology-normalization.spec.md)
* [017 Public Release and Export Policy](017-public-release-and-export-policy.spec.md)

Informs:

* [001 Deck Analyzer](001-deck-analyzer.spec.md)
* [007 Effect DSL](007-effect-dsl.spec.md)
* [014 Data Importer](014-data-importer.spec.md)
* future database schema and migration specifications
