# Aqours Blade6来源Live得分：验证与恢复检查点

## 2026-10-27 恢复检查点

以下旧阻塞记录保留为历史。维护者在列明两处误写恢复和后续Draft PR方案后要求继续LoveCA；本地限定恢复已执行，但修改发布目标另被安全检查拦下，已单独请求明确确认，尚未修改policy或发布。

- 使用带历史记录和租约保护的`requeue`恢复原任务，没有直接编辑运行状态；协调器50项测试通过，提交`122fd48`。
- 保存全部15个WIP文件后正常快进`ca3aec4`，Git内容逐文件一致；备份stash `68e4666ec45c41bbddf0603d571cb0f286b853aa`保留，ignored报告未动。Git规范化了部分CRLF，未修改文件语义。
- 仅撤销两处LL误写；结构化对比基线确认registry只剩`PL!S-bp3-025:1`变化，strict integrity为0错误/0警告，manifest已重新生成。
- Aqours、既有技能及图文报告专项共266项通过；双语图文191项通过。冻结30局9完赛/21人工停止、Replay无错误，本卡实际触发0次。正式说明见`aqours-blade-six-score-verification.md`，最终profiles以协调器本轮源码绑定证据为准。
- PR54已由维护者批准合并上线，不是开放Draft PR。policy仍固定54；未获新的明确批准前不调整该限制、不推送、不创建替代PR。

## 历史状态（2026-10-26，以下仅为保留的中断记录）

2026-10-26 UTC的15:17、15:47、16:17三轮连续确认同一审批阻塞，现将原切片登记为`blocked`。
后两轮只读预检，没有重试已被拒绝的恢复，没有伪称又跑了两次全量测试。
尚未收到维护者对限定LL条目恢复的明确批准；自动心跳的通用开发授权不替代这项审批。
依赖本切片的lily white任务不能领取；其他任务也不能在全局registry破损且工作树未验收时发布。

此切片尚未完成验收，未提交、未推送、未合并、未部署。
最后已发布版本仍为`90a10c6`，同一Draft PR54；其五项GitHub检查已全部通过。
本地分支保持`codex/continuous-development`，不创建替代分支或PR。

## 已真实复现的旧规则错误

`PL!S-bp3-025:1`，revision504，全文hash：
`0016b3bd6db1b30ca828f2dec99189841d606578a9d974ba1aaf919a52510cbb`。

> 【ライブ開始時】自分のステージにいる『Aqours』のメンバー1人を選ぶ。そのメンバーが持つ【ブレード】が6つ以上の場合、このカードのスコアを＋１する。

修改前两项真实状态断言失败，并非仅脚本猜测：

- Blade5被原`minimum_blade=6`过滤，待机直接取消；正文实际应先选择，再判断是否加分。
- Blade6结算后产生玩家全局`score`修正，来源Live的卡牌score仍5而不是6；正文只修改来源Live。

本地综合规则ver.1.06，SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
依据`2.8.1`、`2.10.1`、`4.1.4`、`8.3.8`、`8.4.2`、`9.6.3.1/3`、`9.9.1.5`，
读取当前有效Blade，区别目标与正文条件、来源Live与全局得分，以及来源离开后同ID回来的新对象。

## 原型与已完成检查

- 新受限`public_aqours_blade_six_source_score`不按Blade预筛选；固定新operation只改原来源Live。
- 待机记录原Live对象；离开Live Area后不重新绑定回来的同ID，清除已给出的卡牌score修正。
- 同Live Area内移动保留新策略的来源对象/修正；旧策略与旧Replay快照不静默修改。
- AI v1/v1.1/v1.2使用引擎给出的公开有效Blade选择可得分对象，不查看对手隐藏身份；v0保持原行为。
- 63项卡牌专项在登记误写前通过，含四AI、隐私、新旧SQLite Replay、原生对象移动、低Blade选择与临时/常时边界。
- 3项新增UI交互及全量225项Vitest通过。TypeScript与Vite打包完成，但production build在静态数据导出时因registry错误失败，不能记为build通过。
- 4项新图文场景的独立目标Definition状态断言通过，但全局图文报告尚未通过。
- 变更行静态检查和新测试文件静态检查通过。

上述局部证据不能冒充完整backend/registry门禁，也不能宣称新覆盖率或发布通过。

## 必须先处理的安全阻塞

本轮生成登记补丁时，重复JSON上下文导致改动落入两个无关条目：

1. `LL-bp5-001:1`的原`modify_score`误写为新`modify_source_score_if_selected_blade_six`。
2. `LL-bp5-002:2`误加入默认`auto_branch_from_cost_choice=false`和`branch_cost_conditions={}`。

开工前工作树干净，且本轮持有唯一写租约；diff已核对这些字段来自本轮误写，
但安全检查仍拒绝自动恢复这两个条目，要求维护者批准，已发送一次明确的审批问题。
不得换用其他写入手段绕过拒绝，不得放宽validator、改成manual或使用清理后的临时全局登记冒充通过。
没有明确批准时，只保留现场并等待；不要反复执行已被拒绝的恢复操作或重复全量测试。

已按允许范围仅修正`PL!S-bp3-025:1`自身的新action绑定，并单独验证其Definition有效。
两个LL条目仍保留现场，其中前者导致全局registry无法加载；manifest尚未重新生成。
此时不能运行完整验收或发布。当前JSON语义diff应恰好为上述两个LL条目及目标PL!S条目。

## 批准后的恢复顺序

1. 仅撤销上述本轮误写，保留其他内容。补丁必须包含各自完整effect ID上下文，避免重复片段误匹配。
2. 结构化比较HEAD，确认registry仅`PL!S-bp3-025:1`有语义变化，完整registry可解析。
3. 核对candidate/registry契约，重新生成manifest，重跑专项及完整双语图文报告。
4. 同冻结30技能密集牌组、seed18000–18029、AI v1.2/block、最多500动作诊断，并逐局核对源码指纹。
5. 更新正式中文报告、中日README/Changelog、AI notes和审计记录。
6. 最终checkpoint后执行control/registry/backend/web和pre-push，审查diff后才提交、complete、publish同PR54。

默认AI、Card/SQLite schema、未确认FAQ和原44/6 dirty工作树均未改变。
后续lily white来源score任务仍在队列，不在本轮跳过当前破损登记去新增覆盖。
