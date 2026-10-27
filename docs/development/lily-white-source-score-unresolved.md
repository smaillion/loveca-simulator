# lily white来源Live得分：计数依赖审计

## 结论

`PL!-pb2-041:2`暂不晋级可执行。`unresolved_reason`：
`success_live_counting_override_not_modeled`。
这是已知卡文引出的执行模型依赖，不是假称已经发现官方FAQ歧义。
本轮没有改变registry、游戏引擎、默认AI、Card/SQLite schema或可执行率；两段仍为manual，918/1212及294 manual不变。

## 精确卡文与反例

官方数据库卡名「春情ロマンティック」，Live score7，work=`love_live`、unit=`lily_white`。
两段同属revision1020，完整卡文hash：
`d4db99fac1de6ee00db00cb77d66c86b4adb1920ebed6198e0d68490f915c0a8`。

- 第一段：在自己的成功Live区期间，己方lily white卡牌的效果统计成功区卡牌枚数时，此卡按两枚处理。第一段现为manual，不能在第二段实现中假定它不存在。
- 第二段：Live开始时，自己的成功Live区有两枚以上lily white卡牌，则仅此来源Live的score+1。
- 最小依赖场景：成功区仅一张本卡，另一个本卡位于当前Live区。实体枚数是1，但第一段要求相关计数按两枚处理；不能直接用实体`sum(unit_key in card.unit_keys)`判定第二段。

现有`success_live_unit_count_at_least`只统计实体枚数。12项测试中的孤立predicate probe证明它对“普通一张”和“带第一段的一张”都返回too_low；probe没有被写入registry，也不当作新执行器。
不能复用该通用condition再给玩家全局score：这样同时遗漏计数常时依赖、正文结算时取值、原来源Live与离场对象边界。

## 依据与待确认范围

固定综合规则ver.1.06，PDF SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
核对9.6.1（常时持续生效）、9.7.7（待机来源离场后仍须处理）、9.9.1及其信息处理顺序；
不据此擅自把此计数处理归类为已有某个replacement阶段，或泛化9.9.2的Member专用规则到Live。
本轮官方站点限定FAQ检索没有取得可用的相关官方FAQ正文；不能把搜索无结果当作“FAQ不存在”，也未采用第三方攻略作为裁定。

后续需要单独明确：只对己方lily white效果生效的计数上下文、跨单位筛选、多张来源、来源离场/返回、能力失效与结算前变化。
第一段仍manual时，不为整条第二段标记完整自动覆盖；若将来引入受限降级边界，必须有明确人工reason、原子性、UI/AI/Replay断言，不能只让自动按钮报错。

## 本轮真实证据

- `tests/test_lily_white_source_score_boundary.py`共12项通过：精确身份、成功区实体0/1/2张的实际Live开始待机、unit/work/区域区分、第一段依赖反例、四AI block/隐藏身份不变/不改输入、两种SQL Replay快照。
- 测试没有实现第二段，不声称来源score、复杂计数或本卡新UI已经验收。最终control/registry/backend/web证据单独保存在协调器本轮result.json。
- 上一轮冻结池seed18019实际入队第二段一次并人工停止；这是实际触发，不是牌组频率。
- 应用源码/卡库/registry/manifest指纹仍为`30f611b14b8092d4639ec187c385a58d0bd3f794b14b0e1fef4665f1f5b99a1a`，与原30局provenance及逐局摘要一致；本轮没有假称再次跑了30局。
- 原30局仍9完赛/21人工停止、158/160可执行完成、2个跟随其他人工待机、Replay及错误skip0。不把审计提升为新完赛结果。

## 下一有限切片与发布

独立任务`onplay-lily-white-reveal-four-live-search`针对`PL!-pb2-013:1`，revision986，hash
`0a06fcfee9cde86a6c33f9b5369470994fac45e9a4fe236a94aae1e9e7531f86`。
原冻结池有3次实际强制待机；该文本检查本次公开的顶四张是否全为lily white，再取其中Live，不统计成功区枚数，因而不依赖上述第一段。
仍需先核对全段和短牌库/刷新语义，再作真实状态、公开候补、SQL Replay、四AI及UI验证，不能按频次直接晋级。
本轮不推送、不改固定PR54的policy、不新建PR、不合并或部署；后续发布目标的明确审批仍待确认。
