# 宮下 愛：弃两张手牌，选择颜色获得两颗Heart

## 本批结论

精确适配 `PL!N-sd2-005:1`，text revision936，全文SHA-256：
`64e8c7cad33cf244869c007c1bc7d2ff52ebfd039062a34ee1d793c7f25ee66d`。
从`manual_resolution`晋级为`test_validated_executable / test_validated`，不提升reviewed。
当前**906/1212（74.75%），306 manual**。不改Card、runtime SQLite、deck格式或controllers API。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/NSD02/PL!N-sd2-005-SD2.png" width="210" alt="宮下 愛 官方卡面，受控局面验证而非人工裁定">

> 【ライブ開始時】手札を2枚控え室に置いてもよい：好きなハートの色を1つ指定する。ライブ終了時まで、そのハートを2つ得る。

只匹配这段完整日文，不扩展模糊文本。使用既有`discard_from_hand`、`choose_color`、`gain_heart`，
增加受限`original_live_start_heart_source`快照保护：无条件、可选Live开始、恰好弃两张手牌、
自身获得指定颜色两颗Heart、Live期限。原来源身份沿用既有离场跟踪，不新增通用继承DSL。

## 官方依据与复现

本地综合规则ver.1.06，SHA-256
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
依据9.4的费用规则、9.5.3结算、9.6.3选择、9.7.2/11.5.2待机与Live开始，
以及4.1.4/9.9.2的离场对象规则和8.4.11期限清理。没有重新抓取官网或使用推测FAQ。

第一项红测从实际卡库定义开始Live，确认旧登记只能manual。
进一步复核发现已有费用卡＋颜色技能只给UI费用卡选项，后端却要求颜色，导致界面无法正确提交。
这不是引入新的响应时点：用户先选费用卡和颜色，再一次确认；服务器原子验证后先付费再应用效果。
颜色错误时不弃牌；取消可选能力也不付费。

## 人类可核对的结果

来源Member使用实际卡库定义；其他手牌、Live和控制能力为明确AUDIT fixture。

| 场景 / 操作 | 期望与真实断言 |
|---|---|
| 宮下 愛在己方Stage，手牌3张，真正开始Live | 原生pending出现，提供3张费用候补与六色，不是Main起动 |
| 选手牌A/B与紫色，确认 | A/B进入控室，剩余手牌1；原来源获得紫Heart+2，期限Live；进入应援 |
| 改选其他五色 | 每次只产生所选颜色+2，不增加任意色或另外五色 |
| 拒绝可选能力 | 手牌3张不变，不产生modifier，正常结束 |
| 手牌不足两张 | 明确记录不可支付原因，不产生卡死prompt |
| 只选一张、重复/三张/对手/牌库/Stage卡、错误或缺少颜色 | 原子拒绝，revision/hash/手牌/pending不变 |
| 再提交已结束的invocation | 拒绝，不重复付费或重复加成 |
| 先结算另一受控能力，使来源离场 | 本能力仍可支付费用和指定颜色，但不向控室卡加Heart，明确显示原因 |
| 来源离场后同ID重新登场 | 新对象不继承旧待机能力的Heart；事件与Replay保留原来源已离场标记 |
| 获得加成后离场 / Live结束 | 清理临时Heart，原始印刷Heart不改 |
| 来源在手牌、控室或成功Live区 | 不触发此Stage Member的Live开始能力 |
| 旧manual或旧无source policy结构化快照 | 不补写新策略，历史行为与序列化形状保留 |

来源离场测试使用另一个明确AUDIT手动待机能力，通过合法ManualAdjustmentAction处理，
不是让玩家在pending时绕过顺序。不是把控制fixture当作另张官方卡的技能覆盖。

## 同类交互修正

LegalAction额外输出可选`requires_color_choice`及`color_slots`，保留原费用卡选择类型。
前端只有两张费用卡和颜色都已选时才允许确认；AI已支持从`color_slots`生成选择。
另外四条已有登记：`PL!-sd1-003:2`、`PL!HS-bp1-006:2`、`PL!N-bp4-011:1`、`PL!S-bp5-005:1`。
本批对其验证的是组合控件选项契约，不宣称重新完成四张卡所有语义的独立审查。

## 证据与保留边界

- `tests/test_live_discard_color.py`：48项费用、六色、拒绝、来源对象、旧快照、SQL Replay、四AI与隐私断言。
- 前端117项通过，新增费用和颜色组合提交、来源Heart不适用的中日提示；TypeScript/build通过。
- 图文报告70/70：31真实状态转换、39Registry契约，见
  `logs/continuous-discard-color-effects-20261026/effect-verification-report.zh-CN.md`。
- 固定10局AI均3–9回合正式完赛，双方至少各成功Live一次，Replay一致；5454pass/1既有review，
  Live矩阵20/20及4项条款解释待审。日志`logs/continuous-discard-color-ai10-20261026/`保留ignored。
  这10局没有实际触发本卡，不替代48项定向证据；不是独立人工裁定或AI强度提高。
- 全量profile、源码指纹、manifest和pre-push由协调器保存真实证据，文档不代替执行结果。

本轮首先重审重叠父任务。PDF10.1.2/10.4.1要求检查时点清理，9.9.3要求入场时先适用常时效果；
当前单顶部结构仍不能证明完整临时多Member场面与继承观察者。因此六条正式登场继续manual：
`PL!-PR-015:1`、`PL!SP-PR-020:1`、`PL!N-pb1-013/015/017/023:1`，保留
`temporary_overlap_stage_view_and_inheritance_unresolved`，父任务in_progress，不强行登记。

同一分支与Draft PR #54，不合并部署；旧44/6项dirty工作树及原始ignored报告不改。
