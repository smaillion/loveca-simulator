# 近江彼方：支付Energy检查并重排顶4张

## 本轮范围

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP07/PL!N-bp7-006-P.png" width="150" alt="近江彼方，本轮只适配第一段起动能力">

图片使用本地卡库保存的官方链接，不抓取或打包图片。

- 技能：`PL!N-bp7-006:1`，revision869。
- 完整卡文hash：`65f32a0d0b7434dc7133c8ed26e477bd609b0e669fb0a229451a735cb3c9f380`。
- 精确原文：`【起動】【ターン1回】【E】：自分のデッキの上からカードを4枚見る。その後、それらを好きな順番でデッキの上に置く。`
- 第二段堆墓/分支仍manual；只提升第一段至test_validated，不提升人工reviewed。
- 登记902→903/1212（74.50%），manual310→309，不按整卡统计。

## 复现与处理

初始定向测试复现 `unsupported effect operation: inspect_top_cards`：旧起动
路径把检查交给即时operation executor，而非原生检查流程。
新effect snapshot明确声明 `inspection_activation_policy=start_after_cost`，
仅允许固定Energy费用、自身私有全量检查与排序。先支付一次，再打开已有面板；
不新建generic manual操作，不将查看冒充抽牌，不允许将任何查看卡弃到控室。
None不序列化，旧manual与旧无策略快照保持原行为/hash。

## 官方依据

固定本地综合规则ver.1.06，PDF SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
9.4.1/9.4.2.3规定费用及完整支付，9.5.2规定起动时点；
9.6.3.1与卡文确定检查/排序，10.2.2.2/10.2.3确定不足时刷新。
这不是独立人工裁定认证，也不扩展FAQ敏感语义。

## 可核查状态

`tests/test_activated_inspection.py`含38项定向状态/响应测试：

- 从真实CardDefinition核对当前revision/hash/完整分段，而非合成卡文绑定。
- 自己Main可用，错误阶段、对手回合和非法Energy不改变原状态。
- 2张Active Energy中支付1张，查看顶4后手牌/控室不变，来源不Wait。
- 按3→1→0→2重排，之后第5张位置不变；结算后pending清空且本段回合1次。
- 少选、多选、重复、外部ID、错误顺序提交原子拒绝，已支付成本不重复执行。
- 牌库0/1/2/3张，以及2张牌库加3张控室刷新，按实际可用卡全量返回。
- 真实SQLite保存/重执行Replay和JSON往返一致；旧manual及旧无策略行为保留。
- 双方payload与事件检查私有卡不泄露；四AI policy能合法完成原生检查且不依赖对手隐藏身份。

前端定向契约：显示原文；选3张确认禁用，选4张后编辑顺序并只提交
`resolve_effect_choice`。不修改布局和用户数据格式，不新增SQL/Card schema。

补查发现历史事件原样输出私有检查ID与排序。现在只在玩家响应层过滤对手的
检查/候选/排序及未公开选择ID，保留本人响应、明确公开的卡片快照和原始Replay。
这不等于牌库完整输出隐私认证：牌库/历史ID关联已列最高优先级独立审计，
在该审计通过前不发布线上。

## AI与图文报告

固定20Deck池10局v1.2：10/10正式完赛，10回合内且双方成功Live，最长9回合；
无非法Action、错误skip或Replay差异。逐步审计5454pass/1review，另4项Live
区域措辞解释待审。**这10局未触发本次新技能**，不能当作新技能实战覆盖。
定向AI测试只证明后续排序合法，不声称各策略都会主动发动低收益重排。

图文技能报告共63项通过，其中24项真实operation状态场景、39项registry契约；
新增场景展示准确4张、Energy已Wait、排序、手牌/控室不变与私下返回。
这些数量不是官方规则裁定通过数。

```powershell
python -m pytest tests/test_activated_inspection.py tests/test_effect_verification_report.py -q
python -m tools.ai_sandbox.effect_verification_report --output logs/continuous-inspect4-effects-20261026
python -m tools.ai_sandbox.ai_rules_acceptance --database data/loveca.sqlite3 --output logs/continuous-inspect4-ai10-20261026 --decks 20 --attempts 10 --required-qualified 10 --max-turns 10 --max-actions 500 --policy simple_ai_v1_2
```

中文图文报告：`logs/continuous-inspect4-effects-20261026/effect-verification-report.zh-CN.md`。
整局报告：`logs/continuous-inspect4-ai10-20261026/比赛总报告.zh-CN.md`，原始报告ignored。

## 保留问题

四季 `PL!SP-bp7-008:2` 已有移动事件底座，但触发排队后离场、同ID重新入场缺
原Stage对象身份边界：`source_object_departure_reentry_requires_review`。
不能简单检查当前ID或提前复原，仍manual。六条重叠登場、继承与来源绑定父任务
继续保留，不以小技能进展宣称完整重叠完成。下一轮优先解决这一边界或另选规则
明确的manual家族。只更新同一个Draft PR #54，不合并、不部署。
