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
- 最多一个开放的此分支 PR，目标为 `develop`，具体编号由 policy 固定。目标关闭、合并、转为非 Draft 或 head/base 改变时停止 publish；新目标须重新获批，不自动创建替代。
- `preview` 为独立历史发布线；不会成为自动开发的分支根。

## 数据与并发

`automation/policy.json` 记录执行边界和验证命令；`automation/queue.json` 记录已批准方向、
依赖、优先级和验收标准。这两个文件由 Git 版本管理。

运行进度放在主仓库的 `.tmp/development-loop/state.json`，不随分支切换消失，包含任务状态、
租约、测试证据和 PR 地址。SQLite 仅用作跨进程的短事务锁，进程终止后由操作系统释放；
不操作应用的卡牌库或对战 runtime。文件使用临时文件加原子替换保存。

写代码前必须 claim；租约默认 120 分钟，检查运行期间定期续租。重复唤醒不能领取已有
有效租约；过期后恢复原 in_progress 任务。每轮不超过 45 分钟，结束释放租约。

## 每轮操作顺序

1. 先读主仓库 runtime；有效租约存在则安静结束。读 policy、queue、分支保留约束和本任务相关证据。
2. 在固定工作树正常 `git fetch origin --prune`，设置 `PYTHONPATH` 为该工作树的 `src`，
   运行 `python -m tools.development.loop doctor` 和 `status`，只读检查固定 PR/CI。
3. 选择独立且有价值的有限任务，明确依赖与验收后入队。`claim --owner codex-continuous --task TASK` 取得租约。
   若仅基线落后，可先 claim，再在干净工作树正常同步 `origin/develop`；不得 reset/强行覆盖 dirty。
4. 按变更风险先复现或记录官方依据，再实现与验证。规则变更仍需精确日文全文/revision/hash、
   真实状态、SQL Replay、AI、隐私与必要 UI；构造状态不能冒充完整对局或官方裁定。
5. 完成文档和双语 Changelog 后执行 `checkpoint --lease TOKEN`，再执行
   `check --lease TOKEN --profiles ...`，覆盖任务全部 required profiles。检查期间续租。
6. 执行 `scripts/pre-push-check.ps1`，审查 diff 与验收证据后提交；执行
   `complete --lease TOKEN --outcome done --note "成果与证据"`。最终检查后修改源码或版本化文档必须重验，不能复用旧指纹。
7. 未完成时 `release --lease TOKEN`，保留 in_progress。确实需要外部决定才 complete blocked；
   同一失败三轮仍无解时记录 blocker，其他独立任务可继续，不能自动 requeue。
8. 只有当前授权允许时，在工作树干净且租约释放后 `publish` 到固定 Draft PR；读取新 head 对应 CI，
   pending 不等于成功。合并、部署另行审批。

队列耗尽时只补充下一有限切片，不重复 done 或无变化全量检查。任务优先级为：
CI/可复现缺陷、遗留收敛、技能正确性与 AI 验收、核心规则门禁；维护者明确指定的工作优先。

普通任务更新已有主题报告和 CHANGELOG 即可，README 只在用户能力或使用方式变化时更新，
不再向 README、分支清单、审计总览复制同一段逐轮结果；详见[文档职责](./README.md)。

## 常用管理命令

以下命令均在固定工作树执行：

```powershell
python -m tools.development.loop status
python -m tools.development.loop next
python -m tools.development.loop inventory --output .tmp/worktree-inventory.json
python -m tools.development.loop pause
python -m tools.development.loop resume
```

`pause` 阻止领取新任务，不会中止已持有租约的工作。要停止后续唤醒，还需暂停应用中的计划任务。
恢复后复用现有状态和工作树，不创建替代开发入口。

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

阻塞原因已经解除且相应审批已取得时，使用
`python -m tools.development.loop requeue --task TASK --note "审批和解除原因"`
恢复指定任务，再正常 claim。它拒绝有效写入租约、暂停状态和未完成依赖，
保存原阻塞记录及失败计数，作废该任务的旧门禁授权；不直接编辑运行状态文件。
此命令不授予代码恢复、远程 PR 合并、部署或生产修改的审批。

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
