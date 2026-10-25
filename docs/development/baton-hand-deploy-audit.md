# PR 卡 Baton 手牌登场审计

## 本轮结论

固定分支 `codex/continuous-development`、Draft PR #54。只读核对旧提交 `07f51e4`，
没有合并旧分支、覆盖旧 dirty 文件或复制旧 manifest。

本轮完成条件提示修复和审计，**不宣称这两张卡已经自动适配**：
普通登场、等费用或更高费用来源的 Baton 不再给出该手动提示；只有真正从较低费用
Member Baton 入场时才出现可选手动能力。自动登场底座另列下一项任务。

## 卡牌与绑定

| 西木野真姫 | 桜小路きな子 |
|---|---|
| `PL!-PR-015:1`，revision 723，费用 17 | `PL!SP-PR-020:1`，revision 775，费用 17 |
| ![西木野真姫](https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PR/PL!-PR-015-PR.png) | ![桜小路きな子](https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PR/PL!SP-PR-020-PR.png) |

图片为本地卡库登记的官方图片链接，未复制或重新抓取图片。
两张卡的完整日文文本 hash 相同：
`33aa98797222c47c047413845271fdc26a493ceab414094984e4b97c39cd4a6d`。
均为 effect index 1、登場时点、可选技能。原意是：从费用更低的 Member Baton 入场后，
可以从手牌将 1 张费用不高于 4 的 Member 登场。

## 官方依据

本地综合规则 ver.1.06 PDF，SHA-256
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。

- 4.3.2.3：没有特别指定朝向时，以 Active 状态放置。
- 9.6.2.1.2 / 9.6.2.1.2.1：指定己方 Member 区域；含有本回合从场外入场 Member 的区域不可指定。
- 9.6.2.3.2：Baton 是支付费用时执行的特别处理，不等于普通替换或效果登场。
- 9.6.2.4.2.1：能力导致 Member 入场时也要进行区域指定。
- 10.4.1 / 4.5.5.4：已有 Member 区域的重叠处理及离场后的附属卡处理需要正确实现。
- 11.4.2：从 Stage 以外进入 Member 区域会触发登場能力。

以上是代码实现依据，不是全卡人工裁定；本轮未引入 FAQ 或个别裁定。

## 为什么不直接恢复旧 executable 登记

旧提交只新增候选登记和候选字段测试，没有完整状态转换 / Replay / UI / AI 验收。
其 `deploy_member_from_hand` 配合 `deploy_selected_to_empty_stage` 有以下缺口：

| 项目 | 发现 | 后续必须验收 |
|---|---|---|
| 区域 | operation 限制为空区域，原文没有该限制 | 允许符合规则的已有 Member 区域，并处理重复 Member |
| 限制 | 当前 area 历史标记不等同于“本回合入场 Member 当前所在位置” | Position / Formation 移动后仍准确判断合法区域 |
| 朝向 | operation 未指定时默认 Wait | 新语义应默认 Active；原文明示 Wait 的条目继续 Wait |
| 前端 |旧 hand choice 类型没有接通区域选择 | 所选卡及目标区域完整传给 `resolve_effect` |
| AI | 不保证提交目标区域 | 各 policy 均从 LegalAction 选择，不绕过 validation |
| 连锁 | 不能仅凭候选字段测试推断登場触发正确 | 补新 Member 登場、旧 Member 离场、附属卡清理和 Replay 断言 |

当前另有 10 条 executable 使用 empty-stage operation：
`PL!-bp6-003:2`、`PL!HS-bp5-002:2`、`PL!HS-bp5-022:1`、`PL!HS-bp6-016:1`、
`PL!N-pb1-013:1`、`PL!N-pb1-015:1`、`PL!N-pb1-017:1`、`PL!N-pb1-023:1`、
`PL!S-sd1-006:1`、`PL!SP-bp4-004:2`。
这些记录均未显式登记朝向，而旧 executor 仍默认 Wait，这是已确认的待修正点。
gap report 新增 `executable_audit_warnings` 明确列出全部 10 条，不再让 executable 数字掩盖问题。
下一轮必须逐条修正或降级，并分别复核区域、费用和连锁；本轮不在缺少完整状态验收时批量改标签。
当前 PR 不合并、不部署；这意味着当前静态登记率仍不能替代规则正确率，也不构成发布验收通过。

## 本轮实际修正与证据

先新增测试，复现了普通登场 / 等费用 / 高费用 Baton 仍错误入队，共 9 项红测失败。
修正注册项和精确文本 manual candidate 的条件：

```json
{
  "requires_baton_touch": true,
  "replacement_member_cost_less_than_source": true
}
```

新增 22 项定向测试，连同 gap report 原有测试共 25 项通过：

- 两张费用 17 的卡分别覆盖普通登场、16 费用 Baton、17 费用 Baton、18 费用 Baton。
- 仅 16 → 17 的 Baton 显示该提示，并核对实际支付 Energy 与来源记录。
- 序列化初始状态后重放登场动作，结果一致；原状态不被修改。
- 测试已有 `reduce_play_cost` primitive 不被误当作卡面费用比较值；不据此推断任何 FAQ 敏感卡。
- 三种 AI policy × 两张卡均明确拒绝可选 manual，不伪造免费登场，不静默记作已执行。
- 手动 invocation 不能通过 `accepted=true` 冒充结构化 executable；可正常拒绝并记录 `effect_declined`。
- 同文候选仍为 manual，保留 revision / hash / index；不恢复旧版 empty-stage 自动登记。
- gap report 给出具体原因 `member_deployment_area_orientation_ui_ai_not_rules_conformant`，
  并指向区域规则底座任务，而不再仅称“等待一般审查”。
- gap report 对既有 executable 的 10 条默认 Wait 风险另外显示警告，不将它们包装成规则可信。
- 双方 payload 中己方仍可查看手牌，对手拿不到手牌目标身份，也不能代为操作该 invocation。

完整 registry / backend / web 与协调器验证由源码指纹绑定的运行记录保存。
manifest 仅随 registry 内容更新，卡库指纹不变，未修改 Card Schema、runtime SQLite 或 HTTP 契约。

另用 20 套固定牌组池前 10 组配对运行 AI-vs-AI：10/10 正式完赛、平均 7.1 回合、最长 18，
illegal / blocker / skipped effect / Replay 序列化错误均为 0。仅 7/10 同时满足 10 回合内且
双方有成功 Live，和上轮相同；不把一般完赛回归当作已发现登场问题的正确性证据。
机器报告位于 `logs/continuous-baton-audit-ai-20261025/`，不提交生成日志。

## 下一切片

队列 `effect-deployment-rule-conformance`：补齐合法区域、Active 默认朝向、重复处理、
Member 入场身份跟踪、UI 和 AI 选择，再重新验证两张 PR 卡及上述 10 条旧登记。
涉及旧 snapshot 的行为必须保留显式兼容边界，不直接用新解释伪装旧 Replay 一致。

本轮 executable **903 / 1212（74.50%）**、manual **309**，均不变。
未合并 PR、未部署；等待维护者回程审核。
