# 三人卡名称候选与 Blade Heart 色槽盘点

`LL-bp6-001:2` 完整双段文本 revision 59、SHA256 `cf58746e81720b3db7a0dc378b36dd4b8fb60e88c63ab1a9d97ef0ebd5691331`，仍为 manual。固定综合规则 1.06 的 2.3.2.1/2.3.2.2 及缓存 Q62 支持组合名与部分名；[Q246](https://llofficial-cardgame.com/cardlist/searchresults/?cardno=LL-bp6-001-R%EF%BC%8B&faq=) 本卡示例仅核对基本 Heart 颜色去重，不单凭此推断 Blade Heart。

当前卡库按规范化的三个指定名称作部分字符串盘点，共 100 条：56 Member、44 Energy，其中 6 条名称含组合符号；29 条具有 Blade Heart 色槽，1 条色槽不在基本 Heart 中。这个盘点不是完整费用资格或合法牌组判定。真实 `PL!-bp3-012` 南ことり基本 Heart 为空，Blade Heart 为 `heart03`；`PL!-bp6-003` 基本 Heart 包含 `heart01`、`heart03`、`heart06`，Blade Heart 为 `heart03`。

双方受控 Live 开始测试将上述真实卡面放入手牌，并以未登记、仅基本 Heart 颜色并集原型支付：前者产生零种基本颜色，后者产生三种；四份 SQL Replay 可重放。这仅证明受限原型当前行为，不证明本卡是否计入 Blade Heart、零枚费用、来源原对象或完整规则。卡面和 Stage 为测试构造，不称完整对局或自然触发；未新增 AI/provider 联网验证。正式第二段及其他 blocked 保持，产品、卡库、registry、默认 AI 和旧 Replay 不改。完整门禁与提交状态以 ignored 验收记录为准。
