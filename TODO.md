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

### Phase 5 Sandbox Follow-Up

- Continue tuning `tools/ai_sandbox/blackbox_playtest.py` action caps and strategies.
- Run 50-match and 100-match regression loops after the next executor-pattern expansion.
- Raise rough executable coverage toward 40% only by adding supported executor patterns and tests.
- Do not mark registry entries executable only to improve coverage numbers.

## Low Priority

### Mobile UI Sandbox Feedback

- Run dedicated mobile viewport checks for 390 x 844 and 430 x 932 after hosted room UI stabilizes.
- Pages to check: start / online room create / room join, Deck Builder, Match board, Action Dock, pending effect panel, Manual Adjustment drawer, Card detail dialog, Live judgment detail panel, Event Log.
- Fix blockers immediately: horizontal overflow, unclickable buttons, modal/drawer that cannot close, hidden submit controls, or Action Dock covering required game zones.
- Record visual-only issues separately so they do not block Phase 5 engine work.

### Effect Prompt UI Known Issues

- Branch-choice effects are not yet rendered as a clear choice control in the
  match UI.
- Example pattern:
  `【登場】以下から1つを選ぶ。 ・カードを1枚引き、手札を1枚控え室に置く。 ・相手のステージにいるすべてのコスト2以下のメンバーをウェイトにする。`
- Backend effect definitions can represent `choose_effect_branch`, but the UI
  must expose branch selection before asking for branch-specific card choices.
- Keep this as a high-value Phase 5 UI task because it blocks realistic manual
  validation for registered dual-choice skills.

### Phase 5 Effect Coverage Follow-Up

- Continue Live-start and Live-success exact-text coverage for effects that can
  be fully represented without FAQ-sensitive interpretation.
- Current high-frequency unresolved families include:
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
- Keep `manual_resolution` for these families until the missing semantic slot is
  explicitly modeled; do not mark partial branches as `test_validated_executable`.

### AI Sandbox Strategy Follow-Up

- Improve the sandbox controller so `skip` mode can finish more games instead of
  reaching `max_actions`.
- Current issue: `skip` mode avoids `illegal_action`, but the latest
  `30 decks x 50 matches` regression still completed only 12 matches and left
  38 matches at `max_actions`.
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
