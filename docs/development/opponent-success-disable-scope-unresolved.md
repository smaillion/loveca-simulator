# 对手成员 Live 成功能力无效化边界

固定牌组 seed 18021、18024 的真实待机均指向 `PL!-pb2-003:1`，这是入队记录，不证明目标选择或后续条件已满足。实际南ことり cost9/Blade4，revision 976，完整原文 SHA-256 `46547652e34bdce62f0fabe50830721d17c6b93d1d1df63c784af214b45ecb83`。卡文要求对手 Stage 一名成员的所有 Live 成功能力无效，若因此无效则获得 `heart03`。真实卡定义和原登记保存在 ignored `logs/opponent-success-disable-20261028/inventory-before.json`。

双方实际 Live 开始均确认现有正式登记为强制人工处理，不论受控场景是否有对手目标都不能自动结算；这只是现有实现，不是官方目标资格裁定。四 AI 在该强制人工待机返回 `no_safe_ai_action`，替换对手隐藏牌 ID、名称、卡号、单位、作品和 Blade 后结果相同、输入不变。双方玩家及 API-play/agent provider 构造 context 检查隐私，未联网 provider。

现有正式 `disable_source_live_success_effects` 仅用于 `PL!S-pb1-019:1` 的来源自身。一个明确未登记的受控形态虽然能把 `target=selected` 和对手目标写入模型，实际选择对手后标记仍写在来源自身，对手未被禁用；连续两次只附加两个来源标记，不能证明有多少能力新被无效，也不实现后续 Heart。双方 SQL Replay 验证这一现象和当前 `clear_departed_card_modifiers` 策略下来源离场/同 ID 返回的标记清理；这不是正式卡行为、完整对局或对手目标离场规则证明。不得直接将该操作绑定本卡。

既有官方 FAQ 缓存中的 Q106 针对另一张卡的 Live 开始能力，指出已经无效的能力不能再次无效以满足其后续条件；它提醒需要区分实际新无效与重复标记，但不直接裁定本卡。按卡号未命中本卡 FAQ 不等于 FAQ 不存在。来源待机、对手对象身份、重复及获得/继承能力、适用期限和后续 Heart 仍需独立建模及规则核对。

本轮不改正式卡、产品逻辑、登记或旧 Replay；该卡仍 manual，其他 blocked 保持。专项、SQL、既有冻结绑定和最终门禁以 ignored `logs/opponent-success-disable-20261028/final-acceptance.md` 为准。
