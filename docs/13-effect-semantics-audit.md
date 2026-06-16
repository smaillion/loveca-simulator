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
  * 925 effect definitions
  * 462 `test_validated_executable` definitions
  * 463 timing-only `manual_resolution` definitions
  * registry-entry executable coverage is currently about 49.95%
  * the latest Phase 5 sandbox block run still records high-frequency mandatory manual-resolution blockers across 50 generated matches
  * `skip` mode currently avoids illegal actions in the latest 50-match run, but long sandbox games still frequently reach the action cap before a formal result
  * the latest testing loop added Live-specific temporary score / required-Heart modifiers, reveal-top scoring, Live Area condition checks, grouped Stage Member choice, and additional exact-text Live timing patterns

Therefore, the current repository has broad timing-prompt coverage but is still in a pattern-expansion phase rather than a broad full-card executable-effects phase. The new manual fallback entries are not proof of automated semantic support.

The broad fallback set originally focused on `登場` and `起動` effects. `ライブ開始時` and `ライブ成功時` now have a larger tested subset, but they still contain the highest-risk unresolved families because many effects combine conditional scoring, required-Heart replacement, temporary base-stat rewrites, answer-based choices, and FAQ-sensitive state.

## Latest Sandbox Baseline

The current Phase 5 live-effect loop used the `preview` branch card database as the local full-card baseline.

Observed runs:

* `30 decks x 50 matches --manual-policy block --max-actions 260`
  * latest blocker distribution: 49 `mandatory_manual_resolution`, 1 `max_actions`
  * no `illegal_action` after fixing structured cost choice propagation
* `30 decks x 50 matches --manual-policy skip --max-actions 260`
  * latest blocker distribution before strategy tuning: 47 `max_actions`, 3 completed
  * `illegal_action = 0`
* `30 decks x 20 matches --manual-policy skip --max-actions 260`
  * after sandbox strategy tuning: 20 `max_actions`
  * matches reached turn 16, indicating long-game strategy limits rather than immediate rule-engine crashes
* semantic user-agent sandbox loop
  * added as a second Phase 5 test lane after deterministic black-box sandbox
  * ordinary actions still use deterministic sandbox policy
  * mandatory `manual_resolution` effects can be handed to a configured semantic provider to test whether current structured manual tools are expressive enough for human-like play
  * `mock` provider remains the default for CI and smoke runs; real OpenAI-compatible providers are manual local runs
  * semantic success is a manual playability signal, not registry executable coverage
* follow-up sandbox controller probes
  * added work-key grouped deck generation and Heart-fit Member selection for generated decks
  * added Live-set selection that ranks 1-3 Live combinations by estimated Heart reachability and total score
  * added per-match final success Live counts to sandbox reports, alongside skipped effect IDs
  * a 10-match Heart-fit skip sample completed 2/10 games and still showed 8 `max_actions`, so this is diagnostic progress rather than a solved sandbox strategy
  * after structuring `PL!SP-sd2-023:1`, a 10-match skip sample completed 1/10 games, recorded 9 `max_actions`, and showed total success Live counts `{0: 5, 1: 2, 2: 2, 4: 1}`
  * `PL!SP-sd2-023:1` no longer appears in skipped-effect reports; the remaining top skipped effects are now centered on movement-history, named-member temporary Heart/Blade, base Blade rewrite, Energy-threshold compound effects, and multi-step both-player draw/discard effects
  * after structuring `PL!SP-bp1-007:1`, a 10-match skip sample completed 1/10 games, recorded 9 `max_actions`, and showed total success Live counts `{0: 5, 1: 1, 2: 3, 4: 1}`
  * `PL!SP-bp1-007:1` no longer appears in skipped-effect reports; the highest remaining repeated skipped effects are now movement-history / named-member modifier / base-Blade rewrite families
  * after structuring `PL!SP-bp4-024:1`, a 10-match skip sample completed 1/10 games, recorded 9 `max_actions`, and showed total success Live counts `{0: 5, 2: 4, 4: 1}`
  * `PL!SP-bp4-024:1` no longer appears in skipped-effect reports; the highest remaining repeated skipped effects are still movement-history, multi-target named modifiers, base-stat rewrites, and compound multi-step Live effects
  * after structuring five additional safe Live-start patterns, a 10-match skip sample completed 2/10 games, recorded 8 `max_actions`, and showed total success Live counts `{0: 4, 1: 3, 2: 1, 3: 1, 4: 1}`
  * the added safe patterns include Hasunosora distinct-name score scaling, Dream Believers waiting-room checks, Liella! total Heart checks, Nijigasaki required-Heart checks, and Heart02 required-Heart replacement
  * after structuring `PL!S-sd1-022:1`, a 10-match skip sample completed 1/10 games and no longer listed that Aqours all-stage Blade effect in skipped-effect reports
  * after structuring `PL!N-bp4-028:1`, `PL!SP-bp4-024:2`, and `PL!HS-pb1-026:1`, a 10-match skip sample recorded 10 `max_actions`, success Live counts `{0: 4, 1: 3, 2: 2, 4: 1}`, and removed those effects from the skipped-effect table
  * after structuring `PL!HS-bp6-030:1`, `PL!SP-sd2-025:1`, `PL!-bp4-021:1`, `PL!SP-pb1-025:1`, and `PL!SP-pb1-023:1`, successive 10-match skip samples kept `illegal_action = 0` and removed those exact effects from the skipped-effect table
  * after structuring `PL!N-bp4-027:1` and `PL!SP-bp1-026:1`, a 10-match skip sample completed 1/10 games, recorded 9 `max_actions`, kept `illegal_action = 0`, and removed those effects from the skipped-effect table
  * that 10-match sample surfaced `PL!SP-pb1-001:1` as a skipped effect; the exact-text branch is now structured as “pay 2 Active Energy or discard 2 hand cards” and no longer uses manual fallback
  * the follow-up block-mode run surfaced `PL!N-bp3-026:1`; the exact-text score-values bonus is now structured as an auto-resolved Live score modifier
  * the next block-mode sample surfaced `PL!-bp3-024:1`; the exact-text “choose Heart color and μ's stage member” pattern is now structured with combined card and color selection
  * the following block-mode sample surfaced `PL!S-bp2-023:1`; the exact-text “Live Area contains another Aqours Live” condition is now structured and grants temporary Blade to all own Stage members
  * the same blocker sweep surfaced `PL!HS-bp5-019:1`; the exact-text “other Hasunosora Live cards in Live Area” pattern is now structured as a live-duration required-Heart modifier
  * the next pass surfaced `PL!-pb1-010:1`; the exact-text optional discard cost now grants temporary Blade to all other own Stage members through structured hand selection
  * the next blocker pass surfaced `PL!-bp5-023:1`; the exact-text “Stage members with Heart colors other than heart01/heart06” count now drives a structured required-Heart modifier
  * the next blocker pass surfaced `PL!HS-bp6-029:1`; the exact-text Hasunosora stage-cost inspection pattern now supports keeping one inspected card, returning the rest to deck top, and applying the cost-30 required-Heart bonus
  * the next blocker pass surfaced `PL!HS-pb1-025:2`; the exact-text Live-success pattern now prompts for a Waiting Room Member when the player's hand has six or fewer cards
  * the next blocker pass surfaced `PL!-bp5-020:1`; the exact-text center μ's Heart-pair pattern now reduces required any-color Heart by the center Member's `heart03` pairs, capped at three
  * the next blocker pass surfaced `PL!HS-bp2-024:1`; the exact-text named-stage cost relation now reduces required any-color Heart when `村野さやか` has higher cost than `徒町小鈴`
  * the next blocker pass surfaced `PL!HS-bp5-021:1`; the exact-text base-Heart replacement pattern now lets one Hasunosora Stage Member replace its original Heart colors with `heart01` until Live end
  * a 20-match block smoke after the base-Heart replacement support recorded 12 `mandatory_manual_resolution`, 5 `max_actions`, and 3 completed games; `PL!HS-bp5-021:1` no longer appears in the blocker list
  * the next blocker pass surfaced `PL!SP-bp1-024:1`; the exact-text named-member modifier pattern now gives `澁谷かのん` temporary `heart05` + Blade and `唐 可可` temporary `heart01` + Blade until Live end
  * a 20-match block smoke after named-member modifier support recorded 12 `mandatory_manual_resolution`, 6 `max_actions`, and 2 completed games; `PL!SP-bp1-024:1` no longer appears in the manual blocker list
  * the next blocker pass surfaced `PL!N-pb1-037:1`; effect-caused ready-history tracking now records Nijigasaki Energy / Member readiness and applies the Live-start score bonus as +1 or +2
  * a 20-match block smoke after ready-history support recorded 13 `mandatory_manual_resolution`, 5 `max_actions`, and 2 completed games; `PL!N-pb1-037:1` no longer appears in the manual blocker list
  * after structuring Blade Heart color rewriting and the grouped Stage Member choice for `PL!SP-bp4-023:1`, a 20-match block smoke recorded 2 completed games, 11 `mandatory_manual_resolution`, 7 `max_actions`, and `illegal_action = 0`; `PL!SP-bp4-023:1` no longer appears in the manual blocker list
  * the current repeated manual blocker in that smoke is `PL!N-bp4-031:1`; other remaining blockers are one-off Live-start / Live-success manual families and long-game `max_actions`
  * after structuring `PL!N-bp4-031:1` as draw 3 plus a post-action hand choice returning 3 cards to deck top, a 20-match block smoke recorded 2 completed games, 9 `mandatory_manual_resolution`, and 9 `max_actions`; `PL!N-bp4-031:1` no longer appears in the manual blocker list
  * after adding Baton-specific turn history and structuring `PL!HS-bp2-023:1` / `PL!HS-bp2-025:1`, the next 20-match block smoke still recorded 2 completed games, 9 `mandatory_manual_resolution`, and 9 `max_actions`, but those Hasunosora required-Heart effects no longer appear in the manual blocker list
  * a semantic mock smoke (`30 decks x 5 matches --manual-fallback skip --max-actions 120`) produced 5 `max_actions` and 4 mock `schema_gap` attempts, confirming report plumbing without claiming real semantic resolution
* `30 decks x 50 matches --manual-policy block --max-actions 260` after the safe-pattern expansion
  * earlier blocker distribution: 44 `mandatory_manual_resolution`, 2 `max_actions`, 4 completed
  * this still misses the target of `mandatory_manual_resolution <= 15/50`
* `30 decks x 50 matches --manual-policy block --max-actions 260` after the latest Live pattern expansion
  * latest blocker distribution: 35 `mandatory_manual_resolution`, 9 `max_actions`, 6 completed
  * this improves the mandatory manual count, but still misses the target of `mandatory_manual_resolution <= 15/50`
* `30 decks x 50 matches --manual-policy skip --max-actions 260` after the safe-pattern expansion
  * earlier blocker distribution: 31 `max_actions`, 19 completed
  * `illegal_action = 0`
  * total success Live counts were `{0: 7, 1: 9, 2: 9, 3: 19, 4: 5, 5: 1}`
  * this improved completion but still missed the target of `max_actions <= 20/50`
* `30 decks x 50 matches --manual-policy skip --max-actions 260` after the latest Live pattern expansion
  * latest blocker distribution: 40 `max_actions`, 10 completed
  * `illegal_action = 0`
  * total success Live counts were `{0: 7, 1: 11, 2: 13, 3: 15, 4: 3, 5: 1}`
  * the run confirms the new structured effects are not introducing illegal actions, but sandbox strategy and remaining complex Live-start / Live-success effects still keep many games from reaching formal completion

The original target `mandatory_manual_resolution <= 15/50` was not met. Remaining high-frequency blockers are primarily complex Live-start and Live-success families, including base Heart rewrites, optional multi-branch effects, answer-based effects, movement-history effects, and effects that disable or grant other effects.

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
