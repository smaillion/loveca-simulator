# 六条相邻弃牌检索：费用与公开边界

后续：15条同文顶3私下取1已逐卡单独验收，见[同文家族审计](private3-inspection-family-audit.md)。
下文保留本批历史基线；当前剩余21条单弃牌扫描候选未全部核准。

## 本批结果

六条已有可执行技能逐卡复现并接入已有`triggered_inspection`费用策略；
**登记仍915/1212（75.50%），297manual**。不提升人工reviewed，不修改engine、Card/SQLite schema或对战API。
只更新同一continuous分支及Draft PR54，未合并、未部署。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP03/PL!-bp3-N-010-N.png" width="135" alt="高坂穂乃果">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP05/PL!-bp5-014-N.png" width="135" alt="星空凛">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP06/PL!-bp6-004-R.png" width="135" alt="園田海未">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBLL/PL!-pb1-016-R.png" width="135" alt="東條希">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PLSD01/PL!-sd1-011-SD.png" width="135" alt="絢瀬絵里">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PLSD01/PL!-sd1-012-SD.png" width="135" alt="南ことり">

| 技能 / revision | 支付手牌1张之后 |
|---|---|
| PL!-bp3-010:1 高坂穂乃果 /452 | 看顶5，任选0–1张Live公开入手，其余控室 |
| PL!-bp5-014:1 星空凛 /161 | 看顶4，任选0–1张有heart05或heart06的Member公开入手 |
| PL!-bp6-004:1 園田海未 /6 | 看顶5，任选0–1张μ's Member公开入手 |
| PL!-pb1-016:1 東條希 /431 | 看顶4，任选0–1张lily white卡公开入手，Member与Live均可 |
| PL!-sd1-011:1 絢瀬絵里 /518 | 看顶3，必须私下取1张，其余控室 |
| PL!-sd1-012:1 南ことり /519 | 同一技能段，独立卡库身份与真实费用验证 |

共同费用原文是「手札を1枚控え室に置いてもよい」：可以不支付并不使用技能，
不要求弃牌必须是Member或Live。两条SD卡的后文是「その中から1枚を手札に加え」，
**没有“してもよい”或“公開”**：付款后必须选一张，且不向对手公开。
四条公开检索则明确允许最终选0张；不能混为同一种可选行为。

## 先复现，再修正

六条红测均先确认无手牌费用时未提供不可支付原因。旧快照的空确认会被引擎原子拒绝；
仍可选择拒绝这条可选技能，并非整局无法继续。新快照有明确“结束此能力”路径，
不再要求选择不存在的费用卡，不查看、不支付、不记录调试错误skip。

| 场景 | 核对结果 |
|---|---|
| 正常原生登场、选择自己手中Member或Live支付 | 都合法；准确看3/4/5张，费用只付一次 |
| 空费用、重复费用、对手手牌、已登场来源 | 原子拒绝，原状态与revision不变 |
| 另一待机先补一张手牌 | SQL动作链中之后可以付费；不在触发时丢掉待机 |
| 四条公开检索最终选0张 | 正常结束，其余检查牌进控室 |
| 两条SD付款后选0张 | 原子拒绝；选择一张后正常结束 |
| Member只有Blade Heart、Live只有必要Heart | 不能作为星空凛的Member Heart条件；候补与独立预期集合比较 |
| 不同作品或组合 | μ's与lily white分别筛选；lily white不错误限制为Member |
| 手牌取得前后双方完整响应 | 查看时只有本人可见；仅四条有公开字样的最终取得向对手公开 |
| 牌库不足、甚至只有刚弃掉的费用可刷新 | 先支付，再在剩余牌下刷新；按实际可查看数量处理，不重付费用 |
| 旧SQL快照 | 不补新policy；成功检索及旧无费用拒绝路径均Replay一致 |

177项专项用真实卡库来源与实际登场费用，候补与控制能力是明确AUDIT fixture。
六条保持各自effect ID、完整日文段、revision与SHA-256；新匹配入口只允许这批身份，
追加未知句子或换成未审卡号不能获得这项新费用策略。不声称旧的通用前缀解析已全面审查。

## 规则与证据

本轮重读本地综合规则ver.1.06，PDF SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
9.4.1–2区分费用、己方资源及无法支付；9.7.3.1.1/9.7.3.2说明可选付款与无法发动的待机取消；
5.7.1区分查看与公开；9.6.3.1.4不能被曲解成“任何私有选择都可不选”，两条SD没有筛选条件；
10.2.2.2–3核对查看前不足牌库的刷新。卡牌指定数量与公开方式以官方日文卡文为准。

- 177项专项通过；四种AI都只提交原生LegalAction，改变对手隐藏手牌不改变决策。
- 前端143项、TypeScript和production build通过；六条费用不足可结束、四条公开零张、两条私下必选分别测试。
- 图文**102/102**：63真实状态、39登记契约。本批新增6条正常处理及6条无费用场景，附官方卡图和原文。
  `logs/continuous-adjacent-inspection-effects-20261026/effect-verification-report.zh-CN.md`。
  图文用cost0来源隔离技能，不冒充真实卡费；真实费用另由专项验证。
- 固定AI **10/10** 在3–9回合正式决胜、双方有成功Live、Replay一致。**本批六条没有触发**，不以该结果替代专项。
  全步骤、策略和Live报告在`logs/continuous-adjacent-inspection-ai10-20261026/`。
- Registry严格审计0错误/0警告；完整工程门禁和推送预检由协调器记录当前源码指纹。

剩余36条单弃牌扫描候选未逐卡确认，不等于36条已证实错误；其中15条同文“顶3私下取1”排为下一项。
混合费用、Energy、额外操作和条件技能不自动套用。保留1项既有步骤review、4项Live解释待审、
六条复杂重叠/继承manual；脚本报告不是独立人工裁判认证。旧44/6项dirty及ignored报告不动。
