# Live得分与成功区移动：20项实现回归

## 2026-11-03 下一回合先攻的状态转换验证

从旧核心候选`test_next_first_player_rule`细化8.4.13，而不重新计算旧58项总数。
固定总则1.06第9页原文明确：仅一方在8.4.7实际移动牌到成功Live区时，该方成为先攻；
其他情况原先攻保持。不是按Live成功者、仅按胜者或按玩家ID固定选择。
全文及PDF哈希、26份SQL、负对照与最终工程门禁见
`logs/end-phase-planning-20261102/next-first-review/final-acceptance.md`。

- 新增12个状态转换案例：双方原先攻座次，各覆盖无人成功、仅先攻、仅后攻、同分、
  先攻高分、后攻高分。检查实际移动的牌ID、清理区域、turn_completed事件、唯一合法
  下一回合动作，随后真实提交并检查first/second/active、回合数、结果清零和区域不变。
- 2个选牌暂停案例：单方两张Live，完成成功Live选择前不能开始下一回合；选择后再推进。
  4个过期/重复命令契约检查SQL完整Replay不变；8个四AI双方角色契约实际提交，
  扰动对方隐藏卡面不改变决策且不修改输入。共26项，不把契约参数实例当新增核心规则。
- 所有SQL均显式绑定当前规则身份，确定性回放与身份验证为真。双方投影不泄露对手手牌
  或任一牌库隐藏ID；无新控件、权限或UI行为，不冒称浏览器人工对局。
- 新26加旧4项专项30通过；独立负对照把结果强制改回原先攻时，后攻单独移动的断言失败。
  初次失败来自测试构造未绑定规则身份及使用了错误的选牌动作；保留原日志，修正测试准备，
  没有放宽断言或修改应用来掩盖失败。
- 这是完成Heart判定后的无技能构造状态，不是完整对局或全部结束循环；不触及有歧义的
  8.4.7.1双方胜利且已有两张成功Live限制，不增加正式卡reviewed或75核心完成数。
  应用和registry未变，不重复固定池。上一轮固定池后续证据在`post-policy-frozen/`，
  其自然抽空验证取代下方历史“未重冻”的时点说明，但不改变上述限制。
- 父任务仍in_progress；本地检查与提交不代表上线，PR55保持历史发布。

## 2026-11-03 抽牌取空后的即时刷新

独立切片`draw-depletion-immediate-refresh`从旧核心刷新候选继续复核。固定PDF 1.06的
10.2.1规定刷新不等待检查时点，10.2.2.1指定牌库空且控室非空的条件，10.2.3规定将控室
非公开洗回牌库。修复前双方抽牌阶段抽走最后一张后，控室仍非空却refresh_count=0，
只有下一次取牌才刷新；两项原生Action红测试及旧状态/事件哈希已保留。

- 新建本地/联机对局写入`draw_refresh_policy=after_each_draw_v1`。逐张抽牌在牌进入手牌、
  完成正面状态更新后检查刷新；不是在尚未确定目标区域的通用取牌函数内抢先洗牌。
  旧快照缺省None且JSON省略该字段，继续原行为，不迁移既有对局或改变旧Replay。
- 复用既有确定性洗牌与刷新事件；事件中的`cards_drawn`仍是批量抽牌完成摘要，故刷新
  事件可先于该摘要。没有把事件数组顺序冒称每张牌的细粒度移动时间线。
- 新增38项测试：双方两项缺口回归、两组旧哈希、20个新旧策略SQL边界（末张、控室空、
  库与控室皆空、非末张、Live补抽跨库后取尽）、四AI双方8项实际动作及隐藏卡面扰动、
  4项非法策略值、2项本地/联机新建入口。与既有终局测试合计74项专项通过。
- 双视角检查公开控室正常可见；洗回后包括自己牌库在内的隐藏ID不出现在卡面map、
  事件或legal引用中。过去公开不是永久可见授权。输入不变，SQL Replay与实际状态一致。
- 无新UI控件，沿用牌库/控室计数与刷新事件投影；未进行完整浏览器人工对局。
  测试为构造边界和新建API入口，非自然整局或策略强度比较，不增加reviewed或75核心数。
- 只修复抽牌路径，不宣称磨牌、Yell、公开、检索、多玩家同时满足刷新或完整结束循环
  已全部正确；不改变registry或借此提升任何正式卡。未重新冻结30套牌，不宣称旧冻结
  报告是本次新应用源码的全量行为验收。
- 固定原文、双方新旧SQL与完整门禁/pre-push/审查证据见
  `logs/end-phase-planning-20261102/draw-depletion-review/final-acceptance.md`。
  仅本地提交；PR55是历史发布，后续推送、合并和上线不复用旧许可。

## 2026-11-03 Live设置路径的核心候选复核

从旧核心矩阵的`test_live_set_draws_exactly_the_number_of_set_cards`继续细化，而非重复盘点。
固定总则1.06第7页8.2.2/8.2.4分别要求先、后攻从自身手牌选择至多3张，背面放入Live区，
随后抽取相同数量；原文为「自身の手札のカード」，并非只允许Live卡。零张也受1.3.5.1支持。
PDF及逐字来源、当前测试哈希见`logs/end-phase-planning-20261102/live-set-review/source.json`。

- 新增8个原生状态路径（双方各0/1/2/3张）：从样例牌组新对局经正常准备、空Main进入设置，
  非零选择包含Member，断言具体移区ID、背面状态、牌库顶补抽顺序、完整手牌、对手区域不变、
  下一阶段与当前玩家。保留SQL并验证确定性Replay，而非仅检查手牌张数。
- 另8个非法选择契约：4张、重复、自身牌库、对手手牌均拒绝；完整Replay和当前状态不变。
  另8个AI契约：四种既有policy、双方各一次，实际提交选择并SQL回放；改变对手未公开卡面
  不改变决策，决策不修改输入。它们不是8场完整对局或策略改善证据。
- 状态路径同时检查双视角响应，确保对方手牌、未公开Live及牌库ID不会出现在卡面map、
  事件或legal引用中。未新增UI控件或改变生产权限，没有重新跑浏览器人工对局。
- 旧1项加新增24项专项通过；首轮25项因临时目录父路径缺失在setup阶段报错，未执行行为，
  留存`junit.xml`，正确目录下独立重跑留存`junit-retry.xml`，不是产品失败或删减测试。
- 此切片仅增加测试与证据，不修改应用/registry。无技能Stage、牌库充足、首回合的有限路径
  不覆盖8.2.1/3/5完整检查时点、补抽刷新、触发能力或完整结束循环。不能将24个参数实例
  全计入75核心场景，也不重复计入既有20个Live胜负判定项；父任务保持in_progress。
- 完整同源码control/registry/backend/web、审查与pre-push结果以
  `logs/end-phase-planning-20261102/live-set-review/final-acceptance.md`为准。
  仅本地提交，PR55为已合并历史发布，未再推送或部署。

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
