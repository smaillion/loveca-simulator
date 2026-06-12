# Source Review Status

## Purpose

This file records the current source-review status for official Love Live! Series Official Card Game sources used by terminology and MVP rule-subset planning.

It is a review artifact only. It does not store bulk official text, card images, scraper output, or implementation data.

## Access Notes

Direct HTTP checks on 2026-06-07 JST confirmed successful access to the official root, Card List, Rule/Q&A page, beginner guide, deck recipes, and current comprehensive rules PDF.

## Reviewed Official Sources

| source_id | URL | intended use | current status | notes |
| --- | --- | --- | --- | --- |
| `official_root` | `https://llofficial-cardgame.com/` | root official source | `direct_confirmed` | HTTP 200 confirmed on 2026-06-07 JST. |
| `rule_qa` | `https://llofficial-cardgame.com/rule/` | rules, FAQ, rulings | `direct_confirmed` | HTTP 200 confirmed on 2026-06-07 JST. |
| `beginner_guide` | `https://llofficial-cardgame.com/for-beginners/` | beginner-facing core flow and terminology | `direct_confirmed` | HTTP 200 confirmed on 2026-06-07 JST. |
| `card_list` | `https://llofficial-cardgame.com/cardlist/` | card types, effect text patterns, terminology examples | `direct_confirmed` | HTTP 200 and importer spike access confirmed on 2026-06-07 JST. |
| `deck_recipe` | `https://llofficial-cardgame.com/deckrecipe/` | sample deck construction and environment references | `direct_confirmed` | HTTP 200 confirmed on 2026-06-07 JST. |
| `rule_pdf_1_06` | `https://llofficial-cardgame.com/wordpress/wp-content/uploads/2026/04/28140005/LoveLiveTCG_cr_1.06_260428.pdf` | comprehensive rules | `direct_confirmed` | HTTP 200 `application/pdf` confirmed on 2026-06-07 JST. |
| `quick_manual_mus` | `https://llofficial-cardgame.com/wordpress/wp-content/uploads/2025/09/04114714/L_TCG_-Manuel_%CE%BCs.pdf` | special Blade Heart and quick rules | `direct_confirmed` | Image-based PDF reviewed with PyMuPDF rendering. |

## Status Values

* `direct_confirmed`: direct official URL access succeeded and the source was inspected.
* `indexed_confirmed`: official source content is visible through search index and suitable for planning references.
* `access_limited`: direct access failed from the current environment; do not mark detailed terms as source-confirmed from this source alone.
* `source_review_required`: source is known but not yet reviewed.
