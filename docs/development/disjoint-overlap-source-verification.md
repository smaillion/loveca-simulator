# 效果登场：旧 Member 的无关时点分类

## 结论

本批修正受控 `deploy_selected_to_stage` 底座的过度限制，**不新增正式卡牌支持**。
原本覆盖一张仅有自身登场、手动起动或Live时点能力的旧Member，也会被当作复杂入场观察者拒绝。
新增显式 `overlap_observer_policy=ignore_disjoint_source_triggers`，仅在整段原文完整绑定时识别这类互不相关时点。

旧operation不自动补字段，行为与hash不变。完整临时重叠、继承、常时、未知/复合trigger继续保留限制。
四条虹咲及两张PR登场技能仍manual，登记 **900/1212（74.26%），312 manual**；不提升reviewed。
仍为同一continuous分支与Draft PR #54，不合并、不部署、不改旧dirty工作树。

## 官方依据

只读本地综合规则ver.1.06，PDF SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。

| 条款 | 实现判断 |
|---|---|
| 9.7.2 | 只有诱发条件满足的能力才待机，不为无关事件虚构触发或费用 |
| 10.1.2 / 10.4.1 | 重叠属于检查时点规则处理；本策略不等同完整调度器 |
| 11.4.2 | 自身登场指这张卡从场外进入；另一Member进入不使旧卡自身登场 |
| 11.5.2 / 11.6.2 | Live开始/成功有各自事件，不能由Main中的效果登场代替 |

代码只对旧顶部Member区分声明正确的四类trigger；未使用模糊日文匹配，也不解析未确认FAQ。
原文与按effect_index排序的全部label仅忽略空白后须完全相同；缺失段落、binding errors、
未知effect ID和未登记原文均返回 `outgoing_source_text_requires_overlap_timing_review`。
纯白板Member无原文无需登记。附属卡技能不能借此被忽略。

## 真实旧卡与受控部署

以下六张卡从本地卡库加载完整CardDefinition和当前registry，断言revision/hash一致，
作为**被覆盖的旧Member**。让它们离场的登场技能是明确标记的AUDIT fixture，
不是这些卡的实际能力，也不是四张虹咲登场能力已自动化的证据。

| 旧Member | 原能力时点 | revision | 本次结果 |
|---|---|---:|---|
| `PL!N-pb1-013` | 自身登场，原技能仍manual | 320 | 被另一Member覆盖时不再重复触发 |
| `PL!N-pb1-015` | 自身登场，原技能仍manual | 322 | 同上，不支付原技能费用 |
| `PL!N-pb1-017` | 自身登场，原技能仍manual | 324 | 同上 |
| `PL!N-pb1-023` | 自身登场，原技能仍manual | 330 | 同上 |
| `PL!HS-bp6-014` | 从手牌起动 | 51 | Stage离场不等于玩家从手牌发动 |
| `PL!-PR-020` | Live开始 | 1207 | Main阶段覆盖不产生Live开始事件 |

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBnj/PL!N-pb1-013-P2.png" width="110" alt="真实旧Member卡面，不是新增自动化技能">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBnj/PL!N-pb1-015-P2.png" width="110" alt="真实旧Member卡面">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBnj/PL!N-pb1-017-P2.png" width="110" alt="真实旧Member卡面">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBnj/PL!N-pb1-023-P2.png" width="110" alt="真实旧Member卡面">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP06/PL!HS-bp6-014-R.png" width="110" alt="仅手牌起动能力的姫芽">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PR/PL!-PR-020-PR.png" width="110" alt="Live开始能力的真实旧Member">

图片为卡库已有官方链接，没有抓取或打包图片。

## 状态断言

`tests/test_disjoint_overlap_source.py` 共50项，另与已有occupied部署测试组合89项通过。

- 旧Member原本被排除的区域仅在显式新策略下开放；旧operation仍拒绝，不修改其snapshot。
- 新Member以Active进入，旧顶部及附属Member去控室，附属Energy回Energy Deck。
- 正确支付AUDIT的2Energy；旧卡无关能力即便声明99Energy费用也不支付、不入队。
- 仅新Member登场和真正的己方登场观察者各抽1，没有旧卡额外抽牌或manual invocation。
- 常时、真正的入场/条件式离场观察者、混合trigger、未知时点仍被拒绝。
- 绑定失败/缺失后续原文、附属能力、入场条件及其他Member的条件式观察者仍被拒绝。
- 所有拒绝均在支付前完成，原状态hash不变；新策略不得用于其他operation或费用。
- 六张真实旧卡分别完成SQL Replay，最终状态、events、hash一致。
- 四种AI policy仅提交LegalAction中的合法区域；更改对手隐藏手牌身份不改变选择。
- 双方payload继续隐藏对手手牌，不把区域可用性变成私有信息泄露。

没有新增UI控件或HTTP接口，继续使用既有card/slot选择；全量前端回归另由协调器执行。
上述是程序化状态证据，不是独立模型逐步裁判或完整人工规则审核。

## 固定对战回归

20套牌池，各10场Human-vs-AI driver与AI-vs-AI，显式v1.2，600 action cap：

| 模式 | 正式完赛 | 最长回合 | 双方成功Live且10回合内 | blocker / skip / Replay错误 |
|---|---:|---:|---:|---|
| Human-vs-AI（人类侧为heuristic脚本） | 10/10 | 9 | 9/10 | 0 / 0 / 0 |
| AI-vs-AI | 10/10 | 9 | 10/10 | 0 / 0 / 0 |

Human侧seed12005以0:3成功Live结束，不能将全部20局称为双方都有成功Live，也不是实测真人操作。
随机池未绑定新AUDIT策略，因此这里只证明既有流程回归；新策略正确性由上面的50项定向测试验证。
产品默认仍v1.1，未用本批小样本切换默认策略或宣称最优策略。

原始结果：`logs/continuous-disjoint-overlap-ai20-20261026/`，保持ignored。
后续仍需完整重叠/继承时点和六条技能的逐卡状态、Replay、UI验收，不虚增覆盖率。
