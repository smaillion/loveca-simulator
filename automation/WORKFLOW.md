# 持续开发运行入口

本页只提供每轮操作入口；唯一流程说明见[持续开发指南](../docs/21-continuous-development.md)。
文档查阅与维护方式见[文档导航](../docs/README.md)，专题证据见[开发索引](../docs/development/README.md)。

## 先检查，再工作

1. 先读取主仓库 `.tmp/development-loop/state.json`。有有效租约则不争抢、不修改现场，重复唤醒安静结束。
2. 在固定工作树 `.tmp/continuous-development`，确认分支为 `codex/continuous-development`。
3. 读取 [policy](./policy.json)、[queue](./queue.json)、[指南](../docs/21-continuous-development.md)、
   [分支保留约束](../docs/development/branch-inventory.md)和本任务相关的专题最终验收。不要把历史 WIP、旧 PR 或旧 heartbeat 当当前事实。
4. 正常 fetch，运行 `doctor` / `status`，只读核对固定 PR 及 CI；明确下一有限任务及依赖后 claim。
5. 按指南完成实现、证据、checkpoint、全部 required profiles、pre-push、审查、commit 与 complete。
   未完成则 release 保留 in_progress；长检查续租，每轮最多 45 分钟。

## 不可省略的边界

- 运行状态只由协调器修改；blocked 只能在依赖或审批实际解除后显式 requeue 并记录理由。
- 只复用固定分支、工作树及 policy 中的 PR。目标不是同一 head/base 的开放 Draft 时拒绝 publish；不自动解除编号或建立替代。
- 最新维护者授权优先于历史说明。允许 feature push 不等于允许合并、部署、生产配置或主机操作，后者始终另问。
- 不 reset、force-push 或丢弃用户改动；旧 dirty、stash 和 ignored 报告保留。仅持有租约且工作树干净时正常同步基线。
- Cloud 只备交接，未启用；本机继续运行，不自动睡眠、不迁移 VPS、不启动第二写入者。
- 无新成果、CI 失败、真实阻塞或审批需求时保持安静。

## 历史授权与接续

PR54 已按一次性许可合并上线；后续维护者批准新建的固定 Draft 是 PR55，
见[目标验收](../docs/development/draft-pr55-target-verification.md)。这些记录不是未来合并或发布许可。

Cloud 准备资料在 [CLOUD.md](./CLOUD.md) 与[交接说明](../docs/development/codex-cloud-handoff.md)。
必须先停止另一端并取得切换批准，才能改变 `active_environment`。
