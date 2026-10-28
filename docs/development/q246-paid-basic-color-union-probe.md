# 已支付基本 Heart 颜色并集原型

新增仅允许 `UNREGISTERED-` 的固定测试快照：Live 开始时可选支付指定名称手牌零至四张，再将实际支付的已识别基本颜色去重，每色为原来源 Stage Member 增加一颗，持续至 Live 结束。零至四张和精确名称筛选是受限测试形状，不是 `LL-bp6-001` 的正式费用裁定。未知或 ALL 槽直接原子拒绝，未解释 Blade Heart；正式第二段仍 manual，已有第一段及其他登记不改。

新操作 `gain_source_heart_from_paid_basic_color_union_v1` 使用独立来源策略和服务器触发快照，绑定 invocation、effect、所有者及游戏回合；支付证明仅从实际费用路径产生，不能由客户端提供。来源离区或同 ID 返回不继承旧对象收益，已获得补正在来源离区或 Live 结束清理。已有逐卡颜色操作和旧快照 Replay 保持不变。玩家和构造 provider 上下文不投影内部来源及费用证明。

[Q246 官方卡表](https://llofficial-cardgame.com/cardlist/searchresults/?cardno=LL-bp6-001-R%EF%BC%8B&faq=) 的直接示例仅证明多张弃牌共享基本颜色时各色获得一次；不据此断言零枚支付、组合名称、Blade Heart 或整卡资格。实际完整牌面与关联边界见 [前次审计](./q246-named-cost-color-union-unresolved.md)。双方 SQL Replay、隐藏身份、四 AI 与原生 UI 测试及同牌组冻结的范围和结果见 ignored 验收；CONTROL 和合成卡不是完整对局。其他 blocked 不恢复，本地验证不等于发布。
