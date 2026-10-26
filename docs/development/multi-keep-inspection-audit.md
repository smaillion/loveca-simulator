# 顶7最多取3张：保守人工边界与旧Replay审计

## 结论

**本批没有实现新的自动技能。** 渡辺曜`PL!S-bp2-005:1`从`test_validated_executable`保守回退为
`manual_resolution / parsed_draft`，原因登记为：
`printed_heart_icon_scope_and_multi_keep_executor_unresolved`。
真实覆盖由915调整为**914/1212（75.41%），298 manual**，不虚标人工`reviewed`。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP02/PL!S-bp2-005-P.png" width="180" alt="渡辺 曜">

| 身份 | 核对值 |
|---|---|
| effect ID | PL!S-bp2-005:1 |
| 官方名 / 实际登场cost | 渡辺 曜 /13 |
| text revision |548|
| 原文SHA-256 |1d864314344a8d252f580ccee32897f33b3926a9ee9ff37cc5ca64439197da93|
| 操作形态 | 可选弃手牌1，查看顶7，从指定Heart条件的Member中最多3张公开入手，余牌控室 |

卡文写「【heart02】か【heart04】か【heart05】を持つ」，没有前批「ハートに」的信息栏限定。
当前旧过滤器仅检查Member基础Heart，带指定色Blade Heart但基础Heart不符的Member不会进入候补。
这是**未建模风险的复现，不是本批宣称官方一定要求纳入该卡的最终裁定**。
原费用策略只允许最多取1张，也不能直接为本卡放宽旧策略。

## 官方依据与尚缺证据

重读本地综合规则ver.1.06，PDF SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
2.1.3说明带Blade的Heart图标与同色无Blade图标的关系；2.7.1说明Yell信息，2.9.1–3说明Member Heart；
9.3.4约束有效区域。它们不足以在本次审计中独立确认本卡未限定“持有”的完整筛选范围与ALL边界。
未重新抓取FAQ，也没有独立人工裁定，因此保守隔离，而非猜测补一个图标OR条件。
费用9.4.2/9.7.3.2、查看5.7.1和刷新10.2.2.2/10.2.3仅作为费用/历史路径核对依据。

## 新对局边界

- 精确全文绑定人工候补，移除旧通用自动模式，避免下次生成候补又把它自动晋级。
- 登场仍按真实cost13支付Energy；**技能费用、顶7查看和回收不再自动执行**。
- 人类界面展示原文，可选“不使用”或进入结构化人工处理；不显示误导的自动结算按钮。
- 可选“不使用”正常结束待机，不支付、不查看、不记错误skip。
- 四种AI均明确选择`decline_optional_manual_effect`，持久化`ai_action_selected`事件和SQL Replay；
  这不是自动完成技能，也不是静默忽略强制效果。
- 人工接管专项只用显式AUDIT标记验证入口、记录和Replay，不冒充已完成卡文的全部人工结算。

## 旧快照兼容，不冒充规则认可

21项卡牌专项中，旧可执行snapshot仍使用原始max3和基础Heart过滤；不回写旧对局数据。
真实SQL验证取0/1/2/3、非法4张/重复/Live/对手牌原子拒绝、费用只支付一次、顶7余牌、短牌库刷新顺序。
旧无费用直接确认仍会原子报错，可拒绝技能继续；新人工边界没有自动付款或查看。
这些是**历史行为和Replay兼容证据，不是官方规则符合性通过**。
来源实际cost13来自卡库，候补为明确AUDIT fixture，不冒充整副合法牌组历史。

## 验证结果

- 21项卡牌专项与5项既有候补/报告/gap回归通过。
- 四AI的新人工辞退记录、SQL Replay、隐藏手牌身份不变、输入状态不变均有断言。
- 前端214项及TypeScript/build通过，人工按钮、完整原文与可选辞退有真实交互断言。
- 图文173/173：135项状态转换/边界、38登记契约。
  旧错误自动登记契约删除，替换为有费用和无费用的两项人工保护/辞退场景；两项不计作自动技能支持。
  `logs/continuous-multi-keep-effects-20261026/effect-verification-report.zh-CN.md`。
- 固定AI10/10在`3,6,5,6,9,4,9,5,7,6`回合正式决胜，双方成功Live、Replay一致；**本卡触发0次**。
  `logs/continuous-multi-keep-ai10-20261026/`，不替代专项，既有步骤review/Live解释待审保留。
- 完整control/registry/backend/web、manifest和pre-push由协调器保存最终源码指纹。

不改engine、Card/SQLite schema、API或牌组格式；默认AI仍v1.1，旧44/6项dirty及ignored报告保留。
同一分支与Draft PR54，不合并、不部署。下一批以真实manual触发重建优先级，不反复用低风险十局冒充技能覆盖。
