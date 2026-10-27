# 重叠清理前的登場观察者：宮下愛验证

## 本轮修正

修正既有登记 `PL!N-pb1-005:1`：当费用10的 Member 普通登场到宮下愛所在区域时，
先发生新 Member 登場，再于检查时点处理重叠。愛虽然随后进控室，已经触发的抽1仍需结算。
旧代码清理后只枚举留在 Stage 的观察者，漏掉了她。

本轮不是增加登记数量，仍为 **899/1212（74.17%），313 manual**。
只解决固定抽牌观察者的一个有限家族，不是完整重叠或自动能力排序器。

| 卡牌 | 当前本地正式数据 |
|---|---|
| 卡号 / 名称 | `PL!N-pb1-005` / 宮下 愛，Member cost2 |
| effect identity | `PL!N-pb1-005:1`，revision312，effect index1 |
| 原文 hash | `a24c05703cd27bdf500e947ef67c575ee7ef3c5fba24dc06ced37d0b2b504a8b` |
| 登记 | 原有 `test_validated_executable / test_validated`，未提升 reviewed |

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBnj/PL!N-pb1-005-P2.png" width="170" alt="宮下愛，官方卡面示意而非测试截图">

官方原文：

> 【自動】【ターン1回】自分のステージにコスト10のメンバーが登場したとき、カードを1枚引く。

卡面、属性、effect ID 和文本直接从当前锁版本数据库与 registry 读取，不重新抓取官网。
入场的 cost10 Member 是明确的受控测试卡，不冒充另一张实际卡的完整技能。

## 规则依据

只读综合规则 ver.1.06，第10–12页；PDF SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。

| 条款 | 审计含义 |
|---|---|
| 9.6.2.3.2 | Baton 是在新 Member 入场前支付费用时让旧 Member 离场 |
| 9.7.2 | 条件满足时进入待机，不要求立刻结算 |
| 9.7.7 | 已触发能力的来源随后移动区域，仍须处理 |
| 10.1.2 / 10.4.1 | 普通替换的重叠清理在检查时点，不可把它等同 Baton |
| 9.5.3 / 9.7.3 | 自动能力等待当前动作 / 父效果结束；一般 AP/NAP 自由排序仍未完成 |

这是基于固定 PDF 的程序验证，不是全卡人工裁定；没有推测 FAQ、replacement 或继承语义。

## 修正前后可核对的局面

宮下愛在中央，手牌3张，含一张受控 cost10 Member，场上10张 Active Energy。

| 操作 | 修正前 | 新建对局修正后 |
|---|---|---|
| 普通登场到中央，支付10 | 愛进控室，手牌只剩2张；漏抽1 | 愛先观察到登場，进控室后抽1，最终手牌3张 |
| Baton 到中央，支付8 | 愛作为费用先离场，不观察入场 | 仍不抽牌，最终手牌2张，保留2 Active Energy |
| 入场费用为2 / 9 / 11 | 不应触发 | 不触发，不能把条件简化为大于等于10 |
| 本回合已发动过一次 | 不应再次触发 | 不重置次数，不重复抽牌 |
| 费用不足、重复Energy、非法区域/卡 | 不应部分提交 | 原状态、费用和待机队列均不变 |

先复现两项红测：普通替换漏抽1、受控效果登場拒绝这个安全观察者；再实现修正。
`tests/test_overlap_entry_observer.py` 共 **29项**，包含 player2 对称操作。

## 有界实现及旧 Replay

新增可选 MatchState 字段：

```json
{"member_overlap_policy": "capture_fixed_draw_entry_observers"}
```

新建本地 / Hosted room 对局由 MatchService 显式启用，不需要改变创建请求。
旧快照缺省 None 且序列化省略此字段，旧对局仍按原行为运行和重放；**验证修正请新开对局**。
没有升级 Card Schema 或 runtime SQLite schema，没有改写旧 JSON、历史事件或 hash。

策略只接纳单一 `own_member_played`、自动且无费用/选择、固定抽自身牌库的操作。
条件只能读取入场卡本身的 cost / work / unit / 是否为自身，不能读取临时场面、来源位置或继承。
本地 registry 中当前只有 `PL!N-pb1-005:1` 满足这组边界。

普通登场在清理旧 Member 前捕获合规观察者，然后才处理离场，最后结算待机抽牌。
受控 `deploy_selected_to_stage` 同样支持这个家族，费用和区域验证仍在执行前完成，
父技能结束后才抽牌。Baton 不走此捕获路径，也不会虚构重复登場。

复杂观察者在受控效果登場中仍排除区域；普通登场遇到此类旧观察者时记录
`effect_not_activatable / overlap_entry_observer_requires_timing_review`，不伪造已完成结算。
日志以中日文提示需要手动确认。明确不匹配的入场卡条件不会产生无关警告。

## 回归证据

- 新旧实际 SQLite Replay：事件、最终状态、canonical hash 一致；旧无字段快照保持旧漏抽结果，
  不用新引擎偷偷改写成“历史上已正确抽牌”。
- 本地与房间创建 API 都启用新策略，旧请求无须加参数。
- 三种 Simple AI 均能通过原生 LegalAction 处理受控登場，改变对手隐藏手牌身份不改变决策。
- 双方画面隐藏对手手牌，新抽到的牌不进入对手可见卡牌字典。
- 前端验证未审重叠观察者的可读提示；不做对战 Layout 重构。

固定20 Deck池、seed12000–12009、10局AI、600 action cap：
10/10完赛，平均7.2回合、最长19，无 blocker / skipped effect / Replay序列化错误。
严格“10回合内且双方至少1次成功Live”仍为7/10；与前批相同，不宣称策略提升或随机池触发了本卡。
完整每局记录同前批固定池，原始输出保存在
`logs/continuous-overlap-entry-ai-20261025/simple-ai-report.md`，不上传私有日志。

## 下一步边界

本轮没有在 MatchState 中加入任意临时多 Member 场面，也没有宣称条件式 / 常时 / 继承 /
跨玩家观察者及 AP/NAP 可选排序正确。`effect-overlap-trigger-and-private-choice` 父任务继续保留。
两张 PR 卡与四条虹咲仍 manual；需要逐卡状态 / Replay / UI / AI 验收后才能晋级。
继续同一分支和 Draft PR #54；不合并、不部署，不改旧工作树或生产数据。
