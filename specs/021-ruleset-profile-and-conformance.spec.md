# 021 Ruleset Profile and Conformance Specification

## Purpose

Identify versioned official-rule sources and the evidence used to audit them.
Official Japanese text is authoritative; concise Japanese/Chinese summaries are
review aids, not substitute rules or executable effects.

## Source And Profile Contract

- A source has a stable ID, official HTTPS URL, kind, review status and, when
  confirmed, a SHA-256 of its content. Local paths are optional packaging hints.
- A profile has a stable ID, rule version, ruling-pack version, active source IDs
  and unique clause-reference IDs. All links must resolve inside the profile.
- Source, profile and reference definitions are read-only. Duplicate IDs and
  broken links are rejected rather than silently deduplicated.
- An available but unreviewed FAQ/Q&A source may be catalogued, but cannot be an
  active source. Merely adding a URL is not ruling review.
- `source_confirmed` records source/section identification, not a human rules
  approval. `rules_reviewed` must not be assigned by automated tests.
- New official versions require new profiles. Do not edit old profiles and claim
  that their previous fingerprints still describe equivalent rules.

## Fingerprint

The SHA-256 covers the schema version, complete profile definition and the
profile's active source metadata/content hashes. JSON keys, source IDs and
references are canonicalized by identifier. Local file paths, inactive sources
and collection order do not change rule identity. Rule text summaries, clause
links, versions, hashes and review status do change it.

## Conformance Evidence

`RuleConformanceResult` contains scenario ID, category, status, nonempty official
reference IDs, evidence location and diagnostics. Reports must distinguish
source/contract checks from actual engine state transitions and human review.
A source check must never be counted as a completed gameplay matrix scenario.

## Compatibility Target

The next migration slice will add profile identity to match/replay/online
compatibility, retaining existing app/protocol/card/registry/deck identities.
Unknown profiles must be rejected before match creation. Mismatching rule
fingerprints must not be represented as deterministic replay equivalence.
Old replay read-only inspection remains allowed.

This source-profile slice does **not** change MatchState, HTTP requests, runtime
SQLite, replay serialization or the current match-state hash.

## v0.9 Exit Criteria

At least 75 core scenarios and 20 dedicated Live scenarios with rule references;
zero registry-integrity errors/warnings; explicit reasons for manual effects;
no silent skip in supported decks; compatible, ruleset-aware replay/online
metadata. These are future gates, not capabilities established by this module.

## Dependencies

- [002 Rule Engine](002-rule-engine.spec.md)
- [003 GameState and Actions](003-gamestate-and-actions.spec.md)
- [008 Randomness and Replay](008-randomness-and-replay.spec.md)
- [017 Public Release and Export Policy](017-public-release-and-export-policy.spec.md)
