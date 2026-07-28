# TODO

## High Priority

### Develop-Based Branch Hygiene

- Keep all new feature branches based on `develop`.
- Keep `preview` as an independent public GitHub Pages preview branch.
- Do not create regular feature branches from `preview` or preview-only branches.
- If a branch is accidentally based on preview history, replace or rewrite it onto `develop`.
- Current cleanup target: keep `codex/hosted-online-mvp` and `codex/phase5-sandbox-driver` develop-based, with `preview` retained separately.

### Hosted Online MVP Stability

- Verify room create / join through the hosted FastAPI API.
- Verify HTTP polling, stale revision rejection, action submission, replay export, and expired room cleanup.
- Verify CORS with the planned public frontend origin.
- Verify Cloudflare Tunnel health and API health checks.
- Keep user deck data local to the client; do not add accounts or cloud deck storage.

### Frontend Hosting Transition

- Stage A: VPS temporarily serves frontend and backend during online flow testing.
- Stage B: GitHub Pages or another static host serves the frontend while VPS serves only backend API.
- Stage C: official frontend distribution comes from stable `develop` or `main`; VPS frontend serving is disabled.
- Build official online frontend with `VITE_HOSTED_API_BASE_URL` pointing at the hosted API.

### Preview Retirement Plan

- Keep the current `preview` branch available until hosted online is stable.
- Do not use the old preview branch as the long-term official product entry.
- After online is stable, replace the public frontend distribution with a stable `develop` or `main` build connected to hosted API.
- Archive or treat `preview` as a historical snapshot after the official frontend transition.

### Main Branch Publishing Revisit

- Keep `main` push-triggered publish / deploy disabled while release promotion remains manual-only.
- Revisit whether `main` should regain automated publishing after the official release branch policy is finalized.
- If automated `main` publishing returns, document the required release gate, smoke checks, rollback path, and maintainer approval rule before changing CI triggers.

### Phase 5 Sandbox Follow-Up

- Continue tuning `tools/ai_sandbox/blackbox_playtest.py` action caps and strategies.
- Keep `30 decks x 100 matches --manual-policy block` as the standard long-run regression after each executor-pattern expansion.
- Latest broad Phase 5 long run: `100/100` completed with blocker 0 after the stale-trigger-condition fix.
- The earlier problem-card blockers `PL!S-bp6-001:1` and `PL!S-pb1-001:1` are now structured. Future targeted pools should be generated from the current 115-entry manual gap report instead of preserving this obsolete blocker list.
- Static registry coverage is now `864 / 979 = 88.25%`; the strict integrity audit reports zero errors and warnings. Reaching 90% still requires real executor patterns for the remaining 115 `manual_resolution` entries.
- Do not mark registry entries executable only to improve coverage numbers.
- Keep the official-rule AI acceptance gate at 20 attempts / 10 strict qualified matches. The latest run completed 20/20, qualified 12/20, and produced 14,160 PASS checks with no Replay error.
- Keep the 9-case Live judgment boundary matrix as a release gate. Extend it when card text or FAQ adds a new score-comparison or Success Live placement exception.
- Implement and audit the repeated turn-end automatic-effect check loop from comprehensive rules 8.4.10-8.4.12 before claiming full End Phase coverage.
- The next AI strategy experiment should use a cached probabilistic Live-access model or a narrower tie-breaker. Naive Live conservation, flat draw/recovery bonuses, and uncached one-action Member placement lookahead all failed to beat `simple_ai_v1_1` and must not be restored without a new mirrored benchmark.

## Low Priority

### Mobile UI Sandbox Feedback

- Run dedicated mobile viewport checks for 390 x 844 and 430 x 932 after hosted room UI stabilizes.
- Pages to check: start / online room create / room join, Deck Builder, Match board, Action Dock, pending effect panel, Manual Adjustment drawer, Card detail dialog, Live judgment detail panel, Event Log.
- Fix blockers immediately: horizontal overflow, unclickable buttons, modal/drawer that cannot close, hidden submit controls, or Action Dock covering required game zones.
- Record visual-only issues separately so they do not block Phase 5 engine work.

### Effect Prompt UI Known Issues

- Branch-choice effects now have a basic UI path, including branch-specific
  card candidates and position-change slot selection.
- Remaining UI work should focus on clarity, not baseline availability:
  - make branch labels shorter and more readable on mobile
  - keep selected branch context visible while resolving follow-up choices
  - improve error copy when a branch becomes unavailable after earlier choices
  - add compact visual hints for auto-resolved effects and special Yell effects

### Phase 5 Effect Coverage Follow-Up

- Continue Live-start and Live-success exact-text coverage for effects that can
  be fully represented without FAQ-sensitive interpretation.
- Current unresolved registry families include:
  - Yell-count modifiers such as reducing the number of cards revealed by Yell
  - base Heart rewrites such as "元々持つハートをすべて..."
  - base Blade rewrites such as "元々持つ【ブレード】の数は3つになる"
  - named-member temporary Heart / Blade grants that affect multiple specific
    members with different modifiers
  - effects that disable or grant other effects
  - movement-history effects that require Baton-specific history or selected
    members; simple moved-this-turn Member counting now has partial coverage
  - Energy-threshold compound effects mixing placement and static modifiers
  - answer-based effects
  - compound optional branch effects with different target families
  - more complex branch effects after the exact
    `【ライブ開始時】【E】【E】支払わないかぎり、自分の手札を2枚控え室に置く。`
    pay-or-discard pattern
  - Live-start inspect / reveal effects that derive temporary Heart colors from
    revealed cards
- Because the broad long-run sandbox completes without blockers but targeted
  problem-card decks still expose manual blockers, prioritize repeated
  static/manual families only when they are likely to appear in real decks or
  improve manual-play usability.
- Keep `manual_resolution` for these families until the missing semantic slot is
  explicitly modeled; do not mark partial branches as `test_validated_executable`.

### AI Sandbox Strategy Follow-Up

- Keep improving the sandbox controller so it continues to expose deeper rule
  blockers instead of overfitting to the current deck pool.
- Latest broad long-run baseline: block mode can complete 100/100 matches with
  no blocker. Targeted problem-card smoke still finds Aqours manual blockers,
  so the next useful sandbox work is broader deck diversity, targeted deck pools,
  and semantic user-agent comparison, not only increasing `max_actions`.
- Next strategy work:
  - tune the current work/Heart-synergy deck generator so generated decks become
    closer to practical deck construction without hiding real rule blockers
  - prefer higher-score Live sets when multiple Live cards are available
  - prefer Live cards with reachable Heart requirements
  - report final success Live counts and skipped effect IDs for every sandbox
    run, then use those fields to distinguish low-success deck construction
    from unresolved effect semantics
  - make success Live selection deterministic but progress-oriented
- Add the semantic user-agent sandbox to the standard Phase 5 loop:
  - run deterministic `blackbox_playtest` first for reproducible blockers
  - run `semantic_playtest` second to classify whether a human-like tester can
    express unresolved mandatory effects through current `ManualAdjustmentAction`
  - treat `manual_resolved_by_agent` as a playability signal only, not registry
    coverage
  - triage repeated `schema_gap` entries into either new structured executors or
    deliberate manual-only rule review items
  - keep CI on the `mock` provider; real OpenAI-compatible providers are manual
    local runs because they depend on external configuration and cost

### Simple AI Follow-Up

- `simple_ai_v1_1` now adds Match Point Live preservation, conservative Stage replacement, structured effect scoring, hidden-information-safe observations, and compact decision timing logs while retaining v0 / v1 for old snapshots.
- Corrected 200-match mirrored v1.1-v1 benchmark: 200/200 completed, v1.1 points 54%, average 8.38 turns, P95 14 turns, decision P95 6.975 ms, no illegal action or Replay error, and 19 explicit unsupported-effect skips. The 55% strength target remains open.
- Keep Simple AI deterministic and LegalAction-only; do not add direct GameState mutation or hidden opponent-hand inspection.
- Use the archived 200-match mirrored v1-v0 benchmark as the policy regression baseline; investigate only repeated weaknesses across multiple deck/seed pairs.
- The 30-deck / 100-match skill-dense regression now completes 100/100 matches with zero blocker, silent skip, or Replay error; preserve these exact match indices as a regression pool for future policy changes.
- Continue strategy work only when a larger mirrored pool shows a repeated weakness; do not tune against a single seed.
- Keep the human recovery path for mandatory manual effects explicit and replay-safe.
- Add a focused browser smoke that reaches and observes at least one full CPU turn; the long 20x20 acceptance remains a manual release gate rather than normal CI.
- Browser-only static preview still has no TypeScript rule engine; Simple AI requires local or Hosted FastAPI until that engine is intentionally ported.

### UI Consistency Pass

- Unify the overall UI style across the React SPA.
- Normalize button sizing, font sizes, icon usage, spacing, and visual hierarchy.
- Make repeated content types use the same display pattern across Deck Builder, catalog, and match views.
- Write the resulting UI conventions into the project guidance before applying broad visual refactors.

Notes:

- Current UI is functional but visually uneven after rapid iteration.
- This should be handled as a dedicated design-system pass, not mixed into rule engine or importer work.

### Post-1.0 README Screenshot Refresh

- Update the screenshots in `README.md` and `README.zh-CN.md` to the latest Japanese UI.
- Execute this after the `1.0` release, not during the current alpha stabilization work.
