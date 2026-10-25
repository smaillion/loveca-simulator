# AI v1.2：Live 获取与策略验证报告

## 结论与范围

2026-10-26 JST，在同一 `codex/continuous-development` / Draft PR #54 开发。
新增独立可选 `simple_ai_v1_2`，默认仍为 v1.1，不合并、不部署。
本轮没有新增技能登记：899/1212（74.17%），313 manual，不提升人工审核等级。

## 规则依据与策略

使用本地综合规则 ver.1.06，PDF SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
8.2.2 / 8.2.4 允许将最多3张手牌背面设置后补抽，不限 Live；10.5.1 使公开的非 Live 进入控室。
没有 Live 留在 Live Area 时不进行无依据的应援、得分或成功移动（8.3.6 / 11.5.2.1）。
测试经过真实 set、抽牌、公开、控室清理及 SQLite Replay，不以脚本直接改状态代替处理。

v1.1 没有 Live 时总是设置零张，固定 seed12004 出现26次无 Live 的决策、拖到19回合。
v1.2 此时保留己方手牌估值最高的2张 Member，将剩余最低估值的最多3张合法候选用于换牌。
它不看未来牌库顺序或对手隐藏手牌，不保证抽到 Live，也不伪造双方成功。
已有 Live 时沿用v1.1计划、Match Point节约及末张Live保护；保留旧policy与Replay。

## 相同样本的50局比较

均使用当前20套牌生成规则、相同配对与seed12000–12049、600次整局AI决策上限。
基线源码为 `ea83e19`，v1.2报告增加seed、policy和简短决策原因计数。

| 指标 | v1.1 | v1.2 |
|---|---:|---:|
| 正式完赛 | 50/50 | 50/50 |
| 平均 / 最长回合 | 7.64 / 19 | 5.94 / 11 |
| 10回合内结束且双方成功Live | 29/50 | 38/50 |
| 单局最多AI决策 | 357 | 220 |
| 错误/未支持技能skip | 0 | 0 |
| Replay错误 | 0 | 0 |
| 新策略富余Member换牌 | 0 | 171 |

seed12004：19→9回合；seed12005：7→4回合并消除单边零成功；seed12009：5→6回合且双方成功。
这不是镜像胜率测试，不能据此宣称AI更强或策略最优。

## 10局逐步审计

v1.2先头10局全部满足正式胜负、双方至少1张成功Live、10回合内结束，平均6.0回合。

| 局 / seed | 回合 | 双方成功Live |
|---|---:|---|
| 1 / 12000 | 3 | 2 / 3 |
| 2 / 12001 | 6 | 1 / 3 |
| 3 / 12002 | 5 | 3 / 1 |
| 4 / 12003 | 6 | 3 / 2 |
| 5 / 12004 | 9 | 1 / 3 |
| 6 / 12005 | 4 | 2 / 3 |
| 7 / 12006 | 9 | 2 / 3 |
| 8 / 12007 | 5 | 1 / 3 |
| 9 / 12008 | 7 | 3 / 2 |
| 10 / 12009 | 6 | 3 / 2 |

逐步审计5454项pass、1项review、无fail；现有9项Live判定边界通过，PDF引用未缺失。
review为 `PL!S-bp7-024:1` 原有Heart替换：结构/hash正确，但文本未命中保守语义词典，须人工核对。
这只是有限可重复规则检查，不是独立模型熟读PDF后的全语义裁定，更不是全部规则认证。
完整逐局步骤、原文和事件保留于本地ignored目录：
`logs/continuous-ai-cycle-trace-20261025/比赛总报告.zh-CN.md` 及其 `matches/`。
策略说明位于同目录 `AI策略报告.zh-CN.md`，Live明细为 `Live判定审计.zh-CN.md`。

## 不应混算的旧脚本结果

使用 `card-refresh-sandbox-2026-10-25-final/decks/` 冻结30套牌、原seed9000系列与260步，
重新运行未替换策略的blackbox工具：仍34/50完赛、16行动上限、314/314已触发可执行技能完成、
零skip/Replay错误。16局索引仍为8、9、10、13、17、21、22、25、26、27、30、34、35、37、42、43。
结果保留在 `logs/continuous-legacy-fixed-decks50-20261025/`，不将不同测试池称为34→50改善。
父任务继续跟踪旧脚本共用策略、零Live与复杂重叠；本轮只结算独立换牌子项。

## 验收工具与下一步

AI-vs-AI按整局已执行AI决策计数，包括create时自动推进；256步分批不再使总上限乘8。
Human-vs-AI继续使用human-driver上限。非法动作、异常、revision错误、Replay错误或skip不能通过洁净门禁。
“80%完赛或明确blocker”的工具门禁不等同“至少45/50正式完赛”的性能目标，本轮实际为50/50。
新增22项专项覆盖选择/隐私/原生处理/Replay/上限，前端补中日简短决策理由。
无Card Schema、SQL、decklist、HTTP controllers契约变化；create预算仅为可选Python参数，默认不变。
下一轮应对旧30套牌应用共用controller做同池对照，再考虑扩大样本和是否切换默认策略。

复现入口：

```powershell
python -m tools.ai_sandbox.simple_ai_acceptance --database data/loveca.sqlite3 --decks 20 --matches 50 --max-actions 600 --mode ai-vs-ai --policy simple_ai_v1_2 --output logs/ai-v12
python -m tools.ai_sandbox.ai_rules_acceptance --database data/loveca.sqlite3 --decks 20 --attempts 10 --required-qualified 10 --max-turns 10 --max-actions 600 --policy simple_ai_v1_2 --output logs/ai-v12-audit
```
