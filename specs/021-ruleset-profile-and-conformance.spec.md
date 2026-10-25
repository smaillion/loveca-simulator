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

## Match And Replay Binding

New MatchState snapshots pin ruleset_id, ruleset_fingerprint and
ruling_pack_version. Only the current profile is executable by this engine;
unknown or archived profiles are rejected before match persistence. Existing
create-match requests may omit ruleset_id and use the current profile. Selecting
a new current profile does not itself upgrade the engine: its rule_version must
also equal the engine's declared RULE_VERSION, even for a fully matching snapshot.

Old snapshots omit these optional fields when serialized: no automatic upgrade,
no historical state-hash drift. A same-rule-version legacy snapshot may retain
historical replay execution, but is explicitly legacy_unpinned and does not get
ruleset_identity_verified. This is not evidence of complete rules conformance.

Runtime actions on incompatible identities are rejected before engine execution
or persistence. Replay export keeps the saved initial/final states, actions and
events without executing them, with deterministic_replay_verified=false. Initial
and final identities must agree before reexecution is allowed. A compatible
replay is marked verified only after its result equals the saved final state.

CompatibilityFingerprint compares all three new identity fields in addition to
the existing app/protocol/card/registry/deck fields. Active room payloads inherit
the match identity without relaxing hidden-information redaction. Incompatible
payloads expose no actionable LegalAction and show a localized read-only notice.

No SQLite schema changes. Waiting-room creation-time profile pinning is still
pending; the current room creates its pinned Match when the guest joins. Do not
claim that this remaining room-lifecycle contract is already implemented.

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
