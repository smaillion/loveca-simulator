# 作品与组合检索：六条费用路径审计

## 结论与范围

六条已有可执行登记接入已有`triggered_inspection`费用检查；不是新增六条技能覆盖。
登记仍**915/1212（75.50%），297 manual**，不提升人工`reviewed`。
不改engine、Card/SQLite schema、对战API或牌组格式；旧effect snapshot不补写policy，旧Replay保持原行为。
只更新同一continuous分支和Draft PR54，未合并、未部署；旧44/6项dirty工作树及ignored报告保留。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP01/PL!HS-bp1-009-P.png" width="130" alt="安養寺 姫芽">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBHS/PL!HS-pb1-018-N.png" width="130" alt="村野さやか">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP03/PL!N-bp3-P-012-P.png" width="130" alt="鐘 嵐珠">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBSP/PL!SP-pb1-015-N.png" width="130" alt="平安名すみれ">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBSP/PL!SP-pb1-016-N.png" width="130" alt="葉月 恋">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBSP/PL!SP-pb1-017-N.png" width="130" alt="桜小路きな子">

| effect ID（均:1） | 官方名 | revision / 实际登场cost | 查看数量与候补 |
|---|---|---|---|
| PL!HS-bp1-009 | 安養寺 姫芽 |661 /4|顶5，みらくらぱーく！组合卡|
| PL!HS-pb1-018 | 村野さやか |133 /4|顶5，DOLLCHESTRA组合卡|
| PL!N-bp3-012 | 鐘 嵐珠 |485 /4|顶4，虹ヶ咲作品卡|
| PL!SP-pb1-015 | 平安名すみれ |615 /4|顶5，CatChu!组合卡|
| PL!SP-pb1-016 | 葉月 恋 |616 /4|顶5，KALEIDOSCORE组合卡|
| PL!SP-pb1-017 | 桜小路きな子 |617 /4|顶5，5yncri5e!组合卡|

共同费用为「手札を1枚控え室に置いてもよい」，之后「1枚公開して手札に加えてもよい」。
付款可拒绝，付款后也明确允许取零张；不是把可选付款泛化成任意技能都可空选。
完整日文段、独立原文hash/revision固定在`tests/test_work_unit_inspection.py`，不是按名字或前缀匹配。
组合键来自本地官方标准化卡库：`miracra_park / dollchestra / catchu / kaleidoscore / 5yncri5e`；
虹咲是作品键`nijigasaki`，不误当组合。不改同卡其他段。

## 复现与实际状态

改动前逐卡原生登场并耗尽手牌：六条直接确认都报`effect cost card selection is not legal`。
旧版仍可拒绝技能结束，不能称为整个对局完全无法继续；新版明确显示费用不足并正常取消所选待机。

| 操作 | 验证结果 |
|---|---|
| 实际cost4登场，Member或Live支付手牌费用 | 4张Energy变Wait；手牌费用仅进入控室一次，后续选牌不再次支付 |
| 同作品不同组合、不同作品、带多个组合的卡 | 组合严格按成员关系；作品检索不要求同组合，Member/Live均可候补 |
| 付款后选Member / Live / 零张 | 只有候补进入手牌；余牌进入控室，待机和choice正常结束 |
| 对手手牌、来源、重复费用、错误作品或未查看牌 | 原子拒绝，输入state hash及revision不变 |
| 另一待机先抽牌补出费用 | SQL原生动作链仍可付款，不在触发时提前删待机 |
| 费用不足 | 不查看、不付费、不记调试错误skip；旧快照维持原行为并可拒绝结束 |
| 牌库不足 | 费用先付，再刷新，原牌顶保留；筛选仅针对实际查看的牌 |
| 对手完整响应 | 查看期间不见卡牌身份；公开取得后对手得到指定公开卡 |
| 四种AI及新旧SQL Replay | 合法动作完成或取消，不修改决策输入，不依赖对手隐藏卡身份；最终Replay等于snapshot |

## 官方依据

重读本地综合规则ver.1.06，PDF SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
9.4.1–2：冒号前费用、只能用己方资源且不能部分支付；9.7.3.1.1/9.7.3.2：
可选付款与取消已选而不能发动的待机；5.7.1：指定玩家查看不等于双方公开；
10.2.2.2/10.2.3：查看数量不足时刷新，控室洗牌放在既有牌顶下方。
取得是否公开及可选零张来自各卡后文，不靠猜测FAQ。

## 测试证据与未解决边界

- 192项专项通过；实际来源卡费来自卡库，候补/控制能力为明确AUDIT fixture，不冒充整副合法牌组历史。
- 前端197项及TypeScript/build通过；每个ID分别验证无费用结束和公开零张交互。
- 图文156/156：117项真实状态转换、39登记契约；六条各有正常结算和无费用场景。
  `logs/continuous-work-unit-effects-20261026/effect-verification-report.zh-CN.md`。
  图文来源cost0用于隔离技能；实际cost4由专项另测。
- 固定AI10/10正式决胜，回合`3,6,5,6,9,4,9,5,7,6`，双方有成功Live且Replay一致。
  **本批六条实际触发0次**，不代替专项、不宣称策略强度提升。
  全步骤、策略和Live报告在`logs/continuous-work-unit-ai10-20261026/`。
- 完整control/registry/backend/web、manifest与pre-push需绑定本批最终源码指纹；以协调器结果为准。

余9条扫描不是9条已确认错误；下一批只逐卡审计5条Member/Liella简单文本。
3条Member/Live混合Heart筛选和1条最多取3张另审，不扩大现有最多取1张policy。
既有1项步骤review、4项Live解释待审和六条复杂重叠manual保留；脚本审计不是独立人工裁定。
