# Source and Data Policy

## 1. Purpose

This document defines how the project treats official sources, imported card data, rule data, copyright-sensitive content, and future updates.

The policy applies to both first-class products:

* Deck Analyzer
* Battle Simulator

Both products must use the same source-of-truth policy so that analysis and simulation do not diverge.

## 2. Official Source Priority

Official sources are the source of truth when available.

Primary sources:

* Official Love Live! Series Official Card Game website
* Official card database
* Official comprehensive rules PDF
* Official beginner guide
* Official FAQ / Q&A
* Official deck recipe pages
* Bushiroad Deck Log, if deck data is needed

No unofficial source should override official data when official data exists.

Unofficial or community-maintained sources may be useful for comparison, convenience, or missing context, but they should be clearly marked and should not silently replace official data.

## 3. Language of Record

Love Live! Series Official Card Game source material is primarily Japanese.

All card and rule data should be stored in Japanese as the canonical record, including:

* card names
* card types when sourced from official text
* raw effect text
* Live requirements
* rule text
* FAQ / Q&A text
* official ruling references

Translations may be added later as derived convenience data, but they must not replace Japanese source fields. When both Japanese and translated values exist, Japanese fields are authoritative for validation, rules modeling, and effect modeling.

## 4. Import Version Tracking

Every imported Gameplay Card, Card Printing, Card Set, or source observation should support source tracking.

Expected import metadata:

* source_url
* source_version
* fetched_at
* parser_version
* language

The project should be able to answer:

* where a record came from
* when it was fetched
* what source version it represented
* what importer or parser version produced it
* whether the record was created from Japanese official data

This supports reproducibility, auditing, parser improvements, and correction of bad imports.

## 5. Rule Version Tracking

Rules may change over time through updated comprehensive rules, beginner guides, FAQs, rulings, or errata.

Rule-related data should support:

* official_rule_version
* release_date
* imported_at
* source_url
* source_version
* language

Deck validation, action validation, and effect behavior should eventually be able to identify which rule version was used.

## 6. Local Use vs Public Release

The project may store complete official card information for local personal use.

Public release needs additional caution. Documentation, tooling, and exported data should distinguish local private data from redistributable metadata.

### Safe or Lower-Risk Local Data

The following may be stored locally for personal use:

* card number
* Japanese card name
* card type
* card set code
* cost
* Heart / color information
* Blade value
* Japanese raw effect text
* card image URL
* official source URL

### Caution for Public Release

The following require caution before public redistribution:

* full card images
* full official PDF text
* full card effect text
* bulk redistribution of official data

For public release, prefer:

* normalized metadata
* derived tags
* user-owned deck data
* links to official sources
* optional local importer

### Local Bootstrap Asset Packages

The project may provide a simplified local initialization path through downloadable asset packages.

Technically, a user should eventually be able to install the application, download a versioned local asset package, verify it, and run the simulator without manually importing every card.

However, public CDN distribution must respect the local-use vs public-release boundary:

* application binaries, source code, schemas, import tools, manifests, checksums, and project-owned metadata are suitable for public static distribution
* user-owned deck files are local user data and should not be uploaded to a project CDN
* bulk official card images, full official effect text, full official PDF text, and other copyright-sensitive official assets require explicit redistribution review before public CDN packaging
* if redistribution rights are unclear, prefer an installer or importer that builds the local cache from official sources on the user's machine
* private tester packages may be considered separately, but they must be clearly labeled as local-use review artifacts and not treated as public datasets

A CDN package should be a static bootstrap artifact, not a cloud data service. It should not introduce accounts, user tracking, cloud deck storage, or server-side rule validation.

## 7. Update Strategy

Card data and rules may change over time.

The architecture should support:

* new card releases
* new Card Sets and printings
* rule version changes
* errata
* FAQ and ruling updates
* parser improvements
* manual correction of imported records

Updates should be reproducible. The system should not require deleting history or losing source context when a card, rule, or parser changes.

## 8. Validation Strategy

Imported data should be validated before it is treated as reliable.

Validation should cover:

* expected card count per Card Set
* `card_code` and full `card_id` uniqueness
* valid card type
* valid group or series when known
* valid cost range
* valid Live required Heart and score format
* valid Energy deck constraints
* Japanese source fields being present where official text is stored
* required source metadata

Validation results should be explicit and reviewable. A partially successful import should not silently hide invalid records.

## 9. Manual Review Strategy

Manual review is required for ambiguous or high-risk data.

Areas that need manual review include:

* card effect interpretation
* effect tags
* structured effect modeling
* FAQ or ruling interpretation
* rule edge cases
* parser behavior after official site changes

The system should never assume that machine-parsed effect data is fully correct without review.

Raw Japanese effect text and structured effect data must remain separate so manual correction can improve structured data without altering the source record.

Raw effect text history should be preserved as immutable Card Text Revisions. Derived tags and Effect DSL records must identify the revision and raw text hash they interpret.

## 10. Effect Modeling Policy

Semantic card effects must be modeled in separate layers:

* raw_effect_text
* effect_tags
* structured Effect DSL
* executable effect implementation

Raw Japanese official text is always the canonical source record. Effect tags, structured effects, and executable behavior are derived interpretations.

Every effect should have a simulation support status:

* unsupported
* tagged_only
* manual_resolution
* partially_executable
* fully_executable
* test_validated_executable
* reviewed_executable

The simulator should not auto-resolve unsupported, tagged-only, or manual-resolution effects. Deck analysis may use effect tags, but it should distinguish tag-based heuristics from executable or reviewed effect behavior.

`reviewed_executable` requires human review. Automated rule-test validation alone may support `test_validated_executable`, but it is not enough for reviewed status.

Detailed public export rules are owned by [017-public-release-and-export-policy.spec.md](../specs/017-public-release-and-export-policy.spec.md).
