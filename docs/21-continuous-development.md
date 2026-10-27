# Continuous Development

## 目标与授权

将项目推进变成持续循环：读取任务 → 领取单个工作租约 → 实现 → 测试 / sandbox / 规则审计 →
保存可复核证据 → 更新同一个 Draft PR → 监控 CI → 修复或继续下一项。

2026-10-25 用户授权持续开发架构与持续推进；普通任务的需求细化、设计、实现、测试、
本地提交、feature push 和 Draft PR 不再逐项请求批准。原有“远程 PR 合并前询问用户”的
项目规则继续有效；生产发布和部署也保留独立审批。

## 单一主线

- 基线：`origin/develop`。
- 活跃分支：`codex/continuous-development`。
- 活跃工作树：主仓库的 `.tmp/continuous-development`。
- 原 `codex/official-card-refresh-2026-10-battle-reliability` 已重命名；数据刷新、技能修复、
  AI-DLC 和测试报告随原工作树迁移，不再保留另一份相同开发副本。
- 最多一个开放的此分支 PR，目标为 `develop`。PR 合并后仍复用相同分支，再同步 develop。
- `preview` 为独立历史发布线；不会成为自动开发的分支根。

## 数据与并发

`automation/policy.json` 记录执行边界和验证命令；`automation/queue.json` 记录已批准方向、
依赖、优先级和验收标准。这两个文件由 Git 版本管理。

运行进度放在主仓库的 `.tmp/development-loop/state.json`，不随分支切换消失，包含任务状态、
租约、测试证据和 PR 地址。SQLite 仅用作跨进程的短事务锁，进程终止后由操作系统释放；
不操作应用的卡牌库或对战 runtime。文件使用临时文件加原子替换保存。

写代码前必须 claim；租约默认 120 分钟，检查运行期间定期续租。重复唤醒不能领取已有
有效租约；过期后恢复原 in_progress 任务。每轮不超过 45 分钟，结束释放租约。

## 发布门禁

- `control`：任务依赖、并发、失败、恢复、证据陈旧、PR 复用等协调器测试。
- `registry`：AI-DLC 固定文件、卡库 manifest、strict integrity。
- `backend`：全量 pytest；开发中先运行变更相关专项测试。
- `web`：Vitest、TypeScript、生产构建。
- 涉及技能 / 策略的任务另要求固定 seed sandbox、AI / Live 规则审计和中文报告。
  协调器记录的工程门禁不能代替这些任务本身的行为验收。

证据包含源码 SHA-256、执行命令、退出码、耗时和日志位置。源码变化后旧证据不能完成任务
或发布；已通过的证据在 Git commit 前后仍有效。发布要求当前工作树没有未提交内容。
启动新检查会先作废旧的绿色记录，中途崩溃也不会保留假成功。检查通过后删除本轮生成的
pytest / 临时 SQLite，只保留检查日志和证据；失败时保留现场便于下一轮修复。

GitHub `Development Gates` 只验证 PR，不合并、不部署、不写回分支；同一个 PR 的旧运行会
被新提交取消。定时接续的模型读取失败日志并在同一分支修复，避免新建“修复 CI”分叉。

## 断点与恢复

- 中断：保留任务和改动，下一次从 in_progress 恢复。
- 源码冲突：保留用户改动，不能自动 reset / checkout 丢弃。
- 网络 / 认证暂时失败：保存本地检查点，下轮重试，不重新开分支。
- 同一失败最多连续修三轮；仍失败则说明复现、原因和下一步，其他队列任务可以继续。
- 所有任务完成时，用当前实测 blocker 和 Roadmap 生成下一批验收明确的任务。
- 普通无变化唤醒不发通知；只报告新成果、CI 故障、阻塞或需要合并批准。

## 运行条件

调度使用当前对话的 Codex 定时接续，默认每 30 分钟。需要本机和应用运行、项目可读写、
GitHub 登录有效及账户额度。没有另起 API 模型服务，也不向 VPS 部署开发 agent。
本地关机不会继续执行，恢复后接续；真正脱离本机的 24 小时服务以后再单独迁移到常开主机。

2026-10-25 已准备 [Codex Cloud 交接](./development/codex-cloud-handoff.md)，
但尚未配置 / 发布云端环境或迁移定时任务。`active_environment` 默认 local；Cloud 普通 checkout
可只读预检，不能与本机同时领取任务。可移植 checkpoint 只恢复任务状态，所有测试授权重新生成。
正式切换须先暂停本机任务并取得明确批准；不需要另租开发 VPS，也不改变生产对战服务。

## 遗留收敛

见 `docs/development/branch-inventory.md`。只删除确定已在 develop 中、没有工作树占用的本地
陈旧 ref；带独有提交、未提交文件或 ignored 报告的工作树保留，先做对比迁移。
尤其要保留旧 Phase 6 工作树里的 Ruleset / 规则矩阵，以及 API Play 未提交改动。
