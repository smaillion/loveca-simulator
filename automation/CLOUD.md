# Codex Cloud 接续入口

先阅读 `AGENTS.md`、`docs/development/codex-cloud-handoff.md`、
`automation/policy.json`、`automation/cloud-checkpoint.json`、`automation/queue.json`。
这不是部署任务，也不授权 PR 合并。

## 固定边界

- 只使用 `codex/continuous-development`，目标为既有 Draft PR #54。
- Cloud 使用仓库普通 checkout 根目录，不创建本机式嵌套 worktree；本机仍使用原固定工作树。
- 设置 `LOVECA_DEVELOPMENT_ENV=cloud`，激活 `.venv`，设置 `PYTHONPATH=$PWD/src`。
- 先 fetch / prune，再检查 PR #54 的 state、head/base、Draft 和 CI。若已关闭 / 合并则停止，
  不新建 PR，不尝试 force-push。未配置 GitHub 写入能力时只做预检，不索要本机认证文件。
- `active_environment` 仍为 `local` 时只允许只读预检，不能 claim、check、complete 或 publish。
- 本地 SQLite 只锁同一 checkout 的进程，不锁另一台电脑或其他 Cloud task。
  即使 active_environment=cloud，也必须确认本机自动任务已暂停，并且没有第二个 Cloud writer。
- 只读取指定项目，不添加生产 VPS、SSH、管理员密钥、GPT 认证文件或付费模型 key。

## 首轮

```bash
source .venv/bin/activate
export PYTHONPATH="$PWD/src"
export LOVECA_DEVELOPMENT_ENV=cloud
git fetch origin --prune
python -m tools.development.loop doctor
python -m tools.development.loop status
gh pr view 54 --json state,isDraft,headRefName,baseRefName,headRefOid,statusCheckRollup
```

只有在维护者完成切换后，才领取同一队列。可移植 checkpoint 不包含租约或有效发布证据。
首轮会恢复本交接任务为 in_progress：重新运行全部 required_profiles，确认 Linux / Cloud
真实结果再 complete；不要重复实现交接，不把本机测试冒充 Cloud 已验收。

后续每轮最多 45 分钟、一个有限切片，遵循 `automation/WORKFLOW.md` 的相同验收 / 发布流程。
使用 `claim --owner codex-cloud`，保存 token；长检查前 renew，未完成时 release。
所有源码 / 文档修改（包括 checkpoint）必须在最终 check 之前完成。
每批最终检查前运行 `checkpoint --lease TOKEN`；它有意保留当前任务 in_progress，
新 VM 丢失 runtime 后只需重新验收该切片，不能跳过验证直接发布。

## 接下来做什么

首轮交接验证完成后，优先 `attachment-promotion-trigger-audit`，再推进通用效果登场、
Ruleset / Replay、AI Live 获取和长局。具体以 queue 依赖和当前真实 CI 为准。
官方依据用仓库已固定的 ver.1.06 PDF 与 exact-text 卡库，不重新抓取官网。

旧 v0.9 / API Play dirty 工作树和 ignored 报告没有上传。遇到任务确实需要未迁移材料时，
记录缺失输入并转到无依赖任务，不推断原实现、不删除本机工作树、不宣称收敛完成。

报告使用中文。只有有新验证成果、CI 失败、真实 blocker 或需要人工决定时通知。
本入口不创建计划任务；Cloud 可周期性运行并自动更新同一 PR 的能力必须实测后才能启用。
