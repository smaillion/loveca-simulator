# 000 Card Database Specification

## 1. Purpose

This spec defines conceptual requirements for card data storage and ownership.

It does not define database tables, migrations, SQL, APIs, scraper code, or implementation classes.

## 2. Scope

The card database foundation must support both:

* Deck Analyzer
* Battle Simulator

It must preserve Japanese official source data and provide normalized, versioned concepts for later specifications.

## 3. Source Data Requirements

Card records must preserve:

* official source URL
* source version
* fetch timestamp
* parser version
* language
* stable gameplay `card_code`
* complete printing `card_id`
* canonical Japanese card name
* canonical Japanese raw effect text when present

Official Japanese source data is authoritative. Translations are derived convenience data only.

## 4. Card Identity Requirements

Card data must distinguish:

* Gameplay Card, identified by `card_code`
* Card Printing, identified by complete official `card_id`

Gameplay Card owns rule identity, canonical Japanese name, card type, type-specific attributes, Heart values, official text revision history, Work and Unit associations, and deck legality restrictions.

Card Printing owns rarity, image reference, Card Set membership, and printing-level source observations.

Multiple Card Printings may reference the same Gameplay Card. Equivalent printings must not duplicate rule attributes, effect tags, Effect DSL, or executable behavior.

Card Set represents official card-list groupings such as `BP01`, `PLSD01`, or `PR`. The official `収録商品` text remains a raw source observation in Phase 1 and must not be treated as a normalized Product foreign key.

The detailed logical storage contract is owned by [018-card-data-storage.spec.md](018-card-data-storage.spec.md).

## 5. Card Type and Attribute Requirements

Card data should separate shared card identity from card-type-specific attributes.

Gameplay Card includes canonical Japanese name, card type, rule attributes, and official text revision history. Printing rarity, image, Card Set, and source observations belong to Card Printing.

Member, Live, and Energy cards have different attribute surfaces and should not force unrelated nullable fields onto every card record.

The conceptual model must support:

* Member-specific attributes, including cost, Blade, Blade Heart color, and basic Heart values by official color slot
* Live-specific attributes, including required Heart values by official color slot, score, Blade Heart color, and repeatable special Blade Heart entries when present
* Energy cards as ordinary card identities with no special card-specific attributes
* source references for the official color identifiers used during import

Importer spikes currently identify official search parameters such as `heart01` through `heart06`, `req_heart01` through `req_heart06`, `heart0`, and `blade_heart`. These identifiers must be treated as source-derived color slots until terminology review confirms display names and canonical internal names.

Required Heart values are Live-specific. Member cards should not expose required Heart fields except through generic source payloads or review notes. `heart0` represents an any-color Heart slot and should be used only for Live required Heart or official Blade Heart icons that explicitly represent all colors.

Energy cards should not expose Blade, Blade Heart, Penlight, Heart, score, cost, or Live-specific fields. Under the current MVP understanding, an Energy card functions as one Energy card for payment and readiness purposes.

Blade and Penlight refer to the same project concept for modeling purposes. The canonical internal field should use `blade`, because `ブレード` is the official Japanese term visible in official sources. `blade` is the Member value that determines how many cards are revealed during Yell. Blade Heart color is separate from `blade` and may appear in official card data for Member or Live cards.

Special Blade Hearts are Live-card-specific rule attributes. They activate when the Live card is revealed by Yell and must be stored separately from free-form card effect text. Each entry should preserve the exact official icon label, official HTML source field, normalized effect type, and numeric value. Confirmed types include any-color Heart, draw-after-Yell, and score-at-Live-judgment. For analyzer convenience, an ALL Blade Heart may also project to `blade_heart_color = heart0`; that projection must not erase the structured special Blade Heart entry.

There should not be a generic `live_requirement` field unless official source review identifies a separate field beyond required Heart and score. For now, Live requirements should be modeled as required Heart by color plus any raw official text/effect text.

The card database foundation must also support official deck legality restriction data, including Loveca point-system values. Point restrictions bind Gameplay Card under a versioned rule set. They must not bind Card Printing and must not be confused with Live `score`.

## 6. Effect Data Requirements

The card database design must support the four effect layers:

1. `raw_effect_text`
2. `effect_tags`
3. structured Effect DSL
4. executable effect implementation

Raw text must be preserved independently from tags, DSL drafts, and executable behavior.

Official effect text belongs to a versioned Card Text Revision under Gameplay Card, not to Card Printing or Member/Live attribute records.

Effect tags, Effect DSL drafts, executable behavior, review records, and simulation support status must bind a specific `text_revision_id` and `raw_text_hash`. This allows equivalent printings to share one interpretation while preserving official text changes and errata.

Every modeled effect must support:

* simulation support status
* parse confidence
* review status
* parser version
* raw text hash

## 7. Effect Support Status Dependency

The card data model must support the statuses defined in [015-effect-taxonomy.spec.md](015-effect-taxonomy.spec.md):

* `unsupported`
* `tagged_only`
* `manual_resolution`
* `partially_executable`
* `fully_executable`
* `test_validated_executable`
* `reviewed_executable`

## 8. Validation Requirements

Validation must distinguish:

* source record validity
* Gameplay Card and Card Printing identity validity
* normalized card metadata validity
* Card Text Revision validity
* effect tag validity
* Effect DSL draft validity
* executable/review status validity

LLM-assisted parse output must not be treated as reviewed or authoritative. `reviewed_executable` requires human review; automated rule-test validation alone may only support `test_validated_executable`.

## 9. Out of Scope

This spec does not cover:

* SQL schema and physical storage types
* migrations
* scraping implementation
* effect execution
* UI
* online multiplayer storage

## 10. Related Specs

Related policy ownership:

* [016-terminology-normalization.spec.md](016-terminology-normalization.spec.md)
* [017-public-release-and-export-policy.spec.md](017-public-release-and-export-policy.spec.md)
* [018-card-data-storage.spec.md](018-card-data-storage.spec.md)
