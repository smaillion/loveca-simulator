# 四季：Wait移动后复原与原来源对象验证

## 本轮新增

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP07/PL!SP-bp7-008-P.png" width="150" alt="若菜四季：本轮适配第2段移动复原">

卡图使用卡库已有官方链接，不抓取或打包图片。

- 技能：`PL!SP-bp7-008:2`，revision895。
- 完整卡文hash：`1105aa0ae1ef0d65a9c9856842d388d33aded5b27ba4a34639c225ba1eeb679b`。
- 精确原文：`【自動】ウェイト状態のこのメンバーがエリアを移動したとき、このメンバーをアクティブにする。`
- 登记903→904/1212（74.59%），manual309→308；仅test_validated，不提升人工reviewed。
- 第1段自身Wait抽1保持已有实现，不添加原文没有的回合1次限制。

## 复现与修正

先用原生Position Change交换两个场上Member，产生四季及一个受控AUDIT干扰能力。
先处理干扰能力，将四季送控室、再以同ID回场；旧结构化ready_source路径错误地使新对象Active。
本轮修复前的定向失败为`active != wait`，不是把manual标签改成executable就算完成。

新operation显式声明`source_object_policy=original_moved_stage_member`，只允许这一受限家族。
触发条件确认后，在invocation捕获原Stage对象资格；已有离场hook标记已待机能力的来源离场，
即使同一动作内马上回场，标记仍保留。Stage内再次移动不标记离场。
结算时保留触发资格；已离场则记录`original_source_stage_member_departed`，不复原新卡，
但能力正常结束并记录使用。不存在来源时不再抛Stage错误，也不要求错误skip。

原生manual区域移动会先产生pending，再经合法`resolve_effect`处理；不把它伪称为所有
manual操作都会立即自动结算。效果发动中的区域移动继续在父处理结束后结算，不能提前复原。

## 官方依据

固定本地综合规则ver.1.06，PDF SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。

- 4.1.4：Stage外离场后是新区域的新卡；Stage内Member Area转移例外。
- 9.7.7：来源离场不免除已触发自动能力的处理义务。
- 11.10.1/11.10.2：Position Change移动/交换。
- 11.11.1/11.11.2：Formation Change移动且区域不能重叠。

这支持本轮有限模型，不证明任意跨区引用、继承或所有同时触发已经完成。

## 定向证据

`tests/test_moved_source_ready.py`共39项：

- 真实CardDefinition核对分段、revision/hash；Active移动不触发，原地Formation不触发。
- Position/Formation/manual move真实移动后，经原生Action复原；三种正向SQLite Replay一致。
- Wait条件在触发时确认；受控已Active状态模拟先被其他效果复原，待机能力仍正常结束，不错误重新要求Wait。
- 无原文次数限制时不擅加turn1；受控再次Wait后同回合可再触发。
- 两能力先选干扰项：来源离场、同ID回场不复原，modifier cleanup开/关均正确。
- 再次Stage内移动不会被误判为离场；额外自动触发仍按既有顺序处理。
- 真实`source_to_waiting_room`效果离场后，已待机能力完成并记录非适用原因。
- 普通替换/Baton的底层handler会标记离场；**这两项是handler边界测试**，外层Action测试明确拒绝
  在pending未处理时登场，不能冒充合法的端到端“插队登场”。
- 非法移动、任意选中目标、缺少触发快照均原子拒绝，原state hash不变。
- 旧manual快照仍保留旧generic trigger，不被新registry偷偷重绑定；旧无policy的受控结构化
  快照保留历史Replay（包括同ID复原的旧行为）。不是回写旧对局的规则迁移。
- 四种AI通过未修改的LegalAction选择合法处理；换对手隐藏身份或自己牌库顺序不改变决策，
  双方玩家响应仍遵守上一批隐私过滤。

前端补充已复原、原本已Active、来源曾离场三种中日结果说明与自动效果提示；不改手机布局。
旧第一段抽牌测试中“第二段必须manual”的过期断言已更新为新快照契约，旧manual/旧Replay行为
仍由独立测试保留，不通过删除历史兼容断言来晋级。

## 图文与完整对战

图文报告65项通过，其中26项真实operation状态场景、39项registry契约。
新增正向复原与同ID回场反例，两者都展示官方卡图/原文与实际状态检查。
AUDIT干扰能力是受控测试工具，不是一张新增支持的官方卡。

固定20Deck池10局v1.2全部正式完赛、10回合内且双方成功Live，最长9回合；
零非法Action、错误skip和Replay差异。5454pass/1review，另4项Live解释仍待审。
**这10局没有触发本次新技能**：专项状态/Replay/AI才是该技能的直接证据，不能混算实战覆盖。

```powershell
python -m pytest tests/test_moved_source_ready.py tests/test_effect_verification_report.py -q
python -m tools.ai_sandbox.effect_verification_report --output logs/continuous-moved-source-effects-20261026
python -m tools.ai_sandbox.ai_rules_acceptance --database data/loveca.sqlite3 --output logs/continuous-moved-source-ai10-20261026 --decks 20 --attempts 10 --required-qualified 10 --max-turns 10 --max-actions 500 --policy simple_ai_v1_2
```

中文图文报告：`logs/continuous-moved-source-effects-20261026/effect-verification-report.zh-CN.md`。
整局报告：`logs/continuous-moved-source-ai10-20261026/比赛总报告.zh-CN.md`。原始报告保持ignored。

## 保留边界

旧`source_object_departure_reentry_requires_review`仅对此单一ready-source家族解除，
不提供通用对象epoch，不处理不同group目标、继承、附属能力、复杂continuous/replacement。
六条重叠登場技能继续manual，父任务继续in_progress，不恢复旧实验标签。
无Card Schema/SQLite/decklist迁移；只更新同一Draft PR #54，不合并、不部署，旧dirty工作树不改。
