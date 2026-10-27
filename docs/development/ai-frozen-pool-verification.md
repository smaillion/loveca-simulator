# 冻结30套牌：AI长局与技能实际触发报告

## 本轮结论

2026-10-26 JST，沿用 `codex/continuous-development` 和 Draft PR #54。
旧50局的16个上限案例，在共享v1.2策略下均在原260步以内正式结束；
全池为48/50完赛，达到本任务至少45/50的推进目标，但不是全规则认证。
另有2个新长局、3次明确manual skip，没有修改默认策略或掩盖这些限制。

## 可比较的输入

- 冻结来源：`logs/card-refresh-sandbox-2026-10-25-final/decks/` 的30个原始JSON。
- 牌组按文件名排序；按序逐套计算现有 `decklist_hash` 后以换行拼接求SHA-256：
  `e4d917c74f0a5ef70b587f8c47daa884bdba8779726a24d5f2eec7fa72d0c7f1`。
- seed9000–9049、原配对公式 `i%30` / `(i*7+3)%30`，每局最多260次原生Action。
- 当前引擎和卡库相同，只比较controller；不是v1.2对v1.1的镜像强度比赛。
- 前一轮20套牌、seed12000系列单列于 `ai-live-cycle-verification.md`，不与本表混算。

## 同池50局

| 指标 | legacy heuristic | 共享v1.1 | 共享v1.2 |
|---|---:|---:|---:|
| 正式完赛 | 34/50 | 42/50 | 48/50 |
| 行动上限 | 16 | 8 | 2 |
| 平均 / 最长回合（含上限局） | 10.68 / 16 | 8.74 / 15 | 6.98 / 14 |
| 明确manual skip | 0 | 6 | 3 |
| Replay错误 | 0 | 0 | 0 |
| 富余Member换牌 | 不使用 | 0 | 228 |

v1.2的7220次Action均写入AI决策事件；非法动作和运行异常均为0。
34/50同时达到10回合内正式结束且双方有成功Live；该条件不强行由测试工具制造。
旧脚本仍默认 `heuristic_legacy`，产品仍默认v1.1；v1.2是显式可选实验策略。

## 旧16局复核

| 原局号 | v1.2结果 | Action数 |
|---:|---|---:|
| 8 | 正式结束 | 171 |
| 9 | 正式结束，有manual skip | 162 |
| 10 | 正式结束 | 239 |
| 13 | 正式结束 | 107 |
| 17 | 正式结束 | 199 |
| 21 | 正式结束 | 168 |
| 22 | 正式结束 | 57 |
| 25 | 正式结束 | 227 |
| 26 | 正式结束 | 126 |
| 27 | 正式结束 | 150 |
| 30 | 正式结束，有manual skip | 182 |
| 34 | 正式结束 | 119 |
| 35 | 正式结束 | 85 |
| 37 | 正式结束 | 157 |
| 42 | 正式结束 | 168 |
| 43 | 正式结束 | 211 |

新上限局为12（seed9011）及47（seed9046）。单独用相同输入、block模式、600步诊断：
前者16回合/337步结束，后者14回合/280步结束，无manual skip或Replay错误。
扩大上限的结果不回填260步的48/50统计；它们仍是策略效率待改进样本。

## 技能计数与真实状态核对

最终v1.2报告记录570次可执行invocation：569次解算/拒绝可选效果、1次明确不可发动，
错误skip为0，未完成为0。实际解算率仍标569/570，不把不可发动当作成功执行。
manual部分单列3次 `PL!N-bp7-027:1`（seed9008一次，9029两次），不计入可执行完成率。
这是选择己方虹咲Member并与双方Stage其他Member的有效Blade严格比较、满足时来源Live加1分的技能。
它仍为manual，本轮不虚标注册；已加入下一优先任务，必须补真实状态/Replay/隐私断言后适配。
共享v1.1还遇到一次 `PL!N-bp4-007:1`，后续按实际频率继续归因。

seed9020的不可发动为 `PL!HS-bp6-005:2`：两个已触发回收能力依次结算，前一个取走最后一张
应援公开的DOLLCHESTRA Member；后一个只剩其他组合Member和DOLLCHESTRA Live，因此无合法目标。
已在实际对局处理前后验证公开区内容、事件及Replay，并增加使用真实registry定义的双来源状态测试。
测试显式保存“触发时条件已检查”的上下文，不能用缺少该上下文的手造旧snapshot代替当前对局。
新计数按invocation去重，分别显示解算、明确不可发动、错误跳过、未完成；触发前不可发动不冒充已触发结算。
依据仍为本地PDF ver.1.06和日文卡文；这不是独立语义Agent或人工裁定的完整审核。

## 工具与兼容边界

- `--deck-directory`只读取冻结输入；CLI拒绝输出覆盖该目录。
- 导出副本使用按序文件名，原牌组名称保留于JSON，避免重名覆盖或名称中的路径逃逸。
- `--match-start`是从1开始的原局号，不改变seed和配对；`--seed-base`默认9000。
- `--policy`默认legacy，其他选项为v0/v1/v1.1/v1.2；`noop`仅legacy/v0支持。
- 两位玩家由同一controller轮流驱动，但每次只提供当前一方私有观察；对手隐藏牌和未来牌序不参与决策。
- 不改规则引擎、Card/SQLite schema、HTTP API或技能registry；报告字段只是增加，不替换旧计数含义。
- 本轮新增18项专项，覆盖旧行为、4种policy、隐私、不修改状态、分局恢复、输入保护、输出路径、
  明确manual处理、真实双回收与SQL Replay。

## 复现与下一步

```powershell
python -m tools.ai_sandbox.blackbox_playtest --database data/loveca.sqlite3 --deck-directory logs/card-refresh-sandbox-2026-10-25-final/decks --decks 30 --matches 50 --max-actions 260 --manual-policy skip --policy simple_ai_v1_2 --output logs/frozen-v12
python -m tools.ai_sandbox.blackbox_playtest --database data/loveca.sqlite3 --deck-directory logs/card-refresh-sandbox-2026-10-25-final/decks --decks 30 --matches 1 --match-start 12 --max-actions 600 --manual-policy block --policy simple_ai_v1_2 --output logs/frozen-case12
```

本机完整结果：`logs/continuous-fixed30-v12-final50-20261025/`；
对照：`continuous-fixed30-v11-cap260-20261025/`、`continuous-legacy-fixed-decks50-20261025/`。
原始ignored报告和旧dirty工作树均保留，没有上传私有会话或认证信息。
下一任务优先补 `PL!N-bp7-027:1`，用相同牌组的block回归验证，而非继续只优化对战速度。
