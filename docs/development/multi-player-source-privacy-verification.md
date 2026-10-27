# 多玩家待机来源引用的隐私修复

2026-10-27，仅本地开发与验收，固定分支`codex/continuous-development`。
PR54已由维护者批准合并上线；本批不推送、不新建PR、不合并部署。

## 真实复现

基线`e4162dad6914b5750f7a2b80de01fc0a63738d64`的旧`PL!-pb1-018:1`：

1. 用原生`play_member`登场，产生登场能力与测试用CONTROL观察能力两项待机。
2. 用已存在的`manual_adjustment`处理CONTROL，将来源移入其所有者手牌或牌库。
3. `resolve_effect`开始原双方登场能力，首方提交`resolve_effect_choice`。
4. 轮到对手时，来源仍在隐藏区域，但正常选择及skip的元数据都引用了来源ID。
5. 旧网页和AI投影递归扫描全部legal引用，将这个非候补来源错误加入可见card map。
   语义代理也可能从来源引用读取卡面，不能只删正常选择的一处字段。

原生SQL动作红测试在修复前真实失败，不仅是直接编辑待机夹具。
`logs/multi-player-source-privacy-20261027/native-red.json`保留同一原生动作状态的基线/修复对照：
基线隐藏来源可见=true，修复后=false，原始状态未改变，原始SQL Replay校验通过。
CONTROL只在测试构造，用于制造合法的待机干涉；这不是生产日志，也不把CONTROL当正式卡能力。

## 修复边界

可见卡集合统一由实际区域和已验证的inspection策略确定，不再由legal元数据递归授权。

| 来源所在位置 | 所有者视角 | 对手视角 |
|---|---|---|
| 手牌 | 可见 | 隐藏，正常/skip/待机复制的ID均脱敏 |
| 未知主牌库 | 隐藏 | 隐藏，不因来源或diagnostics引用恢复身份 |
| Stage、控室等公开区域 | 可见 | 可见，公开候补仍可选择 |
| 本人正在私看 | 可见检查对象 | 不可见私看对象或候补 |
| 受限四张公开原型 | 四张可见 | 四张可见，但未知尾牌不公开 |

- 网页完整玩家响应同时处理card map、pending_choice、正常legal action与skip嵌套副本。
- AIObservation使用同一可见集合，删除原来独立的全部legal引用授权逻辑。
- API-play与manual语义代理上下文在输出前脱敏隐藏引用；不可见来源不生成source_card卡面。
- 本人必须提交的manual来源标识单独保留：必须匹配服务器实际待机的invocation/effect/source三元组、来源所有者和manual登记。它只是提交句柄，不授予card map、卡面或牌库位置权限；对手不能获得此例外，伪造/不匹配/非字符串标识不通过。原生SQL验证来源回牌库后本人仍可正常提交人工处理，未修改引擎或Replay格式。
- 已明确公开的`revealed_cards`历史继续保留，但历史不授予当前手牌或牌库永久card map权限。
- 规则引擎、原始MatchState、旧effect snapshot及动作合法性不改；无Card/SQL schema、registry、manifest或默认AI变更。
- 原语义代理卡文测试将原来未放入任何区域的来源放回公开Stage，保留卡文/schema断言，并增加隐藏来源的反向断言；不为兼容无区域夹具开放身份。

官方依据为仓库固定PDF`raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`，
SHA256=`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
4.1.2.2允许确认区域数量；4.8.2/4.9.2规定双方牌库非公开；4.11.2规定只能查看自己的手牌；
4.1.5.1保护进入非公开区域的顺序；9.7.7说明来源移区后能力仍须处理。
不能通过取消待机能力或修改实体状态来掩盖显示层泄露。

## 验证

- `tests/test_multi_player_source_privacy.py`共64项：旧登场/抽后弃/弃后抽和新控室回收，双方来源角色与手牌/牌库/Stage矩阵，另含本人manual句柄及伪造保护。
- 12项原生SQL组合：双方角色、当前与旧无deployment policy快照、手牌/牌库/控室；实际动作处理后重放相等。
- 四AI v0/v1/v1.1/v1.2选择不变，替换隐藏来源卡名/卡号/Blade及实例ID不改变对手完整响应或代理上下文，不修改输入。
- 正常选择和skip单独注入嵌套非候补引用，不恢复隐藏身份。
- 真实房间动作响应、REST重复获取/重连、SSE信号和原始Replay；SSE只传通知信号，不声称它传完整卡面。
- 既有私看、四张公开、公开选择历史与玩家响应测试继续验收；2项原生UI证明缺少来源卡面或来源ID为隐藏占位时仍能选择公开Member与区域。
- 定向关联回归与前端240项及生产构建通过。最初独立前端命令未设置可写TEMP导致权限失败，以及新测试夹具delete类型错误，均已修正；正式门禁重新执行全部profile，不拼接旧结果。
- 首次完整检查在控制/registry通过后主动停止：复查发现过度脱敏会使本人来源回牌库后的manual提交被拒绝，已补上述匹配句柄及两项原生SQL回归。该中断检查不作为最终验收。最终checkpoint后重新执行control/registry/backend/web四组及pre-push；实际源码指纹、各命令退出码与完整日志由主仓库`.tmp/development-loop/runs/`本轮result.json保存。仅全部通过后提交并complete。

这证明已列出的泄露路径及回归边界，不是全局安全认证，不改变人工reviewed或技能执行登记率：仍921/1212、291manual。

## 新源码冻结30局

最终证据`logs/multi-player-source-privacy-20261027/frozen-30-final/`；`frozen-30/`是补本人manual句柄前的中间验证，保留但不作为最终源码依据。
同上轮30牌组，seed18000至18029，v1.2/block/max500；provenance牌组逐项一致。
当前诊断源码指纹与provenance、全部30条摘要一致：
`0356411bfb11b26a1eb1ddb33f96d0f9b6c056445e0b6904b4058842a1576c3f`。

- 仍12正式完赛/18人工停止，180/182可执行待机完成；2项随其他manual待机保留。
- 无非法动作/runtime/Replay错误或错误skip；30局Replay全部通过。
- 此修复不增加技能覆盖、不宣称完赛率改善或beta/长局门禁达标。

下一有限任务为`PL!-pb2-005:1`的成功区得分图标条件与临时赋予μ's常时Blade能力审计，
seed18029存在真实mandatory manual。先核对特殊Blade Heart图标及临时常时能力的来源/持续范围，
不能把“获得常时能力”简单替换为当时Stage的一次性全体加成；不明语义保留unresolved。
后续PR目标仍待已发出的明确审批，不改policy或发布目标，不重复请求同项审批。
