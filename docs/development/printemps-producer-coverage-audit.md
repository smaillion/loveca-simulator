# Printemps复原生产者覆盖审计

2026-10-28 JST。只使用固定工作树与`codex/continuous-development`。本轮是有限生产者清单及独立目标筛选修复，不是穂乃果技能实现，不requeue消费者。

## 真实来源清单

按实际`CardDefinition.unit_keys`含`printemps`且已登记直接`ready_member`操作盘点，得到五条。不是全文关键词搜索，也不声称覆盖尚未建模的manual、获得能力或复杂继承。

| effect | revision | 完整卡文hash | 时点与限制 |
| --- | --- | --- | --- |
| PL!-PR-001:1 | 712 | 15fa6ca29ca4e4bfab665dadebfe6bd076b833f84d99527392df394c43e80cfc | 离场到控室后触发，v1原型初始来源仅Stage/Live，不能直接替换 |
| PL!-bp3-001:2 | 442 | 03019af91423572a345dd28a3ff40213fb05239ed99452cff65fdd8c559bb476 | Live开始，无费用；同卡第1段不改 |
| PL!-bp6-008:1 | 10 | c5c21450dc637b1907f36eb45ba9c264b4fbd1a6a7092aa2dbc6a5bc9b27179c | 起动先Wait本人，后选其他Member；v1明确拒绝费用路线 |
| PL!-pb1-012:1 | 427 | b9330edc34a6956d65e6eb4f353a012df515635f142ff3312f42c9bd9d8b182c | 登场，限本人Printemps目标，本轮只修此筛选 |
| PL!-pb1-028:1 | 437 | 2079004eee0c3c29da064a8859bd918c283872063c845f240311f8b9120e9ff5 | Live开始复原Printemps，实际三人复原后得分，旧操作保持 |

全文、完整CardDefinition和旧EffectDefinition保存在`logs/printemps-producer-coverage-20261027/inventory-before.json`，包括双段全文而非截取段落代替hash。正式v1历史生产者仍为**0/5**，没有批量换操作。

## 南ことり独立缺陷

`PL!-pb1-012:1`全文：

> 【登場】自分のステージにいる『Printemps』のメンバーを1人までアクティブにする。

两项原生登场红测试真实证明旧登记会列出并允许复原非Printemps。修正登记的`choice.unit_key=printemps`，生成器增加card code、全文、revision427及hash精确绑定，pattern为`onplay_ready_printemps_member_up_to1_v2`。不把正确目标单位推广成所有Printemps来源都只能选Printemps：花陽的其他Member目标仍可为非Printemps。

操作仍为旧`ready_member`，没有新增执行器、历史记录路径或消费者绑定。旧无筛选快照仍SQL重放旧行为；这仅保留历史，不称旧规则正确。登记结构化diff仅此字段，manifest重新生成。937/1212、275manual及reviewed不变，不是manual晋级。

## 覆盖依赖

原型只在含新操作的快照启用；正式快照仍无历史。新旧混合场面出现旧ready后，`coverage_complete=false`，查询返回None而非零。晚引入快照也不能证明本回合此前历史。当前全局覆盖位不能认证所有真实Printemps生产者已覆盖；非Printemps旧ready同样使其未知，不能擅自按来源过滤后将未知解释为零。

原生花陽SQL验证先支付来源Wait、再独立选择其他非Printemps目标；不是把目标夹带为费用。原生Baton使PR穂乃果先进入控室再产生离场待机，旧操作可执行，但v1来源捕获明确拒绝，不能用当前裸ID或返回后的新卡面补旧来源。费用路径、初始离场来源/LKI、限定来源的覆盖证明需各自独立有限原型审计。

`PL!-pb2-010:1`仍manual/blocked，原因`printemps_member_ready_target_object_provenance_unmodeled`。本卡要求复原的来源为Printemps，不要求目标单位也是Printemps；不复用作品级布尔标志计人数，不半支持消费者。

## 证据与验收范围

42专项包含24种真实SQL：双方五种候补情形10、新旧快照2、四种来源干涉乘双方8、花陽费用两角色2、PR离场来源两角色2。断言区域互斥、引用存在、输入不变及Replay逐项相等。CONTROL和合成目标仅测试构造，不是生产日志或正式卡能力。

四AI版本在双方角色实际提交0至1合法选择，隐藏实例/卡名/卡号替换不改决定或输入；完整双视角保护手牌、牌库和隐藏来源。两项原生UI保护有/无来源卡面下显式合法目标提交，不出现非候补按钮，不自动代选。无新产品UI或自动图文，不把旧301图文当本卡新增审查。

官方公开FAQ实际GET282条、SHA256`030d275272b23e2c8682a8851ecc345f95302dae3a70aaccc6b70dd54689cea3`，存`official-qa.json`。Q178/Q179支持另一张Printemps Live实际Wait→Active，不冒充本卡专属FAQ；本文目标筛选来自卡文直接限定。固定PDF1.3.2.1、4.1.4、4.5.5.2、9.6.2.4.2、9.7.7、9.11.1、9.12.2与上一底座依据一致。工具未能读取卡页不代表官网不可用，未命中不代表FAQ不存在。

最终同源码control/registry/backend/web、门禁后pre-push、原30牌组冻结的真实运行编号、源码指纹、统计及提交见`logs/printemps-producer-coverage-20261027/final-acceptance.md`。未完成检查不冒充绿色，未变化池不虚报新技能覆盖。本轮不push/publish、新PR、合并部署、主机或其他项目操作。
