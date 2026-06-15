# TODO

## Low Priority

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
