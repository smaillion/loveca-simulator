# 限定来源范围的复原历史完整性原型

2026-10-28 JST。有限任务`effect-ready-qualified-coverage-probe`，固定分支与工作树，只本地实现验证提交。显式unregistered闭合范围探针，不绑定正式生产者、不requeue穂乃果；0/5不是五张卡都manual。

## 独立可省略策略

新快照显式设置`MatchState.member_ready_coverage_policy=qualified_source_v1`，才建立可省略的`member_ready_qualified_coverage`。没有策略的旧快照不加两个键，不修改旧JSON/Replay。旧`member_ready_history.coverage_complete`、旧`current_effect_readied_members`默认语义和作品级flags保持；任何实际旧ready仍令旧全局完整性未知。

独立只读`current_qualified_effect_readied_members`分别指定当前目标所有者、来源所有者、效果玩家、unit/work。可信新操作仍只记录实际Wait到Active，按当前原Member对象去重。当前方向、裸ID、当前Stage/隐藏牌库都不用于推断过去。已Active不记录，重复复原去重，后来Wait保留事实，原目标离区/同ID返回不继承，场内换位/Formation保持。

初始revision非零、旧member flags、已有不完整历史、晚引入可信历史均不能证明本回合起点，返回None而不是零。新回合清理未知事实与旧事件/对象映射；可信历史尚不存在时不把范围账本提升为完整。

## 旧复原只提供未知事实

显式策略下，旧无费用`ready_member`在真实触发/起动入队时若原来源仍在Stage/Live Area，才采集内部`qualified_ready_source_v1`。它绑定真实invocation/effect/实例/来源所有者/效果玩家/严格游戏回合及当时unit/work。原对象仍在时读取当前信息，离场捕获最后信息，返回新卡面不覆盖旧来源。费用路线或初始已离场来源没有这个证明，不能从控室/返回对象补历史。

旧ready实际改变方向后，仅追加`UnprovenMemberReadyV1`：真实invocation、效果玩家、实际目标卡所有者、可有可无的权威来源信息。不会为旧ready制造可信目标对象事件，也不将其当正式v1生产者。已确认不匹配该查询范围的来源可排除；可能匹配或来源未知时，该范围仍None。来源未知时只按真实效果玩家/实际目标所有者限定相关范围，不猜来源单位或所有者。

未知事实保守保留到回合结束，不因后来目标离场就猜测已无相关影响。这不是所有获得/继承/未建模单位变化或任意改方向效果的覆盖认证，正式生产者仍逐卡另审。暂不支持的旧费用或离场来源会多阻塞，不会伪造零人数。

来源证明和账本均为服务器内部信息。新策略下旧ready结算拒绝客户端提交证明/策略/账本及无费用能力的额外Energy；客户端自报数据不进入查询。缺来源证明保留未知，畸形/陈旧的已有证明原子拒绝。策略未启用的旧行为不追改。

## 真实验收

77专项含45种SQL：双方0/1/3实际变化6，匹配/非匹配unit/work6，旧已Active与重复4，旧来源手牌/未知库/返回/换位8，初始离场旧来源三种后续移动乘双方6，新旧策略2，原目标四种移动4，真正Active阶段1，下回合清理1，无可信生产者历史新旧2，旧费用未知1，可信重复/后来Wait2，对方目标实际所有者2。全部区域互斥/引用存在/Replay逐项相同。与旧底座/费用/离场/清单/消费者边界共392关联通过。

CONTROL/合成旧生产者/对方目标是明确unregistered测试构造，不是正式能力、生产日志或完整合法对局。来源返回后直接改unit/work只为诊断旧信息不可被新卡面覆盖。初期把原栏位当移区被真实接口拒绝，已改成Position Change；客户端额外字段原来被旧通用路径忽略，已仅在新策略补原子拒绝，未改旧快照。

四AI v0/v1/v1.1/v1.2双方在旧来源进入未知库后真实选择并提交可信探针；隐藏ID/卡名/卡号/unit/work/Blade替换并同步内部身份引用后动作相同，两份输入不改。内部范围查询没有接入AI策略或改变默认版本，不声称策略改善。完整玩家视图包含实际阶段/移区/复原事件，API-play/manual provider构造context均剥离策略、账本和来源证明，不增加当前隐藏card map权限，不破坏owner manual句柄。未进行provider联网验收。

2项原生UI覆盖来源卡面有/无的显式目标选择，不自动提交或携带内部数据；初始预期遗漏现有accepted=true，已按真实接口修正。无新产品UI或自动图文，旧301图文不算本原型新增完整人工审查。

固定PDF1.3.2.1、9.11.1/9.12.2原文已本轮重新读取，4.1.4原对象边界沿用已验证底座；它们支撑实际方向变化和来源/最后信息，不冒充本策略的官方专属FAQ或正式卡完整裁定。本轮没有新请求FAQ，不把旧282条响应称为本轮新取。

全部required profiles、门禁后pre-push、同原30牌组最终冻结、源码指纹与提交状态见`logs/ready-qualified-coverage-20261028/final-acceptance.md`。最后checkpoint后不改版本化源码/文档复用旧检查。登记937/1212、275manual与reviewed保持，Card/SQL表结构、卡库/generator/registry/manifest/默认AI未改。穂乃果和其余blocked保持；本轮不push/publish、新PR、合并部署、主机或其他项目操作。
