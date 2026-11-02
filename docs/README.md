# 文档导航 / ドキュメント案内

[日本語 README](../README.md) · [中文 README](../README.zh-CN.md) · [变更记录](../CHANGELOG.md) · [专题证据](./development/README.md)

这里是文档入口，不是另一份项目状态表。README 面向使用者，设计与契约留在原文档，逐卡证据保留原路径。
日本語の利用案内は README、個別の検証記録はテーマ別索引から参照できます。

## 从哪里开始

| 目的 | 入口 |
|---|---|
| 使用、安装、本地运行 | [中文 README](../README.zh-CN.md) / [日本語 README](../README.md) |
| 项目目标与规划 | [愿景](./00-project-vision.md)、[路线概要](./05-development-roadmap.md)、[阶段交付与退出条件](./07-roadmap-expanded.md) |
| 理解系统与契约 | [架构](./06-architecture-overview.md)、[术语](./02-domain-glossary.md)、[规格目录](../specs/) |
| 卡库维护 | [数据模型](./03-data-model-notes.md)、[ERD](./12-card-data-erd.md)、[数据库更新指南](./14-database-migration-and-update-guide.md) |
| 规则与技能 | [规则模型](./04-rule-model-notes.md)、[效果分类](./10-effect-modeling-and-taxonomy.md)、[语义审计基线](./13-effect-semantics-audit.md)、[专题证据](./development/README.md) |
| AI 与 Replay | [AI 设计](./08-ai-and-simulation-notes.md)、[Replay 与联机边界](./09-replay-and-online-readiness.md)、[规则符合性审计](./19-ai-rule-conformance-and-strategy-audit.md) |
| 联机与发布 | [联机方案](./16-low-cost-online-battle-plan.md)、[静态 Preview](./17-browser-only-preview-and-pages-release.md)、[发布检查表](./18-hosted-online-smoke-checklist.md) |
| 开发与维护 | [项目约定](./15-project-guidance.md)、[AI-DLC](./20-ai-dlc-development-workflow.md)、[持续开发](./21-continuous-development.md)、[运行入口](../automation/WORKFLOW.md) |
| 来源与历史迁移 | [来源政策](./01-source-policy.md)、[规格一致性审查](./11-core-spec-consistency-review.md)、[Ruleset 迁移](./22-ruleset-source-profile-migration.md)、[分支保留清单](./development/branch-inventory.md) |

## 如何判断当前状态

| 问题 | 事实来源 | 不应作为替代 |
|---|---|---|
| 谁在运行、下一任务、是否阻塞 | 固定工作树中的 `python -m tools.development.loop status`；主仓库 `.tmp/development-loop/state.json` | 旧 heartbeat 文案、queue 的初始 status、历史 WIP 段落 |
| 允许写哪里、使用哪个 PR | [policy](../automation/policy.json)、实际 Git 分支与 GitHub PR | 旧清单中的 ahead/behind 或开放 PR 编号 |
| 当前技能是否登记、依据是否充分 | [锁定 registry](../data_sources/effect-registry.v0.json)、精确卡文/revision/hash、[专题报告](./development/README.md)及其最终验收 | 原型通过、单个测试数、旧报告中的「下一项」 |
| 检查是否通过 | 对应提交/源码指纹的完整 result.json 与真实 GitHub checks | 不同 run 的部分绿色结果拼接 |
| 是否已上线 | 经批准的发布记录、部署工作流及服务版本证据 | feature push、Draft PR、镜像验证成功 |

PR55 的固定目标授权见[历史验收](./development/draft-pr55-target-verification.md)，实际状态必须重新读取。
PR54 是已执行的历史发布，其许可不能复用。任何合并、部署、生产配置或主机操作仍需明确批准。
本地 `logs/` 中的 ignored 验收、SQL Replay 和图文证据不是公共仓库保证提供的内容；缺失时应说明证据不可访问，不能宣称重验通过。

## 文档职责与更新规则

- README 只保留产品概览、限制、使用和本地开发说明；不追加逐卡流水、每轮测试总数或临时审批状态。
- CHANGELOG 保留双语变更摘要和专题链接，不复制完整测试报告；历史条目不能覆盖当前事实。
- 编号设计文档维护稳定设计与适用边界；`specs/` 维护契约。路线概要说明方向，expanded 文档承载具体阶段标准，不能再建立第三份路线。
- `docs/development/` 保存专题决策与证据入口。同一主题的后续小切片优先补入原报告的日期章节；只有独立语义、依赖或验收范围才新建报告。
- 主题报告区分「当前结论」「未解决依赖」「历史验证」，记录取代关系，不回写旧规则快照，不把旧问题无声删除或自动解除 blocked。
- 分支清单仅记录职责、保留约束和带日期的盘点，不作为业务日报。
- 运行操作只在持续开发指南维护；automation 入口引用它。权威任务进度由协调器更新，禁止手改运行状态。
- 新增/合并文档必须检查相对链接和原入口可达性；被其他文档、脚本或外部记录引用的审计路径先保留，不批量改名。
- 验证规模按变更风险确定。纯文档整理不冒称重跑了应用全量测试；应用、规则、隐私或数据变化仍执行对应完整门禁。

## 本次结构整理（2026-11-01）

维护者要求推送既有成果并整理文档。双语 README 的重复审计流水已收敛到 CHANGELOG 与既有专题；
分支清单保留带日期的原始表格，不再混合当前进度；重复运行说明合并到持续开发指南。
所有原专题报告、ignored 验收及发布记录保持原位，卡库、registry、应用和旧 Replay 不变。

本轮仅验证文档入口、专题覆盖、链接、协调器及 registry 门禁，不增加规则支持率或 AI 完赛声明。
暂不把 119 份现有专题机械合成一篇长报告；后续按主题逐步维护，避免破坏精确证据链。
