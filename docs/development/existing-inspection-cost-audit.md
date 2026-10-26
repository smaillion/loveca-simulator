# 既有登场检索费用逐卡审计

后续：六条相邻单弃牌检索已单独验收，见[相邻检索费用审计](adjacent-inspection-cost-audit.md)。
下面保留上一批基线数字；当前剩余36条扫描候选，没有宣称全部正确或全部违规。

## 结论

先用10项红测确认：6条顶2重排能错误重复支付自身Wait，唐可可已Wait时会报错而非取消待机，
3条虹咲弃牌检索在无费用时没有可提交的正常结束路径。已逐条修正，不增加可执行登记：
**915/1212（75.50%），297manual**。仅新建effect snapshot采用明确policy，旧快照不追改。
不改Card/SQLite schema、decklist或controllers API，不提升人工reviewed。

## 卡图与适用文本

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP03/PL!-bp3-N-014-N.png" width="120" alt="星空凛">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP03/PL!-bp3-N-017-N.png" width="120" alt="小泉花陽">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP03/PL!-bp3-N-018-N.png" width="120" alt="矢澤にこ">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP03/PL!N-bp3-N-022-N.png" width="120" alt="三船栞子">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP04/PL!N-bp4-016-N.png" width="120" alt="朝香果林">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP06/PL!S-bp6-018-N.png" width="120" alt="黒澤ルビィ">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP04/PL!SP-bp4-002-R.png" width="120" alt="唐可可">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/NSD02/PL!N-sd2-012-SD2.png" width="120" alt="鐘嵐珠">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/NSD02/PL!N-sd2-014-SD2.png" width="120" alt="中須かすみ">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP07/PL!N-bp7-018-N.png" width="120" alt="近江彼方">

| 技能 / revision | 费用与效果 |
|---|---|
| PL!-bp3-014:1 /455；017:1 /456；018:1 /457 | 自身Active→Wait；查看顶2，任选0–2张按顺序回牌顶，其余控室 |
| PL!N-bp3-022:1 /490；PL!N-bp4-016:1 /370；PL!S-bp6-018:1 /37 | 同一完整官方文本，逐卡验证，不只检查登记字段 |
| PL!SP-bp4-002:1 /377 唐可可 | 自身Active→Wait；顶4，任选0–1张必要Heart总数≥8的Liella! Live公开入手 |
| PL!N-sd2-012:1 /943；014:1 /945 | 可选弃手牌1；顶3，任选0–1张虹咲牌公开入手 |
| PL!N-bp7-018:1 /881 | 可选弃手牌1；顶5，任选0–1张无Blade Heart虹咲Member公开入手 |

6条重排的原文：
> 【登場】このメンバーをウェイトにしてもよい：自分のデッキの上からカードを2枚見る。その中から好きな枚数を好きな順番でデッキの上に置き、残りを控え室に置く。

完整技能含原始提醒句，candidate比较完整技能段；10条均保留原effect ID、revision/hash。
新策略不扩大为任意排序/费用DSL，无费用的PL!N-sd2-009不添加费用策略。

## 状态核对

| 输入 / 操作 | 实际与期望一致 |
|---|---|
| 原生登场后支付一次Wait，再保留0/1/2张 | 精确重排，剩余进控室；第二步不再付费 |
| 来源已Wait | 不查看、不付费、不记调试skip，明确取消此待机 |
| 来源离场后同ID返回 | SQL动作链验证新对象不承担旧费用；仍Active |
| 来源仅在Stage内部Position Change | SQL动作链验证同对象可付Wait，排序继续 |
| 虹咲手牌不足 | 正常结束待机，不虚造弃牌候选或卡死 |
| 先处理另一待机补手牌 | SQL动作链验证按此刻资源重新判断，可正常付费 |
| 唐可可目标Heart7/8或不同作品 | 分别排除/允许/排除；选中Live对手可见 |
| 重排未知、对手或重复卡 | 原子拒绝，revision与状态hash不变 |
| 牌库不足2张 | 先付费，再在剩余牌下刷新，再查看；原顶牌仍在前 |
| 对手完整响应 | 看不到私有保留牌ID和顺序；并非只测试card map |
| 历史无policy可执行快照 | 序列化不补新字段；固定已Wait初始局面仍重放历史路径，不伪装历史已被纠正 |

## 官方依据

本轮重新读取本地综合规则ver.1.06，SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
9.4.1–2规定冒号前费用、己方资源、不可支付时不能部分支付；9.7.3.1.1/9.7.3.2规定
可选费用及选定待机无法发动时取消。4.1.4区分离场新对象与Stage内部移动；
5.7.1、10.2.2.2–3核对查看数量、查看前刷新与剩余牌顺序。脚本不是独立裁判认证。

## 证据与限制

- 166项专项：真实卡库来源与正常登场费用；候补牌和控制待机为明确AUDIT fixture。
- 前端131项：新增0/1/2张保留和显式重排提交；费用不足可结束的既有面板回归保留。
- 图文90/90：51真实状态、39登记契约；新10场景覆盖逐卡正常/不可支付，成本0来源仅用于隔离效果。
  `logs/continuous-existing-inspection-effects-20261026/effect-verification-report.zh-CN.md`。
- 固定AI十局10/10：3–9回合正式胜负、双方成功Live、Replay一致。27个技能109次决策/结算；
  唐可可实际触发、支付、检查和完成各4次。其他9条没有随机触发，不以此替代专项测试。
  `logs/continuous-existing-inspection-ai10-20261026/比赛总报告.zh-CN.md`含全步骤，另有策略/Live审计报告。
- Registry严格审计0错误/0警告；完整门禁和pre-push按协调器源码指纹记录。

剩余42条单弃牌检索只是扫描候选，不是42条已确认错误；下一切片逐卡审计其中6条。
混合费用、Energy、条件/Live时点检索不套用本批策略。六条复杂重叠/继承仍manual，
固定比赛既有1项步骤review与4项Live解释待审不清零。旧44/6项dirty和ignored报告不动。
仅同一continuous分支与Draft PR54，不合并、不部署，等待维护者审核。
