# Tiny Stars：两个姓名的Heart与Blade选择修正

## 结果与范围

实际复现 `PL!SP-bp1-024:1`「Tiny Stars」会自动给第一张同名卡加成。
现已改为在结算时**分别明确选择一名かのん与一名可可**，同一组的Heart与Blade落在同一卡上。
一个名字没有合法目标时，只忽略该组；另一组继续结算。两组都没有时明示原因并正常结束。

这是已有登记的准确性修复，不增加覆盖数字：**905/1212（74.67%），307 manual**。
不提升reviewed，不改Card Schema、runtime SQLite或既有deck格式。旧auto snapshot和Replay保留历史行为。
只更新同一continuous分支与Draft PR #54，不合并、不部署，旧dirty工作树及ignored报告不动。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP01/PL!SP-bp1-024-L.png" width="240" alt="Tiny Stars 官方卡面，实际状态使用受控Member测试">

## 精确绑定与规则

| 项目 | 内容 |
|---|---|
| 技能 | `PL!SP-bp1-024:1`，text revision836 |
| 全文SHA-256 | `b7216c82672134b14428b0acad44ae4c1acc7fd3b6bd87e7c08d6e370e5cf498` |
| 时点 | 己方Live真正开始后待机，结算时选择当前合法Stage顶层Member |
| かのん | 选择1人，heart05+1及Blade+1，持续到Live结束 |
| 可可 | 选择1人，heart01+1及Blade+1，持续到Live结束 |

> 【ライブ開始時】ライブ終了時まで、自分のステージにいる「澁谷かのん」1人は【heart05】【ブレード】を、「唐 可可」1人は【heart01】【ブレード】を得る。

依据仅使用本地综合规则ver.1.06与本地官方日文卡文；没有重新抓取官网：
PDF `raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`，SHA-256
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。

- 9.6.3 / 9.6.3.1：结算时选择，能够选择指定人数时必须选足，不能自动替玩家选第一张。
- 9.6.3.1.3：不存在目标时忽略对应处理，不取消其余独立对象的效果。
- 9.7.2 / 11.5.2：先待机再解算，其他待机效果可先改变场面。
- 9.6.2.4.2：来源离开原区域不取消已经待机的能力。
- 4.1.4 / 8.4.11：目标离场清理其补正，Live结束清理期限补正。

没有套用上一批单一目标policy；新增的显式策略仅允许两个不同姓名、独立组、
无费用强制Live开始、每组一项Heart与Blade。不同组操作复用既有`target_group_id`，不新增任意DSL。
姓名只做既有空白标准化，不模糊匹配；区域、数量、目标或group ID错误均原子拒绝。

## 人类可核对的实际状态

来源Live取实际卡库定义。Member为受控场面fixture，不冒充这些真实Member卡的全部技能。

| 场面 / 操作 | 期望与实际 |
|---|---|
| 左/中两名かのん，右一名可可，开始Live | 待机1项，modifier0，不再自动取左侧 |
| 选择中间かのん与右侧可可 | 中间heart05+1/Blade+1；右侧heart01+1/Blade+1；左侧不变；转应援 |
| 仅有可可，かのん缺席 | かのん组数量0；可可仍必须选1人并得到两项加成 |
| 两组都缺席 | 接受空分组，记录`no_legal_stage_member_at_resolution`，不卡住也不静默跳过 |
| 目标Wait | 仍可选，不擅自Active |
| 触发后目标出现/消失 | 按结算时Stage重新计算；缺席不要求选非Stage或对手卡 |
| 错误姓名、重复/跨组/未知ID、非Stage、对手、附属卡、漏选必需组 | 拒绝且原状态hash/revision/pending保持不变 |
| 选定目标离场并同ID返回 | 清理该组Heart/Blade，另一组不受影响 |
| 来源Live先离场 / Live结束 | 已待机能力仍处理 / 两组所有Live期限补正清理 |
| 旧auto无policy快照 | 仍按旧方式自动执行，SQLite Replay与最终snapshot一致 |

目标出现/消失和来源离场使用明确的受控待机快照，代表另一先结算能力的区域变化，
不是允许用户在pending期间绕过规则执行额外行动。

## 证据与限制

- 新增48项Python定向测试：真实Live触发/原子拒绝/部分目标/期限/SQL Replay/四AI/隐私/策略边界。
- 前端115项通过，新增3项两组/部分缺席/全部缺席的原生选择提交测试；TypeScript与production build通过。
- 图文报告**68/68通过**：29项真实状态转换，39项Registry契约。
  `logs/continuous-named-groups-effects-20261026/effect-verification-report.zh-CN.md`。
- 固定AI10局全部正式完赛，3至9回合，双方各至少成功Live一次，无Replay mismatch或规则审计失败。
  逐步5454 pass、1 review；Live边界20/20，仍有4项既有条款解释待人工复核。
  `logs/continuous-named-groups-ai10-20261026/比赛总报告.zh-CN.md`。
- 这10局没有实际触发Tiny Stars，不能当成本卡随机实战覆盖；本卡正确性以定向状态和SQL Replay证明。
- 全量profile结果保存在协调器证据中；脚本审计不是独立模型或人工裁定。
- 产品默认AI仍v1.1，固定回归显式使用v1.2；本批不改变AI强度策略。
- 六条复杂重叠登场仍manual，完整临时场面、常时与继承观察者未解决；没有借此批恢复标签。
