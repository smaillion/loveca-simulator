# Official Rules Review

## Purpose

This artifact records source-review findings from locally saved official documents in `raw_doc/`.

It avoids bulk redistribution of official rule text. It records only concise findings, source paths, and modeling decisions.

## Sources Reviewed

| source_id | local path | official source type | reviewed status |
| --- | --- | --- | --- |
| `comprehensive_rules_1_06_local` | `raw_doc/LoveLiveTCG_cr_1.06_260428.pdf` | comprehensive rules PDF | `reviewed` |
| `quick_manual_mus` | `https://llofficial-cardgame.com/wordpress/wp-content/uploads/2025/09/04114714/L_TCG_-Manuel_%CE%BCs.pdf` | official quick manual PDF | `reviewed` |
| `loveca_point_system_local` | `raw_doc/カードの使用制限に関するルール 「ラブカポイントシステム」について _ ラブライブ！シリーズ　オフィシャルカードゲーム 公式サイト.html` | official point restriction page | `reviewed` |

The comprehensive rules text was extracted with `pypdf` 6.10.0. The μ's quick manual is a single-page image PDF with no extractable text layer, so it was visually reviewed from a PyMuPDF 1.27.2.3 page rendering.

## Confirmed Rule Findings

| finding_id | finding | modeling impact |
| --- | --- | --- |
| `card_types` | Official card types are Live, Member, and Energy. | `cards.card_type` remains the shared discriminator. |
| `member_fields` | Cost and basic Heart are Member card information. Blade is used by Members during Yell/Live processing. | Member attributes must support `cost`, `blade`, basic Heart by color, and Blade Heart color when present. |
| `live_fields` | Score and required Heart are Live card information. Some Live cards may expose Blade Heart icons or text, but the numeric `blade` value is the Member Yell reveal count. | Live attributes must support `score`, required Heart by color, and optional Blade Heart color. Live attributes should not expose `blade`. |
| `energy_fields` | Energy cards are used to pay costs and form the Energy Deck. They do not have the Member/Live numeric attribute surface. | Energy cards should not have a type-specific attribute table in the MVP model. |
| `deck_composition` | Main deck construction requires exactly 48 Member cards and exactly 12 Live cards. Energy deck construction requires exactly 12 Energy cards. | Deck legality must validate exact type counts separately for main deck and Energy deck. |
| `card_copy_limit` | Main deck cards with the same card number are limited to 4 copies unless official replacement effects change construction. | Deck legality must include card-number copy count validation. |
| `point_system_limit` | The Loveca point system assigns point values to listed restricted cards; decks using those cards must have total points no greater than 9. | Deck legality must include point-restriction validation sourced from official point-system data. |
| `effect_binding` | Card text is the official source for card abilities. | Raw effect text belongs to a Card Text Revision. Tags, DSL, and executable behavior bind to `card_code`, `text_revision_id`, and `raw_text_hash`, never to a printing `card_id` or Member/Live attribute record. |
| `heart_colors` | Comprehensive rules identify Heart colors as pink, red, yellow, green, blue, and purple, plus colorless and any-color icons. Official card-list HTML uses source slots observed as `heart01`, `heart02`, `heart03`, and `heart06`; the ordered rule color list supports `heart04` as green and `heart05` as blue for terminology review. | Heart data must preserve color slot identity. `heart0` represents any-color Heart and should be limited to Live required Heart or all-color Blade Heart icons. |
| `match_setup` | Setup includes main deck and Energy deck placement, main deck shuffle, opening hand draw, mulligan procedure, and moving the top Energy deck cards to the Energy area. | MVP setup can be modeled as deterministic setup actions once exact source-backed counts are documented in specs. |
| `turn_flow` | A turn contains first-player normal phase, second-player normal phase, and Live phase. Normal phases contain Active, Energy, Draw, and Main phases. Live phase contains Live card set, first-player performance, second-player performance, and Live win/loss judgment phases. | Rule model docs should use these official phase names as the confirmed terminology baseline. |
| `live_resolution` | Performance uses active Member Blade totals for Yell reveal count, checks Blade Heart icons on revealed cards, accumulates owned Hearts, checks each Live card's required Heart, then compares Live scores with Yell score contribution. | MVP simulator must keep Blade reveal count, Blade Heart color, required Heart, and Live score as separate concepts. |
| `special_blade_hearts` | The quick manual calls these `特別なブレードハート` and states that they activate when revealed by Yell. It documents ALL, Draw, and Score forms. ALL is treated as any Heart color during Live success judgment; Draw resolves after all Yell processing; Score adds to the score total during Live win/loss judgment. | Special Blade Hearts are Live-card-specific structured attributes, separate from raw card effects and normal Blade Heart color. Import must preserve the official icon `alt`, effect type, and numeric value without converting it into Effect DSL. |

## Corrections Applied

* Energy-specific attribute modeling was removed.
* Blade/Penlight was normalized to the project concept `blade`.
* Generic `live_requirement` modeling was removed; Live requirements are represented as required Heart by color plus score and raw/effect text.
* `blade` is limited to Member attributes. Blade Heart color may appear on Member or Live attributes when official card data exposes it.
* `heart0` was added for any-color required Heart and all-color Blade Heart icons.
* Live attributes may include repeatable `special_blade_hearts` entries for exact official icons such as `ドロー1` and `スコア1`.
* Card point restrictions are treated as deck legality data, separate from Live score.

## Open Follow-Up

* Decide whether point-system records should be grouped by text-equivalent card group or stored per card number with group notes.
* Confirm whether future products introduce additional special Blade Heart icon types or values.
* Add exact deck exhaustion and victory threshold handling after the relevant comprehensive-rule clauses are reviewed.
