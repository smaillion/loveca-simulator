# 本人Wait费用后的复原来源原型

2026-10-28 JST。有限任务`effect-ready-source-wait-cost-provenance-probe`，固定分支/工作树，只本地实现验证提交。仅unregistered probe，不绑定正式卡、不requeue穂乃果，不把原型绿色当生产者完整覆盖。

## 显式新边界

新增操作`ready_member_after_source_wait_provenance_v1`，与旧无费用`ready_member_with_provenance_v1`分开。静态仅允许强制无条件起动、Main时点、每回合一次、费用恰为一次本人来源Wait、效果恰为选择另一名本人顶层Wait Member复原。没有混合费用、费用选择、后续分支、manual、amount/value/branch、来源自身或初始离场来源支持。旧v1仍拒绝所有费用，两种复原操作都不可作为费用。

费用前捕获真实来源invocation/effect/实例/效果玩家/所有者/当前回合与原Stage信息；必须本人Active顶层Member。既有费用执行后检查来源确实变Wait，再将内部`ready_source_wait_cost_v1`标记paid=true。客户端不能提交此证据，也不能在起动时夹带目标、额外费用/分支/颜色。后续严格核对同一已支付的原能力、after_cost阶段、真实严格整数回合和布尔支付值，不重新支付，拒绝拒绝必选、重复/超量/非候补、错误角色或旧revision。

起动后从当前合法其他Member选择一名。此限定原型在无Wait目标时按既有选择最小值规则拒绝起动，不扣费用；不将此行为推广为所有官方起动能力的通用裁定。附属不是顶层来源或目标。只记录实际Wait到Active，源本身支付Wait不计一次复原；目标可为非Printemps，查询筛的是来源单位，不是目标单位。

使用既有原Member对象token、来源/LKI和回合历史。目标离区原token失效，同ID返回不继承；场内移动保持，后来Wait不抹去已发生事实。原来源离区/返回不重读新对象，支付事实不依赖来源此刻还在Stage或仍Wait；但初始已离场源仍未支持。未追踪旧ready或晚引入历史仍未知，不解释为零。

## 时序与证据限制

现代`ap_nap_player_choice`流程在支付后锁定父能力。人工CONTROL即使排在列表前面也不能插入，专项原子拒绝保护保留。为隔离检验来源离区/LKI，八个SQL使用明确构造的已支付检查点和旧`effect_order_policy=None`，再通过旧顺序CONTROL路径移动来源；它们不是现代流程自然可发生的中断或官方能力。没有放宽产品结算锁，也不以这些检查点证明完整生产时序。

目标后续移动/再Wait同样是测试CONTROL检查点。两个核心SQL从原生起动、真实Wait费用、实际后续选择连续执行，旧快照对照不添加新内部键或历史字段。所有SQL断言区域互斥、引用存在、Replay逐项相同；控制/合成能力不是生产日志。

## AI与隐私

只为这个新操作增加既有ready_member估值别名，默认AI版本和旧无费用v1估值不改。v1/v1.1/v1.2在受限的真实起动候补集合中实际选择，四版本都实际提交后续目标。v0原本不主动起动，此边界明确断言no_safe_ai_action，再用原生玩家起动进入后续测试；不冒称四AI都完成自发起动或策略改善。

隐藏实例/名称/卡号替换不改后续决定或输入。完整双方玩家视图及API-play/manual provider构造context都剥离支付证据、ready_source_lki_v1和成员内部历史，不给未知来源当前卡面，不更改owner manual句柄权限。没有provider联网验收。

## 验收

71专项含20种SQL：双方连续原生起动2、旧顺序来源检查点8、结算后原目标检查点4、新旧快照2、无Wait候补拒绝2、附属来源/目标拒绝2。另有静态精确shape、费用证据畸形/缺失/旧回合/布尔、支付前方向、旧revision、重复提交、父能力锁及四AI/双视角/provider构造隐私保护。底层记录器也独立验证费用证据，不能仅绕过resolver直接记录未支付复原。

与旧底座/生产者审计/穂乃果边界的关联检查、两项原生UI与全部control/registry/backend/web及pre-push真实结果，以`logs/ready-source-wait-cost-20261027/final-acceptance.md`为准。两项UI保证有/无来源卡面时必须显式选另一Member，提交不含费用证据；不新增产品UI或自动图文，不把旧301图文计作本原型新增人工审查。

规则依据沿用固定综合规则：1.3.2.1同状态不算变化；9.4.1–9.4.2.3定义费用、本人资源和不可部分支付；4.1.4移区新对象、4.5.5.2附属无方向、9.11.1/9.12.2来源与最后信息。只是通则支撑这个明确受限原型，不是任何正式卡的完整裁定或专属FAQ。

Card/SQL表结构、卡库、generator、registry、manifest及正式卡绑定未改，937/1212、275manual和reviewed不变。PL!-pb2-010:1仍manual/blocked，初始离场源/LKI和限定来源覆盖账本仍需独立有限验证。新源码重绑同原30牌组冻结；正式快照未启用新操作，不把随机池当原型正条件覆盖。本轮不push/publish、新PR、合并部署、主机或其他项目操作。
