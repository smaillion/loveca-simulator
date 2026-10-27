# Energy 回牌库与 Replay 修正报告

## 本轮修复

两张已登记技能共用 `move_selected_energy_to_energy_deck`，旧实现将返回卡的朝向写成
`None`，但现有 CardInstance 只接受 `active` / `wait`。这不是画面问题：费用已经支付后，
刷新或继续下一步会因无法读取 SQLite 快照失败。

| 卡牌 | 柊摩央 | ウィーン・マルガレーテ |
|---|---|---|
| effect ID | `PL!SP-bp5-111:2` | `PL!SP-pb2-010:1` |
| text revision | 247 | 806 |
| 卡面示意，非测试截图 | ![柊摩央](https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP05/PL!SP-bp5-111-R.png) | ![ウィーン・マルガレーテ](https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBSP02/PL!SP-pb2-010-R.png) |

柊摩央：
> 【起動】【ターン1回】エネルギー2枚をエネルギーデッキに置く：自分の控え室にあるライブカードを1枚手札に加える。

ウィーン・マルガレーテ：
> 【ライブ開始時】手札を1枚控え室に置かないかぎり、自分のエネルギー1枚をエネルギーデッキに置く。

原文 SHA-256 分别为：

- `f69337d2929c4dfb13861b26d321b9ccc7ed88319d81023215cb69e28c6db712`
- `74c4b94cf6684d2e76e3c83d609aaa214d98facf67ba0b1aebbe7b6ba2b2aa63`

revision、hash、effect index 和 registry 状态不变，不新增登记、不提升 reviewed。
补齐了柊摩央既有登记缺失的 exact-segment candidate 规则；实际发现的对应身份仍只有
`PL!SP-bp5-111:2`，没有模糊匹配或自动绑定新卡。

## 规则与数据格式的区别

本地综合规则 ver.1.06，第4、5页：`4.3.2`、`4.7.3–4`、`4.9.2`。
PDF：`raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`；SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。

Energy Area 才使用 Active / Wait；Energy Deck 为非公开区域。修正后返回卡保留 `active`
内部默认值供现有模型序列化，且保持背面。这个值**不表示该卡成为可支付的 Active Energy**：
它已离开 Energy Area，不参与可用能量计数。没有把 Energy Deck 当作主牌库刷新，也不改变原有放置顺序。

卡文没有限定只可返回 Active Energy，测试因此包含已 Wait 的 Energy 作为费用 / 分支目标。
这属于固定卡文与模型约束的程序审计，不是全卡人工裁定；未重新抓取官网或引入 FAQ。

## 修正前后的真实流程

先用实际 registry 定义执行完整步骤，复现了5项序列化 / runtime 读取失败，然后修 executor。

| 流程 | 修正前 | 修正后 |
|---|---|---|
| 柊摩央：起动 → 选2张 Energy 支付 | 卡已返回，后续读取报错 | 两张返回且背面，快照可读 |
| 支付后刷新 → 选择控室 Live | 无法继续 | 正常回手，不重复支付，次数限制生效 |
| ウィーン：真实 Live 开始节点 | 能正确触发 | 维持真实 trigger 入队 |
| 选择 Energy 分支 → 再选择1张 Energy | 结算后 JSON / Replay 报错 | Active / Wait 均能返回并正常重放 |
| 改选弃手牌分支 | Energy 不应变化 | 正确弃1手牌，Energy 区及牌库不变 |
| 选择非法ID、重复卡、错误数量或非Energy | 不应改变状态 | 费用、区域、revision、原状态均不变 |

`tests/test_energy_return_replay.py` 共 **26项**：实际分段起动、支付后恢复、实际 Live 开始、
两分支、两种朝向、次数限制、非法原子性、真实 runtime Replay、canonical hash、三种 AI policy
以及对手私有手牌身份不变性。两个 effect 保持 `test_validated_executable / test_validated`。

API 也执行了实际费用支付后的 GET 恢复与 Replay 导出，不只验证 helper 返回值。
三种 AI 每一步都提交 legal action，并在每个中间状态重新反序列化，不能靠最终状态掩盖支付阶段损坏。

## 已损坏的旧对局

不自动改写旧 SQLite、旧 initial/current JSON 或旧 hash。

- 仍有效的旧快照保持原有形状和 canonical hash，没有新增策略字段。
- 已保存空朝向等无效字段的快照，读取 / 操作 / Replay 返回
  `409`、`code=invalid_match_snapshot`，提示开新对局，不伪称重放一致。
- 正常快照的 Replay 一致性检查仍保留；没有放宽相等断言或悄悄归一化历史结果。
- HTTP 错误不返回 Pydantic 原始输入、手牌内容或 token；认证检查仍在读取之前。
- Hosted 房间中双方收到同样的安全诊断；SSE 发送 `room_error` 后结束，不输出半个局面。
- 前端在对战画面显示中日文提示，对这类永久错误停止 SSE / 轮询重试；普通断线仍保留低频恢复。

三项前端测试覆盖永久错误、晚到的临时错误不重新开启轮询，以及无 SSE 时 HTTP 轮询被明确停止。
无需新导入卡库或修改配置。旧损坏对局请保留原数据库副本供诊断，再新建对局；本轮不操作生产数据。

## 固定 AI 回归与限制

20 Deck 池、seed `12000..12009`，10场 AI vs AI、600 action cap：

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

10/10 完赛，平均7.2回合、最长19，未出现 blocker / skipped effect / Replay序列化错误。
严格“10回合内且双方至少1次成功 Live”仍为7/10，不宣称策略提高，也不声称随机池必定触发两张卡。
针对性状态与真实 API 测试才是本次修正的主要证据。原始 smoke 报告留在本机
`logs/continuous-energy-return-ai-20261025/`，不上传私有对局日志。

登记仍为 **899/1212（74.17%），313 manual**。复杂重叠检查时点 / 私有手牌选择仍在后续队列；
本轮不修改 Card Schema、MatchState 字段或 runtime SQLite schema。继续更新 Draft PR #54，不合并、不部署。
