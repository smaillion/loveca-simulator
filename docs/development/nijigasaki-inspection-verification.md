# 虹咲登场检索：费用、私有查看与公开结果

## 本批结果

精确新增4段`test_validated_executable / test_validated`，不提升人工reviewed。
登记由908增加至**912/1212（75.25%）**，manual304→300。
同一continuous分支、Draft PR #54，不合并部署；不改Card/SQLite schema、牌组格式或controllers API。
六条复杂重叠/继承技能仍manual，旧44/6项dirty工作树和ignored报告原样保留。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/NSD02/PL!N-sd2-009-SD2.png" width="150" alt="天王寺璃奈">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/NSD02/PL!N-sd2-012-SD2.png" width="150" alt="鐘 嵐珠">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/NSD02/PL!N-sd2-014-SD2.png" width="150" alt="中須かすみ">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP07/PL!N-bp7-018-N.png" width="150" alt="近江彼方">

| 技能 | 原文概要 / revision |
|---|---|
| `PL!N-sd2-009:1` 天王寺璃奈 | 登场查看顶3，任选1张虹咲卡公开加入手牌，其余控室 / 940 |
| `PL!N-sd2-012:1` 鐘 嵐珠 | 可选弃1张手牌作费用，之后同上 / 943 |
| `PL!N-sd2-014:1` 中須かすみ | 同文但独立身份，不自动继承人工review / 945 |
| `PL!N-bp7-018:1` 近江彼方 | 可选弃1张，查看顶5，任选1张无Blade Heart的虹咲Member公开加入手牌，其余控室 / 881 |

专项测试固定每条全文SHA-256；候选使用完整技能段相等判断，追加一句未知效果后不再匹配。
原文及各检查结果见自动生成的中日图文报告，不以同名或近似文本登记。

## 复现与修正

四项红测通过真实卡库定义和普通`play_member`登场，确认原来均停在manual。
新增检索候选后进一步复现：`exclude_blade_heart`在普通区域选择生效，
但查看牌的独立候选路径未应用，会错误允许特殊应援图标Member。
本批补齐该字段，六种色Blade Heart及draw/score/ALL/unknown图标均排除。
现有其他官方inspection entry没有将该字段设true；不改旧manual或其他选择语义。

## 规则依据与状态断言

固定本地综合规则ver.1.06，SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。

| 条款 / 卡文 | 实际断言 |
|---|---|
| 11.4.2 | 从手牌正常登场才建立对应待机，按真实登场费用支付Energy |
| 9.4.2 / 9.7.3.1.1 | 可拒绝弃牌费用；非法、重复、对手或已不在手牌的费用原子拒绝，不开始查看 |
| 5.7.1 / “加えてもよい” | 查看指定顶3或5，可选择0或1，不强制回收合格卡 |
| 官方作品/Member/Blade Heart条件 | 错作品、Live或带任何Blade Heart的Member按各卡条件排除 |
| 10.2.2.2 / 10.2.3 | 短牌库先在剩余牌下刷新；弃牌费用在查看/刷新前支付，原顶牌顺序保持 |
| 私有查看 / “公開して” | 对手看不到候选卡身份；选定1张的公开事件包含卡号与卡图，双视角实际核对 |
| 9.6.3.1.4及可选卡文 | 无候补或主动选0后正常结束，不伪造目标、不残留pending |

`tests/test_nijigasaki_inspection.py`共102项，包含四种AI策略的原生费用/选择、
不读取对手隐藏身份、拒绝不变、SQL Replay和旧manual快照。
State fixture使用真实来源卡定义和费用；费用卡/顶牌为明确AUDIT受控卡，不代表其余技能已验证。

## 可读报告与回归

- 图文报告**76/76**：37项真实状态转换、39项Registry契约；新增4项逐卡实际操作。
  `logs/continuous-nijigasaki-inspection-effects-20261026/effect-verification-report.zh-CN.md`。
- 图文场景隔离技能、将受控来源登场cost设0，只验证检索行为；真实卡费由102项测试另行覆盖。
- 前端**124项**及TypeScript/build通过，验证合法候补存在时仍可提交0张，未重构UI。
- 固定10局v1.2全部3–9回合正式完赛，双方至少各一次成功Live，Replay一致。
  逐步5454pass/1既有review，Live20/20通过；4项Live条款解释仍待审。
  本批四卡没有在随机池触发，不能用这10局替代定向证据。
  原始比赛报告保留于`logs/continuous-nijigasaki-inspection-ai10-20261026/`。
- 全量backend/control/registry/web、manifest与pre-push结果由协调器保存源码指纹和日志。

产品默认仍v1.1；本批不声称AI强度提高或独立裁判认证。
下一批可分别复核强制弃牌检索及指定Live卡费用，不能直接复制本批标签。
