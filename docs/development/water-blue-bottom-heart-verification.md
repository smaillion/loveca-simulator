# WATER BLUE NEW WORLD：控室洗回与所选成员粉Heart

2026-10-28 JST。有限任务`live-start-waiting-six-shuffle-bottom-selected-aqours-heart`，固定分支和工作树，不新建分支。完整门禁、实际提交和最后状态见[最终验收记录](../../logs/water-blue-bottom-heart-20261027/final-acceptance.md)；本报告的定向绿色不代替全部profiles。

## 精确绑定

- `PL!S-cl1-013:1`，WATER BLUE NEW WORLD，Live score10，revision972。
- 完整文本hash：`92ac3f09ae0da6ba76aff0bd884b762dbd40af9410853a08c4ae05d8abe9576c`。
- 全文：`【ライブ開始時】自分の控え室にある、ブレードハートを持たない『Aqours』のメンバーカードを6枚まで選ぶ。それらをシャッフルし、デッキの一番下に置く。ライブ終了時まで、自分のステージにいる『Aqours』のメンバー1人は、これによりデッキの下に置いたカード2枚につき、【heart05】【heart05】を得る。`
- 先从原生Live开始复现旧mandatory manual，`logs/water-blue-bottom-heart-20261027/native-red.xml`保留。旧seed18027与其他待机共同阻塞，不是唯一阻塞。

## 规则依据与推导

官方公开[FAQ API](https://llofficial-cardgame.com/manage/rule-qa/list?per_page=5000&status=published)本轮实读282条，原响应`official-qa.json`的SHA256为`030d275272b23e2c8682a8851ecc345f95302dae3a70aaccc6b70dd54689cea3`。未检出本卡条目不表示不存在专属FAQ，工具不能读取不等于官网不可用。只用官方资料，不用第三方攻略。

固定PDF `LoveLiveTCG_cr_1.06_260428.pdf` SHA256 `c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。1.3.5.1/9.6.3.1.1允许0至6；5.5.1随机化指定组，5.5.1.2明确零或一张仍算洗牌。Q14支持双方不可预测顺序，Q112明确ALL/得分/抽牌等特殊图标也属于Blade Heart。普通或任何特殊Blade Heart都排除，不能只检查颜色图标。

后续金额为`floor(实际放回数/2)*2`。0/1张产生零补正，结合1.3.2.2零值动作不执行，省略零加成的选人；2至6张有合法Aqours顶层成员时必须选一人。无合法Stage目标仍执行前面的洗回，之后按1.3.2/9.6.3.1.3可能范围结束。这是正文结合通则的有限推导，不冒充本卡专属FAQ或完整人工裁定。

10.2.2.1及Q53/Q267保护空库立即普通刷新；非空牌库不预混控室。若结算开始已空库，先刷新，原控室牌已回库，不再把已不存在的旧候补选回。4.1.4、9.7.7分别约束新对象和来源离场后的待机，不取消该能力。

## 受限实现

新`public_water_blue_bottom_heart`和`shuffle_waiting_aqours_for_selected_heart`只接受固定强制Live开始/每Live一次/无费用/Live期限/原文两步快照，generator核对卡号、全文、revision和hash。初选只能本人控室Member、work=`love_live_sunshine`且无任何Blade Heart，0至6张，不限同名；重复、超量、非候补、他人或额外参数原子拒绝。

选中集合先按公开控室顺序规范化，再调用既有确定性随机洗牌器；接在原牌库尾牌之后，不洗整库，不把请求排序冒充洗牌。待机只保存实际数量及合法公开卡面历史，不发布洗后顺序。后续只选本人当前Stage的Aqours顶层Member，附属、对手和其他作品排除，Wait合法。选择期间禁止人工替换父能力。

粉Heart只加给该原Member对象，至Live结束；来源Live离场、回手牌/未知牌库、同ID返回不取消待机。受益Member离场清理，同ID返回不继承；Stage位置移动保留。新marker带自身`original_selected_water_blue_member` policy，旧空离场policy下也限定清理新marker，不追改旧modifier。旧amount_source、随机、通用选牌和manual快照Replay保留。默认AI、Card/SQL schema和隐私投影不改，不提升reviewed。

## 定向证据

78专项含31种SQL：0/1/2/5/6乘双方角色10、空库2、Stage目标3、原生CONTROL来源干涉8、受益对象离场/返回/换位乘新旧离场policy6、真实Live结束1、旧manual1。所有构造区域互斥。CONTROL只是测试构造，不是正式卡能力或生产日志。

四AI v0/v1/v1.1/v1.2在双方角色实际提交初选与后续目标；隐藏牌库/手牌实例及身份替换不影响动作，不改输入。完整双视角保留公开选择历史，但洗后当前牌库卡面和顺序仍隐藏，未选尾牌/双方手牌不泄露。139项目标/旧多玩家来源隐私/全局契约先通过，补精确身份反向测试后最终全量另验。

7原生UI覆盖0/2/6张、无来源卡面的严格单一受益人及0/1/6结果中日显示；没有洗后排序控件。276图文为238动态/38契约，本卡新增5种数量场景，只是局部状态转换，不冒充完整对局或人工审查。独立前端曾遗漏工作区TEMP导致权限错误、未开始测试；正确TEMP/TMP后7项通过。初期SQL测试误从第二步结果取第一步事件，已改为分别断言两次真实结果，不改产品规则。首次全量164817的前端单测通过、构建发现新夹具动态卡牌键缺少MatchState类型，已补类型后重新checkpoint执行全部四组；不复用该旧绿色。

registry结构化diff仅本段，933/1212（76.98%）、279manual；manifest重生成，不做无关条目格式变更。候选工件最初误包装为object被CLI拒绝，改为要求的数组后正式登记；当时提前启动的中间freeze已停止，`frozen-30/`不是最终依据。

## 同牌组三十局

最终目录`logs/water-blue-bottom-heart-20261027/frozen-30-registered/`，seed18000至18029、v1.2/block/max500；与上一轮30副provenance逐项相同。应用诊断指纹`4198617d013e7bbcf40400fca54000f451686c76da366278d3c96b8c9e16f937`与当前应用、provenance和全部30条摘要一致，30Replay真，证据`evidence-binding.json`。完整门禁指纹范围不同，不混用。

仍19正式完赛/11人工停止，225/225可执行完成，非法/runtime/Replay/错误skip为0。比前轮222/224完成多3，本卡1次，另2次是推进后的既有待机，不能全归本卡。本卡seed18027从第2回合40动作推进到45动作、Live0:0，停在`PL!S-cl1-011:1`。`seed18027-detail.json`有界复跑摘要与冻结逐项相同，原事件确认returned_count=0、heart_amount=0、target=null；不是从入队推测完成，也不是人工分支。随机没有覆盖非零洗回或粉Heart加成，正条件只在专项/SQL/图文验证。不称全池双方Live长局、策略或beta通过。

## 发布边界

本切片只在本地验收提交，不push/publish。PR55已有HEAD91e48d3只读确认OPEN/Draft、head/base未变，远程frontend/backend/API镜像构建及GitGuardian均SUCCESS；不把构建当部署。所有旧blocked保持，不因本实现自动requeue。合并、部署、主机或其他项目操作仍需另外批准。
