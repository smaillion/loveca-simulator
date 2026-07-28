# AI Rule Conformance and Strategy Audit

## Purpose

This document defines the maintained local acceptance process for Simple AI matches. It separates three questions that must not be conflated:

* whether an Action was legal
* whether the resulting state transition followed the official rule model and registered Japanese effect text
* whether an AI policy made a strategically strong choice

## Rule Basis

The audit uses the local official comprehensive rules PDF `raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`, SHA-256 `c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`.

The maintained rule map covers match results, card-text precedence, best-effort resolution, public and private zones, draw and inspection, Energy payment, setup, phase progression, Live Set, reveal, Yell, Heart allocation, Live-success timing, score comparison, match-point ties, success-Live movement, next-turn initiative, and effect resolution.

The project stores clause identifiers and concise summaries. It does not redistribute the complete official rule text.

## Acceptance Command

```powershell
python -m tools.ai_sandbox.ai_rules_acceptance `
  --database data/loveca.sqlite3 `
  --output logs/ai-rules-v1-1-final-review `
  --decks 20 `
  --attempts 20 `
  --required-qualified 10 `
  --max-turns 10 `
  --max-actions 500 `
  --policy simple_ai_v1_1
```

Each accepted Action is checked against the legal-action set, revision progression, zone/card invariants, action-specific transitions, effect snapshot identity, trigger timing, execution support, conservative Japanese semantic-operation alignment, Live resolution, victory state, and Replay output.

The same command also runs a deterministic Live-judgment boundary matrix. A failed boundary causes the command to fail even when the sampled AI matches complete.

## Live Judgment Audit Model

The audit keeps four results separate because the comprehensive rules assign them to different steps:

1. **Live success**: after Heart resolution, a player whose Live Area still contains a Live card produces the Live-success event under 8.4.4.
2. **Live-success check timing**: `ライブ成功時` automatic effects resolve under 8.4.5 before total-score comparison. Score modifiers created here therefore affect the current comparison.
3. **Performance winner and placement eligibility**: 8.4.6 determines the winner or winners, while 8.4.7 and 8.4.7.1 independently determine who may move one card to the Success Live Area.
4. **Match result**: only actual Success Live counts after movement are evaluated against 1.2.1.1 and 1.2.1.2.

This distinction is material at Match Point. On equal total score, both players remain performance winners. A player already holding two Success Live cards cannot add another under 8.4.7.1. If both players are at Match Point, neither moves a card and the match continues; this is not a simultaneous match win or draw.

The maintained matrix covers:

* neither player succeeds
* only one player succeeds
* unequal total score
* an ordinary tie where both players move one card
* a one-sided Match Point tie
* a two-sided Match Point tie
* unequal score while both players are at Match Point
* a Live-success score effect that changes the comparison
* a card effect that prevents equal-score Success Live placement

The production engine now emits separate `live_success_determined`, `live_judgment_started`, `success_live_placement_prevented`, `success_live_selected`, and `live_judgment_completed` evidence. Live-duration modifiers expire after comparison and placement cleanup, not before Live-success effects are resolved.

## Current Result

The fixed 20-match run produced:

* 20/20 formally completed matches
* 12/20 strict qualified matches
* average completion at turn 8.05
* 18/20 matches where both players completed at least one Live
* 14,160 passing transition checks
* zero review or failed checks
* zero illegal Actions, effect-error skips, or Replay mismatches
* 64 distinct effects exercised in 260 effect decisions or resolutions
* 260 passing dynamic effect semantic checks

A strict match must formally complete within 10 turns, give both players at least one successful Live, contain no failed rule check or effect-error skip, and replay to the identical final state.

## Effect Registry Status

The strict registry integrity audit reports zero errors and zero warnings across 979 effect identities.

* 864 `test_validated_executable`
* 115 `manual_resolution`
* 88.25% registry-entry executable coverage

`LL-bp5-002:1` was added in this audit cycle. It uses the existing distinct-Stage-unit condition and a Live-duration all-color Heart modifier targeted at the Center Member.

Static registry coverage and dynamic exercised-effect coverage are independent. A passing match does not justify promoting an untriggered effect, and automated tests do not grant `reviewed_executable` status without human rule review.

## Strategy Experiments

`simple_ai_v1_1` remains the best tested deterministic policy in the maintained pool.

Three v1.2 candidates were explored and rejected:

| Candidate | Matches | Challenger points | Baseline to challenger Live success | Result |
|---|---:|---:|---|---|
| Live conservation plus no-Live access bonus | 80/80 | 48.75% | 57.19% to 53.87% | Reject |
| No-Live access bonus only | 80/80 | 47.50% | 57.32% to 53.01% | Reject |
| Bounded one-action Member placement lookahead | 40/40 | 50.00% | 60.43% to 61.15% | Reject |

All candidates remained legal and replayable. The first two strategic regressions show that preserving Live cards too aggressively weakens current score competition, while a flat bonus for draw/recovery effects loses Stage tempo without measuring the expected cards reached. The bounded lookahead candidate produced only one additional Live success across 139 checks, did not improve match points, and raised decision P95 from 13.96ms to 104.07ms.

The next candidate should use cached Live-access probability/value or a much narrower tie-breaker rather than cloning projected board states on every Main Phase decision. It must be compared with mirrored seats, fixed decks, and fixed seeds before receiving a new policy version.

## Generated Review Artifacts

The acceptance runner writes local Chinese review artifacts under its output directory:

* `比赛总报告.zh-CN.md`
* `AI策略报告.zh-CN.md`
* `Live判定审计.zh-CN.md`
* `官方规则引用.zh-CN.md`
* `比赛完整审计.json`
* `matches/match-NN.zh-CN.md`

Generated match logs are local artifacts and are not committed. The runner and its contract tests are version controlled so contributors can reproduce the reports.

## Limits

This audit proves only observed execution paths plus the fixed Live boundary matrix against the maintained rule map and exact match-local effect snapshots. It does not prove untriggered effects, FAQ-sensitive interactions, replacement effects, inherited abilities, future rule versions, or game-theoretic optimal play. The complete 8.4.10-8.4.12 repeated turn-end automatic-effect loop remains a separately tracked rule-expansion item.
