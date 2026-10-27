# 顶5公开与顶2私下取得：六条费用路径审计

后续六条作品/组合筛选已另行验收，见[独立报告](work-unit-inspection-audit.md)；本文件保留该批历史数字。

## 本批结论

六条已有可执行技能逐卡接入`triggered_inspection`费用检查，修正手牌不足时没有明确结束路径的问题。
**登记仍915/1212（75.50%），297manual**；不提升人工reviewed，不改engine、Card/SQLite schema、牌组或对战API。
只更新同一continuous分支及Draft PR54，未合并、未部署。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PLSD01/PL!-sd1-015-SD.png" width="130" alt="西木野真姫">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP02/PL!HS-bp2-010-N.png" width="130" alt="日野下花帆">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP01/PL!HS-bp1-011-N.png" width="130" alt="村野さやか">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP06/PL!HS-bp6-022-N.png" width="130" alt="安養寺姫芽">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBnj/PL!N-pb1-028-N.png" width="130" alt="朝香果林">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBnj/PL!N-pb1-035-N.png" width="130" alt="ミア・テイラー">

| effect ID（均为:1） | 官方名 | revision / 实际登场cost | 支付手牌1张之后 |
|---|---|---|---|
| PL!-sd1-015 | 西木野 真姫 |520 /9|顶5，任选0–1张Member公开入手|
| PL!HS-bp2-010 | 日野下花帆 |583 /9|同上，独立卡库身份|
| PL!HS-bp1-011 | 村野さやか |663 /9|顶5，任选0–1张Live公开入手|
| PL!HS-bp6-022 | 安養寺 姫芽 |58 /9|同上，独立卡库身份|
| PL!N-pb1-028 | 朝香果林 |332 /4|顶2，必须私下取1张|
| PL!N-pb1-035 | ミア・テイラー |334 /4|同上，独立卡库身份|

完整技能段与三个原文SHA-256分别固定在专项测试：Member组`42df0bd4…`、Live组`60028b48…`、私下组`0798b475…`。
共同费用是「手札を1枚控え室に置いてもよい」；手中Member或Live都可支付，也可不付费而拒绝技能。
公开组后文明确允许不选；私下组后文是「その中から1枚を手札に加え」，不能把可选付款误认为付款后也可空选。
本批不增加作品或组合条件，不改同卡其他技能段。

## 复现与状态核对

先用六条红测确认无费用时缺少不可支付原因。旧空确认会原子报错，但仍可用拒绝技能路径继续；
新快照明确允许结束此待机，不查看、不付费、不记调试错误skip。旧快照的原行为保持，SQL重放不追溯改写。

| 输入/操作 | 实际核对 |
|---|---|
| 原生登场 | 支付真实9或4费用，费用卡可为自己手中的Member或Live |
| 顶5 Member / Live筛选 | 严格类型筛选，Member可来自不同作品并可带Blade Heart；不偷加作品条件 |
| 顶2取得 | 只看原牌顶2张，不误看3张；任选其中类型与作品，但必须取1 |
| 付款后公开零张 / 私下零张 | 前者正常结束，后者原子拒绝 |
| 对手手牌、已登场来源、重复或未检查的卡 | 原子拒绝，原状态hash和revision不变 |
| 另一待机先补出费用 | 原生SQL动作链中之后仍可支付，不在触发时删除待机 |
| 不足牌库，甚至只剩刚弃的费用可刷新 | 先付费、再刷新；保留既有顶牌，按实际可查看数量与候补处理 |
| 对手完整响应 | 私有查看不泄露；只有卡文指定公开的最终取得对手可见 |
| 四种AI与旧SQL Replay | 原生LegalAction正常完成或取消，无错误skip；旧JSON不补policy，新旧最终snapshot一致 |

## 官方依据与证据

本轮重读本地综合规则ver.1.06，PDF SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
9.4.1–2核对费用及不能部分支付，9.7.3.1.1/9.7.3.2核对可选付款与待机取消，
5.7.1、10.2.2.2–3核对查看张数与不足牌库刷新；9.6.3.1.4不能被泛化成任何私有选择都可选0张。

- **174项专项**通过，来源来自实际卡库，候补与控制能力为明确AUDIT fixture；不冒充整场合法历史。
- 前端**185项**、TypeScript、production build通过；六个ID各有费用不足结束，四个公开ID零张和两个私下ID必选交互验证。
- 图文**144/144**：105真实状态、39登记契约。本批六条各有正常结算及无费用场景，包含卡图和原文。
  `logs/continuous-inspection-siblings-effects-20261026/effect-verification-report.zh-CN.md`。
  图文cost0来源仅隔离技能，真实卡费由专项另测。
- 固定AI **10/10**在3–9回合正式决胜，双方有成功Live且Replay一致；**本批六条未触发**，不替代专项。
  全步骤、策略与Live报告位于`logs/continuous-inspection-siblings-ai10-20261026/`。
- Registry严格审计0错误/0警告；完整门禁、manifest与pre-push由协调器保存当前源码指纹。

剩余15条单弃牌扫描候选尚未逐卡核准，下一项仅六条作品/组合检索。
混合费用、Energy、条件与多张取得不自动套用；既有1项步骤review、4项Live解释待审和六条复杂重叠manual继续保留。
脚本审计不是独立人工裁定。旧44/6项dirty工作树及ignored报告不动。
