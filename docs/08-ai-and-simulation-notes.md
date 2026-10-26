# AI and Simulation Notes

PL!N-sd2-026:1 uses the engine's effective Member Blade (including supported
static modifiers), not printed Blade or a player-level Yell bonus. Its opt-in
policy preserves old Replay filtering. Four policies pass current-target and
hidden-hand invariance tests. Frozen30 improves8→9 completed,21 manual stops,
158/160 executable completions; defaultv1.1 unchanged.
[Chinese evidence](development/nijigasaki-blade-four-heart-verification.md).

PL!S-cl1-002:1 delegates original-Yell filtering and ordered bottom return to the
engine. Four policies retain hidden-hand invariance. Frozen30 completes8/30 with
22 explicit manual stops,150/154 executable completions and4 pending behind manual.
No illegal/runtime/Replay/error-skip failures; defaultv1.1 unchanged.
See [the Chinese audit](development/aqours-yell-bottom-verification.md).

PL!N-PR-036:1 now uses a bounded other-Nijigasaki target policy and the engine's
resolution-time card information cost, not Member payment reduction. Four AI
policies, hidden-hand substitutions and returned-source targeting are tested.
Frozen30 diagnostics still finish7, with23 explicit manual stops and no illegal,
runtime or Replay errors. Its9 queued invocations include2 still pending behind
another manual effect, not9 confirmed completions. Product policy stays v1.1.
See [the Chinese audit](development/other-nijigasaki-heart-verification.md).

The next evidence-led fix supports only PL!-pb2-039:1. Its body condition is
evaluated at resolution; two successful μ's Live cards grant +10 Yell reveals,
not Stage Blade. The same frozen 30-deck diagnostic improves from 6 to 7 finished
matches, with 23 explicit manual stops and no illegal/runtime/Replay errors.
Seed18026 finishes on turn5, but the losing side has no successful Live, so this
does not meet the two-sided Live acceptance target. Seed18029 reaches a different
manual blocker on turn2. Product AI remains v1.1; segment2 remains manual.
See [the Chinese verification](development/live-yell-ten-verification.md).

Manual-focused diagnostics are opt-in (`--manual-focus`), leaving the default pool
and product policy unchanged.30 legal decks/30 matches produce6 completions and24
explicit mandatory-manual stops. Current manual skills have80 queue events over42
effect IDs,51 declines and28 blocked invocations; no error skips, illegal actions,
runtime exceptions or Replay errors. Queue events are not proof that official
conditions held. See the [Chinese report](development/manual-trigger-observation-audit.md).
Gapv0.3 separates outcomes and legacy skip evidence instead of relabeling skips
as triggers. Provenance binds src/sandbox Python, card DB, registry and manifest;
it does not include credentials or hidden hands. Defaultv1.1 is unchanged.

Multi-keep audit: PL!S-bp2-005:1 is manual, not an automatically executable skill.
Four policy versions explicitly decline its optional cost and persist the reason;
there is no silent error-skip or private inspection.21 targeted card tests retain
old SQL behavior as compatibility evidence only. Fixed10 does not trigger this
card. Coverage is corrected to914/1212,298manual; defaultv1.1 stays unchanged.
[Reason and audit limits](development/multi-keep-inspection-audit.md).

Mixed-Heart follow-up:165 targeted assertions for three exact identities include
four-policy paid/unpayable completion, privacy invariance and SQL Replay. Fixed10
qualifies in3-9 turns but does not trigger these three.172 illustrated scenarios
pass, not proof of universal rules correctness or stronger AI. Defaultv1.1 stays.
[Chinese evidence](development/mixed-heart-inspection-audit.md).

Member/Liella follow-up:165 targeted assertions cover five exact identities and
their real fees2/5/7/9. All four policies finish safely without hidden-hand
dependence. Fixed10 qualifies in3-9 turns and PL!SP-bp1-005:1 has five actual
cost/inspection/resolution events each; the other four do not trigger. No strategy
strength claim or defaultv1.1 change. [Chinese evidence](development/member-liella-inspection-audit.md).

Work/unit inspection follow-up: six exact cost snapshots have192 per-card native
action assertions including four-policy privacy invariance, real fee4 and SQL
Replay. Fixed10 again qualifies in3–9 turns with both players succeeding at Live,
but these six do not trigger. This is workflow regression, not evidence of
improved AI strength or full card coverage. Defaultv1.1 remains unchanged.
[Chinese scope and evidence](development/work-unit-inspection-audit.md).

Frozen-pool follow-up: the blackbox tool can opt into the shared controller while
keeping its historical heuristic default. With the same archived 30 decks,
seeds9000–9049 and 260 actions, completions are 34 legacy / 42 v1.1 / 48 v1.2.
Three explicit manual skips remain in v1.2; two new capped matches finish under
an explicitly separate 600-action diagnostic. [Evidence and reproducible commands](development/ai-frozen-pool-verification.md).

Experimental `simple_ai_v1_2` adds legal non-Live resource cycling without changing
the v1.1 default or historical policies. A paired 50-match sample completes 50/50
under both policies, reducing mean turns from 7.64 to 5.94 and maximum from 19 to
11. The first ten v1.2 matches all meet the ten-turn / both-player success target.
This is not a strength benchmark or a universal optimal strategy. The archived
30-deck heuristic pool still completes only 34/50. [Chinese evidence and remaining work](development/ai-live-cycle-verification.md).

## 1. Purpose

This document describes AI and simulation strategy for the platform.

It defines architectural expectations and records the current baseline implementation boundary. Concrete behavior remains owned by the implementation and executable tests.

Baseline Simple AI is implemented for the Battle Simulator MVP. Advanced AI remains a future phase.

Current implementation snapshot:

* local and Hosted FastAPI can create Human-vs-Simple-AI matches
* AI decisions are selected only from LegalActionGenerator output and are applied through MatchService
* deterministic AI-vs-AI acceptance and replay verification are available outside normal CI
* unresolved manual effects use explicit skip-and-log behavior under the baseline policy
* AI blockers are persisted as non-mutating runtime events with state revision and effect context
* `RuleEvaluationSnapshot` supplies effective Heart, Blade, Live requirement, score, Energy, and match-progress values calculated by the Rule Engine
* `AIObservation` exposes the AI player's private cards and public game data while hiding opponent hand identities
* `simple_ai_v0` and `simple_ai_v1` remain available for old snapshots and policy comparison; new Simple AI matches use `simple_ai_v1_1`
* the registry integrity audit currently reports 979 effect definitions with zero integrity errors or warnings
* the corrected 200-match mirrored v1.1-v1 benchmark completed 200/200 matches with v1.1 scoring 54%, no illegal action or replay error, average 8.38 turns, P95 14 turns, and v1.1 decision P95 6.975 ms
* the 55% policy-strength target was not met; this result remains the honest regression baseline rather than a reason to tune individual seeds

## 2. Controller Abstraction

The simulator should separate game rules from decision-making.

Controller and LegalActionGenerator boundaries are specified separately so HumanController and SimpleAIController use the same legal-action flow.

Conceptual controller roles:

* PlayerController
* HumanController
* SimpleAIController
* FutureAIController

The engine should expose legal actions from the current GameState. A controller should choose one legal action. The rule engine should validate and resolve the selected action.

Conceptual flow:

* GameState
* LegalActionGenerator
* PlayerController chooses one legal action
* ActionResolver validates and resolves
* New GameState and events are produced

This is an architectural pattern, not an implementation definition.

## 3. HumanController

HumanController represents a human decision source.

It may be driven by CLI prompts, local UI input, or future online client input. It should still choose from legal actions generated by the engine.

HumanController should not directly mutate GameState.

## 4. SimpleAIController

SimpleAIController is required for the simulator MVP.

The first AI does not need to be strong. It only needs to make legal, deterministic, explainable decisions under a simple heuristic policy.

The Simple AI must be able to:

* draw cards according to turn flow
* decide mulligan
* play Member cards if legal
* pay Energy if required
* choose a Live card to attempt
* resolve basic Live success checks through the engine
* end turn when no useful action exists
* avoid illegal actions
* prioritize winning if a winning Live is available

## 5. FutureAIController

FutureAIController represents stronger AI approaches that may be introduced later.

Future AI may use deeper heuristics, matchup statistics, Monte Carlo search, or learned policies. It must still use the same legal action system as humans and Simple AI.

Advanced AI should improve decisions without receiving permission to bypass validation.

## 6. LegalActionGenerator

LegalActionGenerator is the conceptual component that asks the Rule Engine what actions are currently legal.

It is important because:

* Human users should not be offered illegal actions
* AI should not be able to cheat
* future online clients should submit only valid action choices
* action logs can be checked against rule validation
* tests can verify available choices from known GameStates

Legal actions should reflect current player, phase, zones, resources, rule version, and supported effect context.

## 7. Simple AI Heuristic Policy

The v1 and v1.1 policies enumerate legal candidates and score them deterministically. Effective rule values come from `RuleEvaluationSnapshot`; controller code does not reproduce modifier or required-Heart rules.

Current scoring considers:

* mulligan cost curve and Live Heart fit
* projected Stage Heart / Blade value, payment, replacement loss, and on-play effect value
* effective Live requirements, expected Yell, score, and match-point pressure
* structured effect operations, costs, branch choices, targets, Heart colors, and selected counts
* resource preservation when no positive Main Phase action remains

The policy remains intentionally shallow and explainable. It does not search future game trees.

The v1.1 refinement additionally preserves the last practical Live resource, avoids low-value Stage replacement, uses Match Point pressure in effect activation and Live Set scoring, and validates count-based Energy choices against the candidates exposed by LegalActionGenerator. These refinements remain policy preferences and do not change rule legality.

The following order is a target for later policy refinement rather than a claim that every item is already optimized:

Initial Simple AI priority order:

1. If a legal action immediately wins the game, choose it.
2. If a Live can be successfully completed this turn, attempt the best Live.
3. If playing a Member increases Live success probability, play that Member.
4. If multiple Members are playable, prefer lower cost early game.
5. If multiple choices remain, prefer higher Heart contribution.
6. If useful keyword or effect tags are available, prefer cards aligned with the current plan.
7. If no useful Member can be played, preserve resources.
8. End turn.

Initial mulligan policy:

* keep opening hand if it contains playable low-cost Member cards
* mulligan if no early playable Member exists
* prefer keeping at least one Live card if the hand is otherwise playable

These heuristics are intentionally simple. They should be deterministic and explainable rather than strong.

The observation contract excludes opponent hidden-hand identities. Tests must verify that replacing only those hidden identities does not change the selected Action.

## 8. AI vs AI Debug Mode

The simulator supports baseline AI vs AI games without UI interaction through the acceptance runner.

Minimum output:

* winner
* number of turns
* successful Live count for each player
* action log
* final GameState summary

AI vs AI debug mode already supports regression testing and replay generation. It may later support:

* Monte Carlo matchup simulation
* AI policy comparison
* larger policy-strength benchmarks

## 9. Deterministic AI Decisions

AI decisions must be deterministic when the seed is fixed.

Any AI randomness should use the shared randomness model. Random tie-breaks should be recorded or reproducible from the match seed and decision context.

Hidden random choices inside AI policy should be avoided.

## 10. AI Decision Logging

Every AI decision should be loggable.

Decision logs should capture:

* turn
* player
* current phase
* available legal actions
* selected action
* selection reason
* random seed or random context if randomness was used
* controller policy version and bounded score components
* measured decision duration

The purpose of decision logging is to support debugging, explainability, replay preparation, regression testing, and future AI comparison.

Runtime logs intentionally omit the full candidate list to control SQLite growth. Offline mirrored benchmark reports may retain detailed policy measurements.

## 11. Effect Support Awareness

AI behavior should account for effect simulation support status.

Unsupported, tagged-only, and manual-resolution effects may inform heuristics or prompts, but they should not be treated as automatically resolved game behavior.

Simple AI may use effect tags as heuristic hints. For example, it may prefer cards tagged as draw when hand size is low or live_support when attempting a Live.

Simple AI must not assume tagged effects are executable. It must choose from legal actions generated by the rule engine and must not bypass validation.

In AI vs AI debug mode, the default policy for manual-resolution effects is `skip_and_log`. Approximation by effect tags is allowed only in explicit experimental mode, and silent auto-resolution is forbidden. Excluding manual-resolution cards from the fully automated card pool may be supported as another explicit run policy.

Future AI may use structured and reviewed executable effects more deeply.

AI must treat `test_validated_executable` as stronger than unreviewed execution, but not equivalent to `reviewed_executable`.

## 12. Monte Carlo Simulation Relationship

Monte Carlo simulation and AI simulation are related but not identical.

Deck Analyzer may use Monte Carlo draws to estimate consistency without full gameplay. Battle Simulator may use AI vs AI or policy-driven games to estimate matchup behavior.

Both should share:

* deck data
* validation logic
* deterministic randomness
* repeatable run configuration
* clear output assumptions

Monte Carlo results should always state their assumptions.

## 13. Why AI Must Not Bypass Rule Validation

AI must use the same legal action system as human players.

If AI bypasses validation, then:

* debug games become untrustworthy
* matchup simulations become invalid
* replay logs become hard to verify
* future online validation diverges from local simulation
* bugs may be hidden by AI-only shortcuts

The controller chooses. The rule engine validates and resolves.

## 14. Official-Rule Conformance Acceptance

Simple AI policy changes should pass a separate rule-conformance acceptance run in addition to strength benchmarks. The maintained acceptance gate:

* drives both players exclusively through `LegalActionGenerator`
* records before/after state, Action, Events, decision reason, and rule references
* validates zone ownership, revision progression, Live Heart and score resolution, match-point ties, final victory, effect snapshot binding, Japanese semantic-operation alignment, and Replay identity
* requires at least 10 matches to finish within 10 turns while both players complete at least one Live
* treats any illegal Action, effect-error skip, failed semantic check, or Replay mismatch as disqualifying

Live judgment has 20 post-Heart score/movement regressions, with native Action
and SQLite Replay checks. They distinguish Live success, success-effect timing,
performance winner, placement eligibility and whole-match result. Four fixtures
use synthetic effects; four Match Point cases remain rule-text review items
because PDF 8.4.7.1's area wording differs from the existing Success Live count
interpretation. The engine remains unchanged. These cases are not a claim that
Heart allocation, Yell, end-phase loops or all official rulings are certified.
See [the maintained evidence boundary](development/live-boundary-matrix-verification.md).

The maintained run completed 20/20 matches and qualified 12/20. It produced 14,160 passing checks and exercised 64 distinct effects over 260 effect decisions or resolutions. This is path evidence, not proof for effects that did not trigger.

Policy optimization must use mirrored fixed-deck and fixed-seed comparisons. Two initial v1.2 experiments that increased Live conservation or generic draw/recovery priority were rejected: both completed 80/80 matches, but challenger points rates were 48.75% and 47.50%, and both reduced Live success rates. A third 40-match bounded Member-placement lookahead experiment reached only 50.00% points; it improved Live successes from 84/139 to 85/139 while increasing decision P95 from 13.96ms to 104.07ms. `simple_ai_v1_1` therefore remains the best tested deterministic policy until a stronger candidate passes the same gate.

## 15. Future Advanced AI

Future advanced AI may support:

* stronger heuristic evaluation
* matchup-specific strategy
* Monte Carlo search
* policy comparison
* self-play experiments
* deck improvement suggestions

Advanced AI should remain a layer above the shared rule engine. It should improve choices, not redefine legality.
