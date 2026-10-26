# 分支与工作树清单

相邻弃牌检索检查点：同一continuous分支将六条精确卡文接入已有费用策略，不改engine/SQL/Card schema；177专项、143前端和102图文通过，固定10局AI均合格但未触发本批六条。登记仍915/1212、297manual；下一批同文顶3私下取1逐卡审计。旧44/6项dirty与ignored成果不变，仅更新Draft PR54，不合并部署；见`adjacent-inspection-cost-audit.md`。

既有检索费用检查点：同一continuous分支修正7条自身Wait和3条虹咲弃牌费用，166专项、90图文、131前端通过；固定10局均3–9回合，唐可可实际检索4次。登记仍915/1212、297manual，旧snapshot不追改，原44/6项dirty与ignored成果不改。见`existing-inspection-cost-audit.md`；只更新Draft PR54，不合并部署。

检索费用检查点：同一continuous分支新增`PL!-pb2-032:1 / PL!SP-bp7-018:1 / PL!-pb2-008:1`，显式新snapshot重检费用、明确取消不可支付待机、区分公开与私下保留。105专项、80图文、四AI及固定10局回归；915/1212、297manual。见`typed-inspection-cost-verification.md`。既有单Wait检索另排审计，旧44/6dirty和复杂重叠限制不改；同Draft PR54，不合并部署。

虹咲检索检查点：同一continuous分支新增`PL!N-sd2-009/012/014:1`和`PL!N-bp7-018:1`。完整技能段匹配，补查看选择的无Blade Heart筛选，102专项覆盖真实登场/费用/零张/刷新/四AI/双视角/SQL Replay；76图文、固定10局AI回归，登记912/1212、300manual。见`nijigasaki-inspection-verification.md`。六条复杂重叠仍manual，旧44/6dirty不改，同一Draft PR54，不合并部署。

Stage Wait费用检查点：同一continuous分支精确新增彼方`PL!N-sd2-006:1`和嵐珠`PL!N-bp7-012:1`，费用Member与来源加成分离，自费Wait不贡献Blade应援，原来源离场后同ID回场不继承。908/1212、304manual；63定向、72图文、固定10局AI合格，见`live-wait-cost-verification.md`。旧44/6dirty、复杂重叠父任务保留，不合并部署，同一Draft PR54。

弃牌选色检查点：同一continuous分支新增`PL!N-sd2-005:1`，来源对象快照防止离场同ID再入场误加成；费用与颜色组合UI同时修复既有四条登记。906/1212、306manual，48专项、70图文、固定10局AI合格，见`live-discard-color-verification.md`。重叠父任务和旧44/6项dirty仍保留，不合并部署，只更新Draft PR54。

双姓名Live检查点：同一continuous分支修复Tiny Stars `PL!SP-bp1-024:1` 自动首张选择，改为两组独立显式选人；缺席组不取消另一组，旧auto Replay保留。登记仍905/1212、307manual；68图文场景，固定10局AI合格。见 `named-live-group-verification.md`。六条复杂登场、旧44/6项dirty与ignored报告不改，只更新Draft PR54，不合并部署。

公开来源检查点：同一continuous分支为受控重叠登场增加显式完整绑定策略，核对双方公开Stage/附属/表向Live与入场候补，不读隐藏手牌/牌库/背面Live。来源未知导致全区域受阻时不支付费用，原生手动处理与AI可读暂停均有验证。见 `overlap-source-binding-verification.md`；904/1212不变，六卡仍manual，完整继承父任务继续。原44/6项dirty不改，只更新Draft PR54，不合并部署。

移动来源检查点：同一continuous分支精确适配四季`PL!SP-bp7-008:2`，显式policy区分原Stage对象与离场后同ID回场。登记904/1212、308manual；完整重叠/继承与六卡仍保留父任务。见 `moved-source-ready-verification.md`，旧44/6项dirty与ignored报告不改；只更新Draft PR #54，不合并部署。

玩家响应隐私检查点：同一continuous分支修复隐藏牌库card map/真实ID/顺序、未公开技能定义与私有历史输出；在线完整Replay延后至完赛或关闭房间。本地完整视图、原始Replay及SQLite不变。登记903/1212不变，旧44/6项dirty成果不改。见 `player-payload-privacy-verification.md`；只更新Draft PR #54，不合并部署。

起动技能检查点：精确新增四季 `PL!SP-bp7-008:1` 与ミア `PL!N-bp7-023:1`，
费用与抽后弃牌继续用原生操作；修复manual起动占位操作错误自动执行，保留旧结构化前缀。
当前902/1212、310manual；四季第2段及六条重叠卡不晋级。原44/6项dirty和ignored报告不动。
见 `activated-wait-draw-verification.md`。同一Draft PR #54，不合并部署。

Live矩阵检查点：只读核对旧58项核心描述及20项Live原型，迁移Live20项并补原生Action、
17字段完整预期、实际区域清理与逐项SQLite Replay。4项Match Point措辞待审与4项合成技能
单独标记，不搬运旧75项完成声明；旧End Phase清理/触发顺序仍待修，原44/6项dirty及报告不改。
见 `live-boundary-matrix-verification.md`。同一Draft PR #54，不合并部署，登记900/1212不变。

等待房间检查点：创建时固定Ruleset四字段，复用runtime_metadata独立JSON，不改表结构或decklist。
规则变化在Match写入前409拒绝，旧房间不补造身份，元数据随room保留期清理。见
`room-ruleset-lifecycle-verification.md`。原Ruleset迁移父任务本批收口，核心矩阵继续排队。
仍仅更新Draft PR #54，不合并部署，不改旧44/6项dirty成果与ignored报告。

重叠时点检查点：新增显式operation策略，区分旧Member无关的自身/Live时点与真正观察者，
50项受控状态/Replay/四policy验证、20局回归；六条manual和900/1212登记数不变。
完整重叠/继承仍留父任务。见 `disjoint-overlap-source-verification.md`。
仍只更新Draft PR #54，不合并部署，不改旧dirty工作树或ignored原始报告。

Ruleset检查点：同一continuous分支选择性接回Match/Replay身份，不复制旧房间ALTER TABLE。
补上指纹不符时拒绝Action、只读导出与中日提示，旧snapshot不补写字段。等待房间版本固定
仍归父任务，旧44项/6项dirty文件未改动。见 `ruleset-match-replay-verification.md`。
只更新Draft PR #54，不合并部署，不启用Cloud。

虹咲Live检查点：同一continuous分支精确适配 `PL!N-bp7-027:1`，37项状态/快照/Replay/
四policy/隐私专项及中日结果提示通过；冻结50局block中原3次manual blocker消失。
登记900/1212，不提升reviewed。见 `selected-blade-source-score-verification.md`。
仍只更新Draft PR #54，不合并部署，不修改旧dirty工作树与原始报告。

冻结牌组检查点：同一continuous分支为旧blackbox工具增加可选共用AI策略与原始牌组/seed恢复。
50局同260步：legacy34 / v1.1 42 / v1.2 48完赛；保留3次manual skip与新2个上限案例。
下一项为实际触发的 `PL!N-bp7-027:1`，见 `ai-frozen-pool-verification.md`。
仍只更新Draft PR #54，不合并部署，旧dirty工作树与ignored原始报告保留。

AI换牌检查点：同一continuous分支新增可选v1.2，默认v1.1不变；固定50局平均7.64→5.94回合，
前10局均在10回合内结束且双方成功Live。旧30套牌脚本仍34/50，父AI可靠性任务继续跟踪。
见 `ai-live-cycle-verification.md`。只更新Draft PR #54，不合并部署，旧工作树未改动。

第3次登場检查点：已修复实际 `PL!N-bp3-005:1` 计数与普通交代漏触发，保留第二段“2回以上”
及旧Replay；46项专项与固定10局回归通过。见 `third-entry-observer-verification.md`。
父任务保留，下一优先项为AI固定seed长局/零Live归因；仍为同一Draft PR #54，不合并部署，旧工作树不变。

本轮检查点：已在同一 continuous 分支修复新对局 Stage 离场遗留定向补正，真实花帆状态 / SQL Replay /
三policy与固定10局回归通过，旧快照保持原行为；父重叠任务与六张manual卡保留。
见 `stage-departure-modifier-verification.md`。只更新Draft PR #54，不合并部署，旧dirty工作树不变。

生成时间（UTC）：2026-10-25T06:57:14.815226+00:00。基线：`origin/develop`。
本地分支 32 个；工作树 14 个。

本次已删除 9 个完整合入 develop、且没有工作树占用的本地旧分支引用。
历史工作树与 ignored 报告尚未删除；当前只有 continuous-development 是自动任务写入入口。
`git cherry` 已确认 aidlc-workflow-adoption 的 1 个提交和
v0-9-card-sync-effects-ai-reliability 的 3 个提交与当前分支 patch 等价，不需要再次迁移。
优先核对 v0-9-rule-conformance-beta 的 44 项、phase5-api-play-coverage-next 的 6 项未提交改动。
远程仍有旧 PR #27（develop Draft）、#28（preview）、#38（test）；本次不自动关闭它们。

2026-10-25 迁移检查点：旧 v0.9 的 44 项与 API Play 的 6 项 dirty 内容均已只读清点；
只选择性迁移 Ruleset 来源定义 / JSON / 测试 / spec，并修正路径相关指纹与未审 FAQ 激活。
未提交原文件和 ignored 报告未改动、未删除。其他内容仍待队列逐批迁移；不视为已收敛。
详细范围见 `../22-ruleset-source-profile-migration.md`，后续任务见 `automation/queue.json`。

API Play 检查点：16 个旧提交已按功能分组核对，选择性补回 CLI 预检/采样入口，并修正
测试输入中的对手背面卡和他方 private choice 暴露。6 项 dirty 原型仍保留，成本分支与
Baton 手牌登场登记另列任务，不直接继承旧 executable 状态。见 `legacy-api-play-migration.md`。

成本分支检查点：已选择性重建 `PL!-bp5-003:2`，修正旧原型的费用 ID 清空、可选回收数量
和非本分支操作混入问题；旧 6 项 dirty 文件仍原样保留。剩余 Baton 原型继续独立复核。
见 `cost-result-branch-verification.md`。

Baton 原型检查点：已核对 `07f51e4` 的两个 PR entry，没有直接恢复其 executable 标记。
已修正精确文本手动提示条件；区域 / 朝向 / UI / AI 底座另列有限任务，并保留原工作树。
见 `baton-hand-deploy-audit.md`。旧 API Play 的提交与 dirty 成果已逐类登记去向，底座未完成前
父收敛任务继续保持进行中。

效果登场检查点：六条明确空区域的技能已修正 Active / 分步选择 / UI / AI；
四条没有空区域限定的虹咲技能已退回 manual。尚未迁移的已有 Member 区域替换和入场身份
规则继续由父任务追踪，两张 PR 卡仍不提升。原 dirty 工作树和报告未动。
见 `empty-effect-deployment-verification.md`。

入场历史检查点：新增对局以卡牌身份追踪外部 Member 卡进入 Stage，限制随当前顶部 / 附属卡
位置变化；旧快照缺省保留原语义和序列化。未恢复四条虹咲和两张 PR 卡的 executable，
附属卡转为顶部时的技能触发与通用替换登场另列任务。原工作树和报告继续保留。

双方登場检查点：`PL!-pb1-018:1` 已使用独立 snapshot 策略，双方选择后统一 Wait 入场，
再检测并处理登場触发；修正候选卡 / 区域 UI，保留旧 Replay。见 `multi-player-entry-verification.md`。
仍只有同一 continuous 分支与 Draft PR #54，不合并部署，不启用 Cloud，旧 dirty 工作树未动。

## 工作树

来源对象检查点：已为 `PL!HS-pb1-009:1` 增加有界 operation snapshot 策略，重叠前检查中心，
来源离场后不向新对象应用本次 Blade；旧 Replay 保留，registry/manifest 同步。见 `overlap-source-modifier-verification.md`。
非重叠对象、继承与其他旧 modifier 清理仍待审计；六卡 manual、同一 PR #54，旧工作树未改动，不合并部署。

Wait Energy 检查点：已修正 `PL!N-pb1-012:1` 在普通替换后漏补能量，包含附属 Energy 先返还、
费用 / 次数 / 空牌库和顺序消耗资源；新策略保留旧 Replay。见 `overlap-energy-observer-verification.md`。
旧工作树未修改，六张待审卡仍 manual，完整重叠父任务保留；同一 Draft PR #54，不合并部署。

待机排序检查点：已补同玩家技能顺序、AP/NAP 重检和已开始的费用/双方选择锁定，
新对局显式启用独立策略，旧 Replay 不变。见 `pending-effect-order-verification.md`。
完整重叠父任务与六张 manual 卡继续保留；旧 dirty 工作树未动，同一 PR #54 不合并部署。

重叠观察者检查点：真实 `PL!N-pb1-005:1` 的普通替换/费用Baton差异已补有限策略与状态验证，
新对局启用、旧 Replay 不变；复杂时点父任务保留。见 `overlap-entry-observer-verification.md`。
未晋级六张手动卡，原工作树和报告不动，继续同一 PR #54，不合并部署。

非公开选择检查点：已拆出并完成 `effect-private-filtered-hand-choice` 的受控零目标语义、
费用 / 旧 Replay / UI / AI 验证；未迁移或修改旧工作树。完整重叠父任务仍在进行，六张卡保持 manual。
见 `private-hand-choice-verification.md`；同一 PR #54，不合并部署，Cloud 仍未切换。

Energy Replay 后续检查点：两张卡的空朝向已在真实费用 / 分支路径修复，旧坏快照明确拒绝且不改写。
API / SSE 返回安全诊断，前端停止永久错误重试；候选恢复为精确文本匹配，登记率不变。
见 `energy-return-replay-verification.md`。仍使用 PR #54，旧工作树 / 报告未修改，不合并部署。

已有区域底座检查点：新增受控 `deploy_selected_to_stage`，简单覆盖 / 附属卡清理 / 触发已测试，
不绑定正式卡牌；完整重叠触发和私有手牌零张选择继续排队。旧 Energy 回牌库的空朝向
Replay 缺陷已复现并列最高优先级。见 `occupied-deployment-foundation.md`；旧工作树未动。

附属 Member 审计检查点：`PL!-bp6-003:2` 新 effect snapshot 不再把 Area 内转移算作外部登場，
保留旧 snapshot 的触发 / events / hash。另已复现多人控室登場漏发触发并独立排队。
见 `attachment-promotion-verification.md`。Cloud 仅备交接，旧 dirty 工作树仍未上传或删除。

| 分支 | 领先 / 落后 develop | 未提交文件 | 处理方式 | 路径 |
|---|---:|---:|---|---|
| `codex/new-card-pack-update` | 0 / 12 | 1 | 未提交成果，必须保留 | `E:\Repository\loveca-simulation` |
| `codex/fix-priority-card-activations` | 1 / 41 | 1 | 未提交成果，必须保留 | `C:\Users\HanX_\.codex\worktrees\65b5\loveca-simulation` |
| `detached` | 5 / 58 | 1 | 未提交成果，必须保留 | `C:\Users\HanX_\.codex\worktrees\ad90\loveca-simulation` |
| `codex/hotfix-room-lifecycle-cleanup` | 1 / 92 | 0 | 有独有提交，待对比迁移 | `E:\Repository\loveca-hotfix-room-cleanup` |
| `codex/release-rollback-protection` | 2 / 96 | 0 | 有独有提交，待对比迁移 | `E:\Repository\loveca-simulation-worktrees\release-rollback-protection` |
| `codex/v0-9-rule-conformance-beta` | 0 / 0 | 44 | 未提交成果，必须保留 | `E:\Repository\loveca-simulation-worktrees\v0-9-rule-conformance` |
| `codex/ai-rule-audit-10-match` | 0 / 1 | 0 | 已合并历史，报告核对后归档 | `E:\Repository\loveca-simulation\.tmp\ai-rule-audit-10-match` |
| `codex/aidlc-workflow-adoption` | 1 / 0 | 0 | 有独有提交，待对比迁移 | `E:\Repository\loveca-simulation\.tmp\aidlc-workflow-adoption` |
| `codex/continuous-development` | 4 / 0 | 13 | 唯一活跃主线 | `E:\Repository\loveca-simulation\.tmp\continuous-development` |
| `codex/local-simple-ai-stabilization` | 0 / 9 | 0 | 已合并历史，报告核对后归档 | `E:\Repository\loveca-simulation\.tmp\local-simple-ai-stabilization` |
| `codex/phase5-api-play-coverage-next` | 16 / 25 | 6 | 未提交成果，必须保留 | `E:\Repository\loveca-simulation\.tmp\phase5-api-play-next` |
| `codex/simple-ai-v1-1-registry-integrity` | 0 / 3 | 0 | 已合并历史，报告核对后归档 | `E:\Repository\loveca-simulation\.tmp\simple-ai-v1-1-registry-integrity` |
| `codex/simple-ai-v1-effect-accuracy` | 0 / 6 | 0 | 已合并历史，报告核对后归档 | `E:\Repository\loveca-simulation\.tmp\simple-ai-v1-effect-accuracy` |
| `codex/v0-9-card-sync-effects-ai-reliability` | 3 / 0 | 0 | 有独有提交，待对比迁移 | `E:\Repository\loveca-simulation\.tmp\v0-9-card-sync-effects-ai-reliability` |

## 分支

| 分支 | 领先 / 落后 develop | 被工作树使用 |
|---|---:|---|
| `backup/hosted-online-mvp-preview-base` | 11 / 128 | 否 |
| `backup/phase5-sandbox-driver-preview-base` | 11 / 128 | 否 |
| `codex/add-manual-waiting-room-return` | 1 / 73 | 否 |
| `codex/admin-phase5-big-patch` | 1 / 25 | 否 |
| `codex/ai-rule-audit-10-match` | 0 / 1 | 是 |
| `codex/aidlc-workflow-adoption` | 1 / 0 | 是 |
| `codex/area-move-rules` | 1 / 73 | 否 |
| `codex/continuous-development` | 4 / 0 | 是 |
| `codex/deploy-rollback-on-failure` | 1 / 73 | 否 |
| `codex/fix-activated-effect-buttons` | 1 / 73 | 否 |
| `codex/fix-hand-to-waiting-room-options` | 1 / 73 | 否 |
| `codex/fix-hide-opponent-hand` | 1 / 73 | 否 |
| `codex/fix-priority-card-activations` | 1 / 41 | 是 |
| `codex/fix-skill-text-heart-labels` | 1 / 73 | 否 |
| `codex/fix-waiting-room-choice-labels` | 1 / 73 | 否 |
| `codex/hotfix-room-lifecycle-cleanup` | 1 / 92 | 是 |
| `codex/local-simple-ai-stabilization` | 0 / 9 | 是 |
| `codex/new-card-pack-update` | 0 / 12 | 是 |
| `codex/pages-preview-release` | 1 / 128 | 否 |
| `codex/phase5-api-play-coverage` | 16 / 25 | 否 |
| `codex/phase5-api-play-coverage-next` | 16 / 25 | 是 |
| `codex/preserve-member-play-area` | 1 / 73 | 否 |
| `codex/preview-deck-transfer` | 10 / 128 | 否 |
| `codex/release-rollback-protection` | 2 / 96 | 是 |
| `codex/simple-ai-v1-1-registry-integrity` | 0 / 3 | 是 |
| `codex/simple-ai-v1-effect-accuracy` | 0 / 6 | 是 |
| `codex/speed-up-pages-preview` | 1 / 73 | 否 |
| `codex/v0-9-card-sync-effects-ai-reliability` | 3 / 0 | 是 |
| `codex/v0-9-rule-conformance-beta` | 0 / 0 | 是 |
| `develop` | 0 / 27 | 否 |
| `main` | 0 / 134 | 否 |
| `preview` | 3 / 128 | 否 |

`ahead=0` 仅说明提交已包含在 develop；不代表工作树中的未提交文件或 ignored 报告可以删除。
dirty、独有提交与无法读取的工作树全部保留。常规自动任务只使用 continuous-development。
