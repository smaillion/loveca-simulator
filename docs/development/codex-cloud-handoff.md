# Codex Cloud 开发交接

## 当前决定

可以把开发 / 测试迁到 Codex Cloud，不需要另租开发 VPS；这不替代公开对战后端。
本次仅准备交接，尚未创建 / 发布 Cloud 环境、启动云端任务或切换写入者。
本机持续任务保持运行；未合并 PR、未部署、未修改生产配置。

依据为 2026-10-25 实际读取的 [Cloud 说明](https://learn.chatgpt.com/docs/cloud)、
[环境设置](https://learn.chatgpt.com/docs/environments/cloud-environments) 与
[计划任务说明](https://learn.chatgpt.com/docs/automations)。Cloud 的开发任务与本机定时唤醒
不是同一功能，不能只改一个路径就宣称已实现无人值守迁移。

## 已交付的入口

- `scripts/codex-cloud-setup.sh`：Linux 依赖安装与无凭据预检；可用 `--check` 重复检查。
- `automation/CLOUD.md`：新任务应先读的可恢复指令。
- `automation/cloud-checkpoint.json`：任务状态白名单快照。只记录版本、Git commit、PR 和状态；
  不复制 notes、运行日志、绝对路径、租约、token、私有数据或旧 last_check。
- 协调器 `--environment cloud`：支持普通 checkout；本机默认仍要求固定 worktree。
- `active_environment=local`：云端只能预检，任务写入默认关闭。
- `pull_request=54`：推送前校验现有 Draft PR；关闭、合并、改 head/base 后拒绝推送与另建 PR。

任务状态可恢复，不等于测试证据可迁移。云端必须对实际代码重新跑门禁。
checkpoint 记录当批检查前的状态，故最后一项可能是 in_progress；这只要求重新验收，
不应重复实现或重复创建 PR。以后每批最终检查前刷新 checkpoint。

## 建立专用环境

1. 在 Codex 的 Cloud 环境中只选择 `smaillion/loveca-simulator`，并选择
   `codex/continuous-development`。不要取默认 develop，因为本 PR 尚未合并。
2. 设置私人可见（Only me）。boatrace 使用另一个环境和队列，不共用认证或 checkout。
3. 请求 Linux、Python 3.12（项目最低 3.11）、Node 24、npm、Git 与 gh；启用完整 Git 历史。
   仓库已含 `data/loveca.sqlite3`、manifest、registry 和固定 PDF，不需官网重新导入。
4. 在环境准备时执行 `bash scripts/codex-cloud-setup.sh`，审阅输出后再发布环境。
   后续任务激活 `.venv`，设置 `LOVECA_DEVELOPMENT_ENV=cloud` 和 `PYTHONPATH=$PWD/src`。
   本机 `LOVECA_NODE=C:/...` 不能复制过去，Cloud 直接使用 PATH 中的 Node 24。
5. 初期仅允许依赖包源、GitHub source / API 等必要域名。测试 mock 不需模型 API key。
   不开放生产 VPS、Tunnel 管理端、内网、云平台权限；不配置部署凭据。
6. 首轮只做只读预检，核对目标分支 / PR、卡库、Python 测试、Vitest 与 build。
   Docker 镜像仍由既有 GHA 检查；Playwright/截图需在真实 Cloud 环境单独验收，不冒充已通过。

Cloud 环境里的 GitHub 仓库连接与 gh 登录是否可同时用于同一分支更新，需要实际验证。
先使用平台提供的受限 GitHub 集成；不要复制本机 `auth.json`、gh 配置、浏览器 cookie、
`.env`、SSH key、`LOVECA_ADMIN_KEY` 或 GitHub 部署 Secrets。若 gh 不可用则停止发布并记录，
不能擅自增加长期 PAT。确需新凭据时由维护者另行配置最小仓库权限和有效期。

环境变量能被程序读取；官方支持的 network secret 可限制 HTTPS 目的地，但也不是给任何
项目添加生产权限的理由。不能声称平台隔离等于绝对零泄漏；最有效的是根本不注入无关机密。

## 单写者切换（本次未执行）

本机和云端各有独立磁盘；SQLite 租约不是分布式锁。Git 的普通 push 仅防止覆盖历史，
不能阻止两边同时改代码。必须遵守以下人工控制切换：

1. 本机完成当前有限切片、验证、commit / push，并确认 PR #54 的 head 和 CI。
2. 暂停“LoveCA 持续开发”计划任务，使用协调器 pause，等待有效租约和检查进程全部结束。
   保留原工作树，不为切换强杀测试。
3. 保存最终白名单 checkpoint；如需刷新，应在 pause 前持有效租约生成并重新验收提交。
4. 取得维护者明确的切换批准后，将 policy 的 active_environment 改为 cloud，作为单独的
   控制提交验证并推送同一分支。该提交不合并 develop、不触发生产部署。
   本机任务保持暂停；不要为了提交此控制变更绕过业务任务门禁。
5. Cloud fetch 最新分支，核对不存在本机有效 writer，再从 `automation/CLOUD.md` 开始。
   只保留一个有写权限的 Cloud task，不并行启动多个任务 / agent 写同一分支。
6. 首轮重新完成交接切片的全部门禁；一次推送后确认仍是 PR #54，且 GHA 成功。
7. 只有账户支持的 Cloud 定时机制完成真实“无人在线 → 唤醒 → 接续同一分支 → 保存检查点”
   验收后才配置周期执行。普通网页 Scheduled 不承诺持久仓库；当前本机 heartbeat 不会自动迁移。

本机 worker fetch 到新 policy 后会拒绝 claim / check / publish；但离线旧 checkout 不会
实时得知云端状态，所以暂停本机调度仍是必要条件，而不是可选优化。
本机与 Cloud 双方的 runtime 都不得复制给对方，避免过期租约、旧证据和认证污染。

回退：先停止云端并确认无 writer，保留并推送已验证成果；维护者批准后把 policy 切回 local，
本机 fetch 并正常同步，重新验证再 resume。不得 reset / force-push，不删除 Cloud 或本机成果。

## 实际开发进度

交接前来源 commit：`6008a4e66344024a6d66a60df5ac672a67d6cf1c`；
基线 develop：`93faadfa7d5376237884cb356a6cec9e3277cf34`。
PR：[Draft #54](https://github.com/smaillion/loveca-simulator/pull/54)，
2026-10-25 11:26 UTC 前后端 / Docker / AI-DLC / GitGuardian 检查均已成功。
这些是交接前记录，不代表未来 head 或云端验收。

- 卡库：1977 gameplay cards、2700 printings、24 sets；最新 CLLS01 / PBLL02。
- Registry：899 / 1212 = 74.17% executable，313 manual；这是登记率，不是人工裁定正确率。
- 最近一批：pytest 629 passed、Vitest 76 passed、build / manifest / strict integrity 通过。
- 固定 20 Deck 池的 10 局 AI：10/10 正式完赛，平均 7.2 回合、最长 19；只有 7/10 满足
  “10 回合内且双方均有成功 Live”，不能宣称 AI 严格目标已经达成。
- 已补当前 Member 身份 / 区域入场记录；旧 snapshot 省略新字段，保留旧行为和 hash。
- `PL!-bp5-003:2` 成本结果分支完成；6 条空区域效果登场补 Active / 位置选择 / UI / AI。
- 4 条不限定空区域的虹咲技能降为 manual，两张 PR 卡仍 manual，不能恢复旧虚高标签。
- 下一规则切片：附属 Member 转为顶部时的登場 / own_member_played / 入场次数，
  `attachment_promotion_onplay_trigger_and_entry_count_requires_rules_audit`。

中文逐项证据在 `docs/development/*verification.md`、`baton-hand-deploy-audit.md` 和
`legacy-api-play-migration.md`；源码中的真实断言是接续入口，不能只依赖本摘要。

## 仍在本机的材料

`docs/development/branch-inventory.md` 里的旧 v0.9 44 项、API Play 6 项 dirty 内容及 ignored
报告没有打包上传；部分已选择性迁移，不能把剩余项目当作已收敛。旧输入缺失时应明确阻塞
相应任务，优先继续无依赖的规则 / AI 工作。不要全量复制工作区、`.git`、缓存或历史报告。

## 交接验收清单

- [ ] 真实 Cloud 环境建立并发布，安装与预检成功。
- [ ] 本机调度暂停、无有效写入租约；active_environment 经批准切为 cloud。
- [ ] Linux 下 required_profiles 全部通过，未沿用本机 last_check。
- [ ] 同一分支 / Draft PR #54 更新成功，没有新增分叉或远程合并 / 部署。
- [ ] 第二次启动 / 恢复能从 checkpoint 接续，不重做历史任务。
- [ ] Cloud 定时能力与账户额度实际验证；未验证前不承诺 24/7 自动运行。
- [ ] 原工作树与报告仍保留，生产对战服务器和 Secrets 未动。
