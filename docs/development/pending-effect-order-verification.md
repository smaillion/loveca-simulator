# 待机能力顺序与结算锁定验证

## 修正范围

新建对局中，同一玩家有多个待机能力时，不再按插入顺序抢先自动执行。
玩家可在技能面板选择先处理哪一个；AP 的能力优先，处理完一个后重新检查 AP / NAP。
费用已支付、分支已确定、检查牌堆或双方选择尚未结束时，必须先完成当前能力。

这不是新增卡牌登记：仍为 **899/1212（74.17%），313 manual**。
两张 PR 卡与四条虹咲的效果登场仍 manual，不提升 reviewed 状态。

## 固定官方依据

本地综合规则 ver.1.06，第7、10、11页；PDF SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。

| 条款 | 本切片的实现含义 |
|---|---|
| 7.2.1.1 / 7.2.1.2 | 指定回合玩家的阶段使用该玩家；公共 Live Set / 判定阶段使用先攻作为 AP，不照搬界面当前操作人 |
| 9.5.3.2 / 9.5.3.3 | AP 有待机能力时先处理 AP，结算后重检；AP 没有后才处理 NAP |
| 9.7.3 | 自己多个待机能力的处理顺序可选择，不等于可取消强制能力 |

本报告是固定 PDF 下的程序与状态验证，不是完整人工裁定或 FAQ 审核。
9.5.3.1 的所有规则处理优先级、任意临时重叠、复杂常时/继承/替换效果仍未完整实现。

## 可复核的真实状态差异

采用实际登记 `PL!N-pb1-005:1` 宮下愛的 cost10 登場观察者，
与一条明确标注为 **AUDIT 受控效果** 的“手牌补到4张”登場能力组合。
后者不是另一张正式卡牌的完整技能，不作为登记或覆盖率证据。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBnj/PL!N-pb1-005-P2.png" width="170" alt="宮下愛，官方卡面示意，不是测试截图">

宮下愛原文：

> 【自動】【ターン1回】自分のステージにコスト10のメンバーが登場したとき、カードを1枚引く。

普通替换后手牌剩2张，两个能力已触发但都尚未抽牌：

| 玩家选定顺序 | 结算过程 | 实际最终手牌 |
|---|---|---:|
| 愛先，AUDIT 后 | 2 → 抽1变3 → 补到4 | 4 |
| AUDIT 先，愛后 | 2 → 补到4 → 抽1 | 5 |
| 旧快照没有新策略 | 保留历史上的自动插入顺序 | 4 |

两个顺序均通过实际 runtime SQLite 写入、重新读取和 Replay 最终状态比较。
测试不直接改最终手牌，也不以 mock 日志冒充状态转换。

## 顺序与中间步骤保护

- 队列先插入 NAP，不会让 NAP 抢在 AP 前。先攻 / 后攻 Main 与公共 Live 阶段分别测试。
- AP 的可选能力拒绝后，才向 NAP 暴露下一操作；强制能力不能按普通拒绝取消。
- 已付费的手牌选择先完成，不重复扣费；不能 resolve 或 debug skip 同玩家的另一个能力来插队。
- 双方选择锁定父能力，后出现的 AP 能力也不能中途打断；双方完成后才重新检查。
- 带来源的手动处理和手动检查也执行同一顺序校验，不用 ManualAdjustment 冒充能力排序。
- 非法顺序被拒绝时，原状态、revision、费用和 pending queue 不变。
- 三种现有 AI 都从原生 LegalAction 提交 `resolve_effect`；更换对手隐藏手牌身份不会改变决策。
- UI 只读取引擎的 `effect_order_choice` 标记，展示来源和原文，不自行判断触发时点。

## 兼容性

新建本地 / Hosted 对局由 MatchService 显式设置：

```json
{"effect_order_policy": "ap_nap_player_choice"}
```

这是独立于 `member_overlap_policy` 的可选 MatchState 字段。缺省 None 且序列化省略，
包括已有重叠策略但未带新字段的旧快照，也保留历史 eager 顺序和 Replay 行为。
验证新行为请新开对局；不升级 Card Schema / runtime SQLite，不迁移旧 JSON 或重写 hash。
创建请求、`controllers: simple_ai` 和 `resolve_effect` 的 payload 契约保持不变。

## 实测证据

- `test_pending_effect_order.py`：21项，包括真实抽牌顺序、SQL Replay、顺序原子性、
  费用续步、双方选择、三种 AI 私有信息独立性、新 API 默认策略和旧快照兼容。
- 与 `test_multi_player_entry.py` 合跑：**47 passed**。
- `App.test.tsx`：**85 passed**，新增原生顺序选择提交测试。
- 固定20 Deck池、seed12000–12009、600 action cap：10/10 AI完赛，平均7.2回合，最长19。
  无 blocker、skipped effect 或 Replay序列化错误；严格“10回合内且双方至少1次成功Live”为7/10。
  与前批一致，不宣称 AI 强度提升，也不宣称随机池实际覆盖了本次受控技能组合。
- 原始报告保留在本地 `logs/continuous-effect-order-ai-20261025/simple-ai-report.md`，不上传私有运行日志。

父任务 `effect-overlap-trigger-and-private-choice` 继续进行，下一步仍需逐卡处理复杂入场时点。
只更新同一分支和 Draft PR #54；不合并、不部署，不动旧 dirty 工作树或生产数据。
