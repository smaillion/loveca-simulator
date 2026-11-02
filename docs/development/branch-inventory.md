# 分支与工作树清单

## 当前使用约束

- 持续开发只写入 `codex/continuous-development`，固定目录为主仓库的 `.tmp/continuous-development`，不按轮次新建分支。
- 分支/PR 目标以 [policy](../../automation/policy.json) 和 GitHub 实际状态为准；运行租约、任务进度以协调器 `status` 为准。
- 当前固定审查目标的授权见 [PR55 验收](./draft-pr55-target-verification.md)。PR54 已完成历史合并，不能再当开放目标或复用其上线许可。
- 推送不等于合并或部署。目标关闭、合并、转为非 Draft 或 head/base 改变时停止 publish，不自行建立替代 PR。
- 旧 v0.9 的 44 项、API Play 的 6 项未提交成果及 ignored 报告必须保留；历史备份 stash `68e4666ec45c41bbddf0603d571cb0f286b853aa` 不清理。
- 本页只维护分支职责与保留约束。逐卡进展统一查[专题导航](./README.md)，不再向清单追加审计流水。

需要最新清单时，在固定工作树运行 `python -m tools.development.loop inventory --output .tmp/worktree-inventory.json`。
该输出是本机只读盘点，不是允许删除工作树的授权。

## 历史盘点（不是当前状态）

以下表格保留 2026-10-25 06:57 UTC 的原始快照。领先/落后、dirty 数量和路径均为当时值；
不要用它们覆盖当前 Git 或 runtime，也不要把 ahead=0 当作可删除 ignored 证据。

当时删除了 9 个已合入 develop 且无工作树占用的本地旧 ref，其他现场保留。
旧 v0.9 / API Play 的迁移范围见[来源档案迁移](../22-ruleset-source-profile-migration.md)和[API Play 迁移](./legacy-api-play-migration.md)。
2026-10-27 的 PR54 恢复已保存 WIP、核对快进结果并保留备份 stash；之后 PR55 固定目标已独立验收。

<details>
<summary>2026-10-25 工作树与分支原始表格</summary>

### 工作树

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

### 分支

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

</details>
