# Memories：指定姓名一人获得Live临时Blade

## 本批结论

精确适配 `PL!SP-bp7-025:1`「Memories」。只使用已有`gain_blade`操作，但补充
显式 `public_single_as_much_as_possible` 选择策略：**Live开始时待机，结算时才选择**。
同名多份不能自动取第一张；有目标必须选一人，无目标时忽略该项并明确结束。

登记 **905/1212（74.67%），307 manual**。本次只提升一段为
`test_validated_executable / test_validated`，不提升reviewed，不改变Card/SQLite schema。
同一分支及Draft PR #54，不合并部署；旧44/6项dirty与ignored报告不改。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP07/PL!SP-bp7-025-L.png" width="200" alt="Memories 官方卡面，测试并非独立人工裁定">

| 绑定字段 | 当前本地正式数据 |
|---|---|
| 卡号/技能段 | `PL!SP-bp7-025:1`，Live，effect index1 |
| text revision | `928` |
| 全文SHA-256 | `76ad7caa94837eb2944d4236b2339690552e985a14129513e981c03cf8e0ad39` |
| Trigger / 选择 | `live_started`，己方顶部Stage Member，姓名「嵐 千砂都」，1人 |
| Operation / duration | 对选定卡 `gain_blade +1`，`live` |
| 频次 | 沿用Registry的Live时点约定`once_per_live`，不是新增【ターン1回】限制 |

官方日文：

> 【ライブ開始時】ライブ終了時まで、自分のステージにいる「嵐 千砂都」1人は【ブレード】を得る。

只绑定完整文本、revision与hash。姓名仅允许已有的空白标准化，不接受近似字、别名或后缀匹配。
候选流程仍只输出review候选，不覆盖Registry；专项通过后才手工更新此条，manifest已同步。

## 官方依据与时点

本地综合规则ver.1.06，PDF SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。

| 条款 | 实现含义 |
|---|---|
| 11.5.2 / 11.5.2.1 | 只在己方真正开始Live时触发，不在对方Live、手牌或成功Live区发动 |
| 9.7.2 / 9.5.3 | 待机和结算有先后顺序，其他能力可以先改变局面 |
| 9.6.3 / 9.6.3.1 | 结算时选择；有合格目标时必须选择指定的一人 |
| 9.6.3.1.3 | 一人也没有时，忽略目标相关效果；不能卡死或强制选对手/附属卡 |
| 9.6.2.4.2 | 来源卡离开原区域后，已经待机的能力仍可解算 |
| 4.1.4 / 8.4.11 | 离场不把旧对象加成带给新对象，Live结束解除期限补正 |

旧结构化无policy快照保持历史“目标不足时不入队”的行为，旧manual快照仍需人工处理。
新策略仅适用于无费用、强制、Live开始、单一姓名己方Member和Blade+1，其他用途明确拒绝。
不会改变所有旧技能或把私有手牌的“可不选”规则套到公开Stage。

## 人类可核对的状态结果

Source Live是实际卡库定义。Stage上的三张Member为受控测试卡（基础Blade1），
其中两张赋予相同姓名以验证选择，不冒充这些同名实际卡的全部能力。

| 场景 | 期望与实际断言 |
|---|---|
| 己方开始Live，场上两名千砂都 | 显示两个候选，modifier仍0；未点击选择不得确认 |
| 明确选择第二名 | 仅第二名Blade1→2；第一名与对手不变；进入应援阶段 |
| 目标为Wait | 同样可选并获得Blade，不擅自把目标Active |
| 手里/控室/附属卡/对手有同名卡 | 不成为本技能合法目标 |
| 目标出现于另一项先结算的能力之后 | 原能力仍待机，新进入Stage的目标可在结算时选到 |
| 触发后唯一目标离场 | 结算接受零目标，记录`no_legal_stage_member_at_resolution`并正常结束 |
| Live开始时没有目标 | 同样先待机；若结算时仍没有，明示结果而非静默消失 |
| 来源Live先离场 | 不取消已待机效果，仍对结算时选定Member生效 |
| 目标获加成后离场并同ID回场 | 原定向补正清理，不跟随新对象回场 |
| Live结束 | modifier解除，Blade2→1 |
| 错误姓名、零选但有目标、重复/多选、跨玩家目标 | 原revision、zones、pending与hash不变 |

跨能力进场使用明确AUDIT手动能力fixture模拟先后顺序，不宣称另一张官方登场卡已自动化。
部分离场测试直接构造受控待机后快照，注明不是允许玩家绕过pending规则执行额外动作。

## 测试与报告

- `tests/test_named_live_blade.py`：**48项**定向状态/身份/旧快照/SQLite Replay/四AI/隐私断言。
- 图文报告 **66/66** 通过，其中27项真实operation状态、39项Registry契约；新增中日检查标签。
- 前端 **112项**通过，显式选择第二张同名卡的payload和零目标中日结果提示均有验证。
- 固定10局v1.2回归：10/10正式完赛，均10回合内且双方成功Live；完整报告保留在
  `logs/continuous-named-live-ai10-20261026/`。没有实际触发本次Memories，不能冒充新技能随机实战覆盖。
- 全量工程门禁通过记录以本批`loop check`结果为准，不以文档文字代替真实证据。

图文原始报告：`logs/continuous-named-live-effects-20261026/effect-verification-report.zh-CN.md`。
仍有1项既有逐步规则review和4项Live条款解释待审；不是独立模型或人工全局裁定通过。
产品AI默认仍v1.1，策略未改，不把合法选择当作强度提高。

## 六条复杂登场继续保留

本轮不再增加只有受控fixture的新登场层，也不恢复这六条的旧可执行标签。
已有区域/朝向/身份/私有零张/公开来源门禁不等于完整临时多Member场面已实现。

| effect ID | 继续manual的具体原因 |
|---|---|
| `PL!-PR-015:1` | `temporary_overlap_and_inherited_observers_unresolved`；Baton条件已修，仍需完整已有区域登场的静态/继承观察者 |
| `PL!SP-PR-020:1` | 同上；不能用同文本继承未完成的旧原型审核结果 |
| `PL!N-pb1-013:1` | `conditional_overlap_stage_view_unresolved`；支付2Energy后姓名筛选及私有零张已建模，但未证明所有重叠临时条件 |
| `PL!N-pb1-015:1` | 同上；「桜坂しずく」筛选不消除附属/常时/跨玩家观察者问题 |
| `PL!N-pb1-017:1` | 同上；「宮下 愛」的入场仍需完整时点证明 |
| `PL!N-pb1-023:1` | 同上；「ミア・テイラー」的入场仍需完整时点证明 |

同类待审的`PL!SP-bp1-024:1`是两个姓名分别获得不同加成，现自动上限选择需另做受控复现；
部分姓名缺席的多组选择不属于本批单目标策略，不声称已修复。后续按有限任务推进。
