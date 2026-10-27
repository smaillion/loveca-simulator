# 底牌Aqours与原来源Live必要Heart

2026-10-27，仅固定`codex/continuous-development`与工作树内本地开发。不推送、不改PR目标、不合并或部署。

## 最终验收入口

最终四组profiles、源码指纹、pre-push、冻结30局绑定及本地提交结果见[验收记录](../../logs/bottom-one-aqours-requirement-20261027/final-acceptance.md)。专项和工程门禁不等同于完整人工裁定；最终checkpoint后不改源码或版本化文档再复用旧证据。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP07/PL!S-bp7-020-L.png" alt="PL!S-bp7-020" width="220">

## 身份与依据

仅处理`PL!S-bp7-020:2`，完整双段revision912/hash `2762be94925766143618a17b7a60b0cb252f776311eaf3f8198af0c49a60d046`。第2段全文：

> 【ライブ開始時】自分のデッキの下からカードを1枚控え室に置く。それが『Aqours』のメンバーカードの場合、このカードの必要ハートを【heart0】減らす。

原生Live开始先复现mandatory manual，保留`logs/bottom-one-aqours-requirement-20261027/native-red.xml`。第1段的全员Active条件继续manual，逐项不改；正式双段SQL证明两段共同待机、单独处理第2段后第1段仍保留。不能把seed18012的共同人工阻塞归为第2段唯一造成。

依据固定[官方综合规则PDF](../../raw_doc/LoveLiveTCG_cr_1.06_260428.pdf)，SHA256 `c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`：

- 2.11.2/2.11.3的图示明确灰色Heart为无色需求；本卡原需求为无色3、红1、绿2、蓝2。减少一点无色，不代替有色条件，也不赋予Member Heart。
- 9.2.1.2：没有写明期限的持续效果按本场游戏处理。因此新标记为`duration=game`，不能自行当作Live期限。4.1.4的移区新对象另行约束来源，不能因game期限而让同ID返回继承。
- 10.2.1/10.2.2.1/10.2.3：空库先正常刷新，底牌实际置控室后若空库立即刷新。非空库不预混控室，不套用私看预先补库。
- 9.7.7：来源离场不取消待机，仍置入底牌；但不存在原来源Live对象时不生成减需。
- 9.9.1.4/9.9.1.5：替换需求先于加减；颜色最低为零，不把无色负数抵扣其他颜色。

本轮实读[官方公开FAQ接口](https://llofficial-cardgame.com/manage/rule-qa/list?per_page=5000&status=published)282条，响应SHA256 `030d275272b23e2c8682a8851ecc345f95302dae3a70aaccc6b70dd54689cea3`，保存`logs/bottom-one-aqours-requirement-20261027/official-qa.json`。Q115/Q127说明先替换再加减必要Heart，Q259说明成功判定后不因后续需求变化撤销结果；这些不是本卡专属FAQ。当前检索未命中本卡，不声称专属FAQ不存在，不使用第三方攻略。

## 有界实现

新增单个受限操作`mill_bottom_one_aqours_source_requirement`和`original_live_start_bottom_aqours_requirement`。只接受强制Live开始、每Live一次、固定底一张、无费用/额外选择/条件动作、game期限。生成器精确绑定双段全文、revision与hash，只更改第2段。

实际从本人牌库底移动的Card必须同时为Member及`work_key=love_live_sunshine`；不能用unit相似、Live、库顶、旧控室或刷新后的新底牌判定。两处都空则移动零张，不生成减需。先保存实际移动Card的类型/作品结果，再进行即时刷新。

只有触发时捕获的原来源Live仍在Live Area且未离场，才给该Live添加无色需求-1。其他Live和全局需求不变。来源待机后离场仍移动底牌；同ID返回不继承，Live Area内移动仍是原对象。新标记带自身policy，离场时限定清理，即使旧`stage_departure_policy`为空；Live结束实际移区也清理，但不把game期限伪装成live期限。旧无policy的required_heart标记、通用milling与manual快照维持原Replay行为。

## 验证与限制

- 52专项，含17种SQL：短空库4、原生CONTROL来源干涉8、双方所有者2、旧manual1、正式双段共同待机1、结算后离场返回1。CONTROL只为测试构造，不是正式能力或生产日志。新夹具断言区域互斥。
- 原生Live开始验证仅原Live无色需求从3降至2；Member/Live、作品与unit区别、恰一张及刷新顺序、替换后加减、无色为零与有色不变、缺来源snapshot原子拒绝、来源同区/离场/返回及Live结束清理均有断言。
- 四AI v0/v1/v1.1/v1.2实际完成原生Live开始与独立待机；隐藏实例ID/卡名/卡号/Blade替换不变，不改输入。正式双段仍可能被第1段manual阻塞，不称整卡已自动化。
- 双视角完整响应区分已公开移动历史与刷新后的当前隐藏card map；尾牌、双方非公开手牌保持私密。262图文为224动态/38契约，新加5种有限场景，不冒充人工完整裁定。
- 4项原生UI测试核对正/负条件、空库及原来源离场的中日显示。构建曾发现摘要可空类型错误，已补空值判断，不放宽类型检查。
- 正式登记结构化diff只有`:2`，第1段/其他条目逐项不变。930/1212（76.73%）、282manual，不提升reviewed。默认AI、Card/SQL schema和隐私投影未改。

## 本轮冻结诊断

`logs/bottom-one-aqours-requirement-20261027/frozen-30/`与前轮30牌组provenance逐项相同，seed18000–18029、v1.2/block/max500。应用诊断指纹`67373d5115e12e5cf47e6c3d9b43f0e926ae22ac5f1d76e1fa43958bc95e603d`与当前源码、provenance及全部30条摘要一致，30局Replay均真。

仍17正式完赛/13人工停止，216/218可执行完成、2随其他manual待机保留；非法/runtime/Replay/错误skip为零。可执行完成比前轮多1次，来自本卡第2段，不增加完赛率。

seed18012第1回合从17推进到18动作，本卡`:2`真实完成一次，仍因`:1`人工待机而停止。有界复跑`seed18012-detail.json`摘要与冻结逐项相等，原始事件确认milled_count1、condition_met=true、source_available=true、required_heart_delta=-1；不是从入队推断正条件，也不是受控人工分支替代随机结果。这一局不覆盖所有短库或来源离场边界，后者由专项/SQL验证。

不因工程绿色宣称全池双方Live长局或beta达标。姫芽第一段LKI/同区资格、lily white计数、同时公开四张短库及复杂重叠/继承仍保留原unresolved。
