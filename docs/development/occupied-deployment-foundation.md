# 已有 Member 区域效果登場：受控底座

## 当前结论

新增独立 `deploy_selected_to_stage` 操作，验证简单区域的效果登場与覆盖清理。
**尚未绑定任何正式卡牌，也没有提升技能登记率**。父任务仍在进行，不把底座等同于
两张 PR 卡或四张虹咲卡已经可自动处理。

| 待接入卡牌 | 状态 |
|---|---|
| `PL!-PR-015:1` / `PL!SP-PR-020:1` | 仍 manual，等待完整重叠 / 手牌选择边界验证 |
| `PL!N-pb1-013:1` / `015:1` / `017:1` / `023:1` | 仍 manual，不恢复旧 empty-only 标签 |

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PR/PL!-PR-015-PR.png" width="150" alt="待适配的西木野真姫，卡面示意而非测试截图">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PR/PL!SP-PR-020-PR.png" width="150" alt="待适配的桜小路きな子，卡面示意而非测试截图">

两张 PR 卡的精确卡文、revision 和 hash 见 [前次审计](./baton-hand-deploy-audit.md)。
本轮所有新操作场景使用明确标记为 `AUDIT` 的受控技能，不伪称实际卡牌已经通过验证。

## 官方依据与实现限制

只读取本地综合规则 ver.1.06：`raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`，第4、5、10、12页。
PDF SHA-256：`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。

- `4.3.2.3`：未指定朝向时 Active；新操作仍强制显式记录 Active / Wait，避免旧快照漂移。
- `9.6.2.1.2.1`、`9.6.2.4.2.1`：效果登場也必须指定合法区域，本回合外部入场卡所在区域不可指定。
- `10.1.2`、`10.4.1`：重叠规则处理发生在检查时点，保留最后进入的 Member，不是 Baton。
- `4.5.5.4`、`10.5.3–5`：附属 Member 去控室，附属 Energy 回能量牌库。
- `4.1.4`：离开 Member Area 后原区域的临时效果不保留。
- `9.6.3.1.4`：私有手牌的筛选目标可以视为不存在；当前底座尚不实现零张选择，
  因此**不能据此直接晋级手牌登場卡**。

现有 MatchState 每个区域只能保存一个顶部 Member，不能表达任意临时重叠场面。
新操作只接受单个己方手牌 / 控室 Member、明确朝向、单一操作、无后续 choice、固定 Energy 费用。
对复杂离场观察者、附属卡能力、未知 effect、条件式登場观察者、入场卡常时能力等，
在支付前排除对应区域，并在 LegalAction 的 `deployment_unsupported_slots` / 按候选映射中记录原因。
这不是完整重叠调度器，也不是人工 reviewed 裁定。

## 真实状态验证

受控场面：目标带“登場抽1”；旧 Member 带无条件“离场抽1”；另一 Member 带无条件
“己方 Member 登場抽1”。这三项只是 fixture，不是上方卡图的实际能力。

| 场景 | 实际断言 |
|---|---|
| 手牌 / 控室 → 简单已有区域 | 新 Member 以指定 Active 或 Wait 正面登場；原区域卡被清理 |
| 附属 Member / Energy | Member 与旧顶部去控室；Energy 去能量牌库、背面；无卡牌遗失或重复 |
| 费用 | 精确支付2个 Active Energy；非法卡、位置、数量、重复 Energy 均不修改原状态 |
| 登場 / 离场观察者 | 每项真实抽1，共抽3；父效果结束后才处理自动抽牌 |
| 空区域对照 | 只抽登場和己方观察者的2张，没有虚构离场或覆盖事件 |
| 本回合入场限制 | 随 Member 当前区域移动，旧位置释放，当前区域继续禁止 |
| 朝向 / 临时效果 | 新卡按显式朝向进入；离场卡的目标型 modifier 清除，不制造 Baton 历史 |
| 不支持的重叠语义 | 返回受控 unresolved reason；不能支付后再悄悄忽略能力 |
| 先起动支付后目标消失 | 不重复付费，保留旧 Member，以 `effect_operation_not_applied` 明确结束 |
| Replay 与双方视角 | 真实 runtime SQLite 重放的 state / events / hash 一致；对方私有手牌不暴露 |

专项文件 `tests/test_occupied_effect_deployment.py` 共 **39项**，包括三种 AI policy、
deterministic controller、隐藏手牌身份不变性、DSL 拒绝范围和旧 empty-stage 快照对照。
前端区域按钮补显示已有 Member 的日文卡名，仍提交现有 `selected_card_instance_ids` / `to_slot`。
组件测试新增已有区域场景；不新增 HTTP endpoint。

序列化发现：现有 CardInstance 的 orientation 字段不接受 `None`。本路径对离场卡保存
`active` 内部默认值；它在控室 / 能量牌库不具有规则上的 Active 含义。公开控室 Member
为正面，能量牌库卡为背面。没有为了表现“无朝向”而修改 Card Schema 或 SQLite schema。

## 固定 AI 回归

20 Deck 池、seed `12000..12009`，10 场 AI vs AI，600 action cap。

| 局 | Deck | 回合 | P1 / P2 成功 Live |
|---|---|---:|---|
| 1 | 01 / 04 | 3 | 2 / 3 |
| 2 | 02 / 09 | 6 | 1 / 3 |
| 3 | 03 / 14 | 6 | 3 / 1 |
| 4 | 04 / 19 | 7 | 3 / 2 |
| 5 | 05 / 04 | 19 | 2 / 3 |
| 6 | 06 / 09 | 7 | 0 / 3 |
| 7 | 07 / 14 | 8 | 3 / 1 |
| 8 | 08 / 19 | 6 | 1 / 3 |
| 9 | 09 / 04 | 5 | 3 / 1 |
| 10 | 10 / 09 | 5 | 3 / 0 |

10/10 正式完赛，平均7.2回合、最长19，无 blocker / skipped effect / Replay序列化错误。
严格“10回合内且双方至少一次成功 Live”仍只有7/10，没有策略改进的证据。
该固定池没有登记新操作，因此这部分只是既有功能回归；新操作由上面的定向状态测试验证。
原始报告：`logs/continuous-occupied-deployment-ai-20261025/`，不上传对局私有日志。

## 新发现与后续

用真实 `PL!SP-bp5-111:2` 的费用 operation 单独复现：两张 Energy 返回能量牌库后，
`orientation` 被写为 `None`，MatchState JSON 重新读取出现2项验证错误。
同一旧操作还用于 `PL!SP-pb2-010:1`。这不是本轮新增回归，但会破坏 Replay，已加入
最高优先级独立任务 `energy-deck-return-replay-orientation`，本轮没有声称修好。

后续切片已修复上述两张卡的新执行路径，并对旧坏快照增加安全拒绝；不改写历史数据。
详见 [Energy 返回验证报告](./energy-return-replay-verification.md)，本段保留最初发现时的记录。

完整重叠触发 / 手牌零张选择由 `effect-overlap-trigger-and-private-choice` 继续；之后才复核
六条手动卡的自动适配。保留既有6条空区域效果和4条虹咲降级结论，登记仍为
**899 / 1212（74.17%），313 manual**。没有更改 registry、卡库或 importer。

继续使用同一分支和 Draft PR #54；旧 dirty 工作树与报告未动，未合并、未部署、未启用 Cloud。
