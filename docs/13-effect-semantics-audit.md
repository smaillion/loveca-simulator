# Effect Semantics Audit

## Purpose

This document records the first full-card-pool semantic review baseline for effect modeling.

It is a maintainer-oriented audit artifact only. It does not define implementation code, database schema, importer logic, or executable engine behavior.

## Audit Basis

This audit is based only on:

* current local Gameplay Card and Card Text Revision data in `data/loveca.sqlite3`
* official Japanese card effect text already imported into the local database
* official comprehensive rules ver. 1.06 dated April 28, 2026

This audit does not incorporate FAQ, Q&A, or individual ruling clarifications.

## Current Repository Snapshot

Local card data observed during this review:

* about 1,609 Gameplay Cards
* about 795 Card Text Revisions
* about 787 Gameplay Cards with at least one text revision
* current registry coverage has split into two separate layers:
  * 430 effect definitions
  * 87 `test_validated_executable` definitions
  * 343 timing-only `manual_resolution` definitions
  * about 419 registered Gameplay Cards with effect text, or about 53% timing-prompt coverage against the current local card pool with text
  * the current AI sandbox block run records 1 mandatory manual-resolution blocker across 20 generated matches; the remaining blocked runs are mostly max-action exploration limits or complex unresolved effect families
  * the latest testing loop added a multi-player pending choice boundary for two-player effect resolution

Therefore, the current repository has broad timing-prompt coverage but is still in a pattern-expansion phase rather than a broad full-card executable-effects phase. The new manual fallback entries are not proof of automated semantic support.

The broad fallback set currently focuses on `登場` and `起動` effects. `ライブ開始時` and `ライブ成功時` remain limited to explicitly modeled or tested entries, because broad unresolved Live timing prompts can block the core Live flow until the manual-resolution UX is improved.

## Audit Model

Every effect instance should be reviewed on these dimensions:

* `card_code`
* `text_revision_id`
* `effect_index`
* official Japanese timing label
* normalized trigger
* normalized timing
* effect type
* candidate `execution_mode`
* candidate `simulation_support`
* cost shape
* choice shape
* target and source zone
* visibility requirement
* action family
* duration
* unresolved rule note

This audit groups effects by recurring semantic pattern rather than listing every card flatly.

## Trigger Normalization Baseline

Use these normalized mappings unless a later rules review proves otherwise:

* `【登場】` -> `member_played` / `on_play`
* `【起動】` -> `player_activation` / `activated_main`
* `【ライブ開始時】` -> `live_started` / `live_start`
* `【ライブ成功時】` -> `live_succeeded` / `live_success`
* `【自動】` -> `auto_triggered_event` / `auto_triggered_event`
* `【常時】` -> `static_always` / `static_always`
* Baton-Touch-specific wording -> `baton_touch_performed` / `baton_touch`

The original Japanese timing label must always be preserved alongside normalized values.

## Pattern Groups

### 1. On-Play Deck Inspection And Conditional Keep

Representative local text patterns:

* look at the top `N` cards of the deck
* reveal one matching card and add it to hand
* move the remaining cards to Waiting Room

Representative samples observed in local text revisions:

* `【登場】自分のデッキの上からカードを2枚見る。その中から…1枚公開して手札に加えてもよい。残りを控え室に置く。`
* `【登場】手札を1枚控え室に置いてもよい：自分のデッキの上からカードを5枚見る。その中から…1枚公開して手札に加えてもよい。残りを控え室に置く。`

Expected classification:

* effect type: `triggered`
* execution mode: `prompt_then_resolve`
* simulation support floor: `partially_executable`
* choice shape: inspect top `N`, then select `M`
* visibility: inspected privately, selected card revealed, remainder public destination
* action family:
  * `inspect_top_cards`
  * `reveal_cards`
  * `select_to_hand_from_inspected`
  * `move_remaining_cards`

This pattern must not be collapsed into `draw_card`.

### 2. Activated Self-Wait Costs

Representative local text patterns:

* `【起動】【ターン1回】このメンバーをウェイトにする：…`

Expected classification:

* effect type: `activated`
* execution mode:
  * `auto_resolve` only if no further choice exists
  * otherwise `prompt_then_resolve`
* simulation support floor: `partially_executable`
* cost shape: source Member changes to Wait
* action family:
  * `apply_wait_member`
  * plus the subsequent effect-specific action

Self-Wait as a cost must not be represented as a generic free-form manual note.

### 3. Energy Payment

Representative local text patterns:

* `【ライブ開始時】【E】支払ってもよい：…`
* effects that require choosing one or more Active Energy cards

Expected classification:

* execution mode: `prompt_then_resolve`
* choice shape: choose Energy instances
* target constraints: energy only, Active only
* action family: `pay_energy`

This must remain distinct from later state-change effects that merely ready or rest Energy.

### 4. Energy State Change

Representative local text patterns:

* make one or more Energy cards Active
* make one or more Energy cards Wait

Expected classification:

* execution mode:
  * `auto_resolve` when the affected Energy is fully determined
  * `prompt_then_resolve` when the player must choose which Energy
* action family:
  * `ready_energy`
  * `apply_wait_energy`

This must not be represented by hand-card selection or generic `pay_energy`.

### 4A. Energy Deck Placement

Representative local text pattern:

* `【登場】手札を1枚控え室に置いてもよい：自分のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置く。`

Expected classification:

* trigger: `member_played`
* timing: `on_play`
* execution mode: `prompt_then_resolve`
* cost choice: exactly one card from the owner's hand
* cost action: `discard_from_hand`
* result action: `place_energy_from_deck`
* source zone: Energy Deck
* destination zone: Energy Area
* orientation: Wait

The Energy card is the deterministic top Energy Deck card and is not a player choice. The discard and placement resolve atomically. This pattern is distinct from `pay_energy`, `ready_energy`, `apply_wait_energy`, and main-deck draw. It must not use `ManualAdjustmentAction`.

### 5. Live-Start Optional Prompt Effects

Representative local text patterns:

* `【ライブ開始時】…してもよい`
* optional gains to Blade or Heart
* optional ready or Wait changes at Live start

Expected classification:

* effect type: `triggered`
* execution mode: `prompt_then_resolve`
* choice shape: optional accept or decline, often with target or Energy cost
* simulation support:
  * `manual_resolution` only when semantic remainder is still unmodeled
  * otherwise `partially_executable` or stronger

Optional Live-start effects must be detected by the Rule Engine, not by UI heuristics.

### 6. Live-Success Top-Deck Reveal And Score Change

Representative local text patterns:

* reveal the top card of the deck
* add it to hand
* if it matches a condition, add score

Representative sample observed in local text revisions:

* `【ライブ成功時】自分のデッキの一番上のカードを公開し、手札に加える。それが…の場合、ライブの合計スコアを＋1する。`

Expected classification:

* effect type: `triggered`
* execution mode: `prompt_then_resolve` or `auto_resolve` depending on whether reveal handling is already structured
* visibility: revealed to opponent
* action family:
  * `reveal_cards`
  * `move_card`
  * `modify_score`

This pattern must not be reduced to `draw_card` plus a hidden condition.

### 7. Live-Success Deck Reordering

Representative local text patterns:

* look at several top cards
* put them back on top in chosen order
* move a card to top or bottom

Representative samples observed in local text revisions:

* `【ライブ成功時】自分のデッキの上からカードを3枚見る。それらを好きな順番でデッキの上に置く。`
* `…そのライブカードをデッキの一番上か一番下に置いてもよい。`

Expected classification:

* execution mode: `prompt_then_resolve`
* choice shape: inspect then choose order, or choose top/bottom
* visibility: usually private inspection, public final movement
* action family:
  * `inspect_top_cards`
  * `reorder_deck_top`
  * `move_card_top_or_bottom`

This pattern cannot be modeled faithfully with plain `move_card`.

### 8. Waiting Room Recovery

Representative local text patterns:

* recover a Member or Live from Waiting Room to hand
* conditional recovery after score, color, or group checks

Expected classification:

* execution mode:
  * `auto_resolve` if there is only one legal target and no choice
  * otherwise `prompt_then_resolve`
* action family: `return_from_waiting_room`

This pattern is structurally distinct from search and draw.

### 9. Heart-Color Choice

Representative local text patterns:

* choose one Heart color
* gain the chosen Heart until Live end

Representative sample observed in local text revisions:

* `…好きなハートの色を1つ指定する。ライブ終了時まで、そのハートを1つ得る。`

Expected classification:

* execution mode: `prompt_then_resolve`
* choice shape: choose color
* action family:
  * `choose_heart_color`
  * `gain_heart`
* duration: usually `live`

This must not be left as pure manual text if the only missing piece is choosing a color.

### 10. Under-Member Attachment And Deployment

Representative local text patterns:

* reveal a card from hand and place it under this Member
* later deploy a card from under this Member

Representative sample observed in local text revisions:

* `…手札にある…メンバーカードを1枚公開し、このメンバーの下に置いてもよい。`
* `…このメンバーの下にある…メンバーカードを1枚、メンバーのいないエリアに登場させてもよい。`

Expected classification:

* execution mode: `prompt_then_resolve`
* source and target constraints:
  * attached card only
  * stage top member only
* action family:
  * `attach_under_member`
  * `deploy_from_attachment`

This pattern requires attachment-aware targeting and cannot be represented by generic `move_card` alone.

### 11. Static And Continuous Presence Checks

Representative local text patterns:

* `【常時】…かぎり…を得る`
* checks over stage composition, successful Live area, or named groups

Expected classification:

* effect type: `static` or `continuous`
* execution mode candidate: not part of current MVP executor
* simulation support candidate:
  * `tagged_only`
  * `manual_resolution`
  * eventually `partially_executable` or stronger after invariant modeling

These should remain out of current executable scope unless the continuous-state boundary is explicitly modeled.

### 12. Broad Auto-Triggered Event Effects

Representative local text patterns:

* `【自動】…とき…`
* effects triggered by card movement, Live cards leaving zones, or other event-driven state changes

Expected classification:

* normalized trigger: `auto_triggered_event`
* execution mode:
  * `prompt_then_resolve` if structured choice exists
  * `manual_resolution` if event semantics remain unresolved

This family is broader than `live_start` and must not be merged into a generic “other” bucket forever.

## Prompt Boundary Rules

The following responsibilities are fixed by this audit:

* trigger detection belongs to Rule Engine event processing
* prompting belongs to LegalActionGenerator output
* UI only renders legal prompts and collects structured input
* manual adjustment is reserved for unresolved semantic remainder

The UI must not decide that a skill “should appear now” by itself.

## Manual-Resolution Boundary Rules

The following patterns should not default directly to generic manual adjustment when their prompt boundaries are known:

* inspect top cards, then choose kept cards
* choose which Energy cards become Wait or Active
* choose which Member becomes Active or Wait
* choose color
* choose top or bottom
* choose order among revealed cards

For these patterns, the next modeling step should be structured choice or target support, not free-form manual interpretation.

Manual adjustment remains appropriate for:

* unresolved compound conditions
* complex continuous or replacement effects
* semantics requiring broader rule review than current comprehensive-rules baseline
* effects where only the final state change can currently be trusted

## Unresolved Audit Areas

The following areas should remain explicitly unresolved in current docs and specs:

* continuous-effect invariants across multiple overlapping static modifiers
* replacement-effect precedence
* opponent-choice timing details
* FAQ-sensitive interpretations outside comprehensive-rules text
* “deploy from under Member” interactions that may require further trigger review after entering Stage

## Required Documentation Consequences

This audit requires the following documentation stance:

* `execution_mode` must be treated as a first-class concept
* `simulation_support` and `execution_mode` must remain separate
* `ManualAdjustmentAction` must not be described as a generic skill interpreter
* top-deck inspection, reveal, and keep-to-hand must be modeled separately from draw
* Energy payment must remain distinct from Energy state-change selection
* current repository status must not be described as already having broad or complete skill prompting coverage


