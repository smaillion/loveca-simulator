# 鐘嵐珠离场后的 Wait Energy 结算验证

## 本轮结论

修正已有登记 **`PL!N-pb1-012:1` 鐘嵐珠**：另一张 cost11 Member 普通登场到她的区域时，
先触发能量补充；即使嵐珠随后因重叠进入控室，仍从 Energy Deck 顶部放置1张正面 Wait Energy。
不能把普通替换与 Baton 费用离场混为一谈。

本轮没有新增或晋级登记，仍为 **899/1212（74.17%），313 manual**。
两张 PR 卡和四条虹咲的复杂效果登场继续 manual，不提升人工 reviewed 状态。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBnj/PL!N-pb1-012-P2.png" width="180" alt="鐘嵐珠官方卡面示意，并非测试截图">

| 身份 | 锁版本数据 |
|---|---|
| 名称 / 卡号 | 鐘 嵐珠 / `PL!N-pb1-012`，Member cost11 |
| 技能 | `PL!N-pb1-012:1`，revision319，effect index1 |
| 完整卡文 hash | `aa2d2e25f4d9eb9741b0f26ae21790d8db8aa87b9849686b4804d2976d5f73ca` |
| 当前登记 | 原有 `test_validated_executable / test_validated`，没有提升审核等级 |

官方日文原文：

> 【自動】【ターン1回】自分のステージにこのメンバー以外のコスト11のメンバーが登場したとき、自分のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置く。

卡面链接、属性、两段能力、revision 和 hash 均从当前本地卡库 / registry 读取，不重新抓取官网。
第二段 `ライブ成功時` 能力在该时点不会触发，不能仅因为卡上有另一段不相关能力就排除区域。

## 官方依据

只读本地综合规则 ver.1.06，PDF SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。

| 条款 | 本次验证依据 |
|---|---|
| 9.7.2 / 9.7.7 | 条件发生后能力待机，来源卡随后移动区域不取消待机能力 |
| 9.6.2.3.2 | Baton 在入场前先让旧 Member 作为费用离场，旧来源不再观察后续登場 |
| 9.5.3 / 10.4.1 | 先完成当前动作 / 父效果及重叠规则处理，再处理待机能力 |
| 10.5.4 / 10.5.5 | 附属 Energy 随离场整理回 Energy Deck，不进控室 |

“Energy Deck 至少有1张”不是这段日文的登場诱发条件。本切片对被捕获的固定 Wait Energy
观察者，把能量可用性留到实际操作时确认，因此可以使用重叠整理刚返还的 Energy。
没有更改一般技能的资源/费用可发动检查，也没有推测 FAQ、continuous 或 replacement 语义。

## 两项红测与修正后的真实状态

先用上一版新建对局的 fixed-draw 策略复现两项失败，均不是仅对照 registry 字段。
随后为新建对局显式启用新版本，保留旧版本 Replay。

| 场面 / 操作 | 修正前 | 新版本实际结果 |
|---|---|---|
| 嵐珠在中央，另一张 cost11 普通登场，Energy Deck `[E0,E1]` | 嵐珠进控室，但没有补能量 | 顶部 E0 正面 Wait 进入 Energy Area；Deck 仍为 `[E1]` |
| 嵐珠下有 Energy E，Energy Deck 为空，普通替换 | E 返回 Deck 后停留，技能被漏掉 | E 先返还 Deck，再以正面 Wait 补到 Energy Area |
| 同样 cost11 从嵐珠 Baton | 不应触发 | 不补能量；费用离场对照通过 |
| 本卡自己从手牌登场 | 不应触发自己 | 不补能量；另一张同名同卡号的卡则仍可触发旧嵐珠 |
| cost2 / 10 / 12 入场 | 不满足 exact cost11 | 均不补能量 |
| 本回合该来源已用过 | 不能重置次数 | 不重复触发 |
| Energy Deck 为空且无返还牌 | 应尽可能处理，不刷新能量牌库 | 待机能力结束，明确记录未放置原因；没有 debug skip |
| 先选另一项技能耗尽顶部 Energy | 不能凭空补牌或卡死 | 嵐珠结算时记录 `energy_deck_insufficient_at_resolution` 并结束 |

事件顺序断言为：嵐珠能力触发 → 旧 Member 重叠清理 → Energy 补充。
受控效果登场还断言父技能先完成，才让玩家 / AI 决定后续待机能力顺序。
费用只支付一次；非法卡牌、区域、重复 Energy、费用不足和过期 revision 均不改变原状态。

## 有界能力与兼容性

新建本地 / Hosted 对局使用：

```json
{"member_overlap_policy": "capture_fixed_draw_and_energy_entry_observers"}
```

旧 `capture_fixed_draw_entry_observers` 只支持原固定抽牌；None 仍省略字段。
两个旧版本继续保留历史行为，不以修正后的结果改写历史 Replay。
三种版本都经过实际 runtime SQLite 写入、重新读取、Replay 事件 / 最终状态 / hash 比较。
无需修改创建请求、Card Schema 或 runtime SQLite schema，验证新行为请新开对局。

新版本只额外接纳：单一 `own_member_played`、无费用/可选/后续选择、固定自身1张 Wait Energy，
过滤仅引用入场卡的固定信息。复杂来源位置、Stage 条件、非自身目标、数量变化、Active 放置、
继承和条件式离场仍明确受限；不能据此宣称通用瞬时重叠场面已经建模。
已有固定抽牌家族继续验证。卡上的独立 `live_succeeded` 段不会误当作登場/离场观察者。

## UI 与 AI 证据

- 新增 `test_overlap_energy_observer.py` **33项**；合并原抽牌观察者与 AP/NAP 排序回归为 **83 passed**。
- 正式卡牌实际能量移动、原始卡文身份、同名不同实例、空牌库、次数、费用原子性、旧 Replay、
  player2 对称流程均有状态断言。
- 受控父技能使用明确标记的 AUDIT fixture，不冒充另外六张待审卡已适配。
- 三种 Simple AI 都能从原生 LegalAction 完成受控登場与后续能力，不跳过；更换对手隐藏手牌身份
  不改变决策。双方 payload 均不包含对手手牌卡牌身份。
- App 组件测试 **88 passed**。结果通知显示 `能量补充 WAIT: 1 / エネルギー追加 WAIT: 1`，
  能量不足也有中日文说明；普通 Energy Phase 不弹技能结果通知。前端只读事件，不改变结算数据。

固定20 Deck池、seed12000–12009、600 action cap：10/10 AI完赛，平均7.2回合、最长19，
blocker / skipped effect / Replay序列化错误均为0。严格“10回合内且双方至少1次成功Live”仍为7/10，
不宣称策略强度提升，也不把随机池回归当作本卡的定向验证。
原始日志保留在 `logs/continuous-overlap-energy-ai-20261025/`，不提交私有局面日志。

完整重叠、条件式离场、来源属性及继承仍由父任务继续审计。
本报告是程序规则验证，不是全卡人工裁定。继续同一分支与 Draft PR #54，不合并、不部署，
不修改旧 dirty 工作树、生产数据或运行配置。
