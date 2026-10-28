# 本人Wait费用后选择Active目标的独立v2原型

2026-10-28 JST，有限任务`effect-ready-source-wait-active-target-probe-v2`。只在固定分支和工作树本地开发验证，不绑定正式花陽或其他卡，不requeue穂乃果消费者。

## 明确边界

新操作`ready_member_after_source_wait_provenance_v2`仅允许本人原Stage顶层Active Member在Main起动、每回合一次、强制无条件能力：实际支付一次来源Wait费用，再分步严格选择另一名本人当前顶层Member。目标可以Wait或已Active；后者合法但按综合规则1.3.2.1不产生实际Wait到Active事件，支付和次数仍实际消费。没有其他Member时按固定最小目标数拒绝起动且不支付；只有已Active其他Member时可以起动。此范围仅为明确原型，不冒充正式花陽完整裁定。

旧费用`ready_member_after_source_wait_provenance_v1`仍只允许Wait目标；旧无费用v1仍拒绝费用。显式v2要求orientation=None，不批量放宽旧操作。拒绝混合费用、费用选择、额外动作、条件、manual、amount/value/branch、来源自身、初始已离场源、附属及他方目标；不能夹带目标作费用或客户端支付证明。支付后父能力锁不变，拒绝插入其他待机、再次支付、拒绝必选、重复/过期/错角色及非法选择，均断言原子性。

复用既有`ready_source_wait_cost_v1`真实支付证明和`ready_source_lki_v1`，没有新Card或SQL表迁移。resolver及底层记录器都核对真实invocation/effect/来源/效果玩家/所有者/严格回合、after_cost和paid=true；已Active的无变化路径同样不能绕过验证。来源离区/隐藏/同ID返回不覆盖旧LKI，目标离区同ID返回不继承原token，场内移动保持，后来Wait不抹去事实。旧JSON/Replay/作品级flags/未知coverage保持。

## 真实验收

93专项含34 SQL：双方Wait/Active原生支付选择4、无其他Member拒绝2、来源四干涉乘双方及两方向16、目标后续四检查点4、新旧快照乘双方4、无变化后次数消费2、附属来源与目标排除2。SQL逐项核对区域互斥、引用存在和Replay相等，归档`logs/ready-source-wait-active-v2-20261028/sql-evidence-final/`。另外有静态shape、畸形支付证明、非法payload、记录器防绕过和现代父能力锁保护。

来源干涉使用明确构造的已支付旧顺序`effect_order_policy=None`检查点，只验证LKI状态机制，不冒充现代流程自然中断。CONTROL/合成卡/目标后续干涉都是测试构造，不是正式能力、生产日志或完整合法对局。添加用例时曾误把记录器保护留在已完成SQL测试尾部导致两项失败，已移回原函数保留全部断言，最终93通过，不放宽产品规则。

646关联为添加最后两个附属SQL之前的91专项加555既有用例，真实全过；最后两项另纳入93专项及最终全量，不拼接旧绿色。四AI v0/v1/v1.1/v1.2双方Wait/Active后续都实际选择并提交；初次起动若策略返回no_safe_ai_action则如实断言后用原生玩家起动，不冒称四AI均自发起动。来源未知库的隐藏ID/名称/卡号/unit/work/Blade替换并同步内部引用后，决定相等、两份输入不改、两状态实际提交。完整双视角/API-play/manual provider构造context保护内部支付证明/LKI/历史和当前隐藏card map，不破坏owner manual真实句柄；未联网provider。

4原生UI覆盖Wait/Active与有无来源卡面，必须显式选择另一Member、accepted=true、空Energy且不携带内部证明。`ui-final.xml`共354案例中执行4、按名称过滤跳过350，不虚称全跑。无产品UI或自动图文新增，旧311图文不计原型新增人工审查。native-red.xml是旧框架拒绝未知新操作的红例，不是正式卡完成证据。

规则依据本轮复读固定PDF文本1.3.2.1、9.4.1至9.4.2.3、9.6.3.1.2/9.6.3.1.3；原对象与来源沿用4.1.4、9.11.1/9.12.2底座。不是专属FAQ或完整人工裁定，未把旧FAQ响应称为本轮新请求。

## 全量与冻结

最终checkpoint后必须同一源码完整control/registry/backend/web和pre-push通过，再审查提交并complete；真实run、源码指纹及计数只以`logs/ready-source-wait-active-v2-20261028/final-acceptance.md`为准，局部绿色不替代完整门禁。此记录在最终检查前保存，完成凭据在ignored验收文件中补充，不在检查后修改版本化文档复用旧证据。

冻结`frozen-30-final/`应用诊断`7cc969ebf9d80002e559aef5cac18d8d25478cda234e7f3f92b9234dcc24a801`与当前应用源码、provenance及全部30摘要匹配；原30牌组与穂乃果轮逐项相同，seed18000至18029、v1.2/block/max500，30摘要除指纹外逐项相同、30 Replay真，19完赛/11人工、246/247执行完成、一项随其他manual待机，非法/runtime/Replay/错误skip零。正式快照未绑定v2，不称随机原型正条件覆盖、完赛率/策略或beta改善；指纹不变不重复冻结。

仅新操作给既有ready估值别名，默认AI版本及旧操作估值不改。卡库/generator/registry/manifest、Card/SQL表结构、产品UI与隐私投影未改。正式历史生产者仍仅PL!-bp3-001:2和PL!-pb1-012:1，即2/5；937/1212、275manual及reviewed不变。PL!-pb2-010:1仍manual/blocked，其余旧blocked不解除。本轮不push/publish、新PR、合并部署、主机或其他项目操作。
