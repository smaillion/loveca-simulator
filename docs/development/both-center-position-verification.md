# ウィーン・マルガレーテ：双方中央位置选择

2026-10-27。固定工作树与`codex/continuous-development`，仅本地实现与验收；不推送、不新建PR、不合并部署。

## 最终验收入口

完整四组门禁、源码指纹、冻结诊断绑定和提交结果见[最终验收记录](../../logs/both-center-position-20261027/final-acceptance.md)。本报告中的专项通过不是完整门禁通过；只有全部required_profiles及pre-push通过、diff审查完成后才能提交并complete。未通过则保留in_progress，不拼接历史绿色。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP05/PL!SP-bp5-010-AR.png" alt="ウィーン・マルガレーテ PL!SP-bp5-010" width="220">

## 精确身份与依据

仅`PL!SP-bp5-010:1`，revision215，完整日文hash `a99058a753bf9e71a54740c7db2fe2e3ca2d5b5a8c6bf42387de11c4122caaf8`。卡文要求双方各自对本人中央成员进行Position Change；不是登场、Formation、指定对手移动或移动来源对象。先用原生登场复现mandatory manual，红证据`logs/both-center-position-20261027/native-red.xml`保留。

官方[Q&A公开接口](https://llofficial-cardgame.com/manage/rule-qa/list?per_page=5000&status=published)本轮实际读取282条，响应SHA256 `030d275272b23e2c8682a8851ecc345f95302dae3a70aaccc6b70dd54689cea3`，原文保存于同目录`official-qa.json`。Q223直接说明对手决定其本人中央成员目的地；它不直接裁定移动时序。Q220说明占位交换的另一成员也触发移动能力；Q139说明附属Energy随组移动。未命中特定时序FAQ，不等于FAQ不存在。

固定[官方综合规则PDF](https://llofficial-cardgame.com/wordpress/wp-content/uploads/2026/04/28140005/LoveLiveTCG_cr_1.06_260428.pdf)，本地SHA256 `c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`：

- 1.3.4要求主动方先选择，后方知道前方选择；1.3.4.1区分不带选择的同时处理与带选择的主动方先处理。本实现把每方Position Change视为带目的地选择的处理，依此先移动主动方、再由后方选择移动。此为通则结合卡文的推导，不冒充本卡时序专属FAQ。
- 7.2.1.1/7.2.1.2确定主动方；无手番阶段使用先攻，不使用界面操作指针或来源所有者代替。
- 11.10.1要求移到不同区域；11.10.2规定有成员时交换整组。Stage内移动不产生新对象；9.7.7规定已待机能力不因来源离场取消。

## 有界实现

新增`multi_player_center_position_change`及`public_both_center_position_sequential`快照，只允许固定强制登场、无费用/条件/附加动作、双方中央移动。全文/revision/hash生成器精确限定，不修改旧多玩家快照。双方各自只提交本人目的地`left/right`；无中央自动略过，有中央必须选择。额外对象、来源、区域或卡牌列表原子拒绝；保留既有`ai_decision`记录字段，不将其解释为操作参数。

当前中央和占位目标整组交换，附属跟随，Wait状态不变。第一方移动已公开，第二方才选择；移动触发可先入队，但父能力结束前不能处理。父能力结束后按现有AP/NAP规则处理待机，多条能力仍由玩家选择顺序，不能误称全部自动复原。选择中人工调整和错误skip不能绕过必选流程。

来源离场、回手牌/未知牌库或同ID返回都不取消该能力；它移动结算时各方中央，不参考来源初始位置/LKI。本人/对手目的地权限分离。旧manual snapshot继续人工处理并可SQL Replay。Card/SQL schema、默认AI版本与原有隐私授权不变。

网页只在服务器真实definition和policy匹配时向非操作者公开既有目的地/略过结果，不公开候补元数据或隐藏来源；marker伪造不开放选项。牌库尾牌与对手手牌不加入当前card map。四AI、旧沙盒分派和语义provider仅补本类型合法目的地提交。

## 真实专项证据

- 最终69专项：双方角色/主动方阶段、16种中央有无与占位SQL、5种原生登场加CONTROL来源干涉SQL及旧manual SQL，共22种SQL；实际移动触发顺序、非法/重复/他方提交、隐藏信息、不改输入、四AI均有状态断言。CONTROL只在测试构造，不是生产日志或正式卡能力。
- `targeted-compatible-final.xml`为最终69项证据；先前232项目标/关联绿色早于严格字段兼容修正，不替代最终全量。错误使用不存在的registry方法/表名和角色交换后ID前缀断言属于夹具错误，已修正为真实对象引用；未删规则断言。
- 2项原生组件交互验证本人目的地选择及提交；双语图文251项（213动态/38契约），新增4个双方中央有无场景。图文使用受控状态与官方卡图链接，不冒充随机完整对局或人工完整裁定。
- 严格字段检查曾拒绝四AI自带的决策记录；已仅保留记录字段兼容并复验四AI。`frozen-30/`与`frozen-30-final/`为中间源码，最终只接受`frozen-30-compatible-final/`与当前诊断指纹一致的证据。

登记结构化差异仅本段，目标928/1212（76.57%）、284manual，不提升reviewed，不等于人工完整裁定覆盖率。冻结30局保持原牌组/seed18000–18029、v1.2/block/max500，真实摘要及逐局触发以最终验收记录为准，不预先宣称完赛/长局/beta改善。

## 保留边界

姫芽第一段、lily white成功区两枚计数、同时公开四张的短库语义及凛获得常时能力的复杂重叠/继承均未解决，原manual/blocked和拒绝门禁不变。本实现不解除这些依赖。PR54已经批准合并上线；该次授权已用完，后续发布目标仍待先前发出的精确确认，不改policy或发布。
