# 彼方与嵐珠：选择虹咲成员Wait作费用，自身获得加成

## 本批结论

新增两段`test_validated_executable / test_validated`，不提升reviewed。
当前**908/1212（74.92%），304 manual**。复用既有Wait、Blade、Heart、颜色选择和原来源对象跟踪，
只增加显式、受限的Stage费用策略。不改Card、SQLite schema、deck格式或controllers API。
同一continuous分支及Draft PR #54，不合并部署；旧44/6项dirty与ignored原始报告不改。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/NSD02/PL!N-sd2-006-SD2.png" width="190" alt="近江彼方 官方卡面">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP07/PL!N-bp7-012-R.png" width="190" alt="鐘 嵐珠 官方卡面">

| 技能段 | revision / 全文SHA-256 |
|---|---|
| `PL!N-sd2-006:1` 近江彼方 | 937 / `1626135ef08789e583f9e8927e1640e9838f194f28d30f39ced8d1f3510f3647` |
| `PL!N-bp7-012:1` 鐘 嵐珠 | 875 / `c926270668f310d00897f094d0f60ba6de0268664a8588ee139168762e140ac5` |

官方日文：

> 【ライブ開始時】『虹ヶ咲』のメンバー1人をウェイトにしてもよい：ライブ終了時まで、【ブレード】【ブレード】を得る。

> 【ライブ開始時】『虹ヶ咲』のメンバー1人をウェイトにしてもよい：好きなハートの色を1つ指定する。ライブ終了時まで、そのハートを1つ得る。

只匹配完整原文，不使用模糊文本或同名近似。两项红测都从实际卡库定义开始Live，确认旧状态为manual。

## 规则依据

固定本地综合规则ver.1.06，PDF SHA-256
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。

| 条款 | 本批约束 |
|---|---|
| 9.4.1 / 9.4.2.1–3 | 冒号前为费用，只能使用自己资源，不能支付不可能的Wait费用 |
| 5.2.1 / 9.6.3 | 选定合法Active成员再置Wait；可选费用可拒绝，不擅自等待第一张 |
| 9.7.2 / 11.5.2 | 真实己方Live开始后待机，费用与颜色走原生LegalAction |
| 8.3.10 / 8.3.11 | 只合计Active成员Blade，按合计张数执行应援 |
| 8.3.14 | 所有己方成员的Heart计入，不把Wait等同于Heart失效 |
| 4.1.4 / 9.9.2 | 原来源离场后不向控室或同ID再登场的新对象应用旧加成 |
| 8.4.11 | Live结束解除期限修正，不擅自退还Wait费用 |

这是程序化状态验证和规则解释，不是独立人工裁判认证；既有4项Live条款解释待审保持不变。

## 可核对的实际状态

来源Member取实际卡库定义。费用成员、错误作品成员、手牌、附属卡及控制能力为明确AUDIT fixture，
不宣称这些受控卡的其他真实能力已被验证。

| 场景 / 操作 | 期望与实际 |
|---|---|
| 自己Stage上Active来源与另一Active虹咲成员 | 两者都可作为费用候补，错误作品/对手/手牌/附属成员不出现 |
| 选另一成员支付彼方技能 | 费用成员Wait，彼方自身Blade+2；费用成员不被加Blade |
| 选择彼方自身支付 | 彼方Wait并有Blade+2，但原生Yell只计其他Active成员，不计其Blade |
| 选另一成员与黄色支付嵐珠技能 | 费用成员Wait，嵐珠自身黄Heart+1，期限Live；不把费用目标当作受益人 |
| 六种颜色 | 各自只增加所选色1颗；任意色、未知色与未选颜色原子拒绝 |
| 费用成员已Wait | 不能再作为费用；没有Active合格者时明确不可发动，不产生卡死prompt |
| 拒绝可选能力 | 所有原Active成员维持Active，不产生加成 |
| 多选、重复、错误作品、对手Stage、手牌、附属卡、未知ID | 不支付、不修改revision/hash/pending |
| 另一待机控制能力先使来源离场或同ID回场 | 仍可支付其他合法费用，但不向旧区域或新对象加成，明示原因，正常结束 |
| Live结束 | 清理临时加成，不把费用成员复原Active |
| 旧manual与新结构化SQLite Replay | 最终snapshot一致，旧manual仍手动，不补造新策略 |

来源离场通过另一个AUDIT手动待机能力与合法ManualAdjustmentAction完成，
不是允许玩家跳过pending顺序。费用卡与加成目标的区分直接复用既有cost-selected清理，不新增任意目标DSL。

## 验证证据

- `tests/test_live_wait_cost.py`：63项费用、目标、六色、Yell、原来源、SQL Replay、四AI/隐私与策略边界断言。
- 前端120项与TypeScript/build通过，新增Wait费用的单目标/选色组合提交及Blade不适用中日提示。
- 图文72/72：33真实状态转换、39Registry契约，报告
  `logs/continuous-wait-cost-effects-20261026/effect-verification-report.zh-CN.md`。
- 固定10局v1.2：10/10正式完赛，3–9回合，双方至少各一次成功Live、Replay一致。
  逐步5454pass/1既有review，Live20/20与4项条款解释待审；日志
  `logs/continuous-wait-cost-ai10-20261026/`保留ignored。没有触发本批两卡，不替代定向证据。
- 全量工程门禁、manifest、pre-push与源码指纹由本批协调器证据保存。

产品AI默认v1.1不变，不声称强度提高。重叠/继承父任务仍为
`temporary_overlap_stage_view_and_inheritance_unresolved`，六条相关技能保持manual。
