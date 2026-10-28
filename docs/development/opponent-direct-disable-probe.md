# 对手直接 Live 成功能力无效化原型

新增未登记 `disable_opponent_direct_live_success_v1`，只允许明确的强制 Live 开始、本人原 Stage Member 来源、选择一名对手当前公开顶层 Member、Live 期限及单一操作。卡号必须为 `UNREGISTERED-`；不绑定 `PL!-pb2-003:1`。此前其他卡 Q106 关于重复无效的回答仅作边界参考，不称本卡专属裁定。

服务器在真实入队时保存来源 invocation、effect、实例、所有者与严格游戏回合；客户端不能提交来源证明、额外费用或分支。结算仅针对所选目标当前可识别、属于该卡自身的直接 `live_succeeded` effect ID 建立逐效果标记，第一次与已有标记分开；事件的 `known_direct_newly_disabled` 是已识别的直接能力数量，`coverage_complete` 始终为 `false`，因此零不代表目标没有获得、继承或其他未知能力。操作不能串联后续奖励，也不能作用于已入队的成功能力，不把该原型当作正式卡完整覆盖。

目标标记保存在目标所有者下；旧来源自身无效操作和旧 JSON/Replay 不改。目标离区时无论旧清理策略是否启用，该原型标记都清除，同 ID 返回不继承；场内 Position 保留。Live 结束按既有期限清理。来源离场或返回不重新读取新对象以伪造旧来源；内部快照在玩家及 provider 构造投影剥离，隐藏来源引用不授权当前隐藏卡面。

双方 SQL Replay 验证实际成功能力不入队、Live 结束、空对手场、重复、未知引用、非法目标、来源受控隐藏/返回和目标对象变化；四 AI、隐藏身份不变、玩家/provider 构造隐私与原生 UI 仅针对原型。CONTROL 为显式测试构造，不是完整对局或自然中断，provider 未联网。正式 `PL!-pb2-003:1` 仍 manual，获得/继承、完整目标覆盖及后续 Heart 仍需独立建模，其他 blocked 不恢复。最终专项、SQL、同牌组冻结与全部门禁见 ignored `logs/opponent-direct-disable-20261028/final-acceptance.md`。
