# 成员实际复原来源与原对象：版本化底座

2026-10-28 JST。有限任务`effect-ready-member-object-provenance-foundation`，同一固定分支/工作树，仅本地实现验证提交。完整同源码门禁、提交与最终状态见[验收入口](../../logs/member-ready-provenance-20261027/final-acceptance.md)。只用unregistered probe，不绑定正式卡，不requeue穂乃果或其他blocked，不push/publish、新PR、合并部署或主机操作。

## 显式新快照

新增`ready_member_with_provenance_v1`。只有快照含该操作时才初始化可省略的`MatchState.member_ready_history`；旧ready不自动升级，无新操作的旧JSON不加键、旧SQL Replay保持。不是Card或SQL表迁移，不改登记、manifest或默认AI版本。新操作只允许明确顶层Member目标，不收额外amount/branch/来源policy，不是费用；原型不支持费用、cost_choice、follow_up_choice或manual执行。

历史policy为`effect_member_object_v1`，严格整数回合/对象序号与严格布尔coverage，记录真实invocation/effect、来源卡实例/效果玩家/所有者及当时unit/work、目标原Member对象token。已有Active不记；同一invocation/目标对象去重，查询按当前原Member再去重，不按操作次数累加。后来再Wait不撤销已发生事实。普通Active阶段不是卡牌效果，不记录。

真正离开Stage会使目标token失效，同ID返回没有旧资格，再次实际复原取得新token；Position/Formation保持对象，附属不当顶层目标。不裁定复杂重叠、继承或晋级，旧overlap门禁保持。来源限原Stage或Live Area，在触发/无费用起动时绑定；仍为原对象时读当前信息，离场保存最后信息并标记离开，同ID返回新卡面不覆盖旧来源。当前回合/invocation/effect/来源/操作者严格核对，缺失、畸形或伪造元数据原子拒绝。

已经位于其他区域的离场触发源、费用路线和正式生产者完整覆盖尚未认证，不能把底座当所有ready都已记录。来源snapshot与事件为原效果信息副本，不以返回的新对象替换旧来源。旧作品级flags语义保持；新操作的同形作品标志使用确认的原来源/最后信息。

## 未知不是零与隐私

只读`current_effect_readied_members`按来源所有者/效果玩家、unit/work及当前原目标对象筛选，不把来源单位当目标限制。无版本化历史返回None；中途引入新快照、已有旧成员复原标志，或新历史期间发生旧ready时coverage不完整，也返回None，不能当零人数。当前回合不符拒绝。新回合清理记录/对象映射，重新观察实际操作。

历史和`ready_source_lki_v1`仅内部SQL/Replay保留，不输出双方玩家视图；API-play/provider待机context显式移除内部来源信息。不会因历史恢复未知库/对手手牌当前card map权限，owner manual句柄继续与卡面权限分离。客户端不能提交历史、费用或伪accepted。四AI双方真实探针目标选择，隐藏ID/名称/卡号替换不变，两份输入不改；语义context只构造检查，未联网provider验收。没有新增产品UI或自动图文，现有穂乃果人工入口与301图文不算本卡实现。

## 真实验证

62专项含34 SQL：双方0/1/3变化6、Live来源手牌/未知库/返回/同区8、目标移区/返回/Position/Formation10、新旧快照2、重复复原1、真正Active阶段1、下一回合清理1、Stage来源离场/返回2、无费用原生起动2、返回后新token1。区域互斥/引用存在/Replay逐项相等，34份SQL归档。另测来源当前/最后信息、目标单位不限、迟到/混旧生产者时未知、严格元数据、双方玩家/provider完整视图和输入不变。先前61项连旧边界367关联通过，新增legacy SimpleNamespace缺省字段保护由最终全量再验收，不拼接旧绿色。

全部为明确unregistered probe和CONTROL构造，不是正式能力或生产日志。先修正夹具误挂通用Aqours Live的来源；起动夹具trigger/timing、费用选择和自动处理预期按真实接口纠正，没有放宽规则。专项发现新操作未列入目标选择分类，已补入，分步起动才实际处理目标。中间失败及冻结保留，不复用其绿色。

最终应用诊断`828bd42efe8c224571d0e82d0d87877020228d92fa3c6c8bd8cc89096207f913`绑定`logs/member-ready-provenance-20261027/frozen-30-legacy-compatible-final/`。原30牌组逐项相同，seed18000–18029、v1.2/block/max500；最终30摘要/Replay逐条核对结果见`evidence-binding.json`。前一轮同牌组仍19完赛/11人工、246/247可执行完成、1随其他manual待机，非法/runtime/Replay/错误skip0；不预报最终结果。正式快照没有启用新操作，不能把随机池当探针正条件覆盖，不称执行率/完赛/beta改善。`frozen-30/`、`frozen-30-final/`、`frozen-30-compatible-final/`均为legacy缺省字段保护前中间源码，不作最终依据。

最终checkpoint后重跑全部required profiles和门禁后pre-push，最后check后不改版本化源码/文档复用旧证据。登记937/1212（77.31%）、275manual及reviewed不变；穂乃果仍blocked。底座绿色不直接解除正式生产者覆盖依赖，下一有限提案只保存ignored日志，先按真实来源unit盘点生产者/费用/离场源，不凭正文含Printemps绑定，更不自动requeue消费者。其他blocked、44/6 dirty、stash/ignored保持。
