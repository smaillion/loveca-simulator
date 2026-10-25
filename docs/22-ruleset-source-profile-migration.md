# Ruleset 来源档案迁移

## 本批范围

后续检查点：已选择性迁移Match/Replay身份绑定，并补上旧原型缺少的拒绝重执行逻辑。
详见[状态与兼容性验证](./development/ruleset-match-replay-verification.md)。
本报告下文保留来源档案初次迁移时的批次边界；等待房间已完成[规则固定与清理](./development/room-ruleset-lifecycle-verification.md)，规则矩阵仍未完成。

2026-10-25 从旧 `v0-9-rule-conformance` 工作树选择性迁移来源档案，而不是合并整份实验。
固定开发分支仍为 `codex/continuous-development`。原工作树的 44 项未提交文件、API Play 的
6 项未提交文件和所有 ignored 报告均保留。父任务仍未完成，后续批次见 `automation/queue.json`。

本批只提供 `RulesetProfile`、来源/条款引用、符合性结果记录和可移植指纹；不接入实际
对局，也不修改 Card Schema、SQLite、HTTP API、MatchState、Replay 或 registry。

## 来源基线

- 官方综合规则：本地 `raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`，ver.1.06，2026-04-28。
- SHA-256：`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
- Profile：`loveca-ja-1.06`；ruling pack：`comprehensive-only-v1`。
- 49 条简短中日条款引用；检查 PDF hash 和全部条款编号确实存在。
- FAQ/Q&A 仅登记为 `source_available_unreviewed`，没有快照 hash，也不属于生效来源。
- `source_confirmed` 表示资料与条款定位已核对，**不是**完整人工规则裁定。

## 对旧成果的修正

旧 fingerprint 会把本地 PDF 路径和 reference 列表顺序算入身份；同一规则换电脑打包可能
得到不同 hash。本批排除本地路径、对 active source/reference 排序，并忽略未启用来源。
规则版本、来源内容 hash、条款摘要或审查状态变更仍会改变指纹。

旧档案把未审 FAQ 列入 source_ids；本批禁止这种启用方式，避免“有链接”等同“已纳入裁定”。
来源、Profile、引用与嵌套集合均只读，拒绝重复标识、未知来源及越界引用。

核对 PDF 后，修正 End Phase 8.4.11-12 的摘要，明确检查循环返回 8.4.9；将 Member
区域限制精确引用到 `9.6.2.1.2.1`，不再用其父条款冒充；`9.6.3` 只概述目标选择时点。
没有据此擅自修改引擎行为；实际状态断言由下一批矩阵任务完成。

## 已核对的迁移边界

| 原成果 | 本批处理 | 后续任务 |
|---|---|---|
| rulesets.py、来源 JSON、规则档案测试、spec 021 | 迁移并重新实现只读/指纹门禁 | 已完成本批 |
| Match/Replay/API/Online 的 Ruleset 字段 | 不搬运 | `legacy-ruleset-match-replay` |
| hosted_rooms 新 ruleset_id 列 | 不搬运，避免直接引入 runtime schema 变化 | 在兼容性任务设计序列化方案 |
| End Phase 循环、核心矩阵、Live 扩展、release gate | 不搬运旧通过结论 | `legacy-core-matrix-and-end-phase` |
| 旧 registry 979 / 864 / 115 manual 与分类 | 不覆盖当前 1212 / 902 / 310 | 用当前卡池重算 |
| 旧 admin bug bundle | 不搬运 | actions/events 的脱敏需要另审 |
| API Play 16 个旧提交与 6 项 dirty 改动 | 已只读清点，不全量合并 | `legacy-api-play-comparison` |

API Play dirty 改动主要是成本驱动分支、branch inspection 和分支过滤；当前引擎已有部分
同名能力，必须先对比后迁移。旧 registry 提升不可直接继承。AI-DLC 与旧卡库刷新提交已
核对 patch 等价，不重复迁移。

## 验证与限制

`tests/test_rulesets.py` 覆盖 31 项：PDF hash/条款定位、只读定义、重复与坏链接、未知
Profile、未审来源隔离、JSON 往返、指纹稳定/变更与旧 Match 序列化不变。

这些是来源/契约验证，**不等于 31 个对局规则场景**，更不是完整人工审核。源码门禁由
持续协调器记录真实命令、退出码、日志与源码指纹；全量检查必须通过后才发布本批。

下一批接入 Ruleset 对局身份及 Replay 不匹配保护，再迁移规则矩阵；不在本批声称
v0.9 的 75/20 门禁或 online 规则兼容性已完成。
