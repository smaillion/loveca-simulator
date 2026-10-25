# 分支与工作树清单

生成时间（UTC）：2026-10-25T06:57:14.815226+00:00。基线：`origin/develop`。
本地分支 32 个；工作树 14 个。

本次已删除 9 个完整合入 develop、且没有工作树占用的本地旧分支引用。
历史工作树与 ignored 报告尚未删除；当前只有 continuous-development 是自动任务写入入口。
`git cherry` 已确认 aidlc-workflow-adoption 的 1 个提交和
v0-9-card-sync-effects-ai-reliability 的 3 个提交与当前分支 patch 等价，不需要再次迁移。
优先核对 v0-9-rule-conformance-beta 的 44 项、phase5-api-play-coverage-next 的 6 项未提交改动。
远程仍有旧 PR #27（develop Draft）、#28（preview）、#38（test）；本次不自动关闭它们。

2026-10-25 迁移检查点：旧 v0.9 的 44 项与 API Play 的 6 项 dirty 内容均已只读清点；
只选择性迁移 Ruleset 来源定义 / JSON / 测试 / spec，并修正路径相关指纹与未审 FAQ 激活。
未提交原文件和 ignored 报告未改动、未删除。其他内容仍待队列逐批迁移；不视为已收敛。
详细范围见 `../22-ruleset-source-profile-migration.md`，后续任务见 `automation/queue.json`。

API Play 检查点：16 个旧提交已按功能分组核对，选择性补回 CLI 预检/采样入口，并修正
测试输入中的对手背面卡和他方 private choice 暴露。6 项 dirty 原型仍保留，成本分支与
Baton 手牌登场登记另列任务，不直接继承旧 executable 状态。见 `legacy-api-play-migration.md`。

成本分支检查点：已选择性重建 `PL!-bp5-003:2`，修正旧原型的费用 ID 清空、可选回收数量
和非本分支操作混入问题；旧 6 项 dirty 文件仍原样保留。剩余 Baton 原型继续独立复核。
见 `cost-result-branch-verification.md`。

## 工作树

| 分支 | 领先 / 落后 develop | 未提交文件 | 处理方式 | 路径 |
|---|---:|---:|---|---|
| `codex/new-card-pack-update` | 0 / 12 | 1 | 未提交成果，必须保留 | `E:\Repository\loveca-simulation` |
| `codex/fix-priority-card-activations` | 1 / 41 | 1 | 未提交成果，必须保留 | `C:\Users\HanX_\.codex\worktrees\65b5\loveca-simulation` |
| `detached` | 5 / 58 | 1 | 未提交成果，必须保留 | `C:\Users\HanX_\.codex\worktrees\ad90\loveca-simulation` |
| `codex/hotfix-room-lifecycle-cleanup` | 1 / 92 | 0 | 有独有提交，待对比迁移 | `E:\Repository\loveca-hotfix-room-cleanup` |
| `codex/release-rollback-protection` | 2 / 96 | 0 | 有独有提交，待对比迁移 | `E:\Repository\loveca-simulation-worktrees\release-rollback-protection` |
| `codex/v0-9-rule-conformance-beta` | 0 / 0 | 44 | 未提交成果，必须保留 | `E:\Repository\loveca-simulation-worktrees\v0-9-rule-conformance` |
| `codex/ai-rule-audit-10-match` | 0 / 1 | 0 | 已合并历史，报告核对后归档 | `E:\Repository\loveca-simulation\.tmp\ai-rule-audit-10-match` |
| `codex/aidlc-workflow-adoption` | 1 / 0 | 0 | 有独有提交，待对比迁移 | `E:\Repository\loveca-simulation\.tmp\aidlc-workflow-adoption` |
| `codex/continuous-development` | 4 / 0 | 13 | 唯一活跃主线 | `E:\Repository\loveca-simulation\.tmp\continuous-development` |
| `codex/local-simple-ai-stabilization` | 0 / 9 | 0 | 已合并历史，报告核对后归档 | `E:\Repository\loveca-simulation\.tmp\local-simple-ai-stabilization` |
| `codex/phase5-api-play-coverage-next` | 16 / 25 | 6 | 未提交成果，必须保留 | `E:\Repository\loveca-simulation\.tmp\phase5-api-play-next` |
| `codex/simple-ai-v1-1-registry-integrity` | 0 / 3 | 0 | 已合并历史，报告核对后归档 | `E:\Repository\loveca-simulation\.tmp\simple-ai-v1-1-registry-integrity` |
| `codex/simple-ai-v1-effect-accuracy` | 0 / 6 | 0 | 已合并历史，报告核对后归档 | `E:\Repository\loveca-simulation\.tmp\simple-ai-v1-effect-accuracy` |
| `codex/v0-9-card-sync-effects-ai-reliability` | 3 / 0 | 0 | 有独有提交，待对比迁移 | `E:\Repository\loveca-simulation\.tmp\v0-9-card-sync-effects-ai-reliability` |

## 分支

| 分支 | 领先 / 落后 develop | 被工作树使用 |
|---|---:|---|
| `backup/hosted-online-mvp-preview-base` | 11 / 128 | 否 |
| `backup/phase5-sandbox-driver-preview-base` | 11 / 128 | 否 |
| `codex/add-manual-waiting-room-return` | 1 / 73 | 否 |
| `codex/admin-phase5-big-patch` | 1 / 25 | 否 |
| `codex/ai-rule-audit-10-match` | 0 / 1 | 是 |
| `codex/aidlc-workflow-adoption` | 1 / 0 | 是 |
| `codex/area-move-rules` | 1 / 73 | 否 |
| `codex/continuous-development` | 4 / 0 | 是 |
| `codex/deploy-rollback-on-failure` | 1 / 73 | 否 |
| `codex/fix-activated-effect-buttons` | 1 / 73 | 否 |
| `codex/fix-hand-to-waiting-room-options` | 1 / 73 | 否 |
| `codex/fix-hide-opponent-hand` | 1 / 73 | 否 |
| `codex/fix-priority-card-activations` | 1 / 41 | 是 |
| `codex/fix-skill-text-heart-labels` | 1 / 73 | 否 |
| `codex/fix-waiting-room-choice-labels` | 1 / 73 | 否 |
| `codex/hotfix-room-lifecycle-cleanup` | 1 / 92 | 是 |
| `codex/local-simple-ai-stabilization` | 0 / 9 | 是 |
| `codex/new-card-pack-update` | 0 / 12 | 是 |
| `codex/pages-preview-release` | 1 / 128 | 否 |
| `codex/phase5-api-play-coverage` | 16 / 25 | 否 |
| `codex/phase5-api-play-coverage-next` | 16 / 25 | 是 |
| `codex/preserve-member-play-area` | 1 / 73 | 否 |
| `codex/preview-deck-transfer` | 10 / 128 | 否 |
| `codex/release-rollback-protection` | 2 / 96 | 是 |
| `codex/simple-ai-v1-1-registry-integrity` | 0 / 3 | 是 |
| `codex/simple-ai-v1-effect-accuracy` | 0 / 6 | 是 |
| `codex/speed-up-pages-preview` | 1 / 73 | 否 |
| `codex/v0-9-card-sync-effects-ai-reliability` | 3 / 0 | 是 |
| `codex/v0-9-rule-conformance-beta` | 0 / 0 | 是 |
| `develop` | 0 / 27 | 否 |
| `main` | 0 / 134 | 否 |
| `preview` | 3 / 128 | 否 |

`ahead=0` 仅说明提交已包含在 develop；不代表工作树中的未提交文件或 ignored 报告可以删除。
dirty、独有提交与无法读取的工作树全部保留。常规自动任务只使用 continuous-development。
