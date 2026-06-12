# Cross-Product Coverage Report

## Summary

* Status: `sample_completed`
* Source: `https://llofficial-cardgame.com/cardlist/`
* Parser version: `cardlist_spike_v0.3`
* Requested cards: `30`
* Sampled cards: `30`
* Products: `BP01`, `BP03`, `BP06`, `PLSD01`, `HSSD01`, `PR`

## Product and Card-Type Matrix

| product | sampled | Member | Live | Energy | core complete |
| --- | ---: | ---: | ---: | ---: | ---: |
| `BP01` | 5 | 2 | 2 | 1 | 5 |
| `BP03` | 5 | 2 | 2 | 1 | 5 |
| `BP06` | 5 | 2 | 2 | 1 | 5 |
| `PLSD01` | 5 | 2 | 2 | 1 | 5 |
| `HSSD01` | 5 | 2 | 2 | 1 | 5 |
| `PR` | 5 | 2 | 2 | 1 | 5 |

## Bucket Results

| product | kind | requested | attempted | successful | detail errors | type mismatches | page 2 used | error |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `BP01` | `member` | 2 | 2 | 2 | 0 | 0 | `false` | - |
| `BP01` | `live` | 2 | 2 | 2 | 0 | 0 | `false` | - |
| `BP01` | `energy` | 1 | 1 | 1 | 0 | 0 | `false` | - |
| `BP03` | `member` | 2 | 2 | 2 | 0 | 0 | `false` | - |
| `BP03` | `live` | 2 | 2 | 2 | 0 | 0 | `false` | - |
| `BP03` | `energy` | 1 | 1 | 1 | 0 | 0 | `false` | - |
| `BP06` | `member` | 2 | 2 | 2 | 0 | 0 | `false` | - |
| `BP06` | `live` | 2 | 2 | 2 | 0 | 0 | `false` | - |
| `BP06` | `energy` | 1 | 1 | 1 | 0 | 0 | `false` | - |
| `PLSD01` | `member` | 2 | 2 | 2 | 0 | 0 | `false` | - |
| `PLSD01` | `live` | 2 | 2 | 2 | 0 | 0 | `false` | - |
| `PLSD01` | `energy` | 1 | 1 | 1 | 0 | 0 | `false` | - |
| `HSSD01` | `member` | 2 | 2 | 2 | 0 | 0 | `false` | - |
| `HSSD01` | `live` | 2 | 2 | 2 | 0 | 0 | `false` | - |
| `HSSD01` | `energy` | 1 | 1 | 1 | 0 | 0 | `false` | - |
| `PR` | `member` | 2 | 2 | 2 | 0 | 0 | `false` | - |
| `PR` | `live` | 2 | 2 | 2 | 0 | 0 | `false` | - |
| `PR` | `energy` | 1 | 1 | 1 | 0 | 0 | `false` | - |

## Card-Type Field Boundaries

| field group | Member | Live | Energy |
| --- | --- | --- | --- |
| Cost, basic Heart, Blade | observed | not emitted | not emitted |
| Score, required Heart | not emitted | observed | not emitted |
| Special Blade Hearts | not emitted | observed when present | not emitted |
| Type-specific attributes | Member attributes | Live attributes | none |

## Special Blade Heart Coverage

| normalized type | official label family | observed | labels | review status |
| --- | --- | ---: | --- | --- |
| `all_color` | `ALLn` | 9 | `ALL1` | `source_confirmed` |
| `draw` | `ドローn` | 0 | - | `not_observed` |
| `score` | `スコアn` | 2 | `スコア1` | `source_confirmed` |
| `unknown` | `other` | 0 | - | `none_observed` |

## Printing Relationships

* `LL-E-002`: `LL-E-002-PR`, `LL-E-002-SD`
* `PL!-bp3-001`: `PL!-bp3-001-P`, `PL!-bp3-001-R`
* `PL!-bp3-002`: `PL!-bp3-002-P`, `PL!-bp3-002-R`
* `PL!-bp3-012`: `PL!-bp3-012-N`, `PL!-bp3-012-PR`, `PL!-bp3-012-RM`
* `PL!-bp3-014`: `PL!-bp3-014-N`, `PL!-bp3-014-PR`
* `PL!-bp3-020`: `PL!-bp3-020-L`, `PL!-bp3-020-L＋`, `PL!-bp3-020-SECL`
* `PL!-bp4-022`: `PL!-bp4-022-L`, `PL!-bp4-022-SECL`
* `PL!-bp6-001`: `PL!-bp6-001-P`, `PL!-bp6-001-P＋`, `PL!-bp6-001-R＋`, `PL!-bp6-001-SEC`
* `PL!-bp6-002`: `PL!-bp6-002-P`, `PL!-bp6-002-R`
* `PL!HS-sd1-018`: `PL!HS-sd1-018-SD`, `PL!HS-sd1-018-SECL`
* `PL!N-bp1-001`: `PL!N-bp1-001-P`, `PL!N-bp1-001-R`

## HTML Structure by Product

| product | observed official detail labels |
| --- | --- |
| `BP01` | `カードタイプ`, `カード番号`, `コスト`, `スコア`, `ブレード`, `ブレードハート`, `レアリティ`, `作品名`, `参加ユニット`, `収録商品`, `基本ハート`, `必要ハート` |
| `BP03` | `カードタイプ`, `カード番号`, `コスト`, `スコア`, `ブレード`, `ブレードハート`, `レアリティ`, `作品名`, `参加ユニット`, `収録商品`, `基本ハート`, `必要ハート`, `特殊ハート` |
| `BP06` | `カードタイプ`, `カード番号`, `コスト`, `スコア`, `ブレード`, `ブレードハート`, `レアリティ`, `作品名`, `参加ユニット`, `収録商品`, `基本ハート`, `必要ハート`, `特殊ハート` |
| `PLSD01` | `カードタイプ`, `カード番号`, `コスト`, `スコア`, `ブレード`, `ブレードハート`, `レアリティ`, `作品名`, `参加ユニット`, `収録商品`, `基本ハート`, `必要ハート`, `特殊ハート` |
| `HSSD01` | `カードタイプ`, `カード番号`, `コスト`, `スコア`, `ブレード`, `ブレードハート`, `レアリティ`, `作品名`, `参加ユニット`, `収録商品`, `基本ハート`, `必要ハート` |
| `PR` | `カードタイプ`, `カード番号`, `コスト`, `スコア`, `ブレード`, `ブレードハート`, `レアリティ`, `作品名`, `参加ユニット`, `収録商品`, `基本ハート`, `必要ハート` |

## Unmapped Source Data

* Detail labels: `作品名`, `参加ユニット`
* No unmapped Heart or Blade Heart icon was observed.

## Pages Inspected

* `card_list` `200` https://llofficial-cardgame.com/cardlist/
* `search_bp01_member` `200` https://llofficial-cardgame.com/cardlist/searchresults/?title=BP01&card_kind=M
* `detail_bp01_member_01` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816810925
* `detail_bp01_member_02` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816812320
* `search_bp01_live` `200` https://llofficial-cardgame.com/cardlist/searchresults/?title=BP01&card_kind=L
* `detail_bp01_live_01` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816815246
* `detail_bp01_live_02` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816816580
* `search_bp01_energy` `200` https://llofficial-cardgame.com/cardlist/searchresults/?title=BP01&card_kind=E
* `detail_bp01_energy_01` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816819170
* `search_bp03_member` `200` https://llofficial-cardgame.com/cardlist/searchresults/?title=BP03&card_kind=M
* `detail_bp03_member_01` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816821863
* `detail_bp03_member_02` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816823237
* `search_bp03_live` `200` https://llofficial-cardgame.com/cardlist/searchresults/?title=BP03&card_kind=L
* `detail_bp03_live_01` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816825971
* `detail_bp03_live_02` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816827308
* `search_bp03_energy` `200` https://llofficial-cardgame.com/cardlist/searchresults/?title=BP03&card_kind=E
* `detail_bp03_energy_01` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816829857
* `search_bp06_member` `200` https://llofficial-cardgame.com/cardlist/searchresults/?title=BP06&card_kind=M
* `detail_bp06_member_01` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816832445
* `detail_bp06_member_02` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816833822
* `search_bp06_live` `200` https://llofficial-cardgame.com/cardlist/searchresults/?title=BP06&card_kind=L
* `detail_bp06_live_01` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816836534
* `detail_bp06_live_02` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816837942
* `search_bp06_energy` `200` https://llofficial-cardgame.com/cardlist/searchresults/?title=BP06&card_kind=E
* `detail_bp06_energy_01` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816840581
* `search_plsd01_member` `200` https://llofficial-cardgame.com/cardlist/searchresults/?title=PLSD01&card_kind=M
* `detail_plsd01_member_01` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816843280
* `detail_plsd01_member_02` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816844635
* `search_plsd01_live` `200` https://llofficial-cardgame.com/cardlist/searchresults/?title=PLSD01&card_kind=L
* `detail_plsd01_live_01` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816847219
* `detail_plsd01_live_02` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816848573
* `search_plsd01_energy` `200` https://llofficial-cardgame.com/cardlist/searchresults/?title=PLSD01&card_kind=E
* `detail_plsd01_energy_01` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816852208
* `search_hssd01_member` `200` https://llofficial-cardgame.com/cardlist/searchresults/?title=HSSD01&card_kind=M
* `detail_hssd01_member_01` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816854896
* `detail_hssd01_member_02` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816856389
* `search_hssd01_live` `200` https://llofficial-cardgame.com/cardlist/searchresults/?title=HSSD01&card_kind=L
* `detail_hssd01_live_01` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816860574
* `detail_hssd01_live_02` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816863115
* `search_hssd01_energy` `200` https://llofficial-cardgame.com/cardlist/searchresults/?title=HSSD01&card_kind=E
* `detail_hssd01_energy_01` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816865826
* `search_pr_member` `200` https://llofficial-cardgame.com/cardlist/searchresults/?title=PR&card_kind=M
* `detail_pr_member_01` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816868543
* `detail_pr_member_02` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816869897
* `search_pr_live` `200` https://llofficial-cardgame.com/cardlist/searchresults/?title=PR&card_kind=L
* `detail_pr_live_01` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816872638
* `detail_pr_live_02` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816874022
* `search_pr_energy` `200` https://llofficial-cardgame.com/cardlist/searchresults/?title=PR&card_kind=E
* `detail_pr_energy_01` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780816876627

## Raw Files Written

* `data_samples\raw\cross-product\cardlist.html`
* `data_samples\raw\cross-product\bp01-member-search.html`
* `data_samples\raw\cross-product\bp01-member-detail.html`
* `data_samples\raw\cross-product\bp01-live-search.html`
* `data_samples\raw\cross-product\bp01-live-detail.html`
* `data_samples\raw\cross-product\bp01-energy-search.html`
* `data_samples\raw\cross-product\bp01-energy-detail.html`
* `data_samples\raw\cross-product\bp03-member-search.html`
* `data_samples\raw\cross-product\bp03-member-detail.html`
* `data_samples\raw\cross-product\bp03-live-search.html`
* `data_samples\raw\cross-product\bp03-live-detail.html`
* `data_samples\raw\cross-product\bp03-energy-search.html`
* `data_samples\raw\cross-product\bp03-energy-detail.html`
* `data_samples\raw\cross-product\bp06-member-search.html`
* `data_samples\raw\cross-product\bp06-member-detail.html`
* `data_samples\raw\cross-product\bp06-live-search.html`
* `data_samples\raw\cross-product\bp06-live-detail.html`
* `data_samples\raw\cross-product\bp06-energy-search.html`
* `data_samples\raw\cross-product\bp06-energy-detail.html`
* `data_samples\raw\cross-product\plsd01-member-search.html`
* `data_samples\raw\cross-product\plsd01-member-detail.html`
* `data_samples\raw\cross-product\plsd01-live-search.html`
* `data_samples\raw\cross-product\plsd01-live-detail.html`
* `data_samples\raw\cross-product\plsd01-energy-search.html`
* `data_samples\raw\cross-product\plsd01-energy-detail.html`
* `data_samples\raw\cross-product\hssd01-member-search.html`
* `data_samples\raw\cross-product\hssd01-member-detail.html`
* `data_samples\raw\cross-product\hssd01-live-search.html`
* `data_samples\raw\cross-product\hssd01-live-detail.html`
* `data_samples\raw\cross-product\hssd01-energy-search.html`
* `data_samples\raw\cross-product\hssd01-energy-detail.html`
* `data_samples\raw\cross-product\pr-member-search.html`
* `data_samples\raw\cross-product\pr-member-detail.html`
* `data_samples\raw\cross-product\pr-live-search.html`
* `data_samples\raw\cross-product\pr-live-detail.html`
* `data_samples\raw\cross-product\pr-energy-search.html`
* `data_samples\raw\cross-product\pr-energy-detail.html`

## Data-Model Recommendations

* Add a stable gameplay `card_code` separate from full printing `card_id`.
* Preserve product code, rarity, image, and related printing IDs as printing-level metadata.
* Keep Member, Live, and Energy type-specific boundaries already documented.
* Keep repeatable special Blade Hearts separate from free-form effect text.
* Defer fields that remain unmapped or appear in only one source generation until their official semantics are reviewed.

## Recommended Next Step

* Use this coverage set to freeze the Phase 1 conceptual schema and production importer contract; do not start a full import yet.
