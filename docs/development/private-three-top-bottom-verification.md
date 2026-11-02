# 小原鞠莉：私看三张、分别排列库顶与库底

2026-10-27，固定`codex/continuous-development`本地实现，不推送、新建PR或合并部署。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP07/PL!S-bp7-008-P.png" alt="小原鞠莉 PL!S-bp7-008" width="280">

## 身份与复现

- 仅`PL!S-bp7-008:1`，完整双段revision853/hash `1de3807181773c1f9c909324ecf5885928876ce992a6ed6f4d93e2f000a63f6b`共同绑定；不是仅匹配第一句或模糊卡名。
- 第1段：`【登場】自分のデッキの上からカードを3枚見る。その中から好きな枚数を好きな順番でデッキの上に置き、残りを好きな順番でデッキの下に置く。`
- 第2段可选Live开始的底牌姓名回收仍为manual，原登记逐项不变。两类lily white未确认语义也不因此晋级。
- 原生登场红测试复现mandatory manual，见`logs/private-three-top-bottom-20261027/native-red.xml`；原冻结seed18017第4回合74动作Baton登场也实际停止于此。
- 结构化registry diff仅本段，927/1212（76.49%）、285manual；不提升人工reviewed，不冒充完整人工裁定覆盖。

## 官方依据

固定PDF `raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`，SHA256 `c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。5.7.1区分私看与公开；10.2.2.2/10.2.3规定私看数量不足时刷新，控室洗入剩余牌下。

[官方Q85/Q86/Q122](https://llofficial-cardgame.com/question/searchresults/)分别支持不足数量继续查看、恰好看完整库不刷新，以及查看并不等于移出牌库。不是本卡专属FAQ；结合本卡全文处理两组任意顺序，不将私看规则扩大为同时公开四张裁定。公开API本轮实读282条，原响应`logs/private-three-top-bottom-20261027/official-qa.json`，SHA256 `030d275272b23e2c8682a8851ecc345f95302dae3a70aaccc6b70dd54689cea3`。未命中本卡条目不等于不存在专属FAQ。

## 有限实现

新增受限snapshot策略`private_three_top_bottom_order`，只允许强制登场、固定私看三张、无费用/条件/后续额外能力。复用现有私看引擎：检查区只是内部暂存，恰好三张时不因内部暂存误刷新；查看不足则先将控室刷新接在剩余牌下，无牌可补时只处理实际牌。

选中组通过`ordered_card_instance_ids`按从上至下放库顶，未选中组必须另传`bottom_ordered_card_instance_ids`按从上至下接在原尾牌之后。两组并集必须恰好为本次查看对象，不能重复、遗漏、混入原尾牌/他方牌。非法Action原子拒绝，原状态不改；原生inspection期间禁止manual偷换对象。

旧无新policy的私看/reorder仍按原剩余顺序处理，不读取新库底字段；旧amount_source、固定私看、manual快照与原始SQL Replay不变。来源登场后离场、回手牌、同ID返回、进入牌库或场内换位均不取消已待机的私看排序，没有对新来源对象加成。

四AI只增加新类型提交字段，不改默认版本/策略；旧沙盒策略和语义代理hint/example也给出合法两组提交。本人能看到实际私看对象，对手不能；排序完成后双方当前card map均不重新授权未知牌库身份。双方手牌、未看尾牌仍脱敏，原始Replay保留完整审计信息。

原生UI复用选牌/库顶箭头，新增独立库底箭头及中日标签；已选牌取消后回到库底组，完整传递两组顺序。不将私看结果公开或当作取得/弃牌处理。Card/SQL schema及默认AI不改。

## 验收证据

- `tests/test_private_three_top_bottom.py`88专项：三张的六种排列乘四种分组、短空库/刷新、精确全文绑定、非法/重复/遗漏/非候补/他方提交原子性、严格snapshot、两种所有者、四AI隐藏实例/身份替换不变及不改输入。
- 14种SQL组合：新结构化、旧manual、旧结构化各一，来源四种干涉，短库七种。CONTROL只为原生登场后的测试能力干涉，不是正式卡能力或生产日志。完整Replay与最终状态一致。
- 语义代理完整上下文保护尾牌/对手身份，且能产生新类型合法提交示例；旧沙盒策略实际提交可执行。原生Action双视角完整响应覆盖查看前/查看中/排列后，不只检查候选字段。
- 89项专项加图文契约通过；此前345项目标/关联（79专项时点）通过，新增断言随后独立重跑，不将旧结果拼成最终门禁。
- 全量真实发现旧费用结果分支用SimpleNamespace表示临时私看配置，没有selection_policy字段；已改用兼容读取，不改变旧分支对象或放宽校验。112项新专项加旧费用分支回归通过；095208旧全量因该真实回归主动停止，最终必须全部profiles重新执行。
- 6项原生UI交互/中日集成，269前端测试通过；242图文为204动态/38契约，本卡新增四种分组动态场景，不冒充人工裁定。
- 早期旧manual空adjustment、第二所有者沿用第一方Energy夹具均已修正后重跑；未放宽引擎规则迁就测试。登记工具引起的无关键排序已恢复，结构化核对只有目标effect变化。
- 审查发现旧排序栏nowrap会影响新增库底长卡名，手机截图又发现候选长英文名截断；已仅为新策略两组排序控件及候选卡增加有界换行，旧面板样式不改。1280/390宽度受控Playwright截图与实际分组/重排/提交、卡图加载验证保存在`ui-layout.json`及`ui-*.png`，图片是官方卡图替身，不冒充真实对局截图。主动停止094635/094845旧检查，新checkpoint后全部profiles重新执行，不能复用旧结果。CSS/文档变化不改应用诊断指纹，不重复冻结池。
- 最终checkpoint后使用协调器执行完整control/registry/backend/web，真实完整源码指纹/日志以`.tmp/development-loop/runs/*/result.json`为准；全部通过后才本地commit/complete，检查后不再改源码，不拼接旧绿色证据。

## 冻结30局

最终证据`logs/private-three-top-bottom-20261027/frozen-30-compatible-final/`；`frozen-30/`及`frozen-30-final/`分别为补旧沙盒/语义示例前、修复旧分支临时配置兼容前的中间指纹，不能作为最终源码依据。原30牌组provenance逐项一致，seed18000–18029、v1.2/block/max500，最终诊断指纹`3915564c6704506f22f5df5503f063d66d243a6cdb096505d4d0b5108b2381e5`与当前源码、provenance及全部30条摘要一致。

正式完赛14→15、人工停止16→15，208/210可执行完成、两项随其他manual待机保留，非法/runtime/Replay/错误skip均0，30局Replay全部通过。增加的七项完成中本卡一项，其余六项为推进后的既有能力，不全算成本卡。

seed18017本卡实际完成一次，推进至第6回合137动作，成功Live0:3；败方无Live，不称双方Live长局或beta达标。`seed18017-detail.json`有界复跑与冻结摘要逐项相同，实际私看三张、选择三张按新顺序放库顶、库底零张；不能声称随机局覆盖了分拆/全放底，后两者仅在专项/SQL/图文验证。源码诊断指纹不变不重复跑池。

下一有限独立任务：seed18005实际manual的`PL!HS-pb1-014:1`，先核对“仅みらくらぱーく！”条件与对手正面Position Change，来源离场/前方参照不明确则保留unresolved。PR54已获批准合并上线；后续PR目标仍待明确批准，本批不推送、不新建PR、不合并部署。
