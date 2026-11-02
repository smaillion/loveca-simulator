# 全员Active与原Live减需：未解决边界

2026-10-27，固定`codex/continuous-development`及工作树，仅本地边界审计；未新增技能实现，不推送、不改PR目标、不合并或部署。

## 当前结论

`PL!S-bp7-020:1`保持manual，`unresolved_reason=all_active_empty_stage_truth_value_unconfirmed`。本轮没有取得可直接支持“Stage零成员时，所有成员均为Active”真值的官方正文，不能凭`all([])`或自然语言直觉选择真/假，也不能照搬旧Energy实现。不是宣称官方没有FAQ，而是本次来源检查没有取得该边界的可用依据。

第2段已于`45e177b`完成，精确登记、原来源Live减需及旧Replay逐项不变。第一段被审计不意味着自动晋级。最终完整门禁、源码指纹、本地审计提交与blocked状态见[最终验收记录](../../logs/all-active-live-requirement-20261027/final-acceptance.md)。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP07/PL!S-bp7-020-L.png" alt="PL!S-bp7-020" width="220">

## 精确身份与来源

完整双段revision912/hash`2762be94925766143618a17b7a60b0cb252f776311eaf3f8198af0c49a60d046`，只审计第1段：

> 【ライブ開始時】自分のステージにいるすべてのメンバーがアクティブ状態の場合、このカードの必要ハートを【heart0】減らす。

固定官方PDF`raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`，SHA256`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`：4.3.2规定Active/Wait方向；4.5.5.2明确附属卡没有方向状态，不能把附属Member当额外Active/Wait成员；9.6.2.4.2/9.7.7表明来源离场不取消待机；9.2.1.2对没有写期限的持续效果按game处理，4.1.4的移区新对象另行限制来源。它们不能单独证明空Stage的全称条件真值。

实读[官方公开FAQ接口](https://llofficial-cardgame.com/manage/rule-qa/list?per_page=5000&status=published)282条，SHA256`030d275272b23e2c8682a8851ecc345f95302dae3a70aaccc6b70dd54689cea3`，原文`logs/all-active-live-requirement-20261027/official-qa.json`：

- Q96/Q103直接说明另一张卡的Energy全Active条件在各次结算时判断，不是触发时锁定，也不因之后Energy变Wait撤销已经获得的得分。这支持正文条件的结算时点，但不裁定本卡零成员情形。
- Q119/Q120的另一张卡条件同样在结算时读取。它们不把“当前全员Active”变成持续反复重算的静态条件。
- Q196仅确认另一张卡在Stage零成员时可以使用起动能力，未涉及本卡全称Active条件；不能当作直接答案。
- 本次公开数据没有命中本卡号；站内检索和网页工具没有取得相关直接正文，不等于FAQ不存在或官网不可用。未使用第三方攻略。

旧`all_energy_active_bonus`是既有Energy实现，不是本卡的官方裁定来源。现有第一段manual fallback的`duration=live`也只是旧快照元数据，不能据此认定未来执行器的期限；保留旧Replay不代表认证该元数据的规则语义。本轮没有修改它们、没有生成仅非空Stage可执行的半支持登记，也没有放宽校验。

## 真实边界保护

新增28项测试，包含11种SQL：8种双方角色/原生CONTROL来源离场到手牌、未知牌库、同ID返回、Live Area内移动，2种原生兄弟CONTROL把成员Active/Wait状态改变后保留本段待机，1种正式双段共同待机及仅第2段结算。CONTROL只是测试构造，不是正式卡能力或生产日志。

0/1/3名顶层Member、全Active/混合Wait/全Wait场面均从真实Live开始触发，并断言本段继续manual、不会自动生成减需或移动牌库；这些是“未擅自裁定”的保护，不将任何条件真值硬编码为新规则。附属卡结构与顶层数量分离，不把模型中遗留的方向存储值当作附属卡的规则方向状态。所有构造场面断言区域互斥。

四AI v0/v1/v1.1/v1.2在双方角色均返回`no_safe_ai_action`，不猜测未确认能力；隐藏实例ID/卡名/卡号/Blade变更不影响阻塞结果，原输入不变。该接口原因不是黑盒的`mandatory_manual_resolution`类别，两者不混用。

来源进入本人未知牌库后，本人所需manual提交句柄仍可用，但本人及对手当前card map不获得该卡面；来源回手牌时只有所有者可见。两种角色均真实提交人工审计记录并验证SQL Replay，没有因过度脱敏破坏旧人工入口。人工审计只记录标志，不冒充自动结算本卡效果。伪自动/错误玩家提交原子拒绝。

2项原生UI组件测试验证来源卡面存在/缺失时都保留结构化人工入口，不出现自动结算按钮、不自动调用提交。没有修改产品UI或卡面权限。与原底牌能力及多玩家来源隐私合计144项关联回归通过；局部绿色不代替最终完整四组门禁。

## 范围与冻结证据

应用src、sandbox工具、卡库、registry和manifest没有改动，执行登记仍930/1212（76.73%）、282manual，不提升reviewed。应用诊断指纹仍`67373d5115e12e5cf47e6c3d9b43f0e926ae22ac5f1d76e1fa43958bc95e603d`，已与前轮`logs/bottom-one-aqours-requirement-20261027/frozen-30/`的provenance及全部30条摘要核对一致，因此不重复无变化的冻结30局。

原池仍17完赛/13人工停止、216/218可执行完成、2项随其他manual保留，非法/runtime/Replay/错误skip0、30Replay真。seed18012第1回合18动作仍因第1段mandatory manual停止；第2段上一轮正条件真实完成一次不是本轮新增成果。本轮没有随机触发、完赛率或技能覆盖率改善。

本轮工程门禁绿色不能作为空Stage裁定、第一段实现或完整人工审查。待取得直接官方依据或有明确来源的正式人工裁定后，才能通过协调器显式requeue恢复该任务，不直接编辑运行状态，也不自动解除其他blocked任务。
