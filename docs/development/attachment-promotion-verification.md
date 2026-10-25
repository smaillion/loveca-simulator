# 附属 Member 转场：登場触发复核

## 结论与边界

修正 `PL!-bp6-003:2`：从本 Member 下方移到另一空 Member Area 的卡，原本已经位于
Member Area 内。新技能快照不再因此追加 `member_played` / `own_member_played`，也不增加
本回合登場次数。正常从控室进入的 Member 仍触发两类事件。

这是固定综合规则与精确卡文驱动的程序审计，**不是完整人工裁定**。登记状态仍为
`test_validated_executable / test_validated`，不提升 reviewed，不增加技能覆盖数字。
同回合从 Stage 外放到下方的卡，其外部入场身份仍随新位置保留；不能把不触发登場等同于
“解除本回合区域限制”。跨技能的移动触发与一般效果替换仍需各自复核。

## 卡牌与依据

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP06/PL!-bp6-003-R2.png" width="160" alt="南ことり PL!-bp6-003 卡面示意（非测试截图）">

> 【ライブ成功時】このメンバーの下にあるコスト2以下の『μ's』のメンバーカードを1枚、メンバーのいないエリアに登場させてもよい。

- identity：`PL!-bp6-003:2`，text revision `4`。
- 原文 SHA-256：`a97fbfd44a384f8217e07218649736855af4a6fd725dd9de9c7242520f6ed06e`。
- 本地综合规则 ver.1.06：`raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`，PDF 第 4、5、10、13 页。
- PDF SHA-256：`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
- `4.5.5`：下方卡也位于 Member Area；`4.1.4`：Area 之间移动不是一般跨区重建身份。
- `11.4.2`：登場自动能力的来源条件是 Member Area **以外**；卡文没有另外要求强制触发登場能力。
- `4.3.2.3`：未指定朝向时为 Active；`9.6.2.4.2.1`：效果放置仍执行区域选择处理。

没有重新抓取官网或引入 FAQ / Q&A。卡图仅辅助识别，测试结论以真实状态断言为依据。

## 修正前后

受控目标带有“登場抽 1”，场上观察者带有“己方 Member 登場抽 1”。它们只是验证触发的
专用 fixture，不声称卡图中的实际卡牌持有这两项能力。

| 场景 | 修正前 | 新技能快照 |
|---|---|---|
| 下方卡 → 空 Member Area | 额外触发两项抽牌 | 不触发，手牌 / 主牌堆不变 |
| 本回合登場次数 / 旧区域标记 | `+1` / 新区域加入 | 均不增加 |
| 真正控室 Member → 空区域 | 两项抽牌、次数 `+1` | 保持两项真实抽牌和 `+1` |
| 原卡朝向 / 表里 | Active / face-up | 不变 |
| 本回合外部入场身份 | 跟随卡牌 ID | 不变；新近附属卡仍限制其当前所在区域 |
| 同时存在的 Live modifier | 保留 | 保留，不视为离场重建 |
| 拒绝 / 非法位置 | 不应移动 | 区域和计数不变；非法 Action 原子回滚 |

先复现左右两个空区域的失败断言，再修 executor。当前专项文件
`tests/test_attachment_promotion.py` 有 22 个状态 / 契约场景：

- 左右区域、登場与观察者真实抽牌差异、外部控室对照。
- 真正 `live_judgment -> live_succeeded -> pending effect -> resolve_effect` 流程。
- 旧快照 × 新旧区域历史共 4 种真实 runtime SQLite Replay；final state、events 和 hash 一致。
- 三种 Simple AI 均提交原生 card / slot 选择；改变对手隐藏卡身份不改变决策。
- 双方 Online payload 均看到公开的转场卡，但看不到对方手牌；事件不带私有手牌 ID。
- 新旧入场身份、已有 modifier、后续 operation、可选拒绝、非法操作和受控 DSL 字段。
- 精确 candidate / registry / 原文 hash 契约，不继承模糊文本或人工审核标签。

原空区域测试中“附属卡应触发登場 / 增加次数”的预期已明确纠正；外部控室登場的触发与
隐藏信息测试仍保留，未删测试或以 skip 掩盖失败。

## Snapshot 与 UI

新登记操作显式保存 `entry_trigger_policy=member_area_external_only`。
缺省 `None` 保留旧执行方式，且序列化省略该字段，避免旧 Replay hash 漂移。
特别覆盖了上一批已经带有新区域历史、但还没有此技能策略字段的旧快照；不能拿区域历史
作为本轮触发语义的版本开关。无需 Card Schema、SQLite migration 或 Action API 变更。

新事件 `effect_member_promoted_from_attachment` 明确 `source_zone=source_attachments` 和
`member_area_entry_event=false`。结果确认面板用中日文解释“场内移动，不触发登場能力”，
不再把下方卡错误显示成控室来源；旧 snapshot 的事件仍保持原样。

## 固定 AI 回归

使用当前 20 Deck 池与 `simple_ai_v1_1`，seed `12000..12009`，10 局、600 action cap：

| 局 | Deck | 回合 | P1 / P2 成功 Live |
|---|---|---:|---|
| 1 | 01 / 04 | 3 | 2 / 3 |
| 2 | 02 / 09 | 6 | 1 / 3 |
| 3 | 03 / 14 | 6 | 3 / 1 |
| 4 | 04 / 19 | 7 | 3 / 2 |
| 5 | 05 / 04 | 19 | 2 / 3 |
| 6 | 06 / 09 | 7 | 0 / 3 |
| 7 | 07 / 14 | 8 | 3 / 1 |
| 8 | 08 / 19 | 6 | 1 / 3 |
| 9 | 09 / 04 | 5 | 3 / 1 |
| 10 | 10 / 09 | 5 | 3 / 0 |

10/10 正式完赛，平均 7.2 回合，最长 19；illegal / blocker / skipped effect / Replay 序列化
错误均为 0。仍只有 7/10 符合“10 回合内且双方均成功 Live”，与之前结果相同，**不宣称 AI
策略提高、每局必定触发本卡或所有步骤都完成人工审判**。本卡边界由上述针对性状态测试验证。
本机原始报告：`logs/continuous-attachment-promotion-ai-20261025/`，不随 Git 上传。

## 新发现与后续

用真实登记 `PL!-pb1-018:1` 加同一受控目标 / 观察者测试多玩家控室登場：Member 正确放置、进入次数为 1，
但两项应有的抽牌都没有入队（实际抽牌差 0，期望 2，pending choice 已结束）。
该路径走独立的 multi-player helper，不在本次单目标 operation 中修复。
已加入最高优先级有限任务 `multi-player-member-entry-trigger-audit`，下一轮先补真实
双方选择 / 自动效果处理顺序、Replay 与隐藏信息，再继续通用已有 Member 区域替换。

当前登记数仍为 **899 / 1212 = 74.17%**，313 manual；结构 strict integrity 为 0 errors /
0 warnings 仅代表绑定结构，不消除上述行为缺口。未合并、未部署，Cloud 仍未切换。

本机完整回归：pytest 675 passed（1 项既有 Starlette 弃用警告），Vitest 78 passed，
TypeScript / production build、42 项协调器测试、manifest 和 strict integrity 均通过。
最终提交前再次执行全部 required_profiles；机器日志由协调器保存，不把命令名称当作通过证据。
