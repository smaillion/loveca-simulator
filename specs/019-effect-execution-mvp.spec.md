# 019 Effect Execution MVP Specification

## Attachment Promotion Snapshot Boundary (2026-10)

`deploy_selected_to_empty_stage` may declare
`entry_trigger_policy: member_area_external_only`. With this policy, a source
attachment already occupies a Member Area: promoting it emits
`effect_member_promoted_from_attachment`, not an external entry trigger or count.
Waiting Room / hand entry still uses the existing entry events. Active placement,
external-entry card identity and existing Stage modifiers are independent.

The default `None` is omitted from serialization and preserves historical effect
snapshot behavior, even if the match already contains the newer card-identity
history. Do not infer this version from PlayerState history or mutate old Replay.
The field is rejected on other operation families. See the Chinese verification
report in `docs/development/attachment-promotion-verification.md`; this bounded
implementation is not an individual official ruling or reviewed promotion.

## 1. Purpose

### Simultaneous Member Deployment Snapshot Boundary (2026-10)

`multi_player_deploy_waiting_member` may declare choice-level
`deployment_policy: simultaneous_member_area_entry` with explicit `active` / `wait`.
Only a single Waiting Room Member per player is supported, without follow-up operations.
The AP chooses first (first player when no turn player), followed by NAP. Selection does
not move a card. The final action revalidates all selections, places both Members, detects
entry triggers from the final board, completes the parent and resolves AP effects first.
UI submits the existing singular card ID and slot payload; no new HTTP endpoint is needed.
Absent policy is omitted from serialization and preserves historical snapshot behavior.
This bounded path is not a general simultaneous-trigger scheduler or reviewed ruling.
Evidence: `docs/development/multi-player-entry-verification.md`.

This specification defines the first limited executable-effect slice for the local Battle Simulator.

It does not define the final Effect DSL, a database schema, AI behavior, full card coverage, or automatic parsing from Japanese text.

## 2. Registry Boundary

### Bounded Occupied-Area Foundation (2026-10)

`deploy_selected_to_stage` is a new operation identity, not a reinterpretation of old
`deploy_selected_to_empty_stage` snapshots. It requires explicit Active/Wait, one self
Member from hand/Waiting Room, a `card_from_zone` 1..1 choice, fixed self Energy costs
only, and no other actions/follow-up choices. Legal card/slot options use current entry
identity; simple overlap clears the old Member, attachments and departed-card modifiers.
Energy goes to Energy Deck, never Waiting Room; no Baton event/history is created.
Native UI/AI keep using `selected_card_instance_ids` and `to_slot`.

Conditional or inherited overlap observers, unknown outgoing effects, incoming static
effects and orphan attachments are excluded with per-area/per-candidate reasons before
payment. Private-hand zero-target choice and general transient-overlap timing are not
implemented. No official registry entry uses this foundation yet; do not promote the
two PR/four Nijigasaki entries on the strength of synthetic transition tests alone.
Evidence: `docs/development/occupied-deployment-foundation.md`.

Executable effect definitions are stored in a version-controlled JSON registry for this MVP.

Every definition must identify:

* `effect_id`
* `card_code`
* `text_revision_id`
* `raw_text_hash`
* `effect_index`
* trigger, timing, condition, cost, choice, visibility, action, and duration data
* `simulation_support`
* `execution_mode`
* `review_status`

The registry must be validated against Card Text Revision data when a match is created. A missing revision or hash mismatch prevents that effect from loading.

The complete validated definitions used by a match must be serialized into its initial GameState. Replay must not depend on the current registry file.

## 3. State And Action Boundary

GameState owns:

* the registry version
* validated effect-definition snapshots
* pending effect invocations
* per-turn effect usage
* effect-created modifiers

Controllers may only interact with effects through LegalActionGenerator output.

The initial effect actions are:

* `activate_effect`
* `resolve_effect`
* `resolve_effect_choice`
* `manual_adjustment` with effect source fields

UI code must not execute effects, detect effects authoritatively, or mutate GameState directly.

## 4. Trigger And Resolution Rules

The MVP supports:

* `member_played` for `登場`
* player activation during Main Phase for `起動`
* `live_started` at comprehensive rule 8.3.8 timing
* `live_succeeded` after successful Live movement is determined
* `baton_touch_performed` after the Baton Touch event

Trigger detection belongs to the Rule Engine. Pending effects must originate from rule events, not from UI fallback or manual prompt creation.

Multiple waiting abilities owned by the same player must be exposed as selectable pending invocations. Forced effects with no player choice may resolve deterministically inside the Action that produced the trigger.

Optional effects may be declined explicitly. Silent skipping is forbidden.

## 5. Execution Modes

The MVP must distinguish:

* `auto_resolve`
* `prompt_then_resolve`
* `manual_resolution`

`prompt_then_resolve` is the default mode when a trigger is detected but a player must still confirm, choose a target, choose a card, choose Energy, choose count, choose order, or choose color.

`manual_resolution` must be reserved for unresolved semantic remainder after structured trigger and prompt boundaries are already known.

## 6. Initial Supported Operations

The restricted executor supports:

* draw a card
* discard a selected hand card
* return a selected Member from Waiting Room to hand
* apply Wait to the source Member
* apply Wait to selected Energy
* ready a selected Member
* pay Active Energy
* gain Heart until a bounded duration
* gain Blade until Live end
* modify score until a bounded duration
* ready Energy
* inspect top cards, select, reveal, reorder, and move remaining cards for registered patterns
* place the top Energy Deck card into the Energy Area as Active or Wait
* manual resolution

Unknown operations must fail registry validation.

The structured operation for Energy Deck placement is `place_energy_from_deck`. It must not expose the Energy Deck as a player card-selection zone. Resolution takes the deterministic top card, records the source as the Energy Deck, and records the resulting orientation. If an optional effect requires this operation and the Energy Deck is empty, the effect is not offered as activatable.

The MVP supports these prompt shapes for registered effects:

* card selection from hand, Waiting Room, Stage, or Energy Area
* Energy-instance selection
* Heart color selection
* count selection
* inspect-top selection and ordering

The MVP does not yet claim broad support for:

* arbitrary reveal-and-keep semantics outside registered patterns
* attached-card deployment flows
* arbitrary target-filter prompts
* continuous effects
* replacement effects

These gaps must remain explicit in docs and review artifacts until modeled.

## 7. Manual Resolution

An effect with `manual_resolution` support must remain pending until:

* the player declines it when the effect is optional; or
* a structured `ManualAdjustmentAction` identifies the invocation, effect, and source card instance.

Free-text-only resolution and direct UI mutation are forbidden.

`manual_resolution` must not be used as a generic substitute for structured target selection, Energy selection, or top-deck inspection when those prompt boundaries are already known.

## 8. Initial Card Coverage

The current reviewed implementation set is limited to:

* `LL-bp1-001`
* `PL!-bp3-001`
* `PL!-bp3-014`
* exact-text `登場` top-2 reorder entries registered in `effect-registry.v0.json`
* exact-text `ライブ成功時` top-3 reorder entries registered in `effect-registry.v0.json`
* `PL!-bp6-002`
* `PL!-bp6-008`
* `PL!N-bp1-001`
* `PL!HS-sd1-001`
* exact-text Energy Deck placement entries registered in `effect-registry.v0.json`

In addition, the registry may include broad timing-only `manual_resolution` entries for `登場`, `起動`, `ライブ開始時`, and `ライブ成功時` effects. These entries exist so the Rule Engine and LegalActionGenerator can surface replay-safe prompts at the correct timing. They do not imply structured semantic execution.

The executable subset remains intentionally narrow. Broad timing prompt coverage must not be described as broad automatic skill execution coverage.

Automated entries may be `test_validated_executable` after rule tests pass. Human review remains mandatory for `reviewed_executable`.

## 9. Replay Requirements

Invocation IDs, modifier IDs, choices, costs, results, visibility requirements, and usage records must be deterministic and serializable.

The same initial state and Action sequence must reproduce the same final state even if the external registry later changes.

## 10. Dependencies

Depends on:

* [002 Rule Engine](002-rule-engine.spec.md)
* [003 GameState and Actions](003-gamestate-and-actions.spec.md)
* [005 Action System](005-action-system.spec.md)
* [007 Effect DSL](007-effect-dsl.spec.md)
* [008 Randomness and Replay](008-randomness-and-replay.spec.md)
* [012 Controller and Legal Actions](012-controller-and-legal-actions.spec.md)
* [015 Effect Taxonomy](015-effect-taxonomy.spec.md)
* [018 Card Data Storage](018-card-data-storage.spec.md)

## 11. Cost-Result Branch Selection

`choose_effect_branch` may declare `auto_branch_from_cost_choice=true` for the
restricted single-hand-discard pattern. Exactly two complementary work-key
conditions are required. The engine validates the cost card, derives one branch
before mutation, pays the complete cost atomically, and persists the branch on
the invocation. Client-provided conflicting branch IDs are rejected.

The initial legal action exposes the hand cost as `card_from_zone`, not a branch
picker. After payment, inspection branches use `resolve_effect_choice`; recovery
branches expose only post-payment candidates and a read-only `branch_from_cost`
label. Mandatory recovery requires one card when available, otherwise resolves
as much as possible. The selected branch cannot change and other branches must
not run after inspection. Multi-stage UI selection state resets at stage changes.

Existing definitions default to non-automatic branching; old effect snapshots,
ActionRequest and runtime SQLite remain compatible. Private inspection cards are
visible only to the choosing player until their subsequent public movement.

## Energy deck return snapshot integrity

`move_selected_energy_to_energy_deck` keeps returned cards face-down with a valid `active` serialization default. Outside Energy Area this value does not make the card usable Energy. Cost and branch paths must survive JSON, runtime reread and Replay. Invalid historical snapshots return `invalid_match_snapshot` without repair or private validation details; clients stop retrying that permanent error. No Card/runtime schema migration or executable-status promotion is implied. Evidence: `docs/development/energy-return-replay-verification.md`.

## Private filtered hand selection

`EffectChoice.selection_policy = private_filtered_may_choose_none` explicitly enables an effective 0–1 target count under rule 9.6.3.1.4. Initial scope is one own-hand Member selected by card information for the single bounded `deploy_selected_to_stage` operation. Cost/follow-up choices, public zones, other players, variable counts and other operations reject this policy. Original minimum/maximum remain 1/1 in the effect snapshot; LegalAction supplies effective bounds. Zero targets must not carry a slot, do not waive/refund costs, and finish with a non-error operation-not-applied event. The UI supports zero and one without ManualAdjustment. None is omitted from serialization to preserve old snapshots and mandatory selections. No card is promoted on foundation tests alone. Evidence: `docs/development/private-hand-choice-verification.md`.

## Bounded Overlap Entry Observers

New matches explicitly set `MatchState.member_overlap_policy=capture_fixed_draw_entry_observers`; None is omitted and preserves old snapshots/replay. Before normal replacement or bounded effect cleanup, capture the outgoing Member's single-trigger `own_member_played` effects only when they perform automatic fixed self draw with no cost/choice and filters reference immutable entering-card cost/work/unit/identity only. Baton has already removed its payment source and must not capture these observers. Resolve captured effects after the action/parent; do not pretend this is a general transient overlap model or AP/NAP scheduler. Complex effect-deployment slots remain excluded; normal replacement reports unsupported observers with an audit reason rather than claiming resolution. Actual `PL!N-pb1-005:1` is the current validated registry representative, without status promotion or SQLite changes. Evidence: `docs/development/overlap-entry-observer-verification.md`.

## Pending Effect Priority

New matches separately set `MatchState.effect_order_policy=ap_nap_player_choice`; absent/None is omitted and retains legacy eager resolution, independently of the overlap policy. Under rules 7.2.1/9.5.3/9.7.3, expose AP's pending group first, otherwise NAP's, and let the owner choose among multiple effects using existing `resolve_effect`. Re-evaluate priority after each completed effect. Shared Live Set/judgment use the first player as AP. A pending effect-native choice or non-initial resolution stage locks its invocation until completion; resolve, skip and source-bound manual routes enforce the same lock. Multiple automatic effects must not be consumed before the owner can choose; a lone ordinary automatic effect may still resolve directly. LegalAction emits `effect_order_choice` for UI without front-end timing inference. This is not a generic rule-action scheduler, transient-overlap implementation or registry promotion. Evidence: `docs/development/pending-effect-order-verification.md`.

## Fixed Wait Energy Overlap Observer

The latest new-match `member_overlap_policy=capture_fixed_draw_and_energy_entry_observers` includes the previous draw family and one fixed self Wait Energy operation with immutable entry filters. Capture before cleanup, resolve after the action/parent. For this captured family only, the modeled Energy availability check is deferred so returned attachments can supply the Energy; if none remains at resolution, emit `effect_operation_not_applied / energy_deck_insufficient_at_resolution` and finish without refresh or error skip. A separate triggered `live_succeeded` ability on the outgoing card cannot observe this entry/exit and need not exclude the area. Source/stage-dependent observers, inherited abilities, variable amounts and other Energy orientations remain guarded. None and `capture_fixed_draw_entry_observers` retain their historical serialization and Replay behavior. UI renders actual effect Energy counts or the explicit non-applied reason, not normal Energy Phase notifications. Actual representative: `PL!N-pb1-012:1`, without registry promotion or SQLite changes. Evidence: `docs/development/overlap-energy-observer-verification.md`.
