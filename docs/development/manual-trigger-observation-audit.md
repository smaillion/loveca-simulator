# 人工技能实际观察：30套技能密集牌组诊断

## 结论

原gap工具仅统计`skipped_effects`，却把它显示为触发频次；可选能力正常辞退会完全漏掉。
本批离线统计v0.3分开记录：引擎`effect_triggered`入队、`effect_declined`、显式错误skip、
停止时可操作的强制人工待机。**入队不等于官方条件已满足，也不等于技能已发动或结算。**
不按牌组出现次数/AI决策次数晋级，不改engine、runtime events、SQLite、Hosted API或登记。
仍914/1212（75.41%），298 manual；`PL!S-bp2-005:1`保留待审。

## 诊断设置与结果

`simple_ai_v1_2`、`manual-policy=block`、30套合法牌组各作一次先攻侧输入，另一侧为固定置换，
种子18000–18029，最多500动作。新增`--manual-focus`仅用于离线诊断：保留低费Member与一张进展Live，
其余窗口优先含manual段的卡；不改变默认池、默认AI v1.1，也不保证技能条件一定匹配。

| 项目 | 当前结果 |
|---|---:|
| 合法牌组 / 诊断局数 |30 /30|
| 正式完赛 |6|
| 明确人工技能停止 |24|
| action cap / illegal action / runtime exception / Replay error |0 /0 /0 /0|
| 被观察到入队的当前manual ID |42 /298|
| manual入队事件 |80|
| 可选辞退 |51|
| 强制人工待机 |28个待机，分布于24局|
| 显式错误skip |0|
| 已登记可执行待机完成 |125 /127|
| 尚未处理的可执行待机 |2，随人工阻塞留在队列中，不是静默跳过|

含至少一段manual的卡副本，在30套牌组中由默认池124增至928（主牌共1800张）。
这是**卡牌构成**，不是触发率；也不能把6/30包装成发布验收通过。
静态/尚未观察到的技能不代表安全，80次入队也未逐条人工审查触发条件。

## 优先级与下一切片

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBLL02/PL!-pb2-039-L.png" width="135" alt="次批目标PL!-pb2-039">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/CLLS01/PL!S-cl1-010-CL.png" width="135" alt="多组公开图标回收待审">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PR/PL!N-PR-036-PR.png" width="135" alt="条件目标Heart待审">

| Effect | 入队 /辞退 /人工待机 | 取舍 |
|---|---|---|
| PL!S-cl1-010:1 |11 /11 /0|最高频，但分组图标筛选、排序入底及Blade联动复杂，先保留manual|
| PL!SP-bp4-027:1 |5 /5 /0|Formation Change，保留已有空间/跨阶段待审边界|
| PL!S-bp7-001:1 |4 /4 /0|弃费回收高费Member、按名字追加Blade，后续独立切片|
| PL!S-cl1-002:1 |3 /0 /3|Yell公开牌任选入底，需公开区移动历史与顺序测试|
| PL!N-PR-036:1 |3 /0 /3|选另一Member并按cost追加Heart，需原目标/时点测试|
| **PL!-pb2-039:1** |**3 /0 /3**|下一批：成功Live区μs两张条件与Yell公开数量+10，已有modify_yell_count操作可优先复核|

后者不因频次自动晋级。实施前先核对实际0/1/2张成功Live条件，再确认false不应卡住，
true改变Yell数量而非Stage Blade，并核对Live期限、刷新和Replay。
完整top40及每条原文、原因、各项计数在生成的中文报告，不把零观察项称为无风险。

## 复现与证据

```powershell
python -m tools.ai_sandbox.blackbox_playtest --database data/loveca.sqlite3 --output logs/continuous-manual-focus-30-bound-20261026 --decks 30 --matches 30 --manual-focus --manual-policy block --policy simple_ai_v1_2 --seed-base 18000 --max-actions 500
python -m tools.ai_sandbox.effect_gap_report --database data/loveca.sqlite3 --event-trace logs/continuous-manual-focus-30-bound-20261026/sandbox-progress.jsonl --output logs/continuous-manual-observed-bound-20261026 --top 40
```

`provenance.json`保存完整测试牌组、seed、策略、动作上限和源码指纹；每局摘要也携带同一指纹。
指纹范围为`src/**/*.py`、`tools/ai_sandbox/*.py`、卡库、registry和manifest；
它不是协调器全仓库指纹，文档/测试变动不影响该诊断指纹，最终工程门禁另绑定全仓库。
不读取或导出环境变量、GPT认证、用户token；观察器只保留effect ID与非负整数计数，不保存隐藏手牌或候选全集。

- 新增12项测试覆盖入队去重、辞退/skip/blocker区分、真实可选人工技能动作、旧摘要兼容、
  malformed输入拒绝、隐藏信息替换不变、不改输入、源码指纹和30套牌组合规/确定性/人工密度。
- 现有3项gap和1项20局sandbox回归通过；后者在工作区临时目录运行，未修改旧ignored报告。
- 旧`load_actual_trigger_counts`兼容函数保留但明确只返回旧skip，推荐`load_legacy_skip_counts`；
  CLI不再把它传进实际触发列。旧摘要走`--sandbox-summary`，真实事件走`--event-trace`，不混算。
- 最终control/registry/backend及pre-push证据由协调器保存；本批无frontend或runtime协议变更。

同一continuous分支和Draft PR54，不合并、不部署，旧44/6 dirty及所有既有报告保留。
