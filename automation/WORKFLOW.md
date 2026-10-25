# 持续开发入口

当前只有一个自动开发入口：`codex/continuous-development`，固定工作树为主仓库下的
`.tmp/continuous-development`。任务调度使用当前 Codex 对话的定时接续，每 30 分钟唤醒；
每轮最多 45 分钟，完成一个可验证的小批次后保存进度。

2026-10-25 出差期间的授权：继续修复 PR #54 的前端 CI，再按同一队列推进技能与 AI。
改动只更新当前分支和同一个 Draft PR；至少在维护者 2026-10-27 夜间回来审核并明确批准前，
不得合并或部署。保持本机现有运行方式，不自动睡眠、不迁移 VPS。若 PR 被外部关闭或合并，
先记录并等待确认，不自行创建替代 PR。

## 每轮执行

1. 读取 `automation/policy.json`、`automation/queue.json`、`docs/21-continuous-development.md`
   和最新分支清单。所有代码工作均在固定工作树中完成。
2. 运行 `python -m tools.development.loop doctor` 和 `status`，检查 GitHub PR / CI 状态。
   有 CI 失败时先读失败 job 日志、复现并修复；同一失败连续三次仍无法修复则记录 blocker。
3. `claim --owner codex-continuous` 领取最高优先级可执行任务。保存返回的 lease token；
   重叠唤醒拿不到租约时立即退出。超过租约的中断任务由下一次接续恢复。
   `doctor` 若仅因 develop 已前进而失败，仍可先领取租约，再在干净工作树内 fetch 并正常
   merge `origin/develop`。检查和发布会继续拒绝旧基线，直到同步完成；不得 reset 或 force-push。
4. 实施该任务的一个有限切片：先复现 / 记录依据，再改实现和有意义的测试，最后更新
   文档及中日双语 Changelog。按任务验收标准工作；任务过大时拆成有独立验收标准的子项。
5. 使用 `check --lease TOKEN --profiles ...` 执行任务的全部 required profiles。
   检查前设置受支持的 Node 运行时；测试使用工具准备的工作区临时目录。
6. 检查报告与 diff，验证 acceptance 全部满足，再提交当前批次。之后执行
   `complete --lease TOKEN --outcome done --note "中文成果和证据"`。
   验收尚未完成时执行 `release --lease TOKEN`，保留 in_progress 供下一次续跑。
   确实需要外部决定的任务使用 `complete --outcome blocked --note ...`；其他可执行项继续。
7. `publish` 只会在当前源码门禁通过、工作树干净、租约释放后 push 同一个 feature branch，
   创建或更新唯一 Draft PR。不得直接 push `develop`，不得 force-push。
8. 检查 PR 的 CI；失败修复进入下一批最高优先级。成功批次提供中文可读报告。

## 持续规划

- 优先级：CI / 用户可复现缺陷 → 遗留成果收敛 → 技能正确性与 AI 完赛 → v0.9 规则门禁。
- 队列耗尽时，根据当前 Roadmap 和实测证据补充有限、可验证的任务；一次只增加下一批。
- 不按次数重复跑已通过且代码未变化的全量测试。没有新任务、证据或状态变化时保持安静。
- 对官方规则不能确认的语义，登记 unresolved reason，转向其他安全可实现项。
- 可自动执行本地开发、测试、commit、feature push、Draft PR 和失败修复。
- 远程 PR merge、发布、生产数据库操作、生产配置修改仍需用户明确批准。
  当前授权不是放开这几项操作；不要反复请求普通实现阶段审批。
- 当前 PR 合并后，继续复用同一分支和工作树，先同步 `origin/develop`。
  只允许正常 merge / fast-forward；历史不兼容或有用户改动时记录并保留，不 reset。

## 常用操作

在固定工作树内执行：

```powershell
python -m tools.development.loop status
python -m tools.development.loop next
python -m tools.development.loop inventory --output .tmp/worktree-inventory.json
python -m tools.development.loop pause
python -m tools.development.loop resume
```

`pause` 阻止领取新任务；已开始的一轮在当前安全检查点结束。要彻底停止后续唤醒，
在 Codex 的计划任务中暂停“LoveCA 持续开发”。恢复后从现有状态继续，不创建新工作树。

本地任务需要计算机开机、Codex 应用保持运行、项目目录可用以及账户仍有使用额度。
关闭电脑期间不会执行；重新运行后通过持久状态接续。此方案不需要另配模型 API key。
