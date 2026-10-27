# Stage 离场补正：已经获得的加成不应跟随回场

## 结论与边界

本轮先用红测复现：旧 Member 在中心已有2点 Blade，普通替换进入控室后，旧 modifier 仍存在。
新建对局现在清理实际离开 Stage 的卡牌定向补正，不把同一 instance ID 误当成同一个 Stage 对象。
这是准确度修复，不新增卡牌登记：**899/1212（74.17%），313 manual**，不提升 reviewed 状态。

仅更新 `codex/continuous-development` 与 Draft PR #54，不合并、不部署，不修改生产数据。

## 规则依据

本地综合规则 ver.1.06：`raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`。
SHA-256：`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。

| 条款 | 本切片的判定 |
|---|---|
| 4.1.4 | 离开 Member Area 到其他区域后是新区域的新卡，旧区域效果不自动延续 |
| 9.9.2 | 非常时能力产生的持续效果不继续作用于其后离开 Member Area 的卡 |
| 4.1.4 的 Stage 内例外 | Position / Formation / Stage 内移动不视为离开 Stage，不清理加成 |
| 4.5.5.4 / 10.5.5 | 随组离场的下方卡按既有规则整理；本轮同时清理这些卡的定向 modifier |

这是固定 PDF 下的程序状态验证，不是人工规则裁定，也没有引入 FAQ 或完整区域对象系统。

## 真实卡牌流程

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBHS/PL!HS-pb1-009-P2.png" width="180" alt="日野下花帆官方卡面示意，非测试截图">

使用本地正式定义 `PL!HS-pb1-009:1` 日野下花帆（cost15、revision125、index1），
文本 hash `38e3fc157108b2f0049174a08fa2cbf15180ac5809f99365e76087ef4a228613`。
卡文要求中心花帆在『蓮ノ空』Member 登场时，到 Live 结束获得2 Blade。

| 步骤 | 真实操作与断言 | 旧快照对照 | 新快照结果 |
|---|---|---|---|
| 1 | 花帆已经在中心，另一张『蓮ノ空』Member 正常登场到左侧 | 花帆+2 Blade | 花帆+2 Blade |
| 2 | 另一张不带该作品条件的 Member 普通登场到中心，花帆进入控室 | 旧+2 modifier仍留存 | 清除旧+2 modifier |
| 3 | 手动工具把控室中同一 instance ID 的花帆放到右侧 | 仍带旧+2 | 不恢复旧+2 |

第1步使用实际登记和完整卡牌定义；为隔离离场边界，其他 Member / Energy 为明确控制的 fixture，
不是已注册新卡。第3步是现有手动移动工具构造回场，不声称花帆具有免费登场能力。
另有真实 SQLite 三步 Action 重放，核对每步 modifier、最终区域、完整事件序列和最终 state hash。
卡面只是官方图片链接，不能当成 UI 操作截图或人工验收证据。

## 其他状态对照

| 场景 | 验证结果 |
|---|---|
| 普通替换 / Baton费用离场 | 清除离场旧卡 Blade、Heart、状态flag |
| 下方 Member / Energy 随组整理 | Member进控室、Energy回Energy Deck，旧定向补正清除 |
| 对方创建并存于对方玩家桶的定向补正 | 目标离场同样清除，不能取决于补正存放在哪一方 |
| 玩家整体补正 / 其他卡牌补正 | 保留，不因来源或无关目标离场而误删 |
| 手动移动到控室、手牌、主牌库 | 清除，之后回到Stage不恢复 |
| Position / Formation / 手动Stage内移动 | 保留原补正 |
| 有界效果替换登场 | 保留既有自身清理，新策略补齐跨玩家清理 |
| source_to_waiting_room 后再抽牌 | 清理发生在后续抽牌之前，原生结算正常完成 |
| 非法支付、非法区域、过期revision | 整个Action原子拒绝，原状态不变 |

## Snapshot / API / 隐私

新 MatchService 创建的本地和room对局都明确带有：

```json
{"stage_departure_policy": "clear_departed_card_modifiers"}
```

不要求调用方新增请求字段。旧快照缺省 None，序列化不增加字段，维持历史事件与Replay；
有界效果登场原先就有的自身清理也保持原状。不修改Card Schema或SQLite schema。
未知策略值拒绝加载，新旧JSON round-trip与SQLite Replay均有断言。

新增 `stage_card_modifiers_cleared` 只记录 `reason` 和 `removed_count`，
不输出完整modifier值、手牌身份或隐藏卡面；事件日志显示简短中日解除说明，不增加弹窗和操作步骤。

## 本轮证据

- `tests/test_stage_departure_modifiers.py`：**31项通过**；新增文件Ruff检查通过。
- 连同旧花帆、受控登場、入场历史，新增最后一项实际SQLite流程前已 **138 passed**；完整门禁另存协调器证据。
- App组件 **90 passed**，验证中日解除说明；没有重构界面布局。
- 三种AI在受控合法登場候选中选择并完成离场清理；更换对手隐藏手牌身份不影响决策，
  生成的己方payload不含对手手牌。该定向测试不代表AI策略变强。
- 固定20 Deck池、seed12000–12009、10局、600 action cap：**10/10完赛**，平均7.2回合、最长19。
  blocker、错误跳过、Replay序列化错误均0；严格10回合内且双方有成功Live仍 **7/10**，无策略提升。
- 原始报告 `logs/continuous-stage-departure-ai-20261025/` 保留本地，不上传私有日志。

## 后续未解决项

| unresolved reason | 待审边界 |
|---|---|
| `other_zone_move_modifier_lifetime_requires_audit` | 其他独立zone-move操作、单独抽离附属卡等路径没有因本轮自动获得完整支持 |
| `leave_source_last_known_information_requires_audit` | 离场触发需要读取旧数值/旧场面时，不能用清理后的场面代替完整LKI |
| `inherited_ability_overlap_requires_audit` | 附属/继承及复杂同时触发仍由父任务追踪 |
| `conditional_entry_overlap_snapshot_requires_audit` | 依赖瞬时Stage数量的复杂重叠条件尚待独立复核 |

两张PR和四条虹咲技能仍manual；不把这一个生命周期修复当成六卡完整验收，也不重新标记 reviewed。
