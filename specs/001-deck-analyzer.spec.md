# 001 Deck Analyzer Specification

## 1. Purpose

This spec defines MVP requirements for Deck Analyzer effect usage.

It does not define UI, APIs, database schemas, or implementation code.

## 2. MVP Effect Strategy

Deck Analyzer MVP may rely on `effect_tags` and numeric card data.

It must not require all semantic effects to be fully executable.

Deck Analyzer must share card data, terminology, effect taxonomy, and Rule Engine validation assumptions with Battle Simulator. It must not implement an incompatible private rule model.

Deck entries must identify Gameplay Cards by `card_code`. Copy limits, card-type counts, Loveca Point totals, probability analysis, and simulation inputs operate on `card_code`, not full printing `card_id`.

A deck entry may optionally preserve `preferred_printing_id` for image or rarity display. The preferred printing must resolve to the same `card_code` and must not affect legality or analysis results.

Analyzer reports should distinguish:

* structural card facts
* tag-based effect heuristics
* modeled DSL effects
* reviewed executable effects
* unsupported or manual effects

## 3. Required Effect Tags

Deck Analyzer should understand these initial tags:

* `draw`
* `search`
* `energy_boost`
* `cost_reduce`
* `live_support`
* `heart_gain`
* `blade_gain`
* `score_boost`

Deck legality analysis must include official construction limits once source-confirmed:

* main deck: exactly 48 Member cards and exactly 12 Live cards
* Energy deck: exactly 12 Energy cards
* same card number copy limit: no more than 4 copies unless an official construction replacement effect applies
* Loveca point-system total: restricted-card point total must be 9 or lower for applicable official formats
* `recycle`
* `starter`
* `consistency`
* `finisher`
* `manual_complexity`
* `requires_choice`

## 4. Analyzer Behavior

Deck Analyzer may use tags for:

* search filters
* deck summaries
* consistency heuristics
* weakness detection
* improvement suggestions
* Simple AI card-priority hints

Analyzer output must not imply that `tagged_only` effects are automatically executable.

## 5. Dependencies

Depends on:

* [000-card-database.spec.md](000-card-database.spec.md)
* [002-rule-engine.spec.md](002-rule-engine.spec.md)
* [015-effect-taxonomy.spec.md](015-effect-taxonomy.spec.md)
* [016-terminology-normalization.spec.md](016-terminology-normalization.spec.md)
* [018-card-data-storage.spec.md](018-card-data-storage.spec.md)

## 6. Out of Scope

This spec does not require:

* full Effect DSL coverage
* effect execution
* UI implementation
* automatic card effect parsing
