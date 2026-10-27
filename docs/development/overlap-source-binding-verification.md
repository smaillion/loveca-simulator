# 重叠登场：公开来源完整绑定验证

## 本批结论

增加显式 `overlap_observer_policy=require_complete_source_bindings`，补上既有受控
`deploy_selected_to_stage` 只核对旧顶部Member全文的缺口。**这不是新增六张正式卡支持**。
目前策略仅由AUDIT受控fixture采用；六条PR/虹咲登场仍manual，登记保持
**904/1212（74.59%），308 manual**，不提升reviewed。

仍为同一continuous分支与Draft PR #54；不合并部署、不改Card/SQLite schema，
不复制或修改旧44/6项dirty文件和ignored报告。

## 复现与官方依据

修改前的5项红测分别在入场卡、附属Member、其他己方Member、对手Stage、表向Live加入
未绑定的日文能力，保留空effect IDs。旧策略全部错误地开放右侧重叠登场。
这证明“没有effect IDs”不能等于“没有能力”，不是通过提高登记状态解决的问题。

本地综合规则ver.1.06，SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。

| 规则引用 | 本批采用的约束 |
|---|---|
| 9.3.4 / 9.3.4.2–3 | 按有效公开区域检查潜在能力；不能凭隐藏牌身份限制操作 |
| 9.7.2 | 只有确定诱发条件才能正确建立待机，不把未登记文本当作不会触发 |
| 10.1.2 / 10.4.1 | 重叠清理属于检查时点；本批安全门禁不能代替完整临时场面 |
| 9.6.3.1.4 | 私有筛选手牌仍可不选择，不把未知能力的限制改成强制公开/选择 |

以上是程序化证据和受限实现判断，不是独立人工裁判或新的官方FAQ结论。

## 可核对的场面

旧Member使用实际 `PL!N-pb1-013` 卡库定义；入场能力、入场卡与额外观察者为明确标记的
AUDIT fixture。不能将下面的抽2解释为这张真实卡自身的新自动化技能。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBnj/PL!N-pb1-013-P2.png" width="150" alt="作为旧来源的实际卡；登场能力为受控测试fixture">

| 操作/局面 | 期望与实际断言 |
|---|---|
| 全部来源正确绑定，右侧普通效果登场 | 支付2 Energy，新Member Active；旧Member/附属Member控室，Energy按既有规则返还；入场及己方观察者各抽1；待机结束 |
| 入场/附属/其他己方/对手/表向Live有未绑定文本 | 右侧拒绝，原revision、Energy、区域、待机与hash不变 |
| label相同但card code/revision/hash错误、缺段或重复index | 拒绝，不用正确label掩盖错误identity |
| 全文正确但属于附属、常时或未支持的跨玩家/Live观察者 | 明确保留unresolved，不把“已绑定”当作“已实现” |
| 所有区域都受未确认来源阻挡 | 不允许用空目标冒充结算并消耗费用；保留pending，提供原生手动入口，四种AI均报告暂停原因 |
| 修改对手手牌/牌库与对手背面Live文本 | LegalAction选项与当前玩家完整响应一致，不读取这些身份 |
| 私有筛选手牌主动不选目标 | 仍可按原生规则支付费用后结束，无伪造登场；不是强制人工阻断 |
| 没有符合筛选的公开目标 | 不虚构未知来源blocker；保持既有无目标语义 |
| 手动处理受阻的来源 | 校验精确invocation/effect/source，记录人工事件并结束pending；结构化安全状态不因此开放任意绕过 |

## 工程证据与回归

- `tests/test_overlap_source_binding.py`：**59项**定向状态/契约断言。
- SQL Replay覆盖新旧策略的成功登场、拒绝不变及明确手动交接，最终state/events/hash一致。
- 四种Simple AI只使用原生LegalAction；被阻断时返回
  `overlap_source_requires_manual_review`，不尝试无目标自动结算。
- 中日UI展示限制和手动入口，AI暂停原因可读；完整前端**110项**通过，TypeScript/build通过。
- 全量后端/协调器/Registry/manifest门禁由本批 `loop check` 保存真实命令和源码指纹；
  文档不代替门禁结果。

固定20 Deck池、10局v1.2回归：**10/10在10回合内正式完赛，双方都有成功Live**。
逐步审计5454 pass / 1 review，20项Live实现边界通过，另4项规则解释待审。
原始报告位于 `logs/continuous-overlap-binding-ai10-20261026/`，保留ignored。
这10局没有采用受控新策略，证明的是既有对战回归；本批安全语义由59项定向测试提供证据。
产品默认仍v1.1，不将本批小样本宣称为AI强度提高或完全符合官方规则。

## 保留边界

旧无策略与 `ignore_disjoint_source_triggers` snapshot不补写字段，保持历史行为和Replay。
新策略没有自动应用到正式卡或旧对局，也不改变普通手牌登场流程。
它只排除不能安全证明的重叠区域，不执行常时、继承、任意跨玩家观察者或所有特殊有效区域能力。
后续继续完整重叠/继承父任务，逐卡补操作与时点证据后再决定六条登记能否晋级。
