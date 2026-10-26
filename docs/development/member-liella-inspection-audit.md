# Member与Liella检索：五条费用路径审计

## 本批范围

五条已有可执行技能接入已验证的`triggered_inspection`费用检查，不是增加五条覆盖。
登记仍**915/1212（75.50%），297 manual**；不提升人工`reviewed`，不改engine/Card/SQLite schema、牌组或对战API。
旧effect snapshot不补policy，旧Replay维持原行为。同一continuous分支和Draft PR54，未合并、未部署。
旧44/6项dirty工作树及ignored报告均保留。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP03/PL!S-bp3-P-004-P.png" width="130" alt="黒澤ダイヤ">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP03/PL!S-bp3-P-009-P.png" width="130" alt="黒澤ルビィ">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP01/PL!SP-bp1-005-P.png" width="130" alt="葉月 恋">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP02/PL!SP-bp2-007-P.png" width="130" alt="米女メイ">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBSP02/PL!SP-pb2-017-P2.png" width="130" alt="桜小路きな子">

| effect ID（均:1） | 官方名 | revision / 实际登场cost | 费用后查看与候补 |
|---|---|---|---|
| PL!S-bp3-004 | 黒澤ダイヤ |462 /5|顶4，不限作品的Member|
| PL!S-bp3-009 | 黒澤ルビィ |467 /9|顶6，Aqours作品Member|
| PL!SP-bp1-005 | 葉月 恋 |644 /2|顶5，Liella!作品卡，Member与Live都可|
| PL!SP-bp2-007 | 米女メイ |561 /5|顶5，Liella!作品Member|
| PL!SP-pb2-017 | 桜小路きな子 |813 /7|顶5，Liella!作品Member，独立卡库身份|

共同费用为「手札を1枚控え室に置いてもよい」，后文允许公开取得0–1张。
葉月恋文本使用「1枚まで」，其余使用「1枚…てもよい」；两者本批都允许零张，不能推广到必选取得。
完整日文段、原文SHA-256、独立revision与实际费用固定在`tests/test_member_liella_inspection.py`。
Aqours/Liella!是作品筛选，不额外增加组合条件；Blade Heart不是本批排除条件。

## 红测与原生状态验证

改动前逐卡原生登场并用尽手牌，直接确认都报`effect cost card selection is not legal`。
旧版仍可拒绝该技能结束，不能称为整局完全卡死；新版明确显示费用不足，取消已选待机且不查看。

| 操作 | 实际核对 |
|---|---|
| cost5/9/2/5/7原生登场 | Energy变Wait；手牌Member或Live均可作费用，仅支付一次 |
| 顶4/5/6的最后一张、范围外下一张 | 正确查看边界，不提前多看；Aqours第6张满足条件时可取 |
| 不同作品、Member/Live、带Blade Heart、不同组合 | 只使用卡文要求的类型/作品筛选；不增加组合或Blade Heart限制 |
| 取得零张或一张、没有符合条件的牌 | 正常结束，余牌到控室，无残留choice或待机 |
| 对手手牌、已登场来源、重复费用、非候补或未查看的牌 | 原子拒绝，原state hash/revision不变 |
| 另一待机先抽牌补费用 | SQL原生动作链之后仍可支付，不在触发时删除待机 |
| 费用不足、只剩费用牌可刷新、短牌库 | 不可支付不查看；可支付先弃费再刷新，保留既有牌顶，不二次收费 |
| 对手完整响应 | 私有查看不泄露，公开取得卡按卡文向对手显示 |
| 四AI与新旧SQL Replay | 使用LegalAction安全完成/取消，不修改决策输入，不依赖对手隐藏卡身份；最终Replay等于snapshot |

## 官方依据

本地综合规则ver.1.06，PDF SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
9.4.1–2核对冒号前费用与不能部分支付；9.7.3.1.1/9.7.3.2核对可选付款和待机取消；
5.7.1核对指定玩家查看；10.2.2.2/10.2.3核对查看不足时刷新、控室洗牌放在既有牌顶下。
公开取得、数量及类型/作品条件直接来自各卡完整后文，不推测FAQ。

## 测试与实战证据

- 165项专项通过；实际来源卡费来自卡库，候补和控制能力是明确AUDIT fixture，不冒充整副合法牌组历史。
- 前端207项、TypeScript及production build通过；每个ID分别验证费用不足结束与公开零张交互。
- 图文166/166，含127项真实状态转换、39登记契约。五条各有正常结算和无费用场景。
  `logs/continuous-member-liella-effects-20261026/effect-verification-report.zh-CN.md`。
  图文来源cost0只隔离技能，真实2/5/7/9费用由专项另测。
- 固定AI10/10在`3,6,5,6,9,4,9,5,7,6`回合正式决胜，双方有成功Live、Replay一致、错误skip为0。
  **葉月恋`PL!SP-bp1-005:1`实际触发、支付、查看、完成各5次**；其他四条未触发，以专项为准。
  全步骤、策略和Live报告位于`logs/continuous-member-liella-ai10-20261026/`。
  步骤审计5454 pass/1 review及4项既有Live解释待审保留，不宣称全规则人工认证或AI强度提升。
- 完整control/registry/backend/web、manifest及pre-push以协调器最终源码指纹证据为准。

剩余4条扫描不是4条已确认错误；下轮逐卡审计3条Member/Live混合Heart筛选。
`PL!S-bp2-005:1`最多取3张不适用当前最多取1张policy，继续单独待审，不为覆盖率扩大边界。
六条复杂重叠manual和旧工作树未改，默认AI仍v1.1。
