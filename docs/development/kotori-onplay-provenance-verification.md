# 南ことり登场复原：首个正式来源历史快照

2026-10-28 JST。有限任务`printemps-kotori-onplay-provenance-snapshot-audit`。固定分支/工作树，仅本地实现验证提交；只绑定PL!-pb1-012:1，不全局启用范围策略，不requeue穂乃果或其他blocked。

## 完整身份与新快照

南ことり，cost2/Blade1，source unit=printemps/work=love_live。完整全文“【登場】自分のステージにいる『Printemps』のメンバーを1人までアクティブにする。”，revision427，SHA256=b9330edc34a6956d65e6eb4f353a012df515635f142ff3312f42c9bd9d8b182c。全文hash已从当前本地官方卡库复算，旧五生产者登记及卡面信息保存inventory-before.json。

新精确pattern为onplay_ready_printemps_member_up_to1_provenance_v3，只把本段改用已验证无费用ready_member_with_provenance_v1。card code/全文（不strip）/revision/hash均严格绑定；前后空白、hash或revision变化不能回退其他结构化pattern。登记结构化diff只允许本effect的actions[0].action_type与choice.orientation，其他四生产者逐项不变，manifest重生成；卡库、Card/SQL表结构不改。

卡文未限制目标为Wait，因此新v3允许选择本人当前Stage顶层Printemps Member 0至1名，包括已Active的目标；后者不产生新Wait→Active事实。旧v2的Wait预筛只是历史限制，不当作规则正确。初次保留该预筛的中间冻结不作最终证据。无费用，非Printemps/附属/他方或隐藏区域不是候补；不能以来源作品为由额外加目标work筛选。强制登场能力可以选零，不把选零当错误skip或任意拒绝发动。

## 来源与原对象

复用既有v1：真实登场入队时绑定invocation/effect、原来源/所有者/效果玩家、当前游戏回合及原Stage信息。来源回手、进未知库、控室、同ID返回仍处理待机，离区后不重读返回新卡面。场内Position/Formation保留原对象；选中目标真正离区后旧token失效，同ID返回不继承，附属后再回Stage同样不是原对象。后来再Wait不撤销已发生事实。

两张真实同名南ことり在同一回合分别登场并实际复原同一Member，两条真实invocation各有事件，但当前成员查询去重为一人。来源本身经明确CONTROL实际Wait后也可成为合法Printemps目标。CONTROL、合成目标、直接改unit/work的返回来源检查点均为明示测试构造/单位诊断，不是新增正式卡能力或生产日志。

旧v2与更早无unit筛选快照保留原ready_member及原筛选重放，不称旧无筛选正确。历史边界/生产者审计夹具显式固定旧v2动作和Wait筛选，避免动态重载新registry污染原审计。新快照含v1定义会按既有入口初始化内部member_ready_history，不要求每局都实际抽到本卡；其他旧ready仍使旧全局coverage未知。member_ready_coverage_policy始终默认None，范围账本没有因此全局启用。

## AI与验收

两项原生红例证明旧登记无来源事件且pattern仍v2。另一个估值红例证明新v1操作原型阶段估值为0、旧ready为6；为避免正式卡因换操作名被降值，补既有ready估值别名为6。该旧原型估值确有改变，不声称其不变；默认AI版本、其他四生产者的旧ready估值和策略参数不改，不据此声称策略改善。

81专项含55 SQL：双方七种0/1目标选择14，已Active/附属4，来源六种干涉乘双方12，目标六种干涉乘双方12，CONTROL来源Wait/目标Wait/混旧ready乘双方6，新旧v2乘双方4，返回新来源信息检查点1，两张原生同名登场乘双方2。区域互斥/引用存在/Replay逐项相等。非法费用/重复超量/非候补/错角色/旧revision/重复提交原子拒绝，空Energy与ai_decision字段兼容。

四AI双方在来源未知牌库时实际选择并提交，隐藏ID/卡名/卡号/unit/work/Blade替换、同步内部身份引用后动作不变，两份输入不改。完整双视角包含真实登场/移动/复原事件，来源LKI和内部历史不进玩家或API-play/manual provider构造context，不恢复当前隐藏card map，不破坏owner manual句柄。未进行provider联网验收。

3项原生UI覆盖0/1及无来源卡面显式提交，产品UI未改；图文新增5场景（0/1/已Active/无其他Member/非Printemps），完整306图文=268动态/38契约，中日文件含官方卡图，但不是完整对局或人工完整审查。固定PDF1.3.2.1、1.3.5.1、9.6.3.1.1、9.11.1/9.12.2原文已本轮重读；4.1.4、9.7.7沿用已验证原对象/待机底座。这是卡文与通则推导，不冒充本卡专属FAQ；没有将旧282条FAQ响应称为本轮新请求。

最终全部required profiles、门禁后pre-push、最终目标范围修正后同原30牌组冻结及提交，以logs/kotori-onplay-provenance-20261028/final-acceptance.md为准；最后checkpoint后不改版本化源码/文档复用旧检查。只算正式来源历史生产者1/5；登记937/1212、275manual和reviewed不增加，不算manual晋级。穂乃果及其他blocked保持；不push/publish、新PR、合并部署或操作主机。
