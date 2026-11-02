# 津島善子：费用7 Baton后抽二弃一

2026-10-28 JST。有限任务`onplay-cost7-baton-draw-two-discard-one`，沿用固定分支与工作树，仅本地实现验证提交，不push/publish、新PR、合并部署或主机操作。完整门禁、提交及最终状态见[最终验收入口](../../logs/baton-cost7-draw-discard-20261027/final-acceptance.md)，定向绿色不替代全部profiles。

## 身份与依据

津島善子`PL!S-PR-045:1`，cost11/Blade4，revision1218，完整文本hash`03473dd2859e177bd884e25579a92a4ae293ae9790c34af4fe4fd4d1705fc49f`。全文：`【登場】コスト7のメンバーからバトンタッチして登場した場合、カードを2枚引き、手札を1枚控え室に置く。`先从真实登场复现原mandatory manual及错误保留人工待机，两个红例见`native-red.xml`。seed18027原第6回合118动作实际停止，不从卡表猜触发。

本轮公开GET[官方FAQ API](https://llofficial-cardgame.com/manage/rule-qa/list?per_page=5000&status=published)实读282条，SHA256`030d275272b23e2c8682a8851ecc345f95302dae3a70aaccc6b70dd54689cea3`，保存`official-qa.json`。Q24说明先指定区域、移出Baton成员、按费用差支付再登场；Q25允许同费用或较低费用Baton且不多付Energy。Q87支持同回合不同合法区域分别Baton；Q134允许Wait成员Baton，新成员Active。Q119/Q120支持正文条件在结算时处理，不冒充本卡专属FAQ；未检出本卡号不代表FAQ不存在，web不可读不等于官网不可用。

固定PDF1.06的2.6.1区分成员卡费用，9.6.2.3.1/9.6.2.3.2为登场支付及Baton减付，9.6.2.4.2处理正文，9.11.1保留离开Member Area的最后信息；9.7.7保护来源离场后待机。1.3.2按可能范围执行，10.2.1/10.2.2.1/10.2.3要求普通空库刷新。费用卡信息与仅在登场支付时少付Energy的reduce_play_cost不同；当前模型没有另一个任意卡面费用替换执行器，不凭支付数反推原成员费用。这是通则结合卡文与已建模支付语义的限定推导，不冒充完整人工裁定。

## 限定快照

新`private_baton_cost7_draw2_discard1`仅固定强制登场/无费用/无额外条件步骤，复用draw_card2与discard_from_hand。generator核对全文/revision/hash，validator拒绝改数量、对象、时点、选择范围及附加动作。原手牌登场只有该新policy才捕获实际Baton原Member费用`baton_replaced_member_cost_v1`，并在新invocation保存`baton_play_turn_v1`；旧快照不添加这些JSON键。

首次结算检查本次登场事实：真实used_baton_touch、原对象费用严格整数7、来源实例与真实回合一致。不是当前Stage费用，也不是支付差额、旧同回合Baton或客户端自报费用。来源或原被替换成员离场、进入手牌/未知牌库、同ID返回或场内换位，不改本次Baton事实；非Baton或费用6/8不抽不弃。单条失败条件安全自动结束，多条兄弟待机仍由玩家选择处理顺序。

正条件先本人抽二，然后从当前本人手牌严格弃一。初始提交不能内联代选，抽牌后锁定父能力，人工操作不能插入重抽或换对象；当前可执行范围不足时按1.3.2处理，零手牌正常结束，不强迫虚构卡牌。每次抽空及弃牌后空库均只在新policy显式普通刷新，旧draw/discard/manual快照不追改。0/1张短库可经刷新继续，实际抽到多少和实际弃多少分别记录。

额外费用、分支、颜色、非布尔accepted、拒绝必选、重复/超量/非候补、错玩家、过期revision与重复提交原子拒绝。兼容UI空energy数组和ai_decision记录字段。来源进入未知牌库不复活卡面，抽到的手牌只给本人，弃后刷新回库不因公开历史永久授权当前card map。默认AI、Card/SQL表结构与隐私投影不改；新增是既有invocation JSON中的限定历史，不是表迁移。

## 真实验收

94专项含43种SQL：双方角色/非Baton和6-7-8十二种、来源与原Baton成员五种干涉乘双方角色二十种、短空库/已有手牌七种、新旧manual快照两种、两次独立原生Baton乘双方角色两种。区域互斥、引用存在、Replay逐项相同；CONTROL/TAIL和附属构造只用于测试，不是生产日志或正式卡能力。冻结费用事实的直接卡信息变更是显式状态诊断，不冒充原生费用修改能力。

原生费用支付补正、旧历史不可复用、非法输入及严格快照另有断言。四AI v0/v1/v1.1/v1.2在双方角色实际完成初始抽牌与后续弃牌，隐藏实例/卡名/卡号替换不改变决定、不改输入；完整双视角保护抽牌中及弃牌后的当前隐藏区。155项目标/旧Baton/成员历史/图文及全局候选契约通过。296图文为258动态/38契约，新五场景；6原生UI含失败/0-2实际抽数的中日结果及缺来源卡面的两步提交，不冒充完整对局或人工审查，也未声称语义provider联网验收。

最初实现错误假定旧member_played元数据自带turn，实际没有；已只在新policy添加专用回合字段，不修改旧记录。审查补上弃牌后空库立即刷新、严格accepted类型，并将图文构造来源费用对齐实际cost11后重新绑定；前两次冻结目录是中间源码，不作最终证据。注册工具造成的无关key顺序变化机械恢复，结构化diff仅本段，manifest重生成。登记936/1212（77.23%）、276manual，不提升reviewed。

## 同牌组诊断

最终目录`logs/baton-cost7-draw-discard-20261027/frozen-30-compatible-final/`，原30牌组与上轮provenance逐项相同，seed18000–18029、v1.2/block/max500。应用诊断指纹`f3f06681e25774055a6bb4845ae4d626dc6a744d078c0b2e77bd8fdb6ac003ae`与当前src/sandbox/卡库/registry/manifest、provenance及全部30摘要一致，`evidence-binding.json`保留，和完整门禁指纹范围不同。

仍19正式完赛/11人工停止，246/246可执行完成，非法/runtime/Replay/错误skip0、30Replay真。比232多完成14，本卡2、其余12是推进后的既有能力，不全归本卡。seed18027第6回合118动作推进至第10回合222动作、Live2:2，停两条LL-bp6-001:2与一条PL!S-PR-048:1共同manual，不称后者唯一阻塞。`seed18027-detail.json`有界复跑与冻结摘要完全相等；本卡两次原事件均condition_met=false、drawn_count0、discarded_count0，不称随机正条件抽弃覆盖。正条件在专项/SQL/图文验证，不代替冻结结果，不称完赛率、全池双方Live长局、策略或beta达标。

最终checkpoint后重新执行全部required profiles及门禁后pre-push；完整结果、源码指纹和提交保存在验收入口，最后check后不改版本化源码或文档。其他blocked、44/6 dirty工作树、stash与ignored证据保持，不自动requeue。应用指纹不变不重复冻结。
