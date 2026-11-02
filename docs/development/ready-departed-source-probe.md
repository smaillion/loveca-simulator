# Stage离场后触发的复原来源原型

2026-10-28 JST。有限任务`effect-ready-departed-source-lki-probe`，固定分支/工作树，只本地实现、验证与提交。仅unregistered probe，不绑定PL!-PR-001或任何正式卡，不requeue穂乃果，不宣称五条Printemps生产者已覆盖。

## 独立操作与真实来源

新增`ready_member_from_departed_source_provenance_v1`。静态限定为本人顶层Stage Member实际进入本人控室后的可选、无费用触发，固定`member_left_stage_to_waiting_room`/`auto_triggered_event`，本人当前顶层Wait Member可选0至1名，动作仅一次所选Member复原。没有条件、费用、cost_choice、后续动作、manual、amount/value/branch或原来源自身操作。此原型只认证本人目标，不把它当PL!-PR-001完整目标范围裁定。

分两步保存证据：真正离区前只读采集原实例、原所有者、严格游戏回合、原slot、当时unit/work和已存在的该类effect IDs；移区完成后、建立真实待机时才绑定实际invocation/effect。不会把尚未生成的invocation ID谎称离区前已有，也不从控室/返回后卡面补原信息。

四处已有移区入口显式传递捕获值：原生Baton的共同移出函数、普通登场替换、有限效果登场替换、人工移区。仅含新操作的原来源会采集；旧来源返回None，旧trigger_data和JSON不增加键。新来源若没有有效捕获、原slot/实际控室移动/所有者/回合/effect不匹配则原子拒绝，不猜历史。附属进入控室不算顶层Member离场，进入手牌或牌库不触发本原型。

内部`ready_departed_source_v1`与既有`ready_source_lki_v1`逐项绑定，原来源zone=stage、departed=true。resolver和底层记录器均验证严格回合、真实invocation/effect/玩家/原实例/slot及unit/work一致。允许既有resolver从initial进入无费用after_cost阶段，不允许其他分步阶段，不将此阶段名当作已支付费用。旧无费用v1仍拒绝初始已在控室的来源，费用原型仍只允许原Stage Active来源及其实际Wait支付证据。

来源之后回手、进未知库、同ID返回、返回后场内移动均不更新旧来源信息。原目标离区清除对象token，同ID返回不继承；来源返回后若作为新的合法目标，也必须获得新目标token。场内移动保持，后来Wait不撤销先前实际复原。只记录实际Wait到Active；源单位与目标单位不混淆，目标可以非Printemps。

## 原生时序与边界

原生Baton、普通登场和有限效果登场在真实移区完成后产生新待机；有无Active来源均验证。可选能力可选0张、1张或明确不发动。人工CONTROL是明确测试能力；本轮在现代AP/NAP可选待机顺序下由玩家先处理CONTROL再选择复原能力，没有关闭结算锁或伪造自然中断。选择进入同一能力的后续原子处理时，既有父能力锁保持不变。

其他能力将来源作为费用送控室时，捕获的是离场触发能力的来源，不把造成离场的费用能力当成复原能力。有限效果登场用已有未登记部署夹具，实际支付/移动/后续复原都SQL重放，不冒充正式卡能力或完整合法对局。原来源返回后的unit/work直接改值仅为显式单位诊断，不冒充生产修改卡面动作。

## 验收与隐私

100专项含54种SQL：双方Baton/普通登场、原来源Active/Wait与0/1/不发动24；来源后续五种移区乘双方10；新旧2；人工移区2；其他能力费用离场2；原目标后续四种4；返回来源作为新目标2；有限效果登场2；附属来源排除2；离开到其他区域4。全部区域互斥、引用存在、Replay逐项相同。另有原v1仍拒绝初始离场源、缺失/畸形捕获、伪造参数、旧revision、错误玩家、重复提交和静态严格shape断言。

与费用原型、底座、生产者清单及穂乃果边界共315项关联通过。四AI双方在来源进入未知牌库后真实提交，隐藏实例/卡名/卡号/unit/work/Blade替换、同步内部身份引用后动作相同，两份输入不变；不声称provider联网或策略提升。完整双方玩家视图包含真实登场和移区事件，API-play/manual provider构造context均剥离新捕获、来源LKI和内部历史；历史不授予当前隐藏card map权限，来源句柄与卡面权限仍分离。

4项原生UI覆盖有/无来源卡面及0/1目标，显式提交且不携带内部捕获值。无新产品UI或自动图文，不把旧301图文计作本原型新增人工审查。首次红例为旧框架不支持新操作的快照校验；早期专项发现通用resolver在执行前进入after_cost，已按真实阶段修正新操作自己的阶段校验，不改旧费用或父能力锁。

规则依据沿用固定PDF1.3.2.1、4.1.4、4.5.5.2、9.6.2.3.1–9.6.2.4.2、9.7.7、9.11.1与9.12.2，不冒充专属FAQ或完整正式卡裁定。最终同源码全部profiles、pre-push、提交与同原30牌组冻结以`logs/ready-departed-source-20261027/final-acceptance.md`为准；最后checkpoint后不改源码复用旧绿色。

Card/SQL表结构、卡库/generator/registry/manifest、默认AI版本未改。AI只为新操作新增既有ready估值别名。937/1212、275manual及reviewed不变，正式历史生产者仍0/5，穂乃果仍manual/blocked。限定来源覆盖账本、正式生产者逐卡绑定及复杂继承/重叠仍需独立审查；本原型不解决姫芽来源位置/同区域目标资格。只本地提交，不push/publish、新PR、合并部署或主机操作。
