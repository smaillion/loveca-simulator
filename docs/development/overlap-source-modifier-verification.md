# 花帆中心能力：已触发不等于仍能给原 Member 加成

## 本轮结论

补齐现有 **`PL!HS-pb1-009:1` 日野下花帆** 的普通替换边界：
她在中心观察到『蓮ノ空』Member 登場后，能力已待机。随后因重叠离场，不取消能力，
但也不能把这次自身 Blade 加成留给控室里的卡，或稍后重新登场的同一 instance ID。

这是既有登记的准确度改进，不增加登记数：**899/1212（74.17%），313 manual**。
没有提升 `reviewed_executable`，六张复杂效果登场待审卡继续 manual。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBHS/PL!HS-pb1-009-P2.png" width="180" alt="日野下花帆官方卡面示意，不是测试截图">

| 身份 | 当前锁版本数据 |
|---|---|
| 卡号 / 名称 / cost | `PL!HS-pb1-009` / 日野下花帆 / 15 |
| effect identity | `PL!HS-pb1-009:1`，revision125，index1 |
| 卡文 hash | `38e3fc157108b2f0049174a08fa2cbf15180ac5809f99365e76087ef4a228613` |
| 原登记 | `test_validated_executable / test_validated`，本轮不晋级 |

原文：

> 【自動】【センター】【ターン2回】自分のステージに『蓮ノ空』のメンバーが登場するたび、ライブ終了時まで、【ブレード】【ブレード】を得る。

完整官方卡文另有一段 `ライブ開始時` 抽牌能力。本轮没有改变该段效果，也不应因为这段
不相关的 Live 能力而直接排除效果登场的目标区域。卡面、文本、属性与身份均由本地正式数据读取。

## 固定 PDF 依据

综合规则 ver.1.06，SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。

| 条款 | 本次含义 |
|---|---|
| 11.7.3 | 【センター】自动能力在来源处于中心时才触发，不能读成全场有效 |
| 9.7.2 / 9.7.7 | 已待机的自动能力不因来源区域变化而直接取消 |
| 10.4.1 / 9.5.3 | 先完成重叠规则处理，随后处理待机自动能力 |
| 4.1.4 | 离开 Member Area 后属于新区域的新卡；重新入场也不是原来的 Stage 对象 |
| 9.7.4.1.2 | 区域移动诱发需要的 Stage 信息具有离场前状态的规则边界，不能随意读取清理后的场面 |

这里只保存本切片需要的来源区域，不把它扩展成完整 Last Known Information、继承、常时或替换系统。
这是基于固定 PDF 的程序验证，不是人工裁定或 FAQ 审核。

## 人类可核对的状态变化

| 场景 | 触发 / 次数 | 本次 Blade 结果 |
|---|---|---|
| 花帆在中心，其他『蓮ノ空』Member 登场到空侧区 | 触发，消耗一次 | 中心花帆获得2 Blade |
| 花帆自身从手牌登场到中心 | 触发，消耗一次 | 新入场花帆获得2 Blade；实际支付 cost15 |
| 花帆在中心，被『蓮ノ空』Member 普通替换 | 清理前触发，结算后消耗一次 | 来源已离场，新增 modifier 为0，明确显示未应用原因 |
| 同一 instance ID 经另一个 AUDIT 效果重新登场到侧区 | 原待机能力仍处理一次 | 不把前一个 Stage 对象的本次加成给新对象 |
| 花帆位于左 / 右侧区 | 中心条件不满足 | 不触发，不产生加成 |
| 非『蓮ノ空』Member 入场 | 作品条件不满足 | 不触发 |
| 从花帆 Baton 入场 | 花帆作为费用先离场 | 不观察后续登場 |
| 本回合已经使用0 / 1 / 2次 | 结算后的计数分别为1 / 2 / 2 | 来源离场不重置次数，不因没有加成而退还次数 |

先复现旧实现的红测：中心被普通替换时只有未审提示，没有保留这条待机能力。
新实现断言实际 `effect_triggered`、`effect_operation_not_applied`、usage 和 modifier，
不是只改文字或把 debug skip 当成正常处理。

普通替换、受控父效果登场、先重入场再结算分别有状态测试。
AUDIT 父效果只是用于构造合法的先后处理，不是另外六张待审卡的自动化证据。

## Snapshot 策略与旧 Replay

精确候选与实际登记的 `gain_blade` 操作增加：

```json
{"overlap_source_policy": "original_stage_member"}
```

此受控字段只接受固定自身 Blade、Live-duration、无费用 / 选择、带来源区域条件的
`own_member_played` 自动观察者，不能作为费用或任意 target identity 覆盖开关。
只在当前新对局的有界 overlap 策略下捕获，并记录 `overlap_source_slot_at_trigger`。
清理后按捕获区域判断先前是否满足【センター】，不把清理后的顶部 Member 当成花帆。

旧 operation 缺省 None，序列化省略字段；旧快照继续保留历史提示 / 结算行为。
没有新增 MatchState 字段或 SQLite migration。新旧实际 SQLite Replay 的最终状态、事件与 hash 均核对。
Registry hash 已变化，manifest 同步；卡库 fingerprint 与卡文 revision/hash 不变。

## 验证证据与限制

- 新增 `test_overlap_source_modifier.py` **32项**；连同抽牌、Energy 和顺序回归 **115 passed**。
- 覆盖中心 / 自身入场 / 侧区 / 作品 / Baton / 两次限制 / 重新入场、费用与 stale revision 原子拒绝。
- 三种 Simple AI 使用原生 LegalAction 完成多能力结算；更换对手隐藏手牌身份不影响选择。
  双方 payload 不包含对手手牌身份，没有 error skip。
- App 组件测试 **89 passed**，中日结果说明明确区分“来源已离场”与“技能未处理”。
- 当前全卡精确同文扫描只有此1条候选需要该字段；candidate 与 registry 的身份、文本与策略一致。
- Live-start 段的区域放行仅随卡上显式新策略启用；没有该标记的旧快照保持原来的区域限制。
- 固定20 Deck池、seed12000–12009、10局、600 action cap：10/10完赛，平均7.2回合、最长19，
  blocker / skipped effect / Replay序列化错误均为0；严格10回合内且双方有成功Live仍7/10。
  不宣称策略提升或用随机池代替本卡的定向测试。
- 原始运行报告保存在 `logs/continuous-overlap-source-ai-20261025/`，不上传私有对局日志。

仍未解决的边界明确保留：

| unresolved reason | 后续范围 |
|---|---|
| `non_overlap_source_identity_requires_audit` | 本策略不是任意离场/回场/位置改变的通用对象 epoch，非重叠路径需独立审计 |
| `conditional_entry_overlap_snapshot_requires_audit` | 依赖完整瞬时 Stage 数量或其他条件的观察者 |
| `inherited_ability_overlap_requires_audit` | 附属 / 继承及复杂离场观察者 |
| `ordinary_replacement_existing_modifiers_requires_audit` | 本次不替代对离场前已经存在的其他 modifier 的全面清理审计 |

父任务继续进行，不恢复六张复杂技能的旧标签。仅更新同一分支与 Draft PR #54，不合并、不部署，
不修改旧 dirty 工作树或生产数据。
