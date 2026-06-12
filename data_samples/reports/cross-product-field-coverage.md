# Cross-Product Field Coverage

* Parser version: `cardlist_spike_v0.3`
* Sampled cards: `30`

## Global Coverage

| field | extracted_count | missing_count | confidence | notes |
| --- | ---: | ---: | --- | --- |
| `card_code` | 30 | 0 | `high` | Derived gameplay identity. |
| `product_code` | 30 | 0 | `high` | Requested official expansion code. |
| `related_printing_ids` | 11 | 19 | `high` | Optional official related-printing links. |
| `card_id` | 30 | 0 | `high` | Direct official card-number field. |
| `name` | 30 | 0 | `high` | Direct official detail heading. |
| `card_type` | 30 | 0 | `high` | Direct official card-type field. |
| `product` | 30 | 0 | `high` | Direct official product field. |
| `rarity` | 30 | 0 | `high` | Direct official rarity field. |
| `member_attributes.cost` | 12 | 0 | `high` | Applicable only to Member cards. |
| `member_attributes.heart_by_color` | 11 | 1 | `high` | Applicable only to Member cards; requires at least one observed Heart value. |
| `member_attributes.blade` | 11 | 1 | `high` | Applicable only to Member cards. |
| `member_attributes.blade_heart_color` | 5 | 7 | `high` | Applicable only when the Member exposes a Blade Heart icon. |
| `live_attributes.score` | 12 | 0 | `high` | Applicable only to Live cards. |
| `live_attributes.required_heart_by_color` | 12 | 0 | `high` | Applicable only to Live cards; requires at least one observed requirement. |
| `live_attributes.blade_heart_color` | 9 | 3 | `high` | Applicable only when the Live card exposes a Blade Heart icon. |
| `live_attributes.special_blade_hearts` | 11 | 1 | `high` | Applicable only when the Live card exposes official special Blade Heart icons. |
| `raw_effect_text` | 20 | 4 | `medium` | Preserves visible Japanese text and inline official icon alt text. |
| `image_url` | 30 | 0 | `high` | Direct official card image URL. |
| `source_url` | 30 | 0 | `high` | Stable card-number search URL. |
| `fetched_at` | 30 | 0 | `high` | UTC fetch timestamp. |
| `parser_version` | 30 | 0 | `high` | Importer spike parser version. |
| `parse_notes` | 30 | 0 | `high` | Structured parser audit notes. |

## Core Coverage by Product

| product | records | card identity | card type | product | rarity | attributes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `BP01` | 5 | 5 | 5 | 5 | 5 | 5 |
| `BP03` | 5 | 5 | 5 | 5 | 5 | 5 |
| `BP06` | 5 | 5 | 5 | 5 | 5 | 5 |
| `PLSD01` | 5 | 5 | 5 | 5 | 5 | 5 |
| `HSSD01` | 5 | 5 | 5 | 5 | 5 | 5 |
| `PR` | 5 | 5 | 5 | 5 | 5 | 5 |
