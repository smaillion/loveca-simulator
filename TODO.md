# TODO

## High Priority

### AI Live 获取与旧脚本长局（继续）

- 可选v1.2已补无Live时富余Member换牌；固定20套牌50局完赛，前10局达到双方成功Live且10回合内结束。
- 默认仍v1.1。扩大同池镜像强度/资源代价比较，再决定是否改默认，不把小样本称为最优策略。
- 旧30套牌/50局已支持可选共用controller：同260步，legacy仍34完赛、v1.1为42、v1.2为48；旧16个上限案例在v1.2下均结束，另2局需280/337步。默认脚本和产品策略均未切换。
- v1.2在seed9008/9029实际记录3次`PL!N-bp7-027:1`手动skip；优先按当前精确卡文适配双方Stage Blade严格比较，不把skip对局算作全技能合规。
- 十局逐步规则审计仍有1项review；继续人工核对和补真实状态断言，不提升registry审核状态。

### Codex Cloud 开发交接（已准备，未切换）

- 入口见 `automation/CLOUD.md` 与 `docs/development/codex-cloud-handoff.md`；
  Linux setup、白名单 checkpoint、普通 checkout 和固定 PR #54 校验已加入。
- 当前 active_environment=local；维持本机调度，不复制认证和 runtime，不启用第二个写入者。
- 维护者在 Cloud 选择同一仓库 / 分支，私人环境，Python 3.12 / Node 24 / gh，先只读预检。
- 实测 GitHub 写入能力、Linux 全量门禁、恢复及定时能力后，再批准暂停本机并切换 cloud。
- 旧 dirty 工作树 / ignored 报告未上传，缺少输入的遗留任务不能声称迁移完成；生产 VPS 不变。

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

- 已修正 `PL!N-bp3-005:1` 第3次登場的事件计数，不再读作第3次及以后；待机后保存触发资格，
  旧effect snapshot和第二段“2回以上”保留。见 `docs/development/third-entry-observer-verification.md`。
- 当前固定10局仍仅7局满足10回合且双方成功Live；将既有 `ai-long-game-reliability` 提到下一优先项，
  先归因seed12004的19回合、12005/12009的单边零Live，再复核旧50局基线，不反复运行不变的10局刷通过。
  完整继承/重叠父任务继续保留；临时文本revision477/478仅外层引号不同的来源选择另需审计，不改库或自动换hash。
- 已完成 `stage-departure-modifier-cleanup` 有限切片：普通替换 / Baton / 受控效果登场 /
  手动离场清理旧卡和一同离场附属卡的定向补正；Stage内移动、玩家整体补正和旧 Replay 不变。
  真实花帆获得2Blade后离场回场、SQL Replay与三policy已验证，见
  `docs/development/stage-departure-modifier-verification.md`。
  其他 zone-move 操作、继承、来源依赖离场前信息及完整重叠调度仍由父任务审计；六卡继续manual。
- 自动推进入口固定为 `codex/continuous-development`，规则和队列见 `automation/`。
- 先对比旧 v0.9 工作树的 44 项未提交 Ruleset / 规则矩阵改动，再核对旧 API Play 的 6 项改动。
- 保留其原始工作树和报告，逐项迁移验证；不得直接全量合并旧实验或删除 dirty worktree。
- 已完成来源档案切片：只读 Ruleset、49 条 PDF 引用、稳定指纹和未审 FAQ 隔离，详见
  `docs/22-ruleset-source-profile-migration.md`。后续依次接入 Match/Replay 身份、End Phase /
  规则矩阵，再收敛 API Play；不把旧卡池通过结论直接当作当前证据。
- 后续按任务队列推进 AI 长局、技能准确度和 v0.9 门禁；不再为每轮自动任务开分支。
- API Play 旧提交已分组核对，测试输入/采样入口完成选择性迁移；`PL!-bp5-003:2` 成本结果
  分支已按当前文本重建，并增加两分支状态 / AI / Replay 和观察视角测试。
  该切片当时为 903 / 1212；效果登场复核后当前为 899 / 1212（74.17%）、313 manual。
- `PL!-PR-015:1` / `PL!SP-PR-020:1` 已完成旧原型复核并修正手动提示条件，仍为 manual。
  `effect-empty-deployment-active-ui-ai` 已将明确空区域的 6 条技能改为 Active 并补位置选择，
  另 4 条不限定空区域的虹咲技能已退回 manual，旧 Replay 保留原朝向。
  下一步 `effect-deployment-rule-conformance` 仍需实现已有 Member 区域替换、入场身份追踪及附属卡 / 离场处理；
  再复核上述虹咲 4 条和两张 PR 卡，不得只恢复旧标签。见 `docs/development/empty-effect-deployment-verification.md`。
  详见 `docs/development/baton-hand-deploy-audit.md`；旧工作树和原始报告继续保留。
- `member-entry-current-area-history` 已补新对局的卡牌身份记录，覆盖位置 / 阵型改变后的
  当前区域限制、附属 Member 与 Stage 内转移的区分；旧快照缺省仍使用原区域历史。
  见 `docs/development/member-entry-area-history-verification.md`。
- 原 `attachment_promotion_onplay_trigger_and_entry_count_requires_rules_audit` 已按固定 PDF 完成
  有限程序修正：新 effect snapshot 不误发外部登場，旧快照兼容；不视为人工 reviewed。
  见 `docs/development/attachment-promotion-verification.md`。
- `multi_player_deploy_waiting_member` 的真实登记 `PL!-pb1-018:1` 已补双方选择后的同时 Wait 登場，
  目标登場 / 己方登場观察者两项受控抽牌各 +2，AP/NAP 与新旧 Replay 均有回归。
  见 `docs/development/multi-player-entry-verification.md`；后续继续已有 Member 区域的效果替换登场，
  以及一般同时触发的自由排序，不宣称通用登場底座已经全部完成。

- 受控 `deploy_selected_to_stage` 底座已完成独立状态验证，但没有绑定正式卡牌。
  完整的检查时点重叠、出场观察者、继承和私有手牌零张选择仍由父任务追踪；
  两张 PR / 四条虹咲保持 manual。见 `docs/development/occupied-deployment-foundation.md`。
- 非公开手牌零目标已完成独立子切片：显式 snapshot 策略、费用边界、UI / 三种 AI / Replay 与
  双方隐私已验证，见 `docs/development/private-hand-choice-verification.md`。完整重叠 / 离场观察者 /
  继承时点仍由 `effect-overlap-trigger-and-private-choice` 追踪，六张卡未晋级，登记仍899/1212。
- 已补普通替换清理前的有限固定抽牌观察者：真实 `PL!N-pb1-005:1` 普通替换抽1、Baton 不抽，
  新对局启用而旧 Replay 保留历史行为。见 `docs/development/overlap-entry-observer-verification.md`。
  临时场面、条件式/常时/继承仍在父任务中，不把该修复当作完整重叠底座。
- 新对局已补待机队列的 AP/NAP 顺序选择与多步处理锁定：实际抽牌顺序影响最终手牌，
  旧快照保留历史行为，UI / 三种 AI / Replay 已验证。见 `docs/development/pending-effect-order-verification.md`。
  这不是一般规则处理与任意瞬时重叠调度；六张卡继续 manual，父任务尚未完成。
- 已补 `PL!N-pb1-012:1` 固定 Wait Energy 观察者：普通替换后继续处理，附属能量先返还后可补入；
  新 overlap policy 保留 None / fixed-draw 旧 Replay，无牌可补有明确结果。见
  `docs/development/overlap-energy-observer-verification.md`。来源位置/属性、条件式离场、继承与
  一般瞬时重叠仍在父任务中，六张待审卡不晋级。
- 已补 `PL!HS-pb1-009:1` 中心观察者的显式 operation snapshot 策略：普通替换后保留待机，
  不向控室/重入场对象应用本次自身 Blade，次数仍计入。见 `docs/development/overlap-source-modifier-verification.md`。
  非重叠来源对象、完整 Stage 条件、继承及其他旧 modifier 清理列为 unresolved；不视为通用对象追踪已完成。
- 已修复：`PL!SP-bp5-111:2` / `PL!SP-pb2-010:1` 的 Energy 回牌库空朝向，
  验证真实费用 / 分支 / runtime Replay；旧坏快照拒绝读取且不改写，API / SSE 错误不泄露私有信息，
  前端显示诊断并停止重试。见 `docs/development/energy-return-replay-verification.md`；不改 schema。

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
