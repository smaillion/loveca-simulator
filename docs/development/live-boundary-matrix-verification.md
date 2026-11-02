# Live得分与成功区移动：20项实现回归

## 2026-11-02 胜利检查先于期限清理

独立切片`terminal-victory-before-expiry`依据固定PDF的1.2.1、8.4.8-11、9.5.1.1、
10.1.2及10.3.1，修正成功区阈值胜利后仍先清除Live期限补正的顺序。
8.4.8区域清理仍先执行；在8.4.9检查时点达成胜利后立即结束，不再执行8.4.11期限清理。
实际离区引起的原对象补正失效不属于期限清理，本切片不改变它。

- 新建本地/联机对局由服务器写入`victory_check_policy=before_end_expiry_v1`。
  旧快照缺省None并省略JSON字段，保留原状态、事件顺序和Replay；不迁移已存在对局。
- 只影响终局的期限清理。非终局行为、成功Live选择暂停、胜负条件、同分移动限制和
  下回合先攻规则不改；完整8.4.9-12重复检查尚未实现，核心矩阵父任务仍未完成。
- 新增36项回归：双方新旧模式、终局/非终局及多Live选择的16份SQL，
  构造双方已经达到阈值的2份平局SQL，修复前捕获的2组旧状态/事件哈希，
  非终局等价、四AI双方终局无动作及隐藏身份不变、非法policy和两种新对局入口。
  平局输入是检查时点构造，不证明自然同分Live可达，也不解决8.4.7.1旧歧义。
- 先有两项原生Action红测试证明Live期限提前清除；修复后本文件专项与既有Live审计
  合计64项通过。期限标记为构造补正，不绑定正式卡，不提升registry或reviewed。
- 终局不再产生期限失效事件，没有新增UI控件；原有终局页面及空legal action契约沿用。
  四AI检查仅验证终局不继续决策，不冒称完整对局、策略提升或随机正条件覆盖。
- 全部control/registry/backend/web及pre-push完成记录见
  `logs/terminal-victory-20261102/final-acceptance.md`；只有该记录确认后才视作本切片验收。
  不把历史全量或早期专项代替最终门禁，不推送、重复合并或部署PR55。

来源全文及页图保存在`logs/end-phase-planning-20261102/victory-rule-source.json`和
`victory-rules-page*.png`，PDF哈希仍为本页下文固定值。这里只采用固定通则，未声称查询最新FAQ。

## 2026-11-02 审计说明与判定一致性修复

`live_success_before_score_comparison` 的 verdict 与 evidence 使用先后手顺序，
但中文说明曾比较处理中间列表。当同一 Action 的 Heart 判定事件补入先攻玩家时，
中间列表可能先有后攻、后有先攻，导致 pass 显示失败说明；反序输入则 fail 显示成功说明。
本批用构造的状态和事件复现这两种矛盾，统一使用既有顺序比较结果，不改变判定标准。

- 新增8项工程回归：交换先攻身份，验证正序、逆序、缺失和重复名单；断言说明、
  verdict、evidence、JSON序列化一致，且不修改输入状态和事件。
- 红测试为4失败/4通过，修复后与已有Live审计组合48项通过。
- 构造事件用于审计函数的防御性检查，不声明该组合来自真实引擎对局；不增加20项Live
  行为矩阵或75项核心行为的完成数，不是新卡规则或官方裁定证据。
- 引擎、SQL/Replay、registry、AI决策和前端不变，不重新冻结30套牌或宣称策略改善。
  完整门禁使用control/registry/backend；未重跑web，最终同源码结果另存
  `logs/live-success-audit-summary-20261102/final-acceptance.md`。
- 仅本地提交。PR55已合并，其发布许可不复用，后续发布仍需批准。

## 本轮结论

在同一 `codex/continuous-development` / Draft PR #54 选择性迁移旧Live矩阵，
从9项扩展到20项。**实现回归通过不等于官方规则认证**：

- 20项都从已判定Heart需求的场面开始，经LegalAction生成的 `advance_phase` 执行。
- 每项检查17个完整预期字段：成功、Performance胜者、移动资格、禁止移动、实际移动、
  下回合先攻、分数、最终胜负、阶段、pending、临时补正、成功区与控室实际卡牌等。
- 每项创建独立SQLite对局，执行Action、验证原状态不变和revision+1，再重新执行Replay比对最终状态。
- 每方预置1张公开应援卡，确认Live/公开区清空，未移动的Live和应援卡确实进入控室。
- 4项为合成成功时技能（加2分或阻止同分移动），仅验证operation与结算时序，不增加真实卡牌支持。
- 4项Match Point同分带有规则解释待复核标记，其中1项也属于合成技能；两个分类不可相加冒充额外场景。

引擎、API、MatchState、Card Schema、SQLite schema和旧Replay均不改。
Registry仍为 **900/1212（74.26%）可执行，312条manual**，不提升reviewed状态。

## 固定来源与待复核

唯一规则基线为本地 `raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`，SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
测试校验文件实际hash；每项结果保存hash与规则引用。

PDF原图8.4.7.1写作ライブ置き場；当前Match Point实现按**成功Live区已有2张**处理。
本轮确认了这个文字差异，但没有官方勘误/人工审核证据消除疑点。
四项回归明确标记待审，不擅自变更既有行为，也不宣称已取得裁定依据。
8.4.4-5成功事件、8.4.6得分胜者、8.4.7移动及1.2.1胜负是不同层次，报告继续分别输出。

## 场景清单

| 场景 | 检查重点 | 额外边界 |
| --- | --- | --- |
| neither_successful | 双方没有成功Live，不移动 | |
| only_one_successful | 仅先攻0分Live成功仍获胜 | |
| higher_score | 先攻3对2高分移动 | |
| equal_score_no_match_point | 普通同分双方移动 | |
| equal_score_one_match_point | 先攻单边Match Point同分 | 区域措辞待审 |
| equal_score_both_match_point | 双方Match Point同分继续 | 区域措辞待审 |
| higher_score_at_match_point | 双方Match Point但高分方到3张 | |
| live_success_score_before_comparison | 成功时加分先于比较 | 合成技能 |
| only_second_successful | 仅后攻成功，下回合先攻变化 | |
| second_player_higher_score | 后攻高分移动 | |
| equal_zero_score | 双方0分不同于双方无Live | |
| equal_score_second_at_match_point | 后攻单边Match Point同分 | 区域措辞待审 |
| first_reaches_three_against_non_match_point | 成功区2对1时先攻高分获胜 | |
| second_reaches_three_against_non_match_point | 成功区1对2时后攻高分获胜 | |
| match_point_player_loses | 先攻已有2张但低分，不提前获胜 | |
| second_match_point_player_loses | 后攻已有2张但低分，不提前获胜 | |
| match_point_without_successful_live | 已有2张但本轮无人成功 | |
| live_success_score_creates_equal_result | 成功时加分改为同分 | 合成技能 |
| score_bonus_equal_at_match_point | 加分追平后应用既有Match Point限制 | 合成技能、区域措辞待审 |
| card_effect_blocks_equal_placement | 成功时效果阻止双方移动 | 合成技能 |

## 复现与证据

```powershell
python -m pytest tests/test_live_judgment_audit.py tests/test_ai_rules_acceptance.py -q
python -m tools.ai_sandbox.live_judgment_audit --output logs/continuous-live-boundaries-20261026
```

专项共40项测试通过，包括20项SQLite Replay、中文/JSON报告、错误分数使矩阵失败、CLI失败返回非零。
忽略目录下输出 `live-boundaries.json` 与 `Live判定回归.zh-CN.md`，逐项列输入和期望/实际；
AI对战审计的Live报告也保留待审标记，不能只展示PASS掩盖证据边界。
这是固定状态回归，不是20场完整AI对战，不冒充新的策略或全卡实战验收。

另以现有 `simple_ai_v1_2` 跑固定20Deck池、seed12000起的10局整局审计：10/10正式完赛，
10/10在10回合内且双方各有成功Live；5454项逐步检查pass、1项既有语义词典review。
实际覆盖27个技能、109次技能决策/结算（108pass、1review），没有非法Action、技能错误skip或Replay错误。
新20项Live回归随对战报告执行，报告明确显示4项独立的区域措辞待复核，不与上述1项动态review混算。
输出为 `logs/continuous-live-matrix-ai10-20261026/比赛总报告.zh-CN.md` 和同目录Live判定审计。
这是接入验证，不是新旧AI强度比较，不更改默认policy或声称最优策略。

## 旧工作树审查与下一步

只读检查旧v0.9的原型，原44项dirty改动及ignored报告不改、不删除：

- `CORE_RULE_SCENARIOS` 实际58个描述，包含online13、action3、replay2等工程契约；
  不能用58+20得出75项核心规则行为已完成。
- 旧JUnit读取只检查failure/error，会把skipped testcase计为通过；迁移时须修正。
- 旧结束阶段原型先触发结束能力，再清理Live和公开区，与8.4.8先清理的顺序不符。
- 旧原型以来源整体排队并用卡ID去重，没有证明多技能同卡、重新入场对象、期限解除后重检正确。

后续先设计有旧snapshot边界的End Phase调度，按8.4.8-12覆盖清理、待机能力、费用/选择暂停、
期限解除与重新检查，再重分类并补足75项核心行为。此父任务仍未完成。
Heart分配、Yell生成、多Live选一、完整结束阶段循环及FAQ解释不在本轮20项的覆盖声明内。
