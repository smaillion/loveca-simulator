# 宮下愛：异名DiverDiva与Energy双分支

2026-10-27，固定`codex/continuous-development`及工作树，仅本地实现验证，不推送、不改后续PR目标、不合并或部署。

## 最终验收入口

完整四组profiles、源码指纹、pre-push、本地提交与冻结30局的实际结果见[最终验收记录](../../logs/diverdiva-energy-choice-20261027/final-acceptance.md)。专项和图文不是完整人工裁定；最终checkpoint后不修改源码/版本化文档再复用旧检查。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP07/PL!N-bp7-005-P.png" alt="宮下愛 PL!N-bp7-005" width="220">

## 精确身份与官方依据

仅`PL!N-bp7-005:1`，revision868/hash`ad5311610df13efbe44297694127ea7740391a12f280bc947c634172cb6145fb`，宮下愛，cost11/Blade3，unit_key=`diverdiva`，work_key=`nijigasaki`。生成器匹配完整日文全文，不靠关键词宽泛匹配。原生登场红测试先复现原能力仍为mandatory manual，保留`logs/diverdiva-energy-choice-20261027/native-red.xml`。

> 【登場】自分のステージに名前の異なる『DiverDiva』のメンバーが2人いる場合、以下から1つを選ぶ。 ・エネルギーを2枚アクティブにする。 ・自分のエネルギーデッキから、エネルギーカード1枚を自分のステージにいる『虹ヶ咲』のメンバーの下に置く。

实读[官方公开FAQ接口](https://llofficial-cardgame.com/manage/rule-qa/list?per_page=5000&status=published)282条，响应SHA256`030d275272b23e2c8682a8851ecc345f95302dae3a70aaccc6b70dd54689cea3`，原文保存`logs/diverdiva-energy-choice-20261027/official-qa.json`。本次没有命中本卡号，不声称专属FAQ不存在；只使用官方资料。

- 固定PDF`raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`的9.6.2.4.2及Q119/Q120支持正文条件在实际结算时判断，不能触发时过滤或锁定；Q96/Q103的另一卡条件也按每次结算判断。
- PDF2.3.2.1/Q62确认复合名称；Q225/Q210说明一个复合名称实体仍算一个Member。Q208说明其可以按另一个名字参照以满足异名条件。本实现要求两张实际顶层Member，再为两实体分配不同名字，不以单张复合名称虚增人数；这些不是本卡专属FAQ。
- PDF1.3.2要求按可能范围执行无费用效果；复原数量不足两张时必须复原实际可用数量，零张不变。两个固定分支不因暂时没有可执行对象而改写成其他能力或额外费用。此为结合正文的通则推导，不冒充本卡专属分支裁定。
- PDF4.5.5.1/4.5.5.2区分成员下的附属Energy与Energy Area，附属卡没有规则方向状态、不能拿来支付Energy费用；9.7.7保护来源离场后的待机。沿用现有成员离场附属清理规则，不把Energy Deck先放到Energy Area再转移。

## 有界实现

新增精确`public_diverdiva_energy_modes`快照策略，复用原有`choose_effect_branch`流程；只接受强制登场、固定无费用两分支、没有额外条件/次数/对象变种。新`attach_energy_deck_to_selected_nijigasaki`操作只能在这个快照中使用，不能作费用。旧分支、固定数量复原和旧manual快照不追改。

1. 在首次结算时读取己方Stage顶层Member的unit与名字。至少两个实际DiverDiva实体能分别提供不同名字才成立。相同名字不同印刷不成立；一张复合名卡不算两人；附属Member不代替顶层。名字沿用既有空白规范化，并识别`＆`/`&`分隔。条件失败时不选分支、不付费、不操作牌；独立待机可原生自动完成，在多个兄弟待机时仍按玩家顺序选择该能力后结束。
2. 条件成立时由能力所有者选一个分支。复原分支只选本人当前Wait Energy，数量为`min(2,可用数量)`，不是可随意选择0至2。附属分支只选本人当前Stage上的虹ヶ咲Member，不限DiverDiva，也可选仍在场的来源本人。
3. 附属直接取本人Energy Deck中的一张Energy放到目标组下，公开实际移入的牌，不增加Energy Area、不触发Energy Area放置观察者。空Energy Deck按可能范围不移动；不误取现有Energy Area或别人的牌。沿用既有Energy Deck内部取牌约定，不向玩家暴露隐藏顺序。

分支选择后锁定父能力，不允许人工调整插入改变对象，也不能换分支、内联代选、重复/漏选/选非候补或给额外费用。保留既有UI的空`energy_instance_ids=[]`提交格式，但拒绝实际费用牌。来源离场、进入手牌/未知牌库或同ID返回不取消已待机能力；正文条件仍看结算时当前Stage，而非旧来源身份。附件跟随目标组，目标离场后回Energy Deck，不给返回的新成员对象留下附属。

## 真实验收与限制

- 84专项，含22种SQL：复原0/1/2/3可用Energy四种、附属目标/空Energy Deck六种、双方角色来源离场/返回/换位八种、正文条件变化两种、旧manual一种、目标离场附属清理一种。所有构造场面断言区域互斥。CONTROL只在测试构造中用于兄弟待机干涉，不是正式卡能力或生产日志。
- 四AI v0/v1/v1.1/v1.2在双方角色实际完成初始选择和两种分支跟进，失败条件在兄弟队列中也能无分支结束；隐藏实例ID/卡名/卡号变化不影响决定、不改输入。使用既有通用分支提交格式，没有更改默认AI版本或策略。本轮没有声称实际付费语义provider联网验收。
- 双视角完整响应不公开Energy Deck剩余牌/主牌库尾牌或来源进入未知区域后的当前卡面；真正附属的Energy才公开。不是全局隐私认证。旧cost-result分支及全局候选契约合计109项目标/关联通过，仍不能替代完整门禁。
- 266图文为228动态/38契约，新增四种受限待机场景；不冒充原生完整对局或人工裁定。6项原生UI测试保护固定分支、条件失败无选择及中日结果显示；构建验证类型，未放宽校验。
- registry结构化diff仅本段，当前931/1212（76.82%）、281manual，不提升reviewed。Card/SQL schema未改。空Stage全称真值、lily white计数、同时公开四张短库、姫芽第一段LKI和复杂重叠仍保留原blocked，不因本任务恢复。

新源码必须重新绑定并执行原30牌组、seed18000–18029、v1.2/block/max500冻结诊断。最终记录区分真实入队、完成和实际分支，不从总完成增加量推断全部由本卡造成，不以随机缺少某分支冒充全覆盖，也不声称全池双方Live长局或beta达标。
