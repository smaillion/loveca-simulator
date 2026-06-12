# Importer Spike Report

## Summary

* Status: `sample_completed`
* Source: `https://llofficial-cardgame.com/cardlist/`
* Parser version: `cardlist_spike_v0.3`
* Requested cards: `12`
* Sampled cards: `12`
* Card types: `5` Member, `5` Live, `2` Energy

## Pages Inspected

* `card_list` `200` https://llofficial-cardgame.com/cardlist/
* `card_search_results_member` `200` https://llofficial-cardgame.com/cardlist/searchresults/?card_kind=M
* `card_detail_member_001` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780814469166
* `card_detail_member_002` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780814470334
* `card_detail_member_003` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780814471519
* `card_detail_member_004` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780814472729
* `card_detail_member_005` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780814473930
* `card_search_results_live` `200` https://llofficial-cardgame.com/cardlist/searchresults/?card_kind=L
* `card_detail_live_001` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780814477473
* `card_detail_live_002` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780814478697
* `card_detail_live_003` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780814479987
* `card_detail_live_004` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780814481195
* `card_detail_live_005` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780814482364
* `card_search_results_energy` `200` https://llofficial-cardgame.com/cardlist/searchresults/?card_kind=E
* `card_detail_energy_001` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780814484973
* `card_detail_energy_002` `200` https://llofficial-cardgame.com/cardlist/detail/?t=1780814486175

## Data Extraction Method

* Loaded `sources.card_list.url` from `data_sources/source-manifest.yaml`.
* Used one cookie-aware official-site session for all requests.
* Fetched pages sequentially with a minimum one-second request interval.
* Requested separate official search result pages with `card_kind=M`, `card_kind=L`, and `card_kind=E`.
* Loaded card details through the official same-domain AJAX endpoint using `POST /cardlist/detail/` with form field `cardno`.
* Parsed official detail headings and `<dl>` fields. Preserved Japanese effect text and inline official image `alt` labels without Effect DSL parsing.

## Fields Successfully Extracted

* `card_id`: `12` extracted (`high` confidence)
* `name`: `12` extracted (`high` confidence)
* `card_type`: `12` extracted (`high` confidence)
* `product`: `12` extracted (`high` confidence)
* `rarity`: `12` extracted (`high` confidence)
* `member_attributes.cost`: `5` extracted (`high` confidence)
* `member_attributes.heart_by_color`: `5` extracted (`high` confidence)
* `member_attributes.blade`: `1` extracted (`high` confidence)
* `member_attributes.blade_heart_color`: `1` extracted (`high` confidence)
* `live_attributes.score`: `5` extracted (`high` confidence)
* `live_attributes.required_heart_by_color`: `5` extracted (`high` confidence)
* `live_attributes.blade_heart_color`: `3` extracted (`high` confidence)
* `live_attributes.special_blade_hearts`: `5` extracted (`high` confidence)
* `raw_effect_text`: `10` extracted (`medium` confidence)
* `image_url`: `12` extracted (`high` confidence)
* `source_url`: `12` extracted (`high` confidence)
* `fetched_at`: `12` extracted (`high` confidence)
* `parser_version`: `12` extracted (`high` confidence)
* `parse_notes`: `12` extracted (`high` confidence)

## Fields Missing or Unreliable

* `member_attributes.blade`: `4` missing - Applicable only to Member cards.
* `member_attributes.blade_heart_color`: `4` missing - Applicable only when the Member exposes a Blade Heart icon.
* `live_attributes.blade_heart_color`: `2` missing - Applicable only when the Live card exposes a Blade Heart icon.
* Unmapped official fields preserved in `parse_notes.unmapped_fields`: `作品名`, `参加ユニット`

## Pagination Behavior

* Initial search results expose an incremental same-domain endpoint: `/cardlist/cardsearch_ex?view=image&page=...`.
* This spike reads only the first result page for each card type.

## Search Result Page Behavior

* `https://llofficial-cardgame.com/cardlist/searchresults/`
* `https://llofficial-cardgame.com/cardlist/searchresults/?expansion=BP06`
* `https://llofficial-cardgame.com/cardlist/searchresults/?expansion=CLHS01`
* `https://llofficial-cardgame.com/cardlist/searchresults/?expansion=SPSD02`
* `https://llofficial-cardgame.com/cardlist/searchresults/?expansion=PBHS`
* `https://llofficial-cardgame.com/cardlist/searchresults/?expansion=BP05`
* `https://llofficial-cardgame.com/cardlist/searchresults/?expansion=HSSD01`
* `https://llofficial-cardgame.com/cardlist/searchresults/?expansion=SSD01`
* `https://llofficial-cardgame.com/cardlist/searchresults/?expansion=PBN`
* `https://llofficial-cardgame.com/cardlist/searchresults/?expansion=BP04`
* `https://llofficial-cardgame.com/cardlist/searchresults/?expansion=PBLL`
* `https://llofficial-cardgame.com/cardlist/searchresults/?expansion=BP03`
* `https://llofficial-cardgame.com/cardlist/searchresults/?expansion=PLSD01`
* `https://llofficial-cardgame.com/cardlist/searchresults/?expansion=PBLS`
* `https://llofficial-cardgame.com/cardlist/searchresults/?expansion=BP02`
* `https://llofficial-cardgame.com/cardlist/searchresults/?expansion=PBSP`
* `https://llofficial-cardgame.com/cardlist/searchresults/?expansion=BP01`
* `https://llofficial-cardgame.com/cardlist/searchresults/?expansion=NSD01`
* `https://llofficial-cardgame.com/cardlist/searchresults/?expansion=SPSD01`
* `https://llofficial-cardgame.com/cardlist/searchresults/?expansion=PR`
* `https://llofficial-cardgame.com/cardlist/searchresults/?card_kind=M&view=image&sort=new`
* `https://llofficial-cardgame.com/cardlist/searchresults/?card_kind=M&view=text&sort=new`
* `https://llofficial-cardgame.com/cardlist/searchresults/?card_kind=M&sort=`
* `https://llofficial-cardgame.com/cardlist/searchresults/?card_kind=M`
* `https://llofficial-cardgame.com/cardlist/searchresults/?cardno=`
* `https://llofficial-cardgame.com/cardlist/searchresults/?card_kind=L&view=image&sort=new`
* `https://llofficial-cardgame.com/cardlist/searchresults/?card_kind=L&view=text&sort=new`
* `https://llofficial-cardgame.com/cardlist/searchresults/?card_kind=L&sort=`
* `https://llofficial-cardgame.com/cardlist/searchresults/?card_kind=L`
* `https://llofficial-cardgame.com/cardlist/searchresults/?card_kind=E&view=image&sort=new`

## Detail Page Behavior

* Details are not independent stable pages. The official UI sends a cookie-aware AJAX POST to `/cardlist/detail/` with `cardno`.
* A direct POST without the search-page session may return HTTP 200 with an empty body, so the spike establishes the official session first.

## Hidden JSON or API Candidates

* Embedded JSON-like script blocks: `0`
* `https://llofficial-cardgame.com/system/app/cardlist/formApi/`
* `https://llofficial-cardgame.com/cardlist/cardsearch_ex?card_kind=M&view=image&page=`
* `https://llofficial-cardgame.com/cardlist/detail/?t=`
* `https://llofficial-cardgame.com/cardlist/cardsearch_ex?card_kind=L&view=image&page=`
* `https://llofficial-cardgame.com/cardlist/cardsearch_ex?card_kind=E&view=image&page=`

## Image URL Behavior

* `https://llofficial-cardgame.com/wordpress/wp-content/themes/llofficial-cardgame_v1/assets/images/common/apple-touch-icon.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/themes/llofficial-cardgame_v1/assets/images/common/logo.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/thumb/LLC_ BP06_box_image.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/thumb/LLC_binder_HS_image.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/thumb/LLC_SD04_BOX_image.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/thumb/L!_TCG_-PBP_06_box_image.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/thumb/L!_TCG_ BP_05_box_image.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/thumb/L!_TCG_SD03_BOX_image _02.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/thumb/L!_TCG_SD03_BOX_image _01.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/thumb/L!_TCG_ PBP_04_box_image.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/thumb/L!_TCG_ BP_04_box_image.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/thumb/L!_TCG_ PBP_03_box_image.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/thumb/L_TCG_BP_03_BOX_image.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/thumb/L!_TCG_SD02_BOX_image.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/thumb/L_TCG_PB_02_box_image.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/thumb/L_TCG_BP_02_BOX_image.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/thumb/L_TCG_PB_01_BOX_image.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/uploads/2024/12/28162156/L_TCG_-BP_vol1_box_image_250220.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/thumb/L_TCG_SD_02_BOX_image.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/thumb/L_TCG_SD_01_BOX_image.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/themes/llofficial-cardgame_v1/assets/images/common/common/thumb_default.jpg`
* `https://llofficial-cardgame.com/wordpress/wp-content/themes/llofficial-cardgame_v1/assets/images/common/footer/logo_bushiroad.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/uploads/2024/10/30103339/LLC_Web_RH_banner_2_01.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP06/PL!-bp6-001-R2.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP06/PL!-bp6-001-P.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP06/PL!-bp6-001-P2.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP06/PL!-bp6-001-SEC.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP06/PL!-bp6-002-R.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP06/PL!-bp6-002-P.png`
* `https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP06/PL!-bp6-003-R2.png`

## Raw Files Written

* `data_samples\raw\cardlist-sample.html`
* `data_samples\raw\card-searchresults-member.html`
* `data_samples\raw\card-detail-member-sample.html`
* `data_samples\raw\card-searchresults-live.html`
* `data_samples\raw\card-detail-live-sample.html`
* `data_samples\raw\card-searchresults-energy.html`
* `data_samples\raw\card-detail-energy-sample.html`

## Risks for Full Import

* Detail extraction depends on an undocumented AJAX HTML contract.
* Session or anti-automation behavior may change without notice.
* Some semantics are represented by image classes or `alt` text rather than text fields.
* Effect text does not expose guaranteed machine-readable separators.
* Special Blade Heart parsing currently recognizes only exact official `ALLn`, `ドローn`, and `スコアn` icon labels.
* Energy cards have no special attributes in this model; they should remain plain card identities used as one Energy card for payment.
* Detail-page and search pagination behavior must be confirmed across multiple products before schema decisions.
* Public exports must avoid redistributing bulk official text.

## Recommended Changes to specs/000-card-database.spec.md

* Keep the final schema deferred until the same fields are reviewed across multiple releases and rarities.
* Preserve `source_url`, `fetched_at`, `parser_version`, and raw Japanese effect text per card source record.
* Require type-specific Heart color fields: Member basic Heart and Live required Heart must not be collapsed into one scalar. Live required Heart must support the any-color slot `heart0`.
* Keep `blade` as a Member attribute. Allow Blade Heart color on Member and Live cards when the official card data exposes it. Energy cards remain attribute-less.
* Model repeatable Live-card special Blade Hearts separately from normal Blade Heart color and raw card effect text.
* Support Loveca point-system restriction data as separate deck legality metadata with a total deck point limit of 9.

## Recommended Changes to specs/014-data-importer.spec.md

* Document cookie-aware AJAX detail fetching as an observed source behavior.
* Require same-domain enforcement, conservative fetch limits, and partial reports.
* Preserve official Heart color source identifiers such as `heart01` through `heart06`, plus `heart0` for any-color requirements, until terminology normalization confirms canonical color names.
* Normalize Blade/Penlight to one project concept, `blade`, and emit it only for Member card attributes. Blade Heart color remains a separate card attribute when visible in official data.
* Parse exact `特殊ハート` image labels into Live-only `special_blade_hearts` while preserving the original `alt` value.
* Import point-system records separately from card list records; point values must not be confused with Live score.

## Recommended Next Implementation Step

* Review additional products for new special Blade Heart icon types before expanding source coverage or finalizing any database schema.
