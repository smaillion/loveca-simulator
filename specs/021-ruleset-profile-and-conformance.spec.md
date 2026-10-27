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

## Waiting Room Identity

New rooms pin RulesetIdentity at creation, using the same supported-profile
resolver as MatchService. POST /api/rooms accepts optional ruleset_id; omitting
it keeps the old request valid. Identity contains only rule version, profile ID,
fingerprint and ruling-pack version, not full sources, decks, tokens or secrets.

Room and identity persist in the same SQLite transaction. The existing
runtime_metadata table stores JSON under hosted_room_ruleset:<canonical-code>.
No table/column/schema-version change and no data inside decklist are required.
Joining passes the expected identity to MatchService, which resolves current
support again before deck validation or match persistence. Mismatch returns409
ruleset_mismatch without creating a Match or updating the room.

Legacy rooms without metadata retain the prior join-at-current-rules behavior;
their absent creation identity remains null rather than being reconstructed.
Expired metadata follows room grace retention. Cleanup removes only exact-prefix
keys whose room rows no longer exist, preserving schema_version and other keys.
Room-only repositories without runtime_metadata retain legacy behavior, but
cannot request new binding without a standard runtime database.

This implements Ruleset pinning, not a complete client app/catalog/registry
handshake or an atomic concurrent-guest room reservation protocol.

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
