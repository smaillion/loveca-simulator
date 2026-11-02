# Q253：当前原Yell与原来源Live得分

2026-10-28 JST。有限任务`live-success-current-yell-live-source-score-q253`，沿用固定分支和工作树，只本地验证提交，不push/publish、新PR、合并部署或主机操作。完整门禁、提交与最终状态见[最终验收入口](../../logs/q253-current-yell-source-score-20261027/final-acceptance.md)；定向绿色不替代全部profiles。

## 精确范围与依据

GALAXY HidE and SeeK，`PL!S-bp6-023:1`，revision72，完整hash`ecfac853f6d6c490d282df3610013bb0d0714c9941a9e23f1fc99f9cc898e1f7`。全文：`【ライブ成功時】エールにより公開された自分のカードの中にライブカードがある場合、このカードのスコアを＋１する。`这是已登记可执行技能的正确性修复，不是manual晋级；935/1212（77.15%）、277manual及reviewed不变。

原生Live成功两项红例分别证明：唯一Yell Live回手后旧全局score仍+1，以及正条件错误加到全局而不是原Live；`native-red.xml`保存。前轮`q253-valid-final.json/sqlite3`保持，初次误测卡级得分的文件不当作绿色证据。

本轮公开GET[官方FAQ API](https://llofficial-cardgame.com/manage/rule-qa/list?per_page=5000&status=published)实际282条，响应SHA256`030d275272b23e2c8682a8851ecc345f95302dae3a70aaccc6b70dd54689cea3`，保存`official-qa.json`。Q253直接裁定本卡：结算前唯一Yell Live被其他Live成功能力回收后不加分。Q107参照再次Yell后当前公开对象；Q119/Q120支持正文条件在结算时判断、已获得效果不因后来条件改变撤销。未命中其他卡号不代表FAQ不存在，工具不可读不等于官网不可用。

固定[综合规则1.06](https://llofficial-cardgame.com/wordpress/wp-content/uploads/2026/04/28140005/LoveLiveTCG_cr_1.06_260428.pdf)9.2.1.2规定未写期限的持续效果为game，不能沿用旧fallback的live期限。4.1.4移区新对象与期限分开；9.7.7保护来源离场后的待机。9.9.1.4/5先替换再加减。无期限及来源对象处理是通则结合卡文的推导，不冒充专属FAQ或完整人工裁定。

## 新快照与兼容

新`gain_source_score_if_current_yell_live`及`original_live_success_yell_source`仅固定强制Live成功、每Live一次、无费用选择、原来源Live+1、game期限。generator精确全文/revision/hash绑定，拒绝改变卡文后回退旧错误通用pattern；validator拒绝扩大数量、对象、条件、时点及附加步骤。

仅在新operation快照启用既有可空严格整数`yell_tracking_turn`及原Yell对象追踪。结算要求真实当前Live判定、本人成功、invocation真实回合和非布尔追踪回合一致。只计本人remaining原对象、原公开列表与当前Resolution Area交集内实际Live。0张不加、1/2张都只加1；原对象离区失资格，同ID返回不恢复，同区no-op保留，新进入处理区的非原Yell不计。缺失/陈旧/畸形/重复追踪原子拒绝，不猜历史或永久公开缓存。

只给原来源Live的`live_card_score`，不加全局score或其他Live。来源离场仍结算条件，但不加给离场对象、同ID新对象或其他Live；Live Area内移动保留原对象。成功后Yell牌移走不撤销已得分。新marker自身policy在来源离区清理，旧空departure policy也保护；正常Live结束实际移区清理，不把game标记强制当live到期。分数替换后再+1。

旧`yell_revealed_card_type_count_at_least`、通用modify_score及旧快照保留原Replay，包括旧错误行为，不宣称旧规则正确。不更改默认AI、Card/SQL表结构或隐私投影。来源进入未知牌库不复活卡面；公开Yell回手后对手当前card map不保留卡面。提交拒绝额外费用/选择/分支/颜色、错玩家、陈旧revision和重复，兼容空选择/energy数组及ai_decision记录字段。

## 验证边界

110专项含67种SQL：双方角色/先后攻/0-2 Live十二种，Yell成功前/待机后五种移区十例，来源六种干涉乘双方角色与新旧departure policy二十四例，已得分后五种移区乘两policy十例，新旧快照两例，原生Performance→Yell双方角色/顺序/新旧八例，正常Live结束清理一例。区域互斥、引用存在、Replay逐项一致。CONTROL/TAIL只是测试构造，不是正式卡能力或生产日志。

原生Performance八例在副本清空需求隔离阶段，单Live避免另一个必要Heart分配选择；多Live仅原来源范围由另外SQL覆盖。不冒充正式卡面下完整合法对局。显式live到期、替换/加分顺序及Q119条件后来变化另有状态断言。四AI v0/v1/v1.1/v1.2双方角色/正失败条件实际处理两个来源，隐藏ID/名称/卡号/Blade替换不影响动作、不改输入，完整双视角保护手牌、库尾和隐藏来源。291图文为253动态/38契约，新增五场景；6原生UI验证0/1/2、来源失效中日结果及单/双隐藏来源无费用提交。图文和UI不冒充完整对局或人工裁定，也不声称语义provider联网验收。

## 同牌组诊断与门禁

最终冻结目录`logs/q253-current-yell-source-score-20261027/frozen-30-final/`，先前`frozen-30/`是图文helper修正前的中间源码，不作最终依据。原30牌组、seed18000至18029、v1.2/block/max500保持。完整绑定、实际结果和是否触发本卡见`evidence-binding.json`及最终验收入口；没有实际事件不能从登记或入队猜随机正条件，不宣称完赛率、策略或beta改善。

本轮最终应用诊断指纹`7ea8823c4ede21576418b80772b2430b57f9ae65f606fd64e833740e525bc6b7`。仍19正式完赛/11人工停止、232/232可执行完成，非法/runtime/Replay/错误skip0，30Replay真；本卡没有随机触发或完成记录。Q253正反条件、原来源范围和清理由专项/SQL/图文验证，不以受控分支代替随机结果。seed18027仍第6回合118动作、Live1:1，停PL!S-PR-045:1，没有本轮新增完赛或覆盖改善。

全部required profiles及门禁后pre-push以最终checkpoint后同源码重新执行；最终结果和完整源码指纹写入ignored验收记录，检查后不修改版本化源码或文档。应用诊断指纹仅覆盖src/sandbox Python、卡库、registry、manifest，与完整门禁指纹范围不同。旧44/6 dirty工作树、stash、ignored证据及其他blocked保持，不自动requeue。
