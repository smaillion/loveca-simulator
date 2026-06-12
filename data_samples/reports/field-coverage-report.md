# Field Coverage Report

* Parser version: `cardlist_spike_v0.3`
* Sampled cards: `12`

| field | extracted_count | missing_count | confidence | notes |
| --- | ---: | ---: | --- | --- |
| `card_id` | 12 | 0 | `high` | Direct official card-number field. |
| `name` | 12 | 0 | `high` | Direct official detail heading. |
| `card_type` | 12 | 0 | `high` | Direct official card-type field. |
| `product` | 12 | 0 | `high` | Direct official product field. |
| `rarity` | 12 | 0 | `high` | Direct official rarity field. |
| `member_attributes.cost` | 5 | 0 | `high` | Applicable only to Member cards. |
| `member_attributes.heart_by_color` | 5 | 0 | `high` | Applicable only to Member cards; requires at least one observed Heart value. |
| `member_attributes.blade` | 1 | 4 | `high` | Applicable only to Member cards. |
| `member_attributes.blade_heart_color` | 1 | 4 | `high` | Applicable only when the Member exposes a Blade Heart icon. |
| `live_attributes.score` | 5 | 0 | `high` | Applicable only to Live cards. |
| `live_attributes.required_heart_by_color` | 5 | 0 | `high` | Applicable only to Live cards; requires at least one observed requirement. |
| `live_attributes.blade_heart_color` | 3 | 2 | `high` | Applicable only when the Live card exposes a Blade Heart icon. |
| `live_attributes.special_blade_hearts` | 5 | 0 | `high` | Applicable only when the Live card exposes official special Blade Heart icons. |
| `raw_effect_text` | 10 | 0 | `medium` | Preserves visible Japanese text and inline official icon alt text. |
| `image_url` | 12 | 0 | `high` | Direct official card image URL. |
| `source_url` | 12 | 0 | `high` | Stable card-number search URL. |
| `fetched_at` | 12 | 0 | `high` | UTC fetch timestamp. |
| `parser_version` | 12 | 0 | `high` | Importer spike parser version. |
| `parse_notes` | 12 | 0 | `high` | Structured parser audit notes. |
