# 017 Public Release and Export Policy Specification

## 1. Purpose

This spec owns local-vs-public data export policy, copyright-sensitive data handling, and public release restrictions.

It does not provide legal advice and does not define implementation code, database schema, API behavior, or UI.

## 2. Local vs Public Boundary

The project may support complete official card information for local personal use.

Public release, public exports, packaged datasets, and shared artifacts require stricter handling.

## 3. Lower-Risk Public Data

Public release should prefer:

* normalized metadata
* derived tags
* user-owned deck data
* links to official sources
* optional local importer
* source references without bulk official text

## 4. Copyright-Sensitive Data

The following require caution before public redistribution:

* full card images
* full official PDF text
* full card effect text
* bulk redistribution of official card data
* replay exports that embed large amounts of official text

## 5. Export Requirements

Any public-facing export workflow should distinguish:

* local/private export
* public/shareable export
* development/debug export

Public/shareable exports should avoid embedding full copyrighted official text unless explicitly reviewed.

Maintainer approval is required for public release exports, packaged datasets, official recommended executable card pools, or any artifact that may redistribute copyright-sensitive official content.

## 6. Effect Data Export

Effect tags and derived taxonomy labels are safer to export than full raw effect text.

Structured Effect DSL records may still reveal substantial official text interpretation and should be reviewed before public release.

Effects approved for public recommended executable pools must follow the review authority rules in [015-effect-taxonomy.spec.md](015-effect-taxonomy.spec.md).

## 7. Replay Export

Replay sharing should avoid redistributing copyrighted card text beyond what is necessary and acceptable.

Replay records should prefer card identifiers, source references, and action records over embedded full official text.

## 8. Dependencies

This spec informs:

* [000 Card Database](000-card-database.spec.md)
* [001 Deck Analyzer](001-deck-analyzer.spec.md)
* [014 Data Importer](014-data-importer.spec.md)
* [015 Effect Taxonomy](015-effect-taxonomy.spec.md)
* [018 Card Data Storage](018-card-data-storage.spec.md)
