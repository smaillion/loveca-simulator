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
