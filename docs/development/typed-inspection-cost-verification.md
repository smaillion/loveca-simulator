# 登场检索：三种费用与无法支付时的正确结束

后续更新：本报告列出的7条单Wait及3条虹咲手牌费用已逐卡复现并修正，
见[既有检索费用审计](existing-inspection-cost-audit.md)。以下保留本批历史证据，不代表剩余检索均已正确。

## 本批结果

新登记3段`test_validated_executable / test_validated`，不提升人工reviewed。
**912→915/1212（75.50%），manual300→297**。同一continuous分支及Draft PR #54，
不合并部署，不改Card/SQLite schema、牌组或controllers API；旧44/6项dirty及ignored报告不改。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBLL02/PL!-pb2-032-N.png" width="165" alt="星空凛">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP07/PL!SP-bp7-018-N.png" width="165" alt="米女メイ">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBLL02/PL!-pb2-008-PP.png" width="165" alt="小泉花陽">

| 技能 / revision | 费用 | 查看后选择 |
|---|---|---|
| `PL!-pb2-032:1` 星空凛 /1005 | 必须弃自己手牌1张，不可随意拒绝 | 顶5，任选0–1张无Blade Heart的μ's Member公开入手，其余控室 |
| `PL!SP-bp7-018:1` 米女メイ /905 | 可选弃手牌Live1张，不能弃Member | 顶5，必须取1张，不公开所选牌，其余控室 |
| `PL!-pb2-008:1` 小泉花陽 /981 | 可选将原来源自身Active→Wait | 顶4，任选0–1张必要Heart总数≥8的μ's Live公开入手，其余控室 |

每条均固定全文SHA-256并完整技能段匹配，正文增加未知一句后不再命中。
105项测试的来源卡来自实际卡库，正常登场费用分别为4/4/2；候补顶牌和控制能力为明确AUDIT fixture。

## 实际发现与处理

三项原生登场红测首先确认旧登记均manual。随后复现既有检索路径的两个缺口：
来源已Wait仍重复付Wait费用；没有合法手牌费用时留下无法正常确认的待机。

新增有界`cost_payment_policy=triggered_inspection`，只用于本批新快照。
模型只接受固定on-play检索、一个手牌弃牌或自身Wait费用；不同trigger、混合费用、
动态数量、额外操作等未验证语义被拒绝，不变成任意效果DSL。

| 局面 / 操作 | 实际结果 |
|---|---|
| 强制手牌费用且手牌足够，点击拒绝 | 原子拒绝；必须付费，但之后可以保留0张 |
| Live费用，选择手中Member / 对手 / 重复 / 已登场来源 | 原子拒绝，不付费、不查看 |
| 已Wait或原来源离场后同ID回场 | 不重复Wait，不向新对象收取旧能力费用；取消原因明确记录 |
| 费用不足，选择这条待机 | LegalAction取消不可完成的选择要求，界面允许“结束此能力”；不查看、不付费、不错误skip |
| 先选择另一个待机补出手牌费用 | 重新计算费用后可正常检索，不在触发时提前删除技能 |
| 卡文指定公开 / 没有公开字样 | 对手分别能 / 不能看到选入手牌的卡；查看过程始终私有 |
| 必要Heart7 /8 /彩色与无色之和8 | 分别排除 /允许 /允许，不把基本Heart当Live必要Heart |
| 牌库不足 | 先付费用，再在剩余牌下刷新，然后查看；费用不重付 |
| 四种AI、旧manual与新SQL Replay | 均使用原生Action，最终snapshot一致，无非法操作或调试跳过 |

## 官方依据与边界

固定本地综合规则ver.1.06，SHA-256
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。

- 9.4.1–2：冒号前为费用，只能付己方资源，不能支付不可能的动作。
- 9.7.3.1.1 /9.7.3.2：区分可选费用；选定待机无法发动时取消该次待机，不擅自发动效果。
- 4.1.4：原来源离场与同ID新对象区分；复用原来源离场跟踪。
- 5.7.1 /10.2.2.2–3：准确查看与查看前不足牌库的刷新顺序。
- 11.4.2及各自卡文：真实登场、作品/类型/Blade Heart/必要Heart筛选和公开要求。

旧快照没有新策略字段，序列化不补写，也不追溯改变历史行为。
这意味着**尚未证明所有旧检索费用均正确**。扫描命中的7条单Wait检索优先复核：
`PL!-bp3-014/017/018:1`、`PL!N-bp3-022:1`、`PL!N-bp4-016:1`、
`PL!S-bp6-018:1`、`PL!SP-bp4-002:1`。混合费用与其他手牌费用也没有批量套用策略；
下一任务逐卡复现后决定适配或保留unresolved。登记率不等于全卡裁判认证。

## 证据

- `tests/test_typed_inspection_costs.py`：105项；与上一批检索和报告合计208项通过。
- 前端128项、TypeScript/build通过，强制费用不能假装可拒绝，不可支付可正常结束，私下保留必须选1。
- 图文**80/80**：41项真实状态、39项契约；新场景用受控cost0来源隔离检索，真实卡费另有定向测试。
  `logs/continuous-typed-inspection-effects-20261026/effect-verification-report.zh-CN.md`。
- 固定10局v1.2均3–9回合正式胜负、双方有成功Live、Replay一致；本批三卡未触发，不冒充随机实战覆盖。
  `logs/continuous-typed-inspection-ai10-20261026/`保留原始比赛与Live审计，不能代替本批定向验证。
- 全量control/registry/backend/web、manifest和pre-push由协调器记录指纹；产品AI默认v1.1不变。

仍保留既有1项步骤review、4项Live条款解释待审及六条复杂重叠/继承manual限制。
