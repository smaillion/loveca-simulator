# 同文顶3私下取1：15条费用快照逐卡审计

## 本批结果

修正15条已登记技能在手牌不足时缺少明确结束路径的问题，采用已有`triggered_inspection`费用策略。
**登记仍915/1212（75.50%），297manual**；不提升人工reviewed，不改engine、Card/SQLite schema、牌组或对战API。
只处理这些卡的第一段登场能力，不能理解为整张卡其他技能均已验证。同一分支与Draft PR54，不合并部署。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PLSD01/PL!-sd1-016-SD.png" width="125" alt="東條希">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PR/PL!HS-PR-001-PR.png" width="125" alt="日野下花帆">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/CLHS01/PL!HS-cl1-007-CL.png" width="125" alt="セラス">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PR/PL!N-PR-013-PR.png" width="125" alt="ミア・テイラー">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/NSD01/PL!N-sd1-003-SD.png" width="125" alt="桜坂しずく">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PR/PL!S-PR-019-PR.png" width="125" alt="国木田花丸">

| effect ID（均为:1） | 官方名 | revision | 实际登场cost |
|---|---|---:|---:|
| PL!-sd1-016 | 東條 希 |521|4|
| PL!HS-PR-001 | 日野下花帆 |778|10|
| PL!HS-PR-002 | 村野さやか |779|10|
| PL!HS-PR-005 | 大沢瑠璃乃 |780|10|
| PL!HS-cl1-007 | セラス 柳田 リリエンフェルト |88|7|
| PL!HS-pb1-011 | 大沢瑠璃乃 |127|7|
| PL!N-PR-004 | 中須かすみ |745|4|
| PL!N-PR-006 | 朝香果林 |747|4|
| PL!N-PR-013 | ミア・テイラー |752|4|
| PL!N-bp1-007 | 優木せつ菜 |631|4|
| PL!N-bp1-010 | 三船栞子 |634|4|
| PL!N-sd1-002 | 中須かすみ |681|9|
| PL!N-sd1-003 | 桜坂しずく |682|9|
| PL!S-PR-013 | 高海千歌 |726|11|
| PL!S-PR-019 | 国木田花丸 |728|11|

全部原文第一段均为：
> 【登場】手札を1枚控え室に置いてもよい：自分のデッキの上からカードを3枚見る。その中から1枚を手札に加え、残りを控え室に置く。

完整原文hash有三组，不用相同第一段覆盖不同整卡：基础`92d61785…`、蓮ノ空PR`3664d844…`、Aqours PR`1b85acb0…`。
完整SHA-256逐卡固定在专项测试；后两组还含不同Live开始段，此次不混入、不改写。
付款可选，取得不是可选；无作品、类型筛选，也没有公开指示。最少取得数量与公开标记现在独立配置。

## 复现与实际状态

15条红测先确认无手牌时缺少不可支付原因；旧空确认会原子拒绝，仍可用拒绝技能路径继续。
新快照明确允许不查看并取消该待机，旧快照保持原先路径，不伪造历史行为已被纠正。

| 场景 | 实际核对 |
|---|---|
| 正常原生登场 | 支付各自4/7/9/10/11费用，不只测试cost0来源 |
| 弃Member或Live支付，再选不同作品的Member或Live | 都允许；恰好查看原牌顶3张，不误加作品/类型限制 |
| 可选不付费 | 手牌、牌库不变，不开始私有检查 |
| 付款后选0张、重复、对手或未检查的卡 | 原子拒绝，revision与状态hash不变 |
| 第二步取得1张 | 手中取得1，其余2张进控室；费用不重付，未查看的尾牌不动 |
| 另一待机先补出手牌 | 原生SQL动作链允许之后支付，不在触发时提前删除技能 |
| 查看中及私下取得后 | 对手完整响应不含所查看/取得的私有ID或卡面，明示公开事件不被伪造 |
| 不足3张、甚至只有刚弃的费用卡能刷新 | 先付费再刷新，保留既有顶牌顺序，按实际能看的数量处理并取1 |
| 新旧SQL Replay | 成功付款及无费用路径均一致；旧JSON不补policy字段 |
| 四种AI | 原生LegalAction完成或正常拒绝/取消，无错误skip，改变对手隐藏手牌不改变决策 |

## 规则与证据

本轮重读本地综合规则ver.1.06，PDF SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
9.4.1–2规定费用与不可部分支付；9.7.3.1.1/9.7.3.2区分可选付款和待机取消；
5.7.1规定查看，10.2.2.2–3核对不足牌库时的刷新。
9.6.3.1.4对“依卡牌信息筛选的非公开选择”的例外，不等于本技能付款后可以任选0张。

- **435项专项**通过；与上一批六条合计612项通过。来源来自实际卡库，候补与控制能力为明确AUDIT fixture。
- 前端**173项**、TypeScript与production build通过；15个ID各有费用不足结束及私下必选交互回归。
- 图文**132/132**：93真实状态、39登记契约；本批每卡正常付款和无费用各1场景，报告包含全部15张卡图。
  `logs/continuous-private3-effects-20261026/effect-verification-report.zh-CN.md`。
  图文cost0来源只隔离技能，真实费用另有专项，不冒充真实完整对战。
- 固定AI **10/10**在3–9回合正式决胜，双方有成功Live、Replay一致；**本批15条未触发**，不替代专项。
  全步骤、策略、Live审计在`logs/continuous-private3-ai10-20261026/`。
- Registry严格审计0错误/0警告；完整门禁与推送预检由协调器保存当前源码指纹。

剩余21条单弃牌扫描候选仍须核准，下一项仅六条Member/Live顶5与私下顶2兄弟文本。
混合费用、Energy、多张取得及条件技能不一键套用；保留既有1项步骤review、4项Live解释待审和六条复杂重叠manual。
脚本审计不等于人工裁定，原44/6项dirty工作树及ignored报告不动。
