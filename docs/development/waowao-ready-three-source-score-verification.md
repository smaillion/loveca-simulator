# WAO-WAO复原与原Live得分

有限任务 `printemps-waowao-ready-three-source-score-audit` 精确审计 PL!-pb1-028:1。完整卡文“【ライブ開始時】自分のステージにいる『Printemps』のメンバーをアクティブにする。これによりウェイト状態のメンバーが3人以上アクティブ状態になったとき、このカードのスコアを＋１する。”，revision 437，SHA-256 `2079004eee0c3c29da064a8859bd918c283872063c845f240311f8b9120e9ff5`。直接官方Q178允许复原多名，Q179明确原本Active不计实际Wait到Active；本轮FAQ响应及原登记见ignored验收记录。

旧登记用通用 `modify_score`：原生SQL证明实际三人复原后形成全局score补正，而非仅来源Live；来源离场时也仍生成全局补正。旧快照与Replay保留历史行为，不称其正确；正式批次在完整修复验收前不发布。

新快照按完整原文、卡号、revision和hash精确绑定 `ready_member_with_provenance_v1` 与 `gain_source_score_if_three_readied_printemps`。前者只处理本人当前顶层Printemps成员并记录实际Wait到Active及原对象；后者仅当本次实际复原至少三人且原来源Live仍在Live Area时，给该原Live添加1点分数，不改变全局或其他Live。原来源离区不取消待机及复原，但旧对象或同ID返回的新对象不获得加分；已得分后移区清理。正文没有期限，依据综合规则9.2.1.2使用game期限，实际移区另依4.1.4视为新对象；不把期限与对象身份混为一谈。旧通用操作及旧Replay不追改。

候选和静态shape固定无费用、无选择、强制Live开始/每Live一次，不接受其他动作或条件。来源LKI、真实invocation/effect/玩家/游戏回合及原Live证据在执行前严格核对，即使Stage已空也不猜旧对象。专项覆盖双方0至3次实际复原、已Active、来源离场返回及得分后移区、两个来源依次结算、旧快照SQL Replay、非法原子性、四AI及玩家/provider构造隐私。CONTROL及图文中的来源移动为明确测试构造，不是完整正式对局；未联网provider。

中日结果说明与原生选择只显示实际复原人数及原Live得分，不复活隐藏来源。精确专项、图文、SQL、同牌组冻结、最终全部门禁及状态以ignored `logs/waowao-ready-three-20261028/final-acceptance.md` 为准；没有全部验收前不得称完成。只改本卡登记，不算manual晋级，消费者及其他blocked保持。
