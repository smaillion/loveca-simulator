# 小泉花陽：本人Wait费用后的原对象复原历史

2026-10-28 JST。有限任务`printemps-hanayo-source-wait-provenance-snapshot-audit`，固定分支和工作树，仅本地开发验证，不push/publish、新PR、合并部署或主机操作。最终源码指纹、全部门禁、提交与运行状态以`logs/hanayo-source-wait-provenance-20261028/final-acceptance.md`为准。

## 完整身份与有限绑定

PL!-bp6-008:1小泉花陽，cost7/Blade1，来源unit=printemps/work=love_live；全文为“【起動】【ターン1回】このメンバーをウェイトにする：自分のステージにいるほかのメンバー1人をアクティブにする。”。revision10/hash`c5c21450dc637b1907f36eb45ba9c264b4fbd1a6a7092aa2dbc6a5bc9b27179c`与CardDefinition和旧登记已复算并保存在ignored inventory-before.json。新pattern仅按card/fulltext原文（不strip）/revision/hash绑定；身份不符不回退本卡旧结构化pattern，其他卡沿用旧通用匹配。

只将本段改用`ready_member_after_source_wait_provenance_v2`，选择本人其他顶层Member严格一名，可Wait或已Active，不将来源的Printemps单位强加到目标。先原生起动支付本人原Stage Active来源的Wait费用，独立选择目标；已Active不产生复原事件但支付和次数仍消费，没有其他Member不能起动且不支付。来源不能是附属/手牌/他方所有者，目标不能是自身/附属/他方/隐藏区；额外费用、内联目标、重复/超量、伪造证明、分支和颜色原子拒绝。

旧登记中`source_zone=stage`与`source_orientation=active`在新受限v2形状中由合法动作源筛选及实际支付前严格验证共同保证，未简单替换操作名。原登记Wait目标预筛改为无方向筛选，动作显式selected，condition仅按已验证等价来源检查移除。registry结构化对比仅此effect的动作类型/目标、choice方向和两条来源condition变化，manifest重新生成；其他effect、卡库和Card/SQL表结构不变。旧正式快照保留旧ready/Wait筛选和原条件供Replay，不称旧规则正确。不是manual晋级，reviewed不升。

初次手工registry补丁误命中另一张卡，已即时撤回本轮自身的误改，再通过结构化API只更新花陽；全registry逐项对比确认其他effect完全相同，未覆盖用户改动。候选发现契约最初仍要求花陽原通用pattern标识而失败，现保留断言并更新为精确新pattern后通过；不是放宽候选数量或漏报新模式。

新专项的初版全registry对比依赖本地旧Git提交，在浅克隆中不可靠；发现后主动停止当次尚未完成的控制门禁，将可移植专项改为显式验证旧快照字段与新pattern。全registry逐项对比仍由独立ignored证据脚本真实完成，随后重新checkpoint与全部门禁，不复用被停止的检查。

## 限定v2候选修复与旧v1依赖

审计来源条件时原生复现两个既有未登记v2原型候选缺陷：来源已Wait或实际所有者不符时，Legal Action仍列出该能力，但实际提交因无法支付而原子拒绝。`v2-legal-red.xml`保留两项红例；仅对显式v2操作增加本人顶层Member、Active和所有者一致的合法动作筛选，第三个非Member异常来源也有负例。它改变旧v2快照的非法候选显示，不改变旧JSON或Replay状态；不是旧v1、所有能力或整个来源模型的全局放宽。两条正式花陽原生红例分别证明旧登记不记录来源历史且拒绝已Active目标。

独立诊断`v1-legal-diagnostic.json`发现旧未登记`ready_member_after_source_wait_provenance_v1`在来源Wait或构造的异所有者场景也会错误列候选，实际提交仍拒绝且输入不变。当前registry中正式v1费用生产者为空，该诊断不是SQL、生产对局或正式卡能力；本切片按范围未改旧v1，不称此风险已修复。后续应以独立任务补v1合法动作校验、旧Replay和双方AI/隐私验证；本地批次不推送或发布。

## 来源、对象与验收

复用既有真实支付证明和来源LKI，记录实际Wait到Active的来源invocation/effect、原实例、所有者/效果玩家、回合与unit/work和原目标token。来源离区/未知牌库/同ID返回不以新卡面覆盖旧信息；目标离区/同ID返回不继承，场内移动保持，后来Wait不抹去事实。现代父能力锁保持：付费后不能插入其他待机。来源干涉使用明确构造的`effect_order_policy=None`已支付旧顺序检查点，仅证明状态机制，不冒充现代流程自然中断。

原生专项及SQLite包含双方Wait/Active和非Printemps目标、来源条件比较、附属/异常所有者、来源离场返回、目标原对象、非法请求和旧快照。两张真实同名花陽分别起动并复原同一原Member，两个invocation可查询去重；中间将目标再Wait的`CONTROL-WAIT`是测试构造，不是正式能力或生产日志。四AI双方Wait/Active后续实际选择提交；初次如no_safe_ai_action则明确由原生玩家起动，不称四AI都自发起动或策略改善。隐藏来源ID/名称/卡号/unit/work/Blade替换并同步内部引用后决定相等、输入不改，双方玩家和API-play/manual provider构造context不泄露内部证明/来源历史或授权当前隐藏card map；未联网provider。

4原生UI覆盖目标Wait/Active及来源卡面有无，显式选择并提交，不携带内部支付证明。316图文为278动态/38契约，新五个花陽状态含中日和官方卡图；不是完整对局或人工完整审查。精确用例数、SQL归档、限定旧顺序和完整门禁以ignored最终验收记录为准。

规则依据[官方综合规则1.06](https://llofficial-cardgame.com/wordpress/wp-content/uploads/2026/04/28140005/LoveLiveTCG_cr_1.06_260428.pdf)的1.3.2.1、9.4.1至9.4.2.3、9.6.3.1.2/9.6.3.1.3和原对象/来源4.1.4、9.11.1/9.12.2，结合完整卡文推导，不冒充本卡专属FAQ或完整人工裁定。来源单位与目标单位不混同。

## 冻结与边界

同原30牌组seed18000至18029、v1.2/block/max500冻结结果和应用诊断绑定见ignored最终验收；不从未出现的花陽随机事件声称正条件、完赛率/策略或beta改善。正式历史生产者为花陽、南ことり和穂乃果第二段共3/5；937/1212、275manual及reviewed不变。PL!-pb2-010:1消费者与其余blocked保持，未requeue；缺失旧历史或旧生产者混入仍未知，不当零。最终checkpoint后全部required profiles和pre-push必须同源码真实通过，最后check后不改版本化源码/文档复用旧证据。
