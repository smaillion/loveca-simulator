# 已付名称费用的原来源 Blade 原型

新增仅允许 `UNREGISTERED-` 固定快照使用的 `gain_source_blade_for_paid_named_v1`：Live 开始时按已验证的私有名称动态费用策略选择并实际弃牌，每张支付使原来源 Stage Member 获得一 Blade 至 Live 结束。服务端分别记录触发来源和实际费用证明，绑定 invocation、effect、玩家和回合；来源离区或同 ID 返回不继承旧对象加成，已得补正随来源离区或 Live 结束清理。场内换位保持原对象。

本原型不绑定正式 `LL-bp2-001:3` 或其他正式登记，不宣称整卡修复。正式卡旧快照在双方受控来源离区或同 ID 返回后仍生成原 ID 的 Blade 补正，详见 ignored 证据；名称匹配及费用上限的其他已知问题见 [审计](./ll-bp2-composite-cost-unresolved.md)。旧 Blade 操作、旧 JSON/Replay、卡库与 SQL schema 不改。受控来源移动不是完整对局或自然中断，provider 未联网；四 AI 实际行为、SQL、UI 及固定牌组冻结的范围和完整门禁见 ignored 验收。
