# TODO

## High Priority

### 本机持续开发的节能与唤醒（暂缓实施）

- 2026-10-25 决定：出差期间保持现有持续开发，不启用自动睡眠、不迁移开发 VPS。
  2026-10-27（周二）22:00 JST 提醒维护者复查方案；提醒后仍需确认才修改电源设置。
- 先采用 Windows 任务计划程序定时唤醒；任务运行期间保持唤醒，网络恢复后从持久检查点续跑。
- LoveCA 与 boatrace 共用全局忙闲协调器：无有效写入租约、测试 / build / importer 进程，
  且用户未使用电脑时才允许睡眠；不得用没有键鼠输入或 CPU 暂时空闲代替任务状态。
- 设置明确的每日工作窗口 / 运行预算；睡眠前完成检查点，不能为准时睡眠强杀任务。
- 本机只读基线：支持 S3 / 休眠；接电自动睡眠已为“从不”，唤醒定时器仅允许重要任务；
  电池自动睡眠为 10 分钟，唤醒定时器禁用。目前没有已配置的设备唤醒来源。
- 先验收短时间睡眠 → 自动唤醒 → 网络恢复 → 开发续跑，再连续观察三晚；另测锁屏和重启恢复。
- 远程唤醒留作第二阶段：确认网卡 / BIOS，优先使用私有网络和路由器 / NAS 中继，
  不向公网开放 RDP 或唤醒端口，不保存生产密钥或复制 GPT 认证到外部主机。
- 本项仅记录 TODO，未加入自动实施队列；现有 LoveCA 持续开发任务保持启用。

### 持续开发与遗留收敛

- 自动推进入口固定为 `codex/continuous-development`，规则和队列见 `automation/`。
- 先对比旧 v0.9 工作树的 44 项未提交 Ruleset / 规则矩阵改动，再核对旧 API Play 的 6 项改动。
- 保留其原始工作树和报告，逐项迁移验证；不得直接全量合并旧实验或删除 dirty worktree。
- 已完成来源档案切片：只读 Ruleset、49 条 PDF 引用、稳定指纹和未审 FAQ 隔离，详见
  `docs/22-ruleset-source-profile-migration.md`。后续依次接入 Match/Replay 身份、End Phase /
  规则矩阵，再收敛 API Play；不把旧卡池通过结论直接当作当前证据。
- 后续按任务队列推进 AI 长局、技能准确度和 v0.9 门禁；不再为每轮自动任务开分支。
- API Play 旧提交已分组核对，测试输入/采样入口完成选择性迁移；`PL!-bp5-003:2` 成本结果
  分支已按当前文本重建，并增加两分支状态 / AI / Replay 和观察视角测试。
  当前为 903 / 1212 可执行（74.50%），见 `docs/development/cost-result-branch-verification.md`。
- 下一步复核 `PL!-PR-015:1` / `PL!SP-PR-020:1` 的 Baton 手牌登场，不直接搬运旧 executable
  登记；旧工作树和原始报告继续保留。

### AI-DLC Rollout Validation

- Use the pinned AI-DLC workflow for the next rule-engine bugfix, normal feature,
  and infrastructure change, then review whether scope selection and approval
  gates produced useful artifacts without duplicating existing specs.
- Keep `python scripts/aidlc_vendor.py verify` and the official doctor green.
- Add only reviewed project learnings to `team.md` / `project.md`; do not turn
  one-off implementation details into permanent rules.
- Review each upstream AI-DLC release before upgrade and never overwrite the
  LoveCA branch, deployment, language, or rule-conformance adaptations.

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
- After the October 2026 full official refresh through CLLS01/PBLL02, static registry coverage is `902 / 1212 = 74.42%`; strict integrity reports zero errors and warnings. The lower percentage reflects every newly discovered timing segment being registered, including 310 intentionally manual entries. Reaching 90% requires real executor patterns and state-transition tests; do not restore the old percentage by hiding or falsely promoting new text.
- Do not mark registry entries executable only to improve coverage numbers.
- Keep the official-rule AI acceptance gate at 20 attempts / 10 strict qualified matches. The October full-refresh gate completed 20/20, qualified 13/20, and produced 13,539 PASS checks over 61 distinct effects / 212 effect steps with no failure, Replay error, or effect-error skip; two steps remain review annotations.
- The latest 30-deck / 50-match black-box run completed 314/314 executable effect resolutions with no skipped effect or Replay error, but only 34/50 matches reached a result. Prioritize Live-access and long-game policy diagnostics for the 16 action-cap matches instead of treating them as registry blockers.
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
  - BP07 `無2` special Blade Heart semantics, pending an official rule/ruling
  - mandatory Waiting Room return followed by optional deployment of that same selected Member (`PL!S-bp7-007:1`)
  - BP07/NSD02 compound effects whose conditions or target relations are not represented by the restricted executor
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
