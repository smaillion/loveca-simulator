# 想いよひとつになれ：共同Heart颜色与原Yell回收

2026-10-28 JST。固定分支`codex/continuous-development`及既有工作树，本切片仅本地实现、验收与提交，不push/publish、合并或部署。完整同源码门禁和最终提交状态见[最终验收记录](../../logs/aqours-shared-heart-yell-20261027/final-acceptance.md)，专项和图文不代替全部profiles或人工完整裁定。

## 精确身份

- `PL!S-cl1-011:1`，想いよひとつになれ，Live score3，revision970。
- 全文hash：`b56ab4b40570e38e542e3d9613235c13e595d323ea45853c4b94a54fc874a806`。
- 全文：`【ライブ成功時】自分のステージに『Aqours』のメンバーが3人以上おり、かつ、それらのメンバーが同じ色のハートを持つ場合、エールにより公開された自分のカードの中から、その色のハートを持つ『Aqours』のメンバーカード1枚を手札に加える。`
- 改动前原生Live成功产生mandatory manual，`logs/aqours-shared-heart-yell-20261027/native-red.xml`保留；初始断言不存在的selection_policy真实失败。原冻结seed18027第2回合45动作也实际因本卡停止。

## 官方依据

本轮实际读取[官方FAQ API](https://llofficial-cardgame.com/manage/rule-qa/list?per_page=5000&status=published)282条，`official-qa.json`的SHA256为`030d275272b23e2c8682a8851ecc345f95302dae3a70aaccc6b70dd54689cea3`。未命中本卡条目不等于不存在专属FAQ；Web工具不能读取不等于官网不可用。首次本地检索因空card_number字段报错，原响应已完整保存，之后按结构化空值处理重新检索，不影响取得的官方正文。

Q149直接说明另一张Stage成员Heart总数卡所称“成员持有Heart”为基本Heart；Q124直接说明另一张渡辺曜检索卡不参照Blade Heart，只看基本Heart。固定PDF2.9.1–3定义Member Heart和多色持有，9.9.1.1–5要求按持续效果取当前信息。结合本卡正文，Stage检查使用既有有效Member Heart计算（基础栏、替换、临时和常时修正），不加入Blade Heart或Yell得到的ALL；公开Yell Member不在Stage，不凭其Blade Heart或Live必要Heart代替基本Heart。这是通则与其他卡明确用语结合的有限推导，不冒充本卡专属FAQ。

固定PDF `LoveLiveTCG_cr_1.06_260428.pdf` SHA256 `c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`，已视觉核对第2页信息栏与图标。2.1.3说明图标同色，不据此合并不同信息栏。Q119/Q120及9.6.2.4.2支持正文条件结算时检查；8.4.4/8.4.5/11.6.2界定Live成功待机，9.7.7保护来源离场后继续处理，4.1.4保护移区新对象，9.6.3.1/9.6.3.1.3要求有公开合法候补必选一张、无候补按可能范围结束。

共同颜色是三名当前顶层Aqours Member各自正数Heart集合的交集，不是并集；同名实体照常计数，附属不计人数，Wait仍持有Heart。多共同色时，候补只需持有交集中任一颜色，选卡即满足一个共同颜色见证；本效果没有后续依赖所选颜色的动作，因此不额外发明颜色选择步骤。零、两名或没有共同色均不回收，不涉及旧空Stage全称条件裁定。

## 新快照与旧兼容

新`public_aqours_shared_heart_yell_one`只接受固定强制Live成功/每Live一次/无费用条件额外动作/本人公开原Yell的Aqours Member一张，复用既有`move_selected_to_hand`，不新增通用操作。generator逐项限定卡号、全文、revision、hash。正文条件不是trigger filter，不冻结触发时场面；真正提交时重新检查当前三名成员和候补。有候补必须一张，条件失败或无候补允许零张正常完成，不记错误skip，不让对手代选。

仅新policy显式启用既有`remaining_yell_instance_ids`，并与当前Resolution Area取交集；移出的原对象不再候选，同ID回到公开区不恢复原Yell资格，同区域no-op保留。不能把整个Resolution Area、其他玩家或上一批公开牌当本次Yell；缺少新快照追踪时原子拒绝，不猜历史。旧普通Yell、旧入底policy和manual快照不追改，Card/SQL schema及默认AI不改。

来源Live回手牌/未知牌库、同ID返回或仍在Live区不取消能力，不依赖来源最后位置。回收只入所有者手牌，原公开选择卡面可保留为事件历史，但不授权对手当前手牌card map；隐藏来源不因新事件重新获得卡面。错误玩家、重复/过量/非候补/附属/手牌/额外费用和颜色参数、过期revision或重复提交均原子拒绝。保留既有空energy_instance_ids和ai_decision记录接口，不把记录字段解释成操作。

## 定向验证

96专项含38种SQL：双方九种人数/作品/方向/共同色/无候补场面18、原生CONTROL来源干涉8、正文条件变化4、原Yell对象在成功前或待机后离区/返回/同区6、完整Performance→Yell新旧快照2。构造场面区域互斥；初期夹具清空顶层却残留附属、误用不存在的base_hearts类型、把人工全局Heart当作单体Heart已按真实模型修正，未放宽产品规则或删除保护。条件颜色改变SQL通过CONTROL换入不同基本Heart的真实对象，不冒充单体人工加Heart入口。

CONTROL只在测试构造，不是正式卡能力或生产日志。两项完整Performance→Yell测试为隔离触发在测试副本清空来源必要Heart，不冒充官方卡面条件下的完整合法对局；其余成功判定检查点保留实际来源score3和完整能力绑定。静态/临时/替换及负补正的当前Heart另有直接状态断言，四AI v0/v1/v1.1/v1.2在双方角色完成正/失败条件实际提交，隐藏实例ID/名称/卡号/Blade替换不影响动作，不改输入。新旧Yell、WATER和来源隐私关联回归及候选/图文契约均纳入最终完整检查。

5原生UI覆盖无候补零张、有候补严格一张、缺来源卡面及正条件成功/无目标和失败结果中日显示。281图文为243动态/38契约，本卡新增5种有限场景，不冒充完整对局或人工审查。图文helper最初漏导入LivePerformanceResult使五场景失败，补导入后全部281通过；当时中间freeze已停止，最终重新绑定，不能复用旧源码证据。

registry结构化diff仅本段，934/1212（77.06%）、278manual，manifest同步，不提升reviewed。新得到的Q124也明确了旧渡辺曜某一措辞边界，但该卡多取三张执行器仍是独立任务，本轮不重做或擅自晋级；其他blocked均保持。

## 冻结诊断

最终`logs/aqours-shared-heart-yell-20261027/frozen-30-final/`，原30副牌组与前轮provenance逐项相同，seed18000至18029、v1.2/block/max500。应用诊断指纹`48a6d8251334be8fd6528cfae38d8801159ae4174eaa0eb7731efbd17d020078`与当前应用、provenance和全部30摘要相同，`evidence-binding.json`保留。`frozen-30/`是图文导入修复前中间源码，不作最终依据；完整门禁指纹范围不同。

仍19正式完赛/11人工停止，228/228可执行完成，非法/runtime/Replay/错误skip0、30Replay真。本卡seed18027实际完成一次，从第2回合45动作推进到第4回合84动作、Live0:1，停在`PL!S-PR-046:1`两条共同mandatory manual。`seed18027-detail.json`有界复跑摘要与冻结逐项相同，原事件condition_met=false/shared_heart_color_slots=[]/recovered_count=0，不宣称随机正条件回收。完成数较225多3，本卡1、另2来自推进后的既有能力；不全归本卡，不称完赛率改善、全池双方Live长局/策略/beta通过。应用指纹不变不重复冻结。
