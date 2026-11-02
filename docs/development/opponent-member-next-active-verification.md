# Guilty Night, Guilty Kiss!：对手成员下回合复原限制

2026-10-27 UTC（2026-10-28 JST），固定工作树和`codex/continuous-development`。维护者本轮明确批准“修改发布目标并新建Draft PR”；完整验收后允许推送此分支向develop创建下一份Draft，不包含合并或上线。批准前的旧检查已主动停止，policy移除已合并54编号后重新执行全部门禁，不复用旧指纹。

## 最终验收入口

完整四组profiles、源码指纹、最终pre-push、本地提交和冻结30局的实测分支见[最终验收记录](../../logs/opponent-member-next-active-20261027/final-acceptance.md)。本报告中的专项绿色不替代完整门禁；最终checkpoint后不改版本化源码或文档再复用旧检查。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP07/PL!S-bp7-025-L.png" alt="Guilty Night, Guilty Kiss! PL!S-bp7-025" width="280">

## 身份与官方依据

仅`PL!S-bp7-025:1`，Live score3，Aqours/Guilty Kiss，revision917/hash`8f3f0088db7c0001fda1fbc53680efde3f4bc6bcdccc8dde9ac0345ca80d5bc6`。生成器核对卡号、完整日文、revision及hash；原生Live成功先复现mandatory manual，`logs/opponent-member-next-active-20261027/native-red.xml`保留。

> 【ライブ成功時】以下から1つを選ぶ。 ・相手のステージにいるコスト4以下のメンバーを2人までウェイトにする。そのメンバーは次のターンのアクティブフェイズにアクティブしない。 ・カードを1枚引く。

实读[官方FAQ接口](https://llofficial-cardgame.com/manage/rule-qa/list?per_page=5000&status=published)282条，SHA256`030d275272b23e2c8682a8851ecc345f95302dae3a70aaccc6b70dd54689cea3`，保存`official-qa.json`。本次未命中本卡号，不称专属FAQ不存在。固定PDF`raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`的SHA256仍为`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。

- Q144及PDF1.3.5.1/9.6.3.1.1支持“最多两人”选择0至2人，不强制选满，也不误作费用。候补只有对方当前Stage顶层、费用不超过4的Member，附属和己方成员不能选。
- PDF1.3.2.1规定已处于某状态时不会再次发生同样的状态改变。本文没有限定Active目标，也没有“これにより”成功改变的条件，因此可参照已Wait的合法目标并保留其后续限制，但不记录新的Wait改变。这是结合正文的通则推导，不冒充本卡专属FAQ；Q137讲费用不能支付，与本无费用效果分开。
- PDF7.1.2/7.3.3/7.4.1定义游戏回合及各方Active Phase；期限为创建回合加一，不是下一次操作或最近一次本人Active。Q280以另一张Energy能力说明主动复原后再次Wait不取消指定Active不复原效果，本实现结合通则用于选中原Member，不称本卡专属FAQ。
- PDF4.1.4区分移区新对象，11.10/11.11区分场内位置移动；9.7.7保护来源离场后的待机。抽牌分支沿用正常从顶抽牌、10.2.2.1空库刷新，并在新快照抽空后显式刷新，不追改旧draw/manual快照。

## 有限实现

新增精确`public_opponent_cost4_wait_or_draw`快照和`wait_opponent_cost4_skip_next_turn_active`操作，仅强制Live成功、每Live一次、无费用/额外条件、固定两分支。不能改数量、目标、时点或作为费用，不是通用持续限制框架。

所有者先选分支：选择对手最多两名合法Member，或本人抽一张。Wait分支固定原目标对象ID，各目标在其所有者的既有ManualModifier JSON中保存明确policy及`created_turn+1`；只在指定回合本人Active时跳过目标，处理后消费。其他Member和Energy不受影响；提前主动复原再Wait仍保留，场内换位/Formation随原对象保留，离场即按新policy清理，同ID返回不继承，过期清理。即使旧`stage_departure_policy=None`也只清理本次新标记，旧flag/旧Energy与旧manual Replay不追改。

来源Live离场、进手牌/未知牌库、同ID返回或留在Live Area不取消待机；目标在结算时重新核对当前Stage。分支跟进期间人工调整不能插入换对象，错误角色/重复/超量/非候补、过期revision、内联代选、换分支及额外费用原子拒绝。兼容UI的空`energy_instance_ids=[]`，不接受实际费用。来源进入隐藏区不复活卡面；选择对象原本公开，抽到的新手牌不向对手公开。默认AI、Card/SQL schema与可见权限未改。

## 真实验证与限制

- 85专项含34种SQL：目标数量/原Wait六种，抽牌短库四种，所有者与先后攻完整跨两回合四种，目标离场/返回/未知牌库/位置/Formation乘新旧离场policy十种，CONTROL主动ready后Wait一种，双方来源四种干涉八种，旧manual一种。所有构造场面校验区域互斥及引用存在。
- 原生Live成功和真实阶段推进证明仅选中目标在下回合不复原、随后回合正常复原；显式Active检查点另测当回合/目标回合/逾期，不冒充额外原生对局。CONTROL只在测试构造中模拟干涉，不是正式卡能力或生产日志。
- 四AI v0/v1/v1.1/v1.2在双方角色完成初始选择和Wait跟进，隐藏实例ID/名称/卡号替换不改变动作、不改输入。未修改默认策略，不声称实际联网语义provider验收。
- 完整双视角保护隐藏来源及新抽手牌；旧Energy、来源隐私与全局候选契约共214项目标/关联通过。初始夹具中不存在的牌ID、人工动作名和错误事件预期已改为真实对象/接口后重跑，不放宽产品规则。
- 271图文为233动态/38契约，新增五种受限待机场景，不冒充完整对局或人工裁定；7项原生UI保护两分支、0/2目标及中日结果显示。生产构建另由完整门禁检查。
- registry结构化diff仅本段，932/1212（76.90%）、280manual，不提升reviewed。现有空Stage、lily white计数、同时公开四张短库、姫芽第一段及复杂重叠等blocked逐项保持，不自动恢复。

新源码重新跑原30牌组、seed18000–18029、v1.2/block/max500并核对诊断指纹；实测触发、完成、所选分支和是否真正进入目标Active阶段分别记录，不从总完赛数或入队次数推断正条件覆盖，不宣称全池双方Live长局、策略或beta达标。
