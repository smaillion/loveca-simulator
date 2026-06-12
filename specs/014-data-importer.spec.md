# 014 Data Importer Specification

## 1. Purpose

This spec defines source and parsing requirements for importing card and effect data.

It does not define scraper code, database schema, migrations, APIs, or implementation classes.

## 2. Source Requirements

The importer must preserve official Japanese source text.

Imported records should preserve:

* source URL
* source version
* fetched timestamp
* parser version
* language
* gameplay `card_code`
* complete printing `card_id`
* raw Japanese card effect text when present

The importer must emit or make derivable two identity layers:

* Gameplay Card for shared rule data
* Card Printing for rarity, image, Card Set, and source observations

Official card-list query groupings such as `BP01` and `PR` normalize to Card Set. The detail-page `収録商品` value must be preserved as raw Japanese source data and must not be promoted automatically to a normalized Product entity.

The importer must reject or flag cases where multiple printings with one `card_code` expose conflicting canonical name, card type, rule attributes, or official text. It must not silently choose one printing as authoritative.

Card attribute import must preserve card-type-specific boundaries and Heart color distinctions when the official source exposes them. The importer must not collapse color-specific Heart requirements into only a single aggregate Heart value.

Importer output should distinguish:

* shared card identity and source/audit fields
* Member-specific fields, including cost, Blade, Blade Heart color, and basic Heart values by official color slot
* Live-specific fields, including required Heart values by official color slot, score, Blade Heart color, and repeatable special Blade Heart entries when present
* Energy cards with no special type-specific attribute object

Official source identifiers such as `heart01`, `req_heart01`, `heart0`, and `blade_heart` may be stored as source-derived color slots until terminology normalization assigns canonical names.

Required Heart values are Live-specific and should not be emitted as Member or Energy attributes. `heart0` represents an any-color Heart slot and should be emitted only for Live required Heart or official all-color Blade Heart icons.

Blade and Penlight should not be imported as separate concepts unless official source review later proves a distinction. The importer should normalize them to the project concept `blade`, while preserving the official Japanese source term where available. The `blade` value is a Member attribute used for Yell reveal count; Live cards should not emit `blade` unless future official source review proves a distinct Live numeric field.

The official card detail field `特殊ハート` and the quick-manual term `特別なブレードハート` refer to Live-card-specific Blade Heart effects that activate when revealed by Yell. The importer should preserve them as `special_blade_hearts`, separate from normal Blade Heart color and `raw_effect_text`.

For exact official image labels, the spike may normalize:

* `ALLn` to `all_color`
* `ドローn` to `draw`
* `スコアn` to `score`

Each normalized entry must preserve the source `alt` label, official HTML source field, and numeric value. Because official HTML currently exposes `ALLn` under `ブレードハート` while exposing Draw and Score under `特殊ハート`, importer provenance must retain that distinction. An ALL entry may also project to `blade_heart_color = heart0`. Unknown labels must remain `unknown` with the original source label and must not be guessed or converted into Effect DSL.

The importer should not emit a generic `live_requirement` field unless source review identifies a separate official field beyond required Heart and score.

The importer should preserve official `作品名` and `参加ユニット` labels and emit normalization candidates for Work and Unit associations. Tokenization into multiple entities requires a reviewed terminology mapping; raw combined Japanese labels must never be discarded.

Importer design must also support importing official point-system restriction data as deck legality metadata. Point values must bind `card_code` under a versioned rule set and must not be treated as printing data or card score.

## 3. Text Revision Import

Raw Japanese effect text must be normalized into Card Text Revisions owned by Gameplay Card.

The importer must:

* calculate a stable `raw_text_hash`
* reuse an existing revision when `card_code` and hash match
* create a new provisional revision when official text changes
* retain the Printing and Source Observation that exposed the text
* avoid duplicating effect interpretations for equivalent printings

An Energy card or a card without official effect text may have no text revision.

## 4. Effect Parsing Layers

Importer design must support:

1. `raw_effect_text`
2. `effect_tags`
3. structured Effect DSL draft
4. executable implementation status

Raw text preservation is mandatory. Tags and DSL drafts are derived data.

Effect tags and Effect DSL drafts must reference the Card Text Revision that supplied their Japanese source text.

## 5. LLM-Assisted Parsing Policy

LLM-assisted parsing may be used to generate initial effect tags and DSL drafts.

LLM output must not be considered authoritative.

The importer or parsing workflow must preserve:

* `parse_confidence`
* `parser_version`
* `raw_text_hash`
* `review_status`

A card effect must not become `reviewed_executable` without human review. Automated rule-test validation alone is not enough.

Automated rule-test validation may support `test_validated_executable`, but human review is required for `reviewed_executable`.

## 6. Recommended Pipeline

```text
Official raw text
-> Card Text Revision
-> LLM-assisted draft parse
-> effect_tags
-> Effect DSL draft
-> schema validation
-> rule validation
-> test_validated_executable, when automated rule tests cover behavior
-> manual review
-> reviewed_executable effect
```

This pipeline is conceptual and may be refined by future implementation specs.

## 7. Auditability

Effect parsing must be auditable and re-runnable.

The system should be able to compare a current DSL draft against the raw text hash and parser version that produced it.

## 8. Dependencies

Depends on:

* [000-card-database.spec.md](000-card-database.spec.md)
* [015-effect-taxonomy.spec.md](015-effect-taxonomy.spec.md)
* [016-terminology-normalization.spec.md](016-terminology-normalization.spec.md)
* [017-public-release-and-export-policy.spec.md](017-public-release-and-export-policy.spec.md)
* [018-card-data-storage.spec.md](018-card-data-storage.spec.md)
